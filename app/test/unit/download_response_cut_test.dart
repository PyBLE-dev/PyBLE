// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';

import 'package:flutter/foundation.dart' show ValueNotifier;
import 'package:flutter_test/flutter_test.dart';
import 'package:pyble/ble/ble_link.dart';
import 'package:pyble/pble/conn_state.dart';
import 'package:pyble/pble/engine.dart';
import 'package:pyble/pble/fragment.dart';
import 'package:pyble/pble/frame.dart';
import 'package:pyble/pble/pble_connection.dart';
import 'package:pyble/pble/pble_constants.dart';
import 'package:pyble/pble/pble_exception.dart';

import '../support/fake_byte_transport.dart';
import '../support/pble_frames.dart';

class _HeldGetTransport extends FakeByteTransport {
  _HeldGetTransport() : super(mtu: 23);
  final StreamController<Uint8List> input =
      StreamController<Uint8List>.broadcast(sync: true);
  final Completer<PbleFrame> firstBegin = Completer<PbleFrame>();
  final Completer<void> releaseAck = Completer<void>();
  Object? writeError;

  @override
  Stream<Uint8List> get inbound => input.stream;

  @override
  Future<void> send(Uint8List packet, {required bool acknowledged}) async {
    final int before = sentFrames.length;
    await super.send(packet, acknowledged: acknowledged);
    if (sentFrames.length > before &&
        sentFrames.last.opcode == PbleOpcode.fileGetBegin.code &&
        !firstBegin.isCompleted) {
      firstBegin.complete(sentFrames.last);
      await releaseAck.future;
      if (writeError case final Object error) throw error;
    }
  }

  void deliverNow(PbleFrame frame) {
    for (final Uint8List packet in PbleFragmenter(
      mtu: mtu,
    ).fragment(encodeFrame(frame))) {
      input.add(packet);
    }
  }

  @override
  Future<void> dispose() async {
    await input.close();
    await super.dispose();
  }
}

class _Link implements BleLink {
  _Link(this.transport);
  final _HeldGetTransport transport;
  @override
  final ValueNotifier<BleLinkState> linkState = ValueNotifier<BleLinkState>(
    BleLinkState.connected,
  );
  @override
  Stream<List<int>> get inbound => transport.inbound;
  @override
  int get mtu => 23;
  @override
  Future<void> write(List<int> packet, {required bool withoutResponse}) =>
      transport.send(
        Uint8List.fromList(packet),
        acknowledged: !withoutResponse,
      );
  @override
  Future<void> disconnect() async =>
      linkState.value = BleLinkState.disconnected;
}

Future<Object> _outcome(Future<Object> value) =>
    value.then<Object>((Object v) => v, onError: (Object error) => error);
PbleFrame _cmd(PbleOpcode opcode, int id) => PbleFrame(
  type: Pble.typeCmd,
  opcode: opcode.code,
  id: id,
  payload: Uint8List(0),
);

// Dynamic invocation keeps the initial red download reproduction compilable
// before the new optional engine acceptance seam exists.
Future<PbleFrame> _withCut(
  PbleEngine engine,
  PbleFrame command,
  void Function(PbleFrame) cut, {
  Duration timeout = const Duration(seconds: 1),
}) =>
    Function.apply(
          engine.request,
          <Object>[command],
          <Symbol, Object>{#timeout: timeout, #onResponseAccepted: cut},
        )
        as Future<PbleFrame>;

void main() {
  for (final List<int> bytes in <List<int>>[
    <int>[],
    <int>[65, 66, 67],
  ]) {
    test(
      'BEGIN and ${bytes.isEmpty ? 'empty' : 'nonempty'} END before final ACK complete losslessly',
      () async {
        final _HeldGetTransport t = _HeldGetTransport();
        final PbleConnection c = PbleConnection(
          engine: PbleEngine(t),
          appName: 'test',
          appVersion: '0',
          dataTimeout: const Duration(milliseconds: 50),
        );
        addTearDown(() async {
          await c.dispose();
          await t.dispose();
        });
        final Future<Object> result = _outcome(c.getFile('/owned.py'));
        final PbleFrame begin = await t.firstBegin.future;
        t.deliverNow(
          rsp(
            PbleOpcode.fileGetBegin,
            begin.id,
            getBeginOkPayload(bytes.length),
          ),
        );
        if (bytes.isNotEmpty)
          t.deliverNow(evt(PbleOpcode.fileGetData, getDataPayload(0, bytes)));
        t.deliverNow(
          evt(PbleOpcode.fileGetEnd, getEndPayload(pbleCrc32(bytes))),
        );
        await pumpEventQueue();
        t.releaseAck.complete();
        expect(await result, Uint8List.fromList(bytes));
      },
    );
  }

  test(
    'pre-BEGIN DATA/END and wrong-opcode response never enter the download',
    () async {
      final _HeldGetTransport t = _HeldGetTransport();
      final PbleConnection c = PbleConnection(
        engine: PbleEngine(t),
        appName: 'test',
        appVersion: '0',
      );
      addTearDown(() async {
        await c.dispose();
        await t.dispose();
      });
      final Future<Object> result = _outcome(c.getFile('/owned.py'));
      final PbleFrame begin = await t.firstBegin.future;
      t.deliverNow(rsp(PbleOpcode.fileStat, begin.id, getBeginOkPayload(3)));
      t.deliverNow(
        evt(PbleOpcode.fileGetData, getDataPayload(0, <int>[9, 9, 9])),
      );
      t.deliverNow(evt(PbleOpcode.fileGetEnd, getEndPayload(0)));
      t.deliverNow(
        rsp(PbleOpcode.fileGetBegin, begin.id, getBeginOkPayload(1)),
      );
      t.deliverNow(evt(PbleOpcode.fileGetData, getDataPayload(0, <int>[7])));
      t.deliverNow(
        evt(PbleOpcode.fileGetEnd, getEndPayload(pbleCrc32(<int>[7]))),
      );
      t.releaseAck.complete();
      expect(await result, Uint8List.fromList(<int>[7]));
    },
  );

  test(
    'failed BEGIN ignores events and cannot poison a successor GET',
    () async {
      final _HeldGetTransport t = _HeldGetTransport();
      final PbleConnection c = PbleConnection(
        engine: PbleEngine(t),
        appName: 'test',
        appVersion: '0',
      );
      addTearDown(() async {
        await c.dispose();
        await t.dispose();
      });
      final Future<Object> first = _outcome(c.getFile('/missing.py'));
      final PbleFrame begin = await t.firstBegin.future;
      t.deliverNow(
        statusRsp(PbleOpcode.fileGetBegin, begin.id, PbleStatus.eNoEnt),
      );
      t.deliverNow(evt(PbleOpcode.fileGetEnd, getEndPayload(0)));
      t.releaseAck.complete();
      expect(await first, isA<ENoEnt>());
      final Future<Object> next = _outcome(c.getFile('/next.py'));
      await pumpEventQueue();
      t.deliverNow(evt(PbleOpcode.fileGetData, getDataPayload(0, <int>[9])));
      t.deliverNow(
        evt(PbleOpcode.fileGetEnd, getEndPayload(pbleCrc32(<int>[9]))),
      );
      t.deliverNow(
        rsp(
          PbleOpcode.fileGetBegin,
          t.sentFrames.last.id,
          getBeginOkPayload(0),
        ),
      );
      t.deliverNow(evt(PbleOpcode.fileGetEnd, getEndPayload(0)));
      expect(await next, isEmpty);
    },
  );

  for (final (String, PbleFrame, Type) row in <(String, PbleFrame, Type)>[
    ('short DATA', evt(PbleOpcode.fileGetData, <int>[0]), PbleFormatException),
    (
      'oversize DATA',
      evt(PbleOpcode.fileGetData, getDataPayload(0, <int>[1, 2])),
      ECrc,
    ),
    (
      'wrong DATA offset',
      evt(PbleOpcode.fileGetData, getDataPayload(1, <int>[1])),
      ECrc,
    ),
    ('short END', evt(PbleOpcode.fileGetEnd, <int>[0]), PbleFormatException),
    ('wrong END CRC', evt(PbleOpcode.fileGetEnd, getEndPayload(0x1234)), ECrc),
    ('wrong END size', evt(PbleOpcode.fileGetEnd, getEndPayload(0)), ECrc),
  ]) {
    test(
      '${row.$1} fails typed before BEGIN ACK without unobserved errors',
      () async {
        final _HeldGetTransport t = _HeldGetTransport();
        final PbleConnection c = PbleConnection(
          engine: PbleEngine(t),
          appName: 'test',
          appVersion: '0',
        );
        addTearDown(() async {
          await c.dispose();
          await t.dispose();
        });
        final Future<Object> result = _outcome(c.getFile('/owned.py'));
        final PbleFrame begin = await t.firstBegin.future;
        t.deliverNow(
          rsp(PbleOpcode.fileGetBegin, begin.id, getBeginOkPayload(1)),
        );
        t.deliverNow(row.$2);
        await pumpEventQueue(); // expose an unobserved early error before ACK
        t.releaseAck.complete();
        expect((await result).runtimeType, row.$3);
      },
    );
  }

  test(
    'malformed BEGIN fails the request before any stream is adopted',
    () async {
      final _HeldGetTransport t = _HeldGetTransport();
      final PbleConnection c = PbleConnection(
        engine: PbleEngine(t),
        appName: 'test',
        appVersion: '0',
      );
      addTearDown(() async {
        await c.dispose();
        await t.dispose();
      });
      final Future<Object> result = _outcome(c.getFile('/owned.py'));
      final PbleFrame begin = await t.firstBegin.future;
      t.deliverNow(rsp(PbleOpcode.fileGetBegin, begin.id, <int>[0]));
      t.deliverNow(evt(PbleOpcode.fileGetEnd, getEndPayload(0)));
      await pumpEventQueue();
      t.releaseAck.complete();
      expect(await result, isA<PbleFormatException>());
    },
  );

  test(
    'a write failure still rejects already validated streamed bytes',
    () async {
      final _HeldGetTransport t = _HeldGetTransport()
        ..writeError = StateError('final ACK failed');
      final PbleConnection c = PbleConnection(
        engine: PbleEngine(t),
        appName: 'test',
        appVersion: '0',
      );
      addTearDown(() async {
        await c.dispose();
        await t.dispose();
      });
      final Future<Object> result = _outcome(c.getFile('/owned.py'));
      final PbleFrame begin = await t.firstBegin.future;
      t.deliverNow(
        rsp(PbleOpcode.fileGetBegin, begin.id, getBeginOkPayload(0)),
      );
      t.deliverNow(evt(PbleOpcode.fileGetEnd, getEndPayload(0)));
      t.releaseAck.complete();
      expect(await result, same(t.writeError));
    },
  );

  testWidgets('early download watchdog is observed while final ACK is held', (
    WidgetTester tester,
  ) async {
    final _HeldGetTransport t = _HeldGetTransport();
    final PbleConnection c = PbleConnection(
      engine: PbleEngine(t),
      appName: 'test',
      appVersion: '0',
      dataTimeout: const Duration(milliseconds: 80),
    );
    final Future<Object> result = _outcome(c.getFile('/owned.py'));
    await tester.pump();
    final PbleFrame begin = t.sentFrames.single;
    t.deliverNow(rsp(PbleOpcode.fileGetBegin, begin.id, getBeginOkPayload(1)));
    await tester.pump(const Duration(milliseconds: 81));
    t.releaseAck.complete();
    await tester.pump();
    expect(await result, isA<PbleTimeoutException>());
    await c.dispose();
    await t.dispose();
  });

  test('disposal during accepted BEGIN cannot return buffered bytes', () async {
    final _HeldGetTransport t = _HeldGetTransport();
    final PbleConnection c = PbleConnection(
      engine: PbleEngine(t),
      appName: 'test',
      appVersion: '0',
    );
    final Future<Object> result = _outcome(c.getFile('/owned.py'));
    final PbleFrame begin = await t.firstBegin.future;
    t.deliverNow(rsp(PbleOpcode.fileGetBegin, begin.id, getBeginOkPayload(0)));
    t.deliverNow(evt(PbleOpcode.fileGetEnd, getEndPayload(0)));
    await c.dispose();
    t.releaseAck.complete();
    expect(await result, isA<NotConnectedException>());
    await t.dispose();
  });

  test(
    'disconnect retires early stream and successor GET owns its context',
    () async {
      final _HeldGetTransport t = _HeldGetTransport();
      final _Link link = _Link(t);
      final PbleConnection c = PbleConnection.fromLink(
        link: link,
        appName: 'test',
        appVersion: '0',
      );
      void hello() => t.deliverNow(
        rsp(PbleOpcode.hello, t.sentFrames.last.id, <int>[
          0,
          ...utf8.encode('proto=1\nmtu=23\nfs_root=/\n'),
        ]),
      );
      await pumpEventQueue();
      hello();
      await pumpEventQueue();
      expect(c.state.value, ConnState.ready);
      final Future<Object> old = _outcome(c.getFile('/old.py'));
      final PbleFrame begin = await t.firstBegin.future;
      t.deliverNow(
        rsp(PbleOpcode.fileGetBegin, begin.id, getBeginOkPayload(1)),
      );
      link.linkState.value = BleLinkState.disconnected;
      link.linkState.value = BleLinkState.connected;
      t.releaseAck.complete();
      expect(await old, isA<NotConnectedException>());
      await pumpEventQueue();
      hello();
      await pumpEventQueue();
      expect(c.state.value, ConnState.ready);
      final Future<Object> next = _outcome(c.getFile('/next.py'));
      await pumpEventQueue();
      t.deliverNow(
        rsp(PbleOpcode.fileGetBegin, begin.id, getBeginOkPayload(1)),
      );
      t.deliverNow(evt(PbleOpcode.fileGetData, getDataPayload(0, <int>[9])));
      t.deliverNow(
        evt(PbleOpcode.fileGetEnd, getEndPayload(pbleCrc32(<int>[9]))),
      );
      t.deliverNow(
        rsp(
          PbleOpcode.fileGetBegin,
          t.sentFrames.last.id,
          getBeginOkPayload(0),
        ),
      );
      t.deliverNow(evt(PbleOpcode.fileGetEnd, getEndPayload(0)));
      expect(await next, isEmpty);
      await c.dispose();
      await t.dispose();
      link.linkState.dispose();
    },
  );

  test(
    'acceptance callback is exact, once, and ordered with decoded events',
    () async {
      final _HeldGetTransport t = _HeldGetTransport();
      final PbleEngine engine = PbleEngine(t);
      final List<String> order = <String>[];
      final StreamSubscription<PbleFrame> events = engine.events.listen(
        (PbleFrame f) => order.add('event${f.payload.single}'),
      );
      final PbleFrame cmd = _cmd(PbleOpcode.deviceInfo, 5);
      final Future<PbleFrame> result = _withCut(
        engine,
        cmd,
        (_) => order.add('response'),
      );
      await pumpEventQueue();
      t.deliverNow(evt(PbleOpcode.runState, <int>[1]));
      t.deliverNow(statusRsp(PbleOpcode.hello, cmd.id, PbleStatus.ok));
      t.deliverNow(statusRsp(PbleOpcode.deviceInfo, cmd.id + 1, PbleStatus.ok));
      t.deliverNow(statusRsp(PbleOpcode.deviceInfo, cmd.id, PbleStatus.ok));
      t.deliverNow(statusRsp(PbleOpcode.deviceInfo, cmd.id, PbleStatus.ok));
      t.deliverNow(evt(PbleOpcode.runState, <int>[2]));
      await result;
      expect(order, <String>['event1', 'response', 'event2']);
      await events.cancel();
      await engine.dispose();
      await t.dispose();
    },
  );

  test('callback errors fail only that request and do not escape RX', () async {
    final _HeldGetTransport t = _HeldGetTransport();
    final PbleEngine engine = PbleEngine(t);
    final Future<Object> result = _outcome(
      _withCut(
        engine,
        _cmd(PbleOpcode.deviceInfo, 5),
        (_) => throw const PbleFormatException('invalid accepted response'),
      ),
    );
    await pumpEventQueue();
    expect(
      () => t.deliverNow(statusRsp(PbleOpcode.deviceInfo, 5, PbleStatus.ok)),
      returnsNormally,
    );
    expect(await result, isA<PbleFormatException>());
    final Future<PbleFrame> next = engine.request(
      _cmd(PbleOpcode.deviceInfo, 6),
    );
    await pumpEventQueue();
    t.deliverNow(statusRsp(PbleOpcode.deviceInfo, 6, PbleStatus.ok));
    expect((await next).id, 6);
    await engine.dispose();
    await t.dispose();
  });

  test(
    'a response after deadline cannot invoke the acceptance callback',
    () async {
      final _HeldGetTransport t = _HeldGetTransport();
      final PbleEngine engine = PbleEngine(t);
      int cuts = 0;
      final Future<Object> result = _outcome(
        _withCut(
          engine,
          _cmd(PbleOpcode.deviceInfo, 5),
          (_) => cuts++,
          timeout: const Duration(milliseconds: 20),
        ),
      );
      expect(await result, isA<PbleTimeoutException>());
      t.deliverNow(statusRsp(PbleOpcode.deviceInfo, 5, PbleStatus.ok));
      expect(cuts, 0);
      await engine.dispose();
      await t.dispose();
    },
  );

  test(
    'on-time acceptance while final ACK is held preserves the deadline rule',
    () async {
      final _HeldGetTransport t = _HeldGetTransport();
      final PbleEngine engine = PbleEngine(t);
      int cuts = 0;
      final Future<PbleFrame> result = _withCut(
        engine,
        _cmd(PbleOpcode.fileGetBegin, 5),
        (_) => cuts++,
        timeout: const Duration(milliseconds: 25),
      );
      await t.firstBegin.future;
      t.deliverNow(rsp(PbleOpcode.fileGetBegin, 5, getBeginOkPayload(0)));
      expect(cuts, 1);
      expect((await result).id, 5);
      t.releaseAck.complete();
      await engine.dispose();
      await t.dispose();
    },
  );

  test(
    'acceptance callback can retire engine without double completion',
    () async {
      final _HeldGetTransport t = _HeldGetTransport();
      final PbleEngine engine = PbleEngine(t);
      final Future<Object> result = _outcome(
        _withCut(
          engine,
          _cmd(PbleOpcode.deviceInfo, 5),
          (_) => unawaited(engine.dispose()),
        ),
      );
      await pumpEventQueue();
      t.deliverNow(statusRsp(PbleOpcode.deviceInfo, 5, PbleStatus.ok));
      expect(await result, isA<PbleTimeoutException>());
      await engine.dispose();
      await t.dispose();
    },
  );

  test(
    'synchronous EVT listener can submit loopback CMD without reentrant add',
    () async {
      final _LoopbackTransport t = _LoopbackTransport();
      final PbleEngine engine = PbleEngine(t);
      Future<PbleFrame>? nested;
      final List<int> seen = <int>[];
      final StreamSubscription<PbleFrame> events = engine.events.listen((
        PbleFrame event,
      ) {
        seen.add(event.payload.single);
        if (event.payload.single == 1)
          nested = engine.request(_cmd(PbleOpcode.deviceInfo, 5));
      });
      t.deliverNow(evt(PbleOpcode.runState, <int>[1]));
      await pumpEventQueue();
      expect((await nested!).id, 5);
      expect(seen, <int>[1, 2]);
      await events.cancel();
      await engine.dispose();
      await t.dispose();
    },
  );
}

class _LoopbackTransport extends FakeByteTransport {
  final StreamController<Uint8List> input =
      StreamController<Uint8List>.broadcast(sync: true);
  @override
  Stream<Uint8List> get inbound => input.stream;
  void deliverNow(PbleFrame f) {
    for (final Uint8List packet in PbleFragmenter(
      mtu: mtu,
    ).fragment(encodeFrame(f))) {
      input.add(packet);
    }
  }

  @override
  Future<void> send(Uint8List packet, {required bool acknowledged}) {
    final int before = sentFrames.length;
    final Future<void> sent = super.send(packet, acknowledged: acknowledged);
    if (sentFrames.length > before) {
      final PbleFrame cmd = sentFrames.last;
      deliverNow(rsp(PbleOpcode.deviceInfo, cmd.id, <int>[0]));
      deliverNow(evt(PbleOpcode.runState, <int>[2]));
    }
    return sent;
  }

  @override
  Future<void> dispose() async {
    await input.close();
    await super.dispose();
  }
}

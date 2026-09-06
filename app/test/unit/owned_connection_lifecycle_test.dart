// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';

import 'package:flutter/foundation.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:pyble/ble/ble.dart';
import 'package:pyble/pble/ble_byte_transport.dart';
import 'package:pyble/pble/connection.dart';
import 'package:pyble/pble/connection_manager.dart';
import 'package:pyble/pble/conn_state.dart';
import 'package:pyble/pble/engine.dart';
import 'package:pyble/pble/fragment.dart';
import 'package:pyble/pble/frame.dart';
import 'package:pyble/pble/pble_connection.dart';
import 'package:pyble/pble/pble_constants.dart';
import 'package:pyble/pble/pble_exception.dart';
import 'package:pyble/pble/scanner.dart';

import '../support/fake_readiness_seam.dart';

class _TrackedState extends ValueNotifier<BleLinkState> {
  _TrackedState() : super(BleLinkState.disconnected);
  final Set<VoidCallback> listeners = <VoidCallback>{};
  @override
  void addListener(VoidCallback listener) {
    listeners.add(listener);
    super.addListener(listener);
  }

  @override
  void removeListener(VoidCallback listener) {
    listeners.remove(listener);
    super.removeListener(listener);
  }
}

/// Actual encoded HELLO/engine traffic, with only the physical byte pipe faked.
class _OwnedLink implements BleLink {
  final _TrackedState state = _TrackedState();
  final StreamController<List<int>> incoming =
      StreamController<List<int>>.broadcast();
  final List<List<int>> writes = <List<int>>[];
  int disconnectCalls = 0;
  Completer<void>? closeGate;
  Object? closeFailure;
  @override
  Stream<List<int>> get inbound => incoming.stream;
  @override
  ValueListenable<BleLinkState> get linkState => state;
  @override
  int get mtu => 247;
  @override
  Future<void> write(List<int> bytes, {required bool withoutResponse}) async {
    writes.add(List<int>.of(bytes));
  }

  @override
  Future<void> disconnect() async {
    disconnectCalls++;
    await closeGate?.future;
    if (closeFailure case final Object failure) throw failure;
    state.value = BleLinkState.disconnected;
  }

  Future<void> releaseFixture() async {
    await incoming.close();
    state.dispose();
  }

  List<PbleFrame> get frames {
    final PbleReassembler parser = PbleReassembler();
    return <PbleFrame>[
      for (final List<int> packet in writes)
        if (parser.offer(Uint8List.fromList(packet)) case final Uint8List raw)
          decodeFrame(raw),
    ];
  }

  void deliver(PbleFrame frame) {
    for (final Uint8List packet in PbleFragmenter(
      mtu: mtu,
    ).fragment(encodeFrame(frame))) {
      incoming.add(packet);
    }
  }

  void answerHello({int proto = 1}) {
    final PbleFrame hello = frames.lastWhere(
      (PbleFrame f) => f.opcode == PbleOpcode.hello.code,
    );
    deliver(
      PbleFrame(
        type: Pble.typeRsp,
        opcode: hello.opcode,
        id: hello.id,
        payload: Uint8List.fromList(<int>[
          0,
          ...utf8.encode(
            'proto=$proto\nchip=esp32-c3\nmpy=1.28.0\nfs_root=/\nmtu=247',
          ),
        ]),
      ),
    );
  }
}

Future<({PbleConnection connection, _OwnedLink link})> _ready() async {
  final _OwnedLink link = _OwnedLink();
  final PbleConnection connection = PbleConnection.fromLink(
    link: link,
    appName: 'PyBLE',
    appVersion: '0.2.0',
  );
  link.state.value = BleLinkState.connected;
  await pumpEventQueue();
  link.answerHello();
  await pumpEventQueue();
  expect(connection.state.value, ConnState.ready);
  addTearDown(() async {
    if (link.closeGate case final Completer<void> gate when !gate.isCompleted)
      gate.complete();
    try {
      await connection.dispose();
    } catch (_) {}
    await link.releaseFixture();
  });
  return (connection: connection, link: link);
}

PbleConnectionManager _manager(ConnectionFactory factory) {
  final PbleConnectionManager manager = PbleConnectionManager(
    scanner: FakeScanner(),
    readiness: FakeSeamReadiness(BleReadiness.ready),
    connectionFactory: factory,
  );
  addTearDown(() async {
    try {
      await manager.dispose();
    } catch (_) {}
  });
  return manager;
}

void main() {
  group('FR-CONNECT-7 owned physical link teardown', () {
    test(
      'HELLO-ready dispose closes exact link and removes both listeners',
      () async {
        final r = await _ready();
        expect(r.link.state.listeners, hasLength(2));
        await r.connection.dispose();
        expect(r.link.disconnectCalls, 1);
        expect(r.link.state.value, BleLinkState.disconnected);
        expect(r.link.state.listeners, isEmpty);
      },
    );

    test(
      'concurrent and repeated disposal shares physical close completion',
      () async {
        final r = await _ready();
        r.link.closeGate = Completer<void>();
        final Future<void> first = r.connection.dispose();
        final Future<void> second = r.connection.dispose();
        bool done = false;
        unawaited(
          second.then((_) {
            done = true;
          }),
        );
        await pumpEventQueue();
        expect(identical(first, second), isTrue);
        expect(done, isFalse);
        expect(r.link.disconnectCalls, 1);
        r.link.closeGate!.complete();
        await first;
        await r.connection.dispose();
        expect(r.link.disconnectCalls, 1);
      },
    );

    test(
      'close failure still releases streams/listeners and remains a failure',
      () async {
        final r = await _ready();
        final StateError failure = StateError('physical close rejected');
        r.link.closeFailure = failure;
        final Future<void> consoleDone = r.connection.console.drain<void>();
        final Future<void> runDone = r.connection.runState.drain<void>();
        await expectLater(r.connection.dispose(), throwsA(same(failure)));
        await Future.wait(<Future<void>>[consoleDone, runDone]);
        expect(r.link.state.listeners, isEmpty);
        expect(r.link.state.value, BleLinkState.connected);
        await expectLater(r.connection.dispose(), throwsA(same(failure)));
        expect(r.link.disconnectCalls, 1);
      },
    );

    test(
      'direct engine constructor does not own external byte transport',
      () async {
        final _OwnedLink link = _OwnedLink();
        final BleByteTransport transport = BleByteTransport(link);
        final PbleConnection connection = PbleConnection(
          engine: PbleEngine(transport),
          appName: 'PyBLE',
          appVersion: '0.2.0',
        );
        await connection.dispose();
        expect(link.disconnectCalls, 0);
        expect(link.state.listeners, hasLength(1));
        transport.dispose();
        await link.releaseFixture();
      },
    );

    test('late HELLO after disposal never republishes ready', () async {
      final _OwnedLink link = _OwnedLink();
      final PbleConnection connection = PbleConnection.fromLink(
        link: link,
        appName: 'PyBLE',
        appVersion: '0.2.0',
      );
      link.state.value = BleLinkState.connected;
      await pumpEventQueue();
      final List<ConnState> states = <ConnState>[];
      connection.state.addListener(() {
        states.add(connection.state.value);
      });
      await connection.dispose();
      link.answerHello();
      await pumpEventQueue();
      expect(states, isNot(contains(ConnState.ready)));
      expect(link.disconnectCalls, 1);
      expect(link.state.listeners, isEmpty);
      await link.releaseFixture();
    });

    test(
      'disposal aborts an active download without another command',
      () async {
        final r = await _ready();
        final Future<Uint8List> download = r.connection.getFile('owned.bin');
        final Future<void> rejected = expectLater(
          download,
          throwsA(isA<NotConnectedException>()),
        );
        await pumpEventQueue();
        final PbleFrame begin = r.link.frames.last;
        r.link.deliver(
          PbleFrame(
            type: Pble.typeRsp,
            opcode: begin.opcode,
            id: begin.id,
            payload: Uint8List.fromList(<int>[0, 1, 0, 0, 0]),
          ),
        );
        await pumpEventQueue();
        final int count = r.link.writes.length;
        await r.connection.dispose();
        await rejected;
        await expectLater(
          r.connection.runFile('owned.bin'),
          throwsA(isA<NotConnectedException>()),
        );
        expect(r.link.writes, hasLength(count));
      },
    );

    test(
      'terminal owned HELLO refusal closes physical link automatically',
      () async {
        final _OwnedLink link = _OwnedLink();
        final PbleConnection connection = PbleConnection.fromLink(
          link: link,
          appName: 'PyBLE',
          appVersion: '0.2.0',
        );
        link.state.value = BleLinkState.connected;
        await pumpEventQueue();
        link.answerHello(proto: 2);
        await pumpEventQueue();
        expect(link.disconnectCalls, 1);
        expect(link.state.value, BleLinkState.disconnected);
        await connection.dispose();
        await link.releaseFixture();
      },
    );
  });

  group('FR-CONNECT-7 manager ownership and late factories', () {
    test('ordinary manager Disconnect closes the real ready link', () async {
      final r = await _ready();
      final manager = _manager((_) async => r.connection);
      await manager.connect('board-a');
      await manager.disconnect();
      expect(r.link.disconnectCalls, 1);
      expect(r.link.state.value, BleLinkState.disconnected);
      expect(manager.phase.value, ConnectPhase.idle);
    });

    test(
      'replacement waits for old physical close before opening new board',
      () async {
        final a = await _ready();
        final b = await _ready();
        bool openedB = false;
        final manager = _manager((String id) async {
          if (id == 'a') return a.connection;
          openedB = true;
          return b.connection;
        });
        await manager.connect('a');
        a.link.closeGate = Completer<void>();
        final Future<void> replacement = manager.connect('b');
        await pumpEventQueue();
        expect(openedB, isFalse);
        expect(a.link.disconnectCalls, 1);
        a.link.closeGate!.complete();
        await replacement;
        expect(openedB, isTrue);
        expect(b.link.disconnectCalls, 0);
        expect(manager.selected?.id, 'b');
      },
    );

    test(
      'late connection after Disconnect is closed and never attached',
      () async {
        final r = await _ready();
        final Completer<Connection> pending = Completer<Connection>();
        final manager = _manager((_) => pending.future);
        final Future<void> connect = manager.connect('late');
        await pumpEventQueue();
        await manager.disconnect();
        pending.complete(r.connection);
        await connect;
        expect(r.link.disconnectCalls, 1);
        expect(manager.connection.state.value, ConnState.disconnected);
        expect(manager.selected, isNull);
      },
    );

    test('newest connection wins and stale result cannot close it', () async {
      final a = await _ready();
      final b = await _ready();
      final Completer<Connection> pendingA = Completer<Connection>();
      final Completer<Connection> pendingB = Completer<Connection>();
      final manager = _manager(
        (String id) => id == 'a' ? pendingA.future : pendingB.future,
      );
      final Future<void> first = manager.connect('a');
      await pumpEventQueue();
      final Future<void> second = manager.connect('b');
      await pumpEventQueue();
      pendingB.complete(b.connection);
      await second;
      pendingA.complete(a.connection);
      await first;
      expect(a.link.disconnectCalls, 1);
      expect(b.link.disconnectCalls, 0);
      expect(manager.selected?.id, 'b');
      expect(manager.phase.value, ConnectPhase.connected);
    });

    test('old disconnect completion cannot clear a newer session', () async {
      final a = await _ready();
      final b = await _ready();
      final manager = _manager(
        (String id) async => id == 'a' ? a.connection : b.connection,
      );
      await manager.connect('a');
      a.link.closeGate = Completer<void>();
      final Future<void> oldDisconnect = manager.disconnect();
      await pumpEventQueue();
      final Future<void> nextConnect = manager.connect('b');
      a.link.closeGate!.complete();
      await Future.wait(<Future<void>>[oldDisconnect, nextConnect]);
      expect(manager.selected?.id, 'b');
      expect(manager.phase.value, ConnectPhase.connected);
      expect(a.link.disconnectCalls, 1);
      expect(b.link.disconnectCalls, 0);
    });

    test(
      'manager disposal closes a factory that completes after disposal',
      () async {
        final r = await _ready();
        final Completer<Connection> pending = Completer<Connection>();
        final manager = _manager((_) => pending.future);
        final Future<void> connecting = manager.connect('late');
        await pumpEventQueue();
        await manager.dispose();
        pending.complete(r.connection);
        await expectLater(connecting, completes);
        expect(r.link.disconnectCalls, 1);
        await expectLater(manager.connect('forbidden'), throwsStateError);
      },
    );

    test('close errors are not reported as successful Disconnect', () async {
      final r = await _ready();
      final StateError failure = StateError('close failure');
      final manager = _manager((_) async => r.connection);
      await manager.connect('a');
      r.link.closeFailure = failure;
      await expectLater(manager.disconnect(), throwsA(same(failure)));
      expect(manager.phase.value, ConnectPhase.failed);
      expect(manager.lastError, same(failure));
      expect(r.link.state.listeners, isEmpty);
    });

    test('failed old physical close blocks replacement factory', () async {
      final a = await _ready();
      final b = await _ready();
      final StateError failure = StateError('old board still connected');
      bool openedB = false;
      final manager = _manager((String id) async {
        if (id == 'a') return a.connection;
        openedB = true;
        return b.connection;
      });
      await manager.connect('a');
      a.link.closeFailure = failure;
      await expectLater(manager.connect('b'), throwsA(same(failure)));
      expect(openedB, isFalse);
      expect(manager.phase.value, ConnectPhase.failed);
      expect(manager.lastError, same(failure));
      expect(a.link.state.value, BleLinkState.connected);
      // An already-failed retirement is not proof of a physically closed link.
      await expectLater(manager.connect('b'), throwsA(same(failure)));
      expect(openedB, isFalse);
      expect(a.link.disconnectCalls, 1);
    });

    test(
      'manager disposal shares failure and still closes facade streams',
      () async {
        final r = await _ready();
        final StateError failure = StateError('close failure');
        final manager = _manager((_) async => r.connection);
        await manager.connect('a');
        r.link.closeFailure = failure;
        final Future<void> streams = Future.wait(<Future<void>>[
          manager.connection.console.drain<void>(),
          manager.connection.runState.drain<void>(),
          manager.scanResults.drain<void>(),
        ]);
        final Future<void> first = manager.dispose();
        expect(identical(first, manager.dispose()), isTrue);
        await expectLater(first, throwsA(same(failure)));
        await streams;
        await expectLater(manager.dispose(), throwsA(same(failure)));
        expect(r.link.disconnectCalls, 1);
      },
    );
  });
}

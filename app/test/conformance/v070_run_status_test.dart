// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';
import 'package:pyble/pble/conn_state.dart';
import 'package:pyble/pble/engine.dart';
import 'package:pyble/pble/frame.dart';
import 'package:pyble/pble/hello.dart';
import 'package:pyble/pble/pble_connection.dart';
import 'package:pyble/pble/pble_constants.dart';
import 'package:pyble/pble/run_snapshot_codec.dart';
import 'package:pyble/pble/types.dart';

import '../support/fake_byte_transport.dart';
import '../support/hex.dart';
import '../support/pble_frames.dart';

Uint8List body({
  int revision = 2,
  int state = 1,
  int origin = 2,
  int reason = 0,
  int flags = 0,
  int boot = 1,
}) {
  final ByteData d = ByteData(25);
  d.setUint8(0, 1);
  d.setUint8(1, boot);
  d.setUint32(9, 1, Endian.little);
  d.setUint64(13, revision, Endian.little);
  d.setUint8(21, state);
  d.setUint8(22, origin);
  d.setUint8(23, reason);
  d.setUint8(24, flags);
  return d.buffer.asUint8List();
}

void main() {
  final Map<String, dynamic> corpus =
      jsonDecode(
            File(
              '../tests/firmware_tests/host/conformance/v070_run_status_vectors.json',
            ).readAsStringSync(),
          )
          as Map<String, dynamic>;

  group('v070 shared status corpus', () {
    for (final dynamic value in corpus['valid'] as List<dynamic>) {
      final Map<String, dynamic> row = value as Map<String, dynamic>;
      test(row['name'] as String, () {
        final RunSnapshot s = decodeRunSnapshot(
          hexToBytes(row['hex'] as String),
        );
        expect(s.bootId, row['boot_id']);
        expect(s.runId, row['run_id']);
        expect(s.revision, row['revision']);
        expect(s.state.index, row['state']);
        expect(s.origin.index, row['origin']);
        expect(s.terminalReason.index, row['terminal_reason']);
        expect(s.queued, ((row['flags'] as int) & 1) != 0);
        expect(s.stopping, ((row['flags'] as int) & 2) != 0);
      });
    }
    for (final dynamic value in corpus['invalid'] as List<dynamic>) {
      final Map<String, dynamic> row = value as Map<String, dynamic>;
      test('rejects ${row['name']}', () {
        expect(
          () => decodeRunSnapshot(hexToBytes(row['hex'] as String)),
          throwsA(isA<PbleFormatException>()),
        );
      });
    }
    test('capability is explicit and absent on old peers', () {
      expect(parseCaps('run_status=1').hasRunStatus, isTrue);
      expect(parseCaps('').hasRunStatus, isFalse);
      expect(parseCaps('run_status=2').hasRunStatus, isFalse);
    });
    test('revision retains the exact cross-language upper bound', () {
      expect(
        decodeRunSnapshot(body(revision: 9007199254740991)).revision,
        9007199254740991,
      );
    });
    test('revision cannot precede the accepted run generation', () {
      final Uint8List data = body();
      ByteData.sublistView(data).setUint32(9, 3, Endian.little);
      expect(
        () => decodeRunSnapshot(data),
        throwsA(isA<PbleFormatException>()),
      );
    });
  });

  group('v070 synchronized handshake and observation', () {
    late FakeByteTransport transport;
    late PbleConnection conn;
    setUp(() {
      transport = FakeByteTransport(mtu: 23);
      conn = PbleConnection(
        engine: PbleEngine(transport),
        appName: 'PyBLE',
        appVersion: 'test',
      );
    });
    tearDown(() async {
      await conn.dispose();
      await transport.dispose();
    });

    Future<void> offer({bool capable = true}) async {
      await pumpEventQueue();
      final PbleFrame hello = transport.sentFrames.last;
      expect(hello.opcode, PbleOpcode.hello.code);
      transport.deliverFrame(
        rsp(PbleOpcode.hello, hello.id, <int>[
          0,
          ...utf8.encode(
            'proto=1\nagent=0.7.0\nrun_status=${capable ? '1' : '0'}',
          ),
        ]),
      );
      await pumpEventQueue();
    }

    void reply(Uint8List data) {
      final PbleFrame query = transport.sentFrames.last;
      expect(query.opcode, PbleOpcode.runStatus.code);
      expect(query.payload, isEmpty);
      transport.deliverFrame(
        rsp(PbleOpcode.runStatus, query.id, <int>[0, ...data]),
      );
    }

    test('synchronizes running autorun before publishing readiness', () async {
      final Future<void> pending = conn.handshake();
      await offer();
      expect(conn.state.value, ConnState.connecting);
      reply(body(origin: 3));
      await pending;
      expect(conn.state.value, ConnState.running);
      expect(conn.runSnapshot.value?.origin, RunOrigin.autorun);
      expect(transport.sentFrames.map((f) => f.opcode), <int>[1, 0x24]);
    });

    test('newer event wins over an older initial response', () async {
      final Future<void> pending = conn.handshake();
      await offer();
      transport.deliverFrame(
        evt(
          PbleOpcode.runStatusChanged,
          body(revision: 3, state: 2, reason: 1),
        ),
      );
      await pumpEventQueue();
      reply(body());
      await pending;
      expect(conn.runSnapshot.value?.revision, 3);
      expect(conn.runSnapshot.value?.state, RunState.done);
      expect(conn.state.value, ConnState.ready);
      transport.deliverFrame(evt(PbleOpcode.runState, <int>[1]));
      transport.deliverFrame(evt(PbleOpcode.runStatusChanged, body()));
      await pumpEventQueue();
      expect(conn.runSnapshot.value?.state, RunState.done);
      expect(conn.state.value, ConnState.ready);
    });

    test('same revision same body is idempotent', () async {
      final Future<void> pending = conn.handshake();
      await offer();
      reply(body());
      await pending;
      transport.deliverFrame(evt(PbleOpcode.runStatusChanged, body()));
      await pumpEventQueue();
      expect(conn.state.value, ConnState.running);
      expect(conn.runSnapshot.value?.revision, 2);
    });

    test('equal revision conflict retires the connection', () async {
      final Future<void> pending = conn.handshake();
      await offer();
      reply(body());
      await pending;
      transport.deliverFrame(evt(PbleOpcode.runStatusChanged, body(origin: 3)));
      await pumpEventQueue();
      expect(conn.state.value, ConnState.disconnected);
      expect(conn.runSnapshot.value, isNull);
    });

    test('new boot on a live connection requires reconnect', () async {
      final Future<void> pending = conn.handshake();
      await offer();
      reply(body());
      await pending;
      transport.deliverFrame(evt(PbleOpcode.runStatusChanged, body(boot: 2)));
      await pumpEventQueue();
      expect(conn.state.value, ConnState.disconnected);
    });

    test('advertised malformed response is not an idle fallback', () async {
      final Future<void> pending = conn.handshake();
      final Future<void> observed = expectLater(
        pending,
        throwsA(isA<PbleFormatException>()),
      );
      await offer();
      reply(Uint8List(24));
      await observed;
      expect(conn.state.value, ConnState.disconnected);
      expect(conn.runSnapshot.value, isNull);
    });

    test('advertised query timeout never publishes Ready', () async {
      final Future<void> pending = conn.handshake();
      final Future<void> observed = expectLater(
        pending,
        throwsA(isA<PbleTimeoutException>()),
      );
      await offer();
      await observed;
      expect(conn.state.value, ConnState.disconnected);
    });

    test('old firmware does not receive status queries', () async {
      final Future<void> pending = conn.handshake();
      await offer(capable: false);
      await pending;
      expect(transport.sentFrames, hasLength(1));
      transport.deliverFrame(evt(PbleOpcode.runState, <int>[1]));
      await pumpEventQueue();
      expect(conn.state.value, ConnState.running);
    });

    test('accepted Run returns before its automatic status refresh', () async {
      final Future<void> initial = conn.handshake();
      await offer();
      reply(body(revision: 3, state: 2, reason: 1));
      await initial;
      final Future<void> run = conn.runSource('print(1)');
      await pumpEventQueue();
      final PbleFrame command = transport.sentFrames.last;
      transport.deliverFrame(
        statusRsp(PbleOpcode.run, command.id, PbleStatus.ok),
      );
      await run;
      await pumpEventQueue();
      expect(transport.sentFrames.last.opcode, PbleOpcode.runStatus.code);
      expect(
        transport.sentFrames.where(
          (f) => f.opcode == PbleOpcode.runStatus.code,
        ),
        hasLength(2),
      );
      final Uint8List next = body(revision: 4);
      ByteData.sublistView(next).setUint32(9, 2, Endian.little);
      reply(next);
      await pumpEventQueue();
      expect(conn.runSnapshot.value?.runId, 2);
      expect(conn.state.value, ConnState.running);
    });

    test(
      'accepted Stop refreshes state even when tagged events were lost',
      () async {
        final Future<void> initial = conn.handshake();
        await offer();
        reply(body());
        await initial;
        final Future<void> stopped = conn.stop();
        await pumpEventQueue();
        final PbleFrame command = transport.sentFrames.last;
        transport.deliverFrame(
          statusRsp(PbleOpcode.stop, command.id, PbleStatus.ok),
        );
        await stopped;
        await pumpEventQueue();
        expect(transport.sentFrames.last.opcode, PbleOpcode.runStatus.code);
        reply(body(revision: 4, state: 0, reason: 3));
        await pumpEventQueue();
        expect(
          conn.runSnapshot.value?.terminalReason,
          RunTerminalReason.stopped,
        );
        expect(conn.state.value, ConnState.ready);
      },
    );

    test(
      'legacy hints coalesce to one pending query and one follow-up',
      () async {
        final Future<void> initial = conn.handshake();
        await offer();
        reply(body());
        await initial;
        for (int i = 0; i < 20; i++) {
          transport.deliverFrame(evt(PbleOpcode.runState, <int>[2]));
        }
        await pumpEventQueue();
        expect(
          transport.sentFrames.where(
            (f) => f.opcode == PbleOpcode.runStatus.code,
          ),
          hasLength(2),
        );
        expect(conn.state.value, ConnState.running);
        reply(body());
        await pumpEventQueue();
        expect(
          transport.sentFrames.where(
            (f) => f.opcode == PbleOpcode.runStatus.code,
          ),
          hasLength(3),
        );
        reply(body(revision: 3, state: 2, reason: 1));
        await pumpEventQueue();
        expect(transport.sentFrames, hasLength(4));
        expect(conn.state.value, ConnState.ready);
      },
    );

    test('later refresh timeout does not reclassify an accepted Run', () async {
      final Future<void> initial = conn.handshake();
      await offer();
      reply(body(revision: 3, state: 2, reason: 1));
      await initial;
      final Future<void> run = conn.runSource('print(1)');
      await pumpEventQueue();
      final PbleFrame command = transport.sentFrames.last;
      transport.deliverFrame(
        statusRsp(PbleOpcode.run, command.id, PbleStatus.ok),
      );
      await run;
      await pumpEventQueue();
      expect(transport.sentFrames.last.opcode, PbleOpcode.runStatus.code);
      await Future<void>.delayed(const Duration(milliseconds: 5100));
      expect(conn.state.value, ConnState.disconnected);
    });

    test(
      'old automatic refresh cannot retire a synchronized new session',
      () async {
        final Future<void> initial = conn.handshake();
        await offer();
        reply(body());
        await initial;
        transport.deliverFrame(evt(PbleOpcode.runState, <int>[1]));
        await pumpEventQueue();
        final PbleFrame oldQuery = transport.sentFrames.last;
        expect(oldQuery.opcode, PbleOpcode.runStatus.code);

        final Future<void> reconnected = conn.handshake();
        await offer();
        reply(body(boot: 2, revision: 5));
        await reconnected;
        final RunSnapshot recovered = conn.runSnapshot.value!;
        expect(recovered.bootId, decodeRunSnapshot(body(boot: 2)).bootId);
        expect(conn.state.value, ConnState.running);

        // The old operation finishes after a fully synchronized new HELLO.
        // Its generation mismatch is expected and must not fault the new peer.
        transport.deliverFrame(
          rsp(PbleOpcode.runStatus, oldQuery.id, <int>[
            0,
            ...body(revision: 3, state: 2, reason: 1),
          ]),
        );
        await pumpEventQueue();
        expect(conn.state.value, ConnState.running);
        expect(conn.runSnapshot.value, recovered);
        expect((await conn.deviceInfo()).hasRunStatus, isTrue);
      },
    );

    test('disposal invalidates cached status', () async {
      final Future<void> pending = conn.handshake();
      await offer();
      reply(body());
      await pending;
      await conn.dispose();
      expect(conn.runSnapshot.value, isNull);
    });

    test('malformed tagged event retires the live connection', () async {
      final Future<void> pending = conn.handshake();
      await offer();
      reply(body());
      await pending;
      transport.deliverFrame(evt(PbleOpcode.runStatusChanged, Uint8List(24)));
      await pumpEventQueue();
      expect(conn.state.value, ConnState.disconnected);
      expect(conn.runSnapshot.value, isNull);
    });

    test(
      'refresh queries only and returns the newest cached snapshot',
      () async {
        final Future<void> pending = conn.handshake();
        await offer();
        reply(body());
        await pending;
        final Future<RunSnapshot> refresh = conn.refreshRunStatus();
        await pumpEventQueue();
        transport.deliverFrame(
          evt(
            PbleOpcode.runStatusChanged,
            body(revision: 3, state: 2, reason: 1),
          ),
        );
        await pumpEventQueue();
        reply(body());
        expect((await refresh).state, RunState.done);
        expect(transport.sentFrames.map((f) => f.opcode), <int>[1, 0x24, 0x24]);
      },
    );

    test(
      'retired handshake response cannot overwrite a successor session',
      () async {
        final Future<void> first = conn.handshake();
        final Future<void> rejected = expectLater(
          first,
          throwsA(isA<NotConnectedException>()),
        );
        await offer();
        final PbleFrame oldQuery = transport.sentFrames.last;
        final Future<void> successor = conn.handshake();
        await offer();
        reply(body(boot: 2));
        await successor;
        transport.deliverFrame(
          rsp(PbleOpcode.runStatus, oldQuery.id, <int>[0, ...body()]),
        );
        await rejected;
        expect(conn.runSnapshot.value?.bootId, '0200000000000000');
        expect(conn.state.value, ConnState.running);
      },
    );
  });
}

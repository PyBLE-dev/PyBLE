// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.
//
// A-10 [red] — PbleEngine: request/response correlation + EVT routing (§3.3).
//
// Runs the REAL engine over an in-memory [FakeByteTransport], asserting:
//   • nextId() rolls 1..255, never 0 (0 is reserved for EVT), and is distinct
//     across a full cycle;
//   • request(cmd) resolves with the RSP that carries the matching ID;
//   • EVT frames (ID == 0) are routed onto events, keyed by opcode, and never
//     mistaken for a response;
//   • an unanswered request times out with PbleTimeoutException.
//
// CURRENTLY RED: `lib/pble/{engine,frame,pble_constants,pble_exception}.dart`
// do not exist yet. HAND-OFF: `lib/pble/**` → app-protocol-engineer.

import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';

import 'package:pyble/pble/engine.dart';
import 'package:pyble/pble/frame.dart';
import 'package:pyble/pble/pble_constants.dart';
import 'package:pyble/pble/pble_exception.dart';

import '../support/fake_byte_transport.dart';

void main() {
  late FakeByteTransport transport;
  late PbleEngine engine;

  setUp(() {
    transport = FakeByteTransport(mtu: Pble.mtuRequest);
    engine = PbleEngine(transport);
  });

  tearDown(() async {
    await engine.dispose();
    await transport.dispose();
  });

  group('A-10 PbleEngine correlation + events (protocol.md §3.3)', () {
    test('nextId() rolls 1..255, distinct across a cycle, never 0', () {
      final Set<int> ids = <int>{};
      for (int i = 0; i < 255; i++) {
        final int id = engine.nextId();
        expect(id, inInclusiveRange(1, 255));
        expect(id, isNot(Pble.evtId));
        ids.add(id);
      }
      expect(ids, hasLength(255), reason: 'a full cycle yields 255 unique IDs');
    });

    test('request() resolves with the RSP carrying the matching ID', () async {
      final PbleFrame cmd = PbleFrame(
        type: Pble.typeCmd,
        opcode: PbleOpcode.deviceInfo.code,
        id: engine.nextId(),
        payload: Uint8List(0),
      );
      final Future<PbleFrame> pending = engine.request(cmd);
      await pumpEventQueue();

      final int sentId = transport.sentFrames.single.id;
      transport.deliverFrame(
        PbleFrame(
          type: Pble.typeRsp,
          opcode: PbleOpcode.deviceInfo.code,
          id: sentId,
          payload: Uint8List.fromList(<int>[PbleStatus.ok.code]),
        ),
      );

      final PbleFrame rsp = await pending;
      expect(rsp.id, sentId);
      expect(rsp.type, Pble.typeRsp);
      expect(rsp.opcode, PbleOpcode.deviceInfo.code);
    });

    test('EVT frames (id==0) route onto events by opcode', () async {
      final Future<PbleFrame> evt = engine.events.first;
      transport.deliverFrame(
        PbleFrame(
          type: Pble.typeEvt,
          opcode: PbleOpcode.consoleData.code,
          id: Pble.evtId,
          payload: Uint8List.fromList(<int>[0x68, 0x69, 0x0a]),
        ),
      );

      final PbleFrame received = await evt;
      expect(received.type, Pble.typeEvt);
      expect(received.opcode, PbleOpcode.consoleData.code);
      expect(received.id, Pble.evtId);
    });

    test('an unanswered request times out with PbleTimeoutException', () async {
      final PbleFrame cmd = PbleFrame(
        type: Pble.typeCmd,
        opcode: PbleOpcode.deviceInfo.code,
        id: engine.nextId(),
        payload: Uint8List(0),
      );
      await expectLater(
        engine.request(cmd, timeout: const Duration(milliseconds: 50)),
        throwsA(isA<PbleTimeoutException>()),
      );
    });

    test('request acknowledges every outbound fragment', () async {
      final PbleFrame cmd = PbleFrame(
        type: Pble.typeCmd,
        opcode: PbleOpcode.run.code,
        id: engine.nextId(),
        payload: Uint8List.fromList(List<int>.filled(500, 0x78)),
      );
      final Future<PbleFrame> pending = engine.request(cmd);
      await pumpEventQueue();
      transport.deliverFrame(
        PbleFrame(
          type: Pble.typeRsp,
          opcode: cmd.opcode,
          id: cmd.id,
          payload: Uint8List.fromList(<int>[PbleStatus.ok.code]),
        ),
      );
      await pending;

      expect(transport.sentAcknowledged, hasLength(greaterThan(1)));
      expect(transport.sentAcknowledged, everyElement(isTrue));
    });

    test('fire keeps every outbound fragment write-without-response', () async {
      final PbleFrame cmd = PbleFrame(
        type: Pble.typeCmd,
        opcode: PbleOpcode.consoleInput.code,
        id: Pble.evtId,
        payload: Uint8List.fromList(List<int>.filled(500, 0x78)),
      );
      await engine.fire(cmd);

      expect(transport.sentAcknowledged, hasLength(greaterThan(1)));
      expect(transport.sentAcknowledged, everyElement(isFalse));
    });

    test(
      'request timeout includes time spent in acknowledged writes',
      () async {
        await engine.dispose();
        await transport.dispose();
        transport = FakeByteTransport(
          mtu: Pble.mtuRequest,
          sendDelay: const Duration(milliseconds: 200),
        );
        engine = PbleEngine(transport);
        final PbleFrame cmd = PbleFrame(
          type: Pble.typeCmd,
          opcode: PbleOpcode.hello.code,
          id: engine.nextId(),
          payload: Uint8List(0),
        );
        final Stopwatch elapsed = Stopwatch()..start();

        await expectLater(
          engine.request(cmd, timeout: const Duration(milliseconds: 25)),
          throwsA(isA<PbleTimeoutException>()),
        );
        elapsed.stop();

        expect(
          elapsed.elapsed,
          lessThan(const Duration(milliseconds: 100)),
          reason: 'the command deadline begins before its first fragment write',
        );
      },
    );
  });
}

// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.
//
// A-10 [red] — PbleEngine: request/response correlation + EVT routing (§3.3).
//
// Runs the REAL engine over an in-memory [FakeByteTransport], asserting:
//   • nextId() rolls 1..255, never 0 (0 is reserved for EVT), and is distinct
//     across a full cycle;
//   • request(cmd) resolves only with TYPE=RSP carrying the exact originating
//     opcode + ID, even when an ID is reused;
//   • wrong-opcode and non-RSP frames cannot complete a request or hide the
//     exact response in either arrival order;
//   • EVT frames (ID == 0) are routed onto events, keyed by opcode, and never
//     mistaken for a response;
//   • an unanswered request times out with PbleTimeoutException.
//
// CURRENTLY RED: `lib/pble/{engine,frame,pble_constants,pble_exception}.dart`
// do not exist yet. HAND-OFF: `lib/pble/**` → app-protocol-engineer.

import 'dart:async';
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

    test(
      'wrong-opcode same-ID RSP before the exact RSP cannot complete it',
      () async {
        final PbleFrame cmd = PbleFrame(
          type: Pble.typeCmd,
          opcode: PbleOpcode.run.code,
          id: engine.nextId(),
          payload: Uint8List(0),
        );
        final Future<PbleFrame> pending = engine.request(cmd);
        await pumpEventQueue();

        transport.deliverFrame(
          PbleFrame(
            type: Pble.typeRsp,
            opcode: PbleOpcode.hello.code,
            id: cmd.id,
            payload: Uint8List.fromList(<int>[PbleStatus.ok.code, 0x11]),
          ),
        );
        transport.deliverFrame(
          PbleFrame(
            type: Pble.typeRsp,
            opcode: cmd.opcode,
            id: cmd.id,
            payload: Uint8List.fromList(<int>[PbleStatus.ok.code, 0x22]),
          ),
        );

        final PbleFrame rsp = await pending;
        expect(rsp.type, Pble.typeRsp);
        expect(rsp.opcode, cmd.opcode);
        expect(rsp.payload, <int>[PbleStatus.ok.code, 0x22]);
      },
    );

    test(
      'exact RSP before a wrong-opcode same-ID RSP remains authoritative',
      () async {
        final PbleFrame cmd = PbleFrame(
          type: Pble.typeCmd,
          opcode: PbleOpcode.run.code,
          id: engine.nextId(),
          payload: Uint8List(0),
        );
        final Future<PbleFrame> pending = engine.request(cmd);
        await pumpEventQueue();

        transport.deliverFrame(
          PbleFrame(
            type: Pble.typeRsp,
            opcode: cmd.opcode,
            id: cmd.id,
            payload: Uint8List.fromList(<int>[PbleStatus.ok.code, 0x33]),
          ),
        );
        transport.deliverFrame(
          PbleFrame(
            type: Pble.typeRsp,
            opcode: PbleOpcode.hello.code,
            id: cmd.id,
            payload: Uint8List.fromList(<int>[PbleStatus.ok.code, 0x44]),
          ),
        );

        final PbleFrame rsp = await pending;
        expect(rsp.type, Pble.typeRsp);
        expect(rsp.opcode, cmd.opcode);
        expect(rsp.payload, <int>[PbleStatus.ok.code, 0x33]);
      },
    );

    test('non-RSP frame with a nonzero ID cannot complete a request', () async {
      final PbleFrame cmd = PbleFrame(
        type: Pble.typeCmd,
        opcode: PbleOpcode.deviceInfo.code,
        id: engine.nextId(),
        payload: Uint8List(0),
      );
      final Future<PbleFrame> pending = engine.request(cmd);
      await pumpEventQueue();

      transport.deliverFrame(
        PbleFrame(
          type: Pble.typeCmd,
          opcode: cmd.opcode,
          id: cmd.id,
          payload: Uint8List.fromList(<int>[0x55]),
        ),
      );
      transport.deliverFrame(
        PbleFrame(
          type: Pble.typeRsp,
          opcode: cmd.opcode,
          id: cmd.id,
          payload: Uint8List.fromList(<int>[PbleStatus.ok.code, 0x66]),
        ),
      );

      final PbleFrame rsp = await pending;
      expect(rsp.type, Pble.typeRsp);
      expect(rsp.payload, <int>[PbleStatus.ok.code, 0x66]);
    });

    test(
      'reused ID rejects the stale prior-opcode RSP and accepts the new one',
      () async {
        const int reusedId = 91;
        final PbleFrame oldCmd = PbleFrame(
          type: Pble.typeCmd,
          opcode: PbleOpcode.hello.code,
          id: reusedId,
          payload: Uint8List(0),
        );
        final Future<PbleFrame> oldPending = engine.request(oldCmd);
        await pumpEventQueue();
        transport.deliverFrame(
          PbleFrame(
            type: Pble.typeRsp,
            opcode: oldCmd.opcode,
            id: reusedId,
            payload: Uint8List.fromList(<int>[PbleStatus.ok.code, 0x77]),
          ),
        );
        expect((await oldPending).opcode, oldCmd.opcode);

        final PbleFrame newCmd = PbleFrame(
          type: Pble.typeCmd,
          opcode: PbleOpcode.run.code,
          id: reusedId,
          payload: Uint8List(0),
        );
        final Future<PbleFrame> newPending = engine.request(newCmd);
        await pumpEventQueue();
        transport.deliverFrame(
          PbleFrame(
            type: Pble.typeRsp,
            opcode: oldCmd.opcode,
            id: reusedId,
            payload: Uint8List.fromList(<int>[PbleStatus.ok.code, 0x88]),
          ),
        );
        transport.deliverFrame(
          PbleFrame(
            type: Pble.typeRsp,
            opcode: newCmd.opcode,
            id: reusedId,
            payload: Uint8List.fromList(<int>[PbleStatus.ok.code, 0x99]),
          ),
        );

        final PbleFrame rsp = await newPending;
        expect(rsp.type, Pble.typeRsp);
        expect(rsp.opcode, newCmd.opcode);
        expect(rsp.payload, <int>[PbleStatus.ok.code, 0x99]);
      },
    );

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

    test(
      'one deadline bounds aggregate acknowledged multi-fragment writes',
      () async {
        await engine.dispose();
        await transport.dispose();
        transport = FakeByteTransport(
          mtu: 23,
          sendDelay: const Duration(milliseconds: 40),
        );
        engine = PbleEngine(transport);
        final PbleFrame cmd = PbleFrame(
          type: Pble.typeCmd,
          opcode: PbleOpcode.run.code,
          id: engine.nextId(),
          payload: Uint8List.fromList(List<int>.filled(64, 0x78)),
        );
        final Stopwatch elapsed = Stopwatch()..start();

        await expectLater(
          engine.request(cmd, timeout: const Duration(milliseconds: 70)),
          throwsA(isA<PbleTimeoutException>()),
        );
        elapsed.stop();

        expect(transport.sentPackets, isNotEmpty);
        expect(transport.sentPackets.length, lessThan(4));
        expect(
          elapsed.elapsed,
          lessThan(const Duration(milliseconds: 110)),
          reason: 'each fragment must consume the same absolute request budget',
        );
      },
    );

    test(
      'on-time exact RSP wins when its acknowledged write completes late',
      () async {
        await engine.dispose();
        await transport.dispose();
        const int requestId = 92;
        var delivered = false;
        transport = FakeByteTransport(
          sendDelay: const Duration(milliseconds: 40),
          onSendStarted: () {
            if (delivered) return;
            delivered = true;
            transport.deliverFrame(
              PbleFrame(
                type: Pble.typeRsp,
                opcode: PbleOpcode.hello.code,
                id: requestId,
                payload: Uint8List.fromList(<int>[PbleStatus.ok.code, 0xa1]),
              ),
            );
          },
        );
        engine = PbleEngine(transport);
        final PbleFrame cmd = PbleFrame(
          type: Pble.typeCmd,
          opcode: PbleOpcode.hello.code,
          id: requestId,
          payload: Uint8List(0),
        );

        final PbleFrame response = await engine.request(
          cmd,
          timeout: const Duration(milliseconds: 15),
        );

        expect(response.opcode, cmd.opcode);
        expect(response.id, cmd.id);
        expect(response.payload, <int>[PbleStatus.ok.code, 0xa1]);
      },
    );

    test(
      'exact RSP arriving after a pending write deadline still times out',
      () async {
        await engine.dispose();
        await transport.dispose();
        const int requestId = 93;
        Timer? lateResponse;
        transport = FakeByteTransport(
          sendDelay: const Duration(milliseconds: 30),
          onSendStarted: () {
            lateResponse ??= Timer(const Duration(milliseconds: 20), () {
              transport.deliverFrame(
                PbleFrame(
                  type: Pble.typeRsp,
                  opcode: PbleOpcode.hello.code,
                  id: requestId,
                  payload: Uint8List.fromList(<int>[PbleStatus.ok.code, 0xa2]),
                ),
              );
            });
          },
        );
        engine = PbleEngine(transport);
        final PbleFrame cmd = PbleFrame(
          type: Pble.typeCmd,
          opcode: PbleOpcode.hello.code,
          id: requestId,
          payload: Uint8List(0),
        );

        await expectLater(
          engine.request(cmd, timeout: const Duration(milliseconds: 8)),
          throwsA(isA<PbleTimeoutException>()),
        );
        await Future<void>.delayed(const Duration(milliseconds: 35));
        lateResponse?.cancel();
      },
    );
  });
}

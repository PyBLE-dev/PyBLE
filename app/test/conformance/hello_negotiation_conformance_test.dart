// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.
//
// A-10 [red] — HELLO version + capability negotiation against a Fake board.
//
// Drives the REAL client stack (frame codec → fragmentation → PbleEngine →
// HelloNegotiator) over an in-memory [FakeByteTransport]. Verifies protocol.md
// §7 (HELLO is the first exchange; RSP payload = [status:u8][caps]) and §9
// (VER exactly 0x01; the app MUST refuse an unsupported proto_version):
//   • the client offers proto_versions == [1] and sends a HELLO CMD (opcode
//     0x01, type CMD) first (FR-PBLE-5);
//   • it parses [status][caps] and surfaces chip / MicroPython version / free
//     memory / fs root as a DeviceInfo (FR-CONN-1);
//   • a board answering an UNSUPPORTED proto_version is refused with the typed
//     UnsupportedProtocolException (FR-PBLE-6, BLD-7);
//   • a non-OK HELLO status surfaces as a typed §8 exception (S3: the catch-all
//     PbleStatusException is REPLACED by the per-status subtypes, so eInternal
//     maps to EInternal — TDD §14.1, A-11 contract).
//
// SCOPE (S2): the HELLO/caps PAYLOAD byte-serialization is DRAFT and is NOT in
// the shared corpus; this suite asserts against the HIL-observed newline
// key=value caps text (agent v0.4.0) with a TOLERANT parser. Byte-level HELLO
// firmware conformance is deferred until protocol.md §7 freezes the payload
// encoding.
//
// CURRENTLY RED: `lib/pble/{engine,hello,pble_constants,pble_exception}.dart`
// and the extended DeviceInfo do not exist yet. HAND-OFF: `lib/pble/**` →
// app-protocol-engineer.

import 'dart:convert';
import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';

import 'package:pyble/pble/engine.dart';
import 'package:pyble/pble/frame.dart';
import 'package:pyble/pble/hello.dart';
import 'package:pyble/pble/pble_constants.dart';
// EInternal (non-OK HELLO status) reaches us via types.dart's re-export after the
// S3 exception-migration [green]; a direct pble_exception.dart import is redundant.
import 'package:pyble/pble/types.dart';

import '../support/fake_byte_transport.dart';

/// The real agent's HIL-observed caps text (agent v0.4.0), with the chosen
/// [proto] overridable to exercise the version-refusal path.
String capsText({int proto = 1, String label = ''}) => <String>[
  'proto=$proto',
  'agent=0.4.0',
  'chip=esp32-s3',
  'mpy=1.28.0',
  'fs_root=/',
  'mtu=247',
  'window=8',
  'chunk=229',
  'free_mem=8495096',
  'has_sd=0',
  'has_identify=0',
  'identify_led=255',
  'auto_run=0',
  'device_id=5646',
  'label=$label',
].join('\n');

Uint8List helloRspPayload({
  required int status,
  int proto = 1,
  String label = '',
}) => Uint8List.fromList(<int>[
  status,
  ...utf8.encode(capsText(proto: proto, label: label)),
]);

void main() {
  late FakeByteTransport transport;
  late PbleEngine engine;
  late HelloNegotiator negotiator;

  setUp(() {
    transport = FakeByteTransport(mtu: Pble.mtuRequest);
    engine = PbleEngine(transport);
    negotiator = HelloNegotiator(
      engine: engine,
      appName: 'PyBLE',
      appVersion: '0.1.0',
    );
  });

  tearDown(() async {
    await engine.dispose();
    await transport.dispose();
  });

  group('A-10 HELLO negotiation over a Fake board (protocol.md §7/§9)', () {
    test(
      'offers [1], sends a HELLO CMD first, and surfaces DeviceInfo caps',
      () async {
        final Future<HelloResult> pending = negotiator.negotiate();
        await pumpEventQueue();

        // HELLO is the FIRST exchange, and it is a CMD on opcode 0x01 (§7).
        expect(transport.sentFrames, hasLength(1));
        final PbleFrame sent = transport.sentFrames.single;
        expect(sent.type, Pble.typeCmd);
        expect(sent.opcode, PbleOpcode.hello.code);

        transport.deliverFrame(
          PbleFrame(
            type: Pble.typeRsp,
            opcode: PbleOpcode.hello.code,
            id: sent.id,
            payload: helloRspPayload(status: PbleStatus.ok.code),
          ),
        );

        final HelloResult result = await pending;
        expect(result.protoVersion, 1);
        final DeviceInfo caps = result.caps;
        expect(caps.chip, 'esp32-s3');
        expect(caps.mpyVersion, '1.28.0');
        expect(caps.freeMem, 8495096);
        expect(caps.fsRoot, '/');
      },
    );

    test(
      'refuses an unsupported proto_version with UnsupportedProtocolException',
      () async {
        final Future<HelloResult> pending = negotiator.negotiate();
        await pumpEventQueue();
        final PbleFrame sent = transport.sentFrames.single;

        // Board chose proto_version 2, which is not in the client's offer [1].
        transport.deliverFrame(
          PbleFrame(
            type: Pble.typeRsp,
            opcode: PbleOpcode.hello.code,
            id: sent.id,
            payload: helloRspPayload(status: PbleStatus.ok.code, proto: 2),
          ),
        );

        await expectLater(
          pending,
          throwsA(
            isA<UnsupportedProtocolException>()
                .having((e) => e.offered, 'offered', <int>[1])
                .having((e) => e.chosen, 'chosen', 2),
          ),
          reason:
              'a proto_version the client does not support is a typed refusal '
              '(FR-PBLE-6, §9), never a silent failure (BLD-7)',
        );
      },
    );

    test(
      'surfaces a non-OK HELLO status as its typed §8 exception (EInternal)',
      () async {
        final Future<HelloResult> pending = negotiator.negotiate();
        await pumpEventQueue();
        final PbleFrame sent = transport.sentFrames.single;

        transport.deliverFrame(
          PbleFrame(
            type: Pble.typeRsp,
            opcode: PbleOpcode.hello.code,
            id: sent.id,
            payload: helloRspPayload(status: PbleStatus.eInternal.code),
          ),
        );

        // The S2 catch-all PbleStatusException is REPLACED by per-status subtypes
        // (A-11 / TDD §14.1): eInternal (0xFF) → EInternal.
        await expectLater(pending, throwsA(isA<EInternal>()));
      },
    );
  });
}

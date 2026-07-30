// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.
//
// A-10 [red] — PBLE/1 frame-codec conformance against the SHARED corpus.
//
// This is the single cross-language byte-level guard (TDD §8.8): the firmware
// `pyble_proto` codec and this Dart `pble` client BOTH assert against the SAME
// file — `tests/firmware_tests/host/conformance/corpus.json` — loaded relative
// to the repo root and NEVER copied. If the two ends ever disagree on the bytes,
// one of these suites goes red.
//
// For every frozen frame (protocol.md §3.1 frame · §4 opcodes · §8 status, G0/G1
// 2026-07-01) it asserts:
//   • encode(fields)   == frame_hex           (the app produces the exact wire)
//   • decode(frame_hex) == fields             (the app reads the exact wire)
//   • pbleCrc32(VER..PAYLOAD) == corpus crc32 (IEEE/zlib, reflected 0xEDB88320)
// and for the crc_reject vector, decode MUST throw [PbleCrcException] (FR-PBLE-3).
//
// PAYLOADS ARE OPAQUE here (frame codec only); the HELLO/caps (§7) payload
// byte-serialization is still DRAFT and is deliberately NOT in this corpus —
// see hello_negotiation_conformance_test.dart + caps_parser_conformance_test.dart.
//
// CURRENTLY RED: `lib/pble/frame.dart` (PbleFrame/encodeFrame/decodeFrame/
// pbleCrc32) and `lib/pble/pble_exception.dart` (PbleCrcException) do not exist
// yet. HAND-OFF: `lib/pble/**` → app-protocol-engineer.

import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';

import 'package:pyble/pble/frame.dart';
import 'package:pyble/pble/pble_exception.dart';

import '../support/hex.dart';
import '../support/repo_paths.dart';

void main() {
  final Map<String, dynamic> corpus =
      jsonDecode(conformanceCorpus().readAsStringSync())
          as Map<String, dynamic>;
  final List<Map<String, dynamic>> frames = (corpus['frames'] as List)
      .cast<Map<String, dynamic>>();
  final List<Map<String, dynamic>> crcReject = (corpus['crc_reject'] as List)
      .cast<Map<String, dynamic>>();

  group('A-10 frame-codec conformance (SHARED corpus, TDD §8.8)', () {
    test(
      'the shared corpus is loaded relative to the repo root (not copied)',
      () {
        expect(
          conformanceCorpus().existsSync(),
          isTrue,
          reason:
              'corpus.json must be read in place from '
              'tests/firmware_tests/host/conformance/',
        );
        expect(frames, isNotEmpty);
      },
    );

    for (final Map<String, dynamic> f in frames) {
      final String name = f['name'] as String;
      final int type = f['type'] as int;
      final int opcode = f['opcode'] as int;
      final int id = f['id'] as int;
      final String payloadHex = f['payload_hex'] as String;
      final String frameHex = f['frame_hex'] as String;
      final int crc32 = f['crc32'] as int;

      test('encode $name == frozen frame_hex', () {
        final PbleFrame frame = PbleFrame(
          type: type,
          opcode: opcode,
          id: id,
          payload: hexToBytes(payloadHex),
        );
        expect(bytesToHex(encodeFrame(frame)), frameHex);
      });

      test('decode $name == field tuple', () {
        final PbleFrame d = decodeFrame(hexToBytes(frameHex));
        expect(d.type, type);
        expect(d.opcode, opcode);
        expect(d.id, id);
        expect(bytesToHex(d.payload), payloadHex);
      });

      test('crc32 $name matches the zlib oracle (VER..PAYLOAD)', () {
        final List<int> full = hexToBytes(frameHex);
        final List<int> body = full.sublist(0, full.length - 4);
        expect(pbleCrc32(body), crc32);
      });
    }

    for (final Map<String, dynamic> r in crcReject) {
      final String name = r['name'] as String;
      final String frameHex = r['frame_hex'] as String;
      test('decode rejects $name (corrupt CRC) with PbleCrcException', () {
        expect(
          () => decodeFrame(hexToBytes(frameHex)),
          throwsA(isA<PbleCrcException>()),
          reason:
              'a bad CRC must be refused, never silently accepted '
              '(FR-PBLE-3)',
        );
      });
    }
  });
}

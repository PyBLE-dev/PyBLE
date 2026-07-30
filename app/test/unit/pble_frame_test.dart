// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.
//
// A-10 [red] — PBLE/1 frame codec + IEEE CRC-32 (protocol.md §3.1, §8.1).
//
// Unit-level codec checks that complement the shared-corpus conformance suite:
//   • the CRC anchor pbleCrc32("123456789") == 0xcbf43926 (zlib/IEEE, reflected
//     poly 0xEDB88320);
//   • the encode anchor encode(CMD, 0x01, id=7, '') == 010101070000562a0dfa;
//   • LEN is a little-endian u16 over PAYLOAD only;
//   • encode → decode round-trips the field tuple;
//   • a flipped CRC byte → PbleCrcException; a truncated frame → PbleFormatException.
//
// CURRENTLY RED: `lib/pble/frame.dart` + `lib/pble/pble_constants.dart` +
// `lib/pble/pble_exception.dart` do not exist yet. HAND-OFF: `lib/pble/**` →
// app-protocol-engineer.

import 'dart:convert';
import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';

import 'package:pyble/pble/frame.dart';
import 'package:pyble/pble/pble_constants.dart';
import 'package:pyble/pble/pble_exception.dart';

import '../support/hex.dart';

void main() {
  group('A-10 frame codec + CRC-32 (protocol.md §3.1/§8.1)', () {
    test('CRC anchor: pbleCrc32("123456789") == 0xcbf43926', () {
      expect(pbleCrc32(ascii.encode('123456789')), 0xcbf43926);
    });

    test('encode anchor: CMD/0x01/id=7/empty == 010101070000562a0dfa', () {
      final PbleFrame f = PbleFrame(
        type: Pble.typeCmd,
        opcode: PbleOpcode.hello.code,
        id: 7,
        payload: Uint8List(0),
      );
      expect(bytesToHex(encodeFrame(f)), '010101070000562a0dfa');
    });

    test('LEN is a little-endian u16 over the payload', () {
      // A 258-byte payload => LEN bytes [0x02, 0x01] at offsets 4..5.
      final PbleFrame f = PbleFrame(
        type: Pble.typeCmd,
        opcode: 0x20,
        id: 1,
        payload: Uint8List(258),
      );
      final Uint8List bytes = encodeFrame(f);
      expect(bytes[4], 0x02);
      expect(bytes[5], 0x01);
    });

    test('encode → decode round-trips the field tuple', () {
      final PbleFrame f = PbleFrame(
        type: Pble.typeRsp,
        opcode: PbleOpcode.deviceInfo.code,
        id: 42,
        payload: Uint8List.fromList(<int>[0, 1, 2, 3, 4, 5]),
      );
      final PbleFrame d = decodeFrame(encodeFrame(f));
      expect(d.type, f.type);
      expect(d.opcode, f.opcode);
      expect(d.id, f.id);
      expect(d.payload, equals(f.payload));
    });

    test('a flipped CRC byte is rejected with PbleCrcException', () {
      final PbleFrame f = PbleFrame(
        type: Pble.typeCmd,
        opcode: PbleOpcode.hello.code,
        id: 1,
        payload: Uint8List(0),
      );
      final Uint8List bad = Uint8List.fromList(encodeFrame(f));
      bad[bad.length - 1] ^= 0xFF;
      expect(() => decodeFrame(bad), throwsA(isA<PbleCrcException>()));
    });

    test('a truncated frame is rejected with PbleFormatException', () {
      expect(
        () => decodeFrame(Uint8List.fromList(<int>[0x01, 0x01, 0x01])),
        throwsA(isA<PbleFormatException>()),
      );
    });
  });
}

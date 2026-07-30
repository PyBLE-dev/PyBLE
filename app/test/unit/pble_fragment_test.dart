// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.
//
// A-10 [red] — PBLE/1 GATT fragmentation + reassembly (protocol.md §3.2).
//
// The 1-byte FRAG_HDR is: bit7 FIRST, bit6 LAST, bits5..0 index mod 64; the
// receiver concatenates FIRST..LAST. Per-packet payload is sized by MTU
// (mtu - 4: less the 1-byte FRAG_HDR and the 3-byte ATT header). This suite
// asserts, across MTU 23 / 185 / 247:
//   • fragment → reassemble round-trips the message byte-for-byte;
//   • a message that fits one packet is a single FIRST|LAST fragment;
//   • every packet payload is <= mtu - 4;
//   • the FIRST bit is set on the first packet, LAST on the last;
//   • fragment indices increment mod 64 (verified past the 64-fragment wrap).
//
// CURRENTLY RED: `lib/pble/fragment.dart` (PbleFragmenter/PbleReassembler) and
// `lib/pble/pble_constants.dart` do not exist yet. HAND-OFF: `lib/pble/**` →
// app-protocol-engineer.

import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';

import 'package:pyble/pble/fragment.dart';
import 'package:pyble/pble/pble_constants.dart';

Uint8List _message(int size) =>
    Uint8List.fromList(List<int>.generate(size, (i) => i & 0xff));

Uint8List? _reassemble(List<Uint8List> packets) {
  final PbleReassembler r = PbleReassembler();
  Uint8List? out;
  for (final Uint8List p in packets) {
    out = r.offer(p);
  }
  return out;
}

void main() {
  const List<int> mtus = <int>[23, 185, 247];

  group('A-10 fragmentation round-trips across MTU (protocol.md §3.2)', () {
    for (final int mtu in mtus) {
      final int perPacket = mtu - 4;

      // Realistic message sizes: a minimum frame, exactly-one-packet, just over,
      // the corpus 250B RUN frame, and a large message that wraps index mod 64.
      final List<int> sizes = <int>[10, perPacket, perPacket + 1, 260, 4096];

      for (final int size in sizes) {
        test('mtu=$mtu size=$size round-trips byte-for-byte', () {
          final Uint8List msg = _message(size);
          final List<Uint8List> packets = PbleFragmenter(
            mtu: mtu,
          ).fragment(msg);

          for (final Uint8List p in packets) {
            expect(
              p.length - 1,
              lessThanOrEqualTo(perPacket),
              reason: 'per-packet payload must fit mtu-4 at mtu=$mtu',
            );
          }
          expect(
            packets.first[0] & Pble.fragFirst,
            Pble.fragFirst,
            reason: 'first packet carries the FIRST bit',
          );
          expect(
            packets.last[0] & Pble.fragLast,
            Pble.fragLast,
            reason: 'last packet carries the LAST bit',
          );
          for (int i = 0; i < packets.length; i++) {
            expect(
              packets[i][0] & Pble.fragIndexMask,
              i % 64,
              reason: 'fragment index increments mod 64',
            );
          }

          expect(_reassemble(packets), equals(msg));
        });
      }

      test('mtu=$mtu single-packet message is one FIRST|LAST fragment', () {
        final Uint8List msg = _message(perPacket); // fits exactly one packet
        final List<Uint8List> packets = PbleFragmenter(mtu: mtu).fragment(msg);
        expect(packets, hasLength(1));
        expect(packets.single[0] & Pble.fragFirst, Pble.fragFirst);
        expect(packets.single[0] & Pble.fragLast, Pble.fragLast);
        expect(_reassemble(packets), equals(msg));
      });
    }
  });
}

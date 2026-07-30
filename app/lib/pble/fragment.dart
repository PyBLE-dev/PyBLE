// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

import 'dart:typed_data';

import 'pble_constants.dart';

/// Splits a §3.1 message into GATT packets (protocol.md §3.2).
///
/// Each packet is `FRAG_HDR(1) + fragment_data(<= mtu - 4)`, where the header
/// carries `bit7 FIRST`, `bit6 LAST`, and `bits5..0 = index mod 64`. Stateless
/// per call: [fragment] takes a whole message and returns its packet list.
class PbleFragmenter {
  PbleFragmenter({required this.mtu});

  /// The negotiated ATT MTU; the usable fragment payload is `mtu - 4`.
  final int mtu;

  /// Fragments [message] into ordered GATT packets.
  List<Uint8List> fragment(Uint8List message) {
    final int perPacket = mtu - Pble.fragReserved;
    if (perPacket < 1) {
      throw ArgumentError.value(
        mtu,
        'mtu',
        'mtu must exceed the 4-byte reserve',
      );
    }

    final List<Uint8List> packets = <Uint8List>[];
    final int total = message.length;
    int offset = 0;
    int index = 0;
    do {
      final int end = (offset + perPacket) < total
          ? (offset + perPacket)
          : total;
      final bool isFirst = offset == 0;
      final bool isLast = end == total;

      int header = index % 64;
      if (isFirst) header |= Pble.fragFirst;
      if (isLast) header |= Pble.fragLast;

      final int dataLen = end - offset;
      final Uint8List packet = Uint8List(1 + dataLen);
      packet[0] = header;
      packet.setRange(1, 1 + dataLen, message, offset);
      packets.add(packet);

      offset = end;
      index++;
    } while (offset < total);

    return packets;
  }
}

/// Reassembles GATT packets back into a §3.1 message (protocol.md §3.2).
///
/// The receiver concatenates fragment data from the FIRST packet through the
/// LAST packet. Stateful across [offer] calls for one message; a FIRST packet
/// resets any partial buffer, and a stray fragment before FIRST is dropped.
class PbleReassembler {
  final BytesBuilder _buffer = BytesBuilder();
  bool _inProgress = false;

  /// Offers one inbound [packet]. Returns the complete message when the LAST
  /// fragment arrives, otherwise `null`.
  Uint8List? offer(Uint8List packet) {
    if (packet.isEmpty) return null; // malformed: no FRAG_HDR
    final int header = packet[0];
    final bool isFirst = (header & Pble.fragFirst) != 0;
    final bool isLast = (header & Pble.fragLast) != 0;

    if (isFirst) {
      _buffer.clear();
      _inProgress = true;
    }
    if (!_inProgress) return null; // stray fragment without a FIRST; drop it

    _buffer.add(Uint8List.sublistView(packet, 1));

    if (isLast) {
      _inProgress = false;
      return _buffer.takeBytes();
    }
    return null;
  }
}

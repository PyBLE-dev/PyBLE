// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

import 'dart:typed_data';

import 'pble_constants.dart';
import 'pble_exception.dart';

/// A decoded PBLE/1 message frame (protocol.md §3.1, after reassembly).
///
/// Layout on the wire:
/// `VER(1) TYPE(1) OPCODE(1) ID(1) LEN(2 LE) PAYLOAD(LEN) CRC32(4 LE)`.
/// The CRC covers `VER..PAYLOAD`. This type is a plain value object: the codec
/// below is stateless, so a `Frame` never carries transport or CRC state.
class PbleFrame {
  const PbleFrame({
    required this.type,
    required this.opcode,
    required this.id,
    required this.payload,
  });

  /// §3.1 TYPE (see [Pble.typeCmd]/[Pble.typeRsp]/[Pble.typeEvt]).
  final int type;

  /// §4 OPCODE byte.
  final int opcode;

  /// §3.1 ID — 1–255 for CMD/RSP correlation, `0` for EVT.
  final int id;

  /// The opaque payload (LEN bytes). The frame codec does not interpret it.
  final Uint8List payload;
}

// --- IEEE CRC-32 (zlib-compatible, reflected poly 0xEDB88320) --------------

final Uint32List _crcTable = _buildCrcTable();

Uint32List _buildCrcTable() {
  final Uint32List table = Uint32List(256);
  for (int n = 0; n < 256; n++) {
    int c = n;
    for (int k = 0; k < 8; k++) {
      c = (c & 1) != 0 ? (0xedb88320 ^ (c >> 1)) : (c >> 1);
    }
    table[n] = c;
  }
  return table;
}

/// IEEE/zlib CRC-32 over [bytes] (protocol.md §3.1/§8.1).
///
/// Reflected poly `0xEDB88320`, init `0xFFFFFFFF`, final XOR `0xFFFFFFFF`.
/// Anchor: `pbleCrc32(ascii "123456789") == 0xcbf43926`. Returns an unsigned
/// 32-bit value.
int pbleCrc32(List<int> bytes) {
  int crc = 0xffffffff;
  for (final int b in bytes) {
    crc = _crcTable[(crc ^ b) & 0xff] ^ (crc >> 8);
  }
  return (crc ^ 0xffffffff) & 0xffffffff;
}

// --- Frame codec ------------------------------------------------------------

/// Encodes a [PbleFrame] to its exact §3.1 wire bytes (with CRC appended, LE).
///
/// Anchor: `encode(CMD, 0x01, id=7, '') == 010101070000562a0dfa`.
Uint8List encodeFrame(PbleFrame f) {
  final Uint8List payload = f.payload;
  final int len = payload.length;
  // VER TYPE OPCODE ID LEN(2 LE) PAYLOAD — the CRC covers exactly this span.
  final Uint8List body = Uint8List(6 + len);
  body[0] = Pble.version;
  body[1] = f.type & 0xff;
  body[2] = f.opcode & 0xff;
  body[3] = f.id & 0xff;
  body[4] = len & 0xff;
  body[5] = (len >> 8) & 0xff;
  body.setRange(6, 6 + len, payload);

  final int crc = pbleCrc32(body);
  final Uint8List out = Uint8List(body.length + 4);
  out.setRange(0, body.length, body);
  out[body.length] = crc & 0xff;
  out[body.length + 1] = (crc >> 8) & 0xff;
  out[body.length + 2] = (crc >> 16) & 0xff;
  out[body.length + 3] = (crc >> 24) & 0xff;
  return out;
}

/// Decodes §3.1 wire bytes to a [PbleFrame], verifying the CRC-32.
///
/// Throws [PbleFormatException] if the buffer is too short or its declared LEN
/// does not match, and [PbleCrcException] if the CRC is wrong — a CRC-failed
/// frame is REFUSED, never returned with a payload (FR-PBLE-3).
PbleFrame decodeFrame(Uint8List bytes) {
  // Minimum frame: 6-byte header + 0-byte payload + 4-byte CRC.
  if (bytes.length < 10) {
    throw PbleFormatException(
      'frame too short: ${bytes.length} bytes (min 10)',
    );
  }
  final int type = bytes[1];
  final int opcode = bytes[2];
  final int id = bytes[3];
  final int len = bytes[4] | (bytes[5] << 8);
  final int expected = 6 + len + 4;
  if (bytes.length != expected) {
    throw PbleFormatException(
      'length mismatch: LEN=$len implies $expected bytes, have ${bytes.length}',
    );
  }

  final int crcOffset = 6 + len;
  final int stored =
      (bytes[crcOffset]) |
      (bytes[crcOffset + 1] << 8) |
      (bytes[crcOffset + 2] << 16) |
      (bytes[crcOffset + 3] << 24);
  final int computed = pbleCrc32(bytes.sublist(0, crcOffset));
  if ((stored & 0xffffffff) != computed) {
    throw PbleCrcException(
      'crc mismatch: stored '
      '0x${(stored & 0xffffffff).toRadixString(16)} != computed '
      '0x${computed.toRadixString(16)}',
    );
  }

  return PbleFrame(
    type: type,
    opcode: opcode,
    id: id,
    payload: Uint8List.sublistView(bytes, 6, crcOffset),
  );
}

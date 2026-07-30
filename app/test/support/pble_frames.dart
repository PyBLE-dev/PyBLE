// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.
//
// Test-support: PBLE/1 payload + frame builders for the S3 run/console (A-11)
// and file-op (A-12) conformance suites — the byte layer those suites assert
// the client against.
//
// Every layout here mirrors the FROZEN + HIL-verified wire in
// docs/specifications/protocol.md §5 (files), §6 (run/console) and §8 (status);
// nothing is invented. All multi-byte fields are little-endian. These builders
// let a conformance suite (a) script exact RSP/EVT frames back to the client
// over a [FakeByteTransport] and (b) decode the frames the client SENT to assert
// it encoded the request byte-for-byte.
//
// Owner: app-test-author (the scaffold that SCRIPTS the Fake board — not the
// production codec). It drives the REAL `lib/pble` frame codec via [PbleFrame].

import 'dart:convert';
import 'dart:typed_data';

import 'package:pyble/pble/frame.dart';
import 'package:pyble/pble/pble_constants.dart';

// --- little-endian scalar writers (protocol.md §5 "All multi-byte LE") -------

/// One unsigned byte.
List<int> u8(int v) => <int>[v & 0xff];

/// An unsigned 16-bit little-endian value.
List<int> u16le(int v) => <int>[v & 0xff, (v >> 8) & 0xff];

/// An unsigned 32-bit little-endian value.
List<int> u32le(int v) => <int>[
  v & 0xff,
  (v >> 8) & 0xff,
  (v >> 16) & 0xff,
  (v >> 24) & 0xff,
];

/// A `[plen:u16][path UTF-8]` field (protocol.md §5, max 128 B on the wire).
List<int> pathField(String path) {
  final List<int> bytes = utf8.encode(path);
  return <int>[...u16le(bytes.length), ...bytes];
}

// --- little-endian scalar readers (for asserting what the client SENT) -------

/// Reads an unsigned 16-bit LE value at [offset].
int readU16le(List<int> b, int offset) => b[offset] | (b[offset + 1] << 8);

/// Reads an unsigned 32-bit LE value at [offset].
int readU32le(List<int> b, int offset) =>
    b[offset] |
    (b[offset + 1] << 8) |
    (b[offset + 2] << 16) |
    (b[offset + 3] << 24);

// --- frame builders (a Fake-board reply, delivered via deliverFrame) ---------

/// A RSP frame on [opcode] correlated to [id] carrying [payload].
PbleFrame rsp(PbleOpcode opcode, int id, List<int> payload) => PbleFrame(
  type: Pble.typeRsp,
  opcode: opcode.code,
  id: id,
  payload: Uint8List.fromList(payload),
);

/// A status-only RSP (`[status:u8]`) — the shape of STOP/DELETE/MKDIR/RENAME/
/// PUT_END/RUN replies (protocol.md §8).
PbleFrame statusRsp(PbleOpcode opcode, int id, PbleStatus status) =>
    rsp(opcode, id, u8(status.code));

/// An EVT frame (`ID = 0`) on [opcode] carrying [payload] (protocol.md §3.1).
PbleFrame evt(PbleOpcode opcode, List<int> payload) => PbleFrame(
  type: Pble.typeEvt,
  opcode: opcode.code,
  id: Pble.evtId,
  payload: Uint8List.fromList(payload),
);

// --- §6 RUN / CONSOLE payloads ----------------------------------------------

/// `RUN 0x20` request body `[mode:u8][data]` — mode 0=file / 1=source.
List<int> runPayload(int mode, String data) => <int>[
  ...u8(mode),
  ...utf8.encode(data),
];

/// `RUN_STATE 0x40` EVT body `[state:u8]` (0 idle / 1 running / 2 done / 3 err).
List<int> runStatePayload(int state) => u8(state);

/// `CONSOLE_DATA 0x30` EVT body `[stream:u8][bytes]` — stream 0=stdout/1=stderr.
List<int> consoleDataPayload(int stream, List<int> bytes) => <int>[
  ...u8(stream),
  ...bytes,
];

// --- §5 FILE payloads (Fake-board replies + events) --------------------------

/// A single `FILE_LIST` entry `{[etype:u8][esize:u32][nlen:u16][name]}`.
List<int> fileEntry({
  required bool isDir,
  required int size,
  required String name,
}) {
  final List<int> nameBytes = utf8.encode(name);
  return <int>[
    ...u8(isDir ? 1 : 0),
    ...u32le(size),
    ...u16le(nameBytes.length),
    ...nameBytes,
  ];
}

/// `FILE_LIST 0x10` OK RSP body: `[status][more:u8][count:u16]` + entries.
List<int> fileListOkPayload({
  required bool more,
  required List<List<int>> entries,
}) => <int>[
  ...u8(PbleStatus.ok.code),
  ...u8(more ? 1 : 0),
  ...u16le(entries.length),
  for (final List<int> e in entries) ...e,
];

/// `FILE_GET_BEGIN 0x12` OK RSP body: `[status][total_size:u32]`.
List<int> getBeginOkPayload(int totalSize) => <int>[
  ...u8(PbleStatus.ok.code),
  ...u32le(totalSize),
];

/// `FILE_GET_DATA 0x13` EVT body `[offset:u32][bytes]`.
List<int> getDataPayload(int offset, List<int> bytes) => <int>[
  ...u32le(offset),
  ...bytes,
];

/// `FILE_GET_END 0x14` EVT body `[crc32:u32]` (whole file over `[0,total)`).
List<int> getEndPayload(int crc32) => u32le(crc32);

/// `FILE_PUT_BEGIN 0x15` OK RSP body: `[status][resume_offset:u32]`.
List<int> putBeginOkPayload(int resumeOffset) => <int>[
  ...u8(PbleStatus.ok.code),
  ...u32le(resumeOffset),
];

/// `FILE_PUT_ACK 0x41` EVT body `[ack_offset:u32]` (cumulative watermark).
List<int> putAckPayload(int ackOffset) => u32le(ackOffset);

// --- decoders for what the CLIENT sent (assert request encoding) -------------

/// Decodes a `RUN 0x20` request body into `(mode, dataBytes)`.
(int, Uint8List) decodeRunPayload(Uint8List p) =>
    (p[0], Uint8List.sublistView(p, 1));

/// Decodes a `[plen:u16][path]` request body into its UTF-8 path.
String decodePathPayload(Uint8List p) {
  final int plen = readU16le(p, 0);
  return utf8.decode(p.sublist(2, 2 + plen));
}

/// Decodes a `FILE_GET_BEGIN 0x12` request `[offset:u32][plen][path]`.
(int, String) decodeGetBeginPayload(Uint8List p) {
  final int offset = readU32le(p, 0);
  final int plen = readU16le(p, 4);
  return (offset, utf8.decode(p.sublist(6, 6 + plen)));
}

/// Decodes a `FILE_PUT_BEGIN 0x15` request `[total:u32][crc:u32][plen][path]`.
(int, int, String) decodePutBeginPayload(Uint8List p) {
  final int total = readU32le(p, 0);
  final int crc = readU32le(p, 4);
  final int plen = readU16le(p, 8);
  return (total, crc, utf8.decode(p.sublist(10, 10 + plen)));
}

/// Decodes a `FILE_PUT_DATA 0x16` chunk `[offset:u32][bytes]`.
(int, Uint8List) decodePutDataPayload(Uint8List p) =>
    (readU32le(p, 0), Uint8List.sublistView(p, 4));

/// Decodes a `FILE_RENAME 0x1A` request `[slen][src][dlen][dst]`.
(String, String) decodeRenamePayload(Uint8List p) {
  final int slen = readU16le(p, 0);
  final String src = utf8.decode(p.sublist(2, 2 + slen));
  final int dOff = 2 + slen;
  final int dlen = readU16le(p, dOff);
  final String dst = utf8.decode(p.sublist(dOff + 2, dOff + 2 + dlen));
  return (src, dst);
}

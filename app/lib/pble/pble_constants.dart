// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

/// The SINGLE PBLE/1 constants mirror (TDD D7).
///
/// Every wire number the client uses is mirrored here ONCE, sourced verbatim
/// from the FROZEN docs/specifications/protocol.md — never invented inline. A
/// protocol freeze update touches only this file. Nothing in `lib/pble` (or
/// anywhere else) hard-codes an opcode, status, UUID, TYPE, VER, or frag-header
/// bit; they all resolve through the symbols below.
///
/// Sources: protocol.md §2 (GATT/UUIDs/MTU), §3.1 (frame VER/TYPE/ID),
/// §3.2 (fragmentation header bits), §4 (opcodes), §8 (status), §9 (versioning).
library;

/// Scalar wire constants (protocol.md §2/§3/§9).
abstract final class Pble {
  Pble._();

  /// Frame VER byte — v1.0 serves EXACTLY `0x01` (§3.1, §9).
  static const int version = 0x01;

  /// Baseline protocol version the app negotiates (BLD-7, §9).
  static const int protoVersion = 1;

  /// The `proto_versions[]` the client offers in HELLO (§7, §9).
  static const List<int> protoOffer = <int>[1];

  // --- §2 GATT UUIDs (base 7079626c-… encodes ASCII `pybl`). ---

  /// Primary service UUID (§2).
  static const String serviceUuid = '7079626c-1ab1-4d50-9e3a-000000000001';

  /// RX characteristic (app → board): Write / Write-Without-Response (§2).
  static const String rxUuid = '7079626c-1ab1-4d50-9e3a-000000000002';

  /// TX characteristic (board → app): Notify (§2).
  static const String txUuid = '7079626c-1ab1-4d50-9e3a-000000000003';

  /// INFO characteristic (board → app): Read; returns the DEVICE_INFO caps (§2).
  static const String infoUuid = '7079626c-1ab1-4d50-9e3a-000000000004';

  /// Default advertised-name prefix, `PyBLE-XXXX` (§2).
  static const String namePrefix = 'PyBLE-';

  /// Requested ATT MTU (§2); the link falls back to the BLE default if refused.
  static const int mtuRequest = 247;

  // --- §3.1 frame TYPE ---

  /// TYPE = CMD (§3.1).
  static const int typeCmd = 0x01;

  /// TYPE = RSP (§3.1).
  static const int typeRsp = 0x02;

  /// TYPE = EVT (§3.1).
  static const int typeEvt = 0x03;

  /// EVT frames use `ID = 0`; request IDs are 1–255 (§3.1).
  static const int evtId = 0x00;

  // --- §3.2 fragmentation header bits ---

  /// FRAG_HDR bit7 — FIRST packet of a message (§3.2).
  static const int fragFirst = 0x80;

  /// FRAG_HDR bit6 — LAST packet of a message (§3.2).
  static const int fragLast = 0x40;

  /// FRAG_HDR bits5..0 — fragment index mod 64 (§3.2).
  static const int fragIndexMask = 0x3f;

  /// Bytes reserved per GATT packet: the 1-byte FRAG_HDR + the 3-byte ATT
  /// header. The usable fragment payload is `mtu - 4` (§2/§3.2).
  static const int fragReserved = 4;
}

/// PBLE/1 opcodes (protocol.md §4). The enum value IS the wire byte.
enum PbleOpcode {
  hello(0x01),
  deviceInfo(0x02),
  fileList(0x10),
  fileStat(0x11),
  fileGetBegin(0x12),
  fileGetData(0x13),
  fileGetEnd(0x14),
  filePutBegin(0x15),
  filePutData(0x16),
  filePutEnd(0x17),
  fileDelete(0x18),
  mkdir(0x19),
  fileRename(0x1a),
  run(0x20),
  stop(0x21),
  softReboot(0x22),
  setAutorun(0x23),
  consoleData(0x30),
  consoleInput(0x31),
  runState(0x40),
  filePutAck(0x41),
  setLabel(0x50),
  setIdentifyLed(0x51),
  identify(0x52);

  const PbleOpcode(this.code);

  /// The 1-byte OPCODE on the wire.
  final int code;

  /// Resolves a wire byte to its opcode, or `null` if unknown (§9 additive).
  static PbleOpcode? fromCode(int c) {
    for (final PbleOpcode o in PbleOpcode.values) {
      if (o.code == c) return o;
    }
    return null;
  }
}

/// PBLE/1 1-byte status codes (protocol.md §8). The enum value IS the wire byte.
enum PbleStatus {
  ok(0x00),
  eBadReq(0x01),
  eNoEnt(0x02),
  eAcces(0x03),
  eNoSpc(0x04),
  eIo(0x05),
  eNoMem(0x06),
  eBusy(0x07),
  eCrc(0x08),
  eRange(0x09),
  eUnsupported(0x0a),
  eInternal(0xff);

  const PbleStatus(this.code);

  /// The 1-byte status on the wire.
  final int code;

  /// Resolves a wire byte to its status, or `null` if unknown.
  static PbleStatus? fromCode(int c) {
    for (final PbleStatus s in PbleStatus.values) {
      if (s.code == c) return s;
    }
    return null;
  }
}

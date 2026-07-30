// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

import 'pble_constants.dart';

/// The typed PBLE/1 error hierarchy (FR-PBLE-13, protocol.md §8/§9).
///
/// `lib/pble` NEVER leaks a raw status byte, frame, or transport error upward:
/// every failure surfaces as one of these neutral, ASCII-only types so the UI
/// can branch and localize. Each FROZEN §8 status maps to ONE distinct final
/// subtype (a table-driven map — see [pbleExceptionForStatus]) SHARED by the run
/// and file verbs, so a caller can `catch` the exact failure regardless of which
/// op produced it. No display text is carried here.
sealed class PbleException implements Exception {
  const PbleException([this.message]);

  /// Optional ASCII diagnostic (never user-facing copy; the UI localizes).
  final String? message;

  @override
  String toString() =>
      message == null ? runtimeType.toString() : '$runtimeType: $message';
}

/// The board answered with a `proto_version` the client did not offer (§9,
/// FR-PBLE-6). A typed refusal — never a silent failure (BLD-7).
final class UnsupportedProtocolException extends PbleException {
  const UnsupportedProtocolException(this.offered, this.chosen)
    : super('board chose proto_version $chosen, not in offer $offered');

  /// The versions the client offered in HELLO (e.g. `[1]`).
  final List<int> offered;

  /// The version the board selected, which the client cannot speak.
  final int chosen;
}

/// A reassembled frame failed its CRC-32 check at the codec seam (FR-PBLE-3).
/// The frame is DROPPED and never delivered upward as payload.
///
/// NOTE: this is the codec-drop surface only. The §8 `ECRC` status (a board
/// reporting a CRC failure, e.g. a bad whole-file transfer) surfaces as [ECrc].
/// A-13/S4 rewires the reassembly-drop path to also surface as [ECrc]; until
/// then the codec keeps throwing this type (FR-PBLE-3 frame_codec conformance).
final class PbleCrcException extends PbleException {
  const PbleCrcException([super.message]);
}

/// A byte sequence is not a well-formed §3.1 frame (too short, or its declared
/// LEN does not match the buffer).
final class PbleFormatException extends PbleException {
  const PbleFormatException([super.message]);
}

/// A request received no matching RSP within its timeout (NFR-REL, §3.1 ID
/// correlation).
final class PbleTimeoutException extends PbleException {
  const PbleTimeoutException([super.message]);
}

/// The BLE link dropped, or reconnect backoff was exhausted (FR-BLE-4). A
/// neutral, transport-agnostic failure: no `flutter_blue_plus` type crosses the
/// seam (CON-8). The pble layer re-exposes lib/ble link loss as this type.
final class BleLinkException extends PbleException {
  const BleLinkException([super.message]);
}

/// No live board is attached to the stable [Connection] facade: a verb was
/// called while the runtime session was NOT connected — `idle`/`scanning`/
/// `failed`, i.e. before a `connect(id)` published a board or after a
/// `disconnect()` (ADR-0009, FR-CONN-6). A TYPED refusal, never a silent
/// success: the manager's `connection` object identity is stable across the
/// whole session, but its verbs only reach the wire once a board is live.
final class NotConnectedException extends PbleException {
  const NotConnectedException([super.message]);
}

// --- §8 status → one distinct final subtype (FR-PBLE-13, TDD §14.1) ----------
//
// One class per non-OK §8 code; `0x00 OK` is the absence of an exception. The
// names mirror the FROZEN status mnemonics exactly (protocol.md §8). These are
// shared by every verb: a RUN answering EBUSY throws the SAME [EBusy] a file op
// would (the map below is the single source).

/// §8 `0x01 EBADREQ` — malformed request (bad opcode/args/mode).
final class EBadReq extends PbleException {
  const EBadReq([super.message]);
}

/// §8 `0x02 ENOENT` — no such file or directory.
final class ENoEnt extends PbleException {
  const ENoEnt([super.message]);
}

/// §8 `0x03 EACCES` — permission denied (e.g. deleting a non-empty directory).
final class EAcces extends PbleException {
  const EAcces([super.message]);
}

/// §8 `0x04 ENOSPC` — no space left on the device filesystem.
final class ENoSpc extends PbleException {
  const ENoSpc([super.message]);
}

/// §8 `0x05 EIO` — a low-level I/O error on the board.
final class EIo extends PbleException {
  const EIo([super.message]);
}

/// §8 `0x06 ENOMEM` — the board is out of memory.
final class ENoMem extends PbleException {
  const ENoMem([super.message]);
}

/// §8 `0x07 EBUSY` — an op is already in progress (a program is running, or a
/// transfer is active). The single active-writer guard (SEC-2) surfaces this.
final class EBusy extends PbleException {
  const EBusy([super.message]);
}

/// §8 `0x08 ECRC` — a CRC check failed on the board (e.g. a bad whole-file
/// upload), OR a client-side whole-file CRC/size verification failed on
/// download (FR-PBLE-9). A transfer NEVER reports success on a CRC/size mismatch.
final class ECrc extends PbleException {
  const ECrc([super.message]);
}

/// §8 `0x09 ERANGE` — a value/length is out of the allowed range (e.g. a path
/// over 128 bytes, or an incomplete transfer).
final class ERange extends PbleException {
  const ERange([super.message]);
}

/// §8 `0x0A EUNSUPPORTED` — the board does not support the requested capability
/// (e.g. `identify()` with no configured identify-LED).
final class EUnsupported extends PbleException {
  const EUnsupported([super.message]);
}

/// §8 `0xFF EINTERNAL` — an unexpected internal error on the board.
final class EInternal extends PbleException {
  const EInternal([super.message]);
}

/// Maps a FROZEN §8 [status] to its distinct typed [PbleException], or `null`
/// for `0x00 OK` (protocol.md §8, TDD §14.1).
///
/// This is THE single, table-driven map from a status byte to a subtype, shared
/// by every RSP-checking verb (run + file ops). Exhaustive over [PbleStatus], so
/// a future status can only be added by extending the frozen enum + this map.
PbleException? pbleExceptionForStatus(PbleStatus status, [String? message]) {
  return switch (status) {
    PbleStatus.ok => null,
    PbleStatus.eBadReq => EBadReq(message),
    PbleStatus.eNoEnt => ENoEnt(message),
    PbleStatus.eAcces => EAcces(message),
    PbleStatus.eNoSpc => ENoSpc(message),
    PbleStatus.eIo => EIo(message),
    PbleStatus.eNoMem => ENoMem(message),
    PbleStatus.eBusy => EBusy(message),
    PbleStatus.eCrc => ECrc(message),
    PbleStatus.eRange => ERange(message),
    PbleStatus.eUnsupported => EUnsupported(message),
    PbleStatus.eInternal => EInternal(message),
  };
}

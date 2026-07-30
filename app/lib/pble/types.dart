// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

/// Neutral, transport-agnostic types shared across the [Connection] seam.
///
/// These are the ONLY shapes that leave `lib/pble` (D2): no widget ever sees a
/// frame, opcode, status byte, MTU, or `flutter_blue_plus` type. All fields use
/// ASCII technical names (FR-I18N-4); any user-facing text is localized by the
/// UI, never carried here.
///
/// S1 carries only [DeviceInfo]; the S3 run/console/file verbs add [RunState],
/// [ConsoleStream]/[ConsoleEvent], [RemoteEntry], [TransferProgress], and
/// [ProgressCb]. `Diagnostics`/`IdentifyLed` land at A-14/S4. The typed
/// [PbleException] hierarchy is a neutral type too, and is re-exported here so
/// UI/tests that depend on `types.dart` get the full outward-facing surface.
library;

import 'dart:typed_data';

export 'pble_exception.dart';

/// Static description of the connected board, from DEVICE_INFO (protocol.md §4
/// `0x02`) / the HELLO caps payload (§7) / the INFO characteristic (§2) — one
/// and the same payload.
///
/// [deviceId] (the stable MAC-derived suffix) and [label] (the user-set device
/// label, or empty) are the screenless-identity fields. Both are DISPLAY-ONLY
/// and must NEVER be used for authorization or to build a board registry
/// (SEC-9, FR-CONN-1): a connection is fully usable with either empty.
///
/// The S2 caps fields ([protoVersion], [agentVersion], [mtu], [window],
/// [chunk], [hasSd], [hasIdentify], [identifyLed], [autoRun]) are ADDITIVE and
/// default-valued (TDD §5.2, frozen 2026-07-02) so existing construction stays
/// source-compatible. At S2 they ride only on `deviceInfo()`; a `Diagnostics`
/// getter reading the same caps lands at A-14/S4. [identifyLed] is a display
/// GPIO int (`255`/none → `null`), never a profile or capability gate (CON-7).
class DeviceInfo {
  const DeviceInfo({
    required this.chip,
    required this.mpyVersion,
    required this.freeMem,
    required this.fsRoot,
    this.deviceId = '',
    this.label = '',
    this.protoVersion = 1,
    this.agentVersion = '',
    this.mtu = 23,
    this.window = 4,
    this.chunk = 0,
    this.hasSd = false,
    this.hasIdentify = false,
    this.identifyLed,
    this.autoRun = false,
  });

  /// Opaque, port-defined chip target identifier.
  ///
  /// Initial examples are `esp32`, `esp32-s3`, and `esp32-c3`; callers must
  /// preserve unknown future values rather than treating this as an enum.
  final String chip;

  /// MicroPython version string reported by the board.
  final String mpyVersion;

  /// Free heap in bytes at the time of the read.
  final int freeMem;

  /// Filesystem root the board exposes, e.g. `/` or `/flash`.
  final String fsRoot;

  /// Stable MAC-derived identity suffix. DISPLAY-ONLY (SEC-9); may be empty.
  final String deviceId;

  /// User-set device label, or empty. DISPLAY-ONLY (SEC-9).
  final String label;

  /// The negotiated PBLE/1 `proto_version` (baseline `1`; §9).
  final int protoVersion;

  /// The PyBLE agent firmware SemVer, or empty if not reported.
  final String agentVersion;

  /// The negotiated ATT MTU (BLE default `23` until negotiated up; §2).
  final int mtu;

  /// The upload window `W` (cumulative-ACK sliding window; §5).
  final int window;

  /// The board's file `DATA` chunk size in bytes (`0` if not reported; §5).
  final int chunk;

  /// Whether the board exposes an SD card.
  final bool hasSd;

  /// Whether the board supports `IDENTIFY` (§4 `0x52`).
  final bool hasIdentify;

  /// The configured identify-LED GPIO, or `null` for none (`255` on the wire).
  /// DISPLAY-ONLY device config — never a routing/pin profile (CON-7).
  final int? identifyLed;

  /// Whether `/main.py` auto-runs at boot (§4 `SET_AUTORUN`).
  final bool autoRun;
}

/// The execution state of user code on the board (protocol.md §6, `RUN_STATE`
/// `0x40 [state:u8]`).
///
/// Maps the wire byte 1:1: `0 idle / 1 running / 2 done / 3 error`. This is the
/// fine-grained run signal for the console/run UI (FR-CONSOLE-3, FR-RUN-3);
/// [ConnState] deliberately never distinguishes idle/done/error — it only
/// DERIVES `ConnState.running` while [RunState.running].
enum RunState {
  /// No program is running.
  idle,

  /// User code is executing.
  running,

  /// The last run finished normally.
  done,

  /// The last run ended with an uncaught error / traceback.
  error,
}

/// Which console stream a [ConsoleEvent] belongs to (protocol.md §6,
/// `CONSOLE_DATA 0x30 [stream:u8]`).
///
/// The wire carries ONLY [stdout] (`0`) and [stderr] (`1`). [system] is
/// CLIENT-SYNTHESIZED by `lib/pble` for app-side notices (e.g. "reconnected") —
/// it NEVER comes off the wire (FR-CONN-3, FR-PBLE-12).
enum ConsoleStream {
  /// Program standard output (wire stream `0`).
  stdout,

  /// Program standard error / tracebacks (wire stream `1`).
  stderr,

  /// A client-synthesized app-side notice; never decoded from `CONSOLE_DATA`.
  system,
}

/// One chunk of console output (protocol.md §6, `CONSOLE_DATA 0x30`).
///
/// [bytes] are the raw UTF-8 output as received — `lib/pble` never trims, decodes
/// display text, or reflows: the console UI owns rendering (D2).
class ConsoleEvent {
  const ConsoleEvent({required this.stream, required this.bytes});

  /// The stream this chunk belongs to.
  final ConsoleStream stream;

  /// The raw output bytes (typically UTF-8, but not validated here).
  final Uint8List bytes;
}

/// A directory entry from `FILE_LIST 0x10` (protocol.md §5).
///
/// [name] is the LEAF entry name (the `name` field of `{etype,esize,nlen,name}`),
/// NOT a full path — the caller composes the path from the listed directory.
class RemoteEntry {
  const RemoteEntry({
    required this.name,
    required this.isDir,
    required this.size,
  });

  /// The leaf entry name within its parent directory.
  final String name;

  /// Whether this entry is a directory (`etype == 1`) vs a file (`etype == 0`).
  final bool isDir;

  /// File size in bytes (`0` for directories).
  final int size;
}

/// Progress of a file transfer (download or upload), reported to a [ProgressCb].
///
/// [sent] is the number of verified/transferred bytes so far; [total] is the
/// full file size. Progress is monotonic non-decreasing and reaches
/// `sent == total` on success.
class TransferProgress {
  const TransferProgress({required this.sent, required this.total});

  /// Bytes transferred so far (downloaded or uploaded-and-ACKed).
  final int sent;

  /// The total file size in bytes.
  final int total;
}

/// Callback invoked with incremental [TransferProgress] during a transfer.
typedef ProgressCb = void Function(TransferProgress progress);

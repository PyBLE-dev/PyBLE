// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

import 'dart:typed_data';

import 'package:flutter/foundation.dart' show ValueListenable;

import 'conn_state.dart';
import 'types.dart';

/// The single seam every widget binds to (FR-PBLE-14, CON-8).
///
/// `lib/pble` is the ONLY layer that knows the PBLE/1 wire; it presents that
/// behaviour EXCLUSIVELY through this interface and the neutral types in
/// [types.dart]. UI code depends on `Connection`, never on `lib/ble` or any
/// transport type (D1/D2). Tests inject a [FakeConnection]; production injects
/// `PbleConnection` (lands A-14/S4).
///
/// This is the S3 slice of the full surface frozen in
/// docs/specifications/app.md §3: observable state, device info, the run/console
/// verbs (A-11), and the file verbs (A-12), plus a lifecycle hook. `Diagnostics`
/// and the identity verbs (setLabel/setIdentifyLed/identify) are additive and
/// land at A-14/S4. No session-lock, heartbeat, or identity-gating verb is EVER
/// added (FR-CONN-8, SEC-9): this exposes only in-scope board-control verbs.
abstract interface class Connection {
  /// The observable link/run state (FR-CONN-5). Widgets watch this via a
  /// `ValueListenableBuilder`; it is read-only from the UI side.
  ///
  /// [ConnState.running] is DERIVED: it shows while [runState] is
  /// [RunState.running], collapsing back to [ConnState.ready] otherwise.
  ValueListenable<ConnState> get state;

  /// Static description of the connected board (FR-CONN-1).
  Future<DeviceInfo> deviceInfo();

  // --- A-11 run / console (FR-PBLE-11/12/13, FR-CONN-2/3/5) -----------------

  /// Runs the file at [path] on the board (`RUN 0x20 [mode=0][UTF-8 path]`).
  ///
  /// Completes on the RSP; throws the typed §8 exception on a non-OK RSP
  /// (e.g. [EBusy] if a program is already running). A program-level failure
  /// (missing file, uncaught exception) is NOT a RSP error — it arrives async as
  /// a stderr [ConsoleEvent] + [RunState.error], and this Future still completes.
  Future<void> runFile(String path);

  /// Runs a source [snippet] on the board (`RUN 0x20 [mode=1][UTF-8 snippet]`).
  /// Same completion/exception semantics as [runFile].
  Future<void> runSource(String snippet);

  /// Stops the running program (`STOP 0x21`). The RSP is ALWAYS OK (idempotent);
  /// safe to call anytime.
  Future<void> stop();

  /// Soft-reboots the board (`SOFT_REBOOT 0x22`). FIRE-THEN-EXPECT-DISCONNECT:
  /// the reset may preempt the RSP, so this returns WITHOUT awaiting one; the
  /// ensuing link drop + reconnect drive the observable [state].
  Future<void> softReboot();

  /// The board's execution state (FR-CONSOLE-3, `RUN_STATE 0x40`).
  Stream<RunState> get runState;

  /// The board's console output (FR-CONN-3, `CONSOLE_DATA 0x30`). Broadcast:
  /// carries wire [ConsoleStream.stdout]/[ConsoleStream.stderr] plus any
  /// client-synthesized [ConsoleStream.system] notices.
  Stream<ConsoleEvent> get console;

  /// Sends [text] to the program's stdin (`CONSOLE_INPUT 0x31`). FIRE-AND-
  /// FORGET: the firmware sends no RSP, so this never awaits a reply.
  Future<void> sendInput(String text);

  // --- A-12 file operations (FR-PBLE-9, FR-CONN-4/9) ------------------------

  /// Lists the directory at [path] (`FILE_LIST 0x10`). Returns exactly the
  /// entries the board reported; a truncated listing is surfaced by the UI, not
  /// re-issued here (the wire has no continuation cursor).
  Future<List<RemoteEntry>> listDir(String path);

  /// Downloads the file at [path] (`FILE_GET_*`), verifying the assembled size
  /// AND the whole-file CRC-32 before returning (FR-PBLE-9); a mismatch throws
  /// [ECrc]. [onProgress] receives monotonic [TransferProgress] to completion.
  Future<Uint8List> getFile(String path, {ProgressCb? onProgress});

  /// Uploads [bytes] to [path] (`FILE_PUT_*`). Success ONLY on the `PUT_END`
  /// RSP OK (an incomplete transfer → [ERange], a CRC mismatch → [ECrc]; the
  /// old file is kept). [onProgress] reports upload progress.
  Future<void> putFile(String path, Uint8List bytes, {ProgressCb? onProgress});

  /// Deletes [path] (`FILE_DELETE 0x18`). A non-empty directory → [EAcces].
  Future<void> delete(String path);

  /// Creates the directory [path] (`MKDIR 0x19`). Existing directory → OK
  /// (idempotent); a path that is an existing file → [EBadReq].
  Future<void> mkdir(String path);

  /// Renames/moves [from] to [to] (`FILE_RENAME 0x1A`).
  Future<void> rename(String from, String to);

  /// Releases resources held by this connection (notifiers, subscriptions).
  ///
  /// After disposal the connection must not be reused.
  Future<void> dispose();
}

/// Optional local capability for a [Connection] facade whose active live board
/// can change while the facade object itself remains stable.
///
/// The value is opaque and comparable by object identity only. It remains the
/// same for one attached connection session and is replaced on every attach or
/// detach. This is strictly an in-memory consistency stamp for multi-verb app
/// actions: it is not board identity, authentication material, a pairing token,
/// or PBLE/1 wire data.
abstract interface class ConnectionSessionStampSource {
  Object get connectionSessionStamp;
}

/// Returns the current local session stamp for [connection].
///
/// Ordinary injected/fake [Connection] implementations need not implement
/// [ConnectionSessionStampSource]. Their own stable object identity is the
/// fallback stamp, preserving the simple Connection-only test seam.
Object connectionSessionStampOf(Connection connection) => switch (connection) {
  ConnectionSessionStampSource source => source.connectionSessionStamp,
  _ => connection,
};

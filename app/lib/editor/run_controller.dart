// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

/// A-16 — the working-loop run-control providers (ADR-0010, TDD §11.6b/e,
/// specs.md FR-RUN §4.8). Two seams:
///
///   * [runAvailabilityProvider] — the derived, read-only availability of the
///     three run actions (Run / Stop / Soft-reboot), computed from the live
///     [ConnState]. The shell toolbar watches it to enable/disable buttons.
///   * [runControllerProvider] — the imperative controller that RUNS the current
///     buffer, runs a board file, stops, and soft-reboots, EXCLUSIVELY through
///     the [Connection] seam (FR-RUN-4). It is the single active writer; the
///     three verbs are the ONLY board-control actions (FR-RUN-1).
///
/// The controller NEVER swallows a typed [EBusy] (or any [PbleException]): it
/// propagates so the shell can surface `runBusyMessage` honestly (FR-RUN-3). No
/// widget here imports `lib/ble` — binding is via `Connection` only (CON-8).
library;

import 'package:flutter/foundation.dart' show ValueListenable, immutable;
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'package:pyble/app/providers.dart';
import 'package:pyble/pble/pble.dart';

import 'editor_document.dart';
import 'program_actions.dart';
import 'smart_punctuation.dart';

/// The derived availability of the three run actions for the current [ConnState]
/// (FR-RUN-3, SEC-2). Read-only chrome state — never a board mutation.
@immutable
class RunAvailability {
  const RunAvailability({
    required this.canRun,
    required this.canStop,
    required this.canSoftReboot,
    required this.isRunning,
  });

  /// Run is available only when connected and idle.
  final bool canRun;

  /// Stop is available only while a program is running.
  final bool canStop;

  /// Soft-reboot is available whenever a board is attached (ready or running).
  final bool canSoftReboot;

  /// Whether a program is currently running (Run disabled, Stop enabled).
  final bool isRunning;

  /// Derives availability from the observable [state] (the frozen table).
  factory RunAvailability.from(ConnState state) => RunAvailability(
    canRun: state == ConnState.ready,
    canStop: state == ConnState.running,
    canSoftReboot: state == ConnState.ready || state == ConnState.running,
    isRunning: state == ConnState.running,
  );

  @override
  bool operator ==(Object other) =>
      other is RunAvailability &&
      other.canRun == canRun &&
      other.canStop == canStop &&
      other.canSoftReboot == canSoftReboot &&
      other.isRunning == isRunning;

  @override
  int get hashCode => Object.hash(canRun, canStop, canSoftReboot, isRunning);
}

/// The derived run-action availability (ADR-0010, TDD §11.6b).
///
/// [ConnState] is exposed by the seam as a `ValueListenable` whose OBJECT
/// identity is stable, so `ref.watch(connStateProvider)` alone would never
/// recompute on a state change. This provider therefore bridges the listenable:
/// it recomputes on every [ConnState] transition — including the derived
/// `running`/`ready` collapse the seam performs when `RunState.running`/`done`
/// arrive (so the toolbar reacts live), and the connect/disconnect transitions
/// (so Run enables the moment a board is ready). No dependency on
/// `runStateProvider` is needed: `ConnState.running` already tracks
/// `RunState.running` at the seam.
final Provider<RunAvailability> runAvailabilityProvider =
    Provider<RunAvailability>((Ref ref) {
      final ValueListenable<ConnState> state = ref.watch(connStateProvider);
      void onChange() => ref.invalidateSelf();
      state.addListener(onChange);
      ref.onDispose(() => state.removeListener(onChange));
      return RunAvailability.from(state.value);
    });

/// The imperative run controller (ADR-0010, TDD §11.6b). Holds no state; reads
/// the live [Connection] and current [EditorDocument] through [Ref] on each call
/// so it always acts on the current board and buffer.
class RunController {
  const RunController(this._ref);

  final Ref _ref;

  Connection get _connection => _ref.read(connectionProvider);

  /// Uploads and runs the current editor buffer as a board file.
  ///
  /// A typed [PbleException] (e.g. [EBusy] when a program is already running) is
  /// NEVER swallowed — it propagates for the shell to surface (FR-RUN-3).
  ///
  /// The buffer is normalized first (FR-ERR), then goes through the shared
  /// file-backed path used by Blocks (ADR-0013): verified `putFile`, followed by
  /// `runFile`. This avoids the inline `runSource` size ceiling.
  Future<void> run() async {
    final EditorDocument document = _ref.read(editorDocumentProvider);
    final String content = document.content;
    final String cleaned = normalizeSmartPunctuation(content);
    if (cleaned != content) {
      _ref.read(editorDocumentProvider.notifier).setContent(cleaned);
    }
    final EditorDocument uploadedDocument = _ref.read(editorDocumentProvider);
    final String path = boardPathForDocument(uploadedDocument);
    await _ref
        .read(programActionsProvider)
        .runSourceFile(path: path, source: cleaned);
    if (_ref.read(editorDocumentProvider) == uploadedDocument) {
      _ref.read(editorDocumentProvider.notifier).markSaved(boardPath: path);
    }
  }

  /// Runs the board file at [path] directly (used when running a saved file).
  Future<void> runFile(String path) => _connection.runFile(path);

  /// Stops the running program. Idempotent-OK at the seam (FR-RUN-1).
  Future<void> stop() => _connection.stop();

  /// Soft-reboots the board (fire-then-expect-disconnect at the seam).
  Future<void> softReboot() => _connection.softReboot();
}

/// The run-control seam every toolbar/editor Run affordance calls (FR-RUN-4).
final Provider<RunController> runControllerProvider = Provider<RunController>(
  (Ref ref) => RunController(ref),
);

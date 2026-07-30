// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

/// PyBLE `lib/editor/` — the working-loop editor + run-control (A-20 / A-16,
/// ADR-0010, TDD §11.6a/b, specs.md FR-EDIT §4.6 / FR-RUN §4.8).
///
/// Exposes the volatile in-memory current document ([editorDocumentProvider]),
/// the derived run-action availability ([runAvailabilityProvider]) and imperative
/// run controller ([runControllerProvider]), and the live editable surface
/// ([EditorView]). Every board action crosses the abstract `Connection` seam
/// (CON-8); nothing here imports `lib/ble/`.
///
/// Deferred (recorded, not dropped): Drift persistence (A-24); syntax
/// highlighting, multi-file tabs, find/replace, external-keyboard shortcuts, and
/// a line-number gutter (FR-EDIT-1..4, OI-1).
library;

export 'editor_document.dart';
export 'editor_view.dart';
export 'program_actions.dart';
export 'run_controller.dart';
export 'save_controller.dart';
export 'smart_punctuation.dart';

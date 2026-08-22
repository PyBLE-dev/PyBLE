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
/// ADR-0012 puts the rich and plain editing implementations behind the exported
/// EditorSurface seam. The rich default supplies Python highlighting and line
/// numbers; session display settings resize code and gutter together. Deferred
/// (recorded, not dropped): Drift persistence (A-24), multi-file tabs,
/// app-owned find/replace, and the remaining external-keyboard shortcuts.
library;

export 'editor_display_settings.dart';
export 'editor_document.dart';
export 'editor_surface.dart';
export 'editor_surface_factory.dart';
export 'editor_view.dart';
export 'plain_editor_surface.dart' show kEditorPlainSurfaceKey;
export 'program_actions.dart';
export 'rich_editor_surface.dart' show kEditorRichSurfaceKey;
export 'run_controller.dart';
export 'save_controller.dart';
export 'smart_punctuation.dart';

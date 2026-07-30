// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

/// PyBLE `lib/files/` — the board file explorer: list/open/upload/download/
/// rename/delete/mkdir over the [Connection] file verbs (A-30, ADR-0010,
/// TDD §11.6d, specs.md FR-FILES §4.5). Binds only to the `Connection` seam
/// (CON-8); never imports `lib/ble/`.
///
/// Exports the controller/state/error-taxonomy ([FileExplorerController],
/// [FileExplorerState], [FileErrorKind], [fileExplorerProvider]) and the
/// [FilesView] surface (+ its [fileErrorMessage] mapping).
library;

export 'file_explorer_controller.dart';
export 'files_view.dart';

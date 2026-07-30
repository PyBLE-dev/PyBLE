// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

/// PyBLE `lib/console/` — the working-loop live console (A-21, ADR-0010, TDD
/// §11.6c, specs.md FR-CONSOLE §4.7).
///
/// Exposes the bounded ring buffer subscribed to `Connection.console`
/// ([consoleBufferProvider] / [kConsoleMaxEvents]), the full interactive Console
/// surface ([ConsoleView]), and the landscape output strip ([ConsoleStripView] /
/// [kConsoleStripHeight]). Streams are differentiated by `SignalCodeColors`; the
/// raw traceback is always shown (annotate-never-hide, FR-ERR-2). Every board
/// action crosses the `Connection` seam (CON-8); nothing here imports `lib/ble/`.
///
/// Deferred (recorded, not dropped): `console_logs` capture (DAT-5, A-24) and
/// the beginner error explainer (FR-ERR-1..4, A-25).
library;

export 'console_controller.dart';
export 'console_view.dart';

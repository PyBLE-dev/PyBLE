// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

/// PyBLE `lib/connect/` — the scan/connect UI, connection diagnostics, and
/// saved boards (see docs/specifications/app.md §2). Scan-connect-use only:
/// no pairing token, no account, no MAC/identity gating (SEC-6, CON-7).
/// Binds only to the `Connection`/`Scanner` seam (CON-8); never imports
/// `lib/ble/`.
///
/// A-22: the scan/connect flow ([ConnectScreen]) + its controller
/// ([ConnectController]/[connectControllerProvider]/[ConnectState]).
library;

export 'connect_controller.dart';
export 'connect_screen.dart';

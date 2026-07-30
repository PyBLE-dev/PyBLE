// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

/// PyBLE `lib/ble/` — the `flutter_blue_plus` adapter: scan filtered to the
/// PyBLE service UUID, GATT connect, MTU 247, byte-stream in / `write` out,
/// connection-state + reconnect (see docs/specifications/app.md §2).
///
/// This is the SOLE package permitted to import the wire transport; per CON-8 /
/// NFR-MAINT-1 only `lib/pble/` may import `lib/ble/`, and no widget may.
///
/// This barrel exports the NEUTRAL seam only — `BleAdapter`, `BleLink`,
/// `BleLinkState`, `BleScanResult`, the reconnect wrapper (`ReconnectingBleLink`,
/// `BleBackoff`, `BleConnect`), and the readiness seam (`BleReadiness`,
/// `BleReadinessSource`). The concrete `flutter_blue_plus` implementations
/// (`FbpBleAdapter`/`FbpBleLink`/`FbpBleReadinessSource`) are imported directly
/// by the `lib/pble` composition root, so importing this barrel never drags a
/// `flutter_blue_plus` type upward.
library;

export 'ble_adapter.dart';
export 'ble_link.dart';
export 'ble_readiness.dart';
export 'ble_reconnect.dart';
export 'ble_scan_result.dart';

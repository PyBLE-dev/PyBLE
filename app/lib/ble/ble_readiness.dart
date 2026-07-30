// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

/// Whether the BLE stack is ready to scan/connect, retyped off the platform so
/// no `flutter_blue_plus` enum crosses the seam (CON-8, FR-BLE-8). The layer
/// above renders a localized rationale from this state LATER (A-22/S5);
/// `lib/ble` surfaces the structured reason only — never display text.
enum BleReadiness {
  /// Adapter powered on and authorized — scan/connect are available.
  ready,

  /// The Bluetooth adapter is powered off.
  adapterOff,

  /// Bluetooth permission was denied or not yet granted.
  unauthorized,

  /// This device has no usable BLE support.
  unsupported,
}

/// A neutral, mockable source of [BleReadiness] transitions (FR-BLE-6/7). The
/// production implementation derives it from the platform adapter state; a fake
/// drives it in tests, so the permission / adapter-off flow verifies with no
/// radio. Surfaced upward through `lib/pble` — adapter-off and permission-denied
/// are never swallowed.
abstract interface class BleReadinessSource {
  /// The latest readiness (what a fresh subscriber should assume).
  BleReadiness get current;

  /// Readiness transitions over time — the reasons stream the UI localizes later.
  Stream<BleReadiness> get readiness;
}

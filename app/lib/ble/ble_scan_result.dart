// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

/// A single filtered scan hit, retyped off the transport so no
/// `flutter_blue_plus` type crosses the `lib/ble` seam (CON-8, NFR-MAINT-1).
///
/// Only PyBLE boards reach this type: the scan is filtered to the PyBLE service
/// UUID at the radio, so a raw, unfiltered device list is never surfaced (CON-1,
/// SEC-4, FR-BLE-1). The picker above (`lib/connect`) renders [name] + [rssi]
/// and remembers [id] as the `board_ref` for reconnect.
class BleScanResult {
  const BleScanResult({
    required this.id,
    required this.name,
    required this.rssi,
  });

  /// The platform-assigned device identifier (iOS UUID / Android MAC-string).
  /// Consumed verbatim by `reconnect` and persisted as the `board_ref` by
  /// `lib/data` — never used to gate the scan (SEC-1/6).
  final String id;

  /// The advertised name, VERBATIM: the user's label when set, else the default
  /// `PyBLE-XXXX` (protocol.md §2). The adapter neither rewrites nor filters by
  /// it — scanning is filtered by service UUID alone.
  final String name;

  /// Advertised signal strength (dBm) at the moment of the hit.
  final int rssi;
}

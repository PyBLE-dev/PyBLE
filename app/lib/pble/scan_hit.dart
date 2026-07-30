// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

/// A single advertised PyBLE board, as the neutral scan seam surfaces it
/// (FR-CONNECT-1, ADR-0009). This is the `lib/ble`-free retyping of a scan hit:
/// a widget lists boards as `ScanHit{id,name,rssi}` and NEVER sees a
/// `BleScanResult`, a service GUID, or a `flutter_blue_plus` type (CON-8,
/// FR-BLE-8, SEC-4). The radio-side scan is filtered to the PyBLE service UUID,
/// so every `ScanHit` is already a PyBLE board — a raw device list is never
/// exposed.
///
/// Equality and [hashCode] are by [id] ALONE. A device advertising again with a
/// refreshed [rssi] (or a changed [name]) is the SAME hit: the newer snapshot
/// supersedes the older by id, so a `Set`/list keyed on `ScanHit` de-dupes to
/// one entry per board while its RSSI keeps updating, and a UI list key stays
/// stable across refreshes.
class ScanHit {
  const ScanHit({required this.id, required this.name, required this.rssi});

  /// The platform-assigned device id (iOS UUID / Android MAC-string), passed
  /// verbatim to `connect(id)` and remembered as the reconnect handle. Never
  /// used to gate the scan or authorize a board (SEC-1/6/9).
  final String id;

  /// The advertised name VERBATIM: the user's label when set, else the default
  /// `PyBLE-XXXX` (protocol.md §2). Display-only.
  final String name;

  /// Advertised signal strength (dBm) at the moment of the hit.
  final int rssi;

  @override
  bool operator ==(Object other) => other is ScanHit && other.id == id;

  @override
  int get hashCode => id.hashCode;

  @override
  String toString() => 'ScanHit($id, $name, ${rssi}dBm)';
}

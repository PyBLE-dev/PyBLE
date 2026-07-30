// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

import 'ble_link.dart';
import 'ble_scan_result.dart';

/// The mockable transport seam: scan for PyBLE boards and open a GATT link to
/// one. This is the interface every conformant adapter honours — the real
/// `FbpBleAdapter` (flutter_blue_plus) in production and the in-memory fake in
/// tests — so scan/connect are exercised without a radio (FR-BLE-7).
///
/// Permissions (A-04) and reconnect (A-03) are deliberately NOT here; they land
/// in later stories.
abstract interface class BleAdapter {
  /// Emits filtered scan hits. Filtering is by the PyBLE service UUID at the
  /// radio ONLY — never by name or identity (CON-1, SEC-4, FR-BLE-1); a raw,
  /// unfiltered device list is never exposed.
  Stream<BleScanResult> scan();

  /// Stops an in-flight scan (FR-BLE-5).
  Future<void> stopScan();

  /// Stops scanning, then opens a GATT connection to [id], subscribes to TX
  /// notifications and requests MTU 247 (FR-BLE-2/5). Returns the byte pipe.
  Future<BleLink> connect(String id);
}

// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

import 'dart:async';

import 'package:flutter_blue_plus/flutter_blue_plus.dart';

// The single wire-constants mirror (D7 / TDD §4.1) lives in lib/pble; the
// adapter references it so UUIDs/MTU are never redefined here (protocol.md §2).
// This is a leaf-constants import, not a widget reaching for the transport, so
// the seam direction (lib/pble → lib/ble) is preserved.
import 'package:pyble/pble/pble_constants.dart';

import 'ble_adapter.dart';
import 'ble_link.dart';
import 'ble_scan_result.dart';
import 'fbp_ble_link.dart';

/// The `flutter_blue_plus` [BleAdapter]. With [FbpBleLink] these are the ONLY
/// files that import `flutter_blue_plus`; nothing else in the app touches a
/// radio type (CON-8, NFR-MAINT-1, FR-BLE-8).
///
/// iOS/Android differences are isolated here (FR-BLE-7):
///   • MTU is requested via `requestMtu` which flutter_blue_plus honours on
///     Android, while iOS negotiates the maximum at connect — either way
///     [connect] degrades gracefully to whatever ATT MTU is negotiated
///     (FR-BLE-2).
///   • The adapter can report not-ready at launch (CoreBluetooth reports
///     powered-on a beat after start-up; Android may need runtime permission),
///     so [scan] waits — bounded — for the adapter to power on before starting,
///     which also drives the first iOS/Android permission prompt. The *reason*
///     an adapter is unusable is surfaced separately by `FbpBleReadinessSource`,
///     so here we simply no-op rather than throw.
///
/// The timeouts below are transport-robustness knobs (not wire constants): they
/// keep a missing radio or an unresponsive peer from hanging the UI. A failed
/// [connect] tears the half-open GATT link back down so a retry starts clean and
/// no connection is leaked; failures propagate so `lib/pble` can surface them as
/// a failed connect attempt (never an uncaught async error).
class FbpBleAdapter implements BleAdapter {
  FbpBleAdapter();

  static final Guid _serviceGuid = Guid(Pble.serviceUuid);
  static final Guid _rxGuid = Guid(Pble.rxUuid);
  static final Guid _txGuid = Guid(Pble.txUuid);

  /// Bounded wait for the adapter to report powered-on before a scan starts.
  static const Duration _adapterReadyTimeout = Duration(seconds: 12);

  /// Bounded GATT connect attempt; a peer that never answers fails cleanly
  /// (surfaced upstream) instead of hanging.
  static const Duration _connectTimeout = Duration(seconds: 20);

  // Tracks whether a scan is wanted, so a `startScan` that was waiting on the
  // adapter to power on does not fire after `stopScan`/`connect` cancelled it.
  bool _scanRequested = false;

  @override
  Stream<BleScanResult> scan() {
    // Filtered to the PyBLE service UUID at the radio ONLY — never by name or
    // identity (CON-1, SEC-4, FR-BLE-1). Every hit is already a PyBLE board, so
    // the advertised name is surfaced verbatim (label or PyBLE-XXXX).
    _scanRequested = true;
    unawaited(_startFilteredScan());
    return FlutterBluePlus.scanResults
        .expand((List<ScanResult> hits) => hits)
        .map(
          (ScanResult r) => BleScanResult(
            id: r.device.remoteId.str,
            name: r.advertisementData.advName,
            rssi: r.rssi,
          ),
        );
  }

  // Wait (bounded) for the adapter to power on, then start the filtered scan.
  // Waiting first avoids the iOS/Android "scanned before the radio was ready"
  // no-op and triggers the platform permission prompt. Any failure is swallowed
  // — the reason is surfaced through `FbpBleReadinessSource`, and this runs
  // unawaited so a throw here must never become an uncaught async error.
  Future<void> _startFilteredScan() async {
    if (FlutterBluePlus.adapterStateNow != BluetoothAdapterState.on) {
      try {
        await FlutterBluePlus.adapterState
            .firstWhere(
              (BluetoothAdapterState s) => s == BluetoothAdapterState.on,
            )
            .timeout(_adapterReadyTimeout);
      } catch (_) {
        return; // off / unauthorized / unsupported / timed out — nothing to scan
      }
    }
    if (!_scanRequested) return; // stopScan()/connect() beat us to it
    try {
      await FlutterBluePlus.startScan(withServices: <Guid>[_serviceGuid]);
    } catch (_) {
      // Surfaced via readiness; never an uncaught async error.
    }
  }

  @override
  Future<void> stopScan() async {
    _scanRequested = false;
    await FlutterBluePlus.stopScan();
  }

  @override
  Future<BleLink> connect(String id) async {
    // Stop scanning BEFORE opening GATT (FR-BLE-5).
    await stopScan();

    final BluetoothDevice device = BluetoothDevice.fromId(id);
    // Connect without auto-MTU so we request PyBLE's MTU explicitly below, and
    // with a bounded timeout so an unreachable board fails instead of hanging.
    await device.connect(mtu: null, timeout: _connectTimeout);

    try {
      final List<BluetoothService> services = await device.discoverServices();
      final BluetoothService service = services.firstWhere(
        (BluetoothService s) => s.uuid == _serviceGuid,
        orElse: () => throw StateError('PyBLE GATT service not found'),
      );
      final BluetoothCharacteristic rx = service.characteristics.firstWhere(
        (BluetoothCharacteristic c) => c.uuid == _rxGuid,
        orElse: () => throw StateError('PyBLE RX characteristic not found'),
      );
      final BluetoothCharacteristic tx = service.characteristics.firstWhere(
        (BluetoothCharacteristic c) => c.uuid == _txGuid,
        orElse: () => throw StateError('PyBLE TX characteristic not found'),
      );

      // Subscribe to TX notifications before returning the pipe.
      await tx.setNotifyValue(true);

      // Request MTU 247 with graceful fallback. flutter_blue_plus' requestMtu is
      // Android-only (it throws elsewhere); on iOS the OS negotiates the maximum
      // at connect, so we swallow and keep the negotiated `mtuNow` (FR-BLE-2/7).
      try {
        await device.requestMtu(Pble.mtuRequest);
      } catch (_) {
        // Keep the negotiated / BLE-default MTU.
      }

      return FbpBleLink(device, rx, tx);
    } catch (_) {
      // The link is half-open (connected, but discovery/subscribe failed). Tear
      // it down so a retry starts clean and no GATT connection is leaked; some
      // stacks also refuse a fresh connect while a stale one is half-open.
      try {
        await device.disconnect();
      } catch (_) {
        // Best-effort cleanup; propagate the ORIGINAL failure below.
      }
      rethrow;
    }
  }
}

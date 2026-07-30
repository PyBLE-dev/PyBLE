// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.
//
// Test-support: a scriptable BLE-readiness source (A-04) — the mockable platform
// seam the permissions/adapter-off DoR calls for (no radio, no fbp). It MODELS
// the contract the production readiness source (derived from
// FlutterBluePlus.adapterState in lib/ble) must satisfy: a neutral
// Stream<BleReadiness> the layer above can render a localized rationale from
// LATER (A-22/S5).
//
// Kept in its OWN file (not fake_ble.dart) so the A-01/A-02 seam suites, which
// import fake_ble.dart, are unaffected by the not-yet-existing BleReadiness type.
//
// Until lib/ble defines BleReadiness + BleReadinessSource, importers compile-fail
// — the intended A-04 [red]. HAND-OFF: `lib/ble/**` → app-ble-engineer.

import 'dart:async';

import 'package:pyble/ble/ble.dart';

/// A scriptable [BleReadinessSource] double. Drive it with [emit].
class FakeBleReadinessSource implements BleReadinessSource {
  final StreamController<BleReadiness> _controller =
      StreamController<BleReadiness>.broadcast();
  BleReadiness _current = BleReadiness.ready;

  @override
  BleReadiness get current => _current;

  @override
  Stream<BleReadiness> get readiness => _controller.stream;

  /// Scripts a readiness transition (updates [current] and notifies listeners).
  void emit(BleReadiness value) {
    _current = value;
    _controller.add(value);
  }

  Future<void> dispose() => _controller.close();
}

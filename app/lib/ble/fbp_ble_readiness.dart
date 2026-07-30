// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

import 'package:flutter_blue_plus/flutter_blue_plus.dart';

import 'ble_readiness.dart';

/// The `flutter_blue_plus` [BleReadinessSource]: derives the neutral
/// [BleReadiness] from `FlutterBluePlus.adapterState`, isolating the platform
/// quirks (FR-BLE-7). On iOS a permission denial surfaces as
/// `BluetoothAdapterState.unauthorized` off the `Info.plist` usage string; on
/// Android the runtime BLE permissions are requested at `startScan`. With
/// [FbpBleAdapter]/[FbpBleLink] this is one of the few files permitted to import
/// `flutter_blue_plus`; the platform enum it maps never crosses the seam (CON-8).
class FbpBleReadinessSource implements BleReadinessSource {
  FbpBleReadinessSource();

  static BleReadiness _map(BluetoothAdapterState state) {
    switch (state) {
      case BluetoothAdapterState.on:
        return BleReadiness.ready;
      case BluetoothAdapterState.unauthorized:
        return BleReadiness.unauthorized;
      case BluetoothAdapterState.unavailable:
        return BleReadiness.unsupported;
      case BluetoothAdapterState.off:
      case BluetoothAdapterState.turningOn:
      case BluetoothAdapterState.turningOff:
      case BluetoothAdapterState.unknown:
        // Not currently usable; conservatively surface adapter-off so the layer
        // above prompts rather than assuming ready.
        return BleReadiness.adapterOff;
    }
  }

  @override
  BleReadiness get current => _map(FlutterBluePlus.adapterStateNow);

  @override
  Stream<BleReadiness> get readiness => FlutterBluePlus.adapterState.map(_map);
}

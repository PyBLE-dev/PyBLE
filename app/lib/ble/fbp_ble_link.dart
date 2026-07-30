// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

import 'dart:async';

import 'package:flutter/foundation.dart' show ValueListenable, ValueNotifier;
import 'package:flutter_blue_plus/flutter_blue_plus.dart';

import 'ble_link.dart';

/// The `flutter_blue_plus` [BleLink]: a pure byte pipe over one GATT connection.
///
/// It interprets NOTHING (FR-BLE-3) — [inbound] forwards TX (…0003)
/// notifications verbatim and [write] pushes bytes to RX (…0002)
/// Write-Without-Response. Along with [FbpBleAdapter] these are the ONLY files
/// permitted to import `flutter_blue_plus`; no such type escapes this seam.
class FbpBleLink implements BleLink {
  FbpBleLink(this._device, this._rx, this._tx) {
    _connSub = _device.connectionState.listen((BluetoothConnectionState s) {
      _linkState.value = s == BluetoothConnectionState.connected
          ? BleLinkState.connected
          : BleLinkState.disconnected;
    });
  }

  final BluetoothDevice _device;
  final BluetoothCharacteristic _rx;
  final BluetoothCharacteristic _tx;

  final ValueNotifier<BleLinkState> _linkState = ValueNotifier<BleLinkState>(
    BleLinkState.connected,
  );
  late final StreamSubscription<BluetoothConnectionState> _connSub;

  @override
  Stream<List<int>> get inbound => _tx.onValueReceived;

  @override
  Future<void> write(List<int> bytes) =>
      _rx.write(bytes, withoutResponse: true);

  @override
  int get mtu => _device.mtuNow;

  @override
  ValueListenable<BleLinkState> get linkState => _linkState;

  @override
  Future<void> disconnect() async {
    await _device.disconnect();
    _linkState.value = BleLinkState.disconnected;
    await _connSub.cancel();
  }
}

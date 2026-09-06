// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

import 'dart:async';

import 'package:flutter_blue_plus/flutter_blue_plus.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:pyble/ble/ble_link.dart';
import 'package:pyble/ble/fbp_ble_link.dart';
import 'package:pyble/pble/pble_constants.dart';

class _Device extends BluetoothDevice {
  _Device(this.failure, {Object? cancelFailure})
    : changes = StreamController<BluetoothConnectionState>(
        onCancel: () async {
          if (cancelFailure != null) throw cancelFailure;
        },
      ),
      super(
        remoteId: const DeviceIdentifier(
          '00000000-0000-0000-0000-000000000001',
        ),
      );
  final Object failure;
  final StreamController<BluetoothConnectionState> changes;
  int disconnectCalls = 0;
  @override
  Stream<BluetoothConnectionState> get connectionState => changes.stream;
  @override
  Future<void> disconnect({
    int timeout = 35,
    bool queue = true,
    int androidDelay = 2000,
  }) async {
    disconnectCalls++;
    throw failure;
  }
}

void main() {
  for (final bool failCancel in <bool>[false, true]) {
    test(
      'native disconnect failure releases subscription (cancel failure $failCancel)',
      () async {
        final StateError failure = StateError('physical disconnect failed');
        final _Device device = _Device(
          failure,
          cancelFailure: failCancel
              ? StateError('subscription cancel failed')
              : null,
        );
        BluetoothCharacteristic characteristic(String uuid) =>
            BluetoothCharacteristic(
              remoteId: device.remoteId,
              serviceUuid: Guid(Pble.serviceUuid),
              characteristicUuid: Guid(uuid),
            );
        final FbpBleLink link = FbpBleLink(
          device,
          characteristic(Pble.rxUuid),
          characteristic(Pble.txUuid),
        );
        expect(device.changes.hasListener, isTrue);
        await expectLater(link.disconnect(), throwsA(same(failure)));
        expect(device.disconnectCalls, 1);
        expect(device.changes.hasListener, isFalse);
        expect(link.linkState.value, BleLinkState.connected);
        await device.changes.close();
      },
    );
  }
}

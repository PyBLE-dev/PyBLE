// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.
//
// A-01 / A-02 [red] — the lib/ble adapter seam contract (mocked transport).
//
// The DoR verifies this story on a MOCKED transport (Fake board), never a real
// ESP32. This suite locks the SEAM the production FbpBleAdapter/FbpBleLink must
// honour, exercised through the conformant fakes in test/support/fake_ble.dart:
//   • BleScanResult exposes id / name / rssi so the picker can show RSSI
//     (FR-BLE-1);
//   • scan() surfaces ONLY PyBLE-XXXX hits — a raw, unfiltered list is a FAIL
//     (CON-1); scan() returns a per-hit Stream, not a raw List;
//   • connect() stops scanning BEFORE opening GATT (FR-BLE-5);
//   • connect() yields a link at the requested MTU 247, and degrades gracefully
//     to the BLE default (23) when the peer negotiates down (FR-BLE-2).
//
// (Deep flutter_blue_plus mapping is verified by app-ble-engineer against a
// mocked platform channel in their [green]; this suite pins the observable
// contract every conformant adapter — including FbpBleAdapter — must satisfy.)
//
// CURRENTLY RED: `lib/ble` does not define the abstract BleAdapter / BleLink /
// BleScanResult / BleLinkState seam yet. HAND-OFF: `lib/ble/**` →
// app-ble-engineer.

import 'package:flutter_test/flutter_test.dart';

import 'package:pyble/ble/ble.dart';
import 'package:pyble/pble/pble_constants.dart';

import '../support/fake_ble.dart';

void main() {
  group('A-01 filtered scan (FR-BLE-1, CON-1)', () {
    test('BleScanResult carries id, name, and rssi', () {
      const BleScanResult hit = BleScanResult(
        id: 'AA:BB',
        name: 'PyBLE-5646',
        rssi: -52,
      );
      expect(hit.id, 'AA:BB');
      expect(hit.name, 'PyBLE-5646');
      expect(hit.rssi, -52);
    });

    test('scan() surfaces only PyBLE-XXXX hits — never a raw list', () async {
      final FakeBleAdapter adapter = FakeBleAdapter()
        ..rawAdvertisements.addAll(const <BleScanResult>[
          BleScanResult(id: '1', name: 'PyBLE-5646', rssi: -40),
          BleScanResult(id: '2', name: 'Some Headphones', rssi: -55),
          BleScanResult(id: '3', name: 'PyBLE-0A1B', rssi: -70),
          BleScanResult(id: '4', name: 'Fitness Band', rssi: -60),
        ]);

      final List<BleScanResult> seen = await adapter.scan().toList();

      expect(
        seen,
        hasLength(2),
        reason: 'the two non-PyBLE devices are dropped',
      );
      for (final BleScanResult r in seen) {
        expect(
          r.name.startsWith(Pble.namePrefix),
          isTrue,
          reason: 'a raw, unfiltered BLE list must never be exposed (CON-1)',
        );
      }
    });
  });

  group('A-02 connect, MTU 247, byte seam (FR-BLE-2/5)', () {
    test('connect() stops scanning before opening GATT (FR-BLE-5)', () async {
      final FakeBleAdapter adapter = FakeBleAdapter();
      // ignore: unused_local_variable
      final Stream<BleScanResult> _ = adapter.scan();
      await adapter.connect('id-1');

      final int stopIdx = adapter.callLog.indexOf('stopScan');
      final int connIdx = adapter.callLog.indexOf('connect');
      expect(stopIdx, isNonNegative);
      expect(connIdx, isNonNegative);
      expect(
        stopIdx,
        lessThan(connIdx),
        reason: 'scanning is stopped before a connection is initiated',
      );
    });

    test('connect() yields a link at the requested MTU 247', () async {
      final FakeBleAdapter adapter = FakeBleAdapter(
        negotiatedMtu: Pble.mtuRequest,
      );
      final BleLink link = await adapter.connect('id-1');
      expect(link.mtu, 247);
      expect(link.linkState.value, BleLinkState.connected);
    });

    test('connect() degrades gracefully to the BLE default MTU (23)', () async {
      final FakeBleAdapter adapter = FakeBleAdapter(negotiatedMtu: 23);
      final BleLink link = await adapter.connect('id-1');
      expect(
        link.mtu,
        23,
        reason: 'a peer that negotiates MTU down must still connect (FR-BLE-2)',
      );
    });
  });
}

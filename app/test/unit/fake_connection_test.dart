// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.
//
// A-05 prerequisite [red] — the minimal lib/pble Connection seam slice
// (ConnState / DeviceInfo / Connection / FakeConnection), per the frozen seam
// contract (app.md §3, TDD §5.2, D5). FakeConnection is a first-class shipped
// test artifact — the thing every UI suite binds to.
//
// NOTE (routing): 05_sprint_backlog.md S1 has no explicit task for this seam
// slice, yet A-05 [green] binds to it. HAND-OFF: `lib/pble/{conn_state,types,
// connection,fake_connection,pble}.dart` → app-protocol-engineer (no wire/BLE
// code in S1). This suite is its acceptance contract.
//
// Non-goal negatives re-asserted here (SEC-9): deviceId/label are DISPLAY-ONLY;
// a connection is fully usable with them empty — the app never gates on them.

import 'package:pyble/pble/pble.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  group('A-05 lib/pble seam slice — FakeConnection', () {
    test('starts in the scripted initial ConnState (default disconnected)', () {
      expect(FakeConnection().state.value, ConnState.disconnected);
      expect(
        FakeConnection(initial: ConnState.ready).state.value,
        ConnState.ready,
      );
    });

    test('emit() drives observable ConnState transitions', () {
      final fake = FakeConnection();
      final seen = <ConnState>[];
      fake.state.addListener(() => seen.add(fake.state.value));

      fake.emit(ConnState.connecting);
      fake.emit(ConnState.ready);
      fake.emit(ConnState.running);

      expect(seen, <ConnState>[
        ConnState.connecting,
        ConnState.ready,
        ConnState.running,
      ]);
    });

    test('deviceInfo() returns the scripted DeviceInfo', () async {
      const info = DeviceInfo(
        chip: 'esp32-c3',
        mpyVersion: '1.28.0',
        freeMem: 40000,
        fsRoot: '/',
        deviceId: 'AB12',
        label: 'lab-bench',
      );
      final got = await FakeConnection(deviceInfo: info).deviceInfo();
      expect(got.chip, 'esp32-c3');
      expect(got.mpyVersion, '1.28.0');
      expect(got.freeMem, 40000);
      expect(got.fsRoot, '/');
      expect(got.deviceId, 'AB12');
      expect(got.label, 'lab-bench');
    });

    test('scriptedDeviceInfo re-scripts device info for later reads', () async {
      final fake = FakeConnection();
      fake.scriptedDeviceInfo = const DeviceInfo(
        chip: 'esp32',
        mpyVersion: '1.28.0',
        freeMem: 12000,
        fsRoot: '/flash',
        deviceId: 'CD34',
        label: '',
      );
      final got = await fake.deviceInfo();
      expect(got.chip, 'esp32');
      expect(got.fsRoot, '/flash');
    });

    test(
      'deviceId/label are DISPLAY-ONLY: usable when empty (SEC-9)',
      () async {
        final fake = FakeConnection(deviceInfo: fakeInfoNoIdentity());
        final got = await fake.deviceInfo();
        // No exception, no gating: an empty deviceId/label must not block use.
        expect(got.deviceId, isEmpty);
        expect(got.label, isEmpty);
        expect(fake.state.value, ConnState.disconnected);
      },
    );

    test('FakeConnection is a Connection (the seam widgets bind to)', () {
      expect(FakeConnection(), isA<Connection>());
    });

    test('dispose() releases the state notifier', () async {
      final fake = FakeConnection();
      await fake.dispose();
      // A disposed ValueNotifier throws on further mutation.
      expect(() => fake.emit(ConnState.ready), throwsA(anything));
    });
  });
}

DeviceInfo fakeInfoNoIdentity() => const DeviceInfo(
  chip: 'esp32-s3',
  mpyVersion: '1.28.0',
  freeMem: 48000,
  fsRoot: '/',
);

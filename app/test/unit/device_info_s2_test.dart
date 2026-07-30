// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.
//
// A-10 [red] — DeviceInfo additive S2 caps extension (TDD §5.2, frozen
// 2026-07-02).
//
// The neutral DeviceInfo grows the S2 caps fields — protoVersion, agentVersion,
// mtu, window, chunk, hasSd, hasIdentify, identifyLed (int?), autoRun — parsed
// from the single HELLO/DEVICE_INFO/INFO caps payload. They are ADDITIVE and
// DEFAULT-VALUED so existing (S1) construction stays source-compatible. This
// suite pins the defaults, that S1 fields are untouched, and that the caps ride
// only on DeviceInfo (no diagnostics getter until A-14/S4).
//
// identifyLed is a display GPIO int?, never a profile/gate (CON-7); deviceId /
// label remain DISPLAY-ONLY (SEC-9).
//
// CURRENTLY RED: `lib/pble/types.dart` has not been extended with the S2 caps
// fields yet. HAND-OFF: `lib/pble/types.dart` → app-protocol-engineer.

import 'package:flutter_test/flutter_test.dart';

import 'package:pyble/pble/types.dart';

void main() {
  group('A-10 DeviceInfo S2 caps extension (TDD §5.2, additive)', () {
    test('S2 caps fields are default-valued (non-breaking) when omitted', () {
      const DeviceInfo d = DeviceInfo(
        chip: 'esp32-s3',
        mpyVersion: '1.28.0',
        freeMem: 0,
        fsRoot: '/',
      );
      expect(d.protoVersion, 1);
      expect(d.agentVersion, '');
      expect(d.mtu, 23); // BLE default until negotiated
      expect(d.window, 4);
      expect(d.chunk, 0);
      expect(d.hasSd, isFalse);
      expect(d.hasIdentify, isFalse);
      expect(d.identifyLed, isNull);
      expect(d.autoRun, isFalse);
      // S1 fields intact.
      expect(d.deviceId, '');
      expect(d.label, '');
    });

    test('every S2 caps field is settable', () {
      const DeviceInfo d = DeviceInfo(
        chip: 'esp32',
        mpyVersion: '1.28.0',
        freeMem: 8495096,
        fsRoot: '/',
        deviceId: '5646',
        label: 'Bench 3',
        protoVersion: 1,
        agentVersion: '0.4.0',
        mtu: 247,
        window: 4,
        chunk: 243,
        hasSd: true,
        hasIdentify: true,
        identifyLed: 8,
        autoRun: true,
      );
      expect(d.agentVersion, '0.4.0');
      expect(d.mtu, 247);
      expect(d.chunk, 243);
      expect(d.hasSd, isTrue);
      expect(d.hasIdentify, isTrue);
      expect(d.identifyLed, 8);
      expect(d.autoRun, isTrue);
      expect(d.label, 'Bench 3');
    });

    test('identifyLed is nullable (255 → none is modelled as null)', () {
      const DeviceInfo d = DeviceInfo(
        chip: 'esp32-c3',
        mpyVersion: '1.28.0',
        freeMem: 0,
        fsRoot: '/',
      );
      expect(d.identifyLed, isNull);
    });
  });
}

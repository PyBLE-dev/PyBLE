// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.
//
// A-22 [red] — the neutral scan seam: `ScanHit`, the `Scanner` interface, and
// the shipped `FakeScanner` double (frozen contract ADR-0009, TDD §4.8/§5.2).
//
// The scan seam is neutral by design: a widget lists advertised boards as
// `ScanHit{id,name,rssi}` WITHOUT ever seeing a BleScanResult, a service GUID,
// or `flutter_blue_plus` (CON-8, FR-BLE-8, SEC-4). `Scanner.scan()` yields an
// ACCUMULATING, deduped-by-id, latest-RSSI snapshot LIST; `FakeScanner` scripts
// those snapshots with no radio.
//
// CURRENTLY RED: `lib/pble` has no `scan_hit.dart` / `scanner.dart`. HAND-OFF:
// `lib/pble/{scan_hit,scanner}.dart` + the `pble.dart` barrel exports →
// app-protocol-engineer. This suite is the acceptance contract for both.

import 'package:flutter_test/flutter_test.dart';

import 'package:pyble/pble/pble.dart';

void main() {
  group('A-22 ScanHit is a neutral advertised-board value', () {
    test('carries id / name / rssi verbatim off the advertisement', () {
      const ScanHit h = ScanHit(id: 'AABB', name: 'PyBLE-8F3A', rssi: -52);
      expect(h.id, 'AABB');
      expect(h.name, 'PyBLE-8F3A');
      expect(h.rssi, -52);
    });

    test('equality + hashCode are by id only (dedup + stable list keys)', () {
      // Same id, DIFFERENT name/rssi → equal (the newer snapshot supersedes the
      // older by id, so the list key stays stable while the RSSI refreshes).
      const ScanHit a1 = ScanHit(id: 'dev-1', name: 'PyBLE-8F3A', rssi: -40);
      const ScanHit a2 = ScanHit(id: 'dev-1', name: 'workbench', rssi: -90);
      const ScanHit b = ScanHit(id: 'dev-2', name: 'PyBLE-8F3A', rssi: -40);

      expect(a1, equals(a2));
      expect(a1.hashCode, a2.hashCode);
      expect(a1, isNot(equals(b)));

      // De-dup semantics fall straight out of id-equality in a Set.
      expect(<ScanHit>{a1, a2, b}, hasLength(2));
    });
  });

  group('A-22 FakeScanner scripts scan snapshots (no radio)', () {
    late FakeScanner scanner;
    setUp(() => scanner = FakeScanner());

    test('is a Scanner', () {
      expect(scanner, isA<Scanner>());
    });

    test('scan() delivers each scripted snapshot LIST in order', () async {
      const ScanHit a = ScanHit(id: 'a', name: 'PyBLE-A', rssi: -50);
      const ScanHit b = ScanHit(id: 'b', name: 'PyBLE-B', rssi: -70);

      final Future<void> expectation = expectLater(
        scanner.scan(),
        emitsInOrder(<List<ScanHit>>[
          <ScanHit>[a],
          <ScanHit>[a, b],
        ]),
      );
      scanner.emit(<ScanHit>[a]);
      scanner.emit(<ScanHit>[a, b]);
      await expectation;
    });

    test('scan()/stopScan() track scanning state + record calls', () async {
      expect(scanner.scanning, isFalse);

      scanner.scan(timeout: const Duration(seconds: 8));
      expect(scanner.scanning, isTrue);
      expect(scanner.scanStartCount, 1);
      expect(scanner.lastTimeout, const Duration(seconds: 8));

      await scanner.stopScan();
      expect(scanner.scanning, isFalse);
      expect(scanner.stopScanCount, 1);
    });

    test('a fresh scan() can run after a stop (re-scan)', () async {
      scanner.scan();
      await scanner.stopScan();

      const ScanHit c = ScanHit(id: 'c', name: 'PyBLE-C', rssi: -60);
      final Future<void> expectation = expectLater(
        scanner.scan(),
        emits(<ScanHit>[c]),
      );
      expect(scanner.scanStartCount, 2);
      scanner.emit(<ScanHit>[c]);
      await expectation;
    });
  });
}

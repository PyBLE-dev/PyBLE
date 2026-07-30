// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.
//
// A-04 [red] — the platform BLE permission declarations exist with the EXACT
// keys/attributes the frozen contract requires (TDD §7.4, IF-5). A file-content
// test over the real iOS Info.plist + Android manifest (the plugin manifest is
// intentionally blank, so the app must declare these itself).
//
//   iOS      NSBluetoothAlwaysUsageDescription
//   Android  BLUETOOTH_SCAN with android:usesPermissionFlags="neverForLocation"
//            BLUETOOTH_CONNECT
//            ACCESS_FINE_LOCATION with android:maxSdkVersion="30" (Android ≤ 11)
//
// CURRENTLY RED: the manifests are the default Flutter templates with no BLE
// permission block. HAND-OFF: `app/ios/Runner/Info.plist` +
// `app/android/app/src/main/AndroidManifest.xml` → app-ble-engineer (permission
// block only; app-build-smith owns the surrounding skeleton).

import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

import '../support/repo_paths.dart';

/// True if a single `<uses-permission …>` element mentions BOTH [a] and [b]
/// (in either attribute order).
bool usesPermissionWithBoth(String xml, String a, String b) {
  final RegExp fwd = RegExp(
    '<uses-permission\\b[^>]*${RegExp.escape(a)}[^>]*${RegExp.escape(b)}[^>]*>',
  );
  final RegExp rev = RegExp(
    '<uses-permission\\b[^>]*${RegExp.escape(b)}[^>]*${RegExp.escape(a)}[^>]*>',
  );
  return fwd.hasMatch(xml) || rev.hasMatch(xml);
}

void main() {
  final String appRoot = appPackageRoot().path;

  group('A-04 iOS BLE usage description (IF-5)', () {
    test('Info.plist declares a board-neutral Bluetooth usage description', () {
      final File plist = File('$appRoot/ios/Runner/Info.plist');
      expect(plist.existsSync(), isTrue, reason: '${plist.path} must exist');
      final String contents = plist.readAsStringSync();
      expect(
        contents,
        contains('NSBluetoothAlwaysUsageDescription'),
        reason: 'iOS requires a Bluetooth usage-description string (FR-BLE-6)',
      );
      expect(
        contents,
        contains(
          'PyBLE uses Bluetooth to connect to compatible MicroPython boards '
          'and run code over the air.',
        ),
      );
      expect(contents, isNot(contains('connect to your ESP32 board')));
    });
  });

  group('A-04 Android BLE permissions (IF-5)', () {
    late String manifest;

    setUp(() {
      final File file = File(
        '$appRoot/android/app/src/main/AndroidManifest.xml',
      );
      expect(file.existsSync(), isTrue, reason: '${file.path} must exist');
      manifest = file.readAsStringSync();
    });

    test('BLUETOOTH_SCAN is declared with neverForLocation', () {
      expect(
        usesPermissionWithBoth(
          manifest,
          'BLUETOOTH_SCAN',
          'android:usesPermissionFlags="neverForLocation"',
        ),
        isTrue,
        reason: 'the service-UUID-filtered scan derives no location (FR-BLE-6)',
      );
    });

    test('BLUETOOTH_CONNECT is declared', () {
      expect(manifest, contains('BLUETOOTH_CONNECT'));
    });

    test('legacy ACCESS_FINE_LOCATION is capped at maxSdkVersion 30', () {
      expect(
        usesPermissionWithBoth(
          manifest,
          'ACCESS_FINE_LOCATION',
          'android:maxSdkVersion="30"',
        ),
        isTrue,
        reason: 'location handling is Android ≤ 11 only (IF-5)',
      );
    });
  });
}

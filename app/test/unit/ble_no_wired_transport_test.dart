// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.
//
// A-02 [red/guard] — BLE is the ONLY transport (CON-2, NFR-COMPAT-3, SEC per
// §1A.3): no USB-serial and no Wi-Fi/socket runtime path exists.
//
// A static source scan of `app/lib/ble/**` — the one layer allowed to touch a
// transport — asserting it references no wired-serial / USB / socket / Wi-Fi /
// mDNS transport. BLE is a first-class-iPad constraint (USB serial is off the
// table by design). This is a STANDING guard that rides every milestone from
// M1: it passes on the S1 barrel and must keep passing after A-01/A-02 fill in
// the flutter_blue_plus adapter.
//
// (Complements tools/ci/import_boundary.sh, which enforces that only lib/pble
// imports lib/ble; this asserts the transport lib/ble reaches for is BLE-only.)

import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

import '../support/repo_paths.dart';

/// Import statements / type references that would betray a non-BLE transport.
final List<RegExp> _forbidden = <RegExp>[
  RegExp(
    r'''import\s+['"]package:[^'"]*(usb|serial|wifi|mdns|nsd|websocket|network_info)[^'"]*['"]''',
  ),
  RegExp(r'\bServerSocket\b'),
  RegExp(r'\bRawDatagramSocket\b'),
  RegExp(r'\bRawSocket\b'),
  RegExp(r'\bSocket\.(connect|startConnect)\b'),
  RegExp(r'\bHttpClient\b'),
  RegExp(r'\bWebSocket\b'),
  RegExp(r'\bSerialPort\b'),
  RegExp(r'\bUsbDevice\b'),
];

void main() {
  group('A-02 BLE-only transport guard (CON-2, NFR-COMPAT-3)', () {
    test('no lib/ble source reaches for a USB / Wi-Fi / socket transport', () {
      final Directory ble = Directory('${appPackageRoot().path}/lib/ble');
      expect(ble.existsSync(), isTrue, reason: 'lib/ble must exist');

      final List<String> offenders = <String>[];
      final Iterable<File> dartFiles = ble
          .listSync(recursive: true)
          .whereType<File>()
          .where((f) => f.path.endsWith('.dart'));

      for (final File f in dartFiles) {
        final String src = f.readAsStringSync();
        for (final RegExp re in _forbidden) {
          if (re.hasMatch(src)) {
            offenders.add('${f.path} matches ${re.pattern}');
          }
        }
      }

      expect(
        offenders,
        isEmpty,
        reason:
            'BLE is the only transport path; no USB-serial or Wi-Fi '
            'runtime path may exist under lib/ble — $offenders',
      );
    });
  });
}

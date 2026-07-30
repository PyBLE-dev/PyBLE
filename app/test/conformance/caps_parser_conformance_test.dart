// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.
//
// A-10 [red] — caps parser conformance against the REAL agent caps text.
//
// protocol.md §7: caps is newline-separated ASCII `key=value` text. This suite
// pins `parseCaps()` against the HIL-observed payload from agent v0.4.0 on an
// ESP32-S3 (device_id 5646), plus the additive-versioning tolerance §9 requires:
//   • every frozen key maps to the right DeviceInfo field + type;
//   • an EMPTY label parses to '' (label is optional, screenless identity);
//   • a SET label parses verbatim (display-only, SEC-9);
//   • identify_led=255 → none (int? null); a real GPIO int parses through;
//   • has_sd / has_identify / auto_run 0|1 → bool;
//   • UNKNOWN keys are ignored, never fatal (additive caps, §9).
//
// deviceId / label are DISPLAY-ONLY and never gate access or build a registry
// (SEC-9); identify_led is a display GPIO int, never a profile/gate (CON-7).
//
// CURRENTLY RED: `lib/pble/hello.dart` (parseCaps) and the extended DeviceInfo
// caps fields do not exist yet. HAND-OFF: `lib/pble/**` → app-protocol-engineer.

import 'package:flutter_test/flutter_test.dart';

import 'package:pyble/pble/hello.dart';
import 'package:pyble/pble/types.dart';

/// The exact caps text the real agent (v0.4.0) returned over HIL.
const String realAgentCaps =
    'proto=1\n'
    'agent=0.4.0\n'
    'chip=esp32-s3\n'
    'mpy=1.28.0\n'
    'fs_root=/\n'
    'mtu=247\n'
    'window=8\n'
    'chunk=229\n'
    'free_mem=8495096\n'
    'has_sd=0\n'
    'has_identify=0\n'
    'identify_led=255\n'
    'auto_run=0\n'
    'device_id=5646\n'
    'label=';

void main() {
  group('A-10 caps parser conformance (protocol.md §7, real agent v0.4.0)', () {
    test('maps every frozen caps key to the right DeviceInfo field', () {
      final DeviceInfo d = parseCaps(realAgentCaps);
      expect(d.protoVersion, 1);
      expect(d.agentVersion, '0.4.0');
      expect(d.chip, 'esp32-s3');
      expect(d.mpyVersion, '1.28.0');
      expect(d.fsRoot, '/');
      expect(d.mtu, 247);
      expect(d.window, 8);
      expect(d.chunk, 229);
      expect(d.freeMem, 8495096);
      expect(d.hasSd, isFalse);
      expect(d.hasIdentify, isFalse);
      expect(d.autoRun, isFalse);
      expect(d.deviceId, '5646');
    });

    test('an empty label parses to the empty string (screenless identity)', () {
      expect(parseCaps(realAgentCaps).label, '');
    });

    test('a set label parses verbatim (display-only, SEC-9)', () {
      final DeviceInfo d = parseCaps(
        realAgentCaps.replaceFirst('label=', 'label=Bench 3'),
      );
      expect(d.label, 'Bench 3');
    });

    test('identify_led=255 maps to none (int? null)', () {
      expect(parseCaps(realAgentCaps).identifyLed, isNull);
    });

    test('a real identify_led GPIO parses to its int value', () {
      final DeviceInfo d = parseCaps(
        realAgentCaps.replaceFirst('identify_led=255', 'identify_led=8'),
      );
      expect(d.identifyLed, 8);
    });

    test('has_sd / has_identify 1 map to true', () {
      final DeviceInfo d = parseCaps(
        realAgentCaps
            .replaceFirst('has_sd=0', 'has_sd=1')
            .replaceFirst('has_identify=0', 'has_identify=1'),
      );
      expect(d.hasSd, isTrue);
      expect(d.hasIdentify, isTrue);
    });

    test('unknown keys are ignored (additive caps, §9)', () {
      final DeviceInfo d = parseCaps(
        '$realAgentCaps\nfuture_cap=42\nanother=on',
      );
      // Still parses the known fields, and does not throw on the new keys.
      expect(d.chip, 'esp32-s3');
      expect(d.protoVersion, 1);
    });

    test('an unknown future target identifier is accepted verbatim', () {
      final DeviceInfo d = parseCaps(
        realAgentCaps.replaceFirst('chip=esp32-s3', 'chip=future-mcu-port'),
      );

      expect(d.chip, 'future-mcu-port');
      expect(d.protoVersion, 1);
    });
  });
}

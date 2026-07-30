// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.
//
// A-31 GPIO increment — authored, generic machine.Pin Blockly coverage.

import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

import '../support/repo_paths.dart';

void main() {
  late String authoredScript;

  setUpAll(() {
    authoredScript = File(
      '${appPackageRoot().path}/assets/blockly/pyble_blockly.js',
    ).readAsStringSync();
  });

  group('A-31 generic GPIO Blockly assets', () {
    test('offers an authored GPIO toolbox category', () {
      expect(
        authoredScript,
        contains('name: "GPIO"'),
        reason: 'generic hardware blocks need a visible GPIO category',
      );
    });

    test('ships the three composable PyBLE GPIO block types', () {
      for (final String blockType in <String>[
        'pyble_gpio_pin',
        'pyble_gpio_write',
        'pyble_gpio_read',
      ]) {
        expect(
          authoredScript,
          contains(blockType),
          reason: '$blockType must be authored in the MIT PyBLE host asset',
        );
      }
      expect(
        authoredScript,
        isNot(contains('pyble_gpio_configure')),
        reason:
            'declaration stays composable through standard Blockly variables; '
            'PyBLE must not add a second variable/configuration abstraction',
      );
    });

    test(
      'contains no board target, pin catalog, profile, or recommendation',
      () {
        for (final RegExp disallowed in <RegExp>[
          RegExp(
            r'\besp32(?:-s3|-c3)?[_ ](?:pins?|profile|catalog)\b',
            caseSensitive: false,
          ),
          RegExp(r'\bpyble_esp32(?:_s3|_c3)?\b', caseSensitive: false),
          RegExp(r'\bboard[_ ]?profile\b', caseSensitive: false),
          RegExp(r'\bpin[_ ]?profile\b', caseSensitive: false),
          RegExp(r'\bboard[_ ]?catalog\b', caseSensitive: false),
          RegExp(r'\bpin[_ ]?catalog\b', caseSensitive: false),
          RegExp(r'\brouting[_ ]?profile\b', caseSensitive: false),
          RegExp(r'\brecommended[_ ]?pins?\b', caseSensitive: false),
        ]) {
          expect(
            disallowed.hasMatch(authoredScript),
            isFalse,
            reason:
                'GPIO blocks accept an explicit user-selected integer and must '
                'not encode a board-specific pin model: ${disallowed.pattern}',
          );
        }
      },
    );

    test('does not introduce a network-capable GPIO runtime', () {
      for (final RegExp networkPrimitive in <RegExp>[
        RegExp(r'\bfetch\s*\('),
        RegExp(r'\bXMLHttpRequest\b'),
        RegExp(r'\bWebSocket\s*\('),
        RegExp(r'\bEventSource\s*\('),
      ]) {
        expect(
          networkPrimitive.hasMatch(authoredScript),
          isFalse,
          reason: 'GPIO generation must remain inside the offline asset host',
        );
      }
    });
  });
}

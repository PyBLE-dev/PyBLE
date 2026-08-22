// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.
//
// ADR-0023 [red] — explicit ST7789 Blockly asset contract.

import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

import '../support/repo_paths.dart';

void main() {
  late String authoredScript;
  late String flutterBridge;

  setUpAll(() {
    final Directory app = appPackageRoot();
    authoredScript = File(
      '${app.path}/assets/blockly/pyble_blockly.js',
    ).readAsStringSync();
    flutterBridge = File(
      '${app.path}/lib/blocks/blockly_webview.dart',
    ).readAsStringSync();
  });

  group('ADR-0023 explicit TFT Blockly assets', () {
    test('registers exactly the eight frozen TFT block types', () {
      const List<String> blockTypes = <String>[
        'pyble_tft_create',
        'pyble_tft_rgb565',
        'pyble_tft_fill',
        'pyble_tft_pixel',
        'pyble_tft_rect',
        'pyble_tft_text',
        'pyble_tft_show',
        'pyble_tft_backlight',
      ];
      for (final String type in blockTypes) {
        expect(
          RegExp('type: ["\']$type["\']').allMatches(authoredScript),
          hasLength(1),
          reason: '$type must have one authored definition',
        );
        expect(
          authoredScript,
          contains('forBlock.$type'),
          reason: '$type must have one production Python generator',
        );
      }
      expect(authoredScript, contains('hostMessages.tftCategory'));
      expect(flutterBridge, contains("'tftCategory':"));
    });

    test('keeps the constructor electrically explicit and typed', () {
      for (final String input in <String>[
        'SPI_ID',
        'BAUDRATE',
        'POLARITY',
        'PHASE',
        'SCK',
        'MOSI',
        'CS',
        'DC',
        'RESET',
        'BACKLIGHT',
        'WIDTH',
        'HEIGHT',
        'X_OFFSET',
        'Y_OFFSET',
        'BGR',
        'INVERSION',
      ]) {
        expect(
          authoredScript,
          contains('name: "$input"'),
          reason: 'ST7789 construction requires explicit $input',
        );
      }
      expect(authoredScript, contains('const tftType = "TFT"'));
      expect(authoredScript, contains('const tftColorType = "TFTColor"'));
      expect(authoredScript, contains('check: gpioPinType'));
      expect(authoredScript, contains('output: tftType'));
      expect(authoredScript, contains('output: tftColorType'));
    });

    test('generates only the frozen inspectable user-runtime surface', () {
      expect(authoredScript, contains('from pyble_st7789 import ST7789'));
      expect(authoredScript, contains('from pyble_st7789 import rgb565'));
      for (final String call in <String>[
        'ST7789(',
        'rgb565(',
        '.fill(',
        '.pixel(',
        '.rect(',
        '.fill_rect(',
        '.text(',
        '.show()',
        '.backlight(',
      ]) {
        expect(authoredScript, contains(call));
      }
    });

    test('contains no connection-time board gate or inferred GPIO', () {
      for (final RegExp forbidden in <RegExp>[
        RegExp(r'\bDeviceInfo\b'),
        RegExp(r'\bdeviceInfo\s*\('),
        RegExp(r'\bboardProfile\b'),
        RegExp(r'\brecommendedPins?\b'),
        RegExp(r'\bdetectedChip\b'),
      ]) {
        expect(
          forbidden.hasMatch(authoredScript),
          isFalse,
          reason: 'TFT blocks stay visible and explicit: ${forbidden.pattern}',
        );
      }
    });
  });
}

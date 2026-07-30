// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.
//
// A-31 beginner examples increment [red] — catalog and offline-asset contract.

import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

import '../support/repo_paths.dart';

const List<String> _exampleIds = <String>[
  'hello-pyble',
  'count-repeatedly',
  'blink-led',
  'blink-neopixel',
  'read-button',
  'button-controls-led',
  'reusable-function',
];

const Map<String, Set<String>> _requiredBlockTypes = <String, Set<String>>{
  'hello-pyble': <String>{'text_print'},
  'count-repeatedly': <String>{
    'controls_for',
    'variables_get',
    'text_print',
    'pyble_time_sleep_ms',
  },
  'blink-led': <String>{
    'variables_set',
    'controls_repeat_ext',
    'pyble_gpio_pin',
    'pyble_gpio_write',
    'pyble_time_sleep_ms',
  },
  'blink-neopixel': <String>{
    'variables_set',
    'variables_get',
    'controls_repeat_ext',
    'pyble_gpio_pin',
    'pyble_neopixel_create',
    'pyble_neopixel_rgb',
    'pyble_neopixel_set_pixel',
    'pyble_neopixel_write',
    'pyble_time_sleep_ms',
  },
  'read-button': <String>{
    'variables_set',
    'controls_whileUntil',
    'pyble_gpio_pin',
    'pyble_gpio_read',
    'text_print',
    'pyble_time_sleep_ms',
  },
  'button-controls-led': <String>{
    'variables_set',
    'controls_whileUntil',
    'controls_if',
    'logic_compare',
    'pyble_gpio_pin',
    'pyble_gpio_read',
    'pyble_gpio_write',
    'pyble_time_sleep_ms',
  },
  'reusable-function': <String>{
    'procedures_defnoreturn',
    'procedures_callnoreturn',
    'variables_get',
  },
};

const Map<String, Set<String>> _expectedGpioRoles = <String, Set<String>>{
  'hello-pyble': <String>{},
  'count-repeatedly': <String>{},
  'blink-led': <String>{'led'},
  'blink-neopixel': <String>{'pixel'},
  'read-button': <String>{'button'},
  'button-controls-led': <String>{'button', 'led'},
  'reusable-function': <String>{},
};

Iterable<Map<String, dynamic>> _objects(Object? value) sync* {
  if (value is Map<String, dynamic>) {
    yield value;
    for (final Object? child in value.values) {
      yield* _objects(child);
    }
  } else if (value is List<dynamic>) {
    for (final Object? child in value) {
      yield* _objects(child);
    }
  }
}

void main() {
  late File catalogFile;
  late Map<String, dynamic> catalog;
  late List<Map<String, dynamic>> examples;
  late Map<String, dynamic> englishMessages;

  setUpAll(() {
    final Directory app = appPackageRoot();
    catalogFile = File('${app.path}/assets/blockly/examples/catalog.json');
    if (!catalogFile.existsSync()) {
      fail('The bundled beginner catalog is missing: ${catalogFile.path}');
    }
    final Object? decoded = jsonDecode(catalogFile.readAsStringSync());
    expect(decoded, isA<Map<String, dynamic>>());
    catalog = decoded! as Map<String, dynamic>;
    final Object? rawExamples = catalog['examples'];
    expect(rawExamples, isA<List<dynamic>>());
    examples = (rawExamples! as List<dynamic>)
        .map((Object? value) {
          expect(value, isA<Map<String, dynamic>>());
          return value! as Map<String, dynamic>;
        })
        .toList(growable: false);

    final Object? rawMessages = jsonDecode(
      File('${app.path}/lib/localization/arb/app_en.arb').readAsStringSync(),
    );
    expect(rawMessages, isA<Map<String, dynamic>>());
    englishMessages = rawMessages! as Map<String, dynamic>;
  });

  group('A-31 beginner Blockly catalog', () {
    test('ships exactly the seven ordered, stable beginner examples', () {
      expect(catalog['license'], 'SPDX-License-Identifier: MIT');
      expect(catalog['version'], 2);
      expect(
        examples.map((Map<String, dynamic> value) => value['id']),
        orderedEquals(_exampleIds),
      );
      expect(
        examples.map((Map<String, dynamic> value) => value['id']).toSet(),
        hasLength(_exampleIds.length),
        reason: 'catalog IDs are stable lookup keys and must be unique',
      );
    });

    test('keeps all display metadata localized through ARB keys', () {
      const Set<String> forbiddenDisplayFields = <String>{
        'title',
        'summary',
        'concepts',
        'wiring',
        'wiringNotes',
        'source',
        'sourceTemplate',
      };

      for (final Map<String, dynamic> example in examples) {
        expect(
          example.keys.toSet().intersection(forbiddenDisplayFields),
          isEmpty,
          reason:
              '${example['id']} must not hard-code user-visible prose or a '
              'second source-of-truth Python preview in catalog.json',
        );

        for (final String scalarKey in <String>[
          'titleKey',
          'summaryKey',
          'wiringNotesKey',
        ]) {
          final Object? messageKey = example[scalarKey];
          expect(
            messageKey,
            isA<String>().having(
              (String value) => value.trim(),
              'non-empty',
              isNotEmpty,
            ),
            reason: '${example['id']}.$scalarKey',
          );
          expect(
            englishMessages[messageKey],
            isA<String>().having(
              (String value) => value.trim(),
              'localized English value',
              isNotEmpty,
            ),
            reason: '$messageKey must be defined in the template ARB',
          );
        }

        final Object? conceptKeys = example['conceptKeys'];
        expect(conceptKeys, isA<List<dynamic>>(), reason: '${example['id']}');
        expect(conceptKeys, isNotEmpty, reason: '${example['id']} concepts');
        for (final Object? messageKey in conceptKeys! as List<dynamic>) {
          expect(messageKey, isA<String>());
          expect(
            englishMessages[messageKey],
            isA<String>().having(
              (String value) => value.trim(),
              'localized English value',
              isNotEmpty,
            ),
            reason: '$messageKey must be defined in the template ARB',
          );
        }
      }
    });

    test('injects localized toolbox labels instead of hard-coding English', () {
      final Directory app = appPackageRoot();
      final String script = File(
        '${app.path}/assets/blockly/pyble_blockly.js',
      ).readAsStringSync();
      for (final String hardCodedLabel in <String>[
        '"Examples"',
        '"Hello PyBLE"',
        '"Count repeatedly"',
        '"Blink an LED"',
        '"Blink a NeoPixel"',
        '"Read a button"',
        '"Button controls LED"',
        '"Reusable function"',
      ]) {
        expect(
          script,
          isNot(contains(hardCodedLabel)),
          reason:
              '$hardCodedLabel must be supplied by Flutter localization, not '
              'owned by the offline JavaScript host',
        );
      }
      expect(
        script,
        contains('configureHost'),
        reason:
            'the bundled host needs a narrow runtime seam for localized '
            'category and button labels',
      );

      final String blocksDart = Directory('${app.path}/lib/blocks')
          .listSync()
          .whereType<File>()
          .where((File file) => file.path.endsWith('.dart'))
          .map((File file) => file.readAsStringSync())
          .join('\n');
      expect(blocksDart, contains('configureHost'));
      for (final String localizationGetter in <String>[
        'blocksExamples',
        'blocksExampleHelloTitle',
        'blocksExampleCountTitle',
        'blocksExampleBlinkTitle',
        'blocksExampleNeoPixelTitle',
        'blocksExampleReadButtonTitle',
        'blocksExampleButtonLedTitle',
        'blocksExampleFunctionTitle',
      ]) {
        expect(
          blocksDart,
          contains(localizationGetter),
          reason: '$localizationGetter must reach the Blockly toolbox bridge',
        );
      }
    });

    test(
      'NeoPixel blink keeps its GPIO empty and every transmission explicit',
      () {
        final Map<String, dynamic> example = examples.singleWhere(
          (Map<String, dynamic> value) => value['id'] == 'blink-neopixel',
        );
        final List<Map<String, dynamic>> objects = _objects(
          example['workspace'],
        ).toList(growable: false);
        final Map<String, dynamic> pin = objects.singleWhere(
          (Map<String, dynamic> value) =>
              value['type'] == 'pyble_gpio_pin' &&
              value['id'] == 'blink-neopixel-pin',
        );
        final Object? pinInputs = pin['inputs'];
        expect(
          pinInputs is Map<String, dynamic> ? pinInputs['GPIO'] : null,
          isNull,
          reason: 'the user must explicitly choose the NeoPixel data GPIO',
        );
        expect(
          objects
              .where(
                (Map<String, dynamic> value) =>
                    value['type'] == 'pyble_neopixel_set_pixel',
              )
              .length,
          2,
          reason: 'one dim-colour mutation and one explicit off mutation',
        );
        expect(
          objects
              .where(
                (Map<String, dynamic> value) =>
                    value['type'] == 'pyble_neopixel_write',
              )
              .length,
          2,
          reason: 'each buffer mutation is followed by a visible write block',
        );
        expect(
          jsonEncode(example),
          isNot(contains('"NUM":48')),
          reason: 'catalog fixtures never encode a board-specific GPIO',
        );
      },
    );

    test('injects every GPIO label and error through localized host copy', () {
      final Directory app = appPackageRoot();
      final String script = File(
        '${app.path}/assets/blockly/pyble_blockly.js',
      ).readAsStringSync();
      final String blocksDart = Directory('${app.path}/lib/blocks')
          .listSync()
          .whereType<File>()
          .where((File file) => file.path.endsWith('.dart'))
          .map((File file) => file.readAsStringSync())
          .join('\n');

      const List<String> hostKeys = <String>[
        'gpioCategory',
        'gpioPinMessage',
        'gpioWriteMessage',
        'gpioReadMessage',
        'gpioModeInput',
        'gpioModeOutput',
        'gpioPullNone',
        'gpioPullUp',
        'gpioPullDown',
        'gpioLevelLow',
        'gpioLevelHigh',
        'gpioPinTooltip',
        'gpioWriteTooltip',
        'gpioReadTooltip',
        'gpioPinRequiredError',
        'gpioPinInvalidError',
        'gpioModeInvalidError',
        'gpioPullInvalidError',
        'gpioWritePinRequiredError',
        'gpioLevelInvalidError',
        'gpioReadPinRequiredError',
        'gpioRestoreModeInvalidError',
        'gpioRestorePullInvalidError',
        'gpioRestoreLevelInvalidError',
        'multilineValueError',
      ];
      for (final String hostKey in hostKeys) {
        expect(
          script,
          contains('hostMessages.$hostKey'),
          reason:
              'the authored Blockly host must render/report the injected '
              '$hostKey value',
        );
        expect(
          blocksDart,
          matches(
            RegExp(
              "'${RegExp.escape(hostKey)}'\\s*:\\s*l10n\\.",
              multiLine: true,
            ),
          ),
          reason:
              '$hostKey must cross configureHost from AppLocalizations, not '
              'from a second English copy in Dart',
        );
      }

      for (final String hardCodedEnglish in <String>[
        'GPIO pin %1 mode %2 pull %3',
        '"input"',
        '"output"',
        '"none"',
        '"pull up"',
        '"pull down"',
        'Create a MicroPython GPIO pin. Pin availability is board-specific; '
            'the Pins reference is informational.',
        'set %1 digital value %2',
        '"low"',
        '"high"',
        'Write a low or high digital value to an output pin.',
        'read digital value from %1',
        'Read 0 or 1 from a digital input pin.',
        'GPIO pin number is required.',
        'GPIO pin number must be a finite non-negative integer literal.',
        'GPIO pin mode is invalid.',
        'GPIO pull selection is invalid.',
        'GPIO write requires a Pin input.',
        'GPIO output level is invalid.',
        'GPIO read requires a Pin input.',
        'Restored GPIO pin mode is invalid.',
        'Restored GPIO pull selection is invalid.',
        'Restored GPIO output level is invalid.',
        'Multiline values are not accepted.',
      ]) {
        expect(
          script,
          isNot(contains(hardCodedEnglish)),
          reason:
              'authored JavaScript must not retain user-facing English '
              'GPIO copy: $hardCodedEnglish',
        );
      }
    });

    test(
      'injects every NeoPixel label and error through localized host copy',
      () {
        final Directory app = appPackageRoot();
        final String script = File(
          '${app.path}/assets/blockly/pyble_blockly.js',
        ).readAsStringSync();
        final String blocksDart = Directory('${app.path}/lib/blocks')
            .listSync()
            .whereType<File>()
            .where((File file) => file.path.endsWith('.dart'))
            .map((File file) => file.readAsStringSync())
            .join('\n');

        const List<String> hostKeys = <String>[
          'neopixelCategory',
          'neopixelCreateMessage',
          'neopixelRgbMessage',
          'neopixelSetPixelMessage',
          'neopixelFillMessage',
          'neopixelWriteMessage',
          'neopixelCreateTooltip',
          'neopixelRgbTooltip',
          'neopixelSetPixelTooltip',
          'neopixelFillTooltip',
          'neopixelWriteTooltip',
          'neopixelPinRequiredError',
          'neopixelPixelsRequiredError',
          'neopixelPixelsInvalidError',
          'neopixelRedRequiredError',
          'neopixelGreenRequiredError',
          'neopixelBlueRequiredError',
          'neopixelStripRequiredError',
          'neopixelIndexRequiredError',
          'neopixelColorRequiredError',
        ];
        for (final String hostKey in hostKeys) {
          expect(script, contains('hostMessages.$hostKey'));
          expect(
            blocksDart,
            matches(
              RegExp(
                "'${RegExp.escape(hostKey)}'\\s*:\\s*l10n\\.",
                multiLine: true,
              ),
            ),
            reason: '$hostKey must cross configureHost from AppLocalizations',
          );
        }
      },
    );

    test('contains ordinary editable Blockly JSON for every example', () {
      for (final Map<String, dynamic> example in examples) {
        final Object? workspace = example['workspace'];
        expect(workspace, isA<Map<String, dynamic>>());
        final Map<String, dynamic> workspaceMap =
            workspace! as Map<String, dynamic>;
        expect(workspaceMap['blocks'], isA<Map<String, dynamic>>());
        expect(
          jsonDecode(jsonEncode(workspaceMap)),
          equals(workspaceMap),
          reason: '${example['id']} must survive an ordinary JSON round trip',
        );

        for (final Map<String, dynamic> object in _objects(workspaceMap)) {
          expect(
            object.keys,
            isNot(contains('examplePlaceholder')),
            reason:
                '${example['id']} must be loadable by ordinary Blockly '
                'serialization without a PyBLE sentinel block/state',
          );
        }
      }
    });

    test(
      'teaches the complete beginner progression with real block graphs',
      () {
        for (final Map<String, dynamic> example in examples) {
          final String id = example['id']! as String;
          final Set<String> actualTypes = _objects(example['workspace'])
              .map((Map<String, dynamic> value) => value['type'])
              .whereType<String>()
              .toSet();
          expect(
            actualTypes,
            containsAll(_requiredBlockTypes[id]!),
            reason: '$id does not contain its required teaching blocks',
          );
        }
      },
    );

    test('GPIO examples have explicit roles and no numeric pin defaults', () {
      for (final Map<String, dynamic> example in examples) {
        final String id = example['id']! as String;
        final Object? rawRoles = example['gpioRoles'];
        expect(rawRoles, isA<List<dynamic>>(), reason: '$id.gpioRoles');
        final List<Map<String, dynamic>> roles = (rawRoles! as List<dynamic>)
            .cast<Map<String, dynamic>>();
        expect(
          roles.map((Map<String, dynamic> role) => role['role']).toSet(),
          _expectedGpioRoles[id],
          reason: '$id GPIO role set',
        );

        final List<Map<String, dynamic>> pins = _objects(example['workspace'])
            .where(
              (Map<String, dynamic> object) =>
                  object['type'] == 'pyble_gpio_pin',
            )
            .toList(growable: false);
        expect(
          pins,
          hasLength(roles.length),
          reason: 'every $id GPIO constructor must be user-parameterized',
        );

        for (final Map<String, dynamic> role in roles) {
          expect(role['role'], isA<String>());
          expect(role['blockId'], isA<String>());
          expect(role['input'], 'GPIO');
          final Object? labelKey = role['labelKey'];
          expect(
            englishMessages[labelKey],
            isA<String>().having(
              (String value) => value.trim(),
              'localized role label',
              isNotEmpty,
            ),
          );

          final List<Map<String, dynamic>> targets = pins
              .where((Map<String, dynamic> pin) => pin['id'] == role['blockId'])
              .toList(growable: false);
          expect(
            targets,
            hasLength(1),
            reason: '$id role ${role['role']} must target one stable pin block',
          );
          final Object? rawInputs = targets.single['inputs'];
          final Map<String, dynamic>? inputs = rawInputs is Map<String, dynamic>
              ? rawInputs
              : null;
          final Object? rawGpio = inputs?['GPIO'];
          final Map<String, dynamic>? gpio = rawGpio is Map<String, dynamic>
              ? rawGpio
              : null;
          expect(
            gpio == null ||
                (!gpio.containsKey('block') && !gpio.containsKey('shadow')),
            isTrue,
            reason:
                '$id must ask for ${role['role']} GPIO; it must not silently '
                'encode a board-specific pin number or shadow',
          );
        }
      }
    });

    test('cannot encode autorun, board I/O, or a board profile', () {
      const Set<String> forbiddenKeys = <String>{
        'autoRun',
        'runOnLoad',
        'targetPath',
        'board',
        'boardProfile',
        'pinProfile',
      };
      for (final Map<String, dynamic> object in _objects(catalog)) {
        expect(
          object.keys.toSet().intersection(forbiddenKeys),
          isEmpty,
          reason:
              'examples only describe editable workspaces; choosing or '
              'previewing one must never perform a board action',
        );
      }
    });

    test('catalog directory is declared as a packaged Flutter asset', () {
      final String pubspec = File(
        '${appPackageRoot().path}/pubspec.yaml',
      ).readAsStringSync();
      expect(
        pubspec,
        contains('- assets/blockly/examples/'),
        reason:
            'Flutter directory assets are not recursive; catalog.json must be '
            'present in installed iPadOS and Android bundles',
      );
    });
  });

  group('A-31 generic Blockly delay primitive', () {
    test('is in a localized Time category with a required Number socket', () {
      final String script = File(
        '${appPackageRoot().path}/assets/blockly/pyble_blockly.js',
      ).readAsStringSync();
      expect(script, contains('type: "pyble_time_sleep_ms"'));
      expect(script, contains('name: hostMessages.timeCategory'));
      expect(
        script,
        isNot(contains('name: "Time"')),
        reason: 'the category label must come from the Flutter ARB bridge',
      );
      expect(script, contains('name: "MILLISECONDS"'));
      expect(script, contains('check: "Number"'));
      expect(
        RegExp(
          r'type:\s*"pyble_time_sleep_ms"[\s\S]*?inputs:\s*\{[\s\S]*?MILLISECONDS',
        ).hasMatch(script),
        isFalse,
        reason:
            'the toolbox must not prefill a duration shadow/default; examples '
            'provide their intentional pacing values explicitly',
      );
    });

    test(
      'uses the standard MicroPython sleep_ms import and reserves its name',
      () {
        final String script = File(
          '${appPackageRoot().path}/assets/blockly/pyble_blockly.js',
        ).readAsStringSync();
        expect(script, contains('from time import sleep_ms'));
        expect(script, contains('addReservedWords("sleep_ms")'));
      },
    );
  });
}

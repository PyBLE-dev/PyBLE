// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

/// Offline beginner-example catalog, validation, and GPIO materialization.
library;

import 'dart:convert';

import 'package:flutter/foundation.dart' show immutable, listEquals;
import 'package:flutter/services.dart' show rootBundle;
import 'package:flutter_riverpod/flutter_riverpod.dart';

const String kBlocksExamplesAssetPath = 'assets/blockly/examples/catalog.json';
const int kBlocksExamplesCatalogVersion = 2;
const int _maxJavaScriptSafeInteger = 9007199254740991;

const List<String> kBlocksExampleIds = <String>[
  'hello-pyble',
  'count-repeatedly',
  'blink-led',
  'blink-neopixel',
  'read-button',
  'button-controls-led',
  'reusable-function',
];

const Set<String> _blocksExampleTitleKeys = <String>{
  'blocksExampleHelloTitle',
  'blocksExampleCountTitle',
  'blocksExampleBlinkTitle',
  'blocksExampleNeoPixelTitle',
  'blocksExampleReadButtonTitle',
  'blocksExampleButtonLedTitle',
  'blocksExampleFunctionTitle',
};

const Set<String> _blocksExampleSummaryKeys = <String>{
  'blocksExampleHelloSummary',
  'blocksExampleCountSummary',
  'blocksExampleBlinkSummary',
  'blocksExampleNeoPixelSummary',
  'blocksExampleReadButtonSummary',
  'blocksExampleButtonLedSummary',
  'blocksExampleFunctionSummary',
};

const Set<String> _blocksExampleConceptKeys = <String>{
  'blocksExampleConceptText',
  'blocksExampleConceptConsole',
  'blocksExampleConceptVariables',
  'blocksExampleConceptLoops',
  'blocksExampleConceptTiming',
  'blocksExampleConceptGpioOutput',
  'blocksExampleConceptGpioInput',
  'blocksExampleConceptAddressableRgb',
  'blocksExampleConceptConditions',
  'blocksExampleConceptFunctions',
  'blocksExampleConceptParameters',
};

const Set<String> _blocksExampleWiringKeys = <String>{
  'blocksExampleNoWiring',
  'blocksExampleBlinkWiring',
  'blocksExampleNeoPixelWiring',
  'blocksExampleButtonWiring',
  'blocksExampleButtonLedWiring',
};

const Set<String> _blocksExampleGpioLabelKeys = <String>{
  'blocksExampleLedGpio',
  'blocksExampleButtonGpio',
  'blocksExampleNeoPixelGpio',
};

/// A malformed bundled catalog or unsafe materialization request.
class BlocksExampleFormatException implements Exception {
  const BlocksExampleFormatException(this.message);

  final String message;

  @override
  String toString() => 'BlocksExampleFormatException($message)';
}

@immutable
class BlocksExampleGpioRole {
  const BlocksExampleGpioRole({
    required this.role,
    required this.labelKey,
    required this.blockId,
    required this.input,
  });

  final String role;
  final String labelKey;
  final String blockId;
  final String input;
}

@immutable
class BlocksExampleTemplate {
  const BlocksExampleTemplate({
    required this.id,
    required this.titleKey,
    required this.summaryKey,
    required this.conceptKeys,
    required this.wiringNotesKey,
    required this.gpioRoles,
    required this.workspace,
  });

  final String id;
  final String titleKey;
  final String summaryKey;
  final List<String> conceptKeys;
  final String wiringNotesKey;
  final List<BlocksExampleGpioRole> gpioRoles;
  final Map<String, Object?> workspace;

  bool get requiresGpio => gpioRoles.isNotEmpty;

  /// Produces an ordinary Blockly workspace with explicit number blocks.
  ///
  /// The immutable catalog template remains untouched.
  String materializeWorkspaceJson(Map<String, int> gpioValues) {
    if (gpioValues.keys
            .toSet()
            .difference(
              gpioRoles
                  .map((BlocksExampleGpioRole value) => value.role)
                  .toSet(),
            )
            .isNotEmpty ||
        gpioValues.length != gpioRoles.length) {
      throw const BlocksExampleFormatException(
        'every declared GPIO role must have exactly one value',
      );
    }
    if (gpioValues.length > 1 &&
        gpioValues.values.toSet().length != gpioValues.length) {
      throw const BlocksExampleFormatException(
        'GPIO roles in one example must use different numbers',
      );
    }

    final Object? clonedValue = jsonDecode(jsonEncode(workspace));
    if (clonedValue is! Map<String, dynamic>) {
      throw const BlocksExampleFormatException(
        'example workspace is not a JSON object',
      );
    }

    final Set<String> usedIds = _objects(clonedValue)
        .map((Map<String, dynamic> value) => value['id'])
        .whereType<String>()
        .toSet();
    for (final BlocksExampleGpioRole binding in gpioRoles) {
      final int? gpio = gpioValues[binding.role];
      if (gpio == null || gpio < 0 || gpio > _maxJavaScriptSafeInteger) {
        throw BlocksExampleFormatException(
          '${binding.role} GPIO must be a non-negative safe integer',
        );
      }
      final List<Map<String, dynamic>> targets = _objects(clonedValue)
          .where(
            (Map<String, dynamic> value) =>
                value['type'] == 'pyble_gpio_pin' &&
                value['id'] == binding.blockId,
          )
          .toList(growable: false);
      if (binding.input != 'GPIO' || targets.length != 1) {
        throw BlocksExampleFormatException(
          'invalid ${binding.role} GPIO target',
        );
      }

      final Map<String, dynamic> target = targets.single;
      final Object? rawInputs = target['inputs'];
      final Map<String, dynamic> inputs;
      if (rawInputs == null) {
        inputs = <String, dynamic>{};
        target['inputs'] = inputs;
      } else if (rawInputs is Map<String, dynamic>) {
        inputs = rawInputs;
      } else {
        throw BlocksExampleFormatException(
          '${binding.role} GPIO inputs are malformed',
        );
      }
      final Object? existing = inputs['GPIO'];
      if (existing != null &&
          (existing is! Map<String, dynamic> || existing.isNotEmpty)) {
        throw BlocksExampleFormatException(
          '${binding.role} GPIO input is malformed or already connected',
        );
      }

      final String numberId = '$id-${binding.role}-gpio-value';
      if (!usedIds.add(numberId)) {
        throw BlocksExampleFormatException(
          'materialized block ID collides with $numberId',
        );
      }
      inputs['GPIO'] = <String, Object?>{
        'block': <String, Object?>{
          'type': 'math_number',
          'id': numberId,
          'fields': <String, Object?>{'NUM': gpio},
        },
      };
    }
    return jsonEncode(clonedValue);
  }
}

@immutable
class BlocksExampleCatalog {
  const BlocksExampleCatalog({required this.examples});

  final List<BlocksExampleTemplate> examples;

  BlocksExampleTemplate byId(String id) =>
      examples.singleWhere((BlocksExampleTemplate value) => value.id == id);

  static BlocksExampleCatalog parse(String source) {
    final Object? decoded;
    try {
      decoded = jsonDecode(source);
    } on FormatException catch (error) {
      throw BlocksExampleFormatException(error.message);
    }
    if (decoded is! Map<String, dynamic> ||
        decoded['version'] != kBlocksExamplesCatalogVersion ||
        decoded['examples'] is! List<dynamic>) {
      throw const BlocksExampleFormatException(
        'unsupported or malformed example catalog',
      );
    }

    final List<dynamic> rawExamples = decoded['examples']! as List<dynamic>;
    final List<BlocksExampleTemplate> examples = <BlocksExampleTemplate>[];
    for (final Object? rawExample in rawExamples) {
      if (rawExample is! Map<String, dynamic>) {
        throw const BlocksExampleFormatException(
          'catalog example must be an object',
        );
      }
      examples.add(_parseExample(rawExample));
    }
    if (!listEquals(
      examples.map((BlocksExampleTemplate value) => value.id).toList(),
      kBlocksExampleIds,
    )) {
      throw const BlocksExampleFormatException(
        'catalog examples are missing, reordered, or duplicated',
      );
    }
    return BlocksExampleCatalog(
      examples: List<BlocksExampleTemplate>.unmodifiable(examples),
    );
  }

  static BlocksExampleTemplate _parseExample(Map<String, dynamic> value) {
    final String id = _requiredString(value, 'id');
    final String titleKey = _requiredString(value, 'titleKey');
    final String summaryKey = _requiredString(value, 'summaryKey');
    final String wiringNotesKey = _requiredString(value, 'wiringNotesKey');
    if (!_blocksExampleTitleKeys.contains(titleKey) ||
        !_blocksExampleSummaryKeys.contains(summaryKey) ||
        !_blocksExampleWiringKeys.contains(wiringNotesKey)) {
      throw BlocksExampleFormatException(
        '$id references an unsupported localized message',
      );
    }
    final Object? rawConcepts = value['conceptKeys'];
    final Object? rawRoles = value['gpioRoles'];
    final Object? rawWorkspace = value['workspace'];
    if (rawConcepts is! List<dynamic> ||
        rawConcepts.isEmpty ||
        rawRoles is! List<dynamic> ||
        rawWorkspace is! Map<String, dynamic>) {
      throw BlocksExampleFormatException('$id has malformed catalog data');
    }

    final List<String> conceptKeys = rawConcepts
        .map((Object? item) {
          if (item is! String || item.trim().isEmpty) {
            throw BlocksExampleFormatException(
              '$id has an invalid concept key',
            );
          }
          if (!_blocksExampleConceptKeys.contains(item)) {
            throw BlocksExampleFormatException(
              '$id references an unsupported concept message',
            );
          }
          return item;
        })
        .toList(growable: false);
    if (conceptKeys.toSet().length != conceptKeys.length) {
      throw BlocksExampleFormatException('$id repeats a concept key');
    }

    final List<BlocksExampleGpioRole> roles = rawRoles
        .map((Object? item) {
          if (item is! Map<String, dynamic>) {
            throw BlocksExampleFormatException('$id has an invalid GPIO role');
          }
          final BlocksExampleGpioRole role = BlocksExampleGpioRole(
            role: _requiredString(item, 'role'),
            labelKey: _requiredString(item, 'labelKey'),
            blockId: _requiredString(item, 'blockId'),
            input: _requiredString(item, 'input'),
          );
          if (!_blocksExampleGpioLabelKeys.contains(role.labelKey)) {
            throw BlocksExampleFormatException(
              '$id references an unsupported GPIO label',
            );
          }
          return role;
        })
        .toList(growable: false);
    if (roles.map((BlocksExampleGpioRole value) => value.role).toSet().length !=
            roles.length ||
        roles
                .map((BlocksExampleGpioRole value) => value.blockId)
                .toSet()
                .length !=
            roles.length) {
      throw BlocksExampleFormatException('$id repeats a GPIO binding');
    }

    final Object? workspaceClone = jsonDecode(jsonEncode(rawWorkspace));
    final Map<String, Object?> workspace = _deepFreezeJsonMap(
      workspaceClone! as Map<String, dynamic>,
    );
    _validateWorkspace(id, workspace, roles);
    return BlocksExampleTemplate(
      id: id,
      titleKey: titleKey,
      summaryKey: summaryKey,
      conceptKeys: List<String>.unmodifiable(conceptKeys),
      wiringNotesKey: wiringNotesKey,
      gpioRoles: List<BlocksExampleGpioRole>.unmodifiable(roles),
      workspace: workspace,
    );
  }

  static void _validateWorkspace(
    String id,
    Map<String, Object?> workspace,
    List<BlocksExampleGpioRole> roles,
  ) {
    final Object? rawBlocks = workspace['blocks'];
    if (rawBlocks is! Map<String, dynamic> ||
        rawBlocks['languageVersion'] != 0 ||
        rawBlocks['blocks'] is! List<dynamic>) {
      throw BlocksExampleFormatException(
        '$id is not an ordinary Blockly workspace',
      );
    }

    final List<Map<String, dynamic>> blocks = _objects(workspace)
        .where((Map<String, dynamic> value) => value['type'] is String)
        .toList(growable: false);
    final List<String> ids = blocks
        .map((Map<String, dynamic> value) => value['id'])
        .whereType<String>()
        .toList(growable: false);
    if (ids.length != blocks.length || ids.toSet().length != ids.length) {
      throw BlocksExampleFormatException(
        '$id contains a missing or duplicate block ID',
      );
    }

    final List<Map<String, dynamic>> pins = blocks
        .where(
          (Map<String, dynamic> value) => value['type'] == 'pyble_gpio_pin',
        )
        .toList(growable: false);
    if (pins.length != roles.length) {
      throw BlocksExampleFormatException(
        '$id GPIO constructors and bindings do not match',
      );
    }
    for (final BlocksExampleGpioRole role in roles) {
      if (role.input != 'GPIO') {
        throw BlocksExampleFormatException(
          '$id has an unsupported GPIO role input',
        );
      }
      final List<Map<String, dynamic>> targets = pins
          .where((Map<String, dynamic> pin) => pin['id'] == role.blockId)
          .toList(growable: false);
      if (targets.length != 1) {
        throw BlocksExampleFormatException(
          '$id GPIO role does not target one pin block',
        );
      }
      final Object? rawInputs = targets.single['inputs'];
      if (rawInputs != null && rawInputs is! Map<String, dynamic>) {
        throw BlocksExampleFormatException(
          '$id has malformed GPIO constructor inputs',
        );
      }
      final Object? gpio = rawInputs is Map<String, dynamic>
          ? rawInputs['GPIO']
          : null;
      if (gpio != null && (gpio is! Map<String, dynamic> || gpio.isNotEmpty)) {
        throw BlocksExampleFormatException(
          '$id ships a GPIO default or malformed socket',
        );
      }
    }
  }
}

Map<String, Object?> _deepFreezeJsonMap(Map<String, dynamic> value) =>
    Map<String, Object?>.unmodifiable(
      value.map(
        (String key, Object? child) =>
            MapEntry<String, Object?>(key, _deepFreezeJsonValue(child)),
      ),
    );

Object? _deepFreezeJsonValue(Object? value) {
  if (value is Map<String, dynamic>) return _deepFreezeJsonMap(value);
  if (value is List<dynamic>) {
    return List<Object?>.unmodifiable(value.map(_deepFreezeJsonValue));
  }
  return value;
}

String _requiredString(Map<String, dynamic> value, String key) {
  final Object? field = value[key];
  if (field is! String || field.trim().isEmpty) {
    throw BlocksExampleFormatException('missing or invalid $key');
  }
  return field;
}

Iterable<Map<String, dynamic>> _objects(Object? value) sync* {
  if (value is Map<String, dynamic>) {
    yield value;
    for (final Object? child in value.values) {
      yield* _objects(child);
    }
  } else if (value is Map<String, Object?>) {
    final Map<String, dynamic> dynamicValue = value.cast<String, dynamic>();
    yield dynamicValue;
    for (final Object? child in dynamicValue.values) {
      yield* _objects(child);
    }
  } else if (value is List<dynamic>) {
    for (final Object? child in value) {
      yield* _objects(child);
    }
  }
}

/// Parses the exact GPIO grammar admitted by the production generator.
int? parseBlocksExampleGpio(String value) {
  final String trimmed = value.trim();
  if (!RegExp(r'^(?:0|[1-9][0-9]*)$').hasMatch(trimmed)) return null;
  final int? parsed = int.tryParse(trimmed);
  if (parsed == null || parsed < 0 || parsed > _maxJavaScriptSafeInteger) {
    return null;
  }
  return parsed;
}

/// Semantic emptiness includes variables as well as top-level block graphs.
bool isSemanticallyEmptyBlocksWorkspace(String? workspaceJson) {
  if (workspaceJson == null) return false;
  try {
    final Object? decoded = jsonDecode(workspaceJson);
    if (decoded is! Map<String, dynamic>) return false;
    final Object? rawBlocks = decoded['blocks'];
    if (rawBlocks is! Map<String, dynamic>) return false;
    final Object? blocks = rawBlocks['blocks'];
    if (blocks is! List<dynamic> || blocks.isNotEmpty) return false;
    final Object? variables = decoded['variables'];
    return variables == null ||
        (variables is List<dynamic> && variables.isEmpty);
  } on FormatException {
    return false;
  }
}

/// Canonical scratch-generation result returned by the real Blockly runtime.
@immutable
class BlocksExamplePreview {
  const BlocksExamplePreview({
    required this.source,
    required this.workspaceJson,
  });

  final String source;
  final String workspaceJson;
}

@immutable
class BlocksExampleCatalogRequest {
  const BlocksExampleCatalogRequest({this.serial = 0, this.initialExampleId});

  final int serial;
  final String? initialExampleId;
}

final StateProvider<BlocksExampleCatalogRequest>
blocksExampleCatalogRequestProvider =
    StateProvider<BlocksExampleCatalogRequest>(
      (Ref ref) => const BlocksExampleCatalogRequest(),
    );

final FutureProvider<BlocksExampleCatalog> blocksExampleCatalogProvider =
    FutureProvider<BlocksExampleCatalog>((Ref ref) async {
      final String source = await rootBundle.loadString(
        kBlocksExamplesAssetPath,
      );
      return BlocksExampleCatalog.parse(source);
    });

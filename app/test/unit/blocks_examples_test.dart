// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:pyble/app/providers.dart';
import 'package:pyble/blocks/blocks.dart';
import 'package:pyble/pble/pble.dart';

import '../support/repo_paths.dart';

String _snapshot({
  required int revision,
  required String source,
  required Map<String, Object?> workspace,
}) => jsonEncode(<String, Object?>{
  'version': kBlocksBridgeVersion,
  'type': 'snapshot',
  'revision': revision,
  'source': source,
  'workspace': workspace,
});

BlocksExampleCatalog _catalog() {
  final File file = File(
    '${appPackageRoot().path}/assets/blockly/examples/catalog.json',
  );
  return BlocksExampleCatalog.parse(file.readAsStringSync());
}

Map<String, dynamic> _catalogJson() {
  final File file = File(
    '${appPackageRoot().path}/assets/blockly/examples/catalog.json',
  );
  return jsonDecode(file.readAsStringSync())! as Map<String, dynamic>;
}

Map<String, dynamic> _exampleJson(Map<String, dynamic> catalog, String id) =>
    (catalog['examples']! as List<dynamic>)
        .cast<Map<String, dynamic>>()
        .singleWhere((Map<String, dynamic> value) => value['id'] == id);

Map<String, dynamic> _objectWithId(Object? value, String id) {
  if (value is Map<String, dynamic>) {
    if (value['id'] == id) return value;
    for (final Object? child in value.values) {
      try {
        return _objectWithId(child, id);
      } on StateError {
        // Keep looking through the ordinary nested Blockly serialization.
      }
    }
  } else if (value is List<dynamic>) {
    for (final Object? child in value) {
      try {
        return _objectWithId(child, id);
      } on StateError {
        // Keep looking through the ordinary nested Blockly serialization.
      }
    }
  }
  throw StateError('No object has ID $id');
}

Future<void> _loadExampleFuture(
  BlocksDocumentController controller,
  BlocksExamplePreview example, {
  required bool replace,
}) => controller.loadExampleWorkspace(example, replace: replace);

/// FR-BLOCKS-1B (A-38) pins the GPIO slot as a union: every example role
/// value is EITHER a non-negative safe integer (existing semantics) OR a
/// MicroPython pin name matching `^[A-Za-z][A-Za-z0-9_]{0,15}$`, so
/// `materializeWorkspaceJson` accepts `Map<String, Object>` whose values are
/// `int` or `String`. The call routes through a `dynamic` local so this red
/// suite still compiles against the in-flight `Map<String, int>` signature
/// and each test fails at runtime instead of failing the file at compile
/// time.
String _materializeUnion(
  BlocksExampleTemplate example,
  Map<String, Object> gpioValues,
) {
  final dynamic unionValues = gpioValues;
  return example.materializeWorkspaceJson(unionValues);
}

void main() {
  group('A-31 beginner example catalog model', () {
    test('parsed workspace nested maps are immutable', () {
      final BlocksExampleTemplate example = _catalog().byId('hello-pyble');
      final String before = jsonEncode(example.workspace);
      final Map<dynamic, dynamic> blocks =
          example.workspace['blocks']! as Map<dynamic, dynamic>;

      expect(
        () => blocks['languageVersion'] = 99,
        throwsUnsupportedError,
        reason:
            'callers must not be able to mutate a parsed catalog fixture '
            'through its public workspace map',
      );
      expect(jsonEncode(example.workspace), before);
    });

    test('parsed workspace nested lists are immutable', () {
      final BlocksExampleTemplate example = _catalog().byId('hello-pyble');
      final String before = jsonEncode(example.workspace);
      final Map<dynamic, dynamic> blocks =
          example.workspace['blocks']! as Map<dynamic, dynamic>;
      final List<dynamic> blockList = blocks['blocks']! as List<dynamic>;

      expect(
        () => blockList.clear(),
        throwsUnsupportedError,
        reason:
            'callers must not be able to mutate a parsed catalog fixture '
            'through a nested workspace list',
      );
      expect(jsonEncode(example.workspace), before);
    });

    test('materializes explicit GPIO blocks without changing the template', () {
      final BlocksExampleTemplate example = _catalog().byId(
        'button-controls-led',
      );
      final String templateBefore = jsonEncode(example.workspace);

      final String materialized = example.materializeWorkspaceJson(
        const <String, int>{'button': 23, 'led': 17},
      );
      final Map<String, dynamic> decoded =
          jsonDecode(materialized)! as Map<String, dynamic>;
      final String encoded = jsonEncode(decoded);

      expect(encoded, contains('"NUM":23'));
      expect(encoded, contains('"NUM":17'));
      expect(encoded, contains('button-controls-led-button-gpio-value'));
      expect(encoded, contains('button-controls-led-led-gpio-value'));
      expect(jsonEncode(example.workspace), templateBefore);
      expect(templateBefore, isNot(contains('"NUM":17')));
      expect(templateBefore, isNot(contains('"NUM":23')));
    });

    test(
      'materializes the nested NeoPixel Pin role without a board default',
      () {
        final BlocksExampleTemplate example = _catalog().byId('blink-neopixel');
        final String templateBefore = jsonEncode(example.workspace);

        final String materialized = example.materializeWorkspaceJson(
          const <String, int>{'pixel': 48},
        );

        expect(materialized, contains('"id":"blink-neopixel-pin"'));
        expect(materialized, contains('"NUM":48'));
        expect(
          materialized,
          contains('"id":"blink-neopixel-pixel-gpio-value"'),
        );
        expect(templateBefore, isNot(contains('"NUM":48')));
        expect(jsonEncode(example.workspace), templateBefore);
      },
    );

    test('rejects missing, extra, unsafe, and duplicate GPIO choices', () {
      final BlocksExampleTemplate example = _catalog().byId(
        'button-controls-led',
      );

      for (final Map<String, int> values in <Map<String, int>>[
        <String, int>{'led': 17},
        <String, int>{'led': 17, 'button': 23, 'extra': 5},
        <String, int>{'led': -1, 'button': 23},
        <String, int>{'led': 17, 'button': 17},
      ]) {
        expect(
          () => example.materializeWorkspaceJson(values),
          throwsA(isA<BlocksExampleFormatException>()),
          reason: values.toString(),
        );
      }
    });

    test('rejects a materialized GPIO block ID reserved by the template', () {
      final Map<String, dynamic> catalog = _catalogJson();
      final Map<String, dynamic> blink = _exampleJson(catalog, 'blink-led');
      final Map<String, dynamic> blocks =
          (blink['workspace']! as Map<String, dynamic>)['blocks']!
              as Map<String, dynamic>;
      (blocks['blocks']! as List<dynamic>).add(<String, Object?>{
        'type': 'math_number',
        'id': 'blink-led-led-gpio-value',
        'x': 16,
        'y': 16,
        'fields': <String, Object?>{'NUM': 99},
      });
      final BlocksExampleTemplate example = BlocksExampleCatalog.parse(
        jsonEncode(catalog),
      ).byId('blink-led');

      expect(
        () => example.materializeWorkspaceJson(const <String, int>{'led': 17}),
        throwsA(isA<BlocksExampleFormatException>()),
        reason: 'materialization must never create duplicate Blockly block IDs',
      );
    });

    for (final Object malformedInput in <Object>[
      'not-an-input-state',
      <Object?>['not', 'an', 'input', 'state'],
    ]) {
      test('rejects malformed GPIO input state '
          '(${malformedInput.runtimeType})', () {
        final Map<String, dynamic> catalog = _catalogJson();
        final Map<String, dynamic> blink = _exampleJson(catalog, 'blink-led');
        final Map<String, dynamic> pin = _objectWithId(
          blink['workspace'],
          'blink-led-pin',
        );
        final Map<String, dynamic> inputs =
            (pin['inputs'] as Map<String, dynamic>?) ?? <String, dynamic>{};
        pin['inputs'] = inputs;
        inputs['GPIO'] = malformedInput;

        expect(
          () {
            final BlocksExampleTemplate example = BlocksExampleCatalog.parse(
              jsonEncode(catalog),
            ).byId('blink-led');
            example.materializeWorkspaceJson(const <String, int>{'led': 17});
          },
          throwsA(isA<BlocksExampleFormatException>()),
          reason:
              'malformed catalog input data must not be silently overwritten',
        );
      });
    }

    final Map<String, void Function(Map<String, dynamic> catalog)>
    unknownLocalizationKeyMutations =
        <String, void Function(Map<String, dynamic>)>{
          'title': (Map<String, dynamic> catalog) {
            _exampleJson(catalog, 'hello-pyble')['titleKey'] =
                'blocksExampleUnknownCatalogMessage';
          },
          'summary': (Map<String, dynamic> catalog) {
            _exampleJson(catalog, 'hello-pyble')['summaryKey'] =
                'blocksExampleUnknownCatalogMessage';
          },
          'concept': (Map<String, dynamic> catalog) {
            _exampleJson(catalog, 'hello-pyble')['conceptKeys'] = <String>[
              'blocksExampleUnknownCatalogMessage',
            ];
          },
          'wiring note': (Map<String, dynamic> catalog) {
            _exampleJson(catalog, 'hello-pyble')['wiringNotesKey'] =
                'blocksExampleUnknownCatalogMessage';
          },
          'GPIO role label': (Map<String, dynamic> catalog) {
            final Map<String, dynamic> blink = _exampleJson(
              catalog,
              'blink-led',
            );
            (blink['gpioRoles']! as List<dynamic>)
                    .cast<Map<String, dynamic>>()
                    .single['labelKey'] =
                'blocksExampleUnknownCatalogMessage';
          },
        };
    for (final MapEntry<String, void Function(Map<String, dynamic>)> entry
        in unknownLocalizationKeyMutations.entries) {
      test('rejects an unknown ${entry.key} localization key', () {
        final Map<String, dynamic> catalog = _catalogJson();
        entry.value(catalog);

        expect(
          () => BlocksExampleCatalog.parse(jsonEncode(catalog)),
          throwsA(isA<BlocksExampleFormatException>()),
          reason:
              'dialog construction must not discover unsupported ARB keys '
              'after the catalog-loading error boundary',
        );
      });
    }

    test('semantic empty detection includes variables and invalid graphs', () {
      expect(isSemanticallyEmptyBlocksWorkspace(null), isFalse);
      expect(isSemanticallyEmptyBlocksWorkspace('not JSON'), isFalse);
      expect(
        isSemanticallyEmptyBlocksWorkspace(
          jsonEncode(<String, Object?>{'variables': <Object?>[]}),
        ),
        isFalse,
        reason: 'a missing blocks section is unknown unless the object is `{}`',
      );
      expect(
        isSemanticallyEmptyBlocksWorkspace('{}'),
        isTrue,
        reason: 'Blockly serializes its canonical empty workspace as `{}`',
      );
      expect(
        isSemanticallyEmptyBlocksWorkspace(
          jsonEncode(<String, Object?>{
            'blocks': <String, Object?>{
              'languageVersion': 0,
              'blocks': <Object?>[],
            },
          }),
        ),
        isTrue,
      );
      expect(
        isSemanticallyEmptyBlocksWorkspace(
          jsonEncode(<String, Object?>{
            'variables': <Object?>[
              <String, Object?>{'name': 'kept', 'id': 'kept-variable'},
            ],
            'blocks': <String, Object?>{
              'languageVersion': 0,
              'blocks': <Object?>[],
            },
          }),
        ),
        isFalse,
      );
      expect(
        isSemanticallyEmptyBlocksWorkspace(
          jsonEncode(<String, Object?>{
            'blocks': <String, Object?>{
              'languageVersion': 0,
              'blocks': <Object?>[
                <String, Object?>{
                  'type': 'pyble_gpio_write',
                  'id': 'incomplete',
                },
              ],
            },
          }),
        ),
        isFalse,
      );
    });
  });

  group('A-31 beginner example document boundary', () {
    ProviderContainer bind() {
      final ProviderContainer container = ProviderContainer(
        overrides: <Override>[
          connectionProvider.overrideWithValue(
            FakeConnection(initial: ConnState.ready),
          ),
        ],
      );
      addTearDown(container.dispose);
      return container;
    }

    test('scratch preview is non-mutating', () async {
      final ProviderContainer container = bind();
      final BlocksDocumentController controller = container.read(
        blocksDocumentProvider.notifier,
      );
      late final int hostId;
      hostId = controller.beginHost(
        requestSnapshot: (int requestId) async {},
        previewExample: (String workspaceJson) async => BlocksExamplePreview(
          source: "print('preview')\n",
          workspaceJson: workspaceJson,
        ),
      );
      controller.markHostLoading(hostId);
      const Map<String, Object?> workspace = <String, Object?>{
        'blocks': <String, Object?>{
          'languageVersion': 0,
          'blocks': <Object?>[],
        },
      };
      controller.receiveBridgeMessage(
        _snapshot(revision: 4, source: '', workspace: workspace),
        hostId: hostId,
      );
      final BlocksDocument before = container.read(blocksDocumentProvider);

      final BlocksExamplePreview preview = await controller.previewExample(
        jsonEncode(workspace),
      );

      expect(preview.source, "print('preview')\n");
      expect(container.read(blocksDocumentProvider), same(before));
    });

    test('Create copy is empty-only and replacement is explicit', () {
      final ProviderContainer container = bind();
      final BlocksDocumentController controller = container.read(
        blocksDocumentProvider.notifier,
      );
      const Map<String, Object?> existing = <String, Object?>{
        'blocks': <String, Object?>{
          'languageVersion': 0,
          'blocks': <Object?>[
            <String, Object?>{'type': 'text_print', 'id': 'existing'},
          ],
        },
      };
      controller.receiveBridgeMessage(
        _snapshot(revision: 7, source: "print('keep')\n", workspace: existing),
      );
      final BlocksDocument before = container.read(blocksDocumentProvider);
      final BlocksExamplePreview candidate = BlocksExamplePreview(
        source: "print('new')\n",
        workspaceJson: jsonEncode(<String, Object?>{
          'blocks': <String, Object?>{
            'languageVersion': 0,
            'blocks': <Object?>[
              <String, Object?>{'type': 'text_print', 'id': 'new'},
            ],
          },
        }),
      );

      expect(
        () => controller.loadExampleWorkspace(candidate, replace: false),
        throwsA(isA<BlocksWorkspaceNotEmpty>()),
      );
      expect(container.read(blocksDocumentProvider), same(before));

      unawaited(
        _loadExampleFuture(
          controller,
          candidate,
          replace: true,
        ).catchError((_) {}),
      );
      final BlocksDocument after = container.read(blocksDocumentProvider);
      expect(after.status, BlocksStatus.loading);
      expect(after.program, isNull);
      expect(after.retainedWorkspaceRevision, 7);
      expect(after.retainedWorkspaceJson, contains('"id":"new"'));
      expect(after.loadAttempt, before.loadAttempt + 1);
    });

    test(
      'load future commits only after the candidate host snapshot',
      () async {
        final ProviderContainer container = bind();
        final BlocksDocumentController controller = container.read(
          blocksDocumentProvider.notifier,
        );
        const Map<String, Object?> existing = <String, Object?>{
          'blocks': <String, Object?>{
            'languageVersion': 0,
            'blocks': <Object?>[
              <String, Object?>{'type': 'text_print', 'id': 'existing'},
            ],
          },
        };
        const Map<String, Object?> replacement = <String, Object?>{
          'blocks': <String, Object?>{
            'languageVersion': 0,
            'blocks': <Object?>[
              <String, Object?>{'type': 'text_print', 'id': 'replacement'},
            ],
          },
        };
        controller.receiveBridgeMessage(
          _snapshot(
            revision: 7,
            source: "print('keep')\n",
            workspace: existing,
          ),
        );
        final Future<void> completion = _loadExampleFuture(
          controller,
          BlocksExamplePreview(
            source: "print('replacement')\n",
            workspaceJson: jsonEncode(replacement),
          ),
          replace: true,
        );
        bool completed = false;
        unawaited(completion.then<void>((_) => completed = true));
        await Future<void>.delayed(Duration.zero);
        expect(
          completed,
          isFalse,
          reason: 'staging JSON is not a successful Blockly restore',
        );

        late final int hostId;
        hostId = controller.beginHost(
          requestSnapshot: (int requestId) async {},
        );
        controller.markHostLoading(hostId);
        controller.receiveBridgeMessage(
          _snapshot(
            revision: 8,
            source: "print('replacement')\n",
            workspace: replacement,
          ),
          hostId: hostId,
        );
        await completion;

        final BlocksDocument committed = container.read(blocksDocumentProvider);
        expect(completed, isTrue);
        expect(committed.status, BlocksStatus.ready);
        expect(committed.program?.source, "print('replacement')\n");
        expect(committed.retainedWorkspaceRevision, 8);
        expect(jsonDecode(committed.retainedWorkspaceJson!), replacement);
      },
    );

    test(
      'same-source snapshot with different workspace rolls back atomically',
      () async {
        final ProviderContainer container = bind();
        final BlocksDocumentController controller = container.read(
          blocksDocumentProvider.notifier,
        );
        const Map<String, Object?> existing = <String, Object?>{
          'blocks': <String, Object?>{
            'languageVersion': 0,
            'blocks': <Object?>[
              <String, Object?>{'type': 'text_print', 'id': 'existing'},
            ],
          },
        };
        const Map<String, Object?> replacement = <String, Object?>{
          'blocks': <String, Object?>{
            'languageVersion': 0,
            'blocks': <Object?>[
              <String, Object?>{'type': 'text_print', 'id': 'replacement'},
            ],
          },
        };
        const Map<String, Object?> differentWorkspace = <String, Object?>{
          'blocks': <String, Object?>{
            'languageVersion': 0,
            'blocks': <Object?>[],
          },
        };
        controller.receiveBridgeMessage(
          _snapshot(
            revision: 7,
            source: "print('keep')\n",
            workspace: existing,
          ),
        );
        final BlocksDocument before = container.read(blocksDocumentProvider);
        final Future<void> completion = _loadExampleFuture(
          controller,
          BlocksExamplePreview(
            source: "print('replacement')\n",
            workspaceJson: jsonEncode(replacement),
          ),
          replace: true,
        );
        bool completedSuccessfully = false;
        Object? completionError;
        final Future<void> observedCompletion = completion.then<void>(
          (_) => completedSuccessfully = true,
          onError: (Object error, StackTrace stackTrace) {
            completionError = error;
          },
        );
        final int hostId = controller.beginHost(
          requestSnapshot: (int requestId) async {},
        );
        controller.markHostLoading(hostId);

        final BlocksBridgeResult result = controller.receiveBridgeMessage(
          _snapshot(
            revision: 8,
            source: "print('replacement')\n",
            workspace: differentWorkspace,
          ),
          hostId: hostId,
        );
        await observedCompletion;

        expect(
          result,
          BlocksBridgeResult.hostError,
          reason:
              'matching generated text must not authorize a structurally '
              'different workspace',
        );
        expect(completedSuccessfully, isFalse);
        expect(completionError, isA<BlocksGenerationFailed>());

        final BlocksDocument rolledBack = container.read(
          blocksDocumentProvider,
        );
        expect(rolledBack.status, BlocksStatus.loading);
        expect(
          rolledBack.retainedWorkspaceJson,
          before.retainedWorkspaceJson,
          reason: 'the prior graph must be restored byte-for-byte',
        );
        expect(
          rolledBack.retainedWorkspaceRevision,
          before.retainedWorkspaceRevision,
        );
        expect(rolledBack.program, same(before.program));
        expect(rolledBack.error, isNull);
        expect(rolledBack.workspaceError, before.workspaceError);
        expect(
          rolledBack.loadAttempt,
          before.loadAttempt + 2,
          reason:
              'one host stages the candidate and a second host restores the '
              'prior document after rejection',
        );
        expect(controller.hasActiveReadyHost, isFalse);
      },
    );

    test('host restore failure rolls back the exact prior document', () async {
      final ProviderContainer container = bind();
      final BlocksDocumentController controller = container.read(
        blocksDocumentProvider.notifier,
      );
      const Map<String, Object?> existing = <String, Object?>{
        'blocks': <String, Object?>{
          'languageVersion': 0,
          'blocks': <Object?>[
            <String, Object?>{'type': 'text_print', 'id': 'existing'},
          ],
        },
      };
      controller.receiveBridgeMessage(
        _snapshot(revision: 7, source: "print('keep')\n", workspace: existing),
      );
      final BlocksDocument before = container.read(blocksDocumentProvider);
      final Future<void> completion = _loadExampleFuture(
        controller,
        BlocksExamplePreview(
          source: "print('replacement')\n",
          workspaceJson: jsonEncode(<String, Object?>{
            'blocks': <String, Object?>{
              'languageVersion': 0,
              'blocks': <Object?>[
                <String, Object?>{'type': 'text_print', 'id': 'replacement'},
              ],
            },
          }),
        ),
        replace: true,
      );
      final Future<void> expectedFailure = expectLater(
        completion,
        throwsA(isA<BlocksHostUnavailable>()),
      );
      final int hostId = controller.beginHost(
        requestSnapshot: (int requestId) async {},
      );
      controller.markHostLoading(hostId);

      controller.reportHostError('candidate restore failed', hostId: hostId);
      await expectedFailure;

      final BlocksDocument rolledBack = container.read(blocksDocumentProvider);
      expect(
        rolledBack.retainedWorkspaceJson,
        before.retainedWorkspaceJson,
        reason: 'the serialized prior graph must be restored byte-for-byte',
      );
      expect(
        rolledBack.retainedWorkspaceRevision,
        before.retainedWorkspaceRevision,
      );
      expect(rolledBack.program, same(before.program));
      expect(
        rolledBack.retainedWorkspaceJson,
        isNot(contains('"id":"replacement"')),
      );
    });

    test(
      'candidate generation failure rolls back the exact prior document',
      () async {
        final ProviderContainer container = bind();
        final BlocksDocumentController controller = container.read(
          blocksDocumentProvider.notifier,
        );
        const Map<String, Object?> existing = <String, Object?>{
          'blocks': <String, Object?>{
            'languageVersion': 0,
            'blocks': <Object?>[
              <String, Object?>{'type': 'text_print', 'id': 'existing'},
            ],
          },
        };
        const Map<String, Object?> replacement = <String, Object?>{
          'blocks': <String, Object?>{
            'languageVersion': 0,
            'blocks': <Object?>[
              <String, Object?>{
                'type': 'pyble_gpio_write',
                'id': 'replacement',
              },
            ],
          },
        };
        controller.receiveBridgeMessage(
          _snapshot(
            revision: 7,
            source: "print('keep')\n",
            workspace: existing,
          ),
        );
        final BlocksDocument before = container.read(blocksDocumentProvider);
        final Future<void> completion = _loadExampleFuture(
          controller,
          BlocksExamplePreview(
            source: "print('preview was valid')\n",
            workspaceJson: jsonEncode(replacement),
          ),
          replace: true,
        );
        final Future<void> expectedFailure = expectLater(
          completion,
          throwsA(isA<BlocksGenerationFailed>()),
        );
        final int hostId = controller.beginHost(
          requestSnapshot: (int requestId) async {},
        );
        controller.markHostLoading(hostId);

        controller.receiveBridgeMessage(
          jsonEncode(<String, Object?>{
            'version': kBlocksBridgeVersion,
            'type': 'error',
            'message': 'candidate generation failed',
            'revision': 8,
            'workspace': replacement,
          }),
          hostId: hostId,
        );
        await expectedFailure;

        final BlocksDocument rolledBack = container.read(
          blocksDocumentProvider,
        );
        expect(
          rolledBack.retainedWorkspaceJson,
          before.retainedWorkspaceJson,
          reason: 'invalid candidate JSON must not replace the prior graph',
        );
        expect(
          rolledBack.retainedWorkspaceRevision,
          before.retainedWorkspaceRevision,
        );
        expect(rolledBack.program, same(before.program));
        expect(
          rolledBack.retainedWorkspaceJson,
          isNot(contains('"id":"replacement"')),
        );
      },
    );

    test('toolbox request selects a validated catalog entry only', () {
      final ProviderContainer container = bind();
      final BlocksDocumentController controller = container.read(
        blocksDocumentProvider.notifier,
      );

      expect(
        controller.receiveBridgeMessage(
          jsonEncode(<String, Object?>{
            'version': kBlocksBridgeVersion,
            'type': 'openExamples',
            'exampleId': 'blink-led',
          }),
        ),
        BlocksBridgeResult.exampleCatalogRequested,
      );
      final BlocksExampleCatalogRequest request = container.read(
        blocksExampleCatalogRequestProvider,
      );
      expect(request.serial, 1);
      expect(request.initialExampleId, 'blink-led');
    });

    test('unknown toolbox example ID is ignored without document mutation', () {
      final ProviderContainer container = bind();
      final BlocksDocumentController controller = container.read(
        blocksDocumentProvider.notifier,
      );
      late final int hostId;
      hostId = controller.beginHost(requestSnapshot: (int requestId) async {});
      controller.markHostLoading(hostId);
      controller.receiveBridgeMessage(
        _snapshot(
          revision: 7,
          source: "print('keep')\n",
          workspace: const <String, Object?>{
            'blocks': <String, Object?>{
              'languageVersion': 0,
              'blocks': <Object?>[
                <String, Object?>{'type': 'text_print', 'id': 'existing'},
              ],
            },
          },
        ),
        hostId: hostId,
      );
      final BlocksDocument before = container.read(blocksDocumentProvider);
      final BlocksExampleCatalogRequest requestBefore = container.read(
        blocksExampleCatalogRequestProvider,
      );

      final BlocksBridgeResult result = controller.receiveBridgeMessage(
        jsonEncode(<String, Object?>{
          'version': kBlocksBridgeVersion,
          'type': 'openExamples',
          'exampleId': 'not-a-bundled-example',
        }),
        hostId: hostId,
      );

      expect(result, BlocksBridgeResult.ignored);
      expect(container.read(blocksDocumentProvider), same(before));
      expect(
        container.read(blocksExampleCatalogRequestProvider),
        same(requestBefore),
      );
      expect(controller.hasActiveReadyHost, isTrue);
    });
  });

  group('A-38 named pin union in example GPIO materialization', () {
    test('materializes a named pin as a quoted-name text value block', () {
      final BlocksExampleTemplate example = _catalog().byId('blink-led');
      final String templateBefore = jsonEncode(example.workspace);

      final String materialized = _materializeUnion(
        example,
        const <String, Object>{'led': 'LED'},
      );

      final Map<String, dynamic> decoded =
          jsonDecode(materialized)! as Map<String, dynamic>;
      final Map<String, dynamic> value = _objectWithId(
        decoded,
        'blink-led-led-gpio-value',
      );
      expect(
        value['type'],
        'text',
        reason:
            'a pin NAME materializes as the stock Blockly string literal so '
            'the generator can quote it (Pin("LED", ...)) while integers stay '
            'math_number blocks',
      );
      expect(value['fields'], <String, Object?>{'TEXT': 'LED'});
      final Map<String, dynamic> pin = _objectWithId(decoded, 'blink-led-pin');
      final Map<String, dynamic> connected =
          ((pin['inputs']! as Map<String, dynamic>)['GPIO']!
                  as Map<String, dynamic>)['block']!
              as Map<String, dynamic>;
      expect(connected['id'], 'blink-led-led-gpio-value');
      expect(jsonEncode(example.workspace), templateBefore);
      expect(templateBefore, isNot(contains('"TEXT":"LED"')));
    });

    test('accepts the sixteen-character name upper bound', () {
      final BlocksExampleTemplate example = _catalog().byId('blink-led');

      expect(
        () => _materializeUnion(example, const <String, Object>{
          'led': 'A234567890123456',
        }),
        returnsNormally,
        reason: 'the frozen grammar allows up to sixteen characters',
      );
    });

    test('materializes mixed integer and named GPIO roles together', () {
      final BlocksExampleTemplate example = _catalog().byId(
        'button-controls-led',
      );
      final String templateBefore = jsonEncode(example.workspace);

      final String materialized = _materializeUnion(
        example,
        const <String, Object>{'button': 23, 'led': 'LED'},
      );

      expect(materialized, contains('"NUM":23'));
      expect(materialized, contains('"TEXT":"LED"'));
      expect(materialized, contains('button-controls-led-button-gpio-value'));
      expect(materialized, contains('button-controls-led-led-gpio-value'));
      expect(jsonEncode(example.workspace), templateBefore);
    });

    test('rejects names outside the frozen grammar via the invalid-pin '
        'path', () {
      final BlocksExampleTemplate example = _catalog().byId('blink-led');

      for (final Object invalid in <Object>[
        'led led',
        '2x',
        '',
        'ABCDEFGHIJKLMNOPQ', // seventeen characters — one over the bound
        '9LED',
        '2',
        ' LED',
        'LED-1',
        2.5,
        true,
      ]) {
        expect(
          () => _materializeUnion(example, <String, Object>{'led': invalid}),
          throwsA(isA<BlocksExampleFormatException>()),
          reason:
              'GPIO value `$invalid` must follow the existing invalid-pin '
              'error path',
        );
      }
    });

    test('GPIO uniqueness compares canonical union forms', () {
      final BlocksExampleTemplate example = _catalog().byId(
        'button-controls-led',
      );

      expect(
        () => _materializeUnion(example, const <String, Object>{
          'button': 'LED',
          'led': 'LED',
        }),
        throwsA(isA<BlocksExampleFormatException>()),
        reason: "'LED' == 'LED' — duplicate names collide",
      );
      expect(
        () => _materializeUnion(example, const <String, Object>{
          'button': 2,
          'led': 2,
        }),
        throwsA(isA<BlocksExampleFormatException>()),
        reason: '2 == 2 — duplicate integers still collide through the union',
      );
      expect(
        () => _materializeUnion(example, const <String, Object>{
          'button': 'WL_GPIO0',
          'led': 'LED',
        }),
        returnsNormally,
        reason: 'distinct names never collide',
      );
      expect(
        () => _materializeUnion(example, const <String, Object>{
          'button': 2,
          'led': 'LED',
        }),
        returnsNormally,
        reason: "'LED' != 2 — a name never collides with an integer",
      );
    });

    test('parses named pins with the exact integer-or-name grammar', () {
      expect(parseBlocksExampleGpio('LED'), 'LED');
      expect(
        parseBlocksExampleGpio(' WL_GPIO0 '),
        'WL_GPIO0',
        reason: 'surrounding whitespace trims exactly like integer input',
      );
      expect(parseBlocksExampleGpio('17'), 17);
      for (final String invalid in <String>[
        'led led',
        '2x',
        '',
        'ABCDEFGHIJKLMNOPQ',
        '9LED',
        'LED-1',
      ]) {
        expect(parseBlocksExampleGpio(invalid), isNull, reason: '`$invalid`');
      }
    });
  });
}

// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

import 'dart:convert';
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:pyble/app/providers.dart';
import 'package:pyble/blocks/blocks.dart';
import 'package:pyble/editor/editor.dart';
import 'package:pyble/files/files.dart';
import 'package:pyble/localization/localization.dart';
import 'package:pyble/pble/pble.dart';
import 'package:pyble/theme/theme.dart';

class _RecordingConnection extends FakeConnection {
  _RecordingConnection() : super(initial: ConnState.ready);

  final List<(String, Uint8List)> writes = <(String, Uint8List)>[];
  final List<String> reads = <String>[];
  final List<String> runs = <String>[];

  Future<void> seedFile(String path, Uint8List bytes) =>
      super.putFile(path, bytes);

  @override
  Future<Uint8List> getFile(String path, {ProgressCb? onProgress}) {
    reads.add(path);
    return super.getFile(path, onProgress: onProgress);
  }

  @override
  Future<void> putFile(String path, Uint8List bytes, {ProgressCb? onProgress}) {
    writes.add((path, Uint8List.fromList(bytes)));
    return super.putFile(path, bytes, onProgress: onProgress);
  }

  @override
  Future<void> runFile(String path) {
    runs.add(path);
    return super.runFile(path);
  }
}

const String _expectedGpioSource =
    'from machine import Pin\n\n\n'
    'Pin(2, Pin.OUT, None).value(1)\n'
    'print(Pin(4, Pin.IN, Pin.PULL_UP).value())\n';

const String _expectedBlinkSource =
    'from machine import Pin\n'
    'from time import sleep_ms\n\n'
    'led = None\n\n\n'
    'led = Pin(17, Pin.OUT, None)\n'
    'for count in range(10):\n'
    '  led.value(1)\n'
    '  sleep_ms(500)\n'
    '  led.value(0)\n'
    '  sleep_ms(500)\n';

String _richExactWorkspace() => jsonEncode(<String, Object?>{
  'variables': <Object?>[
    <String, Object?>{'name': 'message', 'id': 'rich-message-variable'},
  ],
  'blocks': <String, Object?>{
    'languageVersion': 0,
    'blocks': <Object?>[
      <String, Object?>{
        'type': 'variables_set',
        'id': 'rich-message-set',
        'x': 48,
        'y': 48,
        'collapsed': true,
        'icons': <String, Object?>{
          'comment': <String, Object?>{
            'text': 'Retain this exact visual note.',
            'pinned': false,
            'height': 80,
            'width': 176,
          },
        },
        'fields': <String, Object?>{
          'VAR': <String, Object?>{'id': 'rich-message-variable'},
        },
        'inputs': <String, Object?>{
          'VALUE': <String, Object?>{
            'block': <String, Object?>{
              'type': 'text',
              'id': 'rich-message-text',
              'fields': <String, Object?>{'TEXT': 'PyBLE'},
            },
          },
        },
        'next': <String, Object?>{
          'block': <String, Object?>{
            'type': 'text_print',
            'id': 'rich-message-print',
            'inputs': <String, Object?>{
              'TEXT': <String, Object?>{
                'block': <String, Object?>{
                  'type': 'variables_get',
                  'id': 'rich-message-get',
                  'fields': <String, Object?>{
                    'VAR': <String, Object?>{'id': 'rich-message-variable'},
                  },
                },
              },
            },
          },
        },
      },
      <String, Object?>{
        'type': 'procedures_defnoreturn',
        'id': 'rich-greet-definition',
        'x': 336,
        'y': 48,
        'fields': <String, Object?>{'NAME': 'greet'},
        'icons': <String, Object?>{
          'comment': <String, Object?>{
            'text': 'A reusable greeting procedure.',
            'pinned': false,
            'height': 80,
            'width': 176,
          },
        },
        'extraState': <String, Object?>{
          'name': 'greet',
          'params': <Object?>[
            <String, Object?>{'name': 'name', 'id': 'rich-name-parameter'},
          ],
        },
        'inputs': <String, Object?>{
          'STACK': <String, Object?>{
            'block': <String, Object?>{
              'type': 'text_print',
              'id': 'rich-greet-print',
              'inputs': <String, Object?>{
                'TEXT': <String, Object?>{
                  'block': <String, Object?>{
                    'type': 'variables_get',
                    'id': 'rich-name-get',
                    'fields': <String, Object?>{
                      'VAR': <String, Object?>{'id': 'rich-name-parameter'},
                    },
                  },
                },
              },
            },
          },
        },
      },
      <String, Object?>{
        'type': 'procedures_callnoreturn',
        'id': 'rich-greet-call',
        'x': 336,
        'y': 264,
        'extraState': <String, Object?>{
          'name': 'greet',
          'params': <Object?>['name'],
        },
        'inputs': <String, Object?>{
          'ARG0': <String, Object?>{
            'block': <String, Object?>{
              'type': 'text',
              'id': 'rich-call-name',
              'fields': <String, Object?>{'TEXT': 'friend'},
            },
          },
        },
      },
      <String, Object?>{
        'type': 'text_print',
        'id': 'rich-disabled-print',
        'x': 48,
        'y': 304,
        'disabledReasons': <Object?>['MANUALLY_DISABLED'],
        'inputs': <String, Object?>{
          'TEXT': <String, Object?>{
            'block': <String, Object?>{
              'type': 'text',
              'id': 'rich-disabled-text',
              'fields': <String, Object?>{'TEXT': 'disabled'},
            },
          },
        },
      },
    ],
  },
});

String _seedSnapshot() => jsonEncode(<String, Object?>{
  'version': kBlocksBridgeVersion,
  'type': 'snapshot',
  'revision': 42,
  'source': 'print("waiting for GPIO workspace restore")\n',
  'workspace': <String, Object?>{
    'blocks': <String, Object?>{
      'languageVersion': 0,
      'blocks': <Object?>[
        <String, Object?>{
          'type': 'pyble_gpio_write',
          'id': 'write-pin',
          'x': 24,
          'y': 24,
          'fields': <String, Object?>{'LEVEL': 'HIGH'},
          'inputs': <String, Object?>{
            'PIN': <String, Object?>{
              'block': <String, Object?>{
                'type': 'pyble_gpio_pin',
                'id': 'output-pin',
                'fields': <String, Object?>{'MODE': 'OUT', 'PULL': 'NONE'},
                'inputs': <String, Object?>{
                  'GPIO': <String, Object?>{
                    'block': <String, Object?>{
                      'type': 'math_number',
                      'id': 'output-gpio',
                      'fields': <String, Object?>{'NUM': 2},
                    },
                  },
                },
              },
            },
          },
          'next': <String, Object?>{
            'block': <String, Object?>{
              'type': 'text_print',
              'id': 'print-input',
              'inputs': <String, Object?>{
                'TEXT': <String, Object?>{
                  'block': <String, Object?>{
                    'type': 'pyble_gpio_read',
                    'id': 'read-pin',
                    'inputs': <String, Object?>{
                      'PIN': <String, Object?>{
                        'block': <String, Object?>{
                          'type': 'pyble_gpio_pin',
                          'id': 'input-pin',
                          'fields': <String, Object?>{
                            'MODE': 'IN',
                            'PULL': 'UP',
                          },
                          'inputs': <String, Object?>{
                            'GPIO': <String, Object?>{
                              'block': <String, Object?>{
                                'type': 'math_number',
                                'id': 'input-gpio',
                                'fields': <String, Object?>{'NUM': 4},
                              },
                            },
                          },
                        },
                      },
                    },
                  },
                },
              },
            },
          },
        },
      ],
    },
  },
});

Future<void> _pumpUntil(
  WidgetTester tester,
  bool Function() condition, {
  String? reason,
  String Function()? diagnostics,
}) async {
  for (int attempt = 0; attempt < 80; attempt++) {
    if (condition()) return;
    await tester.pump(const Duration(milliseconds: 250));
  }
  final String detail = diagnostics == null ? '' : ': ${diagnostics()}';
  fail(
    '${reason ?? 'condition was not met before the on-device timeout'}$detail',
  );
}

Widget _testApp(ProviderContainer container, {required bool showBlocks}) {
  return UncontrolledProviderScope(
    container: container,
    child: MaterialApp(
      localizationsDelegates: AppLocalizations.localizationsDelegates,
      supportedLocales: AppLocalizations.supportedLocales,
      theme: PybleTheme.light,
      home: Scaffold(
        body: showBlocks
            ? const BlocksView()
            : const SizedBox.expand(key: ValueKey<String>('blocks-removed')),
      ),
    ),
  );
}

void registerBlocklyWebViewIntegrationTests() {
  testWidgets(
    'real offline WebView restores Blocks, generates Python, saves, and runs',
    (WidgetTester tester) async {
      final _RecordingConnection connection = _RecordingConnection();
      final ProviderContainer container = ProviderContainer(
        overrides: <Override>[connectionProvider.overrideWithValue(connection)],
      );
      final BlocksDocumentController controller = container.read(
        blocksDocumentProvider.notifier,
      );
      addTearDown(container.dispose);
      addTearDown(connection.dispose);

      controller.receiveBridgeMessage(_seedSnapshot());

      await tester.pumpWidget(_testApp(container, showBlocks: true));

      await _pumpUntil(
        tester,
        () {
          final GeneratedProgram? program = container
              .read(blocksDocumentProvider)
              .program;
          return program != null &&
              program.revision > 42 &&
              program.source == _expectedGpioSource;
        },
        reason:
            'the local Blockly asset did not restore and publish GPIO Python',
        diagnostics: () {
          final BlocksDocument state = container.read(blocksDocumentProvider);
          return 'status=${state.status}, error=${state.error}, '
              'workspaceError=${state.workspaceError}, '
              'revision=${state.retainedWorkspaceRevision}, '
              'source=${state.program?.source}';
        },
      );
      expect(find.text('Loading Blocks…'), findsNothing);

      // Exercise the real platform view through both orientation geometries.
      // The retained bridge snapshot must remain runnable; resize is a layout
      // event, never a source mutation or host reset.
      final Size initialPhysicalSize = tester.view.physicalSize;
      addTearDown(tester.view.resetPhysicalSize);
      final double shortSide = initialPhysicalSize.shortestSide;
      final double longSide = initialPhysicalSize.longestSide;
      final List<Size> rotationSequence = <Size>[
        Size(shortSide, longSide),
        Size(longSide, shortSide),
        Size(shortSide, longSide),
        initialPhysicalSize,
      ];
      for (final Size physicalSize in rotationSequence) {
        tester.view.physicalSize = physicalSize;
        await tester.pumpAndSettle();
        final GeneratedProgram? rotatedProgram = container
            .read(blocksDocumentProvider)
            .program;
        expect(rotatedProgram, isNotNull);
        expect(rotatedProgram!.source, _expectedGpioSource);
        expect(
          tester.widget<IconButton>(find.byKey(kBlocksRunButtonKey)).onPressed,
          isNotNull,
        );
      }

      await tester.tap(find.byKey(kBlocksPreviewButtonKey));
      await tester.pumpAndSettle();
      final Finder previewDialog = find.byType(AlertDialog);
      expect(previewDialog, findsOneWidget);
      expect(
        find.descendant(
          of: previewDialog,
          matching: find.text('Generated Python'),
        ),
        findsOneWidget,
      );
      expect(
        find.descendant(
          of: previewDialog,
          matching: find.textContaining('from machine import Pin'),
        ),
        findsOneWidget,
      );
      await tester.tap(
        find.descendant(of: previewDialog, matching: find.text('Close')),
      );
      await tester.pumpAndSettle();

      final int firstHostRevision = container
          .read(blocksDocumentProvider)
          .program!
          .revision;
      await tester.pumpWidget(_testApp(container, showBlocks: false));
      await tester.pumpAndSettle();
      await expectLater(
        container.read(blocksDocumentProvider.notifier).previewSource(),
        throwsA(isA<BlocksHostUnavailable>()),
      );

      await tester.pumpWidget(_testApp(container, showBlocks: true));
      expect(
        tester.widget<IconButton>(find.byKey(kBlocksRunButtonKey)).onPressed,
        isNull,
        reason: 'retained source stays disabled until the new host restores it',
      );
      await _pumpUntil(
        tester,
        () {
          final BlocksDocument state = container.read(blocksDocumentProvider);
          return state.status == BlocksStatus.ready &&
              state.program != null &&
              state.program!.revision > firstHostRevision &&
              state.program!.source == _expectedGpioSource;
        },
        reason:
            'the recreated WebView did not restore the retained GPIO workspace',
      );

      await tester.tap(find.byKey(kBlocksSaveButtonKey));
      await _pumpUntil(tester, () => connection.writes.length == 2);
      expect(connection.writes[0].$1, kBlocksGeneratedPath);
      expect(utf8.decode(connection.writes[0].$2), _expectedGpioSource);
      expect(
        connection.writes[1].$1,
        blocksCompanionPathFor(kBlocksGeneratedPath),
      );
      final BlocksCompanion savedCompanion = BlocksCompanion.parse(
        utf8.decode(connection.writes[1].$2),
      );
      expect(
        savedCompanion.matchesPython(
          path: kBlocksGeneratedPath,
          source: _expectedGpioSource,
        ),
        isTrue,
      );

      await tester.tap(find.byKey(kBlocksRunButtonKey));
      await _pumpUntil(tester, () => connection.runs.length == 1);
      expect(connection.writes, hasLength(4));
      expect(connection.runs.single, kBlocksGeneratedPath);

      // A required GPIO socket is commonly incomplete while the graph is being
      // assembled. Its serialized graph must survive a real WebView recreation
      // without the startup watchdog replacing the repairable host.
      final int invalidRevision =
          container.read(blocksDocumentProvider).retainedWorkspaceRevision! + 1;
      controller.receiveBridgeMessage(
        jsonEncode(<String, Object?>{
          'version': kBlocksBridgeVersion,
          'type': 'error',
          'message': 'GPIO write requires a Pin input.',
          'revision': invalidRevision,
          'workspace': <String, Object?>{
            'blocks': <String, Object?>{
              'languageVersion': 0,
              'blocks': <Object?>[
                <String, Object?>{
                  'type': 'pyble_gpio_write',
                  'id': 'incomplete-write',
                  'x': 24,
                  'y': 24,
                  'fields': <String, Object?>{'LEVEL': 'LOW'},
                },
              ],
            },
          },
        }),
      );
      await tester.pump();
      expect(container.read(blocksDocumentProvider).workspaceError, isNotNull);
      expect(
        tester
            .widget<IconButton>(find.byKey(kBlocksPreviewButtonKey))
            .onPressed,
        isNull,
      );

      await tester.pumpWidget(_testApp(container, showBlocks: false));
      await tester.pumpAndSettle();
      await tester.pumpWidget(_testApp(container, showBlocks: true));
      await _pumpUntil(
        tester,
        () {
          final BlocksDocument state = container.read(blocksDocumentProvider);
          return state.status == BlocksStatus.ready &&
              state.workspaceError != null &&
              state.retainedWorkspaceRevision! > invalidRevision &&
              controller.hasActiveReadyHost;
        },
        reason:
            'the recreated WebView did not retain the incomplete GPIO graph',
      );
      final int restoredInvalidRevision = container
          .read(blocksDocumentProvider)
          .retainedWorkspaceRevision!;

      // Model the user's completed socket at the validated bridge boundary,
      // then make a fresh real host prove the repaired graph restores and
      // regenerates the same actionable Python.
      final Map<String, dynamic> validSeed =
          jsonDecode(_seedSnapshot()) as Map<String, dynamic>;
      final int repairRevision = restoredInvalidRevision + 1;
      controller.receiveBridgeMessage(
        jsonEncode(<String, Object?>{
          'version': kBlocksBridgeVersion,
          'type': 'snapshot',
          'revision': repairRevision,
          'source': _expectedGpioSource,
          'workspace': validSeed['workspace'],
        }),
      );
      await tester.pumpWidget(_testApp(container, showBlocks: false));
      await tester.pumpAndSettle();
      await tester.pumpWidget(_testApp(container, showBlocks: true));
      await _pumpUntil(
        tester,
        () {
          final BlocksDocument state = container.read(blocksDocumentProvider);
          return state.status == BlocksStatus.ready &&
              state.workspaceError == null &&
              state.program?.revision != null &&
              state.program!.revision > repairRevision &&
              state.program!.source == _expectedGpioSource &&
              controller.hasActiveReadyHost;
        },
        reason: 'the repaired GPIO graph did not regenerate after recreation',
      );
      expect(
        tester
            .widget<IconButton>(find.byKey(kBlocksPreviewButtonKey))
            .onPressed,
        isNotNull,
      );

      // The beginner chooser uses the same real WebView generator in a
      // scratch workspace. Browsing and previewing must not change the active
      // revision; explicit replacement loads a normal editable clone but
      // still performs no board write or Run.
      final BlocksDocument beforeExamples = container.read(
        blocksDocumentProvider,
      );
      final int writesBeforeExamples = connection.writes.length;
      final int runsBeforeExamples = connection.runs.length;
      await tester.tap(find.byKey(kBlocksExamplesButtonKey));
      await _pumpUntil(
        tester,
        () => find.byKey(kBlocksExamplesCatalogKey).evaluate().isNotEmpty,
        reason: 'the bundled beginner example chooser did not open',
      );
      await _pumpUntil(
        tester,
        () =>
            find.textContaining("print('Hello, PyBLE!')").evaluate().isNotEmpty,
        reason:
            'the real scratch Blockly workspace did not generate the Hello preview',
      );
      final BlocksDocument afterHelloPreview = container.read(
        blocksDocumentProvider,
      );
      expect(
        afterHelloPreview.retainedWorkspaceJson,
        beforeExamples.retainedWorkspaceJson,
      );
      expect(
        afterHelloPreview.retainedWorkspaceRevision,
        beforeExamples.retainedWorkspaceRevision,
      );

      await tester.tap(
        find.byKey(const ValueKey<String>('blocksExampleCard-blink-neopixel')),
      );
      await tester.pumpAndSettle();
      await tester.enterText(
        find.widgetWithText(TextField, 'NeoPixel data GPIO'),
        '48',
      );
      await _pumpUntil(
        tester,
        () =>
            find
                .textContaining('from neopixel import NeoPixel')
                .evaluate()
                .isNotEmpty &&
            find.textContaining('NeoPixel(Pin(48').evaluate().isNotEmpty,
        reason:
            'the real scratch Blockly workspace did not generate the standard '
            'NeoPixel API from the user-selected GPIO',
      );
      final BlocksDocument afterNeoPixelPreview = container.read(
        blocksDocumentProvider,
      );
      expect(
        afterNeoPixelPreview.retainedWorkspaceJson,
        beforeExamples.retainedWorkspaceJson,
      );
      expect(connection.writes, hasLength(writesBeforeExamples));
      expect(connection.runs, hasLength(runsBeforeExamples));

      const String importedNeoPixelPython = '''
from machine import Pin
from neopixel import NeoPixel

pixels = NeoPixel(Pin(48, Pin.OUT), 1)
pixels[0] = (20, 0, 0)
pixels.write()
pixels.fill((0, 0, 0))
pixels.write()
''';
      final PythonBlocksConversion neoPixelConversion =
          const PythonToBlocksConverter().convert(importedNeoPixelPython);
      expect(neoPixelConversion.diagnostics, isEmpty);
      final BlocksExamplePreview neoPixelRoundTrip = await controller
          .previewExample(neoPixelConversion.workspaceJson!);
      expect(
        neoPixelRoundTrip.source,
        contains('from neopixel import NeoPixel'),
      );
      final PythonBlocksConversion generatedNeoPixel =
          const PythonToBlocksConverter().convert(
            neoPixelRoundTrip.source,
            productionGenerated: true,
          );
      expect(generatedNeoPixel.diagnostics, isEmpty);
      expect(
        generatedNeoPixel.semanticFingerprint,
        neoPixelConversion.semanticFingerprint,
      );

      await tester.tap(
        find.byKey(const ValueKey<String>('blocksExampleCard-blink-led')),
      );
      await tester.pumpAndSettle();
      await tester.enterText(find.widgetWithText(TextField, 'LED GPIO'), '17');
      await _pumpUntil(
        tester,
        () => find.textContaining('Pin(17, Pin.OUT').evaluate().isNotEmpty,
        reason:
            'the real scratch Blockly workspace did not materialize the selected LED GPIO',
      );
      final Finder replaceWorkspaceAction = find.byKey(
        kBlocksExampleReplaceWorkspaceButtonKey,
      );
      await tester.ensureVisible(replaceWorkspaceAction);
      await tester.pumpAndSettle();
      expect(replaceWorkspaceAction.hitTestable(), findsOneWidget);
      await tester.tap(replaceWorkspaceAction);
      await tester.pumpAndSettle();
      final Finder replaceDialog = find.byType(AlertDialog);
      expect(replaceDialog, findsOneWidget);
      await tester.tap(
        find.descendant(
          of: replaceDialog,
          matching: find.text('Replace workspace'),
        ),
      );
      await tester.pump(const Duration(milliseconds: 300));
      await _pumpUntil(
        tester,
        () {
          final BlocksDocument state = container.read(blocksDocumentProvider);
          return state.status == BlocksStatus.ready &&
              state.program?.source == _expectedBlinkSource &&
              controller.hasActiveReadyHost;
        },
        reason:
            'the selected Blink example did not restore as an editable workspace',
      );
      expect(connection.writes, hasLength(writesBeforeExamples));
      expect(connection.runs, hasLength(runsBeforeExamples));

      // The bounded Dart importer emits ordinary Blockly serialization. The
      // real production host must restore it, generate executable Python, keep
      // it provisional until commit, and then persist its dynamic target as a
      // source-first/sidecar-last bundle.
      const String importedPython = '''
from machine import Pin
from time import sleep_ms

led = Pin(17, Pin.OUT)
for i in range(2):
    led.value(1)
    sleep_ms(100)
    led.value(0)
''';
      final PythonBlocksConversion conversion = const PythonToBlocksConverter()
          .convert(importedPython);
      expect(conversion.diagnostics, isEmpty);
      expect(conversion.workspaceJson, isNotNull);
      final int writesBeforeImport = connection.writes.length;
      final int runsBeforeImport = connection.runs.length;
      final BlocksDocument beforeImportPreview = container.read(
        blocksDocumentProvider,
      );
      final BlocksExamplePreview scratchImport = await controller
          .previewExample(conversion.workspaceJson!);
      final PythonBlocksConversion generatedImport =
          const PythonToBlocksConverter().convert(
            scratchImport.source,
            productionGenerated: true,
          );
      expect(generatedImport.diagnostics, isEmpty);
      expect(conversion.semanticFingerprint, isNotNull);
      expect(generatedImport.semanticFingerprint, isNotNull);
      expect(
        generatedImport.semanticFingerprint,
        conversion.semanticFingerprint,
        reason:
            'production generation must reparse to the same normalized model',
      );
      expect(
        container.read(blocksDocumentProvider).retainedWorkspaceJson,
        beforeImportPreview.retainedWorkspaceJson,
        reason: 'the disposable production preview must be non-mutating',
      );
      final Future<GeneratedProgram> staged = controller.stageWorkspaceReview(
        workspaceJson: scratchImport.workspaceJson,
        expectedSource: scratchImport.source,
        targetPath: '/main.py',
        replace: true,
      );
      await tester.pump();
      await _pumpUntil(
        tester,
        () {
          final BlocksDocument state = container.read(blocksDocumentProvider);
          return state.status == BlocksStatus.ready &&
              state.workspaceReviewPending &&
              state.program?.source.contains('led = Pin(17, Pin.OUT, None)') ==
                  true &&
              state.program?.source.contains('for i in range(2):') == true &&
              controller.hasActiveReadyHost;
        },
        reason:
            'the production Blockly host did not restore the Dart-imported workspace',
      );
      final GeneratedProgram importedPreview = await staged;
      expect(importedPreview.source, contains('sleep_ms(100)'));
      expect(connection.writes, hasLength(writesBeforeImport));
      expect(connection.runs, hasLength(runsBeforeImport));

      controller.commitWorkspaceReview();
      await tester.pump();
      expect(container.read(blocksDocumentProvider).targetPath, '/main.py');
      expect(
        tester.widget<IconButton>(find.byKey(kBlocksSaveButtonKey)).onPressed,
        isNotNull,
      );
      await tester.tap(find.byKey(kBlocksSaveButtonKey));
      await _pumpUntil(
        tester,
        () => connection.writes.length == writesBeforeImport + 2,
      );
      expect(connection.writes[writesBeforeImport].$1, '/main.py');
      expect(
        connection.writes[writesBeforeImport + 1].$1,
        '/main.py.pyble-blocks.json',
      );
      final BlocksCompanion importedCompanion = BlocksCompanion.parse(
        utf8.decode(connection.writes[writesBeforeImport + 1].$2),
      );
      expect(
        importedCompanion.matchesPython(
          path: '/main.py',
          source: importedPreview.source,
        ),
        isTrue,
      );
      final BlocksExamplePreview exactReopen = await controller.previewExample(
        importedCompanion.workspaceJson,
      );
      expect(exactReopen.source, importedCompanion.pythonSource);
      expect(
        jsonDecode(exactReopen.workspaceJson),
        jsonDecode(importedCompanion.workspaceJson),
        reason:
            'exact sidecar restoration must preserve every serialized field',
      );

      // Exercise the explicit File Explorer recovery contract through the
      // actual Connection.getFile seam. First ask the pinned production host
      // to canonicalize a deliberately rich workspace, then persist that
      // canonical source/workspace pair as an adjacent companion. Reopening
      // must preserve visual identity fields that are intentionally outside
      // the bounded Python importer's semantic model.
      const String exactPath = '/rich.py';
      final BlocksExamplePreview richCanonical = await controller
          .previewExample(_richExactWorkspace());
      final Map<String, dynamic> richWorkspace =
          jsonDecode(richCanonical.workspaceJson) as Map<String, dynamic>;
      final List<dynamic> richVariables =
          richWorkspace['variables']! as List<dynamic>;
      final List<dynamic> richTopBlocks =
          (richWorkspace['blocks']! as Map<String, dynamic>)['blocks']!
              as List<dynamic>;
      expect(richVariables.first, <String, Object?>{
        'name': 'message',
        'id': 'rich-message-variable',
      });
      expect(
        richVariables
            .map(
              (dynamic variable) =>
                  (variable! as Map<String, dynamic>)['id'] as String,
            )
            .toList(),
        <String>['rich-message-variable', 'rich-name-parameter'],
      );
      expect(
        richTopBlocks
            .map(
              (dynamic block) =>
                  (block! as Map<String, dynamic>)['id'] as String,
            )
            .toList(),
        <String>[
          'rich-message-set',
          'rich-greet-definition',
          'rich-greet-call',
          'rich-disabled-print',
        ],
        reason: 'top-level block order and IDs are exact visual state',
      );
      final Map<String, dynamic> richSet =
          richTopBlocks[0]! as Map<String, dynamic>;
      expect(richSet['x'], 48);
      expect(richSet['y'], 48);
      expect(richSet['collapsed'], isTrue);
      expect(
        ((richSet['icons']! as Map<String, dynamic>)['comment']!
            as Map<String, dynamic>)['text'],
        'Retain this exact visual note.',
      );
      final Map<String, dynamic> richDefinition =
          richTopBlocks[1]! as Map<String, dynamic>;
      expect(richDefinition['extraState'], <String, Object?>{
        'params': <Object?>[
          <String, Object?>{'name': 'name', 'id': 'rich-name-parameter'},
        ],
      });
      expect(
        (richTopBlocks[2]! as Map<String, dynamic>)['extraState'],
        <String, Object?>{
          'name': 'greet',
          'params': <Object?>['name'],
        },
      );
      expect(
        (richTopBlocks[3]! as Map<String, dynamic>)['disabledReasons'],
        contains('MANUALLY_DISABLED'),
      );

      final BlocksCompanion richCompanion = BlocksCompanion.create(
        pythonPath: exactPath,
        pythonSource: richCanonical.source,
        workspaceJson: richCanonical.workspaceJson,
      );
      await connection.seedFile(
        exactPath,
        Uint8List.fromList(utf8.encode(richCanonical.source)),
      );
      await connection.seedFile(
        blocksCompanionPathFor(exactPath),
        Uint8List.fromList(utf8.encode(richCompanion.encode())),
      );
      final EditorDocument editorBeforeExactDownload = container.read(
        editorDocumentProvider,
      );
      final AppSurface surfaceBeforeExactDownload = container.read(
        selectedSurfaceProvider,
      );
      final BlocksDocument blocksBeforeExactDownload = container.read(
        blocksDocumentProvider,
      );
      final int readsBeforeExact = connection.reads.length;
      final EditorDocument? downloadedExact = await container
          .read(fileExplorerProvider.notifier)
          .downloadForBlocks('rich.py');
      expect(downloadedExact, isNotNull);
      final EditorDocument capturedExact = downloadedExact!;
      expect(capturedExact.boardPath, exactPath);
      expect(capturedExact.content, richCanonical.source);
      expect(
        container.read(editorDocumentProvider),
        editorBeforeExactDownload,
        reason: 'Open as Blocks must not replace the Editor document',
      );
      expect(
        container.read(selectedSurfaceProvider),
        surfaceBeforeExactDownload,
        reason: 'source download alone must not change navigation',
      );
      expect(
        container.read(blocksDocumentProvider),
        same(blocksBeforeExactDownload),
        reason: 'source download must not mutate the Blocks document',
      );
      final PythonBlocksPreparation exactPreparation = await container
          .read(pythonBlocksPreparationProvider)
          .prepare(capturedExact, readCompanion: true);
      expect(
        connection.reads.skip(readsBeforeExact),
        <String>[exactPath, blocksCompanionPathFor(exactPath)],
        reason:
            'the explicit reopen GETs the source, then its adjacent companion',
      );
      expect(container.read(editorDocumentProvider), editorBeforeExactDownload);
      expect(
        container.read(selectedSurfaceProvider),
        surfaceBeforeExactDownload,
      );
      expect(
        exactPreparation.origin,
        PythonBlocksPreparationOrigin.exactCompanion,
      );
      expect(exactPreparation.targetPath, exactPath);
      expect(exactPreparation.expectedSource, richCanonical.source);
      expect(exactPreparation.diagnostics, isEmpty);

      final BlocksDocument beforeExactPreview = container.read(
        blocksDocumentProvider,
      );
      final BlocksExamplePreview exactSidecarPreview = await controller
          .previewExample(exactPreparation.workspaceJson!);
      expect(exactSidecarPreview.source, richCanonical.source);
      expect(
        jsonDecode(exactSidecarPreview.workspaceJson),
        jsonDecode(exactPreparation.workspaceJson!),
        reason:
            'production scratch recovery preserves IDs, ordering, coordinates, '
            'comments, extraState, variables, procedures, collapsed state, and '
            'disabled state',
      );
      expect(
        container.read(blocksDocumentProvider).retainedWorkspaceJson,
        beforeExactPreview.retainedWorkspaceJson,
        reason: 'exact companion preview is disposable and non-mutating',
      );
      expect(
        container.read(blocksDocumentProvider).targetPath,
        beforeExactPreview.targetPath,
      );

      final int writesBeforeExact = connection.writes.length;
      final int runsBeforeExact = connection.runs.length;
      final Future<GeneratedProgram> exactStage = controller
          .stageWorkspaceReview(
            workspaceJson: exactSidecarPreview.workspaceJson,
            expectedSource: exactSidecarPreview.source,
            targetPath: exactPreparation.targetPath,
            replace: true,
          );
      await tester.pump();
      await _pumpUntil(
        tester,
        () {
          final BlocksDocument state = container.read(blocksDocumentProvider);
          return state.status == BlocksStatus.ready &&
              state.workspaceReviewPending &&
              state.targetPath == exactPath &&
              state.program?.source == richCanonical.source &&
              controller.hasActiveReadyHost;
        },
        reason:
            'the real production host did not acknowledge the exact sidecar',
      );
      final GeneratedProgram exactAcknowledgement = await exactStage;
      expect(exactAcknowledgement.source, richCanonical.source);
      expect(
        jsonDecode(exactAcknowledgement.workspaceJson),
        jsonDecode(exactPreparation.workspaceJson!),
      );
      expect(connection.writes, hasLength(writesBeforeExact));
      expect(connection.runs, hasLength(runsBeforeExact));

      controller.commitWorkspaceReview();
      await tester.pump();
      final BlocksDocument committedExact = container.read(
        blocksDocumentProvider,
      );
      expect(committedExact.workspaceReviewPending, isFalse);
      expect(committedExact.targetPath, exactPath);
      expect(committedExact.program?.source, richCanonical.source);
      expect(
        jsonDecode(committedExact.retainedWorkspaceJson!),
        jsonDecode(exactPreparation.workspaceJson!),
      );

      // A production acknowledgement that differs by even one source byte
      // fails closed. The provisional target must not stick, and the prior
      // exact document must be recreated without a board write or Run.
      final int loadAttemptBeforeMismatch = committedExact.loadAttempt;
      final int priorRevision = committedExact.program!.revision;
      final Future<GeneratedProgram> mismatchStage = controller
          .stageWorkspaceReview(
            workspaceJson: exactPreparation.workspaceJson!,
            expectedSource: '${richCanonical.source}# must not match\n',
            targetPath: '/examples/mismatch.py',
            replace: true,
          );
      final Future<void> mismatchExpectation = expectLater(
        mismatchStage,
        throwsA(isA<BlocksGenerationFailed>()),
      );
      await tester.pump();
      await _pumpUntil(
        tester,
        () {
          final BlocksDocument state = container.read(blocksDocumentProvider);
          return state.loadAttempt >= loadAttemptBeforeMismatch + 2 &&
              state.status == BlocksStatus.ready &&
              !state.workspaceReviewPending &&
              state.targetPath == exactPath &&
              state.program != null &&
              state.program!.revision > priorRevision &&
              state.program!.source == richCanonical.source &&
              controller.hasActiveReadyHost;
        },
        reason:
            'a mismatched production load did not recreate the prior exact document',
      );
      await mismatchExpectation;
      final BlocksDocument afterMismatch = container.read(
        blocksDocumentProvider,
      );
      expect(afterMismatch.targetPath, committedExact.targetPath);
      expect(afterMismatch.program?.source, committedExact.program?.source);
      expect(
        jsonDecode(afterMismatch.retainedWorkspaceJson!),
        jsonDecode(committedExact.retainedWorkspaceJson!),
      );
      expect(connection.writes, hasLength(writesBeforeExact));
      expect(connection.runs, hasLength(runsBeforeExact));
    },
    timeout: const Timeout(Duration(minutes: 2)),
  );
}

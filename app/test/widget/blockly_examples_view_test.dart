// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.
//
// A-31 beginner examples increment [red] — native chooser and safety contract.

import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:pyble/blocks/blocks.dart';
import 'package:pyble/localization/localization.dart';
import 'package:pyble/pble/pble.dart';

import '../support/feature_harness.dart';
import '../support/recording_connection.dart';
import '../support/repo_paths.dart';

const ValueKey<String> _examplesButtonKey = ValueKey<String>(
  'blocksExamplesButton',
);
const ValueKey<String> _emptyExamplesButtonKey = ValueKey<String>(
  'blocksEmptyExamplesButton',
);
const ValueKey<String> _catalogKey = ValueKey<String>('blocksExamplesCatalog');
const ValueKey<String> _previewKey = ValueKey<String>(
  'blocksExamplePreviewButton',
);
const ValueKey<String> _createCopyKey = ValueKey<String>(
  'blocksExampleCreateCopyButton',
);
const ValueKey<String> _replaceKey = ValueKey<String>(
  'blocksExampleReplaceWorkspaceButton',
);

Finder _fieldWithLabel(String label) => find.byWidgetPredicate(
  (Widget widget) =>
      widget is TextField && widget.decoration?.labelText == label,
);

Override _fakeWorkspace() => blocksWorkspaceBuilderProvider.overrideWithValue(
  (Key key) => SizedBox.expand(key: key),
);

Override _fakeExamplePreviewer() => blocksExamplePreviewerProvider
    .overrideWithValue((String workspaceJson) async {
      return BlocksExamplePreview(
        source: workspaceJson.contains('hello-print')
            ? "print('Hello, PyBLE!')\n"
            : '# Generated from the selected example.\n',
        workspaceJson: workspaceJson,
      );
    });

Override _fakeExampleCatalog() =>
    blocksExampleCatalogProvider.overrideWith((Ref ref) async {
      final File catalog = File(
        '${appPackageRoot().path}/assets/blockly/examples/catalog.json',
      );
      return BlocksExampleCatalog.parse(catalog.readAsStringSync());
    });

String _snapshot({required bool empty, int revision = 1}) =>
    jsonEncode(<String, Object?>{
      'version': kBlocksBridgeVersion,
      'type': 'snapshot',
      'revision': revision,
      'source': empty ? '' : "print('keep my workspace')\n",
      'workspace': <String, Object?>{
        'blocks': <String, Object?>{
          'languageVersion': 0,
          'blocks': empty
              ? <Object?>[]
              : <Object?>[
                  <String, Object?>{
                    'type': 'text_print',
                    'id': 'existing-print',
                    'inputs': <String, Object?>{
                      'TEXT': <String, Object?>{
                        'block': <String, Object?>{
                          'type': 'text',
                          'id': 'existing-text',
                          'fields': <String, Object?>{
                            'TEXT': 'keep my workspace',
                          },
                        },
                      },
                    },
                  },
                ],
        },
      },
    });

Future<RecordingConnection> _pump(
  WidgetTester tester, {
  required bool empty,
  Size size = const Size(1024, 768),
  BlocksExamplePreviewer? previewer,
}) async {
  final RecordingConnection connection = RecordingConnection(
    initial: ConnState.ready,
  );
  await pumpSurface(
    tester,
    const BlocksView(),
    connection: connection,
    extra: <Override>[
      _fakeWorkspace(),
      previewer == null
          ? _fakeExamplePreviewer()
          : blocksExamplePreviewerProvider.overrideWithValue(previewer),
      _fakeExampleCatalog(),
    ],
    size: size,
  );
  containerOf(tester)
      .read(blocksDocumentProvider.notifier)
      .receiveBridgeMessage(_snapshot(empty: empty));
  await tester.pump();
  return connection;
}

void main() {
  group('A-31 beginner examples chooser', () {
    testWidgets('empty workspace has a prominent CTA and toolbar entry', (
      WidgetTester tester,
    ) async {
      await _pump(tester, empty: true);
      final AppLocalizations l10n = l10nOf(tester);

      expect(find.byKey(_examplesButtonKey), findsOneWidget);
      expect(find.byKey(_emptyExamplesButtonKey), findsOneWidget);
      expect(find.byTooltip(l10n.blocksExamples), findsOneWidget);
      expect(find.text(l10n.blocksExamplesEmptyTitle), findsOneWidget);
      expect(find.text(l10n.blocksExamplesOpen), findsOneWidget);
      expect(
        tester.getSize(find.byKey(_examplesButtonKey)).height,
        greaterThanOrEqualTo(48),
      );

      await tester.tap(find.byKey(_emptyExamplesButtonKey));
      await tester.pumpAndSettle();
      expect(find.byKey(_catalogKey), findsOneWidget);
      for (final String title in <String>[
        'Hello PyBLE',
        'Count repeatedly',
        'Blink an LED',
        'Blink a NeoPixel',
        'Read a button',
        'Button controls LED',
        'Reusable function',
      ]) {
        expect(find.text(title), findsOneWidget);
      }
      await tester.tap(find.byIcon(Icons.close));
      await tester.pumpAndSettle();
    });

    testWidgets(
      'preview is non-mutating, never runs, and offers Create copy when empty',
      (WidgetTester tester) async {
        final RecordingConnection connection = await _pump(tester, empty: true);
        final ProviderContainer container = containerOf(tester);
        final BlocksDocument before = container.read(blocksDocumentProvider);

        expect(
          tester.widget<IconButton>(find.byKey(_examplesButtonKey)).onPressed,
          isNotNull,
        );
        tester.widget<IconButton>(find.byKey(_examplesButtonKey)).onPressed!();
        await tester.pumpAndSettle();
        await tester.tap(
          find.byKey(const ValueKey<String>('blocksExampleCard-hello-pyble')),
        );
        await tester.pumpAndSettle();

        expect(find.byKey(_previewKey), findsOneWidget);
        expect(find.byKey(_createCopyKey), findsOneWidget);
        expect(find.byKey(_replaceKey), findsNothing);
        expect(find.text('Generated Python'), findsOneWidget);
        expect(
          find.text('Choose an action below to generate Python.'),
          findsOneWidget,
        );
        expect(find.text('Generating Python…'), findsNothing);
        expect(
          find.textContaining("print('Hello, PyBLE!')"),
          findsNothing,
          reason: 'opening and browsing must not invoke the platform previewer',
        );

        await tester.tap(find.byKey(_previewKey));
        await tester.pumpAndSettle();
        expect(find.textContaining("print('Hello, PyBLE!')"), findsWidgets);

        final BlocksDocument after = container.read(blocksDocumentProvider);
        expect(after.retainedWorkspaceJson, before.retainedWorkspaceJson);
        expect(
          after.retainedWorkspaceRevision,
          before.retainedWorkspaceRevision,
        );
        expect(connection.putFileCalls, isEmpty);
        expect(connection.runFileCalls, isEmpty);
        expect(connection.runSourceCalls, isEmpty);
        await tester.tap(find.text('Close'));
        await tester.pumpAndSettle();
        await tester.tap(find.byIcon(Icons.close));
        await tester.pumpAndSettle();
      },
    );

    testWidgets(
      'successful preview has one stable localized live-region announcement',
      (WidgetTester tester) async {
        final SemanticsHandle semantics = tester.ensureSemantics();
        try {
          await _pump(tester, empty: true);
          final AppLocalizations l10n = l10nOf(tester);

          await tester.tap(find.byKey(_emptyExamplesButtonKey));
          await tester.pumpAndSettle();
          expect(find.textContaining("print('Hello, PyBLE!')"), findsNothing);
          await tester.tap(find.byKey(_previewKey));
          await tester.pumpAndSettle();
          expect(find.textContaining("print('Hello, PyBLE!')"), findsWidgets);
          await tester.tap(find.text('Close'));
          await tester.pumpAndSettle();

          Finder previewLiveRegions() => find.descendant(
            of: find.byKey(_catalogKey),
            matching: find.byWidgetPredicate(
              (Widget widget) =>
                  widget is Semantics && widget.properties.liveRegion == true,
            ),
          );

          expect(
            previewLiveRegions(),
            findsOneWidget,
            reason:
                'a completed preview must expose exactly one announcement '
                'inside the chooser',
          );
          final Semantics announcement = tester.widget<Semantics>(
            previewLiveRegions(),
          );
          expect(
            announcement.properties.label,
            l10n.blocksCodePreviewTitle,
            reason: 'the ready announcement must use localized app copy',
          );
          final int semanticsNodeId = tester
              .getSemantics(previewLiveRegions())
              .id;

          tester.platformDispatcher.textScaleFactorTestValue = 1.1;
          addTearDown(tester.platformDispatcher.clearTextScaleFactorTestValue);
          await tester.pumpAndSettle();

          expect(
            previewLiveRegions(),
            findsOneWidget,
            reason:
                'an unchanged successful preview must not add another live '
                'announcement',
          );
          expect(
            tester.widget<Semantics>(previewLiveRegions()).properties.label,
            l10n.blocksCodePreviewTitle,
          );
          expect(
            tester.getSemantics(previewLiveRegions()).id,
            semanticsNodeId,
            reason:
                'ordinary rebuilds must retain the existing announcement '
                'instead of announcing unchanged preview content again',
          );
        } finally {
          semantics.dispose();
        }
      },
    );

    testWidgets('Create copy loads an editable clone without board I/O', (
      WidgetTester tester,
    ) async {
      final RecordingConnection connection = await _pump(tester, empty: true);
      final ProviderContainer container = containerOf(tester);

      await tester.tap(find.byKey(_emptyExamplesButtonKey));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(_createCopyKey));
      await tester.pump(const Duration(milliseconds: 300));

      final BlocksDocument state = container.read(blocksDocumentProvider);
      expect(state.status, BlocksStatus.loading);
      expect(state.program, isNull);
      expect(state.retainedWorkspaceJson, contains('hello-print'));
      expect(connection.putFileCalls, isEmpty);
      expect(connection.runFileCalls, isEmpty);
      expect(connection.runSourceCalls, isEmpty);
      expect(
        find.textContaining('Example loaded'),
        findsNothing,
        reason: 'staging candidate JSON is not a successful platform restore',
      );

      final Object? restoredWorkspace = jsonDecode(
        state.retainedWorkspaceJson!,
      );
      expect(restoredWorkspace, isA<Map<String, dynamic>>());
      final BlocksDocumentController controller = container.read(
        blocksDocumentProvider.notifier,
      );
      final int hostId = controller.beginHost(
        requestSnapshot: (int requestId) async {},
      );
      controller.markHostLoading(hostId);
      controller.receiveBridgeMessage(
        jsonEncode(<String, Object?>{
          'version': kBlocksBridgeVersion,
          'type': 'snapshot',
          'revision': 2,
          'source': "print('Hello, PyBLE!')\n",
          'workspace': restoredWorkspace,
        }),
        hostId: hostId,
      );
      await tester.pumpAndSettle();

      expect(find.textContaining('Example loaded'), findsOneWidget);
    });

    testWidgets('non-empty workspace requires confirmed replacement', (
      WidgetTester tester,
    ) async {
      final RecordingConnection connection = await _pump(tester, empty: false);
      final ProviderContainer container = containerOf(tester);
      final String retainedBefore = container
          .read(blocksDocumentProvider)
          .retainedWorkspaceJson!;

      tester.widget<IconButton>(find.byKey(_examplesButtonKey)).onPressed!();
      await tester.pumpAndSettle();
      await tester.tap(
        find.byKey(const ValueKey<String>('blocksExampleCard-hello-pyble')),
      );
      await tester.pump(const Duration(milliseconds: 300));

      expect(find.byKey(_createCopyKey), findsNothing);
      expect(find.byKey(_replaceKey), findsOneWidget);
      await tester.tap(find.byKey(_replaceKey));
      await tester.pumpAndSettle();

      expect(find.text('Replace the current block workspace?'), findsOneWidget);
      expect(
        container.read(blocksDocumentProvider).retainedWorkspaceJson,
        retainedBefore,
        reason: 'replacement must not happen before explicit confirmation',
      );
      expect(connection.putFileCalls, isEmpty);
      expect(connection.runFileCalls, isEmpty);
      await tester.tap(
        find.descendant(
          of: find.byType(AlertDialog),
          matching: find.text('Replace workspace'),
        ),
      );
      await tester.pump(const Duration(milliseconds: 300));
      final BlocksDocument replaced = container.read(blocksDocumentProvider);
      expect(replaced.status, BlocksStatus.loading);
      expect(replaced.retainedWorkspaceJson, contains('hello-print'));
      expect(connection.putFileCalls, isEmpty);
      expect(connection.runFileCalls, isEmpty);
    });

    testWidgets('cancelling replacement preserves the exact active document', (
      WidgetTester tester,
    ) async {
      final RecordingConnection connection = await _pump(tester, empty: false);
      final ProviderContainer container = containerOf(tester);
      final BlocksDocument before = container.read(blocksDocumentProvider);
      final AppLocalizations l10n = l10nOf(tester);

      tester.widget<IconButton>(find.byKey(_examplesButtonKey)).onPressed!();
      await tester.pumpAndSettle();
      await tester.tap(
        find.byKey(const ValueKey<String>('blocksExampleCard-hello-pyble')),
      );
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(_replaceKey));
      await tester.pumpAndSettle();
      expect(find.text(l10n.blocksExamplesReplaceTitle), findsOneWidget);

      await tester.tap(
        find.descendant(
          of: find.byType(AlertDialog),
          matching: find.text(l10n.commonCancel),
        ),
      );
      await tester.pumpAndSettle();

      final BlocksDocument after = container.read(blocksDocumentProvider);
      expect(after, same(before));
      expect(after.retainedWorkspaceJson, before.retainedWorkspaceJson);
      expect(after.retainedWorkspaceRevision, before.retainedWorkspaceRevision);
      expect(find.text(l10n.blocksExamplesLoaded), findsNothing);
      expect(connection.putFileCalls, isEmpty);
      expect(connection.runFileCalls, isEmpty);
      expect(connection.runSourceCalls, isEmpty);
    });

    testWidgets(
      'GPIO preview requires explicit valid pins and shows guidance',
      (WidgetTester tester) async {
        final RecordingConnection connection = await _pump(tester, empty: true);
        tester.widget<IconButton>(find.byKey(_examplesButtonKey)).onPressed!();
        await tester.pumpAndSettle();
        await tester.tap(
          find.byKey(const ValueKey<String>('blocksExampleCard-blink-led')),
        );
        await tester.pumpAndSettle();

        expect(
          find.textContaining('GPIO numbers vary by board'),
          findsOneWidget,
        );
        expect(
          find.text('Enter every required GPIO to enable generation.'),
          findsOneWidget,
        );
        expect(find.textContaining('wiring'), findsWidgets);
        expect(find.widgetWithText(TextField, 'LED GPIO'), findsOneWidget);
        expect(
          tester.widget<ButtonStyleButton>(find.byKey(_previewKey)).onPressed,
          isNull,
        );

        await tester.enterText(
          find.widgetWithText(TextField, 'LED GPIO'),
          '17',
        );
        await tester.pump();
        expect(
          tester.widget<ButtonStyleButton>(find.byKey(_previewKey)).onPressed,
          isNotNull,
        );
        expect(connection.putFileCalls, isEmpty);
        expect(connection.runFileCalls, isEmpty);
        await tester.tap(find.byIcon(Icons.close));
        await tester.pumpAndSettle();
      },
    );

    testWidgets(
      'GPIO editing does not invoke the platform previewer until an action',
      (WidgetTester tester) async {
        int previewCalls = 0;
        await _pump(
          tester,
          empty: true,
          previewer: (String workspaceJson) async {
            previewCalls += 1;
            return BlocksExamplePreview(
              source: '# explicit preview\n',
              workspaceJson: workspaceJson,
            );
          },
        );
        tester.widget<IconButton>(find.byKey(_examplesButtonKey)).onPressed!();
        await tester.pumpAndSettle();
        expect(
          previewCalls,
          0,
          reason: 'opening the native chooser must not invoke the WebView',
        );
        await tester.tap(
          find.byKey(
            const ValueKey<String>('blocksExampleCard-count-repeatedly'),
          ),
        );
        await tester.pumpAndSettle();
        expect(
          previewCalls,
          0,
          reason: 'selecting a non-GPIO example must remain preview-idle',
        );
        await tester.tap(
          find.byKey(const ValueKey<String>('blocksExampleCard-blink-led')),
        );
        await tester.pumpAndSettle();
        expect(
          previewCalls,
          0,
          reason: 'selecting an example must not invoke the WebView',
        );

        await tester.enterText(_fieldWithLabel('LED GPIO'), '-1');
        await tester.pumpAndSettle();
        expect(
          previewCalls,
          0,
          reason: 'validating an invalid GPIO must remain native-only',
        );
        await tester.enterText(_fieldWithLabel('LED GPIO'), '');
        await tester.pumpAndSettle();
        expect(
          previewCalls,
          0,
          reason: 'clearing a GPIO draft must remain native-only',
        );
        await tester.enterText(_fieldWithLabel('LED GPIO'), '2');
        await tester.pumpAndSettle();
        expect(
          previewCalls,
          0,
          reason:
              'typing must not call into Android WebView while Gboard owns focus',
        );

        await tester.tap(find.byKey(_previewKey));
        await tester.pumpAndSettle();
        expect(previewCalls, 1);
      },
    );

    testWidgets(
      'tablet GPIO field keeps its input connection across keyboard layout',
      (WidgetTester tester) async {
        const double physicalKeyboardInset = 640;
        addTearDown(tester.view.resetViewInsets);
        await _pump(tester, empty: true);
        tester.widget<IconButton>(find.byKey(_examplesButtonKey)).onPressed!();
        await tester.pumpAndSettle();
        await tester.tap(
          find.byKey(const ValueKey<String>('blocksExampleCard-blink-led')),
        );
        await tester.pumpAndSettle();

        Finder gpioField = _fieldWithLabel('LED GPIO');
        await tester.tap(gpioField);
        await tester.pump();
        Finder editable = find.descendant(
          of: gpioField,
          matching: find.byType(EditableText),
        );
        final TextField originalField = tester.widget<TextField>(gpioField);
        final Key? originalKey = originalField.key;
        final TextEditingController? originalController =
            originalField.controller;
        final FocusNode originalFocus = tester
            .widget<EditableText>(editable)
            .focusNode;
        expect(originalKey, isA<GlobalKey>());
        expect(originalController, isNotNull);
        expect(originalFocus.hasFocus, isTrue);
        expect(tester.testTextInput.isVisible, isTrue);

        tester.view.viewInsets = const FakeViewPadding(
          bottom: physicalKeyboardInset,
        );
        await tester.pump();
        await tester.pump(const Duration(milliseconds: 220));

        gpioField = _fieldWithLabel('LED GPIO');
        editable = find.descendant(
          of: gpioField,
          matching: find.byType(EditableText),
        );
        final FocusNode rebuiltFocus = tester
            .widget<EditableText>(editable)
            .focusNode;
        final TextField rebuiltField = tester.widget<TextField>(gpioField);
        expect(rebuiltField.key, same(originalKey));
        expect(rebuiltField.controller, same(originalController));
        expect(
          rebuiltFocus,
          same(originalFocus),
          reason: 'responsive reparenting must retain the real text field',
        );
        expect(rebuiltFocus.hasFocus, isTrue);
        expect(tester.testTextInput.isVisible, isTrue);

        tester.testTextInput.enterText('1');
        await tester.pump();
        gpioField = _fieldWithLabel('LED GPIO');
        editable = find.descendant(
          of: gpioField,
          matching: find.byType(EditableText),
        );
        final TextField afterFirstDigit = tester.widget<TextField>(gpioField);
        final FocusNode afterFirstDigitFocus = tester
            .widget<EditableText>(editable)
            .focusNode;
        expect(afterFirstDigit.key, same(originalKey));
        expect(afterFirstDigit.controller, same(originalController));
        expect(afterFirstDigit.controller?.text, '1');
        expect(afterFirstDigitFocus, same(originalFocus));
        expect(afterFirstDigitFocus.hasFocus, isTrue);
        expect(tester.testTextInput.isVisible, isTrue);

        tester.testTextInput.enterText('12');
        await tester.pump();
        gpioField = _fieldWithLabel('LED GPIO');
        editable = find.descendant(
          of: gpioField,
          matching: find.byType(EditableText),
        );
        final TextField afterSecondDigit = tester.widget<TextField>(gpioField);
        final FocusNode afterSecondDigitFocus = tester
            .widget<EditableText>(editable)
            .focusNode;
        expect(afterSecondDigit.key, same(originalKey));
        expect(afterSecondDigit.controller, same(originalController));
        expect(afterSecondDigit.controller?.text, '12');
        expect(afterSecondDigitFocus, same(originalFocus));
        expect(afterSecondDigitFocus.hasFocus, isTrue);
        expect(tester.testTextInput.isVisible, isTrue);

        tester.testTextInput.updateEditingValue(
          const TextEditingValue(
            text: '1',
            selection: TextSelection.collapsed(offset: 1),
          ),
        );
        await tester.pump();
        gpioField = _fieldWithLabel('LED GPIO');
        editable = find.descendant(
          of: gpioField,
          matching: find.byType(EditableText),
        );
        final TextField afterDeletion = tester.widget<TextField>(gpioField);
        final FocusNode afterDeletionFocus = tester
            .widget<EditableText>(editable)
            .focusNode;
        expect(afterDeletion.key, same(originalKey));
        expect(afterDeletion.controller, same(originalController));
        expect(afterDeletion.controller?.text, '1');
        expect(afterDeletionFocus, same(originalFocus));
        expect(afterDeletionFocus.hasFocus, isTrue);
        expect(tester.testTextInput.isVisible, isTrue);

        tester.testTextInput.updateEditingValue(
          const TextEditingValue(
            text: '12',
            selection: TextSelection.collapsed(offset: 2),
          ),
        );
        await tester.pump();
        gpioField = _fieldWithLabel('LED GPIO');
        editable = find.descendant(
          of: gpioField,
          matching: find.byType(EditableText),
        );
        final TextField afterReentry = tester.widget<TextField>(gpioField);
        final FocusNode afterReentryFocus = tester
            .widget<EditableText>(editable)
            .focusNode;
        expect(afterReentry.key, same(originalKey));
        expect(afterReentry.controller, same(originalController));
        expect(afterReentry.controller?.text, '12');
        expect(afterReentryFocus, same(originalFocus));
        expect(afterReentryFocus.hasFocus, isTrue);
        expect(tester.testTextInput.isVisible, isTrue);
      },
    );

    testWidgets('NeoPixel example stays generic and requires its data GPIO', (
      WidgetTester tester,
    ) async {
      final RecordingConnection connection = await _pump(tester, empty: true);
      tester.widget<IconButton>(find.byKey(_examplesButtonKey)).onPressed!();
      await tester.pumpAndSettle();
      await tester.tap(
        find.byKey(const ValueKey<String>('blocksExampleCard-blink-neopixel')),
      );
      await tester.pumpAndSettle();

      final Finder gpioField = _fieldWithLabel('NeoPixel data GPIO');
      expect(gpioField, findsOneWidget);
      expect(tester.widget<TextField>(gpioField).controller?.text, isEmpty);
      expect(find.textContaining('WS2812-compatible pixel'), findsOneWidget);
      expect(
        tester.widget<ButtonStyleButton>(find.byKey(_previewKey)).onPressed,
        isNull,
      );

      await tester.enterText(gpioField, '48');
      await tester.pump();
      expect(
        tester.widget<ButtonStyleButton>(find.byKey(_previewKey)).onPressed,
        isNotNull,
      );
      expect(connection.putFileCalls, isEmpty);
      expect(connection.runFileCalls, isEmpty);
    });

    testWidgets('duplicate GPIO roles show an error and recover visibly', (
      WidgetTester tester,
    ) async {
      final RecordingConnection connection = await _pump(tester, empty: true);
      tester.widget<IconButton>(find.byKey(_examplesButtonKey)).onPressed!();
      await tester.pumpAndSettle();
      await tester.tap(
        find.byKey(
          const ValueKey<String>('blocksExampleCard-button-controls-led'),
        ),
      );
      await tester.pumpAndSettle();

      final Finder ledField = _fieldWithLabel('LED GPIO');
      final Finder buttonField = _fieldWithLabel('Button GPIO');
      expect(ledField, findsOneWidget);
      expect(buttonField, findsOneWidget);
      await tester.enterText(ledField, '17');
      await tester.enterText(buttonField, '17');
      await tester.pump();

      final Iterable<String> errors = <Finder>[ledField, buttonField]
          .map(
            (Finder field) =>
                tester.widget<TextField>(field).decoration?.errorText,
          )
          .whereType<String>();
      expect(
        errors,
        isNotEmpty,
        reason:
            'beginners need an explanation when distinct hardware roles use '
            'the same GPIO',
      );
      expect(
        tester.widget<ButtonStyleButton>(find.byKey(_previewKey)).onPressed,
        isNull,
      );
      expect(
        tester.widget<ButtonStyleButton>(find.byKey(_createCopyKey)).onPressed,
        isNull,
      );

      await tester.enterText(buttonField, '23');
      await tester.pumpAndSettle();

      final Iterable<String> recoveredErrors = <Finder>[ledField, buttonField]
          .map(
            (Finder field) =>
                tester.widget<TextField>(field).decoration?.errorText,
          )
          .whereType<String>();
      expect(recoveredErrors, isEmpty);
      expect(
        tester.widget<ButtonStyleButton>(find.byKey(_previewKey)).onPressed,
        isNotNull,
      );
      expect(
        tester.widget<ButtonStyleButton>(find.byKey(_createCopyKey)).onPressed,
        isNotNull,
      );
      expect(connection.putFileCalls, isEmpty);
      expect(connection.runFileCalls, isEmpty);
      expect(connection.runSourceCalls, isEmpty);
    });

    testWidgets(
      'empty generated source with a real graph hides the empty-state CTA',
      (WidgetTester tester) async {
        await _pump(tester, empty: true);
        containerOf(tester)
            .read(blocksDocumentProvider.notifier)
            .receiveBridgeMessage(
              jsonEncode(<String, Object?>{
                'version': kBlocksBridgeVersion,
                'type': 'snapshot',
                'revision': 2,
                'source': '',
                'workspace': <String, Object?>{
                  'blocks': <String, Object?>{
                    'languageVersion': 0,
                    'blocks': <Object?>[
                      <String, Object?>{
                        'type': 'text_print',
                        'id': 'disabled-print',
                        'enabled': false,
                      },
                    ],
                  },
                },
              }),
            );
        await tester.pump();

        expect(
          find.byKey(_emptyExamplesButtonKey),
          findsNothing,
          reason:
              'semantic workspace content, not generated-source length, owns '
              'the beginner empty state',
        );
        expect(find.byKey(_examplesButtonKey), findsOneWidget);
      },
    );

    testWidgets('toolbox request opens the shared chooser at its example', (
      WidgetTester tester,
    ) async {
      await _pump(tester, empty: true);
      final BlocksBridgeResult result = containerOf(tester)
          .read(blocksDocumentProvider.notifier)
          .receiveBridgeMessage(
            jsonEncode(<String, Object?>{
              'version': kBlocksBridgeVersion,
              'type': 'openExamples',
              'exampleId': 'blink-led',
            }),
          );
      expect(result, BlocksBridgeResult.exampleCatalogRequested);
      await tester.pumpAndSettle();

      expect(find.byKey(_catalogKey), findsOneWidget);
      expect(find.widgetWithText(TextField, 'LED GPIO'), findsOneWidget);
      await tester.tap(find.byIcon(Icons.close));
      await tester.pumpAndSettle();
    });

    for (final ({Size size, double textScale}) testCase
        in <({Size size, double textScale})>[
          (size: Size(320, 480), textScale: 1),
          (size: Size(667, 375), textScale: 1),
          (size: Size(320, 480), textScale: 2),
          (size: Size(320, 480), textScale: 3),
        ]) {
      testWidgets('compact chooser scrolls without clipping at '
          '${testCase.size.width}x${testCase.size.height}, '
          '${testCase.textScale}x text', (WidgetTester tester) async {
        tester.platformDispatcher.textScaleFactorTestValue = testCase.textScale;
        addTearDown(tester.platformDispatcher.clearTextScaleFactorTestValue);
        await _pump(tester, empty: true, size: testCase.size);
        tester.widget<IconButton>(find.byKey(_examplesButtonKey)).onPressed!();
        await tester.pumpAndSettle();

        expect(
          tester.takeException(),
          isNull,
          reason:
              'the chooser must scroll instead of overflowing on a short '
              'viewport or at large text',
        );
        expect(find.byKey(_catalogKey), findsOneWidget);

        final Finder lastExample = find.byKey(
          const ValueKey<String>('blocksExampleCard-reusable-function'),
        );
        await Scrollable.ensureVisible(
          tester.element(lastExample),
          alignment: 0.5,
        );
        await tester.pumpAndSettle();
        expect(lastExample.hitTestable(), findsOneWidget);

        for (final Finder action in <Finder>[
          find.byKey(_previewKey),
          find.byKey(_createCopyKey),
        ]) {
          await Scrollable.ensureVisible(
            tester.element(action),
            alignment: 0.5,
          );
          await tester.pumpAndSettle();
          expect(action.hitTestable(), findsOneWidget);
          expect(
            tester.getSize(action).height,
            greaterThanOrEqualTo(48),
            reason: 'compact chooser actions retain touch target height',
          );
          final Rect bounds = tester.getRect(action);
          expect(
            bounds.center.dy,
            inInclusiveRange(0, testCase.size.height),
            reason:
                'the scrollable may clip a tall 3×-text button, but its '
                'interactive center must remain reachable',
          );
        }
        expect(tester.takeException(), isNull);
      });
    }

    testWidgets(
      'compact GPIO chooser keeps fields and actions above the keyboard',
      (WidgetTester tester) async {
        const Size size = Size(320, 480);
        const double physicalKeyboardInset = 360;
        addTearDown(tester.view.resetViewInsets);
        await _pump(tester, empty: true, size: size);
        tester.widget<IconButton>(find.byKey(_examplesButtonKey)).onPressed!();
        await tester.pumpAndSettle();

        final Finder blink = find.byKey(
          const ValueKey<String>('blocksExampleCard-blink-led'),
        );
        await tester.ensureVisible(blink);
        await tester.pumpAndSettle();
        await tester.tap(blink);
        await tester.pumpAndSettle();

        final Finder gpioField = _fieldWithLabel('LED GPIO');
        await tester.ensureVisible(gpioField);
        await tester.pumpAndSettle();
        await tester.tap(gpioField);
        tester.view.viewInsets = const FakeViewPadding(
          bottom: physicalKeyboardInset,
        );
        await tester.pump();
        await tester.pump(const Duration(milliseconds: 220));
        expect(tester.takeException(), isNull);

        final double visibleBottom =
            size.height - physicalKeyboardInset / tester.view.devicePixelRatio;
        await tester.ensureVisible(gpioField);
        await tester.pump();
        expect(gpioField.hitTestable(), findsOneWidget);
        expect(
          tester.getRect(gpioField).bottom,
          lessThanOrEqualTo(visibleBottom + 1),
        );

        await tester.enterText(gpioField, '17');
        await tester.pumpAndSettle();
        for (final Finder action in <Finder>[
          find.byKey(_previewKey),
          find.byKey(_createCopyKey),
        ]) {
          await tester.ensureVisible(action);
          await tester.pumpAndSettle();
          expect(action.hitTestable(), findsOneWidget);
          expect(tester.getSize(action).height, greaterThanOrEqualTo(48));
          expect(
            tester.getRect(action).bottom,
            lessThanOrEqualTo(visibleBottom + 1),
          );
        }
        expect(tester.takeException(), isNull);
      },
    );
  });
}

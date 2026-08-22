// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.
//
// A-20 — the EditorView: an ADR-0012 rich Python surface over the volatile
// in-memory current document (ADR-0010, TDD §11.6a, specs.md FR-EDIT §4.6),
// with the original plain field retained behind the app-owned seam. Binds
// through that seam only (CON-8); find/replace and file tabs remain deferred.
//
// Pins: an editable surface with the localized hint when empty; edits flow to
// editorDocumentProvider (dirty); the unsaved indicator shows while dirty; a
// "New" affordance resets to a fresh untitled buffer.

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:pyble/editor/editor.dart';
import 'package:pyble/localization/localization.dart';
import 'package:pyble/pble/pble.dart';

import '../support/feature_harness.dart';

/// Interactive key the EditorView must expose (for widget tests + HIL), mirroring
/// the ConnectScreen key-contract precedent.
const Key _newKey = ValueKey<String>('editorNewButton');

void main() {
  group('A-20 EditorView — editable surface', () {
    testWidgets('shows one-based logical line numbers including a blank tail', (
      WidgetTester tester,
    ) async {
      final FakeConnection fake = FakeConnection(initial: ConnState.ready);
      addTearDown(fake.dispose);
      await pumpSurface(tester, const EditorView(), connection: fake);

      containerOf(tester)
          .read(editorDocumentProvider.notifier)
          .openFromBoard(path: '/main.py', content: 'alpha\nbeta\n');
      await tester.pump();

      expect(find.byKey(kEditorRichSurfaceKey), findsOneWidget);
      expect(find.text('1'), findsOneWidget);
      expect(find.text('2'), findsOneWidget);
      expect(
        find.text('3'),
        findsOneWidget,
        reason: 'a trailing newline creates a numbered blank logical line',
      );

      await tester.enterText(find.byType(EditableText), 'alpha');
      await tester.pump();
      expect(find.text('1'), findsOneWidget);
      expect(find.text('2'), findsNothing);
      expect(find.text('3'), findsNothing);
    });

    testWidgets('font controls resize code and gutter without editing', (
      WidgetTester tester,
    ) async {
      final FakeConnection fake = FakeConnection(initial: ConnState.ready);
      addTearDown(fake.dispose);
      await pumpSurface(tester, const EditorView(), connection: fake);
      containerOf(tester)
          .read(editorDocumentProvider.notifier)
          .openFromBoard(path: '/main.py', content: 'alpha\nbeta');
      await tester.pump();

      final EditableText before = tester.widget<EditableText>(
        find.byType(EditableText),
      );
      before.controller.selection = const TextSelection.collapsed(offset: 3);
      final EditorDocument documentBefore = containerOf(
        tester,
      ).read(editorDocumentProvider);

      expect(before.style.fontSize, kEditorDefaultFontSize);
      expect(tester.widget<Text>(find.text('1')).style?.fontSize, 14);

      await tester.tap(find.byKey(kEditorIncreaseFontSizeButtonKey));
      await tester.pump();

      final EditableText after = tester.widget<EditableText>(
        find.byType(EditableText),
      );
      expect(after.style.fontSize, 15);
      expect(tester.widget<Text>(find.text('1')).style?.fontSize, 15);
      expect(
        after.controller.selection,
        const TextSelection.collapsed(offset: 3),
      );
      expect(
        containerOf(tester).read(editorDocumentProvider),
        same(documentBefore),
      );
    });

    testWidgets('font sizing preserves undo history', (
      WidgetTester tester,
    ) async {
      final FakeConnection fake = FakeConnection(initial: ConnState.ready);
      addTearDown(fake.dispose);
      await pumpSurface(tester, const EditorView(), connection: fake);

      await tester.enterText(find.byType(EditableText), 'value = 1');
      await tester.pump();
      await tester.tap(find.byKey(kEditorIncreaseFontSizeButtonKey));
      await tester.pump();

      Actions.invoke<UndoTextIntent>(
        tester.element(find.byType(EditableText)),
        const UndoTextIntent(SelectionChangedCause.keyboard),
      );
      await tester.pump();

      expect(containerOf(tester).read(editorDocumentProvider).content, isEmpty);
    });

    testWidgets('opening, zooming, and editing preserve literal tab bytes', (
      WidgetTester tester,
    ) async {
      final FakeConnection fake = FakeConnection(initial: ConnState.ready);
      addTearDown(fake.dispose);
      await pumpSurface(tester, const EditorView(), connection: fake);
      const String source = 'if True:\n\tprint(1)\n';
      containerOf(tester)
          .read(editorDocumentProvider.notifier)
          .openFromBoard(path: '/main.py', content: source);
      await tester.pump();

      EditableText editable = tester.widget<EditableText>(
        find.byType(EditableText),
      );
      expect(editable.controller.text, source);

      await tester.tap(find.byKey(kEditorIncreaseFontSizeButtonKey));
      await tester.pump();
      editable = tester.widget<EditableText>(find.byType(EditableText));
      expect(editable.controller.text, source);

      await tester.enterText(
        find.byType(EditableText),
        '$source# unrelated edit\n',
      );
      await tester.pump();

      expect(
        containerOf(tester).read(editorDocumentProvider).content,
        '$source# unrelated edit\n',
        reason: 'valid tab indentation is source data, never display state',
      );
    });

    testWidgets('font buttons are localized and disable at their bounds', (
      WidgetTester tester,
    ) async {
      final FakeConnection fake = FakeConnection(initial: ConnState.ready);
      addTearDown(fake.dispose);
      await pumpSurface(tester, const EditorView(), connection: fake);
      final AppLocalizations l10n = l10nOf(tester);

      expect(
        tester
            .widget<IconButton>(find.byKey(kEditorDecreaseFontSizeButtonKey))
            .tooltip,
        l10n.editorDecreaseFontSize,
      );
      expect(
        tester
            .widget<IconButton>(find.byKey(kEditorIncreaseFontSizeButtonKey))
            .tooltip,
        l10n.editorIncreaseFontSize,
      );

      containerOf(tester)
          .read(editorDisplaySettingsProvider.notifier)
          .setFontSize(kEditorMinFontSize);
      await tester.pump();
      expect(
        tester
            .widget<IconButton>(find.byKey(kEditorDecreaseFontSizeButtonKey))
            .onPressed,
        isNull,
      );

      containerOf(tester)
          .read(editorDisplaySettingsProvider.notifier)
          .setFontSize(kEditorMaxFontSize);
      await tester.pump();
      expect(
        tester
            .widget<IconButton>(find.byKey(kEditorIncreaseFontSizeButtonKey))
            .onPressed,
        isNull,
      );
    });

    testWidgets('maximum zoom composes with 2x accessibility text scaling', (
      WidgetTester tester,
    ) async {
      final FakeConnection fake = FakeConnection(initial: ConnState.ready);
      addTearDown(fake.dispose);
      await pumpSurface(
        tester,
        const MediaQuery(
          data: MediaQueryData(textScaler: TextScaler.linear(2)),
          child: EditorView(),
        ),
        connection: fake,
      );
      containerOf(tester)
          .read(editorDisplaySettingsProvider.notifier)
          .setFontSize(kEditorMaxFontSize);
      containerOf(tester)
          .read(editorDocumentProvider.notifier)
          .openFromBoard(
            path: '/main.py',
            content: List<String>.generate(
              120,
              (int index) => 'value_${index + 1} = ${index + 1}',
            ).join('\n'),
          );
      await tester.pump();

      expect(
        tester.widget<EditableText>(find.byType(EditableText)).style.fontSize,
        kEditorMaxFontSize,
      );
      expect(
        tester
            .state<EditableTextState>(find.byType(EditableText))
            .renderEditable
            .textScaler
            .scale(kEditorMaxFontSize),
        48,
      );
      expect(find.text('120'), findsOneWidget);
      expect(tester.takeException(), isNull);
    });

    testWidgets('compact editor changes font size without overflowing', (
      WidgetTester tester,
    ) async {
      final FakeConnection fake = FakeConnection(initial: ConnState.ready);
      addTearDown(fake.dispose);
      await pumpSurface(
        tester,
        const MediaQuery(
          data: MediaQueryData(
            textScaler: TextScaler.linear(2),
            highContrast: true,
          ),
          child: EditorView(),
        ),
        connection: fake,
        size: const Size(390, 844),
      );

      final AppLocalizations l10n = l10nOf(tester);
      expect(find.byKey(kEditorCompactFontSizeButtonKey), findsOneWidget);
      final Finder compactTooltip = find.descendant(
        of: find.byKey(kEditorCompactFontSizeButtonKey),
        matching: find.byType(Tooltip),
      );
      expect(compactTooltip, findsOneWidget);
      expect(
        tester.widget<Tooltip>(compactTooltip).message,
        l10n.editorFontSizeValue(kEditorDefaultFontSize.round()),
      );
      expect(tester.takeException(), isNull);
      await tester.tap(find.byKey(kEditorCompactFontSizeButtonKey));
      await tester.pumpAndSettle();
      expect(find.byKey(kEditorCompactFontSizeIncreaseKey), findsOneWidget);
      expect(find.text(l10n.editorIncreaseFontSize), findsOneWidget);
      expect(
        tester.getSize(find.byKey(kEditorCompactFontSizeIncreaseKey)).height,
        greaterThanOrEqualTo(48),
      );
      expect(tester.takeException(), isNull);

      await tester.tap(find.byKey(kEditorCompactFontSizeIncreaseKey));
      await tester.pumpAndSettle();
      expect(
        containerOf(tester).read(editorDisplaySettingsProvider).fontSize,
        kEditorDefaultFontSize + kEditorFontSizeStep,
      );
      expect(
        tester.widget<EditableText>(find.byType(EditableText)).style.fontSize,
        kEditorDefaultFontSize + kEditorFontSizeStep,
      );
    });

    for (final ({double width, bool compact}) breakpoint
        in <({double width, bool compact})>[
          // The header consumes 24 dp of horizontal padding before measuring
          // the width available to its actions.
          (width: 623, compact: true),
          (width: 624, compact: false),
        ]) {
      testWidgets('font controls adapt at ${breakpoint.width.toInt()} dp', (
        WidgetTester tester,
      ) async {
        final FakeConnection fake = FakeConnection(initial: ConnState.ready);
        addTearDown(fake.dispose);
        await pumpSurface(
          tester,
          const EditorView(),
          connection: fake,
          size: Size(breakpoint.width, 844),
        );

        expect(
          find.byKey(kEditorCompactFontSizeButtonKey),
          breakpoint.compact ? findsOneWidget : findsNothing,
        );
        expect(
          find.byKey(kEditorIncreaseFontSizeButtonKey),
          breakpoint.compact ? findsNothing : findsOneWidget,
        );
        expect(tester.takeException(), isNull);
      });
    }

    testWidgets('font size survives editor unmount in the same app session', (
      WidgetTester tester,
    ) async {
      final FakeConnection fake = FakeConnection(initial: ConnState.ready);
      addTearDown(fake.dispose);
      late StateSetter setHostState;
      bool showEditor = true;
      await pumpSurface(
        tester,
        StatefulBuilder(
          builder: (BuildContext context, StateSetter setState) {
            setHostState = setState;
            return showEditor
                ? const EditorView()
                : const SizedBox(key: ValueKey<String>('otherSurface'));
          },
        ),
        connection: fake,
      );
      containerOf(
        tester,
      ).read(editorDisplaySettingsProvider.notifier).setFontSize(19);
      await tester.pump();

      setHostState(() => showEditor = false);
      await tester.pump();
      expect(find.byType(EditorView), findsNothing);
      setHostState(() => showEditor = true);
      await tester.pump();

      expect(
        tester.widget<EditableText>(find.byType(EditableText)).style.fontSize,
        19,
      );
    });

    testWidgets('gutter tracks vertical scroll and ignores horizontal scroll', (
      WidgetTester tester,
    ) async {
      final FakeConnection fake = FakeConnection(initial: ConnState.ready);
      addTearDown(fake.dispose);
      await pumpSurface(
        tester,
        const EditorView(),
        connection: fake,
        size: const Size(800, 480),
      );
      final String longLine =
          'print("${List<String>.filled(120, 'x').join()}")';
      containerOf(tester)
          .read(editorDocumentProvider.notifier)
          .openFromBoard(
            path: '/main.py',
            content: List<String>.filled(100, longLine).join('\n'),
          );
      await tester.pump();

      final double gutterLeft = tester.getTopLeft(find.text('1')).dx;
      final List<ScrollableState> vertical = tester
          .stateList<ScrollableState>(find.byType(Scrollable))
          .where(
            (ScrollableState state) =>
                state.widget.axisDirection == AxisDirection.down &&
                state.position.maxScrollExtent > 0,
          )
          .toList();
      expect(vertical.length, 2);
      vertical.first.position.jumpTo(300);
      await tester.pump();
      expect(
        (vertical.first.position.pixels - vertical.last.position.pixels).abs(),
        lessThan(0.01),
      );

      final ScrollableState horizontal = tester
          .stateList<ScrollableState>(find.byType(Scrollable))
          .singleWhere(
            (ScrollableState state) =>
                state.widget.axisDirection == AxisDirection.right &&
                state.position.maxScrollExtent > 0,
          );
      horizontal.position.jumpTo(300);
      await tester.pump();
      expect(horizontal.position.pixels, 300);
      expect(tester.getTopLeft(find.text('1')).dx, gutterLeft);
    });

    testWidgets('editor hint and font value have exact semantic labels', (
      WidgetTester tester,
    ) async {
      final FakeConnection fake = FakeConnection(initial: ConnState.ready);
      addTearDown(fake.dispose);
      await pumpSurface(tester, const EditorView(), connection: fake);
      final AppLocalizations l10n = l10nOf(tester);

      expect(
        tester.getSemantics(find.byKey(kEditorRichSurfaceKey)).label,
        l10n.editorHintText,
      );
      expect(
        tester.getSemantics(find.byKey(kEditorFontSizeValueKey)).label,
        l10n.editorFontSizeValue(kEditorDefaultFontSize.round()),
      );
    });

    testWidgets('exposes the app-layer Python to Blocks action', (
      WidgetTester tester,
    ) async {
      final FakeConnection fake = FakeConnection(initial: ConnState.ready);
      addTearDown(fake.dispose);
      int calls = 0;
      await pumpSurface(
        tester,
        EditorView(onConvertToBlocks: () => calls += 1),
        connection: fake,
      );

      await tester.tap(find.byKey(kEditorConvertToBlocksButtonKey));
      await tester.pump();

      expect(calls, 1);
      expect(
        tester
            .widget<IconButton>(find.byKey(kEditorConvertToBlocksButtonKey))
            .tooltip,
        l10nOf(tester).editorConvertToBlocks,
      );
    });

    testWidgets('shows a monospace editable field with the hint when empty', (
      WidgetTester tester,
    ) async {
      final FakeConnection fake = FakeConnection(initial: ConnState.ready);
      addTearDown(fake.dispose);
      await pumpSurface(tester, const EditorView(), connection: fake);
      containerOf(tester).read(editorDocumentProvider.notifier).newDocument();
      await tester.pump();

      final AppLocalizations l10n = l10nOf(tester);
      expect(
        find.byType(EditableText),
        findsOneWidget,
        reason: 'the editor is a real editable surface, not a placeholder',
      );
      expect(
        find.text(l10n.editorHintText),
        findsOneWidget,
        reason: 'the empty buffer shows the localized MicroPython hint',
      );
      expect(
        find.text('1'),
        findsOneWidget,
        reason: 'the empty buffer still has logical line one',
      );
    });

    testWidgets('typing updates the current document and marks it dirty', (
      WidgetTester tester,
    ) async {
      final FakeConnection fake = FakeConnection(initial: ConnState.ready);
      addTearDown(fake.dispose);
      await pumpSurface(tester, const EditorView(), connection: fake);
      containerOf(tester).read(editorDocumentProvider.notifier).newDocument();
      await tester.pump();

      await tester.enterText(find.byType(EditableText), 'x = 1');
      await tester.pump();

      final EditorDocument doc = containerOf(
        tester,
      ).read(editorDocumentProvider);
      expect(doc.content, 'x = 1');
      expect(doc.dirty, isTrue);
    });

    testWidgets('shows the unsaved-changes indicator only while dirty', (
      WidgetTester tester,
    ) async {
      final FakeConnection fake = FakeConnection(initial: ConnState.ready);
      addTearDown(fake.dispose);
      await pumpSurface(tester, const EditorView(), connection: fake);
      final AppLocalizations l10n = l10nOf(tester);

      containerOf(tester)
          .read(editorDocumentProvider.notifier)
          .openFromBoard(path: '/main.py', content: 'a\n');
      await tester.pump();
      expect(
        find.text(l10n.editorUnsavedLabel),
        findsNothing,
        reason: 'a freshly-opened file is clean',
      );

      await tester.enterText(find.byType(EditableText), 'a\nb\n');
      await tester.pump();
      expect(
        find.text(l10n.editorUnsavedLabel),
        findsOneWidget,
        reason: 'editing surfaces the unsaved indicator (dirty)',
      );
    });

    testWidgets('New resets to a fresh untitled buffer', (
      WidgetTester tester,
    ) async {
      final FakeConnection fake = FakeConnection(initial: ConnState.ready);
      addTearDown(fake.dispose);
      await pumpSurface(tester, const EditorView(), connection: fake);

      containerOf(tester)
          .read(editorDocumentProvider.notifier)
          .openFromBoard(path: '/old.py', content: 'stuff\n');
      await tester.pump();

      await tester.tap(find.byKey(_newKey));
      await tester.pumpAndSettle();

      final EditorDocument doc = containerOf(
        tester,
      ).read(editorDocumentProvider);
      expect(doc.name, 'untitled.py'); // ASCII technical id, not localized
      expect(doc.content, isEmpty);
      expect(doc.boardPath, isNull);
      expect(doc.dirty, isFalse);
    });
  });
}

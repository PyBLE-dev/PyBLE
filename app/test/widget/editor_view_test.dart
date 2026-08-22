// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.
//
// A-20 [red] — the EditorView: a monospace, SignalCodeColors-styled editable
// surface over the volatile in-memory current document (ADR-0010, TDD §11.6a,
// specs.md FR-EDIT §4.6). v1 is a real editable field (no heavy code-editor dep,
// no google_fonts — OI-1/NFR-OFF); syntax highlighting / tabs / find-replace are
// deferred to A-24/OI-1. Binds through the seam ONLY (CON-8).
//
// Pins: an editable surface with the localized hint when empty; edits flow to
// editorDocumentProvider (dirty); the unsaved indicator shows while dirty; a
// "New" affordance resets to a fresh untitled buffer.
//
// CURRENTLY RED: lib/editor exports no EditorView. HAND-OFF:
// lib/editor/editor_view.dart -> app-editor-console-engineer.

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

      editable.controller.value = const TextEditingValue(
        text: '${source}# unrelated edit\n',
        selection: TextSelection.collapsed(
          offset: '${source}# unrelated edit\n'.length,
        ),
      );
      await tester.pump();

      expect(
        containerOf(tester).read(editorDocumentProvider).content,
        '${source}# unrelated edit\n',
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
      expect(find.text('120'), findsOneWidget);
      expect(tester.takeException(), isNull);
    });

    testWidgets('compact editor exposes font sizing without overflowing', (
      WidgetTester tester,
    ) async {
      final FakeConnection fake = FakeConnection(initial: ConnState.ready);
      addTearDown(fake.dispose);
      await pumpSurface(
        tester,
        const EditorView(),
        connection: fake,
        size: const Size(390, 844),
      );

      expect(find.byKey(kEditorCompactFontSizeButtonKey), findsOneWidget);
      expect(tester.takeException(), isNull);
      await tester.tap(find.byKey(kEditorCompactFontSizeButtonKey));
      await tester.pumpAndSettle();
      expect(find.byKey(kEditorCompactFontSizeIncreaseKey), findsOneWidget);
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

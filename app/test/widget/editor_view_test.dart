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

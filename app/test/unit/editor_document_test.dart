// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.
//
// A-20 [red] — the working-loop current-document provider (ADR-0010, TDD §11.6a,
// specs.md FR-EDIT §4.6). A single volatile in-memory document the editor edits,
// run-control runs, and the files explorer opens-into / uploads-from. Survives
// navigation (a keep-alive provider), NOT a process restart — persistence is the
// A-24 hook (openFromBoard / markSaved), a RECORDED deviation from FR-EDIT-7
// (carried, not dropped).
//
// Pins the frozen contract (illustrative sketch → the [red] test is the freeze):
//   EditorDocument { String name; String content; bool dirty; String? boardPath }
//   editorDocumentProvider = NotifierProvider<EditorDocumentController, EditorDocument>
//     newDocument()                        -> fresh untitled empty (dirty=false, boardPath=null)
//     setContent(String)                   -> content; dirty=true if changed
//     openFromBoard(path:, content:)       -> name=leaf(path), boardPath=path, dirty=false
//     markSaved({boardPath})               -> dirty=false; adopt boardPath   [A-24 hook]
//   The default filename `untitled.py` is an ASCII technical id, never an ARB
//   string (FR-I18N-4).
//
// CURRENTLY RED: lib/editor exports no EditorDocument / editorDocumentProvider.
// HAND-OFF: lib/editor/editor_document.dart -> app-editor-console-engineer.

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:pyble/editor/editor.dart';

void main() {
  ProviderContainer makeContainer() {
    final ProviderContainer container = ProviderContainer();
    addTearDown(container.dispose);
    return container;
  }

  EditorDocument doc(ProviderContainer c) => c.read(editorDocumentProvider);
  EditorDocumentController ctrl(ProviderContainer c) =>
      c.read(editorDocumentProvider.notifier);

  group('A-20 EditorDocument value type', () {
    test('exposes the four frozen ASCII fields', () {
      const EditorDocument d = EditorDocument(
        name: 'main.py',
        content: 'print(1)\n',
        dirty: true,
        boardPath: '/main.py',
      );
      expect(d.name, 'main.py');
      expect(d.content, 'print(1)\n');
      expect(d.dirty, isTrue);
      expect(d.boardPath, '/main.py');
    });
  });

  group('A-20 editorDocumentProvider — new / edit', () {
    test('newDocument yields a fresh untitled empty buffer', () {
      final ProviderContainer c = makeContainer();
      ctrl(c).newDocument();

      final EditorDocument d = doc(c);
      // untitled.py is a technical identifier (ASCII constant, NOT localized).
      expect(d.name, 'untitled.py');
      expect(d.content, isEmpty);
      expect(d.dirty, isFalse);
      expect(d.boardPath, isNull);
    });

    test('setContent updates content and marks the buffer dirty', () {
      final ProviderContainer c = makeContainer();
      ctrl(c).newDocument();

      ctrl(c).setContent('x = 1\n');
      expect(doc(c).content, 'x = 1\n');
      expect(doc(c).dirty, isTrue);
    });

    test('mutation epoch detects edit-away-then-back identity changes', () {
      final ProviderContainer c = makeContainer();
      ctrl(c).setContent('print("captured")\n');
      final EditorDocument captured = doc(c);
      final int capturedEpoch = c.read(editorDocumentEpochProvider);

      ctrl(c).setContent('print("temporary")\n');
      ctrl(c).setContent('print("captured")\n');

      expect(doc(c), captured, reason: 'the four visible fields match again');
      expect(c.read(editorDocumentEpochProvider), greaterThan(capturedEpoch));
    });

    test(
      'setContent to the identical content does not re-dirty a clean buffer',
      () {
        final ProviderContainer c = makeContainer();
        ctrl(c).openFromBoard(path: '/main.py', content: 'print(1)\n');
        expect(doc(c).dirty, isFalse);

        ctrl(c).setContent('print(1)\n'); // no change
        expect(
          doc(c).dirty,
          isFalse,
          reason: 'dirty flips only when the content actually changes',
        );
      },
    );
  });

  group('A-20 editorDocumentProvider — open from board', () {
    test('openFromBoard adopts the leaf name + board path, clean', () {
      final ProviderContainer c = makeContainer();
      ctrl(c).openFromBoard(path: '/lib/blink.py', content: 'led.on()\n');

      final EditorDocument d = doc(c);
      expect(d.name, 'blink.py', reason: 'name is the leaf of the board path');
      expect(d.content, 'led.on()\n');
      expect(d.boardPath, '/lib/blink.py');
      expect(
        d.dirty,
        isFalse,
        reason: 'a freshly-opened board file has no unsaved edits',
      );
    });
  });

  group('A-20 editorDocumentProvider — markSaved (A-24 persistence hook)', () {
    test('markSaved clears dirty and adopts the given board path', () {
      final ProviderContainer c = makeContainer();
      ctrl(c).newDocument();
      ctrl(c).setContent('print("hi")\n');
      expect(doc(c).dirty, isTrue);

      ctrl(c).markSaved(boardPath: '/untitled.py');
      expect(doc(c).dirty, isFalse);
      expect(doc(c).boardPath, '/untitled.py');
      expect(
        doc(c).content,
        'print("hi")\n',
        reason: 'markSaved changes only dirty/boardPath, never the buffer',
      );
    });

    test('markSaved without a path keeps the existing board path', () {
      final ProviderContainer c = makeContainer();
      ctrl(c).openFromBoard(path: '/main.py', content: 'a\n');
      ctrl(c).setContent('a\nb\n');

      ctrl(c).markSaved();
      expect(doc(c).dirty, isFalse);
      expect(doc(c).boardPath, '/main.py');
    });
  });
}

// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.
//
// A-20 — the editor SAVE seam (specs.md FR-EDIT-2, ADR-0010, TDD §11.6a).
//
// Regression cover for the "cannot save" defects found on the bench board:
//   * there was NO save-to-board affordance bound to the editor document at all;
//   * the files-surface upload wrote to `cwd/name`, ignoring the document's own
//     boardPath, so saving a file opened from /lib/util.py created a NEW
//     /util.py and left the edited file untouched — then re-bound the document
//     to the wrong path, making the damage sticky;
//   * a save that FAILED still had to leave the buffer dirty, so the user is
//     never told work was persisted when it was not.
//
// Pins the frozen contract:
//   saveTargetFor(doc) = doc.boardPath ?? '/<doc.name>'
//   saveControllerProvider = Provider<SaveController>
//     save() -> putFile(saveTargetFor(doc), utf8(doc.content))
//            -> markSaved(boardPath: target)   [only on success]
//     a typed PbleException propagates and the buffer stays dirty.

import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:pyble/app/providers.dart';
import 'package:pyble/editor/editor.dart';
import 'package:pyble/pble/pble.dart';

import '../support/recording_connection.dart';

class _HeldSaveConnection extends RecordingConnection {
  _HeldSaveConnection() : super(initial: ConnState.ready);

  final Completer<void> release = Completer<void>();

  @override
  Future<void> putFile(
    String path,
    Uint8List bytes, {
    ProgressCb? onProgress,
  }) async {
    await super.putFile(path, bytes, onProgress: onProgress);
    await release.future;
  }
}

void main() {
  ProviderContainer bind(Connection c) {
    final ProviderContainer container = ProviderContainer(
      overrides: <Override>[connectionProvider.overrideWithValue(c)],
    );
    addTearDown(container.dispose);
    return container;
  }

  group('A-20 saveTargetFor — the document owns its board path', () {
    test(
      'a never-saved buffer lands at the filesystem root under its name',
      () {
        expect(saveTargetFor(const EditorDocument.untitled()), '/untitled.py');
      },
    );

    test(
      'a bound document saves back to its OWN boardPath, not the explorer cwd',
      () {
        const EditorDocument doc = EditorDocument(
          name: 'util.py',
          content: 'x = 1\n',
          dirty: true,
          boardPath: '/lib/util.py',
        );
        expect(
          saveTargetFor(doc),
          '/lib/util.py',
          reason: 'saving an opened file must never fork a new root-level copy',
        );
      },
    );

    test('a bare name is normalised to an absolute board path', () {
      const EditorDocument doc = EditorDocument(
        name: 'main.py',
        content: '',
        dirty: true,
      );
      expect(saveTargetFor(doc), '/main.py');
    });
  });

  group('A-20 SaveController — writes through the Connection seam', () {
    test('save() uploads the current buffer and marks it clean', () async {
      final RecordingConnection rec = RecordingConnection(
        initial: ConnState.ready,
      );
      final ProviderContainer c = bind(rec);

      c.read(editorDocumentProvider.notifier).setContent('print("hi")\n');
      expect(c.read(editorDocumentProvider).dirty, isTrue);

      final String path = await c.read(saveControllerProvider).save();

      expect(path, '/untitled.py');
      expect(rec.putFileCalls.length, 1);
      expect(rec.putFileCalls.single.path, '/untitled.py');
      expect(
        utf8.decode(rec.putFileCalls.single.bytes),
        'print("hi")\n',
        reason: 'the buffer CONTENT must reach the board, not an empty file',
      );

      final EditorDocument saved = c.read(editorDocumentProvider);
      expect(saved.dirty, isFalse);
      expect(
        saved.boardPath,
        '/untitled.py',
        reason: 'the document adopts its target so later saves stay put',
      );
    });

    test(
      'save() writes back to the opened file, not the explorer cwd',
      () async {
        final RecordingConnection rec = RecordingConnection(
          initial: ConnState.ready,
        );
        final ProviderContainer c = bind(rec);

        c
            .read(editorDocumentProvider.notifier)
            .openFromBoard(path: '/lib/util.py', content: 'old\n');
        c.read(editorDocumentProvider.notifier).setContent('new\n');

        await c.read(saveControllerProvider).save();

        expect(rec.putFileCalls.single.path, '/lib/util.py');
        expect(utf8.decode(rec.putFileCalls.single.bytes), 'new\n');
      },
    );

    test('a non-empty buffer is never written as a zero-byte file', () async {
      final RecordingConnection rec = RecordingConnection(
        initial: ConnState.ready,
      );
      final ProviderContainer c = bind(rec);

      const String program = 'for i in range(3):\n    print(i)\n';
      c.read(editorDocumentProvider.notifier).setContent(program);
      await c.read(saveControllerProvider).save();

      expect(rec.putFileCalls.single.bytes.length, utf8.encode(program).length);
      expect(
        rec.putFileCalls.single.bytes,
        isNotEmpty,
        reason: 'the 0-byte test.py on the bench board must not recur',
      );
    });

    test(
      'curly quotes are normalized before the bytes reach the board',
      () async {
        // The iPad case: the editor field's formatter was bypassed (or the
        // platform substituted after it), so the BUFFER still holds U+201C/U+201D.
        // The save seam is the last line of defence — the BOARD must never
        // receive bytes that cannot tokenize.
        final RecordingConnection rec = RecordingConnection(
          initial: ConnState.ready,
        );
        final ProviderContainer c = bind(rec);

        c
            .read(editorDocumentProvider.notifier)
            .setContent('print(“Hello world!!”)\n');
        await c.read(saveControllerProvider).save();

        final String written = utf8.decode(rec.putFileCalls.single.bytes);
        expect(written, 'print("Hello world!!")\n');
        expect(
          rec.putFileCalls.single.bytes.any((int b) => b > 127),
          isFalse,
          reason:
              'the exact bytes that produced SyntaxError on the bench board',
        );
        // Screen and board must agree about what was saved.
        expect(
          c.read(editorDocumentProvider).content,
          'print("Hello world!!")\n',
        );
      },
    );

    test('an invisible non-breaking space is scrubbed before upload', () async {
      final RecordingConnection rec = RecordingConnection(
        initial: ConnState.ready,
      );
      final ProviderContainer c = bind(rec);

      c.read(editorDocumentProvider.notifier).setContent('x = 1\n');
      await c.read(saveControllerProvider).save();

      expect(utf8.decode(rec.putFileCalls.single.bytes), 'x = 1\n');
    });

    test(
      'a FAILED save propagates typed and leaves the buffer dirty',
      () async {
        final RecordingConnection rec = RecordingConnection(
          initial: ConnState.ready,
        );
        final ProviderContainer c = bind(rec);

        c.read(editorDocumentProvider.notifier).setContent('print(1)\n');
        rec.injectError(const ENoSpc('filesystem full'));

        await expectLater(
          c.read(saveControllerProvider).save(),
          throwsA(isA<ENoSpc>()),
        );
        expect(
          c.read(editorDocumentProvider).dirty,
          isTrue,
          reason: 'a failed save must never look like a successful one',
        );
        expect(c.read(editorDocumentProvider).boardPath, isNull);
      },
    );

    test(
      'save completion cannot clear or rebind a document opened mid-upload',
      () async {
        final _HeldSaveConnection rec = _HeldSaveConnection();
        addTearDown(() {
          if (!rec.release.isCompleted) rec.release.complete();
        });
        final ProviderContainer c = bind(rec);
        c
            .read(editorDocumentProvider.notifier)
            .setContent('print("uploaded")\n');

        final Future<String> save = c.read(saveControllerProvider).save();
        while (rec.putFileCalls.isEmpty) {
          await Future<void>.delayed(Duration.zero);
        }
        c
            .read(editorDocumentProvider.notifier)
            .openGenerated(name: 'other.py', content: 'print("keep dirty")\n');
        rec.release.complete();
        expect(await save, '/untitled.py');

        final EditorDocument current = c.read(editorDocumentProvider);
        expect(current.name, 'other.py');
        expect(current.content, 'print("keep dirty")\n');
        expect(current.dirty, isTrue);
        expect(current.boardPath, isNull);
      },
    );
  });
}

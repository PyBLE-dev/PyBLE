// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.
//
// A-30 [red] — the working-loop file-explorer provider (ADR-0010, TDD §11.6d,
// specs.md FR-FILES §4.5). A controller over the Connection file verbs, rooted
// at DeviceInfo.fsRoot, with into/up navigation, open-in-editor, upload-current-
// buffer, newFile, mkdir, delete, rename, continuous transfer progress, and
// typed PbleException -> FileErrorKind mapping (widget maps kind -> ARB). Binds
// through the seam ONLY (CON-8); app-layer cross-imports files -> editor /
// files -> selectedSurface are allowed.
//
// Pins the frozen contract:
//   FileErrorKind { notFound, permission, storageFull, io, crc, busy,
//                   unsupported, range, badRequest, notConnected, generic }
//   FileExplorerState { String cwd; List<RemoteEntry> entries; bool loading;
//                       TransferProgress? progress; FileErrorKind? error;
//                       String? errorPath }
//   fileExplorerProvider = NotifierProvider<FileExplorerController, FileExplorerState>
//     refresh / into / up (bounded at fsRoot) / openInEditor / uploadCurrentBuffer
//     / newFile / mkdir / delete / rename
//   openInEditor -> getFile -> editorDocumentProvider.openFromBoard -> selectedSurface=editor
//   uploadCurrentBuffer -> putFile(cwd/name) -> editorDocumentProvider.markSaved(boardPath)
//
// CURRENTLY RED: lib/files exports no FileErrorKind / FileExplorerState /
// fileExplorerProvider. HAND-OFF: lib/files/file_explorer_controller.dart ->
// app-files-engineer.

import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:pyble/app/providers.dart';
import 'package:pyble/editor/editor.dart';
import 'package:pyble/files/files.dart';
import 'package:pyble/pble/pble.dart';

import '../support/recording_connection.dart';

final class _HeldGetConnection extends RecordingConnection {
  _HeldGetConnection() : super(initial: ConnState.ready);

  final Completer<void> releaseGet = Completer<void>();
  int getStarts = 0;

  @override
  Future<Uint8List> getFile(String path, {ProgressCb? onProgress}) async {
    getStarts += 1;
    await releaseGet.future;
    return super.getFile(path, onProgress: onProgress);
  }
}

void main() {
  Uint8List b(String s) => Uint8List.fromList(utf8.encode(s));

  /// Builds the provider bound to [conn], keeps it alive, and lets its async
  /// root-init (deviceInfo -> fsRoot -> initial listing) settle.
  Future<ProviderContainer> ready(Connection conn) async {
    final ProviderContainer c = ProviderContainer(
      overrides: <Override>[connectionProvider.overrideWithValue(conn)],
    );
    addTearDown(c.dispose);
    c.listen(fileExplorerProvider, (_, _) {});
    await pumpEventQueue();
    await pumpEventQueue();
    return c;
  }

  FileExplorerState state(ProviderContainer c) => c.read(fileExplorerProvider);
  FileExplorerController ctrl(ProviderContainer c) =>
      c.read(fileExplorerProvider.notifier);
  Set<String> names(ProviderContainer c) =>
      state(c).entries.map((RemoteEntry e) => e.name).toSet();

  group('A-30 FileErrorKind — the frozen typed-error taxonomy', () {
    test('exposes exactly the twelve kinds in order', () {
      expect(FileErrorKind.values, <FileErrorKind>[
        FileErrorKind.notFound,
        FileErrorKind.permission,
        FileErrorKind.storageFull,
        FileErrorKind.io,
        FileErrorKind.crc,
        FileErrorKind.busy,
        FileErrorKind.unsupported,
        FileErrorKind.range,
        FileErrorKind.badRequest,
        FileErrorKind.notConnected,
        FileErrorKind.timeout,
        FileErrorKind.generic,
      ]);
    });
  });

  group('A-30 fileExplorerProvider — listing rooted at fsRoot', () {
    test('refresh lists the fsRoot directory (files + dirs)', () async {
      final FakeConnection fake = FakeConnection(initial: ConnState.ready);
      await fake.putFile('/main.py', b('print(1)\n'));
      await fake.mkdir('/lib');
      final ProviderContainer c = await ready(fake);

      expect(
        state(c).cwd,
        '/',
        reason: 'rooted at DeviceInfo.fsRoot (default /)',
      );
      await ctrl(c).refresh();
      await pumpEventQueue();

      expect(names(c), containsAll(<String>['main.py', 'lib']));
      final RemoteEntry file = state(
        c,
      ).entries.firstWhere((RemoteEntry e) => e.name == 'main.py');
      expect(file.isDir, isFalse);
      expect(file.size, b('print(1)\n').length);
    });
  });

  group('A-30 fileExplorerProvider — navigation', () {
    test('into descends and up returns to the parent', () async {
      final FakeConnection fake = FakeConnection(initial: ConnState.ready);
      await fake.mkdir('/lib');
      await fake.putFile('/lib/util.py', b('# util\n'));
      final ProviderContainer c = await ready(fake);

      await ctrl(c).into('lib');
      await pumpEventQueue();
      expect(state(c).cwd, '/lib');
      expect(names(c), contains('util.py'));

      await ctrl(c).up();
      await pumpEventQueue();
      expect(state(c).cwd, '/');
    });

    test('up is bounded at fsRoot (never escapes /flash)', () async {
      const DeviceInfo flash = DeviceInfo(
        chip: 'esp32',
        mpyVersion: '1.28.0',
        freeMem: 48000,
        fsRoot: '/flash',
      );
      final FakeConnection fake = FakeConnection(
        initial: ConnState.ready,
        deviceInfo: flash,
      );
      await fake.mkdir('/flash/sub');
      await fake.putFile('/flash/sub/x.py', b('x\n'));
      final ProviderContainer c = await ready(fake);
      expect(state(c).cwd, '/flash');

      await ctrl(c).into('sub');
      await pumpEventQueue();
      expect(state(c).cwd, '/flash/sub');

      await ctrl(c).up();
      await pumpEventQueue();
      expect(state(c).cwd, '/flash');

      await ctrl(c).up(); // already at root
      await pumpEventQueue();
      expect(
        state(c).cwd,
        '/flash',
        reason: 'navigation is bounded at fsRoot (FR-FILES)',
      );
    });
  });

  group('A-30 fileExplorerProvider — open in editor / upload / newFile', () {
    test('openInEditor downloads into the editor and focuses it', () async {
      final FakeConnection fake = FakeConnection(initial: ConnState.ready);
      await fake.putFile('/blink.py', b('led.on()\n'));
      final ProviderContainer c = await ready(fake);

      await ctrl(c).openInEditor('blink.py');
      await pumpEventQueue();

      final EditorDocument doc = c.read(editorDocumentProvider);
      expect(doc.content, 'led.on()\n');
      expect(doc.name, 'blink.py');
      expect(doc.boardPath, '/blink.py');
      expect(doc.dirty, isFalse);
      expect(
        c.read(selectedSurfaceProvider),
        AppSurface.editor,
        reason: 'files -> editor cross-import: open focuses the editor surface',
      );
    });

    test(
      'downloadForBlocks returns a clean board snapshot without mutating app state',
      () async {
        final RecordingConnection rec = RecordingConnection(
          initial: ConnState.ready,
        );
        await rec.putFile('/blink.py', b('print("blink")\n'));
        final ProviderContainer c = await ready(rec);
        c.read(editorDocumentProvider.notifier).setContent('editor stays\n');
        c.read(selectedSurfaceProvider.notifier).state = AppSurface.files;
        final EditorDocument editorBefore = c.read(editorDocumentProvider);

        final EditorDocument? captured = await ctrl(
          c,
        ).downloadForBlocks('blink.py');

        expect(captured, isNotNull);
        expect(captured!.name, 'blink.py');
        expect(captured.content, 'print("blink")\n');
        expect(captured.boardPath, '/blink.py');
        expect(captured.dirty, isFalse);
        expect(c.read(editorDocumentProvider), editorBefore);
        expect(c.read(selectedSurfaceProvider), AppSurface.files);
        expect(rec.getFileCalls, contains('/blink.py'));
      },
    );

    test('downloadForBlocks ignores a rapid duplicate activation', () async {
      final _HeldGetConnection connection = _HeldGetConnection();
      await connection.putFile('/blink.py', b('print("blink")\n'));
      final ProviderContainer c = await ready(connection);

      final Future<EditorDocument?> first = ctrl(
        c,
      ).downloadForBlocks('blink.py');
      await pumpEventQueue();
      final EditorDocument? duplicate = await ctrl(
        c,
      ).downloadForBlocks('blink.py');

      expect(duplicate, isNull);
      expect(connection.getStarts, 1);
      connection.releaseGet.complete();
      expect((await first)?.content, 'print("blink")\n');
      expect(connection.getFileCalls, <String>['/blink.py']);
    });

    test(
      'uploadCurrentBuffer writes to cwd/name and marks the buffer saved',
      () async {
        final FakeConnection fake = FakeConnection(initial: ConnState.ready);
        final ProviderContainer c = await ready(fake);
        c
            .read(editorDocumentProvider.notifier)
            .newDocument(); // name untitled.py
        c.read(editorDocumentProvider.notifier).setContent('x = 1\n');

        await ctrl(c).uploadCurrentBuffer();
        await pumpEventQueue();

        expect(utf8.decode(await fake.getFile('/untitled.py')), 'x = 1\n');
        final EditorDocument doc = c.read(editorDocumentProvider);
        expect(doc.dirty, isFalse, reason: 'upload marks the buffer saved');
        expect(doc.boardPath, '/untitled.py');
      },
    );

    test('newFile creates an empty board file and opens it', () async {
      final FakeConnection fake = FakeConnection(initial: ConnState.ready);
      final ProviderContainer c = await ready(fake);

      await ctrl(c).newFile('main.py');
      await pumpEventQueue();

      expect(await fake.getFile('/main.py'), isEmpty);
      final EditorDocument doc = c.read(editorDocumentProvider);
      expect(doc.name, 'main.py');
      expect(doc.boardPath, '/main.py');
      expect(c.read(selectedSurfaceProvider), AppSurface.editor);
    });

    test('a transfer reports continuous progress (FR-FILES-4)', () async {
      final RecordingConnection rec = RecordingConnection(
        initial: ConnState.ready,
        steppedProgress: true,
      );
      final ProviderContainer c = await ready(rec);
      c.read(editorDocumentProvider.notifier).newDocument();
      c
          .read(editorDocumentProvider.notifier)
          .setContent(List<String>.filled(64, 'x').join());

      bool sawProgress = false;
      c.listen<FileExplorerState>(fileExplorerProvider, (
        _,
        FileExplorerState s,
      ) {
        if (s.progress != null) sawProgress = true;
      });

      await ctrl(c).uploadCurrentBuffer();
      await pumpEventQueue();

      expect(
        sawProgress,
        isTrue,
        reason: 'FileExplorerState.progress is populated during a transfer',
      );
      expect(
        c.read(fileExplorerProvider).progress,
        isNull,
        reason: 'progress clears when the transfer completes',
      );
    });
  });

  group('A-30 fileExplorerProvider — mkdir / delete / rename', () {
    test('mkdir then delete round-trips through the listing', () async {
      final FakeConnection fake = FakeConnection(initial: ConnState.ready);
      final ProviderContainer c = await ready(fake);

      await ctrl(c).mkdir('data');
      await pumpEventQueue();
      expect(names(c), contains('data'));

      await ctrl(c).delete('data');
      await pumpEventQueue();
      expect(names(c), isNot(contains('data')));
    });

    test('rename replaces the old name with the new', () async {
      final FakeConnection fake = FakeConnection(initial: ConnState.ready);
      await fake.putFile('/old.py', b('a\n'));
      final ProviderContainer c = await ready(fake);

      await ctrl(c).rename('old.py', 'new.py');
      await pumpEventQueue();

      expect(names(c), contains('new.py'));
      expect(names(c), isNot(contains('old.py')));
    });
  });

  group('A-30 fileExplorerProvider — typed error -> FileErrorKind', () {
    Future<void> expectKind(PbleException injected, FileErrorKind kind) async {
      final FakeConnection fake = FakeConnection(initial: ConnState.ready);
      final ProviderContainer c = await ready(fake);
      fake.injectError(injected);

      await ctrl(c).refresh();
      await pumpEventQueue();

      expect(state(c).error, kind, reason: '${injected.runtimeType} -> $kind');
      expect(
        state(c).errorPath,
        isNotNull,
        reason: 'the failing path is surfaced for the message',
      );
    }

    test('maps every §8 status + not-connected to its kind', () async {
      await expectKind(const ENoEnt('x'), FileErrorKind.notFound);
      await expectKind(const EAcces('x'), FileErrorKind.permission);
      await expectKind(const ENoSpc('x'), FileErrorKind.storageFull);
      await expectKind(const EIo('x'), FileErrorKind.io);
      await expectKind(const ECrc('x'), FileErrorKind.crc);
      await expectKind(const EBusy('x'), FileErrorKind.busy);
      await expectKind(const EUnsupported('x'), FileErrorKind.unsupported);
      await expectKind(const ERange('x'), FileErrorKind.range);
      await expectKind(const EBadReq('x'), FileErrorKind.badRequest);
      await expectKind(
        const NotConnectedException('x'),
        FileErrorKind.notConnected,
      );
      await expectKind(const PbleTimeoutException('x'), FileErrorKind.timeout);
      await expectKind(const EInternal('x'), FileErrorKind.generic);
    });
  });

  group(
    'FR-FILES-1 auto-load on connection (the facade never re-fires build)',
    () {
      test(
        'listing auto-loads when a connection becomes ready AFTER first build',
        () async {
          final FakeConnection fake = FakeConnection(
            initial: ConnState.disconnected,
          );
          addTearDown(fake.dispose);
          await fake.putFile('/main.py', b('print(1)\n'));

          final ProviderContainer c = await ready(fake);
          expect(
            state(c).entries,
            isEmpty,
            reason: 'nothing to list while disconnected',
          );
          expect(
            state(c).loading,
            isFalse,
            reason: 'no listing is in flight while disconnected',
          );

          // The board connects: the explorer must re-root + list by ITSELF —
          // no manual refresh (the stable facade never re-fires build; the
          // controller listens to ConnState instead).
          fake.emit(ConnState.ready);
          await pumpEventQueue();
          await pumpEventQueue();

          expect(
            names(c),
            contains('main.py'),
            reason: 'the listing auto-loads on the new connection',
          );
        },
      );

      test(
        'running -> ready (a program finishing) keeps the user\'s cwd',
        () async {
          final FakeConnection fake = FakeConnection(initial: ConnState.ready);
          addTearDown(fake.dispose);
          await fake.mkdir('/lib');
          await fake.putFile('/lib/util.py', b('# util\n'));

          final ProviderContainer c = await ready(fake);
          await ctrl(c).into('lib');
          expect(state(c).cwd, '/lib');

          // A program runs and finishes: ready -> running -> ready must NOT
          // re-root the explorer out of the directory being browsed.
          fake.emit(ConnState.running);
          await pumpEventQueue();
          fake.emit(ConnState.ready);
          await pumpEventQueue();
          await pumpEventQueue();

          expect(
            state(c).cwd,
            '/lib',
            reason: 'a run finishing must not yank the user back to fsRoot',
          );
        },
      );

      test(
        'disconnect clears the stale listing; the next connection re-lists',
        () async {
          final FakeConnection fake = FakeConnection(initial: ConnState.ready);
          addTearDown(fake.dispose);
          await fake.putFile('/main.py', b('print(1)\n'));

          final ProviderContainer c = await ready(fake);
          expect(names(c), contains('main.py'));

          fake.emit(ConnState.disconnected);
          await pumpEventQueue();
          expect(
            state(c).entries,
            isEmpty,
            reason: 'a stale listing from the old board is dropped',
          );

          await fake.putFile('/new.py', b('print(2)\n'));
          fake.emit(ConnState.ready);
          await pumpEventQueue();
          await pumpEventQueue();
          expect(
            names(c),
            contains('new.py'),
            reason: 'the new session auto-lists',
          );
        },
      );
    },
  );
}

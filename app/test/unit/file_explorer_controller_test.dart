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

/// Session-aware, observable file seam for ADR-0043's multi-verb contract.
///
/// This stays local to the controller suite: production [FakeConnection] and
/// shared test support deliberately need no bulk-delete-specific hooks.
final class _BatchDeleteConnection extends RecordingConnection
    implements ConnectionSessionStampSource {
  _BatchDeleteConnection({super.deviceInfo}) : super(initial: ConnState.ready);

  Object _sessionStamp = Object();
  int _deleteOrdinal = 0;
  int _activeDeletes = 0;

  int? failDeleteAt;
  PbleException deleteFailure = const EIo('scripted delete failure');
  PbleException? nextListFailure;
  int? holdDeleteAt;

  final Completer<void> deleteHeld = Completer<void>();
  final Completer<void> releaseDelete = Completer<void>();
  final List<String> attemptedDeletePaths = <String>[];
  final List<String> listedPaths = <String>[];
  final List<String> batchLog = <String>[];
  int maxActiveDeletes = 0;

  @override
  Object get connectionSessionStamp => _sessionStamp;

  void advanceSession() => _sessionStamp = Object();

  void resetBatchTrace() {
    _deleteOrdinal = 0;
    _activeDeletes = 0;
    maxActiveDeletes = 0;
    attemptedDeletePaths.clear();
    listedPaths.clear();
    batchLog.clear();
    deleteCalls.clear();
    operationLog.clear();
  }

  @override
  Future<List<RemoteEntry>> listDir(String path) async {
    listedPaths.add(path);
    batchLog.add('list:$path');
    final PbleException? failure = nextListFailure;
    if (failure != null) {
      nextListFailure = null;
      throw failure;
    }
    return super.listDir(path);
  }

  @override
  Future<void> delete(String path) async {
    _deleteOrdinal += 1;
    final int ordinal = _deleteOrdinal;
    attemptedDeletePaths.add(path);
    batchLog.add('delete:$path');
    _activeDeletes += 1;
    if (_activeDeletes > maxActiveDeletes) {
      maxActiveDeletes = _activeDeletes;
    }
    try {
      if (ordinal == holdDeleteAt) {
        if (!deleteHeld.isCompleted) deleteHeld.complete();
        await releaseDelete.future;
      }
      if (ordinal == failDeleteAt) throw deleteFailure;
      await super.delete(path);
    } finally {
      _activeDeletes -= 1;
    }
  }
}

/// Holds each DEVICE_INFO response so reconnect ordering can be exercised.
final class _HeldDeviceInfoConnection extends RecordingConnection
    implements ConnectionSessionStampSource {
  _HeldDeviceInfoConnection() : super(initial: ConnState.ready);

  Object _sessionStamp = Object();
  final List<Completer<DeviceInfo>> deviceInfoRequests =
      <Completer<DeviceInfo>>[];

  @override
  Object get connectionSessionStamp => _sessionStamp;

  @override
  Future<DeviceInfo> deviceInfo() {
    final Completer<DeviceInfo> request = Completer<DeviceInfo>();
    deviceInfoRequests.add(request);
    return request.future;
  }

  void detachSession() {
    _sessionStamp = Object();
    emit(ConnState.disconnected);
  }

  void attachSession() {
    _sessionStamp = Object();
    emit(ConnState.ready);
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

  Future<({_BatchDeleteConnection connection, ProviderContainer container})>
  batchReady({
    String fsRoot = '/',
    List<String> files = const <String>[],
    List<String> directories = const <String>[],
  }) async {
    final _BatchDeleteConnection connection = _BatchDeleteConnection(
      deviceInfo: DeviceInfo(
        chip: 'esp32-s3',
        mpyVersion: '1.28.0',
        freeMem: 48000,
        fsRoot: fsRoot,
      ),
    );
    addTearDown(() async {
      if (!connection.releaseDelete.isCompleted) {
        connection.releaseDelete.complete();
      }
      await connection.dispose();
    });
    String pathOf(String name) => fsRoot == '/' ? '/$name' : '$fsRoot/$name';
    for (final String directory in directories) {
      await connection.mkdir(pathOf(directory));
    }
    for (final String file in files) {
      await connection.putFile(pathOf(file), b(file));
    }
    final ProviderContainer container = await ready(connection);
    connection.resetBatchTrace();
    return (connection: connection, container: container);
  }

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
      expect(
        state(c).fsRoot,
        '/',
        reason: 'the reported root is public state for Files selection safety',
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

  group('ADR-0043 editable board-entry predicate', () {
    test('matches the case-sensitive firmware jail at the reported root', () {
      bool editable(String cwd, String name) =>
          isEditableBoardEntry(fsRoot: '/flash', cwd: cwd, name: name);

      expect(editable('/flash', 'main.py'), isTrue);
      expect(editable('/flash', 'PyBLE_demo.py'), isTrue);
      expect(editable('/flash', 'PBLE_demo.py'), isTrue);
      expect(editable('/flash', 'pyble_demo.py'), isFalse);
      expect(editable('/flash', 'pyblex.py'), isFalse);
      expect(editable('/flash', 'pble_demo.py'), isFalse);
      expect(editable('/flash', 'boot.py'), isFalse);
      expect(editable('/flash', '_boot.py'), isFalse);
      expect(
        editable('/flash/examples', 'pyble_demo.py'),
        isTrue,
        reason: 'protected prefixes apply only to the top level at fsRoot',
      );
    });

    test('rejects scratch, escaping, malformed, and overlength targets', () {
      bool editable(String cwd, String name) =>
          isEditableBoardEntry(fsRoot: '/flash', cwd: cwd, name: name);

      expect(editable('/flash', 'upload.pbltmp'), isFalse);
      expect(editable('/flash/cache.pbltmp', 'main.py'), isFalse);
      expect(editable('/outside', 'main.py'), isFalse);
      expect(editable('/flash', ''), isFalse);
      expect(editable('/flash', '.'), isFalse);
      expect(editable('/flash', '..'), isFalse);
      expect(editable('/flash', '../escape.py'), isFalse);
      expect(editable('/flash', 'nested/escape.py'), isFalse);
      expect(editable('/flash', r'nested\escape.py'), isFalse);
      expect(editable('/flash', 'bad\u0000.py'), isFalse);

      final String overlength = '${List<String>.filled(119, 'a').join()}.py';
      expect(utf8.encode('/flash/$overlength').length, greaterThan(128));
      expect(editable('/flash', overlength), isFalse);
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
      expect(state(c).fsRoot, '/flash');

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

  group('ADR-0043 FileExplorerController.deleteMany', () {
    test(
      'deletes in display order, reports item progress, and reconciles once',
      () async {
        final h = await batchReady(
          files: <String>['z.py', 'Alpha.py', 'middle.txt'],
        );
        final List<FileDeleteBatchProgress> progress =
            <FileDeleteBatchProgress>[];

        final FileDeleteBatchResult result = await ctrl(h.container).deleteMany(
          <String>['z.py', 'middle.txt', 'Alpha.py'],
          expectedCwd: '/',
          expectedSessionStamp: h.connection.connectionSessionStamp,
          onProgress: progress.add,
        );

        expect(FileDeleteBatchOutcome.values, <FileDeleteBatchOutcome>[
          FileDeleteBatchOutcome.complete,
          FileDeleteBatchOutcome.failed,
          FileDeleteBatchOutcome.partial,
        ]);
        expect(result.outcome, FileDeleteBatchOutcome.complete);
        expect(result.succeededPaths, <String>[
          '/Alpha.py',
          '/middle.txt',
          '/z.py',
        ]);
        expect(result.failedPath, isNull);
        expect(result.unattemptedPaths, isEmpty);
        expect(result.failure, isNull);
        expect(
          progress.map((FileDeleteBatchProgress value) => value.completed),
          <int>[0, 1, 2],
        );
        expect(
          progress.map((FileDeleteBatchProgress value) => value.total),
          everyElement(3),
        );
        expect(
          progress.map((FileDeleteBatchProgress value) => value.currentPath),
          <String>['/Alpha.py', '/middle.txt', '/z.py'],
        );
        expect(h.connection.attemptedDeletePaths, <String>[
          '/Alpha.py',
          '/middle.txt',
          '/z.py',
        ]);
        expect(h.connection.batchLog, <String>[
          'delete:/Alpha.py',
          'delete:/middle.txt',
          'delete:/z.py',
          'list:/',
        ]);
        expect(h.connection.listedPaths, <String>['/']);
        expect(h.connection.maxActiveDeletes, 1);
        expect(state(h.container).entries, isEmpty);
      },
    );

    test('rejects a duplicate selection before board I/O', () async {
      final h = await batchReady(files: <String>['alpha.py', 'beta.py']);

      final FileDeleteBatchResult result = await ctrl(
        h.container,
      ).deleteMany(<String>['beta.py', 'alpha.py', 'beta.py']);

      expect(result.outcome, FileDeleteBatchOutcome.failed);
      expect(result.failure, FileErrorKind.badRequest);
      expect(result.succeededPaths, isEmpty);
      expect(result.failedPath, isNull);
      expect(result.unattemptedPaths, isEmpty);
      expect(h.connection.attemptedDeletePaths, isEmpty);
      expect(h.connection.listedPaths, isEmpty);
    });

    test('awaits each delete before starting the next', () async {
      final h = await batchReady(files: <String>['alpha.py', 'beta.py']);
      h.connection.holdDeleteAt = 1;

      final Future<FileDeleteBatchResult> pending = ctrl(
        h.container,
      ).deleteMany(<String>['beta.py', 'alpha.py']);
      await h.connection.deleteHeld.future;
      await pumpEventQueue();

      expect(h.connection.attemptedDeletePaths, <String>['/alpha.py']);
      expect(h.connection.maxActiveDeletes, 1);
      expect(h.connection.listedPaths, isEmpty);

      h.connection.releaseDelete.complete();
      final FileDeleteBatchResult result = await pending;
      expect(result.outcome, FileDeleteBatchOutcome.complete);
      expect(h.connection.attemptedDeletePaths, <String>[
        '/alpha.py',
        '/beta.py',
      ]);
      expect(h.connection.maxActiveDeletes, 1);
      expect(h.connection.listedPaths, <String>['/']);
    });

    test(
      'stops at the first failure with exact partial accounting and no rollback',
      () async {
        final h = await batchReady(
          files: <String>['alpha.py', 'beta.py', 'gamma.py'],
        );
        h.connection.failDeleteAt = 2;

        final FileDeleteBatchResult result = await ctrl(
          h.container,
        ).deleteMany(<String>['gamma.py', 'alpha.py', 'beta.py']);

        expect(result.outcome, FileDeleteBatchOutcome.partial);
        expect(result.succeededPaths, <String>['/alpha.py']);
        expect(result.failedPath, '/beta.py');
        expect(result.unattemptedPaths, <String>['/gamma.py']);
        expect(result.failure, FileErrorKind.io);
        expect(h.connection.attemptedDeletePaths, <String>[
          '/alpha.py',
          '/beta.py',
        ]);
        expect(h.connection.listedPaths, <String>['/']);
        await expectLater(
          h.connection.getFile('/alpha.py'),
          throwsA(isA<ENoEnt>()),
          reason: 'an acknowledged earlier delete is never rolled back',
        );
        expect(await h.connection.getFile('/beta.py'), isNotEmpty);
        expect(await h.connection.getFile('/gamma.py'), isNotEmpty);
        expect(names(h.container), <String>{'beta.py', 'gamma.py'});
        expect(state(h.container).error, FileErrorKind.io);
        expect(state(h.container).errorPath, '/beta.py');
      },
    );

    test(
      'reconciles once after the first attempted delete and keeps its error primary',
      () async {
        final h = await batchReady(files: <String>['alpha.py', 'beta.py']);
        h.connection.failDeleteAt = 1;
        h.connection.deleteFailure = const PbleTimeoutException(
          'scripted uncertain delete',
        );
        h.connection.nextListFailure = const ENoEnt(
          'scripted reconciliation failure',
        );

        final FileDeleteBatchResult result = await ctrl(
          h.container,
        ).deleteMany(<String>['alpha.py', 'beta.py']);

        expect(result.outcome, FileDeleteBatchOutcome.failed);
        expect(result.succeededPaths, isEmpty);
        expect(result.failedPath, '/alpha.py');
        expect(result.unattemptedPaths, <String>['/beta.py']);
        expect(result.failure, FileErrorKind.timeout);
        expect(h.connection.batchLog, <String>['delete:/alpha.py', 'list:/']);
        expect(h.connection.listedPaths, <String>['/']);
        expect(state(h.container).error, FileErrorKind.timeout);
        expect(state(h.container).errorPath, '/alpha.py');
      },
    );

    test(
      'surfaces reconciliation failure separately after every delete succeeds',
      () async {
        final h = await batchReady(files: <String>['alpha.py', 'beta.py']);
        h.connection.nextListFailure = const EIo(
          'scripted post-success reconciliation failure',
        );

        final FileDeleteBatchResult result = await ctrl(
          h.container,
        ).deleteMany(<String>['beta.py', 'alpha.py']);

        expect(result.outcome, FileDeleteBatchOutcome.complete);
        expect(result.succeededPaths, <String>['/alpha.py', '/beta.py']);
        expect(result.failedPath, isNull);
        expect(result.unattemptedPaths, isEmpty);
        expect(result.failure, isNull);
        expect(h.connection.batchLog, <String>[
          'delete:/alpha.py',
          'delete:/beta.py',
          'list:/',
        ]);
        expect(h.connection.listedPaths, <String>['/']);
        expect(state(h.container).error, FileErrorKind.io);
        expect(state(h.container).errorPath, '/');
      },
    );

    test(
      'session replacement starts no later delete and never lists the successor',
      () async {
        final h = await batchReady(
          files: <String>['alpha.py', 'beta.py', 'gamma.py'],
        );
        h.connection.holdDeleteAt = 1;
        final Object capturedStamp = h.connection.connectionSessionStamp;

        final Future<FileDeleteBatchResult> pending = ctrl(h.container)
            .deleteMany(
              <String>['alpha.py', 'beta.py', 'gamma.py'],
              expectedCwd: '/',
              expectedSessionStamp: capturedStamp,
            );
        await h.connection.deleteHeld.future;
        h.connection.advanceSession();
        h.connection.releaseDelete.complete();

        final FileDeleteBatchResult result = await pending;
        expect(result.outcome, FileDeleteBatchOutcome.partial);
        expect(result.succeededPaths, <String>['/alpha.py']);
        expect(result.failedPath, '/beta.py');
        expect(result.unattemptedPaths, <String>['/gamma.py']);
        expect(result.failure, FileErrorKind.notConnected);
        expect(h.connection.attemptedDeletePaths, <String>['/alpha.py']);
        expect(
          h.connection.listedPaths,
          isEmpty,
          reason: 'the captured folder must not be listed on a successor board',
        );
      },
    );

    test('mismatched expected cwd or session fails before board I/O', () async {
      final h = await batchReady(files: <String>['alpha.py', 'beta.py']);

      final FileDeleteBatchResult wrongCwd = await ctrl(h.container).deleteMany(
        <String>['alpha.py', 'beta.py'],
        expectedCwd: '/other',
        expectedSessionStamp: h.connection.connectionSessionStamp,
      );
      expect(wrongCwd.outcome, FileDeleteBatchOutcome.failed);
      expect(wrongCwd.failure, FileErrorKind.badRequest);
      expect(wrongCwd.succeededPaths, isEmpty);
      expect(h.connection.attemptedDeletePaths, isEmpty);
      expect(h.connection.listedPaths, isEmpty);

      final FileDeleteBatchResult wrongSession = await ctrl(h.container)
          .deleteMany(
            <String>['alpha.py', 'beta.py'],
            expectedCwd: '/',
            expectedSessionStamp: Object(),
          );
      expect(wrongSession.outcome, FileDeleteBatchOutcome.failed);
      expect(wrongSession.failure, FileErrorKind.notConnected);
      expect(wrongSession.succeededPaths, isEmpty);
      expect(h.connection.attemptedDeletePaths, isEmpty);
      expect(h.connection.listedPaths, isEmpty);
    });

    test(
      'empty, unknown, directory, unsafe, locked, and overlength batches do no I/O',
      () async {
        final String overlength = '${List<String>.filled(126, 'x').join()}.py';
        final h = await batchReady(
          files: <String>[
            'main.py',
            'pyble_agent.py',
            'scratch.pbltmp',
            overlength,
          ],
          directories: <String>['folder'],
        );
        final List<({List<String> selected, FileErrorKind failure})> cases =
            <({List<String> selected, FileErrorKind failure})>[
              (selected: <String>[], failure: FileErrorKind.badRequest),
              (
                selected: <String>['missing.py'],
                failure: FileErrorKind.badRequest,
              ),
              (selected: <String>['folder'], failure: FileErrorKind.badRequest),
              (
                selected: <String>['../escape.py'],
                failure: FileErrorKind.badRequest,
              ),
              (
                selected: <String>['main.py', 'pyble_agent.py'],
                failure: FileErrorKind.permission,
              ),
              (
                selected: <String>['scratch.pbltmp'],
                failure: FileErrorKind.permission,
              ),
              (selected: <String>[overlength], failure: FileErrorKind.range),
            ];

        for (final variant in cases) {
          h.connection.resetBatchTrace();
          final FileDeleteBatchResult result = await ctrl(
            h.container,
          ).deleteMany(variant.selected);
          expect(
            result.outcome,
            FileDeleteBatchOutcome.failed,
            reason: 'selection ${variant.selected}',
          );
          expect(
            result.failure,
            variant.failure,
            reason: 'selection ${variant.selected}',
          );
          expect(result.succeededPaths, isEmpty);
          expect(h.connection.attemptedDeletePaths, isEmpty);
          expect(h.connection.listedPaths, isEmpty);
        }
      },
    );

    test('a concurrent batch receives busy and sends no second verb', () async {
      final h = await batchReady(files: <String>['alpha.py', 'beta.py']);
      h.connection.holdDeleteAt = 1;

      final Future<FileDeleteBatchResult> first = ctrl(
        h.container,
      ).deleteMany(<String>['alpha.py']);
      await h.connection.deleteHeld.future;

      final FileDeleteBatchResult concurrent = await ctrl(
        h.container,
      ).deleteMany(<String>['beta.py']);
      final List<String> listedBeforeRelease = List<String>.of(
        h.connection.listedPaths,
      );
      h.connection.releaseDelete.complete();
      final FileDeleteBatchResult firstResult = await first;

      expect(concurrent.outcome, FileDeleteBatchOutcome.failed);
      expect(concurrent.failure, FileErrorKind.busy);
      expect(concurrent.succeededPaths, isEmpty);
      expect(concurrent.failedPath, isNull);
      expect(concurrent.unattemptedPaths, <String>['/beta.py']);
      expect(listedBeforeRelease, isEmpty);
      expect(firstResult.outcome, FileDeleteBatchOutcome.complete);
      expect(h.connection.attemptedDeletePaths, <String>['/alpha.py']);
      expect(h.connection.listedPaths, <String>['/']);
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

  group('FR-FILES-1 auto-load on connection (the facade never re-fires build)', () {
    const DeviceInfo oldInfo = DeviceInfo(
      chip: 'esp32',
      mpyVersion: '1.28.0',
      freeMem: 32000,
      fsRoot: '/old',
    );
    const DeviceInfo currentInfo = DeviceInfo(
      chip: 'esp32-s3',
      mpyVersion: '1.28.0',
      freeMem: 48000,
      fsRoot: '/flash',
    );

    Future<({_HeldDeviceInfoConnection connection, ProviderContainer c})>
    reconnectWithHeldOldInfo() async {
      final _HeldDeviceInfoConnection connection = _HeldDeviceInfoConnection();
      addTearDown(connection.dispose);
      await connection.mkdir('/old');
      await connection.mkdir('/flash');
      await connection.putFile('/flash/current.py', b('# current\n'));

      final ProviderContainer c = await ready(connection);
      expect(connection.deviceInfoRequests, hasLength(1));

      connection.detachSession();
      await pumpEventQueue();
      connection.attachSession();
      await pumpEventQueue();
      expect(connection.deviceInfoRequests, hasLength(2));

      connection.deviceInfoRequests[1].complete(currentInfo);
      await pumpEventQueue();
      await pumpEventQueue();
      expect(state(c).fsRoot, '/flash');
      expect(state(c).cwd, '/flash');
      expect(state(c).hasReportedFsRoot, isTrue);
      expect(names(c), contains('current.py'));
      expect(state(c).error, isNull);
      return (connection: connection, c: c);
    }

    test(
      'a late prior-session DEVICE_INFO success cannot replace the current root',
      () async {
        final h = await reconnectWithHeldOldInfo();

        h.connection.deviceInfoRequests.first.complete(oldInfo);
        await pumpEventQueue();
        await pumpEventQueue();

        expect(state(h.c).fsRoot, '/flash');
        expect(state(h.c).cwd, '/flash');
        expect(state(h.c).hasReportedFsRoot, isTrue);
        expect(names(h.c), contains('current.py'));
        expect(state(h.c).error, isNull);
      },
    );

    test(
      'a late prior-session DEVICE_INFO failure cannot overwrite current state',
      () async {
        final h = await reconnectWithHeldOldInfo();

        h.connection.deviceInfoRequests.first.completeError(
          const EIo('old session failed late'),
        );
        await pumpEventQueue();
        await pumpEventQueue();

        expect(state(h.c).fsRoot, '/flash');
        expect(state(h.c).cwd, '/flash');
        expect(state(h.c).hasReportedFsRoot, isTrue);
        expect(names(h.c), contains('current.py'));
        expect(state(h.c).error, isNull);
      },
    );

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
  });
}

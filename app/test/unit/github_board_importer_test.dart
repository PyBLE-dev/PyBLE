// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.
//
// A-33 connected GitHub-import subset [red] — ADR-0040, App specs §4.9,
// App TDD §10. These tests freeze the board-mutation boundary independently
// of the adaptive view and the GitHub REST adapter: exact safe targets,
// fetch-all validation before mutation, session-bound sequential PUTs, honest
// partial/cancelled results, and Files refresh after a possible write.

import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';

import 'package:pyble/github_import/github_import.dart';
import 'package:pyble/pble/pble.dart';

import '../support/recording_connection.dart';

const int _maxFileBytes = 256 * 1024;
const int _maxBatchBytes = 1024 * 1024;

final class _FakeGithubApi extends Fake implements GithubApi {
  _FakeGithubApi(this.operationLog);

  final List<String> operationLog;
  final Map<String, Uint8List> bytesByObjectSha = <String, Uint8List>{};
  final Map<String, Object> errorsByObjectSha = <String, Object>{};
  final List<String> fetchedRemotePaths = <String>[];

  String? heldObjectSha;
  final Completer<void> fetchHeld = Completer<void>();
  final Completer<void> releaseFetch = Completer<void>();

  @override
  Future<Uint8List> fetchFile(
    PinnedRepository repository,
    GithubEntry entry, {
    GithubCancellation? cancellation,
  }) async {
    operationLog.add('fetch:${entry.remotePath}');
    fetchedRemotePaths.add(entry.remotePath);
    if (entry.objectSha == heldObjectSha) {
      if (!fetchHeld.isCompleted) fetchHeld.complete();
      await releaseFetch.future;
    }
    final Object? error = errorsByObjectSha[entry.objectSha];
    if (error != null) throw error;
    final Uint8List? bytes = bytesByObjectSha[entry.objectSha];
    if (bytes == null) {
      throw StateError('No scripted Git blob for ${entry.objectSha}');
    }
    return Uint8List.fromList(bytes);
  }
}

final class _SessionRecordingConnection extends RecordingConnection
    implements ConnectionSessionStampSource, ConnectionDirectoryListingSource {
  _SessionRecordingConnection({
    List<List<RemoteEntry>>? directoryListings,
    List<bool>? listingTruncation,
    this.failPutAt,
    this.holdPutAt,
  }) : directoryListings =
           directoryListings ?? <List<RemoteEntry>>[<RemoteEntry>[]],
       listingTruncation = listingTruncation ?? <bool>[false],
       _sessionStamp = Object(),
       super(initial: ConnState.ready);

  final List<List<RemoteEntry>> directoryListings;
  final List<bool> listingTruncation;
  final int? failPutAt;
  final int? holdPutAt;

  final Completer<void> putHeld = Completer<void>();
  final Completer<void> releasePut = Completer<void>();

  Object _sessionStamp;
  int _listIndex = 0;
  int _putAttempt = 0;

  @override
  Object get connectionSessionStamp => _sessionStamp;

  void advanceSession() => _sessionStamp = Object();

  @override
  Future<DirectoryListing> listDirWithMetadata(String path) async {
    operationLog.add('list:$path');
    if (directoryListings.isEmpty) {
      return const DirectoryListing(entries: <RemoteEntry>[], truncated: false);
    }
    final int index = _listIndex < directoryListings.length
        ? _listIndex
        : directoryListings.length - 1;
    _listIndex += 1;
    final int truncationIndex = index < listingTruncation.length
        ? index
        : listingTruncation.length - 1;
    return DirectoryListing(
      entries: directoryListings[index],
      truncated: listingTruncation[truncationIndex],
    );
  }

  @override
  Future<List<RemoteEntry>> listDir(String path) async {
    final DirectoryListing listing = await listDirWithMetadata(path);
    return listing.entries;
  }

  @override
  Future<void> putFile(
    String path,
    Uint8List bytes, {
    ProgressCb? onProgress,
  }) async {
    _putAttempt += 1;
    operationLog.add('put:$path');
    if (_putAttempt == failPutAt) {
      injectError(const EIo('scripted board upload failure'));
    }
    await super.putFile(path, bytes, onProgress: onProgress);
    if (_putAttempt == holdPutAt) {
      if (!putHeld.isCompleted) putHeld.complete();
      await releasePut.future;
    }
  }
}

final class _Harness {
  _Harness._({
    required this.operationLog,
    required this.connection,
    required this.api,
    required String cwd,
  }) {
    importer = GithubBoardImporter(
      api: api,
      connection: connection,
      capturedSessionStamp: connection.connectionSessionStamp,
      cwd: cwd,
      refreshFiles: () async {
        operationLog.add('refresh');
        refreshCount += 1;
      },
    );
  }

  factory _Harness({
    String cwd = '/flash',
    List<List<RemoteEntry>>? directoryListings,
    List<bool>? listingTruncation,
    int? failPutAt,
    int? holdPutAt,
  }) {
    // Share one chronological log so tests can prove that no PUT races ahead
    // of a pending or unvalidated Git blob.
    final _SessionRecordingConnection connection = _SessionRecordingConnection(
      directoryListings: directoryListings,
      listingTruncation: listingTruncation,
      failPutAt: failPutAt,
      holdPutAt: holdPutAt,
    );
    final List<String> operationLog = connection.operationLog;
    return _Harness._(
      operationLog: operationLog,
      connection: connection,
      api: _FakeGithubApi(operationLog),
      cwd: cwd,
    );
  }

  final List<String> operationLog;
  final _SessionRecordingConnection connection;
  final _FakeGithubApi api;
  late final GithubBoardImporter importer;
  int refreshCount = 0;
}

String _sha(int value) => value.toRadixString(16).padLeft(40, '0');

final RepositoryLocator _locator = RepositoryLocator.parse(
  'https://github.com/PyBLE-dev/PyBLE',
);

final PinnedRepository _repository = PinnedRepository(
  locator: _locator,
  requestedRef: 'main',
  resolvedRef: 'main',
  commitSha: _sha(1000),
  rootTreeSha: _sha(1001),
);

GithubEntry _file(
  String name, {
  String? remotePath,
  int object = 1,
  int declaredSize = 0,
}) => GithubEntry(
  name: name,
  remotePath: remotePath ?? 'examples/$name',
  kind: GithubEntryKind.regularFile,
  objectSha: _sha(object),
  declaredSize: declaredSize,
);

RemoteEntry _remoteFile(String name) =>
    RemoteEntry(name: name, isDir: false, size: 12);

RemoteEntry _remoteDirectory(String name) =>
    RemoteEntry(name: name, isDir: true, size: 0);

Matcher _failure(GithubFailureKind kind) => isA<GithubFailure>().having(
  (GithubFailure error) => error.kind,
  'kind',
  kind,
);

void _expectFailedResult(GithubImportResult result, GithubFailureKind kind) {
  expect(result.outcome, GithubImportOutcome.failed);
  expect(result.failure, _failure(kind));
  expect(result.succeeded, isEmpty);
}

void main() {
  late List<_SessionRecordingConnection> connections;

  setUp(() => connections = <_SessionRecordingConnection>[]);
  tearDown(() async {
    for (final _SessionRecordingConnection connection in connections) {
      await connection.dispose();
    }
  });

  _Harness harness({
    String cwd = '/flash',
    List<List<RemoteEntry>>? directoryListings,
    List<bool>? listingTruncation,
    int? failPutAt,
    int? holdPutAt,
  }) {
    final _Harness value = _Harness(
      cwd: cwd,
      directoryListings: directoryListings,
      listingTruncation: listingTruncation,
      failPutAt: failPutAt,
      holdPutAt: holdPutAt,
    );
    connections.add(value.connection);
    return value;
  }

  group('A33-SUB-AC-4 review target and conflict safety', () {
    test(
      'maps basenames in stable remote-path order and discovers files',
      () async {
        final _Harness h = harness(
          directoryListings: <List<RemoteEntry>>[
            <RemoteEntry>[_remoteFile('z.py')],
          ],
        );
        final GithubEntry zed = _file(
          'z.py',
          remotePath: 'examples/z.py',
          object: 2,
        );
        final GithubEntry alpha = _file(
          'a.py',
          remotePath: 'examples/a.py',
          object: 1,
        );

        final GithubImportReview review = await h.importer.review(
          _repository,
          <GithubEntry>[zed, alpha],
        );

        expect(
          review.targets.map((ImportTarget target) => target.source.remotePath),
          <String>['examples/a.py', 'examples/z.py'],
        );
        expect(
          review.targets.map((ImportTarget target) => target.boardPath),
          <String>['/flash/a.py', '/flash/z.py'],
        );
        expect(review.conflictPaths, <String>['/flash/z.py']);
        expect(review.blockingPaths, isEmpty);
        expect(review.targets[0].overwrites, isFalse);
        expect(review.targets[1].overwrites, isTrue);
      },
    );

    test(
      'rejects unsafe leaves and duplicate flat targets before listing',
      () async {
        final List<List<GithubEntry>> invalidSelections = <List<GithubEntry>>[
          <GithubEntry>[
            _file('../escape.py', remotePath: 'examples/../escape.py'),
          ],
          <GithubEntry>[
            _file('nested/escape.py', remotePath: 'examples/nested/escape.py'),
          ],
          <GithubEntry>[
            _file('bad\\escape.py', remotePath: 'examples/bad\\escape.py'),
          ],
          <GithubEntry>[
            _file('bad\u0000.py', remotePath: 'examples/bad\u0000.py'),
          ],
        ];

        for (final List<GithubEntry> selection in invalidSelections) {
          final _Harness h = harness();
          await expectLater(
            h.importer.review(_repository, selection),
            throwsA(_failure(GithubFailureKind.invalidTarget)),
          );
          expect(h.operationLog, isEmpty);
        }

        final _Harness duplicate = harness();
        await expectLater(
          duplicate.importer.review(_repository, <GithubEntry>[
            _file('same.py', remotePath: 'one/same.py', object: 20),
            _file('same.py', remotePath: 'two/same.py', object: 21),
          ]),
          throwsA(_failure(GithubFailureKind.duplicateTarget)),
        );
        expect(duplicate.operationLog, isEmpty);

        // `/flash/` is seven bytes. 59 × U+00E9 is 118 bytes and `.py` is
        // three, so the first complete target is exactly 128 UTF-8 bytes.
        final String exactName = '${List<String>.filled(59, 'é').join()}.py';
        final String overName = '${List<String>.filled(60, 'é').join()}.py';
        expect(utf8.encode('/flash/$exactName'), hasLength(128));

        final _Harness exact = harness();
        final GithubImportReview review = await exact.importer.review(
          _repository,
          <GithubEntry>[_file(exactName)],
        );
        expect(review.targets.single.boardPath, '/flash/$exactName');

        final _Harness over = harness();
        await expectLater(
          over.importer.review(_repository, <GithubEntry>[_file(overName)]),
          throwsA(_failure(GithubFailureKind.pathTooLong)),
        );
        expect(over.operationLog, isEmpty);
      },
    );

    test('rejects a selection spanning more than one remote folder', () async {
      final _Harness h = harness();

      await expectLater(
        h.importer.review(_repository, <GithubEntry>[
          _file('alpha.py', remotePath: 'examples/alpha.py', object: 30),
          _file('beta.py', remotePath: 'other/beta.py', object: 31),
        ]),
        throwsA(_failure(GithubFailureKind.invalidTarget)),
      );
      expect(
        h.operationLog,
        isEmpty,
        reason: 'folder scope is target validation and must precede board I/O',
      );
    });

    test('a directory at an exact target is a blocking conflict', () async {
      final _Harness h = harness(
        directoryListings: <List<RemoteEntry>>[
          <RemoteEntry>[_remoteDirectory('alpha.py')],
        ],
      );
      final GithubImportReview review = await h.importer.review(
        _repository,
        <GithubEntry>[_file('alpha.py')],
      );

      expect(review.conflictPaths, isEmpty);
      expect(review.blockingPaths, <String>['/flash/alpha.py']);
      final GithubImportResult result = await h.importer.commit(
        review,
        overwriteConfirmed: true,
      );
      _expectFailedResult(result, GithubFailureKind.blockingConflict);
      expect(h.api.fetchedRemotePaths, isEmpty);
      expect(h.connection.putFileCalls, isEmpty);
    });

    test(
      'a truncated board listing blocks review before any download',
      () async {
        final _Harness h = harness(
          directoryListings: <List<RemoteEntry>>[
            <RemoteEntry>[_remoteFile('visible.py')],
          ],
          listingTruncation: <bool>[true],
        );

        await expectLater(
          h.importer.review(_repository, <GithubEntry>[_file('hidden.py')]),
          throwsA(_failure(GithubFailureKind.incompleteBoardListing)),
        );
        expect(h.api.fetchedRemotePaths, isEmpty);
        expect(h.connection.putFileCalls, isEmpty);
      },
    );

    test(
      'an existing file requires separate explicit overwrite consent',
      () async {
        final _Harness h = harness(
          directoryListings: <List<RemoteEntry>>[
            <RemoteEntry>[_remoteFile('alpha.py')],
            <RemoteEntry>[_remoteFile('alpha.py')],
          ],
        );
        final GithubEntry alpha = _file('alpha.py');
        h.api.bytesByObjectSha[alpha.objectSha] = Uint8List.fromList(
          utf8.encode('print("new")\n'),
        );
        final GithubImportReview review = await h.importer.review(
          _repository,
          <GithubEntry>[alpha],
        );

        final GithubImportResult denied = await h.importer.commit(
          review,
          overwriteConfirmed: false,
        );
        _expectFailedResult(denied, GithubFailureKind.overwriteRequired);
        expect(h.api.fetchedRemotePaths, isEmpty);
        expect(h.connection.putFileCalls, isEmpty);

        final GithubImportResult confirmed = await h.importer.commit(
          review,
          overwriteConfirmed: true,
        );
        expect(confirmed.outcome, GithubImportOutcome.complete);
        expect(confirmed.succeeded, <String>['/flash/alpha.py']);
        expect(h.connection.putFileCalls, hasLength(1));
      },
    );
  });

  group('A33-SUB-AC-5 all-fetch content validation', () {
    test(
      'fetches and validates every byte before sequential byte-exact PUTs',
      () async {
        final _Harness h = harness();
        final GithubEntry beta = _file('beta.py', object: 2);
        final GithubEntry alpha = _file('alpha.py', object: 1);
        final Uint8List alphaBytes = Uint8List.fromList(
          utf8.encode('print("alpha")\n'),
        );
        final Uint8List betaBytes = Uint8List.fromList(
          utf8.encode('# ไพล์ beta\n'),
        );
        h.api.bytesByObjectSha[alpha.objectSha] = alphaBytes;
        h.api.bytesByObjectSha[beta.objectSha] = betaBytes;
        final GithubImportReview review = await h.importer.review(
          _repository,
          <GithubEntry>[beta, alpha],
        );
        h.operationLog.clear();

        final GithubImportResult result = await h.importer.commit(
          review,
          overwriteConfirmed: false,
        );

        expect(result.outcome, GithubImportOutcome.complete);
        expect(result.succeeded, <String>['/flash/alpha.py', '/flash/beta.py']);
        final int firstPut = h.operationLog.indexWhere(
          (String operation) => operation.startsWith('put:'),
        );
        final int lastFetch = h.operationLog.lastIndexWhere(
          (String operation) => operation.startsWith('fetch:'),
        );
        expect(firstPut, greaterThan(lastFetch));
        expect(
          h.connection.putFileCalls.map((PutFileCall call) => call.path),
          <String>['/flash/alpha.py', '/flash/beta.py'],
        );
        expect(h.connection.putFileCalls[0].bytes, orderedEquals(alphaBytes));
        expect(h.connection.putFileCalls[1].bytes, orderedEquals(betaBytes));
        expect(h.connection.mkdirCalls, isEmpty);
        expect(h.connection.getFileCalls, isEmpty);
        expect(h.connection.runFileCalls, isEmpty);
        expect(h.connection.runSourceCalls, isEmpty);
        expect(h.refreshCount, 1);
      },
    );

    test('strict UTF-8, NUL, and 256 KiB failures precede all PUTs', () async {
      final List<({String label, Uint8List bytes, GithubFailureKind kind})>
      variants = <({String label, Uint8List bytes, GithubFailureKind kind})>[
        (
          label: 'malformed UTF-8',
          bytes: Uint8List.fromList(<int>[0xc3, 0x28]),
          kind: GithubFailureKind.invalidUtf8,
        ),
        (
          label: 'NUL bytes',
          bytes: Uint8List.fromList(<int>[0x70, 0x00, 0x79]),
          kind: GithubFailureKind.nulByte,
        ),
        (
          label: 'a file larger than 256 KiB',
          bytes: Uint8List(_maxFileBytes + 1),
          kind: GithubFailureKind.fileTooLarge,
        ),
      ];

      for (final ({String label, Uint8List bytes, GithubFailureKind kind})
          variant
          in variants) {
        final _Harness h = harness();
        final GithubEntry entry = _file(
          'unsafe.py',
          declaredSize: variant.bytes.length,
        );
        h.api.bytesByObjectSha[entry.objectSha] = variant.bytes;
        final GithubImportReview review = await h.importer.review(
          _repository,
          <GithubEntry>[entry],
        );

        final GithubImportResult result = await h.importer.commit(
          review,
          overwriteConfirmed: false,
        );

        _expectFailedResult(result, variant.kind);
        expect(h.connection.putFileCalls, isEmpty, reason: variant.label);
        expect(h.refreshCount, 0, reason: variant.label);
      }
    });

    test(
      'actual bytes above the 1 MiB batch limit reject the whole batch',
      () async {
        final _Harness h = harness();
        final List<GithubEntry> entries = <GithubEntry>[];
        for (int index = 0; index < 5; index += 1) {
          final int length = index == 4 ? 1 : _maxFileBytes;
          final GithubEntry entry = _file(
            'part$index.py',
            object: index + 1,
            declaredSize: length,
          );
          entries.add(entry);
          h.api.bytesByObjectSha[entry.objectSha] = Uint8List.fromList(
            List<int>.filled(length, 0x20),
          );
        }
        expect(
          h.api.bytesByObjectSha.values.fold<int>(
            0,
            (int total, Uint8List bytes) => total + bytes.length,
          ),
          _maxBatchBytes + 1,
        );
        final GithubImportReview review = await h.importer.review(
          _repository,
          entries,
        );

        final GithubImportResult result = await h.importer.commit(
          review,
          overwriteConfirmed: false,
        );

        _expectFailedResult(result, GithubFailureKind.batchTooLarge);
        expect(h.api.fetchedRemotePaths, hasLength(5));
        expect(h.connection.putFileCalls, isEmpty);
        expect(h.refreshCount, 0);
      },
    );
  });

  group('A33-SUB-AC-4/-6 current conflicts and connection session', () {
    test(
      'a changed conflict set invalidates consent before the first PUT',
      () async {
        final _Harness h = harness(
          directoryListings: <List<RemoteEntry>>[
            <RemoteEntry>[],
            <RemoteEntry>[_remoteFile('alpha.py')],
          ],
        );
        final GithubEntry alpha = _file('alpha.py');
        h.api.bytesByObjectSha[alpha.objectSha] = Uint8List.fromList(
          utf8.encode('alpha = 1\n'),
        );
        final GithubImportReview review = await h.importer.review(
          _repository,
          <GithubEntry>[alpha],
        );

        final GithubImportResult result = await h.importer.commit(
          review,
          overwriteConfirmed: false,
        );

        _expectFailedResult(result, GithubFailureKind.conflictChanged);
        expect(h.connection.putFileCalls, isEmpty);
        expect(h.refreshCount, 0);
      },
    );

    test(
      'the session stamp is checked before review and between PUTs',
      () async {
        final _Harness staleAtReview = harness();
        staleAtReview.connection.advanceSession();

        await expectLater(
          staleAtReview.importer.review(_repository, <GithubEntry>[
            _file('alpha.py'),
          ]),
          throwsA(_failure(GithubFailureKind.staleSession)),
        );
        expect(staleAtReview.operationLog, isEmpty);

        final _Harness h = harness(holdPutAt: 1);
        final GithubEntry alpha = _file('alpha.py', object: 1);
        final GithubEntry beta = _file('beta.py', object: 2);
        h.api.bytesByObjectSha[alpha.objectSha] = Uint8List.fromList(
          utf8.encode('alpha = 1\n'),
        );
        h.api.bytesByObjectSha[beta.objectSha] = Uint8List.fromList(
          utf8.encode('beta = 2\n'),
        );
        final GithubImportReview review = await h.importer.review(
          _repository,
          <GithubEntry>[alpha, beta],
        );

        final Future<GithubImportResult> pending = h.importer.commit(
          review,
          overwriteConfirmed: false,
        );
        await h.connection.putHeld.future;
        h.connection.advanceSession();
        h.connection.releasePut.complete();
        final GithubImportResult result = await pending;

        expect(result.outcome, GithubImportOutcome.partial);
        expect(result.failure, _failure(GithubFailureKind.staleSession));
        expect(result.succeeded, <String>['/flash/alpha.py']);
        expect(result.failedOrCancelled, isNull);
        expect(result.unattempted, <String>['/flash/beta.py']);
        expect(
          h.connection.putFileCalls.map((PutFileCall call) => call.path),
          <String>['/flash/alpha.py'],
        );
        expect(h.refreshCount, 1);
      },
    );
  });

  group('A33-SUB-AC-7 partial results, cancellation, and refresh', () {
    test(
      'a failed PUT reports succeeded, failed, and unattempted paths',
      () async {
        final _Harness h = harness(failPutAt: 2);
        final List<GithubEntry> entries = <GithubEntry>[
          _file('alpha.py', object: 1),
          _file('beta.py', object: 2),
          _file('gamma.py', object: 3),
        ];
        for (final GithubEntry entry in entries) {
          h.api.bytesByObjectSha[entry.objectSha] = Uint8List.fromList(
            utf8.encode('# ${entry.name}\n'),
          );
        }
        final GithubImportReview review = await h.importer.review(
          _repository,
          entries,
        );

        final GithubImportResult result = await h.importer.commit(
          review,
          overwriteConfirmed: false,
        );

        expect(result.outcome, GithubImportOutcome.partial);
        expect(result.failure, _failure(GithubFailureKind.board));
        expect(result.succeeded, <String>['/flash/alpha.py']);
        expect(result.failedOrCancelled, '/flash/beta.py');
        expect(result.unattempted, <String>['/flash/gamma.py']);
        expect(
          h.connection.putFileCalls.map((PutFileCall call) => call.path),
          <String>['/flash/alpha.py', '/flash/beta.py'],
        );
        expect(h.refreshCount, 1);
        expect(h.connection.mkdirCalls, isEmpty);
        expect(h.connection.runFileCalls, isEmpty);
        expect(h.connection.runSourceCalls, isEmpty);
      },
    );

    test(
      'cancel is zero-write during fetch and cooperative during PUT',
      () async {
        final _Harness beforeCommit = harness();
        final GithubEntry fetchAlpha = _file('alpha.py');
        beforeCommit.api.bytesByObjectSha[fetchAlpha.objectSha] =
            Uint8List.fromList(utf8.encode('alpha = 1\n'));
        beforeCommit.api.heldObjectSha = fetchAlpha.objectSha;
        final GithubImportReview fetchReview = await beforeCommit.importer
            .review(_repository, <GithubEntry>[fetchAlpha]);

        final Future<GithubImportResult> pendingFetch = beforeCommit.importer
            .commit(fetchReview, overwriteConfirmed: false);
        await beforeCommit.api.fetchHeld.future;
        beforeCommit.importer.cancel();
        beforeCommit.api.releaseFetch.complete();
        final GithubImportResult fetchResult = await pendingFetch;

        expect(fetchResult.outcome, GithubImportOutcome.cancelled);
        expect(fetchResult.succeeded, isEmpty);
        expect(fetchResult.failedOrCancelled, isNull);
        expect(fetchResult.unattempted, <String>['/flash/alpha.py']);
        expect(beforeCommit.connection.putFileCalls, isEmpty);
        expect(beforeCommit.refreshCount, 0);

        final _Harness h = harness(holdPutAt: 1);
        final GithubEntry alpha = _file('alpha.py', object: 1);
        final GithubEntry beta = _file('beta.py', object: 2);
        h.api.bytesByObjectSha[alpha.objectSha] = Uint8List.fromList(
          utf8.encode('alpha = 1\n'),
        );
        h.api.bytesByObjectSha[beta.objectSha] = Uint8List.fromList(
          utf8.encode('beta = 2\n'),
        );
        final GithubImportReview review = await h.importer.review(
          _repository,
          <GithubEntry>[alpha, beta],
        );

        final Future<GithubImportResult> pending = h.importer.commit(
          review,
          overwriteConfirmed: false,
        );
        await h.connection.putHeld.future;
        h.importer.cancel();
        h.connection.releasePut.complete();
        final GithubImportResult result = await pending;

        expect(result.outcome, GithubImportOutcome.cancelled);
        expect(result.succeeded, <String>['/flash/alpha.py']);
        expect(result.failedOrCancelled, isNull);
        expect(result.unattempted, <String>['/flash/beta.py']);
        expect(
          h.connection.putFileCalls.map((PutFileCall call) => call.path),
          <String>['/flash/alpha.py'],
        );
        expect(h.refreshCount, 1);
      },
    );
  });
}

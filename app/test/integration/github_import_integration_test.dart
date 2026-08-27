// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.
//
// Deterministic A-33 connected-subset integration: the real public GitHub REST
// adapter feeds the board importer and shipped in-memory FakeConnection. No
// live network, GitHub credential, BLE transport, or executable source is used.

import 'dart:convert';
import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

import 'package:pyble/github_import/github_import.dart';
import 'package:pyble/pble/pble.dart';

const String _commitSha = '1111111111111111111111111111111111111111';
const String _rootTreeSha = '2222222222222222222222222222222222222222';
const String _examplesTreeSha = '3333333333333333333333333333333333333333';
const String _alphaBlobSha = '4444444444444444444444444444444444444444';
const String _zetaBlobSha = '5555555555555555555555555555555555555555';
const String _ignoredBlobSha = '6666666666666666666666666666666666666666';
const String _movedCommitSha = '9999999999999999999999999999999999999999';

final class _SequentialFakeConnection extends FakeConnection {
  _SequentialFakeConnection(this.operations, {this.failPutAt})
    : super(initial: ConnState.ready);

  final List<String> operations;
  final int? failPutAt;
  final List<String> putPaths = <String>[];
  int activePuts = 0;
  int maximumConcurrentPuts = 0;
  int _putAttempt = 0;
  int getCalls = 0;
  int mkdirCalls = 0;
  int deleteCalls = 0;
  int renameCalls = 0;
  int runFileCalls = 0;
  int runSourceCalls = 0;

  @override
  Future<void> putFile(
    String path,
    Uint8List bytes, {
    ProgressCb? onProgress,
  }) async {
    final int attempt = ++_putAttempt;
    operations.add('put:$path');
    putPaths.add(path);
    activePuts += 1;
    if (activePuts > maximumConcurrentPuts) {
      maximumConcurrentPuts = activePuts;
    }
    try {
      // Yield once so an implementation that starts PUTs concurrently is
      // detected deterministically by [maximumConcurrentPuts].
      await Future<void>.delayed(Duration.zero);
      if (attempt == failPutAt) {
        throw const EIo('scripted PUT failure');
      }
      await super.putFile(path, bytes, onProgress: onProgress);
    } finally {
      activePuts -= 1;
    }
  }

  @override
  Future<Uint8List> getFile(String path, {ProgressCb? onProgress}) {
    getCalls += 1;
    return super.getFile(path, onProgress: onProgress);
  }

  @override
  Future<void> mkdir(String path) {
    mkdirCalls += 1;
    return super.mkdir(path);
  }

  @override
  Future<void> delete(String path) {
    deleteCalls += 1;
    return super.delete(path);
  }

  @override
  Future<void> rename(String from, String to) {
    renameCalls += 1;
    return super.rename(from, to);
  }

  @override
  Future<void> runFile(String path) {
    runFileCalls += 1;
    return super.runFile(path);
  }

  @override
  Future<void> runSource(String snippet) {
    runSourceCalls += 1;
    return super.runSource(snippet);
  }
}

final class _RestBlobFixture {
  const _RestBlobFixture({
    required this.name,
    required this.sha,
    required this.bytes,
    this.mode = '100644',
  });

  final String name;
  final String sha;
  final Uint8List bytes;
  final String mode;
}

http.Response _jsonResponse(Object? body) => http.Response(
  jsonEncode(body),
  200,
  headers: const <String, String>{'content-type': 'application/json'},
);

void _expectUnauthenticatedApiRequest(
  http.Request request, {
  Map<String, String> queryParameters = const <String, String>{},
}) {
  expect(request.method, 'GET');
  expect(request.url.scheme, 'https');
  expect(request.url.host, 'api.github.com');
  expect(request.url.hasPort, isFalse);
  expect(request.url.queryParameters, queryParameters);
  expect(request.followRedirects, isFalse);
  expect(request.maxRedirects, 0);
  expect(request.headers['Accept'], 'application/vnd.github+json');
  expect(request.headers['X-GitHub-Api-Version'], '2026-03-10');
  expect(request.headers['User-Agent'], startsWith('PyBLE/'));
  final Set<String> headerNames = request.headers.keys
      .map((String name) => name.toLowerCase())
      .toSet();
  expect(headerNames, isNot(contains('authorization')));
  expect(headerNames, isNot(contains('cookie')));
  expect(request.bodyBytes, isEmpty);
}

MockClient _restFixtureClient({
  required List<_RestBlobFixture> blobs,
  required List<String> requestedPaths,
  required List<String> operations,
}) {
  final Map<String, _RestBlobFixture> blobsBySha = <String, _RestBlobFixture>{
    for (final _RestBlobFixture blob in blobs) blob.sha: blob,
  };
  return MockClient((http.Request request) async {
    _expectUnauthenticatedApiRequest(request);
    final String path = request.url.path;
    requestedPaths.add(path);
    operations.add('http:$path');

    if (path == '/repos/PyBLE-dev/integration-fixture/commits/main') {
      return _jsonResponse(<String, Object?>{
        'sha': _commitSha,
        'commit': <String, Object?>{
          'tree': <String, Object?>{'sha': _rootTreeSha},
        },
      });
    }
    if (path ==
        '/repos/PyBLE-dev/integration-fixture/git/trees/$_rootTreeSha') {
      return _jsonResponse(<String, Object?>{
        'sha': _rootTreeSha,
        'truncated': false,
        'tree': <Object?>[
          <String, Object?>{
            'path': 'examples',
            'mode': '040000',
            'type': 'tree',
            'sha': _examplesTreeSha,
          },
        ],
      });
    }
    if (path ==
        '/repos/PyBLE-dev/integration-fixture/git/trees/'
            '$_examplesTreeSha') {
      return _jsonResponse(<String, Object?>{
        'sha': _examplesTreeSha,
        'truncated': false,
        'tree': <Object?>[
          for (final _RestBlobFixture blob in blobs)
            <String, Object?>{
              'path': blob.name,
              'mode': blob.mode,
              'type': 'blob',
              'sha': blob.sha,
              'size': blob.bytes.length,
            },
        ],
      });
    }

    const String blobPrefix = '/repos/PyBLE-dev/integration-fixture/git/blobs/';
    if (path.startsWith(blobPrefix)) {
      final _RestBlobFixture? blob =
          blobsBySha[path.substring(blobPrefix.length)];
      if (blob != null) {
        return _jsonResponse(<String, Object?>{
          'sha': blob.sha,
          'size': blob.bytes.length,
          'encoding': 'base64',
          'content': base64.encode(blob.bytes),
        });
      }
    }
    throw StateError('Unexpected mock HTTP request: ${request.url}');
  });
}

Future<({GithubBoardImporter importer, GithubImportReview review})>
_prepareFixtureReview({
  required GithubRepositoryClient api,
  required _SequentialFakeConnection connection,
  required Future<void> Function() refreshFiles,
}) async {
  final RepositoryLocator locator = RepositoryLocator.parse(
    'https://github.com/PyBLE-dev/integration-fixture',
  );
  final PinnedRepository repository = await api.resolve(locator, ref: 'main');
  final GithubDirectory root = await api.listDirectory(
    repository,
    treeSha: repository.rootTreeSha,
    remotePath: '',
  );
  final GithubEntry examples = root.entries.single;
  final GithubDirectory directory = await api.listDirectory(
    repository,
    treeSha: examples.objectSha,
    remotePath: examples.remotePath,
  );
  final GithubBoardImporter importer = GithubBoardImporter(
    api: api,
    connection: connection,
    capturedSessionStamp: connectionSessionStampOf(connection),
    cwd: '/',
    refreshFiles: refreshFiles,
  );
  final GithubImportReview review = await importer.review(
    repository,
    directory.entries
        .where((GithubEntry entry) => entry.isSelectablePythonFile)
        .toList(),
  );
  return (importer: importer, review: review);
}

void main() {
  test(
    'real SHA-pinned client imports sequential exact bytes into FakeConnection',
    () async {
      final Uint8List alphaBytes = Uint8List.fromList(
        utf8.encode("print('alpha')\n"),
      );
      final Uint8List zetaBytes = Uint8List.fromList(
        utf8.encode("print('zeta')\n"),
      );
      final List<String> operations = <String>[];
      final List<String> requestedPaths = <String>[];
      final _SequentialFakeConnection connection = _SequentialFakeConnection(
        operations,
      );
      int movingRefResolutions = 0;
      int refreshCount = 0;

      final MockClient httpClient = MockClient((http.Request request) async {
        final String path = request.url.path;
        _expectUnauthenticatedApiRequest(
          request,
          queryParameters:
              path == '/repos/PyBLE-dev/integration-fixture/branches'
              ? const <String, String>{'per_page': '100', 'page': '1'}
              : const <String, String>{},
        );
        requestedPaths.add(path);
        operations.add('http:$path');

        if (path == '/repos/PyBLE-dev/integration-fixture') {
          return _jsonResponse(<String, Object?>{'default_branch': 'moving'});
        }
        if (path == '/repos/PyBLE-dev/integration-fixture/branches') {
          return _jsonResponse(<Object?>[
            <String, Object?>{
              'name': 'release/v1',
              'commit': <String, Object?>{'sha': _commitSha},
            },
            <String, Object?>{
              'name': 'moving',
              'commit': <String, Object?>{'sha': _commitSha},
            },
          ]);
        }
        if (path == '/repos/PyBLE-dev/integration-fixture/commits/moving') {
          movingRefResolutions += 1;
          return _jsonResponse(<String, Object?>{
            // A second ref resolution would model the named ref moving. The
            // integration must retain the first immutable object graph.
            'sha': movingRefResolutions == 1 ? _commitSha : _movedCommitSha,
            'commit': <String, Object?>{
              'tree': <String, Object?>{'sha': _rootTreeSha},
            },
          });
        }
        if (path ==
            '/repos/PyBLE-dev/integration-fixture/git/trees/$_rootTreeSha') {
          return _jsonResponse(<String, Object?>{
            'sha': _rootTreeSha,
            'truncated': false,
            'tree': <Object?>[
              <String, Object?>{
                'path': 'examples',
                'mode': '040000',
                'type': 'tree',
                'sha': _examplesTreeSha,
                'url': 'https://untrusted.invalid/tree',
              },
            ],
          });
        }
        if (path ==
            '/repos/PyBLE-dev/integration-fixture/git/trees/'
                '$_examplesTreeSha') {
          return _jsonResponse(<String, Object?>{
            'sha': _examplesTreeSha,
            'truncated': false,
            // Deliberately not review order: the importer must freeze a stable
            // remote-path order before fetching or writing.
            'tree': <Object?>[
              <String, Object?>{
                'path': 'zeta.py',
                'mode': '100644',
                'type': 'blob',
                'sha': _zetaBlobSha,
                'size': zetaBytes.length,
              },
              <String, Object?>{
                'path': 'notes.mpy',
                'mode': '100644',
                'type': 'blob',
                'sha': _ignoredBlobSha,
                'size': 4,
              },
              <String, Object?>{
                'path': 'alpha.py',
                'mode': '100755',
                'type': 'blob',
                'sha': _alphaBlobSha,
                'size': alphaBytes.length,
              },
            ],
          });
        }
        if (path ==
            '/repos/PyBLE-dev/integration-fixture/git/blobs/$_alphaBlobSha') {
          return _jsonResponse(<String, Object?>{
            'sha': _alphaBlobSha,
            'size': alphaBytes.length,
            'encoding': 'base64',
            'content': base64.encode(alphaBytes),
            'url': 'https://untrusted.invalid/alpha.py',
          });
        }
        if (path ==
            '/repos/PyBLE-dev/integration-fixture/git/blobs/$_zetaBlobSha') {
          return _jsonResponse(<String, Object?>{
            'sha': _zetaBlobSha,
            'size': zetaBytes.length,
            'encoding': 'base64',
            'content': base64.encode(zetaBytes),
            'url': 'https://untrusted.invalid/zeta.py',
          });
        }
        throw StateError('Unexpected mock HTTP request: ${request.url}');
      });
      final GithubRepositoryClient api = GithubRepositoryClient(
        httpClient: httpClient,
      );

      try {
        final RepositoryLocator locator = RepositoryLocator.parse(
          'https://github.com/PyBLE-dev/integration-fixture',
        );
        final GithubBranchCatalog catalog = await api.listBranches(locator);
        expect(catalog.locator, same(locator));
        expect(catalog.defaultBranch, 'moving');
        expect(catalog.branches, <String>['moving', 'release/v1']);

        final PinnedRepository repository = await api.resolve(
          locator,
          ref: catalog.defaultBranch,
        );
        expect(repository.requestedRef, 'moving');
        expect(repository.resolvedRef, 'moving');
        expect(repository.commitSha, _commitSha);
        expect(repository.rootTreeSha, _rootTreeSha);

        final GithubDirectory root = await api.listDirectory(
          repository,
          treeSha: repository.rootTreeSha,
          remotePath: '',
        );
        final GithubEntry examples = root.entries.single;
        expect(examples.kind, GithubEntryKind.directory);
        expect(examples.objectSha, _examplesTreeSha);

        final GithubDirectory directory = await api.listDirectory(
          repository,
          treeSha: examples.objectSha,
          remotePath: examples.remotePath,
        );
        final List<GithubEntry> selected = directory.entries
            .where((GithubEntry entry) => entry.isSelectablePythonFile)
            .toList();
        expect(selected.map((GithubEntry entry) => entry.remotePath), <String>[
          'examples/zeta.py',
          'examples/alpha.py',
        ]);

        final GithubBoardImporter importer = GithubBoardImporter(
          api: api,
          connection: connection,
          capturedSessionStamp: connectionSessionStampOf(connection),
          cwd: '/',
          refreshFiles: () async {
            refreshCount += 1;
            operations.add('refresh:/');
          },
        );
        final GithubImportReview review = await importer.review(
          repository,
          selected,
        );
        expect(
          review.targets.map((ImportTarget target) => target.source.remotePath),
          <String>['examples/alpha.py', 'examples/zeta.py'],
        );
        expect(
          review.targets.map((ImportTarget target) => target.boardPath),
          <String>['/alpha.py', '/zeta.py'],
        );
        expect(review.conflictPaths, isEmpty);
        expect(review.blockingPaths, isEmpty);

        final GithubImportResult result = await importer.commit(
          review,
          overwriteConfirmed: false,
        );

        expect(result.outcome, GithubImportOutcome.complete);
        expect(result.succeeded, <String>['/alpha.py', '/zeta.py']);
        expect(result.failedOrCancelled, isNull);
        expect(result.unattempted, isEmpty);
        expect(result.failure, isNull);
        expect(movingRefResolutions, 1);
        expect(requestedPaths, <String>[
          '/repos/PyBLE-dev/integration-fixture',
          '/repos/PyBLE-dev/integration-fixture/branches',
          '/repos/PyBLE-dev/integration-fixture/commits/moving',
          '/repos/PyBLE-dev/integration-fixture/git/trees/$_rootTreeSha',
          '/repos/PyBLE-dev/integration-fixture/git/trees/'
              '$_examplesTreeSha',
          '/repos/PyBLE-dev/integration-fixture/git/blobs/$_alphaBlobSha',
          '/repos/PyBLE-dev/integration-fixture/git/blobs/$_zetaBlobSha',
        ]);
        expect(
          operations,
          <String>[
            for (final String path in requestedPaths) 'http:$path',
            'put:/alpha.py',
            'put:/zeta.py',
            'refresh:/',
          ],
          reason: 'every immutable blob must finish before the first board PUT',
        );
        expect(connection.putPaths, <String>['/alpha.py', '/zeta.py']);
        expect(connection.maximumConcurrentPuts, 1);
        expect(refreshCount, 1);
        expect(connection.getCalls, 0);
        expect(connection.mkdirCalls, 0);
        expect(connection.deleteCalls, 0);
        expect(connection.renameCalls, 0);
        expect(connection.runFileCalls, 0);
        expect(connection.runSourceCalls, 0);

        expect(
          await connection.getFile('/alpha.py'),
          orderedEquals(alphaBytes),
        );
        expect(await connection.getFile('/zeta.py'), orderedEquals(zetaBytes));
      } finally {
        httpClient.close();
        await connection.dispose();
      }
    },
  );

  test(
    'a late invalid REST blob rejects the candidate before every board PUT',
    () async {
      final List<_RestBlobFixture> blobs = <_RestBlobFixture>[
        _RestBlobFixture(
          name: 'alpha.py',
          sha: _alphaBlobSha,
          bytes: Uint8List.fromList(utf8.encode("print('alpha')\n")),
        ),
        _RestBlobFixture(
          name: 'beta.py',
          sha: '7777777777777777777777777777777777777777',
          bytes: Uint8List.fromList(utf8.encode("print('beta')\n")),
        ),
        _RestBlobFixture(
          name: 'zeta.py',
          sha: _zetaBlobSha,
          bytes: Uint8List.fromList(<int>[0xc3, 0x28]),
        ),
      ];
      final List<String> operations = <String>[];
      final List<String> requestedPaths = <String>[];
      final _SequentialFakeConnection connection = _SequentialFakeConnection(
        operations,
      );
      int refreshCount = 0;
      final MockClient httpClient = _restFixtureClient(
        blobs: blobs,
        requestedPaths: requestedPaths,
        operations: operations,
      );
      final GithubRepositoryClient api = GithubRepositoryClient(
        httpClient: httpClient,
      );

      try {
        final prepared = await _prepareFixtureReview(
          api: api,
          connection: connection,
          refreshFiles: () async {
            refreshCount += 1;
          },
        );
        final GithubImportResult result = await prepared.importer.commit(
          prepared.review,
          overwriteConfirmed: false,
        );

        expect(result.outcome, GithubImportOutcome.failed);
        expect(result.failure?.kind, GithubFailureKind.invalidUtf8);
        expect(result.failure?.path, 'examples/zeta.py');
        expect(result.succeeded, isEmpty);
        expect(result.failedOrCancelled, isNull);
        expect(result.unattempted, <String>[
          '/alpha.py',
          '/beta.py',
          '/zeta.py',
        ]);
        expect(
          requestedPaths.where((String path) => path.contains('/git/blobs/')),
          hasLength(3),
        );
        expect(connection.putPaths, isEmpty);
        expect(refreshCount, 0);
        expect(connection.runFileCalls, 0);
        expect(connection.runSourceCalls, 0);
      } finally {
        httpClient.close();
        await connection.dispose();
      }
    },
  );

  test(
    'a third PUT failure reports exact succeeded failed and unattempted paths',
    () async {
      final List<_RestBlobFixture> blobs = <_RestBlobFixture>[
        _RestBlobFixture(
          name: 'zeta.py',
          sha: _zetaBlobSha,
          bytes: Uint8List.fromList(utf8.encode("print('zeta')\n")),
        ),
        _RestBlobFixture(
          name: 'gamma.py',
          sha: '8888888888888888888888888888888888888888',
          bytes: Uint8List.fromList(utf8.encode("print('gamma')\n")),
        ),
        _RestBlobFixture(
          name: 'beta.py',
          sha: '7777777777777777777777777777777777777777',
          bytes: Uint8List.fromList(utf8.encode("print('beta')\n")),
        ),
        _RestBlobFixture(
          name: 'alpha.py',
          sha: _alphaBlobSha,
          bytes: Uint8List.fromList(utf8.encode("print('alpha')\n")),
          mode: '100755',
        ),
      ];
      final List<String> operations = <String>[];
      final List<String> requestedPaths = <String>[];
      final _SequentialFakeConnection connection = _SequentialFakeConnection(
        operations,
        failPutAt: 3,
      );
      int refreshCount = 0;
      final MockClient httpClient = _restFixtureClient(
        blobs: blobs,
        requestedPaths: requestedPaths,
        operations: operations,
      );
      final GithubRepositoryClient api = GithubRepositoryClient(
        httpClient: httpClient,
      );

      try {
        final prepared = await _prepareFixtureReview(
          api: api,
          connection: connection,
          refreshFiles: () async {
            refreshCount += 1;
            operations.add('refresh:/');
          },
        );
        final GithubImportResult result = await prepared.importer.commit(
          prepared.review,
          overwriteConfirmed: false,
        );

        expect(result.outcome, GithubImportOutcome.partial);
        expect(result.failure?.kind, GithubFailureKind.board);
        expect(result.failure?.path, '/gamma.py');
        expect(result.succeeded, <String>['/alpha.py', '/beta.py']);
        expect(result.failedOrCancelled, '/gamma.py');
        expect(result.unattempted, <String>['/zeta.py']);
        expect(connection.putPaths, <String>[
          '/alpha.py',
          '/beta.py',
          '/gamma.py',
        ]);
        final int lastHttp = operations.lastIndexWhere(
          (String operation) => operation.startsWith('http:'),
        );
        final int firstPut = operations.indexWhere(
          (String operation) => operation.startsWith('put:'),
        );
        expect(firstPut, greaterThan(lastHttp));
        expect(connection.maximumConcurrentPuts, 1);
        expect(refreshCount, 1);
        expect(connection.getCalls, 0);
        expect(connection.mkdirCalls, 0);
        expect(connection.deleteCalls, 0);
        expect(connection.renameCalls, 0);
        expect(connection.runFileCalls, 0);
        expect(connection.runSourceCalls, 0);
      } finally {
        httpClient.close();
        await connection.dispose();
      }
    },
  );
}

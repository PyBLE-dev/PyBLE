// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.
//
// A-33 [red] — immutable, unauthenticated GitHub repository reads. These
// tests describe PyBLE's fresh REST adapter; they do not exercise or copy
// another application's implementation.

import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

import 'package:pyble/github_import/github_import.dart';

const String _commitSha = '1111111111111111111111111111111111111111';
const String _rootTreeSha = '2222222222222222222222222222222222222222';
const String _childTreeSha = '3333333333333333333333333333333333333333';
const String _helloBlobSha = '4444444444444444444444444444444444444444';

RepositoryLocator _locator() =>
    RepositoryLocator.parse('https://github.com/PyBLE-dev/examples');

PinnedRepository _pinned() => PinnedRepository(
  locator: _locator(),
  requestedRef: 'main',
  resolvedRef: 'main',
  commitSha: _commitSha,
  rootTreeSha: _rootTreeSha,
);

GithubEntry _helloEntry() => const GithubEntry(
  name: 'hello.py',
  remotePath: 'examples/hello.py',
  kind: GithubEntryKind.regularFile,
  objectSha: _helloBlobSha,
  declaredSize: 18,
);

void _expectGitHubRequest(http.Request request) {
  expect(request.url.scheme, 'https');
  expect(request.url.host, 'api.github.com');
  expect(request.url.hasPort, isFalse);
  expect(request.headers['Accept'], 'application/vnd.github+json');
  expect(request.headers['X-GitHub-Api-Version'], '2026-03-10');
  expect(request.headers['User-Agent'], startsWith('PyBLE/'));
  expect(request.headers.containsKey('Authorization'), isFalse);
  expect(request.headers.containsKey('Cookie'), isFalse);
}

Matcher _githubFailure(GithubFailureKind kind) => isA<GithubFailure>().having(
  (GithubFailure failure) => failure.kind,
  'kind',
  kind,
);

void main() {
  group('RepositoryLocator', () {
    test(
      'accepts only a canonical repository root and normalizes one slash',
      () {
        final RepositoryLocator locator = RepositoryLocator.parse(
          'https://github.com/PyBLE-dev/PyBLE/',
        );

        expect(locator.owner, 'PyBLE-dev');
        expect(locator.repo, 'PyBLE');
        expect(locator.canonicalRoot.scheme, 'https');
        expect(locator.canonicalRoot.host, 'github.com');
        expect(
          locator.canonicalRoot.toString(),
          'https://github.com/PyBLE-dev/PyBLE',
        );
      },
    );

    test('rejects credentials, alternate origins, and non-root paths', () {
      const List<String> invalid = <String>[
        'http://github.com/PyBLE-dev/PyBLE',
        'https://www.github.com/PyBLE-dev/PyBLE',
        'https://github.com.evil.example/PyBLE-dev/PyBLE',
        'https://user@github.com/PyBLE-dev/PyBLE',
        'https://github.com:443/PyBLE-dev/PyBLE',
        'https://github.com/PyBLE-dev/PyBLE?tab=readme',
        'https://github.com/PyBLE-dev/PyBLE#readme',
        'https://github.com/PyBLE-dev/PyBLE.git',
        'https://github.com/PyBLE-dev/PyBLE/tree/main',
        'https://github.com/PyBLE-dev',
        'https://github.com/PyBLE-dev%2FPyBLE/examples',
        'https://github.com/PyBLE-dev/../PyBLE',
      ];

      for (final String value in invalid) {
        expect(
          () => RepositoryLocator.parse(value),
          throwsA(_githubFailure(GithubFailureKind.invalidInput)),
          reason: value,
        );
      }
    });
  });

  group('GithubRepositoryClient resolution', () {
    test(
      'blank ref resolves the default branch to commit and root-tree SHAs',
      () async {
        final List<http.Request> requests = <http.Request>[];
        final MockClient httpClient = MockClient((http.Request request) async {
          requests.add(request);
          _expectGitHubRequest(request);

          if (requests.length == 1) {
            expect(request.url.pathSegments, <String>[
              'repos',
              'PyBLE-dev',
              'examples',
            ]);
            return http.Response(
              jsonEncode(<String, Object?>{'default_branch': 'main'}),
              200,
            );
          }

          expect(request.url.pathSegments, <String>[
            'repos',
            'PyBLE-dev',
            'examples',
            'commits',
            'main',
          ]);
          return http.Response(
            jsonEncode(<String, Object?>{
              'sha': _commitSha,
              'commit': <String, Object?>{
                'tree': <String, Object?>{'sha': _rootTreeSha},
              },
            }),
            200,
          );
        });
        final GithubApi api = GithubRepositoryClient(httpClient: httpClient);

        final PinnedRepository repository = await api.resolve(_locator());

        expect(repository.locator.canonicalRoot, _locator().canonicalRoot);
        expect(repository.requestedRef, isEmpty);
        expect(repository.resolvedRef, 'main');
        expect(repository.commitSha, _commitSha);
        expect(repository.rootTreeSha, _rootTreeSha);
        expect(requests, hasLength(2));
      },
    );

    test(
      'explicit slash ref is one encoded segment and skips metadata',
      () async {
        late http.Request seen;
        final MockClient httpClient = MockClient((http.Request request) async {
          seen = request;
          _expectGitHubRequest(request);
          return http.Response(
            jsonEncode(<String, Object?>{
              'sha': _commitSha,
              'commit': <String, Object?>{
                'tree': <String, Object?>{'sha': _rootTreeSha},
              },
            }),
            200,
          );
        });
        final GithubRepositoryClient api = GithubRepositoryClient(
          httpClient: httpClient,
        );

        final PinnedRepository repository = await api.resolve(
          _locator(),
          ref: 'release/v1',
        );

        expect(seen.url.pathSegments, <String>[
          'repos',
          'PyBLE-dev',
          'examples',
          'commits',
          'release/v1',
        ]);
        expect(seen.url.toString(), contains('release%2Fv1'));
        expect(repository.requestedRef, 'release/v1');
        expect(repository.resolvedRef, 'release/v1');
      },
    );

    test(
      'rejects malformed commit identity instead of publishing a pin',
      () async {
        final MockClient httpClient = MockClient(
          (http.Request request) async => http.Response(
            jsonEncode(<String, Object?>{
              'sha': 'short',
              'commit': <String, Object?>{
                'tree': <String, Object?>{'sha': _rootTreeSha},
              },
            }),
            200,
          ),
        );
        final GithubRepositoryClient api = GithubRepositoryClient(
          httpClient: httpClient,
        );

        await expectLater(
          api.resolve(_locator(), ref: 'main'),
          throwsA(_githubFailure(GithubFailureKind.malformedResponse)),
        );
      },
    );
  });

  group('GithubRepositoryClient tree browsing', () {
    test(
      'uses a non-recursive tree read and classifies object modes',
      () async {
        late http.Request seen;
        final MockClient httpClient = MockClient((http.Request request) async {
          seen = request;
          _expectGitHubRequest(request);
          return http.Response(
            jsonEncode(<String, Object?>{
              'sha': _rootTreeSha,
              'truncated': false,
              'tree': <Object?>[
                <String, Object?>{
                  'path': 'hello.py',
                  'mode': '100644',
                  'type': 'blob',
                  'sha': _helloBlobSha,
                  'size': 18,
                },
                <String, Object?>{
                  'path': 'executable.py',
                  'mode': '100755',
                  'type': 'blob',
                  'sha': '5555555555555555555555555555555555555555',
                  'size': 9,
                },
                <String, Object?>{
                  'path': 'notes.PY',
                  'mode': '100644',
                  'type': 'blob',
                  'sha': '6666666666666666666666666666666666666666',
                  'size': 5,
                },
                <String, Object?>{
                  'path': 'nested',
                  'mode': '040000',
                  'type': 'tree',
                  'sha': _childTreeSha,
                },
                <String, Object?>{
                  'path': 'link.py',
                  'mode': '120000',
                  'type': 'blob',
                  'sha': '7777777777777777777777777777777777777777',
                  'size': 8,
                },
                <String, Object?>{
                  'path': 'vendor',
                  'mode': '160000',
                  'type': 'commit',
                  'sha': '8888888888888888888888888888888888888888',
                },
              ],
            }),
            200,
          );
        });
        final GithubRepositoryClient api = GithubRepositoryClient(
          httpClient: httpClient,
        );

        final GithubDirectory directory = await api.listDirectory(
          _pinned(),
          treeSha: _rootTreeSha,
          remotePath: 'examples',
        );

        expect(seen.url.pathSegments, <String>[
          'repos',
          'PyBLE-dev',
          'examples',
          'git',
          'trees',
          _rootTreeSha,
        ]);
        expect(seen.url.queryParameters.containsKey('recursive'), isFalse);
        expect(directory.treeSha, _rootTreeSha);
        expect(directory.remotePath, 'examples');

        final Map<String, GithubEntry> byName = <String, GithubEntry>{
          for (final GithubEntry entry in directory.entries) entry.name: entry,
        };
        expect(byName['hello.py']?.kind, GithubEntryKind.regularFile);
        expect(byName['hello.py']?.remotePath, 'examples/hello.py');
        expect(byName['hello.py']?.isSelectablePythonFile, isTrue);
        expect(byName['executable.py']?.kind, GithubEntryKind.regularFile);
        expect(byName['executable.py']?.isSelectablePythonFile, isTrue);
        expect(byName['notes.PY']?.kind, GithubEntryKind.regularFile);
        expect(byName['notes.PY']?.isSelectablePythonFile, isFalse);
        expect(byName['nested']?.kind, GithubEntryKind.directory);
        expect(byName['nested']?.objectSha, _childTreeSha);
        expect(byName['link.py']?.kind, GithubEntryKind.ineligible);
        expect(byName['vendor']?.kind, GithubEntryKind.ineligible);
      },
    );

    test(
      'does not fetch a child tree until that directory is opened',
      () async {
        final List<String> requestedTreeShas = <String>[];
        final MockClient httpClient = MockClient((http.Request request) async {
          _expectGitHubRequest(request);
          final String requestedSha = request.url.pathSegments.last;
          requestedTreeShas.add(requestedSha);
          if (requestedSha == _rootTreeSha) {
            return http.Response(
              jsonEncode(<String, Object?>{
                'sha': _rootTreeSha,
                'truncated': false,
                'tree': <Object?>[
                  <String, Object?>{
                    'path': 'nested',
                    'mode': '040000',
                    'type': 'tree',
                    'sha': _childTreeSha,
                  },
                ],
              }),
              200,
            );
          }
          return http.Response(
            jsonEncode(<String, Object?>{
              'sha': _childTreeSha,
              'truncated': false,
              'tree': <Object?>[
                <String, Object?>{
                  'path': 'child.py',
                  'mode': '100644',
                  'type': 'blob',
                  'sha': _helloBlobSha,
                  'size': 3,
                },
              ],
            }),
            200,
          );
        });
        final GithubRepositoryClient api = GithubRepositoryClient(
          httpClient: httpClient,
        );

        final GithubDirectory root = await api.listDirectory(
          _pinned(),
          treeSha: _rootTreeSha,
          remotePath: '',
        );
        expect(requestedTreeShas, <String>[_rootTreeSha]);

        final GithubEntry nested = root.entries.single;
        final GithubDirectory child = await api.listDirectory(
          _pinned(),
          treeSha: nested.objectSha,
          remotePath: nested.remotePath,
        );

        expect(requestedTreeShas, <String>[_rootTreeSha, _childTreeSha]);
        expect(child.entries.single.remotePath, 'nested/child.py');
      },
    );

    test('rejects truncated or wrong-identity tree responses', () async {
      for (final Map<String, Object?> response in <Map<String, Object?>>[
        <String, Object?>{
          'sha': _rootTreeSha,
          'truncated': true,
          'tree': <Object?>[],
        },
        <String, Object?>{
          'sha': _childTreeSha,
          'truncated': false,
          'tree': <Object?>[],
        },
      ]) {
        final GithubRepositoryClient api = GithubRepositoryClient(
          httpClient: MockClient(
            (http.Request request) async =>
                http.Response(jsonEncode(response), 200),
          ),
        );

        await expectLater(
          api.listDirectory(_pinned(), treeSha: _rootTreeSha, remotePath: ''),
          throwsA(_githubFailure(GithubFailureKind.malformedResponse)),
        );
      }
    });
  });

  group('GithubRepositoryClient blob reads', () {
    test(
      'fetches the selected blob SHA and decodes its exact base64 bytes',
      () async {
        final Uint8List expected = Uint8List.fromList(
          utf8.encode("print('hello')\n"),
        );
        late http.Request seen;
        final MockClient httpClient = MockClient((http.Request request) async {
          seen = request;
          _expectGitHubRequest(request);
          return http.Response(
            jsonEncode(<String, Object?>{
              'sha': _helloBlobSha,
              'size': expected.length,
              'encoding': 'base64',
              'content': base64.encode(expected),
              // Returned URLs are deliberately untrusted and must not be used.
              'url': 'https://evil.example/changed.py',
            }),
            200,
          );
        });
        final GithubRepositoryClient api = GithubRepositoryClient(
          httpClient: httpClient,
        );

        final Uint8List bytes = await api.fetchFile(_pinned(), _helloEntry());

        expect(seen.url.pathSegments, <String>[
          'repos',
          'PyBLE-dev',
          'examples',
          'git',
          'blobs',
          _helloBlobSha,
        ]);
        expect(bytes, expected);
      },
    );

    test('rejects blob identity mismatch and non-base64 encoding', () async {
      for (final Map<String, Object?> response in <Map<String, Object?>>[
        <String, Object?>{
          'sha': '9999999999999999999999999999999999999999',
          'size': 3,
          'encoding': 'base64',
          'content': 'YWJj',
        },
        <String, Object?>{
          'sha': _helloBlobSha,
          'size': 3,
          'encoding': 'utf-8',
          'content': 'abc',
        },
      ]) {
        final GithubRepositoryClient api = GithubRepositoryClient(
          httpClient: MockClient(
            (http.Request request) async =>
                http.Response(jsonEncode(response), 200),
          ),
        );

        await expectLater(
          api.fetchFile(_pinned(), _helloEntry()),
          throwsA(_githubFailure(GithubFailureKind.malformedResponse)),
        );
      }
    });

    test(
      'rejects a blob size that disagrees with its selected tree entry',
      () async {
        final GithubRepositoryClient api = GithubRepositoryClient(
          httpClient: MockClient(
            (http.Request request) async => http.Response(
              jsonEncode(<String, Object?>{
                'sha': _helloBlobSha,
                'size': 3,
                'encoding': 'base64',
                'content': base64.encode(utf8.encode('abc')),
              }),
              200,
            ),
          ),
        );

        await expectLater(
          api.fetchFile(_pinned(), _helloEntry()),
          throwsA(_githubFailure(GithubFailureKind.malformedResponse)),
        );
      },
    );
  });

  group('GithubRepositoryClient failures', () {
    test('maps HTTP status classes to stable failure kinds', () async {
      const Map<int, GithubFailureKind> cases = <int, GithubFailureKind>{
        404: GithubFailureKind.notFound,
        403: GithubFailureKind.privateOrForbidden,
        500: GithubFailureKind.server,
      };

      for (final MapEntry<int, GithubFailureKind> entry in cases.entries) {
        final GithubRepositoryClient api = GithubRepositoryClient(
          httpClient: MockClient(
            (http.Request request) async => http.Response('{}', entry.key),
          ),
        );
        await expectLater(
          api.resolve(_locator(), ref: 'main'),
          throwsA(_githubFailure(entry.value)),
          reason: 'HTTP ${entry.key}',
        );
      }
    });

    test(
      'preserves bounded GitHub rate-limit reset and retry metadata',
      () async {
        final GithubRepositoryClient api = GithubRepositoryClient(
          httpClient: MockClient(
            (http.Request request) async => http.Response(
              '{}',
              429,
              headers: <String, String>{
                'x-ratelimit-remaining': '0',
                'x-ratelimit-reset': '2000000000',
                'retry-after': '120',
              },
            ),
          ),
        );

        try {
          await api.resolve(_locator(), ref: 'main');
          fail('Expected a typed rate-limit failure.');
        } on GithubFailure catch (failure) {
          expect(failure.kind, GithubFailureKind.rateLimited);
          expect(failure.rateLimitRemaining, 0);
          expect(
            failure.rateLimitReset,
            DateTime.fromMillisecondsSinceEpoch(2000000000 * 1000, isUtc: true),
          );
          expect(failure.retryAfter, const Duration(seconds: 120));
        }
      },
    );

    test(
      'maps transport loss to offline without exposing raw errors',
      () async {
        final GithubRepositoryClient api = GithubRepositoryClient(
          httpClient: MockClient(
            (http.Request request) async =>
                throw const SocketException('host unavailable'),
          ),
          timeout: const Duration(milliseconds: 50),
        );

        await expectLater(
          api.resolve(_locator(), ref: 'main'),
          throwsA(_githubFailure(GithubFailureKind.offline)),
        );
      },
    );

    test('aborts an in-flight request through its operation token', () async {
      final Completer<void> requestStarted = Completer<void>();
      final GithubCancellation cancellation = GithubCancellation();
      final GithubRepositoryClient api = GithubRepositoryClient(
        httpClient: MockClient.streaming((request, bodyStream) async {
          expect(request, isA<http.AbortableRequest>());
          final http.AbortableRequest abortable =
              request as http.AbortableRequest;
          requestStarted.complete();
          await abortable.abortTrigger;
          throw http.RequestAbortedException(request.url);
        }),
      );

      final Future<PinnedRepository> pending = api.resolve(
        _locator(),
        ref: 'main',
        cancellation: cancellation,
      );
      await requestStarted.future;
      cancellation.cancel();

      await expectLater(
        pending,
        throwsA(_githubFailure(GithubFailureKind.cancelled)),
      );
    });

    test('aborts an in-flight blob response through the same token', () async {
      final Completer<void> requestStarted = Completer<void>();
      final GithubCancellation cancellation = GithubCancellation();
      final GithubRepositoryClient api = GithubRepositoryClient(
        httpClient: MockClient.streaming((request, bodyStream) async {
          expect(request, isA<http.AbortableRequest>());
          final http.AbortableRequest abortable =
              request as http.AbortableRequest;
          requestStarted.complete();
          await abortable.abortTrigger;
          throw http.RequestAbortedException(request.url);
        }),
      );

      final Future<Uint8List> pending = api.fetchFile(
        _pinned(),
        _helloEntry(),
        cancellation: cancellation,
      );
      await requestStarted.future;
      cancellation.cancel();

      await expectLater(
        pending,
        throwsA(_githubFailure(GithubFailureKind.cancelled)),
      );
    });

    test('ignores malformed Retry-After metadata without leaking', () async {
      final GithubRepositoryClient api = GithubRepositoryClient(
        httpClient: MockClient(
          (http.Request request) async => http.Response(
            '{}',
            429,
            headers: <String, String>{'retry-after': 'not-an-http-date'},
          ),
        ),
      );

      await expectLater(
        api.resolve(_locator(), ref: 'main'),
        throwsA(_githubFailure(GithubFailureKind.rateLimited)),
      );
    });
  });
}

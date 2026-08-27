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
const int _repositoryId = 1345960947;
const int _branchPageBodyLimit = 512 * 1024;
const int _branchAggregateBodyLimit = 2 * 1024 * 1024;

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
  declaredSize: 15,
);

Map<String, Object?> _branch(String name) => <String, Object?>{
  'name': name,
  'commit': <String, Object?>{
    'sha': _commitSha,
    'url':
        'https://api.github.com/repos/PyBLE-dev/examples/commits/$_commitSha',
  },
  'protected': false,
};

Map<String, Object?> _repositoryMetadata(String defaultBranch) =>
    <String, Object?>{'id': _repositoryId, 'default_branch': defaultBranch};

String _branchesLink(
  int page, {
  String relation = 'next',
  int repositoryId = _repositoryId,
}) =>
    '<https://api.github.com/repositories/$repositoryId/branches'
    '?per_page=100&page=$page>; rel="$relation"';

String _locatorBranchesLink(int page) =>
    '<https://api.github.com/repos/PyBLE-dev/examples/branches'
    '?per_page=100&page=$page>; rel="next"';

Uint8List _paddedJsonBytes(Object? value, int byteLength) {
  final List<int> encoded = utf8.encode(jsonEncode(value));
  if (encoded.length > byteLength) {
    throw StateError('JSON fixture exceeds requested byte length');
  }
  return Uint8List(byteLength)
    ..fillRange(0, byteLength, 0x20)
    ..setRange(0, encoded.length, encoded);
}

List<Object?> _numberedBranches(int start, int count) => <Object?>[
  for (int index = start; index < start + count; index += 1)
    _branch('branch-${index.toString().padLeft(3, '0')}'),
];

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
            return http.Response(jsonEncode(_repositoryMetadata('main')), 200);
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

  group('GithubRepositoryClient branch discovery', () {
    test(
      'reads metadata then one exact branch page and puts the default first',
      () async {
        final List<http.Request> requests = <http.Request>[];
        final GithubApi api = GithubRepositoryClient(
          httpClient: MockClient((http.Request request) async {
            requests.add(request);
            _expectGitHubRequest(request);

            if (requests.length == 1) {
              expect(request.url.pathSegments, <String>[
                'repos',
                'PyBLE-dev',
                'examples',
              ]);
              expect(request.url.hasQuery, isFalse);
              return http.Response(
                jsonEncode(_repositoryMetadata('main')),
                200,
              );
            }

            expect(request.url.pathSegments, <String>[
              'repos',
              'PyBLE-dev',
              'examples',
              'branches',
            ]);
            expect(request.url.queryParametersAll, <String, List<String>>{
              'per_page': <String>['100'],
              'page': <String>['1'],
            });
            expect(
              request.url.queryParameters.containsKey('protected'),
              isFalse,
            );
            return http.Response(
              jsonEncode(<Object?>[
                _branch('zeta'),
                _branch('feature/slash'),
                _branch('main'),
                _branch('alpha'),
              ]),
              200,
            );
          }),
        );

        final GithubBranchCatalog catalog = await api.listBranches(_locator());

        expect(catalog.locator, _locator());
        expect(catalog.defaultBranch, 'main');
        expect(catalog.branches, <String>[
          'main',
          'alpha',
          'feature/slash',
          'zeta',
        ]);
        expect(() => catalog.branches.add('mutated'), throwsUnsupportedError);
        expect(requests, hasLength(2));
      },
    );

    test('requires a positive bounded repository id for discovery', () async {
      const List<Object?> invalidIds = <Object?>[
        null,
        0,
        -1,
        '1345960947',
        9007199254740992,
      ];

      for (final Object? invalidId in invalidIds) {
        int requestCount = 0;
        final GithubApi api = GithubRepositoryClient(
          httpClient: MockClient((http.Request request) async {
            requestCount += 1;
            return http.Response(
              jsonEncode(<String, Object?>{
                'id': invalidId,
                'default_branch': 'main',
              }),
              200,
            );
          }),
        );

        await expectLater(
          api.listBranches(_locator()),
          throwsA(_githubFailure(GithubFailureKind.malformedResponse)),
          reason: 'repository id: $invalidId',
        );
        expect(requestCount, 1, reason: 'repository id: $invalidId');
      }
    });

    test(
      'validates Link pagination and sorts a complete multi-page catalog',
      () async {
        final List<int> requestedPages = <int>[];
        int requestCount = 0;
        final GithubApi api = GithubRepositoryClient(
          httpClient: MockClient((http.Request request) async {
            requestCount += 1;
            _expectGitHubRequest(request);
            if (request.url.pathSegments.last != 'branches') {
              return http.Response(
                jsonEncode(_repositoryMetadata('main')),
                200,
              );
            }

            final int page = int.parse(request.url.queryParameters['page']!);
            requestedPages.add(page);
            expect(request.url.queryParameters['per_page'], '100');
            if (page == 1) {
              return http.Response(
                jsonEncode(<Object?>[_branch('zeta'), _branch('main')]),
                200,
                headers: <String, String>{
                  'link':
                      '${_branchesLink(2)}, '
                      '${_branchesLink(2, relation: 'last')}',
                },
              );
            }
            expect(page, 2);
            return http.Response(
              jsonEncode(<Object?>[_branch('release/v1'), _branch('alpha')]),
              200,
            );
          }),
        );

        final GithubBranchCatalog catalog = await api.listBranches(_locator());

        expect(requestCount, 3);
        expect(requestedPages, <int>[1, 2]);
        expect(catalog.defaultBranch, 'main');
        expect(catalog.branches, <String>[
          'main',
          'alpha',
          'release/v1',
          'zeta',
        ]);
      },
    );

    test('accepts the exact locator-derived pagination path', () async {
      final List<int> requestedPages = <int>[];
      final GithubApi api = GithubRepositoryClient(
        httpClient: MockClient((http.Request request) async {
          if (request.url.pathSegments.last != 'branches') {
            return http.Response(jsonEncode(_repositoryMetadata('main')), 200);
          }
          final int page = int.parse(request.url.queryParameters['page']!);
          requestedPages.add(page);
          return http.Response(
            jsonEncode(<Object?>[_branch(page == 1 ? 'main' : 'release/v1')]),
            200,
            headers: page == 1
                ? <String, String>{'link': _locatorBranchesLink(2)}
                : const <String, String>{},
          );
        }),
      );

      final GithubBranchCatalog catalog = await api.listBranches(_locator());

      expect(requestedPages, <int>[1, 2]);
      expect(catalog.branches, <String>['main', 'release/v1']);
    });

    test(
      'rejects a wrong-host or skipped-page next Link without following it',
      () async {
        final List<({String label, String link})> cases =
            <({String label, String link})>[
              (
                label: 'wrong host',
                link:
                    '<https://evil.example/repositories/$_repositoryId/branches'
                    '?per_page=100&page=2>; rel="next"',
              ),
              (label: 'skipped page', link: _branchesLink(3)),
              (
                label: 'mismatched repository id',
                link: _branchesLink(2, repositoryId: _repositoryId + 1),
              ),
            ];

        for (final ({String label, String link}) variant in cases) {
          int requestCount = 0;
          final GithubApi api = GithubRepositoryClient(
            httpClient: MockClient((http.Request request) async {
              requestCount += 1;
              _expectGitHubRequest(request);
              if (request.url.pathSegments.last != 'branches') {
                return http.Response(
                  jsonEncode(_repositoryMetadata('main')),
                  200,
                );
              }
              return http.Response(
                jsonEncode(<Object?>[_branch('main')]),
                200,
                headers: <String, String>{'link': variant.link},
              );
            }),
          );

          await expectLater(
            api.listBranches(_locator()),
            throwsA(_githubFailure(GithubFailureKind.malformedResponse)),
            reason: variant.label,
          );
          expect(requestCount, 2, reason: variant.label);
        }
      },
    );

    test('accepts a branch page body at exactly 512 KiB', () async {
      final GithubApi api = GithubRepositoryClient(
        httpClient: MockClient((http.Request request) async {
          if (request.url.pathSegments.last != 'branches') {
            return http.Response(jsonEncode(_repositoryMetadata('main')), 200);
          }
          return http.Response.bytes(
            _paddedJsonBytes(<Object?>[_branch('main')], _branchPageBodyLimit),
            200,
          );
        }),
      );

      final GithubBranchCatalog catalog = await api.listBranches(_locator());

      expect(catalog.branches, <String>['main']);
    });

    test('rejects a branch page body one byte above 512 KiB', () async {
      int requestCount = 0;
      final GithubApi api = GithubRepositoryClient(
        httpClient: MockClient((http.Request request) async {
          requestCount += 1;
          if (request.url.pathSegments.last != 'branches') {
            return http.Response(jsonEncode(_repositoryMetadata('main')), 200);
          }
          return http.Response.bytes(
            _paddedJsonBytes(<Object?>[
              _branch('main'),
            ], _branchPageBodyLimit + 1),
            200,
          );
        }),
      );

      await expectLater(
        api.listBranches(_locator()),
        throwsA(_githubFailure(GithubFailureKind.malformedResponse)),
      );
      expect(requestCount, 2);
    });

    test('accepts aggregate branch bodies at exactly 2 MiB', () async {
      final List<int> requestedPages = <int>[];
      final GithubApi api = GithubRepositoryClient(
        httpClient: MockClient((http.Request request) async {
          if (request.url.pathSegments.last != 'branches') {
            return http.Response(jsonEncode(_repositoryMetadata('main')), 200);
          }

          final int page = int.parse(request.url.queryParameters['page']!);
          requestedPages.add(page);
          return http.Response.bytes(
            _paddedJsonBytes(<Object?>[
              _branch(page == 1 ? 'main' : 'branch-$page'),
            ], _branchPageBodyLimit),
            200,
            headers: page < 4
                ? <String, String>{'link': _branchesLink(page + 1)}
                : const <String, String>{},
          );
        }),
      );

      final GithubBranchCatalog catalog = await api.listBranches(_locator());

      expect(requestedPages, <int>[1, 2, 3, 4]);
      expect(catalog.branches, <String>[
        'main',
        'branch-2',
        'branch-3',
        'branch-4',
      ]);
    });

    test('rejects aggregate branch bodies one byte above 2 MiB', () async {
      final List<int> requestedPages = <int>[];
      final GithubApi api = GithubRepositoryClient(
        httpClient: MockClient((http.Request request) async {
          if (request.url.pathSegments.last != 'branches') {
            return http.Response(jsonEncode(_repositoryMetadata('main')), 200);
          }

          final int page = int.parse(request.url.queryParameters['page']!);
          requestedPages.add(page);
          final int bodyLength = switch (page) {
            < 4 => _branchPageBodyLimit,
            4 => _branchAggregateBodyLimit - (3 * _branchPageBodyLimit) - 1,
            _ => 2,
          };
          return http.Response.bytes(
            _paddedJsonBytes(
              page == 5
                  ? const <Object?>[]
                  : <Object?>[_branch(page == 1 ? 'main' : 'branch-$page')],
              bodyLength,
            ),
            200,
            headers: page < 5
                ? <String, String>{'link': _branchesLink(page + 1)}
                : const <String, String>{},
          );
        }),
      );

      await expectLater(
        api.listBranches(_locator()),
        throwsA(_githubFailure(GithubFailureKind.malformedResponse)),
      );
      expect(requestedPages, <int>[1, 2, 3, 4, 5]);
    });

    test('accepts a complete catalog at the 512-branch boundary', () async {
      final List<int> requestedPages = <int>[];
      final GithubApi api = GithubRepositoryClient(
        httpClient: MockClient((http.Request request) async {
          if (request.url.pathSegments.last != 'branches') {
            return http.Response(
              jsonEncode(_repositoryMetadata('branch-000')),
              200,
            );
          }

          final int page = int.parse(request.url.queryParameters['page']!);
          requestedPages.add(page);
          final int start = (page - 1) * 100;
          final int count = page < 6 ? 100 : 12;
          return http.Response(
            jsonEncode(_numberedBranches(start, count)),
            200,
            headers: page < 6
                ? <String, String>{'link': _branchesLink(page + 1)}
                : const <String, String>{},
          );
        }),
      );

      final GithubBranchCatalog catalog = await api.listBranches(_locator());

      expect(requestedPages, <int>[1, 2, 3, 4, 5, 6]);
      expect(catalog.branches, hasLength(512));
      expect(catalog.branches.first, 'branch-000');
      expect(catalog.branches.last, 'branch-511');
    });

    test(
      'rejects a 513th branch without publishing a partial catalog',
      () async {
        final List<int> requestedPages = <int>[];
        final GithubApi api = GithubRepositoryClient(
          httpClient: MockClient((http.Request request) async {
            if (request.url.pathSegments.last != 'branches') {
              return http.Response(
                jsonEncode(_repositoryMetadata('branch-000')),
                200,
              );
            }

            final int page = int.parse(request.url.queryParameters['page']!);
            requestedPages.add(page);
            final int start = (page - 1) * 100;
            final int count = page < 6 ? 100 : 13;
            return http.Response(
              jsonEncode(_numberedBranches(start, count)),
              200,
              headers: page < 6
                  ? <String, String>{'link': _branchesLink(page + 1)}
                  : const <String, String>{},
            );
          }),
        );

        await expectLater(
          api.listBranches(_locator()),
          throwsA(_githubFailure(GithubFailureKind.tooManyBranches)),
        );
        expect(requestedPages, <int>[1, 2, 3, 4, 5, 6]);
      },
    );

    test('rejects a seventh advertised page without requesting it', () async {
      final List<int> requestedPages = <int>[];
      final GithubApi api = GithubRepositoryClient(
        httpClient: MockClient((http.Request request) async {
          if (request.url.pathSegments.last != 'branches') {
            return http.Response(
              jsonEncode(_repositoryMetadata('branch-000')),
              200,
            );
          }

          final int page = int.parse(request.url.queryParameters['page']!);
          requestedPages.add(page);
          final int start = (page - 1) * 100;
          final int count = page < 6 ? 100 : 12;
          return http.Response(
            jsonEncode(_numberedBranches(start, count)),
            200,
            headers: <String, String>{'link': _branchesLink(page + 1)},
          );
        }),
      );

      await expectLater(
        api.listBranches(_locator()),
        throwsA(_githubFailure(GithubFailureKind.tooManyBranches)),
      );
      expect(requestedPages, <int>[1, 2, 3, 4, 5, 6]);
    });

    test('rejects duplicate and invalid branch names as malformed', () async {
      final List<({String label, List<Object?> body})> cases =
          <({String label, List<Object?> body})>[
            (
              label: 'duplicate',
              body: <Object?>[_branch('main'), _branch('main')],
            ),
            (label: 'empty', body: <Object?>[_branch('main'), _branch('')]),
            (
              label: 'leading whitespace',
              body: <Object?>[_branch('main'), _branch(' feature')],
            ),
            (
              label: 'backslash',
              body: <Object?>[_branch('main'), _branch(r'feature\unsafe')],
            ),
          ];

      for (final ({String label, List<Object?> body}) variant in cases) {
        final GithubApi api = GithubRepositoryClient(
          httpClient: MockClient((http.Request request) async {
            if (request.url.pathSegments.last != 'branches') {
              return http.Response(
                jsonEncode(_repositoryMetadata('main')),
                200,
              );
            }
            return http.Response(jsonEncode(variant.body), 200);
          }),
        );

        await expectLater(
          api.listBranches(_locator()),
          throwsA(_githubFailure(GithubFailureKind.malformedResponse)),
          reason: variant.label,
        );
      }
    });

    test('resolves the selected branch through the commit endpoint', () async {
      final List<http.Request> requests = <http.Request>[];
      final GithubApi api = GithubRepositoryClient(
        httpClient: MockClient((http.Request request) async {
          requests.add(request);
          _expectGitHubRequest(request);
          if (request.url.pathSegments.last == 'examples') {
            return http.Response(jsonEncode(_repositoryMetadata('main')), 200);
          }
          if (request.url.pathSegments.last == 'branches') {
            return http.Response(
              jsonEncode(<Object?>[_branch('main'), _branch('release/v1')]),
              200,
            );
          }

          expect(request.url.pathSegments, <String>[
            'repos',
            'PyBLE-dev',
            'examples',
            'commits',
            'release/v1',
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
        }),
      );

      final GithubBranchCatalog catalog = await api.listBranches(_locator());
      final String selected = catalog.branches.singleWhere(
        (String branch) => branch == 'release/v1',
      );
      final PinnedRepository pinned = await api.resolve(
        _locator(),
        ref: selected,
      );

      expect(requests, hasLength(3));
      expect(requests.last.url.toString(), contains('release%2Fv1'));
      expect(pinned.requestedRef, 'release/v1');
      expect(pinned.resolvedRef, 'release/v1');
      expect(pinned.commitSha, _commitSha);
      expect(pinned.rootTreeSha, _rootTreeSha);
    });
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

    test('accepts 512 direct entries and rejects a 513th', () async {
      Map<String, Object?> treeWithEntries(int count) => <String, Object?>{
        'sha': _rootTreeSha,
        'truncated': false,
        'tree': <Object?>[
          for (int index = 0; index < count; index += 1)
            <String, Object?>{
              'path': 'example_$index.py',
              'mode': '100644',
              'type': 'blob',
              'sha': index.toRadixString(16).padLeft(40, '0'),
              'size': 0,
            },
        ],
      };

      final GithubRepositoryClient atLimit = GithubRepositoryClient(
        httpClient: MockClient(
          (http.Request request) async =>
              http.Response(jsonEncode(treeWithEntries(512)), 200),
        ),
      );
      final GithubDirectory accepted = await atLimit.listDirectory(
        _pinned(),
        treeSha: _rootTreeSha,
        remotePath: '',
      );
      expect(accepted.entries, hasLength(512));

      final GithubRepositoryClient aboveLimit = GithubRepositoryClient(
        httpClient: MockClient(
          (http.Request request) async =>
              http.Response(jsonEncode(treeWithEntries(513)), 200),
        ),
      );
      await expectLater(
        aboveLimit.listDirectory(
          _pinned(),
          treeSha: _rootTreeSha,
          remotePath: '',
        ),
        throwsA(_githubFailure(GithubFailureKind.malformedResponse)),
      );
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
    test('enforces one absolute deadline against a trickling body', () async {
      final StreamController<List<int>> body = StreamController<List<int>>();
      final Completer<void> abortObserved = Completer<void>();
      Timer? trickle;
      final MockClient httpClient = MockClient.streaming((
        http.BaseRequest request,
        http.ByteStream requestBody,
      ) async {
        expect(request, isA<http.AbortableRequest>());
        final http.AbortableRequest abortable =
            request as http.AbortableRequest;
        trickle = Timer.periodic(const Duration(milliseconds: 10), (_) {
          if (!body.isClosed) body.add(const <int>[0x20]);
        });
        unawaited(
          abortable.abortTrigger!.then((_) async {
            if (!abortObserved.isCompleted) abortObserved.complete();
            trickle?.cancel();
            if (!body.isClosed) await body.close();
          }),
        );
        return http.StreamedResponse(body.stream, HttpStatus.ok);
      });
      final GithubRepositoryClient api = GithubRepositoryClient(
        httpClient: httpClient,
        timeout: const Duration(milliseconds: 80),
      );
      final Stopwatch elapsed = Stopwatch()..start();

      try {
        await expectLater(
          api
              .resolve(_locator(), ref: 'main')
              .timeout(const Duration(seconds: 1)),
          throwsA(_githubFailure(GithubFailureKind.offline)),
        );
        expect(elapsed.elapsed, lessThan(const Duration(milliseconds: 500)));
        await expectLater(
          abortObserved.future.timeout(const Duration(milliseconds: 200)),
          completes,
        );
      } finally {
        elapsed.stop();
        trickle?.cancel();
        if (!body.isClosed) await body.close();
        httpClient.close();
      }
    });

    test(
      'cancels response bodies rejected by status or declared length',
      () async {
        final List<({int status, int? length, GithubFailureKind kind})> cases =
            <({int status, int? length, GithubFailureKind kind})>[
              (
                status: HttpStatus.notFound,
                length: null,
                kind: GithubFailureKind.notFound,
              ),
              (
                status: HttpStatus.ok,
                length: 1024 * 1024 + 1,
                kind: GithubFailureKind.malformedResponse,
              ),
            ];

        for (final variant in cases) {
          final int status = variant.status;
          final int? length = variant.length;
          final GithubFailureKind kind = variant.kind;
          bool bodyCancelled = false;
          final StreamController<List<int>> body = StreamController<List<int>>(
            onCancel: () {
              bodyCancelled = true;
            },
          );
          final MockClient httpClient = MockClient.streaming((
            http.BaseRequest request,
            http.ByteStream requestBody,
          ) async {
            return http.StreamedResponse(
              body.stream,
              status,
              contentLength: length,
            );
          });
          final GithubRepositoryClient api = GithubRepositoryClient(
            httpClient: httpClient,
          );

          try {
            await expectLater(
              api.resolve(_locator(), ref: 'main'),
              throwsA(_githubFailure(kind)),
            );
            expect(
              bodyCancelled,
              isTrue,
              reason: 'HTTP $status with Content-Length $length',
            );
          } finally {
            unawaited(body.close());
            httpClient.close();
          }
        }
      },
    );

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

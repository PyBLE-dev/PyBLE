// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.
//
// A-33 connected subset [red] — native, adaptive GitHub example browsing and
// an explicit review/commit into the captured Files directory. The network is
// a fresh in-memory GithubApi fake and every board assertion crosses only the
// Connection seam; no GitHub account, radio, or proprietary implementation is
// involved.

import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:pyble/files/files.dart';
import 'package:pyble/github_import/github_import.dart';
import 'package:pyble/localization/localization.dart';
import 'package:pyble/pble/pble.dart';

import '../support/feature_harness.dart';
import '../support/recording_connection.dart';

const String _commitSha = '1111111111111111111111111111111111111111';
const String _rootTreeSha = '2222222222222222222222222222222222222222';
const String _nestedTreeSha = '3333333333333333333333333333333333333333';
const String _helloBlobSha = '4444444444444444444444444444444444444444';
const String _blinkBlobSha = '5555555555555555555555555555555555555555';
const String _readmeBlobSha = '6666666666666666666666666666666666666666';

const GithubEntry _helloEntry = GithubEntry(
  name: 'hello.py',
  remotePath: 'hello.py',
  kind: GithubEntryKind.regularFile,
  objectSha: _helloBlobSha,
  declaredSize: 21,
);

const GithubEntry _blinkEntry = GithubEntry(
  name: 'blink.py',
  remotePath: 'blink.py',
  kind: GithubEntryKind.regularFile,
  objectSha: _blinkBlobSha,
  declaredSize: 14,
);

const GithubEntry _readmeEntry = GithubEntry(
  name: 'README.md',
  remotePath: 'README.md',
  kind: GithubEntryKind.regularFile,
  objectSha: _readmeBlobSha,
  declaredSize: 8,
);

const GithubEntry _nestedEntry = GithubEntry(
  name: 'nested',
  remotePath: 'nested',
  kind: GithubEntryKind.directory,
  objectSha: _nestedTreeSha,
  declaredSize: 0,
);

final class _FakeGithubApi implements GithubApi {
  _FakeGithubApi({
    this.entries = const <GithubEntry>[
      _helloEntry,
      _blinkEntry,
      _readmeEntry,
      _nestedEntry,
    ],
    Map<String, String> sourceByRemotePath = const <String, String>{
      'hello.py': "print('hello')\n",
      'blink.py': 'print(1)\n',
    },
    this.resolveFailure,
    this.resolveGate,
    this.listGate,
  }) : _bytesByRemotePath = <String, Uint8List>{
         for (final MapEntry<String, String> source
             in sourceByRemotePath.entries)
           source.key: Uint8List.fromList(utf8.encode(source.value)),
       };

  final List<GithubEntry> entries;
  final Map<String, Uint8List> _bytesByRemotePath;
  final GithubFailure? resolveFailure;
  final Completer<void>? resolveGate;
  final Completer<void>? listGate;
  final List<(RepositoryLocator, String)> resolveCalls =
      <(RepositoryLocator, String)>[];
  final List<String> listedRemotePaths = <String>[];
  final List<String> fetchedRemotePaths = <String>[];

  @override
  Future<PinnedRepository> resolve(
    RepositoryLocator locator, {
    String ref = '',
  }) async {
    resolveCalls.add((locator, ref));
    await resolveGate?.future;
    if (resolveFailure case final GithubFailure failure) throw failure;
    return PinnedRepository(
      locator: locator,
      requestedRef: ref,
      resolvedRef: ref.isEmpty ? 'main' : ref,
      commitSha: _commitSha,
      rootTreeSha: _rootTreeSha,
    );
  }

  @override
  Future<GithubDirectory> listDirectory(
    PinnedRepository repository, {
    required String treeSha,
    required String remotePath,
  }) async {
    listedRemotePaths.add(remotePath);
    await listGate?.future;
    return GithubDirectory(
      treeSha: treeSha,
      remotePath: remotePath,
      entries: entries,
    );
  }

  @override
  Future<Uint8List> fetchFile(
    PinnedRepository repository,
    GithubEntry entry,
  ) async {
    fetchedRemotePaths.add(entry.remotePath);
    return Uint8List.fromList(_bytesByRemotePath[entry.remotePath]!);
  }
}

final class _FailingPutConnection extends RecordingConnection {
  _FailingPutConnection() : super(initial: ConnState.ready);

  int _putAttempt = 0;

  @override
  Future<void> putFile(
    String path,
    Uint8List bytes, {
    ProgressCb? onProgress,
  }) async {
    _putAttempt += 1;
    if (_putAttempt == 2) {
      injectError(const EIo('scripted second PUT failure'));
    }
    await super.putFile(path, bytes, onProgress: onProgress);
  }
}

final class _HoldingPutConnection extends RecordingConnection {
  _HoldingPutConnection() : super(initial: ConnState.ready);

  final Completer<void> putSettled = Completer<void>();
  final Completer<void> releasePut = Completer<void>();

  @override
  Future<void> putFile(
    String path,
    Uint8List bytes, {
    ProgressCb? onProgress,
  }) async {
    await super.putFile(path, bytes, onProgress: onProgress);
    putSettled.complete();
    await releasePut.future;
  }
}

Key _entryKey(String remotePath) => ValueKey<String>('githubEntry_$remotePath');

Key _selectionKey(String remotePath) =>
    ValueKey<String>('githubSelect_$remotePath');

Future<void> _openImport(
  WidgetTester tester,
  RecordingConnection connection,
  _FakeGithubApi api, {
  Size size = const Size(1024, 768),
}) async {
  await pumpSurface(
    tester,
    const FilesView(),
    connection: connection,
    extra: <Override>[githubApiProvider.overrideWithValue(api)],
    size: size,
  );
  await tester.pumpAndSettle();
  await tester.tap(find.byTooltip(l10nOf(tester).githubImportAction));
  await tester.pumpAndSettle();
}

Future<void> _browse(
  WidgetTester tester, {
  String repository = 'https://github.com/PyBLE-dev/examples',
  String ref = '',
}) async {
  await tester.enterText(find.byKey(kGithubRepositoryFieldKey), repository);
  if (ref.isNotEmpty) {
    await tester.enterText(find.byKey(kGithubRefFieldKey), ref);
  }
  await tester.tap(find.byKey(kGithubBrowseButtonKey));
  await tester.pumpAndSettle();
}

void main() {
  group('A-33 GitHub import — adaptive connected Files workflow', () {
    testWidgets(
      'wide dialog pins the default ref, reviews exact targets, and commits exact bytes without Run',
      (WidgetTester tester) async {
        final RecordingConnection connection = RecordingConnection(
          initial: ConnState.ready,
        );
        final _FakeGithubApi api = _FakeGithubApi();
        addTearDown(connection.dispose);

        await _openImport(tester, connection, api);
        expect(find.byType(Dialog), findsOneWidget);
        expect(find.byType(BottomSheet), findsNothing);

        await _browse(tester);

        expect(api.resolveCalls, hasLength(1));
        expect(
          api.resolveCalls.single.$1.canonicalRoot.toString(),
          'https://github.com/PyBLE-dev/examples',
        );
        expect(
          api.resolveCalls.single.$2,
          isEmpty,
          reason: 'a blank ref must request the repository default branch',
        );
        expect(api.listedRemotePaths, <String>['']);
        expect(find.textContaining(_commitSha), findsOneWidget);

        expect(find.byKey(_entryKey('hello.py')), findsOneWidget);
        expect(find.byKey(_selectionKey('hello.py')), findsOneWidget);
        expect(find.byKey(_entryKey('blink.py')), findsOneWidget);
        expect(find.byKey(_selectionKey('blink.py')), findsOneWidget);
        expect(find.byKey(_entryKey('README.md')), findsOneWidget);
        expect(find.byKey(_selectionKey('README.md')), findsNothing);
        expect(find.byKey(_entryKey('nested')), findsOneWidget);
        expect(find.byKey(_selectionKey('nested')), findsNothing);

        await tester.tap(find.byKey(_selectionKey('hello.py')));
        await tester.tap(find.byKey(_selectionKey('blink.py')));
        await tester.pump();
        await tester.tap(find.byKey(kGithubReviewButtonKey));
        await tester.pumpAndSettle();

        expect(find.textContaining('hello.py'), findsWidgets);
        expect(find.textContaining('/hello.py'), findsOneWidget);
        expect(find.textContaining('blink.py'), findsWidgets);
        expect(find.textContaining('/blink.py'), findsOneWidget);

        await tester.tap(find.byKey(kGithubCommitButtonKey));
        await tester.pumpAndSettle();

        expect(api.fetchedRemotePaths, <String>['blink.py', 'hello.py']);
        expect(
          connection.putFileCalls.map((PutFileCall call) => call.path),
          <String>['/blink.py', '/hello.py'],
        );
        expect(utf8.decode(connection.putFileCalls[0].bytes), 'print(1)\n');
        expect(
          utf8.decode(connection.putFileCalls[1].bytes),
          "print('hello')\n",
        );
        expect(connection.mkdirCalls, isEmpty);
        expect(connection.runFileCalls, isEmpty);
        expect(connection.runSourceCalls, isEmpty);
      },
    );

    testWidgets('599 dp opens the same workflow as a modal bottom sheet', (
      WidgetTester tester,
    ) async {
      final RecordingConnection connection = RecordingConnection(
        initial: ConnState.ready,
      );
      final _FakeGithubApi api = _FakeGithubApi();
      addTearDown(connection.dispose);

      await _openImport(tester, connection, api, size: const Size(599, 768));

      expect(find.byType(BottomSheet), findsOneWidget);
      expect(find.byType(Dialog), findsNothing);
      expect(find.byKey(kGithubRepositoryFieldKey), findsOneWidget);
      expect(find.byKey(kGithubRefFieldKey), findsOneWidget);
    });

    testWidgets(
      'an existing target needs a separate localized confirmation; Cancel writes nothing',
      (WidgetTester tester) async {
        final RecordingConnection connection = RecordingConnection(
          initial: ConnState.ready,
        );
        final _FakeGithubApi api = _FakeGithubApi(
          entries: const <GithubEntry>[_helloEntry],
          sourceByRemotePath: const <String, String>{
            'hello.py': "print('replacement')\n",
          },
        );
        addTearDown(connection.dispose);
        await connection.putFile(
          '/hello.py',
          Uint8List.fromList(utf8.encode("print('original')\n")),
        );
        connection.putFileCalls.clear();
        connection.operationLog.clear();

        await _openImport(tester, connection, api);
        final AppLocalizations l10n = l10nOf(tester);
        await _browse(tester);
        await tester.tap(find.byKey(_selectionKey('hello.py')));
        await tester.pump();
        await tester.tap(find.byKey(kGithubReviewButtonKey));
        await tester.pumpAndSettle();

        expect(find.textContaining('/hello.py'), findsOneWidget);
        await tester.tap(find.byKey(kGithubCommitButtonKey));
        await tester.pumpAndSettle();

        final Finder overwriteDialog = find.byType(AlertDialog);
        expect(overwriteDialog, findsOneWidget);
        expect(
          find.descendant(
            of: overwriteDialog,
            matching: find.textContaining('/hello.py'),
          ),
          findsOneWidget,
        );
        expect(find.byKey(kGithubCommitButtonKey), findsOneWidget);
        expect(connection.putFileCalls, isEmpty);

        await tester.tap(
          find.descendant(
            of: overwriteDialog,
            matching: find.text(l10n.commonCancel),
          ),
        );
        await tester.pumpAndSettle();

        expect(connection.putFileCalls, isEmpty);
        expect(
          utf8.decode(await connection.getFile('/hello.py')),
          "print('original')\n",
        );
        expect(connection.runFileCalls, isEmpty);
        expect(connection.runSourceCalls, isEmpty);
      },
    );

    testWidgets(
      'resolve, folder loading, rate guidance, and error focus are explicit',
      (WidgetTester tester) async {
        final RecordingConnection connection = RecordingConnection(
          initial: ConnState.ready,
        );
        final Completer<void> resolveGate = Completer<void>();
        final Completer<void> listGate = Completer<void>();
        final _FakeGithubApi loadingApi = _FakeGithubApi(
          resolveGate: resolveGate,
          listGate: listGate,
        );
        addTearDown(connection.dispose);

        await _openImport(tester, connection, loadingApi);
        await tester.enterText(
          find.byKey(kGithubRepositoryFieldKey),
          'https://github.com/PyBLE-dev/examples',
        );
        await tester.tap(find.byKey(kGithubBrowseButtonKey));
        await tester.pump();
        expect(find.text('Resolving repository…'), findsOneWidget);

        resolveGate.complete();
        await tester.pump();
        expect(find.text('Loading repository folder…'), findsOneWidget);
        listGate.complete();
        await tester.pumpAndSettle();

        await tester.tap(find.byTooltip(l10nOf(tester).githubImportClose));
        await tester.pumpAndSettle();

        final _FakeGithubApi rateLimitedApi = _FakeGithubApi(
          resolveFailure: const GithubFailure(
            GithubFailureKind.rateLimited,
            rateLimitRemaining: 0,
            retryAfter: Duration(seconds: 120),
          ),
        );
        await _openImport(tester, connection, rateLimitedApi);
        await _browse(tester);

        expect(find.textContaining('120'), findsOneWidget);
        final Finder failure = find.byKey(
          const ValueKey<String>('githubImportFailure'),
        );
        expect(failure, findsOneWidget);
        expect(tester.widget<Focus>(failure).focusNode?.hasFocus, isTrue);
        expect(
          tester.getSemantics(failure),
          matchesSemantics(isLiveRegion: true),
        );
      },
    );

    testWidgets('dismissal returns focus to the invoking Files action', (
      WidgetTester tester,
    ) async {
      final RecordingConnection connection = RecordingConnection(
        initial: ConnState.ready,
      );
      final _FakeGithubApi api = _FakeGithubApi();
      addTearDown(connection.dispose);
      await pumpSurface(
        tester,
        const FilesView(),
        connection: connection,
        extra: <Override>[githubApiProvider.overrideWithValue(api)],
      );
      await tester.pumpAndSettle();

      final Finder tooltip = find.byTooltip(l10nOf(tester).githubImportAction);
      final Finder buttonFinder = find.ancestor(
        of: tooltip,
        matching: find.byType(IconButton),
      );
      final FocusNode? invokingFocus = tester
          .widget<IconButton>(buttonFinder)
          .focusNode;
      expect(invokingFocus, isNotNull);

      await tester.tap(tooltip);
      await tester.pumpAndSettle();
      await tester.tap(find.byTooltip(l10nOf(tester).githubImportClose));
      await tester.pumpAndSettle();

      expect(invokingFocus!.hasFocus, isTrue);
    });

    testWidgets(
      'partial result labels succeeded, failed, and unattempted paths and announces once',
      (WidgetTester tester) async {
        final _FailingPutConnection connection = _FailingPutConnection();
        final GithubEntry third = GithubEntry(
          name: 'third.py',
          remotePath: 'third.py',
          kind: GithubEntryKind.regularFile,
          objectSha: '7777777777777777777777777777777777777777',
          declaredSize: 9,
        );
        final _FakeGithubApi api = _FakeGithubApi(
          entries: <GithubEntry>[_helloEntry, _blinkEntry, third],
          sourceByRemotePath: const <String, String>{
            'hello.py': "print('hello')\n",
            'blink.py': 'print(1)\n',
            'third.py': 'print(3)\n',
          },
        );
        addTearDown(connection.dispose);

        await _openImport(tester, connection, api);
        await _browse(tester);
        for (final String path in <String>[
          'hello.py',
          'blink.py',
          'third.py',
        ]) {
          await tester.tap(find.byKey(_selectionKey(path)));
        }
        await tester.pump();
        await tester.tap(find.byKey(kGithubReviewButtonKey));
        await tester.pumpAndSettle();
        await tester.tap(find.byKey(kGithubCommitButtonKey));
        await tester.pumpAndSettle();

        expect(find.text('Downloaded'), findsOneWidget);
        expect(find.text('Failed'), findsOneWidget);
        expect(find.text('Not attempted'), findsOneWidget);
        final Finder result = find.byKey(
          const ValueKey<String>('githubImportResult'),
        );
        expect(result, findsOneWidget);
        expect(
          tester.getSemantics(result),
          matchesSemantics(isLiveRegion: true),
        );
      },
    );

    testWidgets('editing repository or ref invalidates the pinned selection', (
      WidgetTester tester,
    ) async {
      final RecordingConnection connection = RecordingConnection(
        initial: ConnState.ready,
      );
      final _FakeGithubApi api = _FakeGithubApi();
      addTearDown(connection.dispose);

      await _openImport(tester, connection, api);
      await _browse(tester);
      await tester.tap(find.byKey(_selectionKey('hello.py')));
      await tester.pump();
      expect(
        tester
            .widget<CheckboxListTile>(find.byKey(_selectionKey('hello.py')))
            .value,
        isTrue,
      );

      await tester.enterText(find.byKey(kGithubRefFieldKey), 'other-branch');
      await tester.pump();

      expect(find.textContaining(_commitSha), findsNothing);
      expect(find.byKey(_selectionKey('hello.py')), findsNothing);
      expect(
        tester
            .widget<FilledButton>(find.byKey(kGithubReviewButtonKey))
            .onPressed,
        isNull,
      );
    });

    testWidgets('an in-flight PUT cannot dismiss and hide its final result', (
      WidgetTester tester,
    ) async {
      final _HoldingPutConnection connection = _HoldingPutConnection();
      final _FakeGithubApi api = _FakeGithubApi(
        entries: const <GithubEntry>[_helloEntry],
      );
      addTearDown(() async {
        if (!connection.releasePut.isCompleted) {
          connection.releasePut.complete();
        }
        await connection.dispose();
      });

      await _openImport(tester, connection, api);
      await _browse(tester);
      await tester.tap(find.byKey(_selectionKey('hello.py')));
      await tester.pump();
      await tester.tap(find.byKey(kGithubReviewButtonKey));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(kGithubCommitButtonKey));
      await connection.putSettled.future;
      await tester.pump();

      final Finder close = find.ancestor(
        of: find.byTooltip(l10nOf(tester).githubImportClose),
        matching: find.byType(IconButton),
      );
      expect(tester.widget<IconButton>(close).onPressed, isNull);
      expect(find.byType(Dialog), findsOneWidget);

      connection.releasePut.complete();
      await tester.pumpAndSettle();
      expect(
        find.byKey(const ValueKey<String>('githubImportResult')),
        findsOneWidget,
      );
    });
  });
}

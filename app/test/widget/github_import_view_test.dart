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

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter/services.dart';
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

const GithubEntry _protectedExampleEntry = GithubEntry(
  name: 'pyble_i2c_scan.py',
  remotePath: 'pyble_i2c_scan.py',
  kind: GithubEntryKind.regularFile,
  objectSha: '7777777777777777777777777777777777777777',
  declaredSize: 14,
);

final class _BranchCatalogFixture {
  const _BranchCatalogFixture({
    required this.defaultBranch,
    required this.branches,
    this.gate,
  });

  final String defaultBranch;
  final List<String> branches;
  final Completer<void>? gate;
}

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
    this.childListFailure,
    this.resolveGate,
    this.listGate,
    this.fetchFailuresRemaining = 0,
    this.fetchFailure = const GithubFailure(GithubFailureKind.offline),
    this.listFailuresRemaining = 0,
    this.branchCatalogs = const <_BranchCatalogFixture>[
      _BranchCatalogFixture(
        defaultBranch: 'main',
        branches: <String>['main', 'develop', 'release/v1'],
      ),
    ],
  }) : _bytesByRemotePath = <String, Uint8List>{
         for (final MapEntry<String, String> source
             in sourceByRemotePath.entries)
           source.key: Uint8List.fromList(utf8.encode(source.value)),
       };

  final List<GithubEntry> entries;
  final Map<String, Uint8List> _bytesByRemotePath;
  final GithubFailure? resolveFailure;
  final GithubFailure? childListFailure;
  final Completer<void>? resolveGate;
  final Completer<void>? listGate;
  int fetchFailuresRemaining;
  final GithubFailure fetchFailure;
  int listFailuresRemaining;
  final List<_BranchCatalogFixture> branchCatalogs;
  final List<RepositoryLocator> listBranchesCalls = <RepositoryLocator>[];
  final List<(RepositoryLocator, String)> resolveCalls =
      <(RepositoryLocator, String)>[];
  final List<String> listedRemotePaths = <String>[];
  final List<String> fetchedRemotePaths = <String>[];

  @override
  Future<GithubBranchCatalog> listBranches(
    RepositoryLocator locator, {
    GithubCancellation? cancellation,
  }) async {
    final int callIndex = listBranchesCalls.length;
    listBranchesCalls.add(locator);
    final int fixtureIndex = callIndex < branchCatalogs.length
        ? callIndex
        : branchCatalogs.length - 1;
    final _BranchCatalogFixture fixture = branchCatalogs[fixtureIndex];
    await fixture.gate?.future;
    // Deliberately return even after cancellation. Widget generations, rather
    // than a cooperative fake, must keep stale discovery out of the chooser.
    return GithubBranchCatalog(
      locator: locator,
      defaultBranch: fixture.defaultBranch,
      branches: fixture.branches,
    );
  }

  @override
  Future<PinnedRepository> resolve(
    RepositoryLocator locator, {
    String ref = '',
    GithubCancellation? cancellation,
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
    GithubCancellation? cancellation,
  }) async {
    listedRemotePaths.add(remotePath);
    await listGate?.future;
    if (listFailuresRemaining > 0) {
      listFailuresRemaining -= 1;
      throw GithubFailure(GithubFailureKind.offline, path: remotePath);
    }
    final GithubFailure? failure = childListFailure;
    if (remotePath.isNotEmpty && failure != null) {
      throw failure;
    }
    return GithubDirectory(
      treeSha: treeSha,
      remotePath: remotePath,
      entries: entries,
    );
  }

  @override
  Future<Uint8List> fetchFile(
    PinnedRepository repository,
    GithubEntry entry, {
    GithubCancellation? cancellation,
  }) async {
    fetchedRemotePaths.add(entry.remotePath);
    if (fetchFailuresRemaining > 0) {
      fetchFailuresRemaining -= 1;
      throw fetchFailure;
    }
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

final class _HoldingReviewConnection extends RecordingConnection {
  _HoldingReviewConnection() : super(initial: ConnState.ready);

  final Completer<void> listStarted = Completer<void>();
  final Completer<void> releaseList = Completer<void>();

  @override
  Future<DirectoryListing> listDirWithMetadata(String path) async {
    if (!listStarted.isCompleted) listStarted.complete();
    await releaseList.future;
    return super.listDirWithMetadata(path);
  }
}

final class _CountingReviewConnection extends RecordingConnection {
  _CountingReviewConnection() : super(initial: ConnState.ready);

  int importerListCalls = 0;

  @override
  Future<DirectoryListing> listDirWithMetadata(String path) {
    importerListCalls += 1;
    return super.listDirWithMetadata(path);
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
  String repository = kOfficialExamplesRepositoryUrl,
  String ref = '',
}) async {
  final TextField repositoryField = tester.widget<TextField>(
    find.byKey(kGithubRepositoryFieldKey),
  );
  if (repositoryField.controller!.text != repository) {
    await tester.enterText(find.byKey(kGithubRepositoryFieldKey), repository);
    await tester.pump();
    await tester.tap(find.byKey(kGithubLoadBranchesButtonKey));
    await tester.pumpAndSettle();
  }
  if (ref.isNotEmpty) {
    if (find.byKey(kGithubRefFieldKey).evaluate().isEmpty) {
      await tester.tap(find.byKey(kGithubManualRefToggleKey));
      await tester.pump();
    }
    await tester.enterText(find.byKey(kGithubRefFieldKey), ref);
  }
  await tester.tap(find.byKey(kGithubBrowseButtonKey));
  await tester.pumpAndSettle();
}

Future<void> _toggleSelection(WidgetTester tester, String remotePath) async {
  final Finder selection = find.byKey(_selectionKey(remotePath));
  await tester.ensureVisible(selection);
  await tester.pumpAndSettle();
  await tester.tap(selection);
  await tester.pump();
}

Future<void> _activateButtonWithEnter(WidgetTester tester, Key key) async {
  final Finder button = find.byKey(key);
  final Finder label = find.descendant(of: button, matching: find.byType(Text));
  final FocusNode focusNode = Focus.of(tester.element(label));
  focusNode.requestFocus();
  await tester.pump();
  expect(focusNode.hasFocus, isTrue);
  await tester.sendKeyEvent(LogicalKeyboardKey.enter);
  await tester.pumpAndSettle();
}

void main() {
  group('A-33 GitHub import — adaptive connected Files workflow', () {
    testWidgets(
      'a new importer prefills the editable official examples repository',
      (WidgetTester tester) async {
        final RecordingConnection connection = RecordingConnection(
          initial: ConnState.ready,
        );
        final _FakeGithubApi api = _FakeGithubApi();
        addTearDown(connection.dispose);

        await _openImport(tester, connection, api);

        final TextField repositoryField = tester.widget<TextField>(
          find.byKey(kGithubRepositoryFieldKey),
        );
        expect(
          repositoryField.controller!.text,
          kOfficialExamplesRepositoryUrl,
        );
        expect(repositoryField.enabled, isTrue);
        expect(api.listBranchesCalls, hasLength(1));
        expect(
          api.listBranchesCalls.single.canonicalRoot.toString(),
          kOfficialExamplesRepositoryUrl,
        );

        const String customRepository = 'https://github.com/example/lessons';
        await tester.enterText(
          find.byKey(kGithubRepositoryFieldKey),
          customRepository,
        );
        await tester.pump(const Duration(seconds: 1));

        expect(repositoryField.controller!.text, customRepository);
        expect(
          api.listBranchesCalls,
          hasLength(1),
          reason: 'editing must not spend one GitHub request per keystroke',
        );
      },
    );

    testWidgets(
      'initial discovery exposes branches only and resolves the default branch again',
      (WidgetTester tester) async {
        final RecordingConnection connection = RecordingConnection(
          initial: ConnState.ready,
        );
        final _FakeGithubApi api = _FakeGithubApi(
          branchCatalogs: const <_BranchCatalogFixture>[
            _BranchCatalogFixture(
              defaultBranch: 'main',
              branches: <String>['main', 'develop', 'release/v1'],
            ),
          ],
        );
        addTearDown(connection.dispose);

        await _openImport(tester, connection, api);

        expect(find.byKey(kGithubBranchDropdownKey), findsOneWidget);
        expect(find.byKey(kGithubRefFieldKey), findsNothing);
        await tester.tap(find.byKey(kGithubBranchDropdownKey));
        await tester.pumpAndSettle();
        expect(find.textContaining('main'), findsWidgets);
        expect(find.text('develop'), findsOneWidget);
        expect(find.text('release/v1'), findsOneWidget);
        await tester.tap(find.textContaining('main').last);
        await tester.pumpAndSettle();

        await tester.tap(find.byKey(kGithubBrowseButtonKey));
        await tester.pumpAndSettle();

        expect(api.resolveCalls, hasLength(1));
        expect(api.resolveCalls.single.$2, 'main');
        expect(find.textContaining(_commitSha), findsOneWidget);
      },
    );

    testWidgets('selecting an alternate branch resolves its exact name', (
      WidgetTester tester,
    ) async {
      final RecordingConnection connection = RecordingConnection(
        initial: ConnState.ready,
      );
      final _FakeGithubApi api = _FakeGithubApi();
      addTearDown(connection.dispose);

      await _openImport(tester, connection, api);
      await tester.tap(find.byKey(kGithubBranchDropdownKey));
      await tester.pumpAndSettle();
      await tester.tap(find.text('release/v1').last);
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(kGithubBrowseButtonKey));
      await tester.pumpAndSettle();

      expect(api.resolveCalls, hasLength(1));
      expect(api.resolveCalls.single.$2, 'release/v1');
    });

    testWidgets('an empty branch catalog is explicit and cannot be browsed', (
      WidgetTester tester,
    ) async {
      final RecordingConnection connection = RecordingConnection(
        initial: ConnState.ready,
      );
      final _FakeGithubApi api = _FakeGithubApi(
        branchCatalogs: const <_BranchCatalogFixture>[
          _BranchCatalogFixture(defaultBranch: 'main', branches: <String>[]),
        ],
      );
      addTearDown(connection.dispose);

      await _openImport(tester, connection, api);

      expect(find.text(l10nOf(tester).githubImportNoBranches), findsOneWidget);
      expect(find.byKey(kGithubBranchDropdownKey), findsNothing);
      expect(find.byKey(kGithubLoadBranchesButtonKey), findsOneWidget);
      expect(
        tester
            .widget<FilledButton>(find.byKey(kGithubBrowseButtonKey))
            .onPressed,
        isNull,
      );
      expect(api.resolveCalls, isEmpty);
    });

    testWidgets('the branch chooser retains useful semantics at 2x text', (
      WidgetTester tester,
    ) async {
      tester.platformDispatcher.textScaleFactorTestValue = 2;
      addTearDown(tester.platformDispatcher.clearTextScaleFactorTestValue);
      final RecordingConnection connection = RecordingConnection(
        initial: ConnState.ready,
      );
      final _FakeGithubApi api = _FakeGithubApi();
      addTearDown(connection.dispose);

      await _openImport(tester, connection, api);
      final Finder chooser = find.byKey(kGithubBranchDropdownKey);
      final Finder input = find.descendant(
        of: chooser,
        matching: find.byType(EditableText),
      );
      await tester.ensureVisible(chooser);
      await tester.pumpAndSettle();

      expect(
        tester.getSemantics(input),
        matchesSemantics(
          label: l10nOf(tester).githubImportBranchLabel,
          value: 'main',
          isTextField: true,
          hasEnabledState: true,
          isEnabled: true,
          isFocusable: true,
          hasTapAction: true,
          hasFocusAction: true,
          hasExpandedState: true,
        ),
      );
      expect(tester.takeException(), isNull);
    });

    testWidgets(
      'keyboard search selects an available branch and resolves its exact ref',
      (WidgetTester tester) async {
        final RecordingConnection connection = RecordingConnection(
          initial: ConnState.ready,
        );
        final _FakeGithubApi api = _FakeGithubApi();
        addTearDown(connection.dispose);

        await _openImport(tester, connection, api);
        final Finder input = find.descendant(
          of: find.byKey(kGithubBranchDropdownKey),
          matching: find.byType(EditableText),
        );
        await tester.tap(input);
        await tester.pumpAndSettle();
        await tester.enterText(input, 'release');
        await tester.pumpAndSettle();
        expect(find.text('release/v1'), findsOneWidget);

        await tester.testTextInput.receiveAction(TextInputAction.done);
        await tester.pumpAndSettle();
        expect(
          tester.widget<EditableText>(input).controller.text,
          'release/v1',
        );

        await tester.tap(find.byKey(kGithubBrowseButtonKey));
        await tester.pumpAndSettle();
        expect(api.resolveCalls, hasLength(1));
        expect(api.resolveCalls.single.$2, 'release/v1');
      },
    );

    testWidgets('advanced mode retains exact tag and commit refs', (
      WidgetTester tester,
    ) async {
      final RecordingConnection connection = RecordingConnection(
        initial: ConnState.ready,
      );
      final _FakeGithubApi api = _FakeGithubApi();
      addTearDown(connection.dispose);

      await _openImport(tester, connection, api);
      await tester.tap(find.byKey(kGithubManualRefToggleKey));
      await tester.pump();
      expect(find.byKey(kGithubBranchDropdownKey), findsNothing);
      expect(find.byKey(kGithubRefFieldKey), findsOneWidget);

      await tester.enterText(find.byKey(kGithubRefFieldKey), 'v1.2.0');
      await tester.tap(find.byKey(kGithubBrowseButtonKey));
      await tester.pumpAndSettle();
      expect(api.resolveCalls.single.$2, 'v1.2.0');

      await tester.enterText(find.byKey(kGithubRefFieldKey), _commitSha);
      await tester.pump();
      expect(
        find.text(l10nOf(tester).githubImportPinnedCommit(_commitSha)),
        findsNothing,
      );
      await tester.tap(find.byKey(kGithubBrowseButtonKey));
      await tester.pumpAndSettle();

      expect(
        api.resolveCalls.map(((RepositoryLocator, String) call) => call.$2),
        <String>['v1.2.0', _commitSha],
      );
    });

    testWidgets(
      'editing the repository clears its catalog until explicit branch refresh',
      (WidgetTester tester) async {
        final RecordingConnection connection = RecordingConnection(
          initial: ConnState.ready,
        );
        final _FakeGithubApi api = _FakeGithubApi();
        addTearDown(connection.dispose);

        await _openImport(tester, connection, api);
        expect(find.byKey(kGithubBranchDropdownKey), findsOneWidget);

        const String customRepository = 'https://github.com/example/lessons';
        await tester.enterText(
          find.byKey(kGithubRepositoryFieldKey),
          customRepository,
        );
        await tester.pump(const Duration(seconds: 1));

        expect(find.byKey(kGithubBranchDropdownKey), findsNothing);
        expect(find.byKey(kGithubLoadBranchesButtonKey), findsOneWidget);
        expect(api.listBranchesCalls, hasLength(1));

        await tester.tap(find.byKey(kGithubLoadBranchesButtonKey));
        await tester.pumpAndSettle();

        expect(api.listBranchesCalls, hasLength(2));
        expect(
          api.listBranchesCalls.last.canonicalRoot.toString(),
          customRepository,
        );
        expect(find.byKey(kGithubBranchDropdownKey), findsOneWidget);

        await tester.tap(find.byKey(kGithubBrowseButtonKey));
        await tester.pumpAndSettle();
        expect(
          api.resolveCalls.single.$1.canonicalRoot.toString(),
          customRepository,
        );
        expect(api.resolveCalls.single.$2, 'main');
      },
    );

    testWidgets('a stale branch response cannot replace a refreshed catalog', (
      WidgetTester tester,
    ) async {
      final RecordingConnection connection = RecordingConnection(
        initial: ConnState.ready,
      );
      final Completer<void> staleGate = Completer<void>();
      final _FakeGithubApi api = _FakeGithubApi(
        branchCatalogs: <_BranchCatalogFixture>[
          _BranchCatalogFixture(
            defaultBranch: 'main',
            branches: const <String>['main', 'stale-branch'],
            gate: staleGate,
          ),
          const _BranchCatalogFixture(
            defaultBranch: 'stable',
            branches: <String>['stable', 'next'],
          ),
        ],
      );
      addTearDown(() {
        if (!staleGate.isCompleted) staleGate.complete();
      });
      addTearDown(connection.dispose);

      await pumpSurface(
        tester,
        const FilesView(),
        connection: connection,
        extra: <Override>[githubApiProvider.overrideWithValue(api)],
      );
      await tester.pumpAndSettle();
      await tester.tap(find.byTooltip(l10nOf(tester).githubImportAction));
      await tester.pump();
      expect(api.listBranchesCalls, hasLength(1));

      const String customRepository = 'https://github.com/example/lessons';
      await tester.enterText(
        find.byKey(kGithubRepositoryFieldKey),
        customRepository,
      );
      await tester.pump();
      await tester.tap(find.byKey(kGithubLoadBranchesButtonKey));
      await tester.pumpAndSettle();
      expect(api.listBranchesCalls, hasLength(2));

      staleGate.complete();
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(kGithubBrowseButtonKey));
      await tester.pumpAndSettle();

      expect(api.resolveCalls, hasLength(1));
      expect(
        api.resolveCalls.single.$1.canonicalRoot.toString(),
        customRepository,
      );
      expect(
        api.resolveCalls.single.$2,
        'stable',
        reason: 'the late official-repository result must remain stale',
      );
    });

    testWidgets(
      'wide dialog pins the selected default branch, reviews exact targets, and commits exact bytes without Run',
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
          'main',
          reason: 'normal mode must resolve the selected default branch again',
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

        await _toggleSelection(tester, 'hello.py');
        await _toggleSelection(tester, 'blink.py');
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
      expect(find.byKey(kGithubBranchDropdownKey), findsOneWidget);
      expect(find.byKey(kGithubManualRefToggleKey), findsOneWidget);
    });

    testWidgets('hardware Enter activates Browse and Review', (
      WidgetTester tester,
    ) async {
      final RecordingConnection connection = RecordingConnection(
        initial: ConnState.ready,
      );
      final _FakeGithubApi api = _FakeGithubApi(
        entries: const <GithubEntry>[_helloEntry],
      );
      addTearDown(connection.dispose);

      await _openImport(tester, connection, api);
      await _activateButtonWithEnter(tester, kGithubBrowseButtonKey);

      expect(api.resolveCalls, hasLength(1));
      expect(api.listedRemotePaths, <String>['']);
      await _toggleSelection(tester, 'hello.py');
      await _activateButtonWithEnter(tester, kGithubReviewButtonKey);

      expect(find.text(l10nOf(tester).githubImportReviewTitle), findsOneWidget);
      expect(connection.putFileCalls, isEmpty);
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
        await _toggleSelection(tester, 'hello.py');
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
          matchesSemantics(
            isLiveRegion: true,
            isFocusable: true,
            isFocused: true,
            hasFocusAction: true,
          ),
        );
        Finder failureLiveRegions() => find.descendant(
          of: failure,
          matching: find.byWidgetPredicate(
            (Widget widget) =>
                widget is Semantics && widget.properties.liveRegion == true,
          ),
        );
        expect(failureLiveRegions(), findsOneWidget);
        final int failureNodeId = tester.getSemantics(failureLiveRegions()).id;
        tester.platformDispatcher.textScaleFactorTestValue = 1.1;
        addTearDown(tester.platformDispatcher.clearTextScaleFactorTestValue);
        await tester.pump();
        expect(failureLiveRegions(), findsOneWidget);
        expect(tester.getSemantics(failureLiveRegions()).id, failureNodeId);
        expect(find.text(l10nOf(tester).githubImportRetry), findsNothing);
        expect(
          tester
              .widget<FilledButton>(find.byKey(kGithubBrowseButtonKey))
              .onPressed,
          isNull,
        );

        await tester.pump(const Duration(seconds: 120));
        expect(find.text(l10nOf(tester).githubImportRetry), findsOneWidget);
        expect(
          tester
              .widget<FilledButton>(find.byKey(kGithubBrowseButtonKey))
              .onPressed,
          isNotNull,
        );
      },
    );

    testWidgets(
      'a failed root listing keeps its pin and retries only that listing',
      (WidgetTester tester) async {
        final RecordingConnection connection = RecordingConnection(
          initial: ConnState.ready,
        );
        final _FakeGithubApi api = _FakeGithubApi(listFailuresRemaining: 1);
        addTearDown(connection.dispose);

        await _openImport(tester, connection, api);
        await _browse(tester);

        expect(api.resolveCalls, hasLength(1));
        expect(api.listedRemotePaths, <String>['']);
        expect(find.textContaining(_commitSha), findsOneWidget);

        await tester.tap(find.text(l10nOf(tester).githubImportRetry));
        await tester.pumpAndSettle();

        expect(api.resolveCalls, hasLength(1));
        expect(api.listedRemotePaths, <String>['', '']);
        expect(find.text('hello.py'), findsOneWidget);
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
          await _toggleSelection(tester, path);
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
        Finder resultLiveRegions() => find.byWidgetPredicate(
          (Widget widget) =>
              widget is Semantics &&
              widget.key == const ValueKey<String>('githubImportResult') &&
              widget.properties.liveRegion == true,
        );
        expect(resultLiveRegions(), findsOneWidget);
        expect(
          tester.getSemantics(result),
          matchesSemantics(isLiveRegion: true),
        );
        final int resultNodeId = tester.getSemantics(resultLiveRegions()).id;
        tester.platformDispatcher.textScaleFactorTestValue = 1.1;
        addTearDown(tester.platformDispatcher.clearTextScaleFactorTestValue);
        await tester.pumpAndSettle();
        expect(resultLiveRegions(), findsOneWidget);
        expect(tester.getSemantics(resultLiveRegions()).id, resultNodeId);
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
      await _toggleSelection(tester, 'hello.py');
      expect(
        tester
            .widget<CheckboxListTile>(find.byKey(_selectionKey('hello.py')))
            .value,
        isTrue,
      );

      await tester.tap(find.byKey(kGithubManualRefToggleKey));
      await tester.pump();
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
      await _toggleSelection(tester, 'hello.py');
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

    testWidgets('failed child navigation retains the parent selection', (
      WidgetTester tester,
    ) async {
      final RecordingConnection connection = RecordingConnection(
        initial: ConnState.ready,
      );
      final _FakeGithubApi api = _FakeGithubApi(
        childListFailure: const GithubFailure(GithubFailureKind.server),
      );
      addTearDown(connection.dispose);

      await _openImport(tester, connection, api);
      await _browse(tester);
      await _toggleSelection(tester, 'hello.py');
      await tester.tap(find.byKey(_entryKey('nested')));
      await tester.pumpAndSettle();

      expect(
        tester
            .widget<CheckboxListTile>(find.byKey(_selectionKey('hello.py')))
            .value,
        isTrue,
      );
      expect(find.text('/'), findsNWidgets(2));
    });

    testWidgets('a zero-write blob failure retries from the same review', (
      WidgetTester tester,
    ) async {
      final RecordingConnection connection = RecordingConnection(
        initial: ConnState.ready,
      );
      final _FakeGithubApi api = _FakeGithubApi(
        entries: const <GithubEntry>[_helloEntry],
        fetchFailuresRemaining: 1,
      );
      addTearDown(connection.dispose);

      await _openImport(tester, connection, api);
      await _browse(tester);
      await _toggleSelection(tester, 'hello.py');
      await tester.tap(find.byKey(kGithubReviewButtonKey));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(kGithubCommitButtonKey));
      await tester.pumpAndSettle();

      expect(connection.putFileCalls, isEmpty);
      expect(find.text(l10nOf(tester).githubImportRetry), findsOneWidget);
      expect(find.byKey(kGithubCommitButtonKey), findsOneWidget);

      await tester.tap(find.text(l10nOf(tester).githubImportRetry));
      await tester.pumpAndSettle();

      expect(connection.putFileCalls, hasLength(1));
      expect(
        find.byKey(const ValueKey<String>('githubImportResult')),
        findsOneWidget,
      );
    });

    testWidgets('a size failure identifies its safe repository path', (
      WidgetTester tester,
    ) async {
      const GithubEntry oversized = GithubEntry(
        name: 'oversized.py',
        remotePath: 'examples/oversized.py',
        kind: GithubEntryKind.regularFile,
        objectSha: _helloBlobSha,
        declaredSize: 21,
      );
      final RecordingConnection connection = RecordingConnection(
        initial: ConnState.ready,
      );
      final _FakeGithubApi api = _FakeGithubApi(
        entries: const <GithubEntry>[oversized],
        fetchFailuresRemaining: 1,
        fetchFailure: const GithubFailure(
          GithubFailureKind.fileTooLarge,
          path: 'examples/oversized.py',
        ),
      );
      addTearDown(connection.dispose);

      await _openImport(tester, connection, api);
      await _browse(tester);
      await _toggleSelection(tester, 'examples/oversized.py');
      await tester.tap(find.byKey(kGithubReviewButtonKey));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(kGithubCommitButtonKey));
      await tester.pumpAndSettle();

      expect(connection.putFileCalls, isEmpty);
      expect(find.textContaining('examples/oversized.py'), findsOneWidget);
    });

    testWidgets('a rate-limited blob retry waits without writing', (
      WidgetTester tester,
    ) async {
      final RecordingConnection connection = RecordingConnection(
        initial: ConnState.ready,
      );
      final _FakeGithubApi api = _FakeGithubApi(
        entries: const <GithubEntry>[_helloEntry],
        fetchFailuresRemaining: 1,
        fetchFailure: const GithubFailure(
          GithubFailureKind.rateLimited,
          retryAfter: Duration(seconds: 60),
        ),
      );
      addTearDown(connection.dispose);

      await _openImport(tester, connection, api);
      await _browse(tester);
      await tester.tap(
        find.byKey(const ValueKey<String>('githubSelect_hello.py')),
      );
      await tester.pump();
      await tester.tap(find.byKey(kGithubReviewButtonKey));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(kGithubCommitButtonKey));
      await tester.pumpAndSettle();

      expect(connection.putFileCalls, isEmpty);
      expect(find.textContaining('60'), findsOneWidget);
      expect(find.text(l10nOf(tester).githubImportRetry), findsNothing);
      expect(
        tester
            .widget<FilledButton>(find.byKey(kGithubCommitButtonKey))
            .onPressed,
        isNull,
      );

      await tester.pump(const Duration(seconds: 60));
      expect(find.text(l10nOf(tester).githubImportRetry), findsOneWidget);
      expect(
        tester
            .widget<FilledButton>(find.byKey(kGithubCommitButtonKey))
            .onPressed,
        isNotNull,
      );

      await tester.tap(find.text(l10nOf(tester).githubImportRetry));
      await tester.pumpAndSettle();
      expect(connection.putFileCalls, hasLength(1));
      expect(
        find.byKey(const ValueKey<String>('githubImportResult')),
        findsOneWidget,
      );
    });

    testWidgets('review cancellation cannot bypass a blob retry deadline', (
      WidgetTester tester,
    ) async {
      final RecordingConnection connection = RecordingConnection(
        initial: ConnState.ready,
      );
      final _FakeGithubApi api = _FakeGithubApi(
        entries: const <GithubEntry>[_helloEntry],
        fetchFailuresRemaining: 1,
        fetchFailure: const GithubFailure(
          GithubFailureKind.rateLimited,
          retryAfter: Duration(seconds: 60),
        ),
      );
      addTearDown(connection.dispose);

      await _openImport(tester, connection, api);
      await _browse(tester);
      await _toggleSelection(tester, 'hello.py');
      await tester.tap(find.byKey(kGithubReviewButtonKey));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(kGithubCommitButtonKey));
      await tester.pumpAndSettle();
      expect(api.fetchedRemotePaths, <String>['hello.py']);

      await tester.tap(
        find.widgetWithText(TextButton, l10nOf(tester).commonCancel),
      );
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(kGithubReviewButtonKey));
      await tester.pumpAndSettle();

      expect(
        tester
            .widget<FilledButton>(find.byKey(kGithubCommitButtonKey))
            .onPressed,
        isNull,
      );
      expect(api.fetchedRemotePaths, <String>['hello.py']);

      await tester.pump(const Duration(seconds: 60));
      expect(
        tester
            .widget<FilledButton>(find.byKey(kGithubCommitButtonKey))
            .onPressed,
        isNotNull,
      );
    });

    testWidgets('folder navigation cannot bypass a retry deadline', (
      WidgetTester tester,
    ) async {
      final RecordingConnection connection = RecordingConnection(
        initial: ConnState.ready,
      );
      final _FakeGithubApi api = _FakeGithubApi(
        childListFailure: const GithubFailure(
          GithubFailureKind.rateLimited,
          retryAfter: Duration(seconds: 60),
        ),
      );
      addTearDown(connection.dispose);

      await _openImport(tester, connection, api);
      await _browse(tester);
      await tester.tap(find.byKey(_entryKey('nested')));
      await tester.pumpAndSettle();
      expect(api.listedRemotePaths, <String>['', 'nested']);

      await tester.tap(find.byKey(_entryKey('nested')));
      await tester.pumpAndSettle();
      expect(api.listedRemotePaths, <String>['', 'nested']);

      await tester.pump(const Duration(seconds: 60));
      await tester.tap(find.byKey(_entryKey('nested')));
      await tester.pumpAndSettle();
      expect(api.listedRemotePaths, <String>['', 'nested', 'nested']);
    });

    testWidgets('board target review has a distinct visible phase', (
      WidgetTester tester,
    ) async {
      final _HoldingReviewConnection connection = _HoldingReviewConnection();
      final _FakeGithubApi api = _FakeGithubApi(
        entries: const <GithubEntry>[_helloEntry],
      );
      addTearDown(() async {
        if (!connection.releaseList.isCompleted) {
          connection.releaseList.complete();
        }
        await connection.dispose();
      });

      await _openImport(tester, connection, api);
      await _browse(tester);
      await _toggleSelection(tester, 'hello.py');
      await tester.tap(find.byKey(kGithubReviewButtonKey));
      await connection.listStarted.future;
      await tester.pump();

      expect(find.text('Checking board targets…'), findsOneWidget);

      connection.releaseList.complete();
      await tester.pumpAndSettle();
      expect(find.byKey(kGithubCommitButtonKey), findsOneWidget);
      expect(find.byKey(kGithubRootDestinationWarningKey), findsOneWidget);
    });

    testWidgets(
      'root guide blocks a protected example target before board or blob I/O',
      (WidgetTester tester) async {
        final _CountingReviewConnection connection =
            _CountingReviewConnection();
        final _FakeGithubApi api = _FakeGithubApi(
          entries: const <GithubEntry>[_protectedExampleEntry],
          sourceByRemotePath: const <String, String>{
            'pyble_i2c_scan.py': 'print("scan")\n',
          },
        );
        addTearDown(connection.dispose);

        await _openImport(tester, connection, api);
        final AppLocalizations l10n = l10nOf(tester);
        expect(find.byKey(kGithubRootDestinationWarningKey), findsOneWidget);
        expect(
          find.text(l10n.githubImportRootDestinationWarning('/examples')),
          findsOneWidget,
        );

        await _browse(tester);
        final Finder selection = find.byKey(_selectionKey('pyble_i2c_scan.py'));
        await _toggleSelection(tester, 'pyble_i2c_scan.py');
        await tester.tap(find.byKey(kGithubReviewButtonKey));
        await tester.pumpAndSettle();

        expect(
          find.text(
            l10n.githubImportErrorProtectedRootTarget(
              '/pyble_i2c_scan.py',
              '/examples',
            ),
          ),
          findsOneWidget,
        );
        expect(tester.widget<CheckboxListTile>(selection).value, isTrue);
        expect(find.byKey(kGithubRootDestinationWarningKey), findsNothing);
        expect(find.text(l10n.githubImportRetry), findsNothing);
        expect(find.byKey(kGithubCommitButtonKey), findsNothing);
        expect(
          tester
              .widget<FilledButton>(find.byKey(kGithubReviewButtonKey))
              .onPressed,
          isNull,
        );
        final Finder failure = find.byKey(
          const ValueKey<String>('githubImportFailure'),
        );
        expect(tester.widget<Focus>(failure).focusNode?.hasFocus, isTrue);
        expect(
          tester.getSemantics(failure),
          matchesSemantics(
            isLiveRegion: true,
            isFocusable: true,
            isFocused: true,
            hasFocusAction: true,
          ),
        );
        expect(connection.importerListCalls, 0);
        expect(api.fetchedRemotePaths, isEmpty);
        expect(connection.putFileCalls, isEmpty);
        expect(connection.mkdirCalls, isEmpty);
        expect(connection.runFileCalls, isEmpty);
        expect(connection.runSourceCalls, isEmpty);
      },
    );

    testWidgets(
      'a reported non-slash root guides to and imports from its child folder',
      (WidgetTester tester) async {
        const DeviceInfo info = DeviceInfo(
          chip: 'future-port',
          mpyVersion: '1.28.0',
          freeMem: 48000,
          fsRoot: '/flash',
        );
        final RecordingConnection connection = RecordingConnection(
          initial: ConnState.ready,
          deviceInfo: info,
        );
        final _FakeGithubApi api = _FakeGithubApi(
          entries: const <GithubEntry>[_protectedExampleEntry],
          sourceByRemotePath: const <String, String>{
            'pyble_i2c_scan.py': 'print("scan")\n',
          },
        );
        addTearDown(connection.dispose);
        await connection.mkdir('/flash/examples');
        connection.mkdirCalls.clear();
        connection.operationLog.clear();

        await _openImport(tester, connection, api);
        final AppLocalizations l10n = l10nOf(tester);
        expect(
          find.text(l10n.githubImportRootDestinationWarning('/flash/examples')),
          findsOneWidget,
        );
        await tester.tap(find.byTooltip(l10n.githubImportClose));
        await tester.pumpAndSettle();

        await tester.tap(
          find.byKey(const ValueKey<String>('fileEntry_examples')),
        );
        await tester.pumpAndSettle();
        await tester.tap(find.byTooltip(l10n.githubImportAction));
        await tester.pumpAndSettle();
        expect(find.byKey(kGithubRootDestinationWarningKey), findsNothing);

        await _browse(tester);
        await _toggleSelection(tester, 'pyble_i2c_scan.py');
        await tester.tap(find.byKey(kGithubReviewButtonKey));
        await tester.pumpAndSettle();
        expect(
          find.textContaining('/flash/examples/pyble_i2c_scan.py'),
          findsOneWidget,
        );
        await tester.tap(find.byKey(kGithubCommitButtonKey));
        await tester.pumpAndSettle();

        expect(
          connection.putFileCalls.map((PutFileCall call) => call.path),
          <String>['/flash/examples/pyble_i2c_scan.py'],
        );
        expect(connection.mkdirCalls, isEmpty);
        expect(connection.runFileCalls, isEmpty);
        expect(connection.runSourceCalls, isEmpty);
      },
    );

    testWidgets('review marks an existing regular-file target before consent', (
      WidgetTester tester,
    ) async {
      final RecordingConnection connection = RecordingConnection(
        initial: ConnState.ready,
      );
      final _FakeGithubApi api = _FakeGithubApi(
        entries: const <GithubEntry>[_helloEntry],
      );
      addTearDown(connection.dispose);
      await connection.putFile(
        '/hello.py',
        Uint8List.fromList(utf8.encode('print(0)\n')),
      );

      await _openImport(tester, connection, api);
      await _browse(tester);
      await _toggleSelection(tester, 'hello.py');
      await tester.tap(find.byKey(kGithubReviewButtonKey));
      await tester.pumpAndSettle();

      expect(
        find.text(l10nOf(tester).githubImportWillOverwrite),
        findsOneWidget,
      );
      expect(find.textContaining('/hello.py'), findsOneWidget);
    });
  });
}

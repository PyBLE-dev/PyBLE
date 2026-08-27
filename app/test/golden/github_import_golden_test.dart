// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.
//
// A-33 connected subset — deterministic visual coverage for the adaptive,
// SHA-pinned public GitHub importer. Every repository response is an authored
// in-memory fixture and every board operation crosses the Connection seam.

import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:pyble/app/providers.dart';
import 'package:pyble/files/files.dart';
import 'package:pyble/github_import/github_import.dart';
import 'package:pyble/localization/localization.dart';
import 'package:pyble/pble/pble.dart';
import 'package:pyble/theme/theme.dart';

import '../support/recording_connection.dart';

const String _commitSha = '1111111111111111111111111111111111111111';
const String _rootTreeSha = '2222222222222222222222222222222222222222';
const String _folderTreeSha = '3333333333333333333333333333333333333333';

const GithubEntry _folderEntry = GithubEntry(
  name: 'examples',
  remotePath: 'examples',
  kind: GithubEntryKind.directory,
  objectSha: _folderTreeSha,
  declaredSize: 0,
);

const GithubEntry _alphaEntry = GithubEntry(
  name: 'alpha.py',
  remotePath: 'alpha.py',
  kind: GithubEntryKind.regularFile,
  objectSha: '4444444444444444444444444444444444444444',
  declaredSize: 17,
);

const GithubEntry _betaEntry = GithubEntry(
  name: 'beta.py',
  remotePath: 'beta.py',
  kind: GithubEntryKind.regularFile,
  objectSha: '5555555555555555555555555555555555555555',
  declaredSize: 16,
);

const GithubEntry _gammaEntry = GithubEntry(
  name: 'gamma.py',
  remotePath: 'gamma.py',
  kind: GithubEntryKind.regularFile,
  objectSha: '6666666666666666666666666666666666666666',
  declaredSize: 17,
);

const GithubEntry _notesEntry = GithubEntry(
  name: 'NOTES.md',
  remotePath: 'NOTES.md',
  kind: GithubEntryKind.regularFile,
  objectSha: '7777777777777777777777777777777777777777',
  declaredSize: 10,
);

const GithubEntry _protectedExampleEntry = GithubEntry(
  name: 'pyble_i2c_scan.py',
  remotePath: 'pyble_i2c_scan.py',
  kind: GithubEntryKind.regularFile,
  objectSha: '8888888888888888888888888888888888888888',
  declaredSize: 14,
);

final class _GoldenGithubApi implements GithubApi {
  _GoldenGithubApi({
    this.branchFailure,
    this.childListGate,
    this.entries = _defaultEntries,
  });

  final GithubFailure? branchFailure;
  final Completer<void>? childListGate;
  final List<GithubEntry> entries;

  static const List<GithubEntry> _defaultEntries = <GithubEntry>[
    _folderEntry,
    _alphaEntry,
    _betaEntry,
    _gammaEntry,
    _notesEntry,
  ];

  static final Map<String, Uint8List> _bytesByPath = <String, Uint8List>{
    'alpha.py': Uint8List.fromList(utf8.encode("print('alpha')\n")),
    'beta.py': Uint8List.fromList(utf8.encode("print('beta')\n")),
    'gamma.py': Uint8List.fromList(utf8.encode("print('gamma')\n")),
    'pyble_i2c_scan.py': Uint8List.fromList(utf8.encode('print("scan")\n')),
  };

  @override
  Future<GithubBranchCatalog> listBranches(
    RepositoryLocator locator, {
    GithubCancellation? cancellation,
  }) async {
    if (branchFailure case final GithubFailure failure) throw failure;
    if (cancellation?.isCancelled ?? false) {
      throw const GithubFailure(GithubFailureKind.cancelled);
    }
    return GithubBranchCatalog(
      locator: locator,
      defaultBranch: 'main',
      branches: const <String>['main', 'release/v1'],
    );
  }

  @override
  Future<PinnedRepository> resolve(
    RepositoryLocator locator, {
    String ref = '',
    GithubCancellation? cancellation,
  }) async {
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
    if (remotePath.isNotEmpty && childListGate != null) {
      await childListGate!.future;
    }
    if (cancellation?.isCancelled ?? false) {
      throw const GithubFailure(GithubFailureKind.cancelled);
    }
    return GithubDirectory(
      treeSha: treeSha,
      remotePath: remotePath,
      entries: remotePath.isEmpty ? entries : const <GithubEntry>[],
    );
  }

  @override
  Future<Uint8List> fetchFile(
    PinnedRepository repository,
    GithubEntry entry, {
    GithubCancellation? cancellation,
  }) async {
    if (cancellation?.isCancelled ?? false) {
      throw const GithubFailure(GithubFailureKind.cancelled);
    }
    return Uint8List.fromList(_bytesByPath[entry.remotePath]!);
  }
}

final class _SecondPutFailsConnection extends RecordingConnection {
  _SecondPutFailsConnection() : super(initial: ConnState.ready);

  int _putCount = 0;

  @override
  Future<void> putFile(
    String path,
    Uint8List bytes, {
    ProgressCb? onProgress,
  }) async {
    _putCount += 1;
    if (_putCount == 2) {
      injectError(const EIo('deterministic golden fixture failure'));
    }
    await super.putFile(path, bytes, onProgress: onProgress);
  }
}

final class _GateablePutConnection extends RecordingConnection {
  _GateablePutConnection() : super(initial: ConnState.ready);

  bool holdNextPut = false;
  final Completer<void> putStarted = Completer<void>();
  final Completer<void> releasePut = Completer<void>();

  @override
  Future<void> putFile(
    String path,
    Uint8List bytes, {
    ProgressCb? onProgress,
  }) async {
    if (holdNextPut) {
      holdNextPut = false;
      if (!putStarted.isCompleted) putStarted.complete();
      await releasePut.future;
    }
    await super.putFile(path, bytes, onProgress: onProgress);
  }
}

Future<void> _pumpGoldenHost(
  WidgetTester tester, {
  required RecordingConnection connection,
  required GithubApi api,
  required Size size,
  double textScale = 1,
  bool highContrast = false,
}) async {
  tester.view.devicePixelRatio = 2;
  tester.view.physicalSize = size * 2;
  tester.view.viewInsets = const FakeViewPadding();
  addTearDown(tester.view.resetDevicePixelRatio);
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetViewInsets);

  await tester.pumpWidget(
    ProviderScope(
      overrides: <Override>[
        connectionProvider.overrideWithValue(connection),
        githubApiProvider.overrideWithValue(api),
      ],
      child: MaterialApp(
        localizationsDelegates: AppLocalizations.localizationsDelegates,
        supportedLocales: AppLocalizations.supportedLocales,
        theme: highContrast ? PybleTheme.highContrastLight : PybleTheme.light,
        highContrastTheme: PybleTheme.highContrastLight,
        builder: (BuildContext context, Widget? child) {
          final MediaQueryData media = MediaQuery.of(context);
          return MediaQuery(
            data: media.copyWith(
              highContrast: highContrast,
              textScaler: TextScaler.linear(textScale),
            ),
            child: child!,
          );
        },
        home: const Scaffold(body: FilesView()),
      ),
    ),
  );
  await tester.pumpAndSettle();
}

AppLocalizations _l10n(WidgetTester tester) =>
    AppLocalizations.of(tester.element(find.byType(Scaffold).first));

Future<void> _openImporter(WidgetTester tester) async {
  await tester.tap(find.byTooltip(_l10n(tester).githubImportAction));
  await tester.pumpAndSettle();
}

Future<void> _browseRepository(WidgetTester tester) async {
  expect(
    tester
        .widget<TextField>(find.byKey(kGithubRepositoryFieldKey))
        .controller
        ?.text,
    kOfficialExamplesRepositoryUrl,
  );
  expect(find.byKey(kGithubBranchDropdownKey), findsOneWidget);
  await tester.tap(find.byKey(kGithubBrowseButtonKey));
  await tester.pumpAndSettle();
}

Future<void> _selectFiles(
  WidgetTester tester,
  Iterable<String> remotePaths,
) async {
  for (final String remotePath in remotePaths) {
    final Finder selection = find.byKey(
      ValueKey<String>('githubSelect_$remotePath'),
    );
    await tester.ensureVisible(selection);
    await tester.pumpAndSettle();
    await tester.tap(selection);
  }
  await tester.pump();
}

Future<void> _expectGolden(WidgetTester tester, String name) => expectLater(
  find.byType(MaterialApp),
  matchesGoldenFile('goldens/$name.png'),
);

void main() {
  group('A-33 GitHub import adaptive goldens', () {
    testWidgets(
      'wide dialog starts with the editable official repository and default branch',
      (WidgetTester tester) async {
        final RecordingConnection connection = RecordingConnection(
          initial: ConnState.ready,
        );
        final _GoldenGithubApi api = _GoldenGithubApi();
        addTearDown(connection.dispose);

        await _pumpGoldenHost(
          tester,
          connection: connection,
          api: api,
          size: const Size(1024, 768),
        );
        await _openImporter(tester);

        final TextField repositoryField = tester.widget<TextField>(
          find.byKey(kGithubRepositoryFieldKey),
        );
        expect(
          repositoryField.controller?.text,
          kOfficialExamplesRepositoryUrl,
        );
        expect(repositoryField.enabled, isNot(false));
        expect(find.byKey(kGithubBranchDropdownKey), findsOneWidget);
        await tester.tap(find.byKey(kGithubBranchDropdownKey));
        await tester.pumpAndSettle();
        expect(find.textContaining('main'), findsWidgets);
        expect(find.text('release/v1'), findsOneWidget);
        expect(connection.putFileCalls, isEmpty);
        expect(connection.runFileCalls, isEmpty);
        expect(connection.runSourceCalls, isEmpty);
        await _expectGolden(tester, 'github_import_wide_branch_chooser');
      },
      tags: const <String>['golden'],
    );

    testWidgets(
      'wide dialog retains context while a child folder loads',
      (WidgetTester tester) async {
        final RecordingConnection connection = RecordingConnection(
          initial: ConnState.ready,
        );
        final Completer<void> childGate = Completer<void>();
        final _GoldenGithubApi api = _GoldenGithubApi(childListGate: childGate);
        addTearDown(connection.dispose);
        addTearDown(() {
          if (!childGate.isCompleted) childGate.complete();
        });

        await _pumpGoldenHost(
          tester,
          connection: connection,
          api: api,
          size: const Size(1024, 768),
        );
        await _openImporter(tester);
        await _browseRepository(tester);
        await _selectFiles(tester, const <String>['alpha.py']);
        await tester.tap(
          find.byKey(const ValueKey<String>('githubEntry_examples')),
        );
        FocusManager.instance.primaryFocus?.unfocus();
        await tester.pump(const Duration(milliseconds: 240));

        expect(find.byType(Dialog), findsOneWidget);
        expect(
          find.text(_l10n(tester).githubImportLoadingFolder),
          findsOneWidget,
        );
        expect(
          tester
              .widget<CheckboxListTile>(
                find.byKey(const ValueKey<String>('githubSelect_alpha.py')),
              )
              .value,
          isTrue,
        );
        await _expectGolden(tester, 'github_import_wide_folder_loading');

        childGate.complete();
        await tester.pumpAndSettle();
      },
      tags: const <String>['golden'],
    );

    testWidgets(
      'wide dialog previews exact board targets for review',
      (WidgetTester tester) async {
        final RecordingConnection connection = RecordingConnection(
          initial: ConnState.ready,
        );
        final _GoldenGithubApi api = _GoldenGithubApi();
        addTearDown(connection.dispose);

        await _pumpGoldenHost(
          tester,
          connection: connection,
          api: api,
          size: const Size(1024, 768),
        );
        await _openImporter(tester);
        await _browseRepository(tester);
        await _selectFiles(tester, const <String>['alpha.py', 'gamma.py']);
        await tester.tap(find.byKey(kGithubReviewButtonKey));
        await tester.pumpAndSettle();

        expect(find.byType(Dialog), findsOneWidget);
        expect(
          find.text(_l10n(tester).githubImportReviewTitle),
          findsOneWidget,
        );
        expect(find.textContaining('/alpha.py'), findsOneWidget);
        expect(find.textContaining('/gamma.py'), findsOneWidget);
        await _expectGolden(tester, 'github_import_wide_review');
      },
      tags: const <String>['golden'],
    );

    testWidgets(
      'wide dialog distinguishes an honest partial board result',
      (WidgetTester tester) async {
        final _SecondPutFailsConnection connection =
            _SecondPutFailsConnection();
        final _GoldenGithubApi api = _GoldenGithubApi();
        addTearDown(connection.dispose);

        await _pumpGoldenHost(
          tester,
          connection: connection,
          api: api,
          size: const Size(1024, 768),
        );
        await _openImporter(tester);
        await _browseRepository(tester);
        await _selectFiles(tester, const <String>[
          'alpha.py',
          'beta.py',
          'gamma.py',
        ]);
        await tester.tap(find.byKey(kGithubReviewButtonKey));
        await tester.pumpAndSettle();
        await tester.tap(find.byKey(kGithubCommitButtonKey));
        await tester.pumpAndSettle();

        expect(
          find.byKey(const ValueKey<String>('githubImportResult')),
          findsOneWidget,
        );
        expect(
          find.text(_l10n(tester).githubImportSucceededHeading),
          findsOneWidget,
        );
        expect(
          find.text(_l10n(tester).githubImportFailedHeading),
          findsOneWidget,
        );
        expect(
          find.text(_l10n(tester).githubImportUnattemptedHeading),
          findsOneWidget,
        );
        await _expectGolden(tester, 'github_import_wide_partial');
      },
      tags: const <String>['golden'],
    );

    testWidgets(
      'compact rate-limit error survives 2x text, high contrast, and keyboard inset',
      (WidgetTester tester) async {
        final RecordingConnection connection = RecordingConnection(
          initial: ConnState.ready,
        );
        final _GoldenGithubApi api = _GoldenGithubApi(
          branchFailure: const GithubFailure(
            GithubFailureKind.rateLimited,
            rateLimitRemaining: 0,
            retryAfter: Duration(seconds: 120),
          ),
        );
        addTearDown(connection.dispose);

        await _pumpGoldenHost(
          tester,
          connection: connection,
          api: api,
          size: const Size(599, 1024),
          textScale: 2,
          highContrast: true,
        );
        await _openImporter(tester);
        tester.view.viewInsets = const FakeViewPadding(bottom: 440);
        await tester.pumpAndSettle();

        expect(find.byType(BottomSheet), findsOneWidget);
        expect(find.byType(Dialog), findsNothing);
        expect(find.textContaining('120'), findsOneWidget);
        expect(find.text(_l10n(tester).githubImportRetry), findsNothing);
        expect(
          tester
              .widget<FilledButton>(find.byKey(kGithubBrowseButtonKey))
              .onPressed,
          isNull,
        );
        expect(
          find.byKey(const ValueKey<String>('githubImportFailure')),
          findsOneWidget,
        );
        await _expectGolden(
          tester,
          'github_import_compact_rate_limit_a11y_keyboard',
        );
      },
      tags: const <String>['golden'],
    );

    testWidgets(
      'compact root guide explains a protected official example target',
      (WidgetTester tester) async {
        final RecordingConnection connection = RecordingConnection(
          initial: ConnState.ready,
        );
        final _GoldenGithubApi api = _GoldenGithubApi(
          entries: const <GithubEntry>[_protectedExampleEntry],
        );
        addTearDown(connection.dispose);

        await _pumpGoldenHost(
          tester,
          connection: connection,
          api: api,
          size: const Size(599, 768),
        );
        await _openImporter(tester);
        expect(find.byKey(kGithubRootDestinationWarningKey), findsOneWidget);
        await _browseRepository(tester);
        await _selectFiles(tester, const <String>['pyble_i2c_scan.py']);
        await tester.tap(find.byKey(kGithubReviewButtonKey));
        await tester.pumpAndSettle();

        expect(find.byType(BottomSheet), findsOneWidget);
        expect(
          find.text(
            _l10n(
              tester,
            ).githubImportErrorProtectedRootTarget('/pyble_i2c_scan.py'),
          ),
          findsOneWidget,
        );
        expect(find.text(_l10n(tester).githubImportRetry), findsNothing);
        expect(connection.putFileCalls, isEmpty);
        await _expectGolden(tester, 'github_import_compact_protected_root');
      },
      tags: const <String>['golden'],
    );

    testWidgets(
      'wide portrait shows an empty pinned repository folder',
      (WidgetTester tester) async {
        final RecordingConnection connection = RecordingConnection(
          initial: ConnState.ready,
        );
        final _GoldenGithubApi api = _GoldenGithubApi(
          entries: const <GithubEntry>[],
        );
        addTearDown(connection.dispose);

        await _pumpGoldenHost(
          tester,
          connection: connection,
          api: api,
          size: const Size(768, 1024),
        );
        await _openImporter(tester);
        await _browseRepository(tester);
        FocusManager.instance.primaryFocus?.unfocus();
        await tester.pump();

        expect(find.byType(Dialog), findsOneWidget);
        expect(
          find.text(_l10n(tester).githubImportEmptyFolder),
          findsOneWidget,
        );
        await _expectGolden(tester, 'github_import_wide_portrait_empty');
      },
      tags: const <String>['golden'],
    );

    testWidgets(
      'compact landscape shows canonical URL validation',
      (WidgetTester tester) async {
        final RecordingConnection connection = RecordingConnection(
          initial: ConnState.ready,
        );
        final _GoldenGithubApi api = _GoldenGithubApi();
        addTearDown(connection.dispose);

        await _pumpGoldenHost(
          tester,
          connection: connection,
          api: api,
          size: const Size(599, 430),
        );
        await _openImporter(tester);
        await tester.enterText(
          find.byKey(kGithubRepositoryFieldKey),
          'https://github.com/PyBLE-dev/PyBLE/tree/main',
        );
        await tester.tap(find.byKey(kGithubLoadBranchesButtonKey));
        await tester.pumpAndSettle();

        expect(find.byType(BottomSheet), findsOneWidget);
        final Finder inlineValidation = find.descendant(
          of: find.byKey(kGithubRepositoryFieldKey),
          matching: find.text(_l10n(tester).githubImportErrorInvalidInput),
        );
        expect(inlineValidation, findsOneWidget);
        expect(inlineValidation.hitTestable(), findsOneWidget);
        expect(
          find.byKey(const ValueKey<String>('githubImportFailure')),
          findsOneWidget,
        );
        await _expectGolden(
          tester,
          'github_import_compact_landscape_validation',
        );
      },
      tags: const <String>['golden'],
    );

    testWidgets(
      'wide conflict lifecycle shows overwrite, upload, and complete states',
      (WidgetTester tester) async {
        final _GateablePutConnection connection = _GateablePutConnection();
        final _GoldenGithubApi api = _GoldenGithubApi(
          entries: const <GithubEntry>[_alphaEntry],
        );
        addTearDown(() async {
          if (!connection.releasePut.isCompleted) {
            connection.releasePut.complete();
          }
          await connection.dispose();
        });
        await connection.putFile(
          '/alpha.py',
          Uint8List.fromList(utf8.encode("print('old')\n")),
        );
        connection.putFileCalls.clear();
        connection.operationLog.clear();

        await _pumpGoldenHost(
          tester,
          connection: connection,
          api: api,
          size: const Size(1024, 768),
        );
        await _openImporter(tester);
        await _browseRepository(tester);
        await _selectFiles(tester, const <String>['alpha.py']);
        await tester.tap(find.byKey(kGithubReviewButtonKey));
        await tester.pumpAndSettle();
        await tester.tap(find.byKey(kGithubCommitButtonKey));
        await tester.pumpAndSettle();

        expect(find.byType(AlertDialog), findsOneWidget);
        expect(
          find.text(_l10n(tester).githubImportOverwriteTitle),
          findsOneWidget,
        );
        await _expectGolden(
          tester,
          'github_import_wide_overwrite_confirmation',
        );

        connection.holdNextPut = true;
        await tester.tap(find.text(_l10n(tester).githubImportOverwrite));
        await connection.putStarted.future;
        await tester.pump(const Duration(milliseconds: 240));

        expect(find.text(_l10n(tester).githubImportUploading), findsOneWidget);
        await _expectGolden(tester, 'github_import_wide_uploading');

        connection.releasePut.complete();
        await tester.pumpAndSettle();
        expect(
          find.text(_l10n(tester).githubImportComplete(1)),
          findsOneWidget,
        );
        expect(
          find.byKey(const ValueKey<String>('githubImportResult')),
          findsOneWidget,
        );
        await _expectGolden(tester, 'github_import_wide_complete');
      },
      tags: const <String>['golden'],
    );
  });
}

// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.
//
// A-30 [red] — the FilesView: a real board file explorer over the Connection
// file verbs (ADR-0010, TDD §11.6d, specs.md FR-FILES §4.5). Lists fsRoot with
// into/up navigation; open-in-editor (getFile -> editor buffer), upload-current-
// buffer (putFile), mkdir, delete, rename — each with typed-error -> localized
// message; disabled with guidance while disconnected. Binds through the seam
// ONLY (CON-8); the files -> editor cross-import is app-layer, allowed.
//
// Interactive keys the FilesView MUST expose (widget tests + HIL), mirroring the
// ConnectScreen key-contract precedent:
//   ValueKey('fileEntry_<name>')  — a listing row; tap = into (dir) / open (file)
//   ValueKey('fileDelete_<name>') — the row's delete affordance
//   ValueKey('fileRename_<name>') — the row's rename affordance
//   ValueKey('fileSelect_<name>') — an eligible file's selection checkbox
// Top actions are found by their localized tooltips (filesActionRefresh /
// filesActionUpload / filesActionNewFolder / filesGoUp).
//
// CURRENTLY RED: lib/files exports no FilesView. HAND-OFF:
// lib/files/files_view.dart -> app-files-engineer.

import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:pyble/app/providers.dart';
import 'package:pyble/editor/editor.dart';
import 'package:pyble/files/files.dart';
import 'package:pyble/localization/localization.dart';
import 'package:pyble/pble/pble.dart';

import '../support/feature_harness.dart';
import '../support/recording_connection.dart';

const Key _normalActionsRowKey = ValueKey<String>('filesNormalActionsRow');
const Key _actionsOverflowKey = ValueKey<String>('filesActionsOverflowButton');
const Key _overflowRefreshKey = ValueKey<String>('filesOverflowRefresh');
const Key _overflowNewFileKey = ValueKey<String>('filesOverflowNewFile');
const Key _overflowNewFolderKey = ValueKey<String>('filesOverflowNewFolder');
const Key _overflowUploadKey = ValueKey<String>('filesOverflowUpload');

/// Records a deterministic fail-fast boundary without changing the shared
/// connection test double. Files before [failPath] delete normally; that path
/// records its attempted verb and fails, so later files must remain untouched.
class _FailingDeleteConnection extends RecordingConnection {
  _FailingDeleteConnection({required this.failPath})
    : super(initial: ConnState.ready);

  final String failPath;

  @override
  Future<void> delete(String path) {
    if (path == failPath) {
      deleteCalls.add(path);
      return Future<void>.error(const EIo('scripted bulk-delete failure'));
    }
    return super.delete(path);
  }
}

/// Holds one delete so the shell navigation provider can change while the
/// non-cancellable PBLE/1 mutation remains in flight.
class _HeldDeleteConnection extends RecordingConnection {
  _HeldDeleteConnection() : super(initial: ConnState.ready);

  final Completer<void> started = Completer<void>();
  final Completer<void> release = Completer<void>();

  @override
  Future<void> delete(String path) async {
    if (!started.isCompleted) started.complete();
    await release.future;
    await super.delete(path);
  }
}

/// Simulates a file disappearing before the board reports ENOENT. Reconciliation
/// must not leave that absent row counted as a selected, retryable ghost.
class _DisappearingDeleteConnection extends RecordingConnection {
  _DisappearingDeleteConnection() : super(initial: ConnState.ready);

  @override
  Future<void> delete(String path) async {
    await super.delete(path);
    throw const ENoEnt('scripted file disappeared before delete');
  }
}

/// Holds exactly one requested listing while leaving the previous rows visible.
class _HeldListConnection extends RecordingConnection {
  _HeldListConnection() : super(initial: ConnState.ready);

  Completer<void> listStarted = Completer<void>();
  Completer<void> releaseList = Completer<void>();
  bool _holdNext = false;

  void holdNextList() {
    listStarted = Completer<void>();
    releaseList = Completer<void>();
    _holdNext = true;
  }

  @override
  Future<List<RemoteEntry>> listDir(String path) async {
    if (_holdNext) {
      _holdNext = false;
      listStarted.complete();
      await releaseList.future;
    }
    return super.listDir(path);
  }
}

void main() {
  Uint8List b(String s) => Uint8List.fromList(utf8.encode(s));
  Key entryKey(String n) => ValueKey<String>('fileEntry_$n');
  Key selectKey(String n) => ValueKey<String>('fileSelect_$n');
  Key deleteKey(String n) => ValueKey<String>('fileDelete_$n');
  Key renameKey(String n) => ValueKey<String>('fileRename_$n');
  Key moreKey(String n) => ValueKey<String>('fileMore_$n');
  Key blocksKey(String n) => ValueKey<String>('fileOpenBlocks_$n');

  bool primaryFocusIsWithin(WidgetTester tester, Finder finder) {
    final BuildContext? focused = FocusManager.instance.primaryFocus?.context;
    if (focused == null) return false;
    final Element target = tester.element(finder);
    if (identical(focused, target)) return true;
    bool found = false;
    focused.visitAncestorElements((Element ancestor) {
      if (identical(ancestor, target)) {
        found = true;
        return false;
      }
      return true;
    });
    return found;
  }

  void expectTouchTarget(WidgetTester tester, Finder finder, String label) {
    final Size size = tester.getSize(finder);
    expect(
      size.width,
      greaterThanOrEqualTo(48),
      reason: '$label must retain a 48 dp minimum width',
    );
    expect(
      size.height,
      greaterThanOrEqualTo(48),
      reason: '$label must retain a 48 dp minimum height',
    );
  }

  void expectOneHorizontalLine(WidgetTester tester, List<Finder> actions) {
    final List<double> centers = actions
        .map((Finder action) => tester.getCenter(action).dy)
        .toList(growable: false);
    expect(
      centers.map((double center) => (center - centers.first).abs()),
      everyElement(lessThan(0.1)),
      reason: 'normal Files actions must share exactly one horizontal row',
    );
  }

  Future<void> enterSelection(WidgetTester tester) async {
    await tester.tap(find.byKey(kFilesSelectActionKey));
    await tester.pumpAndSettle();
  }

  Future<void> selectAllShown(WidgetTester tester) async {
    await tester.tap(find.byKey(kFilesSelectAllShownKey));
    await tester.pumpAndSettle();
  }

  group('A-30 FilesView — connected listing + navigation', () {
    testWidgets('exposes GitHub import only for a ready board session', (
      WidgetTester tester,
    ) async {
      final FakeConnection fake = FakeConnection(initial: ConnState.ready);
      addTearDown(fake.dispose);
      await pumpSurface(tester, const FilesView(), connection: fake);
      await tester.pumpAndSettle();

      Finder action = find.byTooltip(l10nOf(tester).githubImportAction);
      expect(action, findsOneWidget);
      Finder actionButton = find.ancestor(
        of: action,
        matching: find.byType(IconButton),
      );
      expect(actionButton, findsOneWidget);
      expect(tester.widget<IconButton>(actionButton).onPressed, isNotNull);

      fake.emitRunState(RunState.running);
      await tester.pump();
      expect(find.byTooltip(l10nOf(tester).githubImportAction), findsNothing);
      action = find.byTooltip(l10nOf(tester).githubImportRequiresReady);
      expect(action, findsOneWidget);
      actionButton = find.ancestor(
        of: action,
        matching: find.byType(IconButton),
      );
      expect(
        tester.widget<IconButton>(actionButton).onPressed,
        isNull,
        reason: 'a running board cannot accept import PUTs',
      );
    });

    testWidgets(
      'compact toolbar keeps Select and GitHub direct on one action row',
      (WidgetTester tester) async {
        final RecordingConnection rec = RecordingConnection(
          initial: ConnState.ready,
        );
        addTearDown(rec.dispose);
        await rec.putFile('/alpha.py', b('print("alpha")\n'));
        await pumpSurface(
          tester,
          const FilesView(),
          connection: rec,
          size: const Size(252, 568),
        );
        await tester.pumpAndSettle();
        final AppLocalizations l10n = l10nOf(tester);

        final Finder select = find.byTooltip(l10n.filesActionSelect);
        final Finder github = find.byTooltip(l10n.githubImportAction);
        final Finder overflow = find.byKey(_actionsOverflowKey);
        expect(find.byKey(_normalActionsRowKey), findsOneWidget);
        expect(select, findsOneWidget);
        expect(github, findsOneWidget);
        expect(overflow, findsOneWidget);
        expect(find.byTooltip(l10n.filesActionRefresh), findsNothing);
        expect(find.byTooltip(l10n.filesEmptyCta), findsNothing);
        expect(find.byTooltip(l10n.filesActionNewFolder), findsNothing);
        expect(find.byTooltip(l10n.filesActionUpload), findsNothing);
        expectOneHorizontalLine(tester, <Finder>[select, github, overflow]);
        expect(tester.getSize(find.byKey(_normalActionsRowKey)).height, 48);
        expectTouchTarget(tester, select, 'compact Select');
        expectTouchTarget(tester, github, 'compact GitHub import');
        expectTouchTarget(tester, overflow, 'compact overflow');
        expect(tester.getSemantics(overflow).label, l10n.filesMoreActions);
        expect(tester.takeException(), isNull);
      },
    );

    testWidgets(
      'compact overflow labels and routes every lower-frequency action',
      (WidgetTester tester) async {
        final _HeldListConnection rec = _HeldListConnection();
        addTearDown(() async {
          if (!rec.releaseList.isCompleted) rec.releaseList.complete();
          await rec.dispose();
        });
        await rec.putFile('/alpha.py', b('a\n'));
        await pumpSurface(
          tester,
          const FilesView(),
          connection: rec,
          size: const Size(252, 568),
        );
        await tester.pumpAndSettle();
        final AppLocalizations l10n = l10nOf(tester);

        await tester.tap(find.byKey(_actionsOverflowKey));
        await tester.pumpAndSettle();

        for (final (Key key, String label) in <(Key, String)>[
          (_overflowRefreshKey, l10n.filesActionRefresh),
          (_overflowNewFileKey, l10n.filesEmptyCta),
          (_overflowNewFolderKey, l10n.filesActionNewFolder),
          (_overflowUploadKey, l10n.filesActionUpload),
        ]) {
          final Finder item = find.byKey(key);
          expect(item, findsOneWidget);
          expect(
            find.descendant(of: item, matching: find.text(label)),
            findsOneWidget,
          );
          expectTouchTarget(tester, item, label);
        }

        rec.holdNextList();
        await tester.tap(find.byKey(_overflowRefreshKey));
        await rec.listStarted.future;
        expect(find.byKey(_actionsOverflowKey), findsOneWidget);
        rec.releaseList.complete();
        await tester.pumpAndSettle();
        expect(tester.takeException(), isNull);
      },
    );

    testWidgets('roomy toolbar exposes all six actions on one row', (
      WidgetTester tester,
    ) async {
      final RecordingConnection rec = RecordingConnection(
        initial: ConnState.ready,
      );
      addTearDown(rec.dispose);
      await rec.putFile('/alpha.py', b('a\n'));
      await pumpSurface(
        tester,
        const FilesView(),
        connection: rec,
        size: const Size(600, 568),
      );
      await tester.pumpAndSettle();
      final AppLocalizations l10n = l10nOf(tester);
      final List<Finder> actions = <Finder>[
        find.byTooltip(l10n.filesActionSelect),
        find.byTooltip(l10n.filesActionRefresh),
        find.byTooltip(l10n.filesEmptyCta),
        find.byTooltip(l10n.filesActionNewFolder),
        find.byTooltip(l10n.filesActionUpload),
        find.byTooltip(l10n.githubImportAction),
      ];

      expect(find.byKey(_actionsOverflowKey), findsNothing);
      for (final Finder action in actions) {
        expect(action, findsOneWidget);
        expectTouchTarget(tester, action, 'roomy Files action');
      }
      expectOneHorizontalLine(tester, actions);
      expect(tester.getSize(find.byKey(_normalActionsRowKey)).height, 48);
      expect(tester.takeException(), isNull);
    });

    testWidgets('compact overflow remains usable at 2x text', (
      WidgetTester tester,
    ) async {
      tester.platformDispatcher.textScaleFactorTestValue = 2;
      addTearDown(tester.platformDispatcher.clearTextScaleFactorTestValue);
      final RecordingConnection rec = RecordingConnection(
        initial: ConnState.ready,
      );
      addTearDown(rec.dispose);
      await rec.putFile('/alpha.py', b('a\n'));
      await pumpSurface(
        tester,
        const FilesView(),
        connection: rec,
        size: const Size(252, 568),
      );
      await tester.pumpAndSettle();
      final AppLocalizations l10n = l10nOf(tester);

      await tester.tap(find.byKey(_actionsOverflowKey));
      await tester.pumpAndSettle();

      expect(find.text(l10n.filesActionRefresh), findsOneWidget);
      expect(find.text(l10n.filesEmptyCta), findsOneWidget);
      expect(find.text(l10n.filesActionNewFolder), findsOneWidget);
      expect(find.text(l10n.filesActionUpload), findsOneWidget);
      expect(tester.takeException(), isNull);
    });

    testWidgets('lists the fsRoot entries when connected', (
      WidgetTester tester,
    ) async {
      final FakeConnection fake = FakeConnection(initial: ConnState.ready);
      addTearDown(fake.dispose);
      await fake.putFile('/main.py', b('print(1)\n'));
      await fake.mkdir('/lib');
      await pumpSurface(tester, const FilesView(), connection: fake);
      await tester.pumpAndSettle();

      expect(find.textContaining('main.py'), findsWidgets);
      expect(find.textContaining('lib'), findsWidgets);
    });

    testWidgets('pull-to-refresh re-lists the current directory (FR-FILES-1)', (
      WidgetTester tester,
    ) async {
      final FakeConnection fake = FakeConnection(initial: ConnState.ready);
      addTearDown(fake.dispose);
      await fake.putFile('/main.py', b('print(1)\n'));
      await pumpSurface(tester, const FilesView(), connection: fake);
      await tester.pumpAndSettle();
      expect(find.textContaining('main.py'), findsWidgets);

      // A file appears on the board out-of-band (e.g. another writer); the
      // explorer has no push channel, so the user pulls to refresh.
      await fake.putFile('/added.py', b('print(2)\n'));
      expect(find.textContaining('added.py'), findsNothing);

      expect(find.byType(RefreshIndicator), findsOneWidget);
      await tester.fling(find.byType(ListView), const Offset(0, 300), 1000);
      await tester.pumpAndSettle();

      expect(
        find.textContaining('added.py'),
        findsWidgets,
        reason: 'the pull gesture re-lists the directory',
      );
    });

    testWidgets('tapping a folder navigates into it; Up returns', (
      WidgetTester tester,
    ) async {
      final FakeConnection fake = FakeConnection(initial: ConnState.ready);
      addTearDown(fake.dispose);
      await fake.mkdir('/lib');
      await fake.putFile('/lib/util.py', b('# util\n'));
      await pumpSurface(tester, const FilesView(), connection: fake);
      await tester.pumpAndSettle();

      await tester.tap(find.byKey(entryKey('lib')));
      await tester.pumpAndSettle();
      expect(find.textContaining('util.py'), findsWidgets);
      expect(containerOf(tester).read(fileExplorerProvider).cwd, '/lib');

      await tester.tap(find.byTooltip(l10nOf(tester).filesGoUp));
      await tester.pumpAndSettle();
      expect(containerOf(tester).read(fileExplorerProvider).cwd, '/');
    });

    testWidgets(
      'tapping a file opens it in the editor and focuses that surface',
      (WidgetTester tester) async {
        final FakeConnection fake = FakeConnection(initial: ConnState.ready);
        addTearDown(fake.dispose);
        await fake.putFile('/blink.py', b('led.on()\n'));
        await pumpSurface(tester, const FilesView(), connection: fake);
        await tester.pumpAndSettle();

        await tester.tap(find.byKey(entryKey('blink.py')));
        await tester.pumpAndSettle();

        final EditorDocument doc = containerOf(
          tester,
        ).read(editorDocumentProvider);
        expect(doc.content, 'led.on()\n');
        expect(doc.boardPath, '/blink.py');
        expect(
          containerOf(tester).read(selectedSurfaceProvider),
          AppSurface.editor,
        );
      },
    );

    testWidgets('Python rows expose an explicit Open as Blocks action', (
      WidgetTester tester,
    ) async {
      final FakeConnection fake = FakeConnection(initial: ConnState.ready);
      addTearDown(fake.dispose);
      await fake.putFile('/blink.py', b('print("blink")\n'));
      await fake.putFile('/notes.txt', b('notes\n'));
      await pumpSurface(tester, const FilesView(), connection: fake);
      await tester.pumpAndSettle();

      expect(find.byKey(blocksKey('blink.py')), findsOneWidget);
      expect(find.byTooltip(l10nOf(tester).filesOpenAsBlocks), findsOneWidget);
      expect(find.byKey(blocksKey('notes.txt')), findsNothing);
    });
  });

  group('A-30 FilesView — disconnected', () {
    testWidgets(
      'shows guidance and no destructive actions while disconnected',
      (WidgetTester tester) async {
        final FakeConnection fake = FakeConnection(
          initial: ConnState.disconnected,
        );
        addTearDown(fake.dispose);
        await pumpSurface(tester, const FilesView(), connection: fake);
        await tester.pump();
        final AppLocalizations l10n = l10nOf(tester);

        expect(find.text(l10n.filesDisconnectedTitle), findsOneWidget);
        expect(find.byTooltip(l10n.filesActionUpload), findsNothing);
        expect(find.byTooltip(l10n.filesActionRefresh), findsNothing);
        expect(find.byTooltip(l10n.githubImportAction), findsNothing);
      },
    );
  });

  group('A-30 FilesView — upload / mkdir / delete / rename', () {
    testWidgets('Upload writes the current buffer to the board', (
      WidgetTester tester,
    ) async {
      final RecordingConnection rec = RecordingConnection(
        initial: ConnState.ready,
      );
      addTearDown(rec.dispose);
      await pumpSurface(tester, const FilesView(), connection: rec);
      await tester.pumpAndSettle();

      containerOf(tester).read(editorDocumentProvider.notifier).newDocument();
      containerOf(
        tester,
      ).read(editorDocumentProvider.notifier).setContent('x = 1\n');

      await tester.tap(find.byTooltip(l10nOf(tester).filesActionUpload));
      await tester.pumpAndSettle();

      expect(rec.putFileCalls, hasLength(1));
      expect(rec.putFileCalls.single.path, '/untitled.py');
      expect(utf8.decode(rec.putFileCalls.single.bytes), 'x = 1\n');
    });

    testWidgets('New folder dialog creates a directory (mkdir)', (
      WidgetTester tester,
    ) async {
      final RecordingConnection rec = RecordingConnection(
        initial: ConnState.ready,
      );
      addTearDown(rec.dispose);
      await pumpSurface(tester, const FilesView(), connection: rec);
      await tester.pumpAndSettle();
      final AppLocalizations l10n = l10nOf(tester);

      await tester.tap(find.byTooltip(l10n.filesActionNewFolder));
      await tester.pumpAndSettle();
      expect(find.text(l10n.filesNewFolderTitle), findsOneWidget);

      await tester.enterText(find.byType(TextField), 'data');
      await tester.tap(find.text(l10n.commonCreate));
      await tester.pumpAndSettle();

      expect(rec.mkdirCalls, contains('/data'));
    });

    testWidgets('Delete asks to confirm, then deletes', (
      WidgetTester tester,
    ) async {
      final RecordingConnection rec = RecordingConnection(
        initial: ConnState.ready,
      );
      addTearDown(rec.dispose);
      await rec.putFile('/gone.py', b('bye\n'));
      await pumpSurface(tester, const FilesView(), connection: rec);
      await tester.pumpAndSettle();
      final AppLocalizations l10n = l10nOf(tester);

      await tester.tap(find.byKey(moreKey('gone.py')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(deleteKey('gone.py')));
      await tester.pumpAndSettle();
      expect(
        find.text(l10n.filesDeleteConfirmTitle('gone.py')),
        findsOneWidget,
      );
      expect(find.text(l10n.filesDeleteConfirmBody), findsOneWidget);

      await tester.tap(find.text(l10n.commonDelete));
      await tester.pumpAndSettle();
      expect(rec.deleteCalls, contains('/gone.py'));
    });

    testWidgets('Rename dialog renames the entry', (WidgetTester tester) async {
      final RecordingConnection rec = RecordingConnection(
        initial: ConnState.ready,
      );
      addTearDown(rec.dispose);
      await rec.putFile('/old.py', b('a\n'));
      await pumpSurface(tester, const FilesView(), connection: rec);
      await tester.pumpAndSettle();
      final AppLocalizations l10n = l10nOf(tester);

      await tester.tap(find.byKey(moreKey('old.py')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(renameKey('old.py')));
      await tester.pumpAndSettle();
      expect(find.text(l10n.filesRenameTitle('old.py')), findsOneWidget);

      await tester.enterText(find.byType(TextField), 'new.py');
      await tester.tap(find.text(l10n.commonRename));
      await tester.pumpAndSettle();

      expect(rec.renameCalls, contains(('/old.py', '/new.py')));
    });
  });

  group('A-30 FilesView — visible-file multi-delete (ADR-0043)', () {
    testWidgets(
      'Select exposes file checkboxes and row taps toggle without opening',
      (WidgetTester tester) async {
        final RecordingConnection rec = RecordingConnection(
          initial: ConnState.ready,
        );
        addTearDown(rec.dispose);
        await rec.putFile('/alpha.py', b('print("alpha")\n'));
        await rec.putFile('/notes.txt', b('notes\n'));
        await pumpSurface(tester, const FilesView(), connection: rec);
        await tester.pumpAndSettle();
        final AppLocalizations l10n = l10nOf(tester);

        expect(find.byKey(kFilesSelectActionKey), findsOneWidget);
        expect(find.text(l10n.filesActionSelect), findsOneWidget);
        expectTouchTarget(tester, find.byKey(kFilesSelectActionKey), 'Select');

        await enterSelection(tester);

        expect(find.byKey(kFilesSelectionBarKey), findsOneWidget);
        expect(find.text(l10n.filesSelectionFilesOnly), findsOneWidget);
        expect(find.text(l10n.filesSelectionSelectedCount(0)), findsOneWidget);
        for (final String name in <String>['alpha.py', 'notes.txt']) {
          expect(find.byKey(selectKey(name)), findsOneWidget);
          expect(
            tester.widget<Checkbox>(find.byKey(selectKey(name))).value,
            isFalse,
          );
        }
        expect(find.byTooltip(l10n.filesSelectionCancel), findsOneWidget);
        expect(find.byTooltip(l10n.filesSelectionDelete), findsOneWidget);
        expectTouchTarget(
          tester,
          find.byKey(kFilesSelectAllShownKey),
          'Select all shown',
        );
        expectTouchTarget(
          tester,
          find.byKey(kFilesBulkDeleteActionKey),
          'Delete selected',
        );

        await tester.tap(find.byKey(entryKey('alpha.py')));
        await tester.pump();

        expect(
          tester.widget<Checkbox>(find.byKey(selectKey('alpha.py'))).value,
          isTrue,
        );
        expect(
          tester.getSemantics(find.byKey(selectKey('alpha.py'))),
          isSemantics(hasCheckedState: true, isChecked: true),
        );
        final String selectedOne = l10n.filesSelectionSelectedCount(1);
        final Finder countText = find.text(selectedOne);
        expect(countText, findsOneWidget);
        final Finder countLiveRegion = find.ancestor(
          of: countText,
          matching: find.byWidgetPredicate(
            (Widget widget) =>
                widget is Semantics && widget.properties.liveRegion == true,
          ),
        );
        expect(countLiveRegion, findsOneWidget);
        expect(
          tester.getSemantics(countLiveRegion).label,
          contains(selectedOne),
          reason: 'the live-region announcement includes the exact count',
        );
        expect(
          rec.getFileCalls,
          isEmpty,
          reason: 'selection-mode row taps toggle instead of opening',
        );

        await tester.tap(find.byKey(entryKey('alpha.py')));
        await tester.pump();
        expect(
          tester.widget<Checkbox>(find.byKey(selectKey('alpha.py'))).value,
          isFalse,
        );
        expect(find.text(l10n.filesSelectionSelectedCount(0)), findsOneWidget);
      },
    );

    testWidgets('long press enters selection and selects an eligible file', (
      WidgetTester tester,
    ) async {
      final RecordingConnection rec = RecordingConnection(
        initial: ConnState.ready,
      );
      addTearDown(rec.dispose);
      await rec.putFile('/alpha.py', b('print("alpha")\n'));
      await pumpSurface(tester, const FilesView(), connection: rec);
      await tester.pumpAndSettle();
      final AppLocalizations l10n = l10nOf(tester);

      await tester.longPress(find.byKey(entryKey('alpha.py')));
      await tester.pumpAndSettle();

      expect(find.byKey(kFilesSelectionBarKey), findsOneWidget);
      expect(
        tester.widget<Checkbox>(find.byKey(selectKey('alpha.py'))).value,
        isTrue,
      );
      expect(find.text(l10n.filesSelectionSelectedCount(1)), findsOneWidget);
      expect(rec.getFileCalls, isEmpty);
    });

    testWidgets('Space toggles the keyboard-focused file checkbox', (
      WidgetTester tester,
    ) async {
      final RecordingConnection rec = RecordingConnection(
        initial: ConnState.ready,
      );
      addTearDown(rec.dispose);
      await rec.putFile('/alpha.py', b('print("alpha")\n'));
      await pumpSurface(tester, const FilesView(), connection: rec);
      await tester.pumpAndSettle();

      await enterSelection(tester);
      final Finder checkbox = find.byKey(selectKey('alpha.py'));
      for (
        int step = 0;
        step < 8 && !primaryFocusIsWithin(tester, checkbox);
        step += 1
      ) {
        await tester.sendKeyEvent(LogicalKeyboardKey.tab);
        await tester.pump();
      }
      expect(
        primaryFocusIsWithin(tester, checkbox),
        isTrue,
        reason: 'the selected-file checkbox participates in focus traversal',
      );

      await tester.sendKeyEvent(LogicalKeyboardKey.space);
      await tester.pump();

      expect(tester.widget<Checkbox>(checkbox).value, isTrue);
      expect(rec.getFileCalls, isEmpty);
    });

    testWidgets(
      'long press cannot enter selection while refresh is in flight',
      (WidgetTester tester) async {
        final _HeldListConnection rec = _HeldListConnection();
        addTearDown(() {
          if (!rec.releaseList.isCompleted) rec.releaseList.complete();
          rec.dispose();
        });
        await rec.putFile('/alpha.py', b('alpha\n'));
        await pumpSurface(tester, const FilesView(), connection: rec);
        await tester.pumpAndSettle();

        rec.holdNextList();
        final Future<void> pending = containerOf(
          tester,
        ).read(fileExplorerProvider.notifier).refresh();
        await rec.listStarted.future;
        await tester.pump();

        final TextButton selectAction = tester.widget<TextButton>(
          find.byKey(kFilesSelectActionKey),
        );
        expect(selectAction.onPressed, isNull);
        await tester.longPress(find.byKey(entryKey('alpha.py')));
        await tester.pump();
        expect(find.byKey(kFilesSelectionBarKey), findsNothing);

        rec.releaseList.complete();
        await pending;
        await tester.pumpAndSettle();
      },
    );

    testWidgets(
      'folders and protected root or scratch entries stay locked and excluded',
      (WidgetTester tester) async {
        final RecordingConnection rec = RecordingConnection(
          initial: ConnState.ready,
        );
        addTearDown(rec.dispose);
        await rec.mkdir('/lib');
        await rec.putFile('/main.py', b('print("main")\n'));
        for (final String name in <String>[
          'pyble_agent.py',
          'pble_config.py',
          'boot.py',
          '_boot.py',
          'transfer.pbltmp',
        ]) {
          await rec.putFile('/$name', b('# protected\n'));
        }
        await pumpSurface(tester, const FilesView(), connection: rec);
        await tester.pumpAndSettle();
        final AppLocalizations l10n = l10nOf(tester);

        for (final String name in <String>[
          'pyble_agent.py',
          'pble_config.py',
          'boot.py',
          '_boot.py',
          'transfer.pbltmp',
        ]) {
          final Finder row = find.byKey(entryKey(name));
          await Scrollable.ensureVisible(tester.element(row));
          await tester.pump();
          expect(
            find.descendant(
              of: row,
              matching: find.byTooltip(l10n.filesEntryProtected),
            ),
            findsOneWidget,
            reason: '$name explains its locked state',
          );
          expect(find.byKey(moreKey(name)), findsNothing);
          expect(find.byKey(renameKey(name)), findsNothing);
          expect(find.byKey(deleteKey(name)), findsNothing);
          expect(find.byKey(blocksKey(name)), findsNothing);
        }
        expect(find.byKey(moreKey('main.py')), findsOneWidget);
        expect(find.byKey(blocksKey('main.py')), findsOneWidget);

        await tester.tap(find.byKey(entryKey('boot.py')));
        await tester.pumpAndSettle();
        expect(
          rec.getFileCalls,
          isEmpty,
          reason: 'a protected control-plane file cannot be opened',
        );

        await enterSelection(tester);

        expect(find.byKey(selectKey('main.py')), findsOneWidget);
        expect(find.byKey(selectKey('lib')), findsNothing);
        for (final String name in <String>[
          'pyble_agent.py',
          'pble_config.py',
          'boot.py',
          '_boot.py',
          'transfer.pbltmp',
        ]) {
          expect(find.byKey(selectKey(name)), findsNothing);
        }

        await selectAllShown(tester);
        expect(
          tester.widget<Checkbox>(find.byKey(selectKey('main.py'))).value,
          isTrue,
        );
        expect(
          find.text(l10n.filesSelectionSelectedCount(1)),
          findsOneWidget,
          reason: 'Select all counts only the one eligible shown file',
        );

        await tester.tap(find.byKey(entryKey('lib')));
        await tester.pump();
        expect(
          containerOf(tester).read(fileExplorerProvider).cwd,
          '/',
          reason:
              'folders neither select nor navigate while selection is active',
        );
      },
    );

    testWidgets('ordinary nested pyble-prefixed files remain eligible', (
      WidgetTester tester,
    ) async {
      final RecordingConnection rec = RecordingConnection(
        initial: ConnState.ready,
      );
      addTearDown(rec.dispose);
      await rec.mkdir('/lib');
      await rec.putFile('/lib/pyble_user.py', b('print("user")\n'));
      await pumpSurface(tester, const FilesView(), connection: rec);
      await tester.pumpAndSettle();

      await tester.tap(find.byKey(entryKey('lib')));
      await tester.pumpAndSettle();
      await enterSelection(tester);

      expect(find.byKey(selectKey('pyble_user.py')), findsOneWidget);
      expect(find.byTooltip(l10nOf(tester).filesEntryProtected), findsNothing);
    });

    testWidgets(
      'Select all means eligible shown files, toggles clear, and browse actions hide',
      (WidgetTester tester) async {
        final RecordingConnection rec = RecordingConnection(
          initial: ConnState.ready,
        );
        addTearDown(rec.dispose);
        await rec.mkdir('/lib');
        await rec.putFile('/alpha.py', b('a\n'));
        await rec.putFile('/notes.txt', b('notes\n'));
        await pumpSurface(tester, const FilesView(), connection: rec);
        await tester.pumpAndSettle();
        final AppLocalizations l10n = l10nOf(tester);

        await enterSelection(tester);

        for (final String tooltip in <String>[
          l10n.filesGoUp,
          l10n.filesActionRefresh,
          l10n.filesEmptyCta,
          l10n.filesActionNewFolder,
          l10n.filesActionUpload,
          l10n.githubImportAction,
        ]) {
          expect(
            find.byTooltip(tooltip),
            findsNothing,
            reason: '$tooltip is unavailable during selection',
          );
        }
        for (final Key key in <Key>[
          moreKey('alpha.py'),
          blocksKey('alpha.py'),
          renameKey('notes.txt'),
          deleteKey('notes.txt'),
        ]) {
          expect(find.byKey(key), findsNothing);
        }
        expect(
          find.byTooltip(l10n.filesSelectionSelectAllShown(2)),
          findsOneWidget,
        );

        await selectAllShown(tester);

        expect(
          tester.widget<Checkbox>(find.byKey(selectKey('alpha.py'))).value,
          isTrue,
        );
        expect(
          tester.widget<Checkbox>(find.byKey(selectKey('notes.txt'))).value,
          isTrue,
        );
        expect(find.text(l10n.filesSelectionSelectedCount(2)), findsOneWidget);
        expect(find.byTooltip(l10n.filesSelectionClearAll), findsOneWidget);

        await tester.tap(find.byKey(kFilesSelectAllShownKey));
        await tester.pump();

        expect(
          tester.widget<Checkbox>(find.byKey(selectKey('alpha.py'))).value,
          isFalse,
        );
        expect(
          tester.widget<Checkbox>(find.byKey(selectKey('notes.txt'))).value,
          isFalse,
        );
        expect(find.text(l10n.filesSelectionSelectedCount(0)), findsOneWidget);
      },
    );

    for (final String exit in <String>['Cancel', 'Escape', 'Back']) {
      testWidgets(
        '$exit exits selection with zero deletes and restores focus',
        (WidgetTester tester) async {
          final RecordingConnection rec = RecordingConnection(
            initial: ConnState.ready,
          );
          addTearDown(rec.dispose);
          await rec.putFile('/alpha.py', b('a\n'));
          await pumpSurface(tester, const FilesView(), connection: rec);
          await tester.pumpAndSettle();
          final AppLocalizations l10n = l10nOf(tester);

          await enterSelection(tester);
          await tester.tap(find.byKey(entryKey('alpha.py')));
          await tester.pump();

          switch (exit) {
            case 'Cancel':
              await tester.tap(find.byTooltip(l10n.filesSelectionCancel));
              break;
            case 'Escape':
              await tester.sendKeyEvent(LogicalKeyboardKey.escape);
              break;
            case 'Back':
              await tester.binding.handlePopRoute();
              break;
          }
          await tester.pumpAndSettle();

          expect(rec.deleteCalls, isEmpty);
          expect(find.byKey(selectKey('alpha.py')), findsNothing);
          final Finder selectAction = find.byKey(kFilesSelectActionKey);
          expect(selectAction, findsOneWidget);
          expect(
            primaryFocusIsWithin(tester, selectAction),
            isTrue,
            reason: '$exit returns keyboard focus to Select',
          );
        },
      );
    }

    testWidgets(
      'confirmation names the exact cwd and every file in display order; cancel is zero-I/O',
      (WidgetTester tester) async {
        final RecordingConnection rec = RecordingConnection(
          initial: ConnState.ready,
        );
        addTearDown(rec.dispose);
        await rec.mkdir('/examples');
        for (final String name in <String>['zeta.py', 'alpha.py', 'beta.py']) {
          await rec.putFile('/examples/$name', b('$name\n'));
        }
        await pumpSurface(tester, const FilesView(), connection: rec);
        await tester.pumpAndSettle();

        await tester.tap(find.byKey(entryKey('examples')));
        await tester.pumpAndSettle();
        final AppLocalizations l10n = l10nOf(tester);
        await enterSelection(tester);
        for (final String name in <String>['zeta.py', 'beta.py', 'alpha.py']) {
          await tester.tap(find.byKey(entryKey(name)));
          await tester.pump();
        }

        await tester.tap(find.byKey(kFilesBulkDeleteActionKey));
        await tester.pumpAndSettle();

        final Finder dialog = find.byType(AlertDialog);
        expect(dialog, findsOneWidget);
        expect(
          find.descendant(
            of: dialog,
            matching: find.text(l10n.filesDeleteSelectedConfirmTitle(3)),
          ),
          findsOneWidget,
        );
        expect(
          find.descendant(
            of: dialog,
            matching: find.text(
              l10n.filesDeleteSelectedConfirmBody('/examples'),
            ),
          ),
          findsOneWidget,
        );
        final Finder alpha = find.descendant(
          of: dialog,
          matching: find.text('alpha.py'),
        );
        final Finder beta = find.descendant(
          of: dialog,
          matching: find.text('beta.py'),
        );
        final Finder zeta = find.descendant(
          of: dialog,
          matching: find.text('zeta.py'),
        );
        expect(alpha, findsOneWidget);
        expect(beta, findsOneWidget);
        expect(zeta, findsOneWidget);
        expect(
          tester.getTopLeft(alpha).dy,
          lessThan(tester.getTopLeft(beta).dy),
        );
        expect(
          tester.getTopLeft(beta).dy,
          lessThan(tester.getTopLeft(zeta).dy),
        );

        final Finder cancel = find.descendant(
          of: dialog,
          matching: find.widgetWithText(TextButton, l10n.commonCancel),
        );
        expect(cancel, findsOneWidget);
        expect(
          primaryFocusIsWithin(tester, cancel),
          isTrue,
          reason: 'destructive Delete never receives initial dialog focus',
        );
        await tester.tap(cancel);
        await tester.pumpAndSettle();

        expect(rec.deleteCalls, isEmpty);
        expect(find.byKey(kFilesSelectionBarKey), findsOneWidget);
        for (final String name in <String>['alpha.py', 'beta.py', 'zeta.py']) {
          expect(
            tester.widget<Checkbox>(find.byKey(selectKey(name))).value,
            isTrue,
          );
        }
      },
    );

    testWidgets('complete batch deletes in display order and exits selection', (
      WidgetTester tester,
    ) async {
      final RecordingConnection rec = RecordingConnection(
        initial: ConnState.ready,
      );
      addTearDown(rec.dispose);
      for (final String name in <String>['beta.py', 'gamma.py', 'alpha.py']) {
        await rec.putFile('/$name', b('$name\n'));
      }
      await pumpSurface(tester, const FilesView(), connection: rec);
      await tester.pumpAndSettle();
      final AppLocalizations l10n = l10nOf(tester);

      await enterSelection(tester);
      await tester.tap(find.byKey(entryKey('beta.py')));
      await tester.tap(find.byKey(entryKey('alpha.py')));
      await tester.pump();
      await tester.tap(find.byKey(kFilesBulkDeleteActionKey));
      await tester.pumpAndSettle();
      final Finder dialog = find.byType(AlertDialog);
      await tester.tap(
        find.descendant(
          of: dialog,
          matching: find.widgetWithText(FilledButton, l10n.commonDelete),
        ),
      );
      await tester.pumpAndSettle();

      expect(rec.deleteCalls, <String>['/alpha.py', '/beta.py']);
      expect(find.byKey(entryKey('alpha.py')), findsNothing);
      expect(find.byKey(entryKey('beta.py')), findsNothing);
      expect(find.byKey(entryKey('gamma.py')), findsOneWidget);
      expect(find.byKey(kFilesSelectionBarKey), findsNothing);
      expect(find.text(l10n.filesDeleteSelectedComplete(2)), findsOneWidget);
      final Finder selectAction = find.byKey(kFilesSelectActionKey);
      expect(selectAction, findsOneWidget);
      expect(primaryFocusIsWithin(tester, selectAction), isTrue);
    });

    testWidgets(
      'first failure stops the batch, keeps unresolved selected, and reports truth',
      (WidgetTester tester) async {
        final _FailingDeleteConnection rec = _FailingDeleteConnection(
          failPath: '/beta.py',
        );
        addTearDown(rec.dispose);
        for (final String name in <String>['gamma.py', 'beta.py', 'alpha.py']) {
          await rec.putFile('/$name', b('$name\n'));
        }
        await pumpSurface(tester, const FilesView(), connection: rec);
        await tester.pumpAndSettle();
        final AppLocalizations l10n = l10nOf(tester);

        await enterSelection(tester);
        await selectAllShown(tester);
        await tester.tap(find.byKey(kFilesBulkDeleteActionKey));
        await tester.pumpAndSettle();
        await tester.tap(
          find.descendant(
            of: find.byType(AlertDialog),
            matching: find.widgetWithText(FilledButton, l10n.commonDelete),
          ),
        );
        await tester.pumpAndSettle();

        expect(rec.deleteCalls, <String>[
          '/alpha.py',
          '/beta.py',
        ], reason: 'gamma is unattempted after beta fails');
        expect(find.byKey(entryKey('alpha.py')), findsNothing);
        expect(find.byKey(entryKey('beta.py')), findsOneWidget);
        expect(find.byKey(entryKey('gamma.py')), findsOneWidget);
        expect(find.byKey(kFilesSelectionBarKey), findsOneWidget);
        expect(
          tester.widget<Checkbox>(find.byKey(selectKey('beta.py'))).value,
          isTrue,
        );
        expect(
          tester.widget<Checkbox>(find.byKey(selectKey('gamma.py'))).value,
          isTrue,
        );
        expect(find.text(l10n.filesSelectionSelectedCount(2)), findsOneWidget);
        final String stopped = l10n.filesDeleteSelectedStopped(1, 2);
        final Finder stoppedText = find.text(stopped);
        expect(stoppedText, findsOneWidget);
        expect(find.textContaining(l10n.filesErrorIo), findsWidgets);
        final Finder resultLiveRegion = find.ancestor(
          of: stoppedText,
          matching: find.byWidgetPredicate(
            (Widget widget) =>
                widget is Semantics && widget.properties.liveRegion == true,
          ),
        );
        expect(resultLiveRegion, findsOneWidget);
        expect(
          tester.getSemantics(resultLiveRegion),
          isSemantics(isLiveRegion: true),
        );
      },
    );

    testWidgets(
      'editing selection clears the prior partial-result accounting',
      (WidgetTester tester) async {
        final _FailingDeleteConnection rec = _FailingDeleteConnection(
          failPath: '/beta.py',
        );
        addTearDown(rec.dispose);
        for (final String name in <String>['alpha.py', 'beta.py', 'gamma.py']) {
          await rec.putFile('/$name', b('$name\n'));
        }
        await pumpSurface(tester, const FilesView(), connection: rec);
        await tester.pumpAndSettle();
        final AppLocalizations l10n = l10nOf(tester);

        await enterSelection(tester);
        await selectAllShown(tester);
        await tester.tap(find.byKey(kFilesBulkDeleteActionKey));
        await tester.pumpAndSettle();
        await tester.tap(
          find.descendant(
            of: find.byType(AlertDialog),
            matching: find.widgetWithText(FilledButton, l10n.commonDelete),
          ),
        );
        await tester.pumpAndSettle();

        final String stopped = l10n.filesDeleteSelectedStopped(1, 2);
        expect(find.text(stopped), findsOneWidget);
        await tester.tap(find.byKey(entryKey('gamma.py')));
        await tester.pump();

        expect(
          find.text(stopped),
          findsNothing,
          reason:
              'a terminal result cannot be rewritten by later selection edits',
        );
        expect(
          find.text(l10n.filesDeleteSelectedStopped(1, 1)),
          findsNothing,
          reason:
              'a later selection edit dismisses rather than mutates the result',
        );
        expect(find.text(l10n.filesSelectionSelectedCount(1)), findsOneWidget);
      },
    );

    testWidgets(
      'reconciliation removes an absent failed row from retry selection',
      (WidgetTester tester) async {
        final _DisappearingDeleteConnection rec =
            _DisappearingDeleteConnection();
        addTearDown(rec.dispose);
        await rec.putFile('/alpha.py', b('alpha\n'));
        await rec.putFile('/beta.py', b('beta\n'));
        await pumpSurface(tester, const FilesView(), connection: rec);
        await tester.pumpAndSettle();
        final AppLocalizations l10n = l10nOf(tester);

        await enterSelection(tester);
        await selectAllShown(tester);
        await tester.tap(find.byKey(kFilesBulkDeleteActionKey));
        await tester.pumpAndSettle();
        await tester.tap(
          find.descendant(
            of: find.byType(AlertDialog),
            matching: find.widgetWithText(FilledButton, l10n.commonDelete),
          ),
        );
        await tester.pumpAndSettle();

        expect(find.byKey(entryKey('alpha.py')), findsNothing);
        expect(find.byKey(selectKey('alpha.py')), findsNothing);
        expect(find.byKey(selectKey('beta.py')), findsOneWidget);
        expect(
          tester.widget<Checkbox>(find.byKey(selectKey('beta.py'))).value,
          isTrue,
        );
        expect(find.text(l10n.filesSelectionSelectedCount(1)), findsOneWidget);
        expect(
          find.text(l10n.filesDeleteSelectedStopped(0, 1)),
          findsOneWidget,
        );
      },
    );

    testWidgets(
      'navigation during a running delete clears selection without hidden focus',
      (WidgetTester tester) async {
        final _HeldDeleteConnection rec = _HeldDeleteConnection();
        addTearDown(rec.dispose);
        await rec.putFile('/alpha.py', b('alpha\n'));
        await pumpSurface(tester, const FilesView(), connection: rec);
        await tester.pumpAndSettle();
        final AppLocalizations l10n = l10nOf(tester);

        await enterSelection(tester);
        await tester.tap(find.byKey(entryKey('alpha.py')));
        await tester.pump();
        await tester.tap(find.byKey(kFilesBulkDeleteActionKey));
        await tester.pumpAndSettle();
        await tester.tap(
          find.descendant(
            of: find.byType(AlertDialog),
            matching: find.widgetWithText(FilledButton, l10n.commonDelete),
          ),
        );
        await tester.pump();
        expect(rec.started.isCompleted, isTrue);

        containerOf(tester).read(selectedSurfaceProvider.notifier).state =
            AppSurface.editor;
        await tester.pump();
        rec.release.complete();
        await tester.pumpAndSettle();

        expect(find.byKey(kFilesSelectionBarKey), findsNothing);
        final Finder selectAction = find.byKey(kFilesSelectActionKey);
        expect(selectAction, findsOneWidget);
        expect(
          primaryFocusIsWithin(tester, selectAction),
          isFalse,
          reason: 'completion must not move focus into an offstage Files tree',
        );
        expect(find.text(l10n.filesDeleteSelectedComplete(1)), findsOneWidget);
      },
    );

    testWidgets('a running delete locks progress, selection, and mutations', (
      WidgetTester tester,
    ) async {
      final _HeldDeleteConnection rec = _HeldDeleteConnection();
      addTearDown(() {
        if (!rec.release.isCompleted) rec.release.complete();
        rec.dispose();
      });
      await rec.putFile('/alpha.py', b('alpha\n'));
      await rec.putFile('/beta.py', b('beta\n'));
      await pumpSurface(tester, const FilesView(), connection: rec);
      await tester.pumpAndSettle();
      final AppLocalizations l10n = l10nOf(tester);

      await enterSelection(tester);
      await selectAllShown(tester);
      await tester.tap(find.byKey(kFilesBulkDeleteActionKey));
      await tester.pumpAndSettle();
      await tester.tap(
        find.descendant(
          of: find.byType(AlertDialog),
          matching: find.widgetWithText(FilledButton, l10n.commonDelete),
        ),
      );
      await tester.pump();
      expect(rec.started.isCompleted, isTrue);

      final String progress = l10n.filesDeleteSelectedProgress(
        'alpha.py',
        0,
        2,
      );
      final Finder progressText = find.text(progress);
      expect(progressText, findsOneWidget);
      final Finder liveProgress = find.ancestor(
        of: progressText,
        matching: find.byWidgetPredicate(
          (Widget widget) =>
              widget is Semantics && widget.properties.liveRegion == true,
        ),
      );
      expect(liveProgress, findsOneWidget);
      expect(tester.widget<Semantics>(liveProgress).properties.label, progress);

      final Finder cancel = find.ancestor(
        of: find.byTooltip(l10n.filesSelectionCancel),
        matching: find.byType(IconButton),
      );
      expect(tester.widget<IconButton>(cancel).onPressed, isNull);
      expect(
        tester
            .widget<IconButton>(find.byKey(kFilesSelectAllShownKey))
            .onPressed,
        isNull,
      );
      expect(
        tester
            .widget<IconButton>(find.byKey(kFilesBulkDeleteActionKey))
            .onPressed,
        isNull,
      );
      for (final String name in <String>['alpha.py', 'beta.py']) {
        expect(
          tester.widget<Checkbox>(find.byKey(selectKey(name))).onChanged,
          isNull,
        );
        expect(
          tester.widget<ListTile>(find.byKey(entryKey(name))).onTap,
          isNull,
        );
      }
      expect(find.byType(RefreshIndicator), findsNothing);
      expect(find.text(l10n.filesSelectionSelectedCount(2)), findsOneWidget);

      rec.release.complete();
      await tester.pumpAndSettle();
    });

    testWidgets(
      'disconnect dismisses an open exact confirmation with zero I/O',
      (WidgetTester tester) async {
        final RecordingConnection rec = RecordingConnection(
          initial: ConnState.ready,
        );
        addTearDown(rec.dispose);
        await rec.putFile('/alpha.py', b('alpha\n'));
        await pumpSurface(tester, const FilesView(), connection: rec);
        await tester.pumpAndSettle();
        final AppLocalizations l10n = l10nOf(tester);

        await enterSelection(tester);
        await tester.tap(find.byKey(entryKey('alpha.py')));
        await tester.pump();
        await tester.tap(find.byKey(kFilesBulkDeleteActionKey));
        await tester.pumpAndSettle();
        expect(find.byType(AlertDialog), findsOneWidget);

        rec.emit(ConnState.disconnected);
        await tester.pumpAndSettle();

        expect(find.byType(AlertDialog), findsNothing);
        expect(find.text(l10n.filesDisconnectedTitle), findsOneWidget);
        expect(rec.deleteCalls, isEmpty);
      },
    );

    testWidgets('a replaced listing dismisses a stale confirmation safely', (
      WidgetTester tester,
    ) async {
      final RecordingConnection rec = RecordingConnection(
        initial: ConnState.ready,
      );
      addTearDown(rec.dispose);
      await rec.putFile('/alpha.py', b('alpha\n'));
      await pumpSurface(tester, const FilesView(), connection: rec);
      await tester.pumpAndSettle();

      await enterSelection(tester);
      await tester.tap(find.byKey(entryKey('alpha.py')));
      await tester.pump();
      await tester.tap(find.byKey(kFilesBulkDeleteActionKey));
      await tester.pumpAndSettle();
      expect(find.byType(AlertDialog), findsOneWidget);

      await containerOf(tester).read(fileExplorerProvider.notifier).refresh();
      await tester.pumpAndSettle();

      expect(find.byType(AlertDialog), findsNothing);
      expect(find.byKey(kFilesSelectionBarKey), findsNothing);
      expect(rec.deleteCalls, isEmpty);
      final Finder selectAction = find.byKey(kFilesSelectActionKey);
      expect(primaryFocusIsWithin(tester, selectAction), isTrue);
    });

    testWidgets(
      'selection and exact confirmation do not overflow narrow 2x UI',
      (WidgetTester tester) async {
        tester.platformDispatcher.textScaleFactorTestValue = 2;
        addTearDown(tester.platformDispatcher.clearTextScaleFactorTestValue);
        final RecordingConnection rec = RecordingConnection(
          initial: ConnState.ready,
        );
        addTearDown(rec.dispose);
        for (final String name in <String>[
          'alpha.py',
          'beta.py',
          'delta.py',
          'epsilon.py',
          'gamma.py',
        ]) {
          await rec.putFile('/$name', b('$name\n'));
        }
        await pumpSurface(
          tester,
          const FilesView(),
          connection: rec,
          size: const Size(320, 568),
        );
        await tester.pumpAndSettle();

        await enterSelection(tester);
        final Finder selectAll = find.byKey(kFilesSelectAllShownKey);
        await Scrollable.ensureVisible(
          tester.element(selectAll),
          alignment: 0.5,
        );
        await tester.pump();
        expectTouchTarget(tester, selectAll, 'narrow Select all shown');
        await tester.tap(selectAll);
        await tester.pumpAndSettle();

        final Finder delete = find.byKey(kFilesBulkDeleteActionKey);
        await Scrollable.ensureVisible(tester.element(delete), alignment: 0.5);
        await tester.pump();
        expectTouchTarget(tester, delete, 'narrow Delete selected');
        expect(delete.hitTestable(), findsOneWidget);
        expect(
          tester.takeException(),
          isNull,
          reason:
              'the contextual bar reflows or scrolls instead of overflowing',
        );

        await tester.tap(delete);
        await tester.pumpAndSettle();
        final Finder dialog = find.byType(AlertDialog);
        expect(dialog, findsOneWidget);
        final Finder lastName = find.descendant(
          of: dialog,
          matching: find.text('gamma.py'),
        );
        await Scrollable.ensureVisible(
          tester.element(lastName),
          alignment: 0.5,
        );
        await tester.pump();
        expect(lastName.hitTestable(), findsOneWidget);
        expect(
          tester.takeException(),
          isNull,
          reason: 'the exact-name confirmation scrolls at 320 dp and 2x text',
        );
      },
    );
  });

  group('A-30 FilesView — typed error -> localized message', () {
    testWidgets('a failing refresh surfaces the mapped message', (
      WidgetTester tester,
    ) async {
      final FakeConnection fake = FakeConnection(initial: ConnState.ready);
      addTearDown(fake.dispose);
      await pumpSurface(tester, const FilesView(), connection: fake);
      await tester.pumpAndSettle();
      final AppLocalizations l10n = l10nOf(tester);

      fake.injectError(const ENoEnt('nope'));
      await tester.tap(find.byTooltip(l10n.filesActionRefresh));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 400));

      expect(
        find.text(l10n.filesErrorNotFound),
        findsWidgets,
        reason: 'ENOENT maps to FileErrorKind.notFound -> filesErrorNotFound',
      );
    });
  });
}

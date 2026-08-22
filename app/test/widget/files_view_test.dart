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
// Top actions are found by their localized tooltips (filesActionRefresh /
// filesActionUpload / filesActionNewFolder / filesGoUp).
//
// CURRENTLY RED: lib/files exports no FilesView. HAND-OFF:
// lib/files/files_view.dart -> app-files-engineer.

import 'dart:convert';
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:pyble/editor/editor.dart';
import 'package:pyble/files/files.dart';
import 'package:pyble/localization/localization.dart';
import 'package:pyble/app/providers.dart';
import 'package:pyble/pble/pble.dart';

import '../support/feature_harness.dart';
import '../support/recording_connection.dart';

void main() {
  Uint8List b(String s) => Uint8List.fromList(utf8.encode(s));
  Key entryKey(String n) => ValueKey<String>('fileEntry_$n');
  Key deleteKey(String n) => ValueKey<String>('fileDelete_$n');
  Key renameKey(String n) => ValueKey<String>('fileRename_$n');
  Key moreKey(String n) => ValueKey<String>('fileMore_$n');
  Key blocksKey(String n) => ValueKey<String>('fileOpenBlocks_$n');

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

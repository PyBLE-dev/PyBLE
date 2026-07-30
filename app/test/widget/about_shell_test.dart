// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.
//
// X-11 [red] — global About entry and shell-state preservation
// (FR-ABOUT-1/7/8).

import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:pyble/app/pages/about_page.dart';
import 'package:pyble/app/providers.dart';
import 'package:pyble/blocks/blocks.dart';
import 'package:pyble/console/console.dart';
import 'package:pyble/editor/editor.dart';
import 'package:pyble/pble/pble.dart';

import '../support/recording_connection.dart';
import '../support/shell_harness.dart';

/// Adds the two read verbs not covered by [RecordingConnection], so an About
/// round trip can prove it causes no board request rather than only no mutation.
class _CompleteRecordingConnection extends RecordingConnection {
  _CompleteRecordingConnection({required super.initial});

  int deviceInfoCalls = 0;
  int listDirCalls = 0;

  @override
  Future<DeviceInfo> deviceInfo() {
    deviceInfoCalls += 1;
    return super.deviceInfo();
  }

  @override
  Future<List<RemoteEntry>> listDir(String path) {
    listDirCalls += 1;
    return super.listDir(path);
  }

  int get verbCalls =>
      deviceInfoCalls +
      runSourceCalls.length +
      runFileCalls.length +
      stopCalls +
      softRebootCalls +
      sendInputCalls.length +
      listDirCalls +
      getFileCalls.length +
      putFileCalls.length +
      deleteCalls.length +
      mkdirCalls.length +
      renameCalls.length;
}

ProviderContainer _containerOf(WidgetTester tester) =>
    ProviderScope.containerOf(tester.element(find.byType(MaterialApp)));

void _expectNoRecordedMutations(RecordingConnection connection) {
  expect(connection.operationLog, isEmpty);
  expect(connection.runSourceCalls, isEmpty);
  expect(connection.runFileCalls, isEmpty);
  expect(connection.stopCalls, 0);
  expect(connection.softRebootCalls, 0);
  expect(connection.sendInputCalls, isEmpty);
  expect(connection.putFileCalls, isEmpty);
  expect(connection.deleteCalls, isEmpty);
  expect(connection.mkdirCalls, isEmpty);
  expect(connection.renameCalls, isEmpty);
}

void main() {
  testWidgets(
    'wide toolbar opens About while disconnected without a board verb',
    (WidgetTester tester) async {
      final RecordingConnection connection = RecordingConnection();
      await pumpShell(tester, connection: connection, surface: ipadLandscape);

      final Finder about = find.byTooltip('About PyBLE');
      expect(about, findsOneWidget);
      expect(tester.getSize(about).height, greaterThanOrEqualTo(48));

      await tester.tap(about);
      await tester.pumpAndSettle();

      expect(find.byType(AboutPage), findsOneWidget);
      _expectNoRecordedMutations(connection);
    },
  );

  testWidgets('About remains reachable while a board is connecting', (
    WidgetTester tester,
  ) async {
    final _CompleteRecordingConnection connection =
        _CompleteRecordingConnection(initial: ConnState.connecting);
    await pumpShell(tester, connection: connection, surface: ipadLandscape);
    final int verbsBeforeAbout = connection.verbCalls;

    await tester.tap(find.byTooltip('About PyBLE'));
    await tester.pumpAndSettle();

    expect(find.byType(AboutPage), findsOneWidget);
    expect(connection.state.value, ConnState.connecting);
    expect(connection.verbCalls, verbsBeforeAbout);
    _expectNoRecordedMutations(connection);
  });

  testWidgets('compact About remains reachable while a program is running', (
    WidgetTester tester,
  ) async {
    final _CompleteRecordingConnection connection =
        _CompleteRecordingConnection(initial: ConnState.running);
    await pumpShell(tester, connection: connection, surface: phonePortrait);
    final int verbsBeforeAbout = connection.verbCalls;

    await tester.tap(find.byTooltip('More actions'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('About PyBLE'));
    await tester.pumpAndSettle();

    expect(find.byType(AboutPage), findsOneWidget);
    expect(connection.state.value, ConnState.running);
    expect(connection.verbCalls, verbsBeforeAbout);
    _expectNoRecordedMutations(connection);
  });

  testWidgets(
    'compact More menu exposes About and preserves the selected surface',
    (WidgetTester tester) async {
      final RecordingConnection connection = RecordingConnection(
        initial: ConnState.ready,
      );
      await pumpShell(tester, connection: connection, surface: phonePortrait);

      await tester.tap(
        find.descendant(
          of: find.byType(NavigationBar),
          matching: find.text('Blocks'),
        ),
      );
      await tester.pump();
      expect(
        find.byKey(const ValueKey<String>('blocksWorkspaceHost-0')),
        findsOneWidget,
      );

      expect(find.byTooltip('Soft-reboot'), findsNothing);
      final Finder more = find.byTooltip('More actions');
      expect(more, findsOneWidget);
      expect(tester.getSize(more).height, greaterThanOrEqualTo(48));

      await tester.tap(more);
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 500));
      expect(
        find.byKey(const Key('toolbarSoftRebootMenuItem')),
        findsOneWidget,
      );
      expect(find.byKey(const Key('toolbarAboutMenuItem')), findsOneWidget);

      await tester.tap(find.text('About PyBLE'));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 500));
      expect(find.byType(AboutPage), findsOneWidget);

      await tester.pageBack();
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 500));
      expect(find.byType(AboutPage), findsNothing);
      expect(
        find.byKey(const ValueKey<String>('blocksWorkspaceHost-0')),
        findsOneWidget,
      );
      _expectNoRecordedMutations(connection);
    },
  );

  testWidgets('About and licenses preserve the complete live Blocks session', (
    WidgetTester tester,
  ) async {
    const String editorSource = 'print("keep editor buffer")\n';
    const String blocksSource = 'print("keep visual workspace")\n';
    final _CompleteRecordingConnection connection =
        _CompleteRecordingConnection(initial: ConnState.running);
    await pumpShell(tester, connection: connection, surface: ipadLandscape);
    final ProviderContainer container = _containerOf(tester);

    container.read(editorDocumentProvider.notifier).setContent(editorSource);
    container.read(selectedSurfaceProvider.notifier).state = AppSurface.blocks;
    await tester.pump();

    final BlocksBridgeResult admitted = container
        .read(blocksDocumentProvider.notifier)
        .receiveBridgeMessage(
          jsonEncode(<String, Object?>{
            'version': kBlocksBridgeVersion,
            'type': 'snapshot',
            'revision': 7,
            'source': blocksSource,
            'workspace': <String, Object?>{
              'blocks': <String, Object?>{
                'languageVersion': 0,
                'blocks': <Object?>[
                  <String, Object?>{
                    'type': 'text_print',
                    'id': 'about-round-trip',
                  },
                ],
              },
            },
          }),
        );
    expect(admitted, BlocksBridgeResult.snapshotAccepted);

    // Subscribe before scripting the broadcast event so the provider retains
    // the live execution state throughout the nested route round trip.
    container.read(runStateProvider);
    connection.emitConsole(
      ConsoleStream.stdout,
      'live output stays\n'.codeUnits,
    );
    connection.emitRunState(RunState.running);
    await tester.pump();
    await tester.pump();

    final EditorDocument editorBefore = container.read(editorDocumentProvider);
    final BlocksDocument blocksBefore = container.read(blocksDocumentProvider);
    final List<ConsoleEvent> consoleBefore = container.read(
      consoleBufferProvider,
    );
    final int verbsBeforeAbout = connection.verbCalls;

    expect(container.read(selectedSurfaceProvider), AppSurface.blocks);
    expect(editorBefore.content, editorSource);
    expect(editorBefore.dirty, isTrue);
    expect(blocksBefore.program?.source, blocksSource);
    expect(blocksBefore.retainedWorkspaceJson, contains('about-round-trip'));
    expect(consoleBefore, hasLength(1));
    expect(find.textContaining('live output stays'), findsWidgets);
    expect(container.read(runStateProvider).value, RunState.running);
    expect(connection.state.value, ConnState.running);
    expect(
      find.byKey(const ValueKey<String>('blocksWorkspaceHost-0')),
      findsOneWidget,
    );

    await tester.tap(find.byTooltip('About PyBLE'));
    await tester.pumpAndSettle();
    expect(find.byType(AboutPage), findsOneWidget);

    final Finder licenses = find.byKey(
      const Key('aboutOpenSourceLicensesAction'),
    );
    await tester.ensureVisible(licenses);
    await tester.pumpAndSettle();
    await tester.tap(licenses);
    await tester.pumpAndSettle();
    expect(find.byType(LicensePage), findsOneWidget);

    await tester.pageBack();
    await tester.pumpAndSettle();
    expect(find.byType(AboutPage), findsOneWidget);
    expect(find.byType(LicensePage), findsNothing);

    await tester.pageBack();
    await tester.pumpAndSettle();
    expect(find.byType(AboutPage), findsNothing);
    expect(container.read(selectedSurfaceProvider), AppSurface.blocks);
    expect(container.read(editorDocumentProvider), editorBefore);
    expect(container.read(blocksDocumentProvider), same(blocksBefore));
    expect(container.read(consoleBufferProvider), same(consoleBefore));
    expect(container.read(runStateProvider).value, RunState.running);
    expect(container.read(connectionProvider), same(connection));
    expect(connection.state.value, ConnState.running);
    expect(connection.verbCalls, verbsBeforeAbout);
    _expectNoRecordedMutations(connection);
    expect(find.textContaining('live output stays'), findsWidgets);
    expect(
      find.byKey(const ValueKey<String>('blocksWorkspaceHost-0')),
      findsOneWidget,
    );
  });

  testWidgets('compact Soft-reboot menu item retains its Connection action', (
    WidgetTester tester,
  ) async {
    final RecordingConnection connection = RecordingConnection(
      initial: ConnState.ready,
    );
    await pumpShell(tester, connection: connection, surface: phonePortrait);

    await tester.tap(find.byTooltip('More actions'));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('toolbarSoftRebootMenuItem')));
    await tester.pumpAndSettle();

    expect(connection.softRebootCalls, 1);
    expect(tester.takeException(), isNull);
  });
}

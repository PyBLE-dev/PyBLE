// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.
//
// A-16 [red] — the shell toolbar wires Run / Stop / Soft-reboot to run-control,
// hosts the live console strip, and focuses the console on Run (ADR-0010, TDD
// §11.6b/e, specs.md FR-RUN §4.8, FR-UI-3). The three run actions are the ONLY
// board-control verbs (FR-RUN-1); enable/disable derives from ConnState +
// RunState via runAvailabilityProvider. Everything routes through the Connection
// seam (FR-RUN-4), so it is driven here against a RecordingConnection — no board.
//
// CURRENTLY RED: lib/app/shell.dart still renders Run/Stop/Soft-reboot as inert
// slots (onPressed: null) and the console strip as a titled placeholder; the
// run-control providers do not exist yet. HAND-OFF: lib/app/shell.dart +
// lib/app/providers.dart (runStateProvider) -> app-architect;
// lib/editor/run_controller.dart -> app-editor-console-engineer.

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:pyble/app/app.dart';
import 'package:pyble/app/providers.dart';
import 'package:pyble/editor/editor.dart';
import 'package:pyble/localization/localization.dart';
import 'package:pyble/pble/pble.dart';

import '../support/recording_connection.dart';
import '../support/shell_harness.dart';

void main() {
  AppLocalizations l10n(WidgetTester t) =>
      AppLocalizations.of(t.element(find.byType(Scaffold).first));
  ProviderContainer container(WidgetTester t) =>
      ProviderScope.containerOf(t.element(find.byType(PybleApp)));

  IconButton runButton(WidgetTester t) =>
      t.widget<IconButton>(find.widgetWithIcon(IconButton, Icons.play_arrow));
  IconButton stopButton(WidgetTester t) =>
      t.widget<IconButton>(find.widgetWithIcon(IconButton, Icons.stop));
  IconButton rebootButton(WidgetTester t) =>
      t.widget<IconButton>(find.widgetWithIcon(IconButton, Icons.restart_alt));

  group('A-16 toolbar — availability derived from ConnState', () {
    testWidgets('disconnected disables Run, Stop, and Soft-reboot', (
      WidgetTester tester,
    ) async {
      final RecordingConnection rec = RecordingConnection(
        initial: ConnState.disconnected,
      );
      await pumpShell(tester, connection: rec, surface: ipadLandscape);

      expect(runButton(tester).onPressed, isNull);
      expect(stopButton(tester).onPressed, isNull);
      expect(rebootButton(tester).onPressed, isNull);
    });

    testWidgets('ready enables Run + Soft-reboot, disables Stop', (
      WidgetTester tester,
    ) async {
      final RecordingConnection rec = RecordingConnection(
        initial: ConnState.ready,
      );
      await pumpShell(tester, connection: rec, surface: ipadLandscape);

      expect(runButton(tester).onPressed, isNotNull);
      expect(stopButton(tester).onPressed, isNull);
      expect(rebootButton(tester).onPressed, isNotNull);
    });

    testWidgets('running enables Stop + Soft-reboot, disables Run', (
      WidgetTester tester,
    ) async {
      final RecordingConnection rec = RecordingConnection(
        initial: ConnState.running,
      );
      await pumpShell(tester, connection: rec, surface: ipadLandscape);

      expect(
        runButton(tester).onPressed,
        isNull,
        reason: 'Run is disabled while a program runs (FR-RUN-3)',
      );
      expect(stopButton(tester).onPressed, isNotNull);
      expect(rebootButton(tester).onPressed, isNotNull);
    });
  });

  group('A-16 toolbar — verbs route through the Connection seam', () {
    testWidgets(
      'Run uploads and executes the current editor buffer as a file',
      (WidgetTester tester) async {
        final RecordingConnection rec = RecordingConnection(
          initial: ConnState.ready,
        );
        await pumpShell(tester, connection: rec, surface: ipadLandscape);
        container(
          tester,
        ).read(editorDocumentProvider.notifier).setContent('print(1)\n');

        await tester.tap(find.widgetWithIcon(IconButton, Icons.play_arrow));
        await tester.pumpAndSettle();

        expect(rec.putFileCalls, hasLength(1));
        expect(
          String.fromCharCodes(rec.putFileCalls.single.bytes),
          'print(1)\n',
        );
        expect(rec.runFileCalls, <String>['/untitled.py']);
        expect(rec.runSourceCalls, isEmpty);
      },
    );

    testWidgets('Stop calls stop() while running', (WidgetTester tester) async {
      final RecordingConnection rec = RecordingConnection(
        initial: ConnState.running,
      );
      await pumpShell(tester, connection: rec, surface: ipadLandscape);

      await tester.tap(find.widgetWithIcon(IconButton, Icons.stop));
      await tester.pumpAndSettle();

      expect(rec.stopCalls, 1);
    });

    testWidgets('Soft-reboot calls softReboot()', (WidgetTester tester) async {
      final RecordingConnection rec = RecordingConnection(
        initial: ConnState.ready,
      );
      await pumpShell(tester, connection: rec, surface: ipadLandscape);

      await tester.tap(find.widgetWithIcon(IconButton, Icons.restart_alt));
      await tester.pumpAndSettle();

      expect(rec.softRebootCalls, 1);
    });

    testWidgets('EBusy on Run is surfaced honestly (runBusyMessage)', (
      WidgetTester tester,
    ) async {
      final RecordingConnection rec = RecordingConnection(
        initial: ConnState.ready,
      );
      await pumpShell(tester, connection: rec, surface: ipadLandscape);
      container(
        tester,
      ).read(editorDocumentProvider.notifier).setContent('while True: pass\n');
      rec.injectError(const EBusy('already running'));

      await tester.tap(find.widgetWithIcon(IconButton, Icons.play_arrow));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 400));

      expect(
        find.text(l10n(tester).runBusyMessage),
        findsWidgets,
        reason: 'EBUSY is never swallowed (FR-RUN-3)',
      );
    });
  });

  group('A-16 shell — live console strip + focus-on-run', () {
    testWidgets('the landscape console strip renders live output', (
      WidgetTester tester,
    ) async {
      final RecordingConnection rec = RecordingConnection(
        initial: ConnState.ready,
      );
      await pumpShell(tester, connection: rec, surface: ipadLandscape);

      rec.emitConsole(ConsoleStream.stdout, 'boot ok\n'.codeUnits);
      // Async broadcast delivery + ValueListenable rebuild through the strip's
      // buffer: pump twice so the appended event paints (see console_view_test).
      await tester.pump();
      await tester.pump();

      expect(find.textContaining('boot ok'), findsWidgets);
    });

    testWidgets('Run focuses the console in the stacked (phone) layout', (
      WidgetTester tester,
    ) async {
      final RecordingConnection rec = RecordingConnection(
        initial: ConnState.ready,
      );
      await pumpShell(tester, connection: rec, surface: phonePortrait);
      container(tester).read(selectedSurfaceProvider.notifier).state =
          AppSurface.editor;
      container(
        tester,
      ).read(editorDocumentProvider.notifier).setContent('print(1)\n');
      await tester.pump();

      await tester.tap(find.widgetWithIcon(IconButton, Icons.play_arrow));
      await tester.pumpAndSettle();

      expect(
        container(tester).read(selectedSurfaceProvider),
        AppSurface.console,
        reason:
            'stacked layout has no always-visible strip, so Run navigates '
            'to the Console surface (shell responsibility)',
      );
    });

    testWidgets(
      'console output survives a tab switch (kept alive by the shell)',
      (WidgetTester tester) async {
        final RecordingConnection rec = RecordingConnection(
          initial: ConnState.ready,
        );
        await pumpShell(tester, connection: rec, surface: phonePortrait);

        // Emit while the Console surface is NOT the selected one.
        container(tester).read(selectedSurfaceProvider.notifier).state =
            AppSurface.editor;
        await tester.pump();
        rec.emitConsole(ConsoleStream.stdout, 'early output\n'.codeUnits);
        await tester.pump();

        // Switch to the Console surface; the earlier output must still be there.
        container(tester).read(selectedSurfaceProvider.notifier).state =
            AppSurface.console;
        await tester.pumpAndSettle();

        expect(
          find.textContaining('early output'),
          findsWidgets,
          reason: 'the console buffer is kept alive across nav (FR-CONSOLE-7)',
        );
      },
    );
  });
}

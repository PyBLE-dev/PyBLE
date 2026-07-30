// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.
//
// A-21 [red] — the ConsoleView: renders the live console buffer, differentiates
// stdout/stderr/system (SignalCodeColors), a stdin row -> sendInput, a clear
// action, and a RunState indicator (ADR-0010, TDD §11.6c, specs.md FR-CONSOLE
// §4.7). Both the landscape strip and the Console surface render off the same
// consoleBufferProvider. Binds through the seam ONLY (CON-8).
//
// Pins: live stdout/stderr/system render; RunState indicator reflects
// runStateProvider; stdin input -> Connection.sendInput; clear empties output;
// input is disabled with guidance while disconnected. (Scroll-lock is
// widget-local ephemeral state, exercised via HIL, not pinned here.)
//
// CURRENTLY RED: lib/console exports no ConsoleView. HAND-OFF:
// lib/console/console_view.dart -> app-editor-console-engineer.

import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:pyble/console/console.dart';
import 'package:pyble/localization/localization.dart';
import 'package:pyble/pble/pble.dart';

import '../support/feature_harness.dart';
import '../support/recording_connection.dart';

void main() {
  group('A-21 ConsoleView — live output', () {
    testWidgets('renders stdout, stderr, and system output', (
      WidgetTester tester,
    ) async {
      final FakeConnection fake = FakeConnection(initial: ConnState.ready);
      addTearDown(fake.dispose);
      await pumpSurface(tester, const ConsoleView(), connection: fake);

      fake.emitConsole(ConsoleStream.stdout, utf8.encode('hello world\n'));
      fake.emitConsole(ConsoleStream.stderr, utf8.encode('NameError: boom\n'));
      fake.emitConsole(ConsoleStream.system, utf8.encode('reconnected'));
      // Console events arrive on an async broadcast stream, are appended to the
      // ring in a microtask, then surface through the ValueListenable — one pump
      // drains the delivery, a second lets the rebuilt frame paint.
      await tester.pump();
      await tester.pump();

      expect(find.textContaining('hello world'), findsWidgets);
      expect(
        find.textContaining('NameError: boom'),
        findsWidgets,
        reason: 'the raw traceback always renders (FR-ERR-2)',
      );
      expect(find.textContaining('reconnected'), findsWidgets);
    });

    testWidgets('RunState indicator reflects runStateProvider', (
      WidgetTester tester,
    ) async {
      final FakeConnection fake = FakeConnection(initial: ConnState.ready);
      addTearDown(fake.dispose);
      await pumpSurface(tester, const ConsoleView(), connection: fake);
      final AppLocalizations l10n = l10nOf(tester);

      fake.emitRunState(RunState.running);
      await tester.pump();
      expect(find.text(l10n.runStateRunning), findsOneWidget);

      fake.emitRunState(RunState.error);
      await tester.pump();
      expect(find.text(l10n.runStateError), findsOneWidget);
    });
  });

  group('A-21 ConsoleView — stdin + clear', () {
    testWidgets('typing + send forwards the line to Connection.sendInput', (
      WidgetTester tester,
    ) async {
      final RecordingConnection rec = RecordingConnection(
        initial: ConnState.ready,
      );
      addTearDown(rec.dispose);
      await pumpSurface(tester, const ConsoleView(), connection: rec);
      final AppLocalizations l10n = l10nOf(tester);

      await tester.enterText(find.byType(TextField), 'my name');
      await tester.tap(find.byTooltip(l10n.consoleSendTooltip));
      await tester.pump();

      expect(rec.sendInputCalls, isNotEmpty);
      expect(rec.sendInputCalls.single, contains('my name'));
    });

    testWidgets('clear empties the console output', (
      WidgetTester tester,
    ) async {
      final FakeConnection fake = FakeConnection(initial: ConnState.ready);
      addTearDown(fake.dispose);
      await pumpSurface(tester, const ConsoleView(), connection: fake);
      final AppLocalizations l10n = l10nOf(tester);

      fake.emitConsole(ConsoleStream.stdout, utf8.encode('transient output\n'));
      // Async broadcast delivery + ValueListenable rebuild: pump twice (see the
      // "renders stdout, stderr, and system output" test above).
      await tester.pump();
      await tester.pump();
      expect(find.textContaining('transient output'), findsWidgets);

      await tester.tap(find.byTooltip(l10n.consoleClearTooltip));
      await tester.pump();
      expect(find.textContaining('transient output'), findsNothing);
    });
  });

  group('A-21 ConsoleView — disconnected', () {
    testWidgets('input is disabled with guidance while disconnected', (
      WidgetTester tester,
    ) async {
      final FakeConnection fake = FakeConnection(
        initial: ConnState.disconnected,
      );
      addTearDown(fake.dispose);
      await pumpSurface(tester, const ConsoleView(), connection: fake);
      final AppLocalizations l10n = l10nOf(tester);

      expect(find.text(l10n.consoleInputDisabledHint), findsOneWidget);
      expect(
        find.byTooltip(l10n.consoleSendTooltip),
        findsNothing,
        reason: 'no send affordance while there is no board to receive input',
      );
    });
  });
}

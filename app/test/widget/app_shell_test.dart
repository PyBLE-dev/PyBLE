// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.
//
// A-05 [red] — app shell renders and binds ONLY to the Connection seam.
//
// Acceptance criteria (04_stories.md A-05):
//   • shell + navigation wired only to Connection; no widget imports lib/ble
//     (CON-8, FR-UI-7 — the compile path proves it: this test imports only
//     package:pyble/app/… + package:pyble/pble/…, never lib/ble);
//   • shell renders on the single Flutter package across form factors (BLD-1);
//   • hosts the future surfaces (connect/editor/console/files) without binding
//     to transport types (PRD 16.1);
//   • reflects ConnState from the injected FakeConnection.
//
// GREEN: `lib/app/**` (shell, PybleApp) and the `lib/pble/**` seam slice
// (Connection/ConnState/DeviceInfo/FakeConnection) now exist; the shell has been
// restyled to the "Signal" design system (design-system.md, ADR-0008). The
// original A-05 assertions below are preserved verbatim (four nav labels, no
// overflow across the five breakpoints, a live ConnState rebuild); a second group
// adds coverage for the new Signal chrome (the connection-status pill + the inert
// toolbar action slots) without weakening any of it.
// HAND-OFF provenance: lib/app → app-architect; lib/pble → app-protocol-engineer.

import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:pyble/app/app.dart';
import 'package:pyble/app/pages/pin_reference_page.dart';
import 'package:pyble/app/providers.dart';
import 'package:pyble/console/console.dart';
import 'package:pyble/editor/editor.dart';
import 'package:pyble/files/files.dart';
import 'package:pyble/localization/localization.dart';
import 'package:pyble/pble/pble.dart';

import '../support/shell_harness.dart';

/// Focus-mode and responsive-region keys are literal contracts on purpose:
/// shell tests must be able to distinguish the primary landscape Blocks
/// workspace from the legacy secondary-pane host without reaching into a
/// private widget implementation.
const ValueKey<String> _focusedBlocksWorkspaceKey = ValueKey<String>(
  'focusedBlocksWorkspace',
);
const ValueKey<String> _blocksWorkspaceHostKey = ValueKey<String>(
  'blocksWorkspaceHost-0',
);

/// The Signal connection-status pill's stable key (design-system.md §7.6). The
/// pill labels itself with the localized `connStatus*` word per [ConnState]; in
/// the test locale (`en`) those words are the literals asserted below.
const ValueKey<String> _pillKey = ValueKey<String>('connStatusPill');

/// Localized `en` state words the pill renders (ARB: connStatus{Disconnected,
/// Ready}). Findable only inside the pill subtree, so state changes are legible.
Finder _pillLabel(String word) =>
    find.descendant(of: find.byKey(_pillKey), matching: find.text(word));

AppLocalizations _l10n(WidgetTester tester) =>
    AppLocalizations.of(tester.element(find.byType(Scaffold).first));

/// The run-control toolbar action tooltips (ARB: toolbar{Run,Stop,SoftReboot}).
/// These always render; their ENABLED state is state-driven from run-control
/// (A-16, covered by run_toolbar_test.dart). The connection action is separate:
/// Connect (inert) before a board is connected, Disconnect (active) after it is
/// (ADR-0011).
const Set<String> _runControlTooltips = <String>{'Run', 'Stop', 'Soft-reboot'};

/// The IDE navigation destinations shown once a board is connected. Connect is
/// the pre-connection full-screen surface, not an IDE tab (ADR-0011).
const List<String> _ideNav = <String>['Editor', 'Console', 'Files', 'Blocks'];

Finder _landscapeBlocksDestination() => find.descendant(
  of: find.byType(NavigationRail),
  matching: find.text('Blocks'),
);

Future<void> _focusLandscapeBlocks(WidgetTester tester) async {
  final Finder destination = _landscapeBlocksDestination();
  expect(
    destination,
    findsOneWidget,
    reason: 'Blocks must be a first-class landscape NavigationRail destination',
  );
  await tester.tap(destination);
  // The fake host deliberately leaves Blocks in its loading state. Pump one
  // frame rather than waiting for the indeterminate progress animation.
  await tester.pump();
}

void main() {
  group('A-05 shell renders and binds to Connection', () {
    testWidgets('shows the IDE navigation destinations on iPad landscape '
        '(connected)', (tester) async {
      await pumpShell(
        tester,
        connection: fakeConnection(
          initial: ConnState.ready,
          info: fakeDeviceInfo(),
        ),
        surface: ipadLandscape,
      );

      expect(find.byType(PybleApp), findsOneWidget);
      for (final label in _ideNav) {
        expect(
          find.text(label),
          findsWidgets,
          reason: 'IDE navigation destination "$label" must be present (FR-UI)',
        );
      }
      // Connect is the pre-connection screen, not an IDE tab (ADR-0011): it is
      // absent from the connected shell (the toolbar shows Disconnect instead).
      expect(find.text('Connect'), findsNothing);
    });

    testWidgets(
      'renders without overflow across the tablet + phone breakpoints',
      (tester) async {
        for (final surface in const <ShellSurface>[
          ipadLandscape,
          ipadPortrait,
          androidTabletLandscape,
          androidTabletPortrait,
          phonePortrait,
        ]) {
          await pumpShell(
            tester,
            connection: fakeConnection(initial: ConnState.ready),
            surface: surface,
          );
          expect(
            tester.takeException(),
            isNull,
            reason:
                'shell must lay out without overflow at ${surface.name} '
                '(FR-UI-1/2/5)',
          );
          for (final label in _ideNav) {
            expect(
              find.text(label),
              findsWidgets,
              reason: 'nav "$label" must survive at ${surface.name}',
            );
          }
        }
      },
    );

    testWidgets('reflects a live ConnState change from the FakeConnection', (
      tester,
    ) async {
      final connection = fakeConnection(initial: ConnState.disconnected);
      await pumpShell(tester, connection: connection, surface: ipadLandscape);

      // The shell binds to the observable ConnState; a scripted transition must
      // rebuild it without throwing (FR-CONN-5).
      connection.emit(ConnState.connecting);
      await tester.pumpAndSettle();
      connection.emit(ConnState.ready);
      await tester.pumpAndSettle();

      expect(tester.takeException(), isNull);
      expect(find.byType(PybleApp), findsOneWidget);
    });
  });

  group('A-05 Signal chrome (design-system.md, ADR-0008)', () {
    testWidgets('toolbar shows the run controls and an active Disconnect action '
        'when connected', (tester) async {
      await pumpShell(
        tester,
        connection: fakeConnection(initial: ConnState.ready),
        surface: ipadLandscape,
      );

      // The three run-control slots are present with their localized tooltips
      // (§7.1); their enabled state is covered by run_toolbar_test.dart (A-16).
      for (final tooltip in _runControlTooltips) {
        expect(
          find.byTooltip(tooltip),
          findsOneWidget,
          reason: 'toolbar action "$tooltip" slot must render (FR-UI-3)',
        );
      }

      // Connected → the connection action is an ACTIVE Disconnect (ADR-0011);
      // Connect is not shown while a board is connected.
      expect(find.byTooltip('Connect'), findsNothing);
      final IconButton disconnect = tester
          .widgetList<IconButton>(find.byType(IconButton))
          .firstWhere((b) => b.tooltip == 'Disconnect');
      expect(
        disconnect.onPressed,
        isNotNull,
        reason: 'Disconnect is active while a board is connected',
      );
    });

    testWidgets('connection-status pill reflects a live ConnState transition', (
      tester,
    ) async {
      final connection = fakeConnection(initial: ConnState.disconnected);
      await pumpShell(tester, connection: connection, surface: ipadLandscape);

      // The pill is the app's primary state signal (§7.6, FR-UI-6/FR-CONN-5):
      // present once, self-labelled with the current state word.
      expect(find.byKey(_pillKey), findsOneWidget);
      expect(_pillLabel('Disconnected'), findsOneWidget);

      // A scripted transition through the seam re-labels the pill in place —
      // legible by text (with color/glyph as reinforcement, never color alone).
      connection.emit(ConnState.ready);
      await tester.pumpAndSettle();

      expect(tester.takeException(), isNull);
      expect(_pillLabel('Ready'), findsOneWidget);
      expect(_pillLabel('Disconnected'), findsNothing);
    });

    testWidgets(
      'connected pill retains board ID and firmware after Connect unmounts',
      (tester) async {
        await pumpShell(
          tester,
          connection: fakeConnection(
            initial: ConnState.ready,
            info: fakeDeviceInfo(deviceId: '5646', agentVersion: '0.6.0'),
          ),
          surface: ipadLandscape,
        );

        final AppLocalizations l10n = _l10n(tester);
        expect(_pillLabel('Ready'), findsOneWidget);
        expect(
          find.descendant(
            of: find.byKey(_pillKey),
            matching: find.text(
              l10n.connStatusBoardInfoSummary('5646', '0.6.0'),
            ),
          ),
          findsOneWidget,
        );
        expect(
          find.bySemanticsLabel(
            l10n.connStatusBoardInfoSemanticLabel('Ready', '5646', '0.6.0'),
          ),
          findsOneWidget,
        );
        expect(
          find.text(l10n.connectDeviceInfoTitle),
          findsNothing,
          reason: 'ADR-0011 replaces the Connect surface once ready',
        );
      },
    );

    testWidgets(
      'connected pill reports empty additive metadata without gating',
      (tester) async {
        await pumpShell(
          tester,
          connection: fakeConnection(
            initial: ConnState.ready,
            info: fakeDeviceInfo(deviceId: '', agentVersion: ''),
          ),
          surface: phonePortrait,
        );

        final AppLocalizations l10n = _l10n(tester);
        expect(
          find.descendant(
            of: find.byKey(_pillKey),
            matching: find.text(
              l10n.connStatusBoardInfoSummary(
                l10n.connectDeviceNotReported,
                l10n.connectDeviceNotReported,
              ),
            ),
          ),
          findsOneWidget,
        );
        expect(tester.takeException(), isNull);
        expect(find.byTooltip('Disconnect'), findsOneWidget);
      },
    );

    testWidgets(
      'Connect-to-IDE transition retains identity in ready and running',
      (tester) async {
        final FakeConnection connection = fakeConnection(
          initial: ConnState.connecting,
          info: fakeDeviceInfo(deviceId: '5646', agentVersion: '0.6.0'),
        );
        final PbleConnectionManager manager = await pumpShell(
          tester,
          connection: connection,
          surface: ipadLandscape,
        );

        final AppLocalizations l10n = _l10n(tester);
        expect(
          find.text(l10n.connectEmptyTitle),
          findsOneWidget,
          reason: 'the pre-connection Connect surface starts mounted',
        );

        await manager.connect('shell-transition-board');
        connection.emit(ConnState.ready);
        await tester.pumpAndSettle();

        expect(find.text(l10n.connectEmptyTitle), findsNothing);
        expect(find.text(l10n.connectDeviceInfoTitle), findsNothing);
        expect(_pillLabel('Ready'), findsOneWidget);
        expect(
          find.text(l10n.connStatusBoardInfoSummary('5646', '0.6.0')),
          findsOneWidget,
        );
        expect(
          find.bySemanticsLabel(
            l10n.connStatusBoardInfoSemanticLabel('Ready', '5646', '0.6.0'),
          ),
          findsOneWidget,
        );

        connection.emit(ConnState.running);
        await tester.pumpAndSettle();

        expect(_pillLabel('Running'), findsOneWidget);
        expect(
          find.text(l10n.connStatusBoardInfoSummary('5646', '0.6.0')),
          findsOneWidget,
        );
        expect(
          find.bySemanticsLabel(
            l10n.connStatusBoardInfoSemanticLabel('Running', '5646', '0.6.0'),
          ),
          findsOneWidget,
        );
      },
    );

    testWidgets('tight 2x layout ellipsizes identity but not state', (
      tester,
    ) async {
      tester.platformDispatcher.textScaleFactorTestValue = 2;
      addTearDown(tester.platformDispatcher.clearTextScaleFactorTestValue);
      const String longId = 'BOARD-IDENTITY-1234567890';
      const String longVersion = '0.6.0-development-metadata';

      await pumpShell(
        tester,
        connection: fakeConnection(
          initial: ConnState.ready,
          info: fakeDeviceInfo(deviceId: longId, agentVersion: longVersion),
        ),
        surface: phonePortrait,
      );

      final AppLocalizations l10n = _l10n(tester);
      final Finder stateFinder = _pillLabel('Ready');
      final Finder summaryFinder = find.descendant(
        of: find.byKey(_pillKey),
        matching: find.text(
          l10n.connStatusBoardInfoSummary(longId, longVersion),
        ),
      );
      expect(stateFinder, findsOneWidget);
      expect(summaryFinder, findsOneWidget);
      expect(
        tester.renderObject<RenderParagraph>(stateFinder).didExceedMaxLines,
        isFalse,
        reason: 'the full state word is the non-negotiable minimum signal',
      );
      expect(
        tester.renderObject<RenderParagraph>(summaryFinder).didExceedMaxLines,
        isTrue,
        reason: 'only the appended identity may ellipsize under pressure',
      );
      expect(
        find.bySemanticsLabel(
          l10n.connStatusBoardInfoSemanticLabel('Ready', longId, longVersion),
        ),
        findsOneWidget,
        reason: 'visual ellipsis must not truncate accessibility metadata',
      );
      expect(tester.takeException(), isNull);
    });
  });

  group('FR-UI-1 collapsible landscape Files sidebar', () {
    testWidgets('collapse button hides the Files pane; expand restores it', (
      tester,
    ) async {
      await pumpShell(
        tester,
        connection: fakeConnection(
          initial: ConnState.ready,
          info: fakeDeviceInfo(),
        ),
        surface: ipadLandscape,
      );

      // Expanded by default: the collapse affordance shows, expand does not.
      expect(find.byTooltip('Collapse files'), findsOneWidget);
      expect(find.byTooltip('Show files'), findsNothing);

      // Collapse the sidebar.
      await tester.tap(find.byTooltip('Collapse files'));
      await tester.pumpAndSettle();
      expect(tester.takeException(), isNull);
      expect(find.byTooltip('Show files'), findsOneWidget);
      expect(find.byTooltip('Collapse files'), findsNothing);

      // The IDE nav destinations survive the collapse (Files stays a rail
      // toggle, never removed).
      for (final label in _ideNav) {
        expect(
          find.text(label),
          findsWidgets,
          reason: 'nav "$label" must survive the sidebar collapse',
        );
      }

      // Expand again.
      await tester.tap(find.byTooltip('Show files'));
      await tester.pumpAndSettle();
      expect(find.byTooltip('Collapse files'), findsOneWidget);
    });

    testWidgets('the Files navigation destination toggles the sidebar, '
        'never duplicating Files into the centre', (tester) async {
      await pumpShell(
        tester,
        connection: fakeConnection(
          initial: ConnState.ready,
          info: fakeDeviceInfo(),
        ),
        surface: ipadLandscape,
      );

      // Tapping the Files item in the rail collapses the sidebar (FR-UI-1) —
      // it does not navigate the centre pane to a second Files surface.
      final Finder railFiles = find.descendant(
        of: find.byType(NavigationRail),
        matching: find.text('Files'),
      );
      expect(railFiles, findsOneWidget);
      await tester.tap(railFiles);
      await tester.pumpAndSettle();

      expect(tester.takeException(), isNull);
      expect(
        find.byTooltip('Show files'),
        findsOneWidget,
        reason: 'the Files rail item toggled the sidebar closed',
      );
    });
  });

  group('A-30 Files selection shell lifecycle (ADR-0043)', () {
    testWidgets('stacked navigation away clears temporary file selection', (
      WidgetTester tester,
    ) async {
      final FakeConnection connection = fakeConnection(
        initial: ConnState.ready,
      );
      await connection.putFile('/alpha.py', Uint8List.fromList(<int>[97, 10]));
      await pumpShell(tester, connection: connection, surface: ipadPortrait);

      Finder destination(String label) => find.descendant(
        of: find.byType(NavigationBar),
        matching: find.text(label),
      );

      await tester.tap(destination('Files'));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(kFilesSelectActionKey));
      await tester.pumpAndSettle();
      expect(find.byKey(kFilesSelectionBarKey), findsOneWidget);

      await tester.tap(destination('Editor'));
      await tester.pumpAndSettle();
      await tester.tap(destination('Files'));
      await tester.pumpAndSettle();

      expect(find.byKey(kFilesSelectionBarKey), findsNothing);
      expect(find.byKey(kFilesSelectActionKey), findsOneWidget);
    });

    testWidgets(
      'landscape Editor to Console focus keeps the visible Files selection',
      (WidgetTester tester) async {
        final FakeConnection connection = fakeConnection(
          initial: ConnState.ready,
        );
        await connection.putFile(
          '/alpha.py',
          Uint8List.fromList(<int>[97, 10]),
        );
        await pumpShell(tester, connection: connection, surface: ipadLandscape);

        await tester.tap(find.byKey(kFilesSelectActionKey));
        await tester.pumpAndSettle();
        expect(find.byKey(kFilesSelectionBarKey), findsOneWidget);

        final Finder console = find.descendant(
          of: find.byType(NavigationRail),
          matching: find.text('Console'),
        );
        await tester.tap(console);
        await tester.pumpAndSettle();

        expect(find.byKey(kFilesSelectionBarKey), findsOneWidget);
      },
    );
  });

  group('A-31 responsive Blocks reachability', () {
    testWidgets(
      'landscape NavigationRail opens a dedicated focused Blocks workspace',
      (tester) async {
        await pumpShell(
          tester,
          connection: fakeConnection(
            initial: ConnState.ready,
            info: fakeDeviceInfo(),
          ),
          surface: ipadLandscape,
        );

        await _focusLandscapeBlocks(tester);

        expect(find.byKey(_focusedBlocksWorkspaceKey), findsOneWidget);
        expect(find.byKey(_blocksWorkspaceHostKey), findsOneWidget);
        expect(
          find.byType(FilesView),
          findsNothing,
          reason: 'Files pane chrome must yield to focused visual programming',
        );
        expect(
          find.byType(EditorView),
          findsNothing,
          reason: 'the editor pane must not remain squeezed beside Blocks',
        );
        expect(
          find.byType(PinReferencePage),
          findsNothing,
          reason: 'Pins are a separate destination, not Blocks-side chrome',
        );
        expect(find.byTooltip('Collapse files'), findsNothing);
        expect(find.byType(SegmentedButton<RightPaneSurface>), findsNothing);
        expect(
          find.byIcon(Icons.play_arrow),
          findsOneWidget,
          reason:
              'focused Blocks exposes one unambiguous Run action, not both '
              'the global editor Run and the Blocks Run',
        );
      },
    );

    for (final ShellSurface surface in const <ShellSurface>[
      ipadLandscape,
      androidTabletLandscape,
      ShellSurface('tablet_landscape_threshold', Size(900, 600), 1),
    ]) {
      testWidgets(
        'focused Blocks owns the primary canvas width @ ${surface.name}',
        (tester) async {
          await pumpShell(
            tester,
            connection: fakeConnection(initial: ConnState.ready),
            surface: surface,
          );

          await _focusLandscapeBlocks(tester);

          expect(tester.takeException(), isNull);
          final Size railSize = tester.getSize(find.byType(NavigationRail));
          final Size hostSize = tester.getSize(
            find.byKey(_blocksWorkspaceHostKey),
          );
          final double postRailWidth = surface.size.width - railSize.width;

          expect(
            hostSize.width,
            greaterThanOrEqualTo(720),
            reason:
                'the Blockly canvas must remain practically usable at the '
                '${surface.name} landscape breakpoint',
          );
          expect(
            hostSize.width / postRailWidth,
            greaterThanOrEqualTo(0.60),
            reason:
                'the canvas must own at least 60% of content after the '
                'NavigationRail at ${surface.name}',
          );
        },
      );
    }

    testWidgets('a 1024 dp-wide iPad portrait remains in stacked layout', (
      tester,
    ) async {
      await pumpShell(
        tester,
        connection: fakeConnection(initial: ConnState.ready),
        surface: ipadPortrait,
      );

      expect(find.byType(NavigationBar), findsOneWidget);
      expect(find.byType(NavigationRail), findsNothing);
      expect(
        find.descendant(
          of: find.byType(NavigationBar),
          matching: find.text('Blocks'),
        ),
        findsOneWidget,
      );
    });

    testWidgets('portrait Blocks stays selected and focused after rotation', (
      tester,
    ) async {
      await pumpShell(
        tester,
        connection: fakeConnection(initial: ConnState.ready),
        surface: ipadPortrait,
      );

      final Finder blocksDestination = find.descendant(
        of: find.byType(NavigationBar),
        matching: find.text('Blocks'),
      );
      await tester.tap(blocksDestination);
      await tester.pump();
      expect(find.byKey(_blocksWorkspaceHostKey), findsOneWidget);

      tester.view.physicalSize =
          ipadLandscape.size * ipadLandscape.devicePixelRatio;
      await tester.pump();

      final NavigationRail rail = tester.widget<NavigationRail>(
        find.byType(NavigationRail),
      );
      expect(rail.selectedIndex, 3);
      expect(
        _landscapeBlocksDestination(),
        findsOneWidget,
        reason: 'rotation must preserve the selected Blocks destination',
      );
      expect(
        find.byKey(_focusedBlocksWorkspaceKey),
        findsOneWidget,
        reason: 'rotation must keep Blocks in the full landscape focus mode',
      );
    });

    testWidgets(
      'focused Blocks console is on demand and expands for new output',
      (tester) async {
        final FakeConnection connection = fakeConnection(
          initial: ConnState.ready,
        );
        await pumpShell(tester, connection: connection, surface: ipadLandscape);

        await _focusLandscapeBlocks(tester);

        expect(
          tester.getSize(find.byType(ConsoleStripView)).height,
          kConsoleCollapsedStripHeight,
        );
        expect(find.byTooltip('Expand console'), findsOneWidget);

        await tester.tap(find.byKey(kConsoleStripToggleKey));
        await tester.pump();
        expect(
          tester.getSize(find.byType(ConsoleStripView)).height,
          kConsoleStripHeight,
        );

        await tester.tap(find.byKey(kConsoleStripToggleKey));
        await tester.pump();
        connection.emitConsole(ConsoleStream.stdout, <int>[111, 107, 10]);
        await tester.pump();

        expect(
          tester.getSize(find.byType(ConsoleStripView)).height,
          kConsoleStripHeight,
          reason: 'new program output must reveal itself below the workspace',
        );
        expect(find.textContaining('ok'), findsOneWidget);
      },
    );

    testWidgets('stacked tablet exposes Blocks as a full-width destination', (
      tester,
    ) async {
      await pumpShell(
        tester,
        connection: fakeConnection(initial: ConnState.ready),
        surface: androidTabletPortrait,
      );

      final Finder blocksDestination = find.descendant(
        of: find.byType(NavigationBar),
        matching: find.text('Blocks'),
      );
      expect(blocksDestination, findsOneWidget);
      await tester.tap(blocksDestination);
      await tester.pump();

      expect(find.byKey(_blocksWorkspaceHostKey), findsOneWidget);
    });
  });

  group('ADR-0011 connection-gated shell', () {
    testWidgets(
      'disconnected shows the full-screen Connect flow, no IDE chrome',
      (tester) async {
        await pumpShell(
          tester,
          connection: fakeConnection(initial: ConnState.disconnected),
          surface: ipadLandscape,
        );

        expect(tester.takeException(), isNull);
        // No IDE chrome before a board is connected: no navigation rail, no
        // Files-sidebar collapse control.
        expect(find.byType(NavigationRail), findsNothing);
        expect(find.byTooltip('Collapse files'), findsNothing);
        // The connection action is an inert Connect (the live scan/connect flow is
        // the surface below); Disconnect is not offered while disconnected.
        expect(find.byTooltip('Connect'), findsOneWidget);
        expect(find.byTooltip('Disconnect'), findsNothing);
      },
    );

    testWidgets('the IDE chrome appears once a board becomes ready', (
      tester,
    ) async {
      final connection = fakeConnection(initial: ConnState.disconnected);
      await pumpShell(tester, connection: connection, surface: ipadLandscape);
      expect(find.byType(NavigationRail), findsNothing);

      connection.emit(ConnState.ready);
      await tester.pumpAndSettle();

      expect(tester.takeException(), isNull);
      // IDE chrome now present: the nav rail with the IDE destinations.
      expect(find.byType(NavigationRail), findsOneWidget);
      for (final label in _ideNav) {
        expect(find.text(label), findsWidgets);
      }
    });
  });
}

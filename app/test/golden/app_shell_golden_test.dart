// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.
//
// A-05 [red] — platform-parity golden scaffold (NFR-COMPAT-1, FR-UI-1/2/5).
//
// Standing gate: goldens render the shell at iPad AND Android, landscape AND
// portrait, plus a phone breakpoint, in `en`. Neither platform may lag.
//
// Two-phase: the shell (`lib/app/**`) + seam (`lib/pble/**`) do not exist yet,
// so this file compile-fails today — the intended A-05 [red]. Once the shell
// lands (green), flip `kGoldensReady` to true and seed the PNG baselines with:
//
//     flutter test --update-goldens test/golden/app_shell_golden_test.dart
//
// The `skip` keeps the first post-green CI run from failing on absent baselines
// until they are generated and committed under test/golden/goldens/.

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:pyble/app/app.dart';
import 'package:pyble/console/console.dart';
import 'package:pyble/pble/pble.dart';

import '../support/shell_harness.dart';

/// Re-baseline window OPEN (A-22): the Connect surface in the shell's
/// `IndexedStack` becomes the real `ConnectScreen` (scan/connect UI), so the
/// committed shell PNGs are stale. Held `false` — skipping the platform-parity
/// goldens — until `lib/connect`'s `ConnectScreen` lands [green]; the reseed step
/// then flips this back `true` and regenerates the baselines with:
///
///     flutter test --update-goldens test/golden/app_shell_golden_test.dart
const bool kGoldensReady = true;

void main() {
  group('A-05 shell platform-parity goldens (en)', () {
    for (final surface in parityMatrix) {
      testWidgets(
        'shell @ ${surface.name}',
        (tester) async {
          await pumpShell(
            tester,
            connection: fakeConnection(
              initial: ConnState.ready,
              info: fakeDeviceInfo(),
            ),
            surface: surface,
          );
          await expectLater(
            find.byType(PybleApp),
            matchesGoldenFile('goldens/shell_${surface.name}.png'),
          );
        },
        // Baselines seeded (see the header); skip stays available for a
        // future re-baseline window by flipping kGoldensReady back off.
        skip: !kGoldensReady,
      );
    }

    // Focused visual programming is a materially different landscape shell,
    // so it has dedicated iPad + Android baselines rather than being inferred
    // from the default Editor/Pins captures. The PNGs land with the green UI.
    for (final surface in const <ShellSurface>[
      ipadLandscape,
      androidTabletLandscape,
    ]) {
      testWidgets('focused Blocks @ ${surface.name}', (tester) async {
        await pumpShell(
          tester,
          connection: fakeConnection(
            initial: ConnState.ready,
            info: fakeDeviceInfo(),
          ),
          surface: surface,
        );

        final Finder blocksDestination = find.descendant(
          of: find.byType(NavigationRail),
          matching: find.text('Blocks'),
        );
        expect(
          blocksDestination,
          findsOneWidget,
          reason: 'Blocks is a first-class landscape rail destination',
        );
        await tester.tap(blocksDestination);
        await tester.pump();

        expect(
          find.byKey(const ValueKey<String>('focusedBlocksWorkspace')),
          findsOneWidget,
        );
        await expectLater(
          find.byType(PybleApp),
          matchesGoldenFile('goldens/shell_${surface.name}_blocks_focused.png'),
        );
      }, skip: !kGoldensReady);
    }

    testWidgets('focused Blocks @ ipad_portrait', (tester) async {
      await pumpShell(
        tester,
        connection: fakeConnection(
          initial: ConnState.ready,
          info: fakeDeviceInfo(),
        ),
        surface: ipadPortrait,
      );

      await tester.tap(
        find.descendant(
          of: find.byType(NavigationBar),
          matching: find.text('Blocks'),
        ),
      );
      await tester.pump();

      await expectLater(
        find.byType(PybleApp),
        matchesGoldenFile('goldens/shell_ipad_portrait_blocks_focused.png'),
      );
    }, skip: !kGoldensReady);

    testWidgets('focused Blocks @ 900 dp threshold', (tester) async {
      const ShellSurface threshold = ShellSurface(
        'tablet_landscape_threshold',
        Size(900, 600),
        1,
      );
      await pumpShell(
        tester,
        connection: fakeConnection(initial: ConnState.ready),
        surface: threshold,
      );

      await tester.tap(
        find.descendant(
          of: find.byType(NavigationRail),
          matching: find.text('Blocks'),
        ),
      );
      await tester.pump();

      expect(
        find.byKey(const ValueKey<String>('blocksGeneratedPythonInspector')),
        findsNothing,
      );
      await expectLater(
        find.byType(PybleApp),
        matchesGoldenFile(
          'goldens/shell_tablet_landscape_threshold_blocks_focused.png',
        ),
      );
    }, skip: !kGoldensReady);

    testWidgets('focused Blocks @ ipad_landscape expanded console', (
      tester,
    ) async {
      await pumpShell(
        tester,
        connection: fakeConnection(initial: ConnState.ready),
        surface: ipadLandscape,
      );

      await tester.tap(
        find.descendant(
          of: find.byType(NavigationRail),
          matching: find.text('Blocks'),
        ),
      );
      await tester.pump();
      await tester.tap(find.byKey(kConsoleStripToggleKey));
      await tester.pump();

      await expectLater(
        find.byType(PybleApp),
        matchesGoldenFile(
          'goldens/shell_ipad_landscape_blocks_console_expanded.png',
        ),
      );
    }, skip: !kGoldensReady);

    // The pre-connection state (ADR-0011): with no board connected the shell is
    // a full-screen Connect experience — NO IDE chrome (Files sidebar / Pins /
    // console strip). Locked as its own baseline so the gated layout is covered.
    testWidgets('shell @ ipad_landscape_disconnected', (tester) async {
      await pumpShell(
        tester,
        connection: fakeConnection(initial: ConnState.disconnected),
        surface: ipadLandscape,
      );
      await expectLater(
        find.byType(PybleApp),
        matchesGoldenFile('goldens/shell_ipad_landscape_disconnected.png'),
      );
    }, skip: !kGoldensReady);
  });
}

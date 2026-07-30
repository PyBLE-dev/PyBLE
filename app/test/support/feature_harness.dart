// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.
//
// Test-support: the working-loop feature harness (ADR-0010, TDD §11.6). Pumps a
// single feature surface (EditorView / ConsoleView / FilesView) in isolation
// with the Signal theme + AppLocalizations delegates, bound to a scripted
// Connection through the SEAM ONLY (connectionProvider override) — never
// `lib/ble` (CON-8, HARD INVARIANT #1). Also provides a ProviderContainer
// builder for the controller/provider unit suites.
//
// Owner: app-test-author. Scripts the shipped FakeConnection (lib/pble, owner
// app-protocol-engineer) through the neutral seam; adds no lib/** code.

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:pyble/app/providers.dart';
import 'package:pyble/localization/localization.dart';
import 'package:pyble/pble/pble.dart';
import 'package:pyble/theme/theme.dart';

/// A ProviderContainer with the [Connection] seam bound to [connection] and any
/// [extra] overrides. Disposed via `addTearDown` by the caller.
ProviderContainer featureContainer(
  Connection connection, {
  List<Override> extra = const <Override>[],
}) => ProviderContainer(
  overrides: <Override>[
    connectionProvider.overrideWithValue(connection),
    ...extra,
  ],
);

/// Pumps [child] inside a ProviderScope (seam bound to [connection]) + a
/// `MaterialApp` carrying the Signal theme and the AppLocalizations delegates,
/// under a `Scaffold` so `SnackBar`/dialogs have a host. [extra] adds further
/// provider overrides.
///
/// NOTE: callers with an animating (indeterminate) progress indicator must pump
/// explicit frames rather than [WidgetTester.pumpAndSettle].
Future<void> pumpSurface(
  WidgetTester tester,
  Widget child, {
  required Connection connection,
  List<Override> extra = const <Override>[],
  Size size = const Size(1024, 768),
}) async {
  tester.view.devicePixelRatio = 2.0;
  tester.view.physicalSize = size * 2.0;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);

  await tester.pumpWidget(
    ProviderScope(
      overrides: <Override>[
        connectionProvider.overrideWithValue(connection),
        ...extra,
      ],
      child: MaterialApp(
        localizationsDelegates: AppLocalizations.localizationsDelegates,
        supportedLocales: AppLocalizations.supportedLocales,
        theme: PybleTheme.light,
        home: Scaffold(body: child),
      ),
    ),
  );
  await tester.pump();
}

/// The AppLocalizations resolved from the currently-pumped tree.
AppLocalizations l10nOf(WidgetTester tester) =>
    AppLocalizations.of(tester.element(find.byType(Scaffold).first));

/// The ProviderContainer backing the currently-pumped ProviderScope.
ProviderContainer containerOf(WidgetTester tester) =>
    ProviderScope.containerOf(tester.element(find.byType(MaterialApp)));

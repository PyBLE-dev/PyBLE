// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.
//
// X-12 [red] — the MaterialApp is wired for localization (FR-I18N-1/5).
//
// Pins the shell wiring the ARB framework needs: the root MaterialApp must
// register AppLocalizations.delegate (so localized lookups resolve) and list
// `en` in supportedLocales (en day-one, CON-9). The app resolves the platform
// locale by default (FR-I18N-5).
//
// CURRENTLY RED: `lib/app/app.dart`'s MaterialApp does not yet set
// localizationsDelegates / supportedLocales — the X-12 framework has landed but
// the wiring is the shell-migration [green]. HAND-OFF: `lib/app/app.dart` →
// app-architect.

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:pyble/localization/localization.dart';
import 'package:pyble/pble/pble.dart';

import '../support/shell_harness.dart';

void main() {
  group('X-12 MaterialApp localization wiring (FR-I18N-1/5)', () {
    testWidgets('registers AppLocalizations.delegate and supports en', (
      tester,
    ) async {
      await pumpShell(
        tester,
        connection: fakeConnection(initial: ConnState.ready),
        surface: ipadLandscape,
      );

      final MaterialApp app = tester.widget<MaterialApp>(
        find.byType(MaterialApp),
      );

      expect(
        app.supportedLocales,
        contains(const Locale('en')),
        reason: 'en ships day-one and must be a supported locale (CON-9)',
      );
      expect(
        app.localizationsDelegates,
        contains(AppLocalizations.delegate),
        reason:
            'AppLocalizations.delegate must be registered so localized '
            'lookups resolve (FR-I18N-1)',
      );
    });
  });
}

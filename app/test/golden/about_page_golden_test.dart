// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.
//
// X-11 — responsive About-page visual parity (FR-ABOUT-7).

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:pyble/app/app_build_info.dart';
import 'package:pyble/app/pages/about_page.dart';
import 'package:pyble/localization/localization.dart';
import 'package:pyble/theme/theme.dart';

import '../support/shell_harness.dart';

Future<void> _pumpAboutGolden(WidgetTester tester, ShellSurface surface) async {
  tester.view.devicePixelRatio = surface.devicePixelRatio;
  tester.view.physicalSize = surface.size * surface.devicePixelRatio;
  addTearDown(tester.view.resetDevicePixelRatio);
  addTearDown(tester.view.resetPhysicalSize);

  await tester.pumpWidget(
    MaterialApp(
      localizationsDelegates: AppLocalizations.localizationsDelegates,
      supportedLocales: AppLocalizations.supportedLocales,
      theme: PybleTheme.light,
      home: AboutPage(
        buildInfoLoader: () async =>
            const AppBuildInfo(version: '0.1.0', buildNumber: '1'),
      ),
    ),
  );
  await tester.pumpAndSettle();
}

void main() {
  group('X-11 About visual parity', () {
    for (final ShellSurface surface in const <ShellSurface>[
      ipadLandscape,
      ipadPortrait,
      androidTabletLandscape,
      androidTabletPortrait,
      phonePortrait,
    ]) {
      testWidgets('About @ ${surface.name}', (WidgetTester tester) async {
        await _pumpAboutGolden(tester, surface);

        await expectLater(
          find.byType(AboutPage),
          matchesGoldenFile('goldens/about_${surface.name}.png'),
        );
      });
    }
  });
}

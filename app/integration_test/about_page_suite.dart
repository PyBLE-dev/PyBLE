// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.
//
// X-11 — real-platform package metadata and offline license smoke.

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:package_info_plus/package_info_plus.dart';

import 'package:pyble/app/licenses.dart';
import 'package:pyble/app/pages/about_page.dart';
import 'package:pyble/localization/localization.dart';
import 'package:pyble/theme/theme.dart';

void registerAboutPageIntegrationTests() {
  testWidgets('installed package metadata and licenses render offline', (
    WidgetTester tester,
  ) async {
    registerBundledLicenses();
    final PackageInfo installed = await PackageInfo.fromPlatform();
    final String expectedVersion = installed.buildNumber.trim().isEmpty
        ? 'Version ${installed.version.trim()}'
        : 'Version ${installed.version.trim()} '
              '(${installed.buildNumber.trim()})';

    await tester.pumpWidget(
      MaterialApp(
        locale: const Locale('en'),
        localizationsDelegates: AppLocalizations.localizationsDelegates,
        supportedLocales: AppLocalizations.supportedLocales,
        theme: PybleTheme.light,
        home: const AboutPage(),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text(expectedVersion), findsOneWidget);
    expect(find.text('pyble.dev'), findsOneWidget);

    final Finder licenses = find.byKey(
      const Key('aboutOpenSourceLicensesAction'),
    );
    await tester.ensureVisible(licenses);
    await tester.tap(licenses);
    await tester.pumpAndSettle();

    expect(find.byType(LicensePage), findsOneWidget);
    expect(find.textContaining('MIT License'), findsWidgets);
  });
}

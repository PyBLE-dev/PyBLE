// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.
//
// X-11 [red] — frozen About-page subset (FR-ABOUT-2..7).

import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:pyble/app/app_build_info.dart';
import 'package:pyble/app/pages/about_page.dart';
import 'package:pyble/localization/localization.dart';
import 'package:pyble/theme/theme.dart';

const AppBuildInfo _installedInfo = AppBuildInfo(
  version: '1.2.3',
  buildNumber: '45',
);

Future<void> _pumpAbout(
  WidgetTester tester, {
  AppBuildInfoLoader? loader,
  Size size = const Size(1024, 768),
  double textScale = 1,
  bool highContrast = false,
}) async {
  final AppBuildInfoLoader effectiveLoader =
      loader ?? () async => _installedInfo;
  tester.view.devicePixelRatio = 2;
  tester.view.physicalSize = size * 2;
  addTearDown(tester.view.resetDevicePixelRatio);
  addTearDown(tester.view.resetPhysicalSize);

  await tester.pumpWidget(
    MaterialApp(
      localizationsDelegates: AppLocalizations.localizationsDelegates,
      supportedLocales: AppLocalizations.supportedLocales,
      theme: highContrast ? PybleTheme.highContrastLight : PybleTheme.light,
      highContrastTheme: PybleTheme.highContrastLight,
      builder: (BuildContext context, Widget? child) => MediaQuery(
        data: MediaQuery.of(context).copyWith(
          highContrast: highContrast,
          textScaler: TextScaler.linear(textScale),
        ),
        child: child!,
      ),
      home: AboutPage(
        key: ValueKey<AppBuildInfoLoader>(effectiveLoader),
        buildInfoLoader: effectiveLoader,
      ),
    ),
  );
  await tester.pump();
}

void main() {
  group('X-11 About page identity and package metadata', () {
    testWidgets(
      'shows clean-room PyBLE product, platform, and project identity',
      (WidgetTester tester) async {
        await _pumpAbout(tester);
        await tester.pumpAndSettle();

        expect(find.byKey(const Key('aboutPage')), findsOneWidget);
        expect(find.text('About PyBLE'), findsOneWidget);
        expect(find.text('PyBLE'), findsOneWidget);
        expect(find.text('Python over Bluetooth Low Energy'), findsOneWidget);
        expect(find.text('Version 1.2.3 (45)'), findsOneWidget);
        expect(find.text('Designed for MicroPython + BLE'), findsOneWidget);
        expect(
          find.text(
            'A free, open-source, tablet-first IDE for editing, saving, and '
            'running MicroPython on compatible boards over BLE.',
          ),
          findsOneWidget,
        );
        expect(
          find.textContaining(
            'ESP32, ESP32-S3, and ESP32-C3 are the initial firmware targets',
          ),
          findsOneWidget,
        );
        expect(find.text('Free and open source'), findsOneWidget);
        expect(find.text('Private by default'), findsOneWidget);
        expect(find.text('Project'), findsOneWidget);
        expect(find.text('pyble.dev'), findsOneWidget);
        expect(find.text('esp32'), findsOneWidget);
        expect(find.text('esp32-s3'), findsOneWidget);
        expect(find.text('esp32-c3'), findsOneWidget);
        expect(find.text('PBLE/1'), findsOneWidget);
      },
    );

    testWidgets(
      'renders pending, blank-build, and failed metadata truthfully',
      (WidgetTester tester) async {
        final Completer<AppBuildInfo> pending = Completer<AppBuildInfo>();
        await _pumpAbout(tester, loader: () => pending.future);

        expect(find.text('Loading version…'), findsOneWidget);
        expect(find.textContaining(RegExp(r'\d+\.\d+\.\d+')), findsNothing);

        pending.complete(const AppBuildInfo(version: '2.0.0', buildNumber: ''));
        await tester.pumpAndSettle();
        expect(find.text('Version 2.0.0'), findsOneWidget);
        expect(find.textContaining('()'), findsNothing);

        await _pumpAbout(
          tester,
          loader: () => Future<AppBuildInfo>.error(StateError('unavailable')),
        );
        await tester.pumpAndSettle();
        expect(find.text('Version unavailable'), findsOneWidget);
        expect(tester.takeException(), isNull);
      },
    );

    testWidgets('opens Flutter licenses locally with PyBLE legalese', (
      WidgetTester tester,
    ) async {
      await _pumpAbout(tester);
      await tester.pumpAndSettle();

      final Finder licenses = find.byKey(
        const Key('aboutOpenSourceLicensesAction'),
      );
      expect(licenses, findsOneWidget);
      expect(tester.getSize(licenses).height, greaterThanOrEqualTo(48));

      await tester.ensureVisible(licenses);
      await tester.pump();
      await tester.tap(licenses);
      await tester.pumpAndSettle();

      expect(find.byType(LicensePage), findsOneWidget);
      expect(find.text('PyBLE'), findsWidgets);
      expect(find.textContaining('MIT License'), findsWidgets);
      expect(find.textContaining('Version 1.2.3 (45)'), findsWidgets);
    });
  });

  group('X-11 About responsive and accessible layout', () {
    for (final ({String name, Size size, double textScale, bool contrast})
        testCase
        in <({String name, Size size, double textScale, bool contrast})>[
          (
            name: 'small phone',
            size: const Size(320, 480),
            textScale: 1,
            contrast: false,
          ),
          (
            name: 'phone large text',
            size: const Size(390, 844),
            textScale: 2,
            contrast: false,
          ),
          (
            name: 'iPad portrait',
            size: const Size(1024, 1366),
            textScale: 1,
            contrast: false,
          ),
          (
            name: 'iPad landscape high contrast',
            size: const Size(1366, 1024),
            textScale: 2,
            contrast: true,
          ),
          (
            name: 'Android tablet landscape',
            size: const Size(1280, 800),
            textScale: 1,
            contrast: false,
          ),
          (
            name: 'Android tablet portrait',
            size: const Size(800, 1280),
            textScale: 1,
            contrast: false,
          ),
        ]) {
      testWidgets('${testCase.name} scrolls without overflow', (
        WidgetTester tester,
      ) async {
        await _pumpAbout(
          tester,
          size: testCase.size,
          textScale: testCase.textScale,
          highContrast: testCase.contrast,
        );
        await tester.pumpAndSettle();

        await tester.scrollUntilVisible(
          find.byKey(const Key('aboutPageEnd')),
          300,
          scrollable: find.byType(Scrollable).first,
        );
        await tester.pump();

        expect(
          tester.takeException(),
          isNull,
          reason: '${testCase.name} must scroll instead of overflow',
        );
        expect(find.byKey(const Key('aboutPageEnd')), findsOneWidget);
      });
    }

    testWidgets('marks the page and section titles as semantic headings', (
      WidgetTester tester,
    ) async {
      final SemanticsHandle semantics = tester.ensureSemantics();
      await _pumpAbout(tester);
      await tester.pumpAndSettle();

      for (final Key key in const <Key>[
        Key('aboutProductHeading'),
        Key('aboutPlatformHeading'),
        Key('aboutOpenSourceHeading'),
        Key('aboutPrivacyHeading'),
        Key('aboutProjectHeading'),
      ]) {
        expect(
          tester
              .getSemantics(find.byKey(key))
              .getSemanticsData()
              .flagsCollection
              .isHeader,
          isTrue,
          reason: '$key must expose heading semantics',
        );
      }
      semantics.dispose();
    });
  });
}

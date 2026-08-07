// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

import '../support/repo_paths.dart';

void main() {
  test('Android integration tests use an isolated application ID', () {
    final String appRoot = appPackageRoot().path;
    final String gradle = File(
      '$appRoot/android/app/build.gradle.kts',
    ).readAsStringSync();
    final File manifest = File(
      '$appRoot/android/app/src/integration/AndroidManifest.xml',
    );
    final String ci = File(
      '$appRoot/../.github/workflows/ci.yml',
    ).readAsStringSync();
    final String contributing = File(
      '$appRoot/../CONTRIBUTING.md',
    ).readAsStringSync();

    expect(gradle, contains('flavorDimensions += "purpose"'));
    expect(gradle, contains('create("production")'));
    expect(gradle, contains('create("integration")'));
    expect(gradle, contains('applicationIdSuffix = ".integrationtest"'));
    expect(manifest.existsSync(), isTrue);
    expect(manifest.readAsStringSync(), contains('PyBLE Integration Test'));

    final RegExpMatch? integrationPrebuild = RegExp(
      r'- name: Prebuild Android integration application.*?'
      r'(?=\n      - name:)',
      dotAll: true,
    ).firstMatch(ci);
    expect(integrationPrebuild, isNotNull);
    expect(integrationPrebuild!.group(0), contains('--flavor integration'));
    expect(integrationPrebuild.group(0), contains('app-integration-debug.apk'));

    final RegExpMatch? androidIntegrationStep = RegExp(
      r'- name: Real About \+ Blockly integration \(Android API 34\).*?'
      r'(?=\n      - name:)',
      dotAll: true,
    ).firstMatch(ci);
    expect(androidIntegrationStep, isNotNull);
    expect(
      androidIntegrationStep!.group(0),
      contains('--flavor integration'),
      reason:
          'device tests must never install or uninstall the production app ID',
    );
    expect(
      androidIntegrationStep.group(0),
      contains('app-integration-debug.apk'),
    );

    final RegExpMatch? productionReleaseStep = RegExp(
      r'- name: Production release APK build.*?'
      r'(?=\n      - name:)',
      dotAll: true,
    ).firstMatch(ci);
    expect(productionReleaseStep, isNotNull);
    expect(
      productionReleaseStep!.group(0),
      contains(
        'flutter build apk --release --flavor production '
        '--target lib/main.dart',
      ),
      reason:
          'CI must compile the normal artifact after host tests regenerate '
          'the dev-plugin registrant',
    );
    expect(
      productionReleaseStep.group(0),
      contains("package: name='dev.pyble.pyble'"),
    );

    expect(
      contributing,
      contains('flutter run --flavor production --target lib/main.dart'),
    );
    expect(contributing, isNot(contains('flutter run -d <device>')));
    expect(
      contributing,
      contains(
        'flutter build apk --release --flavor production '
        '--target lib/main.dart',
      ),
    );
    expect(contributing, contains('--flavor integration'));
    expect(
      gradle,
      contains('flutter run --release --flavor production'),
      reason: 'the signing comment must not advertise an ambiguous command',
    );
  });
}

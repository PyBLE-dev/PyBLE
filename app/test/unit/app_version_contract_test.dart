// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.
//
// BLD-3 [red] — one mechanically checked app identity spans package metadata,
// PBLE/1 HELLO, and public GitHub requests (ADR-0044).

import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

import 'package:pyble/app/app_info.dart';

import '../support/repo_paths.dart';

void main() {
  test('app 0.2.0 beta starts at globally monotonic build 5', () {
    final String pubspec = File(
      '${appPackageRoot().path}/pubspec.yaml',
    ).readAsStringSync();
    final List<RegExpMatch> declarations = RegExp(
      r'^version:\s*((?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*))\+([1-9]\d*)\s*$',
      multiLine: true,
    ).allMatches(pubspec).toList(growable: false);

    expect(
      declarations,
      hasLength(1),
      reason: 'pubspec must declare one canonical SemVer+positiveBuild value',
    );
    final RegExpMatch declaration = declarations.single;

    expect(declaration.group(1), '0.2.0');
    expect(declaration.group(2), '5');
    expect(
      kAppVersion,
      declaration.group(1),
      reason: 'PBLE/1 HELLO must match the package base version exactly',
    );
  });

  test('production PBLE/1 HELLO consumes the shared app identity', () {
    final String mainSource = File(
      '${appPackageRoot().path}/lib/main.dart',
    ).readAsStringSync();

    expect(
      mainSource,
      matches(
        RegExp(
          r'PbleConnectionManager\.production\('
          r'\s*appName:\s*kAppName,'
          r'\s*appVersion:\s*kAppVersion,'
          r'\s*\)',
        ),
      ),
      reason:
          'the production manager must not replace either shared constant '
          'with an independently versioned literal',
    );
  });
}

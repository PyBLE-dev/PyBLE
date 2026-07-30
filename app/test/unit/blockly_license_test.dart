// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

import 'dart:io';

import 'package:flutter/foundation.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:pyble/app/licenses.dart';

import '../support/repo_paths.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  test('the bundled PyBLE license stays byte-for-byte with /LICENSE', () {
    final String bundled = File(
      '${appPackageRoot().path}/assets/licenses/PyBLE-LICENSE.txt',
    ).readAsStringSync();
    final String canonical = File(
      '${repoRoot().path}/LICENSE',
    ).readAsStringSync();

    expect(bundled, canonical);
  });

  test('the PyBLE MIT license is registered in-app', () async {
    registerBundledLicenses();

    final LicenseEntry entry = await LicenseRegistry.licenses.firstWhere(
      (LicenseEntry candidate) => candidate.packages.contains('PyBLE'),
    );
    final String text = entry.paragraphs
        .map((LicenseParagraph paragraph) => paragraph.text)
        .join('\n');

    expect(text, contains('MIT License'));
    expect(text, contains('Viwat Vchirawongkwin'));
  });

  test('the vendored Blockly Apache license is registered in-app', () async {
    registerBundledLicenses();

    final LicenseEntry entry = await LicenseRegistry.licenses.firstWhere(
      (LicenseEntry candidate) => candidate.packages.contains('Blockly'),
    );
    final String text = entry.paragraphs
        .map((LicenseParagraph paragraph) => paragraph.text)
        .join('\n');

    expect(text, contains('Apache License'));
    expect(text, contains('Version 2.0'));
  });
}

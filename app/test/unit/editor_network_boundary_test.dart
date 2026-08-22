// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

import '../support/repo_paths.dart';

void main() {
  test('the editor cannot send source to an HTTP analyzer', () {
    final Directory editor = Directory('${appPackageRoot().path}/lib/editor');
    final List<File> dartFiles = editor
        .listSync(recursive: true)
        .whereType<File>()
        .where((File file) => file.path.endsWith('.dart'))
        .toList(growable: false);

    expect(dartFiles, isNotEmpty);
    for (final File file in dartFiles) {
      final String source = file.readAsStringSync();
      expect(source, isNot(contains("package:http")), reason: file.path);
      expect(source, isNot(contains('DartPadAnalyzer')), reason: file.path);
    }
  });
}

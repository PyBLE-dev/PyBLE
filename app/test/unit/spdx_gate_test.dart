// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.
//
// X-01 [red] — SPDX-MIT header gate (BLD-8, NFR-MAINT-4).
//
// Verification obligation for the story "every Dart/native source carries an
// SPDX-License-Identifier: MIT header; CI rejects any file lacking one." This
// suite (a) self-tests the gate `tools/ci/spdx_lint.sh` against temp fixtures —
// a header-less file must be flagged, a headed file must pass — and (b) asserts
// the real `app/lib` + `app/test` Dart tree carries the header.
//
// Production side: `tools/ci/spdx_lint.sh` (owner app-build-smith; landed at
// X-01 bootstrap). If this suite goes red, the gate script regressed.

import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

import '../support/repo_paths.dart';

void main() {
  final spdx = File(gateScript('spdx_lint.sh'));

  group('X-01 SPDX-MIT header gate (BLD-8)', () {
    test('the gate script exists', () {
      expect(
        spdx.existsSync(),
        isTrue,
        reason: 'tools/ci/spdx_lint.sh must exist (owner app-build-smith)',
      );
    });

    test('flags a Dart file that lacks the SPDX-MIT header', () {
      final tmp = Directory.systemTemp.createTempSync('pyble_spdx_miss_');
      addTearDown(() => tmp.deleteSync(recursive: true));
      File('${tmp.path}/naked.dart').writeAsStringSync('void main() {}\n');

      final r = Process.runSync('bash', [spdx.path, tmp.path]);
      expect(
        r.exitCode,
        isNonZero,
        reason: 'a header-less .dart file must fail the SPDX gate',
      );
    });

    test('passes a Dart file that carries the SPDX-MIT header', () {
      final tmp = Directory.systemTemp.createTempSync('pyble_spdx_ok_');
      addTearDown(() => tmp.deleteSync(recursive: true));
      File('${tmp.path}/ok.dart').writeAsStringSync(
        '// SPDX-License-Identifier: MIT\n'
        '// Part of PyBLE (https://pyble.dev) — see /LICENSE.\n'
        'void main() {}\n',
      );

      final r = Process.runSync('bash', [spdx.path, tmp.path]);
      expect(r.exitCode, 0, reason: r.stderr.toString());
    });

    for (final extension in <String>['js', 'html', 'css', 'json']) {
      test('flags an authored Blockly .$extension asset without SPDX', () {
        final tmp = Directory.systemTemp.createTempSync('pyble_spdx_blocks_');
        addTearDown(() => tmp.deleteSync(recursive: true));
        File('${tmp.path}/app/assets/blockly/authored.$extension')
          ..createSync(recursive: true)
          ..writeAsStringSync('authored content\n');

        final r = Process.runSync('bash', [spdx.path, tmp.path]);
        expect(
          r.exitCode,
          isNonZero,
          reason: 'an authored Blockly .$extension asset must fail SPDX lint',
        );
      });
    }

    test('passes headed authored Blockly assets', () {
      final tmp = Directory.systemTemp.createTempSync('pyble_spdx_blocks_ok_');
      addTearDown(() => tmp.deleteSync(recursive: true));
      for (final extension in <String>['js', 'html', 'css', 'json']) {
        File('${tmp.path}/app/assets/blockly/authored.$extension')
          ..createSync(recursive: true)
          ..writeAsStringSync(
            'SPDX-License-Identifier: MIT\n'
            'authored content\n',
          );
      }

      final r = Process.runSync('bash', [spdx.path, tmp.path]);
      expect(r.exitCode, 0, reason: r.stderr.toString());
    });

    test('exempts bundled Blockly vendor assets and pinned upstream', () {
      final tmp = Directory.systemTemp.createTempSync('pyble_spdx_vendor_');
      addTearDown(() => tmp.deleteSync(recursive: true));
      for (final path in <String>[
        '${tmp.path}/app/assets/blockly/vendor/upstream.js',
        '${tmp.path}/app/assets/blockly/vendor/upstream.dart',
        '${tmp.path}/app/upstream/blockly/upstream.js',
        '${tmp.path}/app/upstream/blockly/upstream.dart',
      ]) {
        (File(path)..createSync(recursive: true)).writeAsStringSync(
          'third-party content\n',
        );
      }

      final r = Process.runSync('bash', [spdx.path, tmp.path]);
      expect(
        r.exitCode,
        0,
        reason: 'third-party Blockly trees are outside the gate: ${r.stderr}',
      );
    });

    test(
      'every app/lib and app/test Dart file carries the SPDX-MIT header',
      () {
        final app = appPackageRoot();
        final roots = <Directory>[
          Directory('${app.path}/lib'),
          Directory('${app.path}/test'),
        ];
        final offenders = <String>[];
        for (final root in roots) {
          if (!root.existsSync()) continue;
          final dartFiles = root
              .listSync(recursive: true)
              .whereType<File>()
              .where((f) => f.path.endsWith('.dart'));
          for (final f in dartFiles) {
            if (!f.readAsStringSync().contains(
              'SPDX-License-Identifier: MIT',
            )) {
              offenders.add(f.path);
            }
          }
        }
        expect(
          offenders,
          isEmpty,
          reason: 'missing SPDX-MIT header: $offenders',
        );
      },
    );
  });
}

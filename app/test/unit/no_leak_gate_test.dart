// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.
//
// X-02 [red] — no-leak gate over app source (CON-6, FR-PBLE-15).
//
// Verification obligation for "CI fails on forbidden proprietary tokens across
// app/ sources." This suite (a) self-tests the gate `tools/ci/no_leak.sh`: a
// forbidden identifier planted in an `app/lib/pble/*.dart` fixture must be
// rejected; (b) proves the gate exempts governance docs that merely quote the
// tokens (PRD 1B.6); and (c) asserts the real tree passes.
//
// CLEAN-ROOM: every forbidden identifier below is ASSEMBLED from harmless
// fragments at run time, so this source file contains no contiguous forbidden
// literal — the same discipline the gate script itself uses. The fixtures are
// written to the system temp dir, never into the repo, so nothing forbidden is
// ever committed. Production side: `tools/ci/no_leak.sh` (owner app-build-smith).

import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

import '../support/repo_paths.dart';

/// The forbidden regex alternatives, each assembled from fragments that
/// are individually harmless (none matches the gate regex on its own).
final List<String> _forbiddenTokens = <String>[
  <String>['ti', 'tra', 'lab'].join(), // alt 1: vendor product name
  <String>['sl', 'p', '/1'].join(), // alt 2: protocol/path form
  <String>['sl', 'p', '_a'].join(), // alt 3: prefixed-symbol form
  <String>['micro', 'pad'].join(), // alt 4: prior application name
];

void main() {
  final gate = File(gateScript('no_leak.sh'));

  group('X-02 no-leak gate (CON-6, FR-PBLE-15)', () {
    test('the gate script exists', () {
      expect(
        gate.existsSync(),
        isTrue,
        reason: 'tools/ci/no_leak.sh must exist',
      );
    });

    for (var i = 0; i < _forbiddenTokens.length; i++) {
      final token = _forbiddenTokens[i];
      test(
        'rejects a forbidden token (alt ${i + 1}) in app/lib/pble source',
        () {
          final tmp = Directory.systemTemp.createTempSync('pyble_leak_');
          addTearDown(() => tmp.deleteSync(recursive: true));
          final planted = File('${tmp.path}/app/lib/pble/leak.dart')
            ..createSync(recursive: true);
          planted.writeAsStringSync(
            '// SPDX-License-Identifier: MIT\n'
            'const String x = "$token";\n',
          );

          final r = Process.runSync('bash', [gate.path, tmp.path]);
          expect(
            r.exitCode,
            isNonZero,
            reason:
                'no-leak must reject a forbidden identifier under app/lib/pble',
          );
        },
      );
    }

    for (final extension in <String>['js', 'html', 'css', 'json']) {
      test(
        'rejects a forbidden token in an authored Blockly .$extension asset',
        () {
          final tmp = Directory.systemTemp.createTempSync(
            'pyble_blockly_leak_',
          );
          addTearDown(() => tmp.deleteSync(recursive: true));
          final planted = File(
            '${tmp.path}/app/assets/blockly/authored.$extension',
          )..createSync(recursive: true);
          planted.writeAsStringSync(
            'SPDX-License-Identifier: MIT\n${_forbiddenTokens.first}\n',
          );

          final r = Process.runSync('bash', [gate.path, tmp.path]);
          expect(
            r.exitCode,
            isNonZero,
            reason: 'no-leak must reject authored Blockly .$extension assets',
          );
        },
      );
    }

    test('does not exempt an authored directory merely named vendor', () {
      final tmp = Directory.systemTemp.createTempSync('pyble_named_vendor_');
      addTearDown(() => tmp.deleteSync(recursive: true));
      final planted = File('${tmp.path}/app/lib/vendor/leak.dart')
        ..createSync(recursive: true);
      planted.writeAsStringSync(
        '// SPDX-License-Identifier: MIT\n'
        'const String x = "${_forbiddenTokens.first}";\n',
      );

      final r = Process.runSync('bash', [gate.path, tmp.path]);
      expect(
        r.exitCode,
        isNonZero,
        reason:
            'only app/assets/blockly/vendor is exempt; authored vendor-named '
            'directories remain in scope',
      );
    });

    test('exempts the bundled Blockly vendor subtree and pinned upstream', () {
      final tmp = Directory.systemTemp.createTempSync('pyble_blockly_vendor_');
      addTearDown(() => tmp.deleteSync(recursive: true));
      for (final path in <String>[
        '${tmp.path}/app/assets/blockly/vendor/upstream.js',
        '${tmp.path}/app/assets/blockly/vendor/upstream.dart',
        '${tmp.path}/app/upstream/blockly/upstream.js',
        '${tmp.path}/app/upstream/blockly/upstream.dart',
      ]) {
        (File(path)..createSync(recursive: true)).writeAsStringSync(
          _forbiddenTokens.first,
        );
      }

      final r = Process.runSync('bash', [gate.path, tmp.path]);
      expect(
        r.exitCode,
        0,
        reason: 'third-party Blockly trees are outside the gate: ${r.stderr}',
      );
    });

    test(
      'does not flag a governance .md that quotes the tokens (PRD 1B.6)',
      () {
        final tmp = Directory.systemTemp.createTempSync('pyble_leak_md_');
        addTearDown(() => tmp.deleteSync(recursive: true));
        final doc = File('${tmp.path}/app/NOTES.md')
          ..createSync(recursive: true);
        doc.writeAsStringSync(
          '# forbidden tokens (quoted to forbid them)\n'
          '${_forbiddenTokens.join(" ")}\n',
        );

        final r = Process.runSync('bash', [gate.path, tmp.path]);
        expect(
          r.exitCode,
          0,
          reason: 'markdown is exempt by extension — ${r.stderr}',
        );
      },
    );

    test(
      'passes the real tree (no forbidden identifiers in shippable source)',
      () {
        final r = Process.runSync('bash', [gate.path, repoRoot().path]);
        expect(r.exitCode, 0, reason: r.stderr.toString());
      },
    );
  });
}

// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.
//
// X-12 [red] — locale-parity gate self-test (FR-I18N-1..4, BLD-5, CON-9,
// NFR-A11Y-1/2).
//
// This suite is the contract for the merge-blocking gate `tools/ci/
// locale_parity.sh` and self-tests it with throwaway fixtures (system temp,
// never committed). It defines the gate's invocation + behaviour:
//
//   locale_parity.sh [APP_DIR]   (APP_DIR defaults to the repo's app/)
//     scans <APP_DIR>/lib/localization/arb/app_*.arb and <APP_DIR>/lib/app,
//     exiting non-zero on ANY of:
//     1. KEY PARITY  — a non-en app_*.arb whose key set != en's (MISSING or
//        ORPHAN key). A partial translation must not ship (NFR-A11Y-2). The
//        comparison ignores `@@locale` and `@key` description metadata.
//     2. TECHNICAL IDENTIFIER — an ARB VALUE that localizes a reserved ASCII
//        technical token (esp32 / esp32-s3 / esp32-c3, paths, opcode/cap/status
//        names): a token present in the en value must appear verbatim in every
//        other locale's value for that key (FR-I18N-4).
//     3. HARD-CODED TEXT — a display-string literal in lib/app (Text(),
//        tooltip:, AppBar title, SnackBar, label:) not sourced from
//        AppLocalizations (FR-I18N-3).
//
// CURRENTLY RED for TWO reasons, each a clean hand-off:
//   • the gate script does not exist yet → HAND-OFF app-build-smith (owns
//     tools/ci/locale_parity.sh + the ci.yml wiring);
//   • once it exists, the "real app tree passes" check stays red until the shell
//     user-facing strings are migrated to ARB keys → HAND-OFF app-architect
//     (shell-string migration + MaterialApp delegate wiring).

import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

import '../support/repo_paths.dart';

const String _spdx = '// SPDX-License-Identifier: MIT\n';

/// A minimal valid ARB (keys + @@locale only; no descriptions needed here).
String _arb(String locale, Map<String, String> entries) {
  final StringBuffer b = StringBuffer('{\n  "@@locale": "$locale"');
  entries.forEach((k, v) {
    b.write(',\n  "$k": ${_json(v)}');
  });
  b.write('\n}\n');
  return b.toString();
}

String _json(String s) =>
    '"${s.replaceAll(r'\', r'\\').replaceAll('"', r'\"')}"';

/// Lays out a throwaway app-package root with ARB bundles + optional Dart
/// sources beneath `lib/`.
Directory _fixtureApp({
  required Map<String, String> arbs, // locale -> file body
  Map<String, String> appDart = const <String, String>{}, // relPath -> source
  Map<String, String> libDart =
      const <String, String>{}, // lib relPath -> source
}) {
  final Directory tmp = Directory.systemTemp.createTempSync('pyble_locale_');
  arbs.forEach((locale, body) {
    File('${tmp.path}/lib/localization/arb/app_$locale.arb')
      ..createSync(recursive: true)
      ..writeAsStringSync(body);
  });
  appDart.forEach((rel, source) {
    File('${tmp.path}/lib/app/$rel')
      ..createSync(recursive: true)
      ..writeAsStringSync(source);
  });
  libDart.forEach((rel, source) {
    File('${tmp.path}/lib/$rel')
      ..createSync(recursive: true)
      ..writeAsStringSync(source);
  });
  return tmp;
}

void main() {
  final File gate = File(gateScript('locale_parity.sh'));

  int runGate(Directory appDir) =>
      Process.runSync('bash', <String>[gate.path, appDir.path]).exitCode;

  void requireGate() {
    if (!gate.existsSync()) {
      fail(
        'tools/ci/locale_parity.sh not implemented yet — HAND-OFF to '
        'app-build-smith (X-12). This suite is its contract.',
      );
    }
  }

  group('X-12 locale-parity gate (BLD-5, FR-I18N-1..4)', () {
    test('the gate script exists', () {
      expect(
        gate.existsSync(),
        isTrue,
        reason: 'tools/ci/locale_parity.sh missing — app-build-smith (X-12)',
      );
    });

    test('a valid single-locale (en-only) bundle passes', () {
      requireGate();
      final Directory app = _fixtureApp(
        arbs: <String, String>{
          'en': _arb('en', <String, String>{'greet': 'Hello', 'bye': 'Bye'}),
        },
      );
      addTearDown(() => app.deleteSync(recursive: true));
      expect(
        runGate(app),
        0,
        reason: 'a complete en bundle must not false-positive',
      );
    });

    test('KEY PARITY: a locale MISSING a key fails', () {
      requireGate();
      final Directory app = _fixtureApp(
        arbs: <String, String>{
          'en': _arb('en', <String, String>{'greet': 'Hello', 'bye': 'Bye'}),
          'fr': _arb('fr', <String, String>{
            'greet': 'Bonjour',
          }), // missing "bye"
        },
      );
      addTearDown(() => app.deleteSync(recursive: true));
      expect(
        runGate(app),
        isNonZero,
        reason: 'a partial translation must not ship (NFR-A11Y-2)',
      );
    });

    test('KEY PARITY: a locale with an ORPHAN key fails', () {
      requireGate();
      final Directory app = _fixtureApp(
        arbs: <String, String>{
          'en': _arb('en', <String, String>{'greet': 'Hello'}),
          'fr': _arb('fr', <String, String>{
            'greet': 'Bonjour',
            'extra': 'Extra',
          }),
        },
      );
      addTearDown(() => app.deleteSync(recursive: true));
      expect(
        runGate(app),
        isNonZero,
        reason: 'a key not present in en (orphan) must fail parity',
      );
    });

    test('TECHNICAL IDENTIFIER: localizing a reserved ASCII token fails', () {
      requireGate();
      final Directory app = _fixtureApp(
        arbs: <String, String>{
          'en': _arb('en', <String, String>{'note': 'Reference for esp32'}),
          // "esp32" was localized away — FR-I18N-4 violation.
          'fr': _arb('fr', <String, String>{'note': 'Référence pour la puce'}),
        },
      );
      addTearDown(() => app.deleteSync(recursive: true));
      expect(
        runGate(app),
        isNonZero,
        reason: 'technical identifiers stay ASCII and are never localized',
      );
    });

    test('HARD-CODED TEXT: a display literal in lib/app fails', () {
      requireGate();
      final Directory app = _fixtureApp(
        arbs: <String, String>{
          'en': _arb('en', <String, String>{'greet': 'Hello'}),
        },
        appDart: <String, String>{
          'bad_widget.dart':
              '${_spdx}import "package:flutter/material.dart";\n'
              'Widget build() => const Text("Hardcoded label");\n',
        },
      );
      addTearDown(() => app.deleteSync(recursive: true));
      expect(
        runGate(app),
        isNonZero,
        reason: 'no hard-coded display text (FR-I18N-3)',
      );
    });

    test('HARD-CODED TEXT: an AppLocalizations-sourced Text() passes', () {
      requireGate();
      final Directory app = _fixtureApp(
        arbs: <String, String>{
          'en': _arb('en', <String, String>{'greet': 'Hello'}),
        },
        appDart: <String, String>{
          'ok_widget.dart':
              '${_spdx}import "package:flutter/material.dart";\n'
              'Widget build(BuildContext c) => Text(AppLocalizations.of(c).greet);\n',
        },
      );
      addTearDown(() => app.deleteSync(recursive: true));
      expect(
        runGate(app),
        0,
        reason: 'strings sourced from AppLocalizations are the sanctioned path',
      );
    });

    test('HARD-CODED TEXT: GitHub-import display literals also fail', () {
      requireGate();
      final Directory app = _fixtureApp(
        arbs: <String, String>{
          'en': _arb('en', <String, String>{'greet': 'Hello'}),
        },
        libDart: <String, String>{
          'github_import/bad_widget.dart':
              '${_spdx}import "package:flutter/material.dart";\n'
              'Widget build() => const Text("Unlocalized import action");\n',
        },
      );
      addTearDown(() => app.deleteSync(recursive: true));
      expect(
        runGate(app),
        isNonZero,
        reason:
            'feature-package UI is subject to the same ARB-only display-copy '
            'contract as lib/app (FR-I18N-3)',
      );
    });

    test('HARD-CODED TEXT: touched Files-package literals also fail', () {
      requireGate();
      final Directory app = _fixtureApp(
        arbs: <String, String>{
          'en': _arb('en', <String, String>{'greet': 'Hello'}),
        },
        libDart: <String, String>{
          'files/bad_widget.dart':
              '${_spdx}import "package:flutter/material.dart";\n'
              'Widget build() => const Text("Unlocalized Files action");\n',
        },
      );
      addTearDown(() => app.deleteSync(recursive: true));
      expect(
        runGate(app),
        isNonZero,
        reason: 'Files UI must remain ARB-only after adding the import action',
      );
    });

    test('the REAL app tree passes the locale-parity gate', () {
      requireGate();
      // RED until the shell user-facing strings are migrated to ARB keys
      // (app-architect [green]); today lib/app carries English literals.
      expect(
        runGate(appPackageRoot()),
        0,
        reason:
            'the shipping app must pass parity (BLD-5) — pending the '
            'shell-string migration (HAND-OFF app-architect)',
      );
    });
  });
}

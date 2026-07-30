// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.
//
// X-03 [red] — import-boundary gate (NFR-MAINT-1, CON-8, FR-BLE-8, FR-UI-7).
//
// The seam is the testability precondition: the wire lives only in `lib/pble/`,
// so `lib/pble/` is the SOLE importer of `lib/ble/`; every other `lib/**` file
// (the shell and all widgets) binds to `Connection` via `package:pyble/pble/…`
// and MUST NOT import `lib/ble/` (TDD D1/D2, §15.6).
//
// This suite defines the contract for the gate script and self-tests it:
//   • a file OUTSIDE lib/pble importing lib/ble (package: or relative) → REJECT
//   • lib/pble importing lib/ble → ALLOW (sole importer)
//   • a widget importing only the Connection seam → ALLOW
//   • the real app tree → PASS
//
// Production side: `tools/ci/import_boundary.sh [APP_DIR]` (owner
// app-build-smith, NEW at X-03). It scans `<APP_DIR>/lib/**/*.dart` and exits
// non-zero if any file whose path is NOT under `<APP_DIR>/lib/pble/` imports
// `lib/ble/`. APP_DIR defaults to the repo's `app/`.
//
// CURRENTLY RED: the script does not exist yet — HAND-OFF to app-build-smith.

import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

import '../support/repo_paths.dart';

/// Lays out a throwaway app-package root (`<tmp>/lib/...`) with one Dart file.
Directory _fixtureApp(String relPath, String source) {
  final tmp = Directory.systemTemp.createTempSync('pyble_boundary_');
  File('${tmp.path}/$relPath')
    ..createSync(recursive: true)
    ..writeAsStringSync(source);
  return tmp;
}

const _spdx = '// SPDX-License-Identifier: MIT\n';

void main() {
  final gate = File(gateScript('import_boundary.sh'));

  int runGate(Directory appDir) =>
      Process.runSync('bash', [gate.path, appDir.path]).exitCode;

  group('X-03 import-boundary gate (NFR-MAINT-1, CON-8)', () {
    test('the gate script exists', () {
      expect(
        gate.existsSync(),
        isTrue,
        reason:
            'tools/ci/import_boundary.sh not implemented yet — '
            'HAND-OFF to app-build-smith (X-03). This suite is its contract.',
      );
    });

    test(
      'rejects a widget (outside lib/pble) importing lib/ble via package:',
      () {
        if (!gate.existsSync()) {
          fail('import_boundary.sh missing — app-build-smith hand-off (X-03)');
        }
        final app = _fixtureApp(
          'lib/editor/bad.dart',
          "${_spdx}import 'package:pyble/ble/ble.dart';\nvoid f() {}\n",
        );
        addTearDown(() => app.deleteSync(recursive: true));
        expect(
          runGate(app),
          isNonZero,
          reason: 'a widget importing lib/ble must fail the boundary gate',
        );
      },
    );

    test('rejects a relative import that resolves into lib/ble', () {
      if (!gate.existsSync()) {
        fail('import_boundary.sh missing — app-build-smith hand-off (X-03)');
      }
      final app = _fixtureApp(
        'lib/console/bad.dart',
        "${_spdx}import '../ble/ble.dart';\nvoid f() {}\n",
      );
      addTearDown(() => app.deleteSync(recursive: true));
      expect(
        runGate(app),
        isNonZero,
        reason: 'a relative import into lib/ble must also be rejected',
      );
    });

    test('allows lib/pble as the sole importer of lib/ble', () {
      if (!gate.existsSync()) {
        fail('import_boundary.sh missing — app-build-smith hand-off (X-03)');
      }
      final app = _fixtureApp(
        'lib/pble/client.dart',
        "${_spdx}import 'package:pyble/ble/ble.dart';\nvoid f() {}\n",
      );
      addTearDown(() => app.deleteSync(recursive: true));
      expect(
        runGate(app),
        0,
        reason: 'lib/pble is the single seam allowed to import lib/ble',
      );
    });

    test('allows lib/ble files importing their own siblings (intra-module)', () {
      if (!gate.existsSync()) {
        fail('import_boundary.sh missing — app-build-smith hand-off (X-03)');
      }
      final app = _fixtureApp(
        'lib/ble/fbp_impl.dart',
        "${_spdx}import 'ble_link.dart';\nimport '../ble/ble.dart';\nvoid f() {}\n",
      );
      addTearDown(() => app.deleteSync(recursive: true));
      expect(
        runGate(app),
        0,
        reason:
            'lib/ble is the module itself — sibling imports are legal '
            '(S2 regression: the gate self-tripped once lib/ble went multi-file)',
      );
    });

    test('allows a widget importing only the Connection seam', () {
      if (!gate.existsSync()) {
        fail('import_boundary.sh missing — app-build-smith hand-off (X-03)');
      }
      final app = _fixtureApp(
        'lib/editor/ok.dart',
        "${_spdx}import 'package:pyble/pble/pble.dart';\nvoid f() {}\n",
      );
      addTearDown(() => app.deleteSync(recursive: true));
      expect(
        runGate(app),
        0,
        reason: 'binding to package:pyble/pble/… is the sanctioned path',
      );
    });

    test('passes the real app tree', () {
      if (!gate.existsSync()) {
        fail('import_boundary.sh missing — app-build-smith hand-off (X-03)');
      }
      expect(
        runGate(appPackageRoot()),
        0,
        reason: 'no lib/** file outside lib/pble may import lib/ble',
      );
    });
  });
}

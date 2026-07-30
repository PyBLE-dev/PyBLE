// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.
//
// Test-support: locate the repo root and the app package root from inside a
// `flutter test` run (CWD == the `app/` package dir). Used by the gate
// self-tests (X-01/X-02/X-03) that shell out to `tools/ci/*.sh`.
//
// Owner: app-test-author. Pure `dart:io`; imports no `lib/**`.

import 'dart:io';

/// The `app/` package root — where `flutter test` runs (`Directory.current`).
Directory appPackageRoot() => Directory.current;

/// Walks up from the app package root until it finds the repo root (the dir
/// that contains `tools/ci`). Fails loudly if it cannot be located.
Directory repoRoot() {
  var dir = Directory.current;
  while (true) {
    if (Directory('${dir.path}/tools/ci').existsSync()) return dir;
    final parent = dir.parent;
    if (parent.path == dir.path) {
      throw StateError(
        'repo root not found: no ancestor of ${Directory.current.path} '
        'contains tools/ci',
      );
    }
    dir = parent;
  }
}

/// Absolute path to a CI gate script under `tools/ci/`.
String gateScript(String name) => '${repoRoot().path}/tools/ci/$name';

/// The SHARED, cross-language PBLE/1 conformance corpus (TDD §8.8).
///
/// This is the single byte-level guard that the firmware `pyble_proto` codec and
/// the Dart `pble` client agree on the wire. It is loaded RELATIVE to the repo
/// root and is NEVER copied into `app/` — both ends assert against this one file
/// (`tests/firmware_tests/host/conformance/corpus.json`).
File conformanceCorpus() => File(
  '${repoRoot().path}/tests/firmware_tests/host/conformance/corpus.json',
);

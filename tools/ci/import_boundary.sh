#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
#
# X-03 — IMPORT-BOUNDARY gate (NFR-MAINT-1, CON-8, FR-BLE-8, FR-UI-7, TDD §15.6).
#
# The Connection seam is load-bearing: the BLE wire lives ONLY in `lib/ble/`,
# and `lib/pble/` is the SOLE package permitted to import it. Every other
# `lib/**` file — the shell and all widgets — binds to `Connection` via
# `package:pyble/pble/…` and MUST NOT reach the transport directly. This gate
# mechanically enforces that seam so it cannot rot.
#
#   Rule: for every `<APP_DIR>/lib/**/*.dart` whose path is NOT under
#         `<APP_DIR>/lib/pble/`, FAIL if it imports/exports `lib/ble/`, whether
#         as `package:pyble/ble/…` or as a relative URI that resolves into
#         `lib/ble/`. Files under `lib/pble/` are exempt (the sole importer).
#
#   Usage:  import_boundary.sh [APP_DIR]     (APP_DIR defaults to <repo>/app)
#   Exit:   non-zero (and names each offender) if any boundary crossing is
#           found; 0 if the tree is clean.
#
# Pure bash + POSIX tools; no filesystem access to the imported target, so the
# relative-import resolution works even against not-yet-created files (as the
# self-test fixtures require).

set -u

HERE="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
REPO_ROOT="$(cd "$HERE/../.." && pwd)"
APP_DIR="${1:-$REPO_ROOT/app}"
LIB_DIR="$APP_DIR/lib"

if [ ! -d "$LIB_DIR" ]; then
  echo "import-boundary gate: no $LIB_DIR to scan (clean)"
  exit 0
fi

# Logical path normalization: collapse '.' and '..' segments WITHOUT touching
# the filesystem (the import target need not exist). Input is a path relative to
# lib/; output is the normalized path relative to lib/. String-based (no bash
# arrays) so it is safe under `set -u` on bash 3.2 (the macOS system shell),
# where expanding an empty array trips 'unbound variable'.
normalize_path() {
  local input="$1" seg out=""
  local oldIFS="$IFS"
  IFS='/'
  for seg in $input; do
    case "$seg" in
      '' | .) : ;;
      ..)
        # Pop the last segment of the slash-joined stack.
        case "$out" in
          */*) out="${out%/*}" ;;
          *) out="" ;;
        esac
        ;;
      *)
        if [ -z "$out" ]; then out="$seg"; else out="$out/$seg"; fi
        ;;
    esac
  done
  IFS="$oldIFS"
  printf '%s' "$out"
}

violations=0

while IFS= read -r file; do
  # Path of this file relative to lib/ (e.g. "editor/bad.dart", "main.dart").
  rel="${file#"$LIB_DIR"/}"

  # lib/pble/ is the ONE sanctioned importer of lib/ble/ — exempt. lib/ble/'s
  # own files are the module itself (intra-module sibling imports are legal).
  case "$rel" in
    pble/* | ble/*) continue ;;
  esac

  # This file's directory, relative to lib/ ("" when directly under lib/).
  dir="${rel%/*}"
  [ "$dir" = "$rel" ] && dir=""

  # Extract every single-line import/export URI (group 2 == the quoted URI).
  while IFS= read -r uri; do
    [ -z "$uri" ] && continue
    case "$uri" in
      package:pyble/ble/*)
        printf 'import-boundary: %s imports lib/ble via %s\n' "$rel" "$uri" >&2
        violations=1
        ;;
      *:*)
        # Any other scheme (dart:, package:flutter/…, package:pyble/pble/…) is
        # allowed — only package:pyble/ble/ crosses the seam.
        :
        ;;
      *)
        # Relative URI: resolve against this file's dir and see if it lands in
        # lib/ble/.
        norm="$(normalize_path "$dir/$uri")"
        case "$norm" in
          ble | ble/*)
            printf 'import-boundary: %s imports lib/ble via relative %s\n' \
              "$rel" "$uri" >&2
            violations=1
            ;;
        esac
        ;;
    esac
  done < <(sed -nE "s/^[[:space:]]*(import|export)[[:space:]]+['\"]([^'\"]+)['\"].*/\2/p" "$file")
done < <(find "$LIB_DIR" -type f -name '*.dart')

if [ "$violations" -ne 0 ]; then
  echo "import-boundary gate: a widget (lib/** outside lib/pble) imports lib/ble" >&2
  echo "  fix: bind to Connection via package:pyble/pble/… — only lib/pble may import lib/ble (CON-8)" >&2
  exit 1
fi

echo "import-boundary gate: clean (only lib/pble imports lib/ble)"
exit 0

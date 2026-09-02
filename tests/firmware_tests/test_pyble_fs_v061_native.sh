#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
#
# RED wrapper for native-C parity with v0.6.1 filesystem hardening semantics.

set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"

PY="${PYBLE_PYTHON:-python3}"
if ! command -v "$PY" >/dev/null 2>&1; then
  printf '    FAIL - no CPython (%s) on PATH — required for native FS parity tests\n' "$PY"
  exit 1
fi

exec "$PY" "$HERE/host/test_pyble_fs_v061_native.py"

#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.

set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
PY="${PYBLE_PYTHON:-python3}"

if ! command -v "$PY" >/dev/null 2>&1; then
  printf '    FAIL - no CPython (%s) on PATH — required for target HIL contract tests\n' "$PY"
  exit 1
fi

exec "$PY" "$HERE/host/test_target_hil_benches.py"

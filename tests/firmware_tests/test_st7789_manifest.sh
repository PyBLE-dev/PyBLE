#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
#
# ADR-0023 wrapper: run_tests.sh discovers test_*.sh files, while effective
# manifest resolution and source-structure checks live in the CPython suite.

set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"

PY="${PYBLE_PYTHON:-python3}"
if ! command -v "$PY" >/dev/null 2>&1; then
  printf '    FAIL - no CPython (%s) on PATH — required for ST7789 manifest tests\n' "$PY"
  exit 1
fi

exec "$PY" "$HERE/host/test_st7789_manifest.py"

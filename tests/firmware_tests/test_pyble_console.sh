#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
#
# Wrapper so run_tests.sh (which globs test_*.sh) drives the F-25 rpi-pico2-w
# console host suite (port spec P3/P8: run-gate, [stream][<=200] chunking,
# token-bucket budget, readinto 1-or-None, 256 B stdin ring, inject_stop)
# under CPython. RED until agent-engineer lands firmware/pyble/pyble_console.py
# [green]. Exit non-zero on any failure.

set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"

PY="${PYBLE_PYTHON:-python3}"
if ! command -v "$PY" >/dev/null 2>&1; then
  printf '    FAIL - no CPython (%s) on PATH — required to run pyble_console host tests\n' "$PY"
  exit 1
fi

exec "$PY" "$HERE/host/test_pyble_console.py"

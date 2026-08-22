#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
#
# Wrapper so run_tests.sh (which globs test_*.sh) drives the F-25 rpi-pico2-w
# runner host suite (port spec P2/P3: validate-before-reserve, EBUSY-no-emit,
# on_stopped->IDLE, RSP-precedes-RUN_STATE, stopped->idle) under CPython.
# RED until agent-engineer grows firmware/pyble/pyble_runner.py [green].
# Exit non-zero on any failure.

set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"

PY="${PYBLE_PYTHON:-python3}"
if ! command -v "$PY" >/dev/null 2>&1; then
  printf '    FAIL - no CPython (%s) on PATH — required to run pyble_runner rp2 host tests\n' "$PY"
  exit 1
fi

exec "$PY" "$HERE/host/test_pyble_runner_rp2.py"

#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
#
# Wrapper so run_tests.sh (which globs test_*.sh) drives the F-01 `pyble_ble`
# PURE-helper host unit suite under CPython (NimBLE peripheral is HIL-deferred).
# RED until ble-transport-engineer lands firmware/pyble/pyble_ble.py [green].
# Exit non-zero on any failure.

set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"

PY="${PYBLE_PYTHON:-python3}"
if ! command -v "$PY" >/dev/null 2>&1; then
  printf '    FAIL - no CPython (%s) on PATH — required to run pyble_ble host tests\n' "$PY"
  exit 1
fi

exec "$PY" "$HERE/host/test_pyble_ble.py"

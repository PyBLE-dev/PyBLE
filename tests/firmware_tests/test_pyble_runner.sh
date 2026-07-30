#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
#
# Wrapper so run_tests.sh (globs test_*.sh) drives the pyble_runner host suite
# under CPython. [red] (Sprint S3) until the owning engineer lands the module
# [green]. DoR-BLOCKED banner is inside host/test_pyble_runner.py — commit [red]
# only after the gating protocol.md §6/§7/§9 freezes + specs.md FR mirror land.
# Exit non-zero on any failure.

set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"

PY="${PYBLE_PYTHON:-python3}"
if ! command -v "$PY" >/dev/null 2>&1; then
  printf '    FAIL - no CPython (%s) on PATH — required to run pyble_runner host tests\n' "$PY"
  exit 1
fi

exec "$PY" "$HERE/host/test_pyble_runner.py"

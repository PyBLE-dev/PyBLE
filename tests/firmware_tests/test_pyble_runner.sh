#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
#
# Wrapper so run_tests.sh (globs test_*.sh) drives the pyble_runner host suite
# under CPython. The file retains its original Sprint-S3 red→green provenance;
# the gating protocol sections and production module are now frozen/present.
# Exit non-zero on any failure.

set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"

PY="${PYBLE_PYTHON:-python3}"
if ! command -v "$PY" >/dev/null 2>&1; then
  printf '    FAIL - no CPython (%s) on PATH — required to run pyble_runner host tests\n' "$PY"
  exit 1
fi

exec "$PY" "$HERE/host/test_pyble_runner.py"

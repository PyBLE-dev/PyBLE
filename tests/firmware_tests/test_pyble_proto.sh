#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
#
# Wrapper so run_tests.sh (which globs test_*.sh) drives the F-02 `pyble_proto`
# host unit + PBLE/1 conformance suite under CPython. RED until protocol-engineer
# lands firmware/pyble/pyble_proto.py [green]. Exit non-zero on any failure.

set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"

PY="${PYBLE_PYTHON:-python3}"
if ! command -v "$PY" >/dev/null 2>&1; then
  printf '    FAIL - no CPython (%s) on PATH — required to run pyble_proto host tests\n' "$PY"
  exit 1
fi

exec "$PY" "$HERE/host/test_pyble_proto.py"

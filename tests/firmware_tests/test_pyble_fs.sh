#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
#
# Wrapper so run_tests.sh (globs test_*.sh) drives the F-25 pyble_fs host suite
# under CPython over a tmpdir root. [red] (rpi-pico2-w port, plan C2) until
# agent-engineer lands firmware/pyble/pyble_fs.py [green]. Frozen refs:
# protocol.md §5/§8, ports/rpi-pico2-w.md P2/P5/P6, C reference pble_fs.c.
# Exit non-zero on any failure.

set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"

PY="${PYBLE_PYTHON:-python3}"
if ! command -v "$PY" >/dev/null 2>&1; then
  printf '    FAIL - no CPython (%s) on PATH — required to run pyble_fs host tests\n' "$PY"
  exit 1
fi

exec "$PY" "$HERE/host/test_pyble_fs.py"

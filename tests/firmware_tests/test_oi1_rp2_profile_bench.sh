#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
#
# RED — host-only RP2 OI-1 runner discrimination. No BLE, tty, flash, or board.

set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
PY="${PYBLE_PYTHON:-python3}"

if ! command -v "$PY" >/dev/null 2>&1; then
  printf '    FAIL - no CPython (%s) on PATH — required for RP2 OI tests\n' "$PY"
  exit 1
fi

exec "$PY" "$HERE/host/test_oi1_rp2_profile_bench.py"

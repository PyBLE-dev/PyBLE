#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
#
# RED — exact Arm GNU RP2 ownership, attribution, and Eligible Compilation.
# Hermetic: no firmware build, network, serial device, or hardware access.

set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
PY="${PYBLE_PYTHON:-python3}"

if ! command -v "$PY" >/dev/null 2>&1; then
  printf '    FAIL - no CPython (%s) on PATH — required for ARM closure tests\n' "$PY"
  exit 1
fi

exec "$PY" "$HERE/host/test_rp2_arm_runtime_closure.py"

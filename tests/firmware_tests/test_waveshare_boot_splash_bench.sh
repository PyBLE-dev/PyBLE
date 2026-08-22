#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
#
# Host-only ADR-0024 splash HIL-tooling contract. Fake BLE/device/operator;
# never opens a BLE adapter, serial port, or connected board.

set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
PY="${PYBLE_PYTHON:-python3}"

if ! command -v "$PY" >/dev/null 2>&1; then
  printf '    FAIL - no CPython (%s) on PATH\n' "$PY"
  exit 1
fi

exec "$PY" "$HERE/host/test_waveshare_boot_splash_bench.py"

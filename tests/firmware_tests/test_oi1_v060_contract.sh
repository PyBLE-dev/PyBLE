#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
#
# RED — ADR-0033 five-profile OI-1 and release-CLI qualification contract.
# Hermetic: no BLE, serial device, firmware build, flash, or network access.

set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
PY="${PYBLE_PYTHON:-python3}"

if ! command -v "$PY" >/dev/null 2>&1; then
  printf '    FAIL - no CPython (%s) on PATH — required for v0.6 OI tests\n' "$PY"
  exit 1
fi

exec "$PY" "$HERE/host/test_oi1_v060_contract.py"

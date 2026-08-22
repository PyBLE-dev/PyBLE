#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
#
# Wrapper so run_tests.sh (which globs test_*.sh) drives the F-25 rpi-pico2-w
# `pyble_ble` increment (module-local numeric IRQ constants, never-raising irq
# dispatch, gatts_set_buffer/config(mtu=247) bindings, 4096-cap -> ERANGE path)
# under CPython. BTstack behaviour itself is NEVER faked — these tests exercise
# our own seams against recording module surfaces only. RED until
# ble-transport-engineer lands the plan-C6 increment in
# firmware/pyble/pyble_ble.py [green]. Exit non-zero on any failure.

set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"

PY="${PYBLE_PYTHON:-python3}"
if ! command -v "$PY" >/dev/null 2>&1; then
  printf '    FAIL - no CPython (%s) on PATH — required to run pyble_ble rp2 host tests\n' "$PY"
  exit 1
fi

exec "$PY" "$HERE/host/test_pyble_ble_rp2.py"

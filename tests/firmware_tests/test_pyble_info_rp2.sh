#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
#
# Wrapper so run_tests.sh (which globs test_*.sh) drives the F-25 rpi-pico2-w
# `pyble_info` increment (frozen §7 short-token caps with the [status]-prefixed
# HELLO RSP, chip rpi-pico2-w, chunk = mtu-18, device_id from unique_id, single
# payload source, _version.py sourcing) under CPython. RED until
# identity-engineer lands the plan-C7 rewrite of firmware/pyble/pyble_info.py
# [green]. Exit non-zero on any failure.

set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"

PY="${PYBLE_PYTHON:-python3}"
if ! command -v "$PY" >/dev/null 2>&1; then
  printf '    FAIL - no CPython (%s) on PATH — required to run pyble_info rp2 host tests\n' "$PY"
  exit 1
fi

exec "$PY" "$HERE/host/test_pyble_info_rp2.py"

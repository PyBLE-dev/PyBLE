#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
#
# Wrapper so run_tests.sh (which globs test_*.sh) drives the F-25 rpi-pico2-w
# `pyble_proto` increment (SET_AUTORUN 0x23 opcode parity + streaming CRC-32)
# under CPython. RED until protocol-engineer lands the plan-C5 increment in
# firmware/pyble/pyble_proto.py [green]. Exit non-zero on any failure.

set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"

PY="${PYBLE_PYTHON:-python3}"
if ! command -v "$PY" >/dev/null 2>&1; then
  printf '    FAIL - no CPython (%s) on PATH — required to run pyble_proto rp2 host tests\n' "$PY"
  exit 1
fi

exec "$PY" "$HERE/host/test_pyble_proto_opcode_parity.py"

#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
#
# Wrapper so run_tests.sh (which globs test_*.sh) drives the F-25 rpi-pico2-w
# agent wiring host suite (port spec P1/P2/P4: all §4 opcodes registered,
# dispatch wiring, EVT emit, disconnect keeps .pbltmp, transfers-during-RUN
# EBUSY, SOFT_REBOOT RSP-before-reset, idle STOP) under CPython. RED until
# agent-engineer lands firmware/pyble/pyble_agent.py [green]. Exit non-zero
# on any failure.

set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"

PY="${PYBLE_PYTHON:-python3}"
if ! command -v "$PY" >/dev/null 2>&1; then
  printf '    FAIL - no CPython (%s) on PATH — required to run pyble_agent host tests\n' "$PY"
  exit 1
fi

exec "$PY" "$HERE/host/test_pyble_agent.py"

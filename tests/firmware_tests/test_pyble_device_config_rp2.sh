#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
#
# Wrapper so run_tests.sh (globs test_*.sh) drives the rpi-pico2-w device-config
# persistence host suite (F-25 / port spec P1+P5) under CPython. [red] until
# rp2-agent-engineer grows firmware/pyble/pyble_device_config.py [green].
# The PURE scaffold surface stays covered by test_pyble_device_config.sh —
# this suite adds the /pyble_conf.json persistence + plumbing layer.
# Exit non-zero on any failure.

set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"

PY="${PYBLE_PYTHON:-python3}"
if ! command -v "$PY" >/dev/null 2>&1; then
  printf '    FAIL - no CPython (%s) on PATH — required to run pyble_device_config_rp2 host tests\n' "$PY"
  exit 1
fi

exec "$PY" "$HERE/host/test_pyble_device_config_rp2.py"

#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
#
# Host-only OI-1 HIL-tooling contract. Fake BLE/reset/clock transports; no board.

set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
PY="${PYBLE_PYTHON:-python3}"

if ! command -v "$PY" >/dev/null 2>&1; then
  printf '    FAIL - no CPython (%s) on PATH\n' "$PY"
  exit 1
fi

exec "$PY" "$HERE/host/test_oi1_profile_bench.py"

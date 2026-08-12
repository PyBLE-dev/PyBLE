#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
#
# RED — strict C3/Pico private-result validation and atomic V5 binding.
# Hermetic: no build, network, BLE, serial, USB, flash, or publication.

set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
PY="${PYBLE_PYTHON:-python3}"

if ! command -v "$PY" >/dev/null 2>&1; then
  printf '    FAIL - no CPython (%s) on PATH — required for v0.6 gate tests\n' "$PY"
  exit 1
fi

exec "$PY" "$HERE/host/test_release_v060_private_gates.py"

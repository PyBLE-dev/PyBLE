#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
#
# RED — heterogeneous v0.6 packaged-build verification routing.
# Hermetic: no build, network, BLE, serial device, flash, or publication.

set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
PY="${PYBLE_PYTHON:-python3}"

if ! command -v "$PY" >/dev/null 2>&1; then
  printf '    FAIL - no CPython (%s) on PATH — required for routing tests\n' "$PY"
  exit 1
fi

exec "$PY" "$HERE/host/test_release_v060_packaged_build_routing.py"

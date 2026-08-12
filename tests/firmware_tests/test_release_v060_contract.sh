#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
#
# RED — v0.6.0 five-profile qualified-release source and routing contract.
# Hermetic: no firmware build, network, serial device, or hardware access.

set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"

PY="${PYBLE_PYTHON:-python3}"
if ! command -v "$PY" >/dev/null 2>&1; then
  printf '    FAIL - no CPython (%s) on PATH — required for v0.6 release tests\n' "$PY"
  exit 1
fi

exec "$PY" "$HERE/host/test_release_v060_contract.py"

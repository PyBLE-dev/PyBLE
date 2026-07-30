#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
#
# Canonical host entrypoint for source and optional generated three-target
# runtime contracts. Generated checks run when PYBLE_BUILD_ROOT is complete.

set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
PY="${PYBLE_PYTHON:-python3}"

if ! command -v "$PY" >/dev/null 2>&1; then
  printf '    FAIL - no CPython (%s) on PATH — required for runtime-contract tests\n' "$PY"
  exit 1
fi

exec "$PY" "$HERE/host/test_target_runtime_contract.py"

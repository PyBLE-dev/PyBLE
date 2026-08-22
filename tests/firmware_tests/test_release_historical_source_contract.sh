#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
#
# [red] Revalidate retained firmware with its exact source-era contract while
# keeping the current release-source validation fail closed.

set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"

PY="${PYBLE_PYTHON:-python3}"
if ! command -v "$PY" >/dev/null 2>&1; then
  printf '    FAIL - no CPython (%s) on PATH — required for historical release-source tests\n' "$PY"
  exit 1
fi

exec "$PY" "$HERE/host/test_release_historical_source_contract.py"

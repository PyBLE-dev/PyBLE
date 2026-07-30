#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
#
# [red] X-03/X-11 — Hermetic adversarial tests for source-frozen builds,
# convergent preparation, and immutable release-bundle validation.

set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"

PY="${PYBLE_PYTHON:-python3}"
if ! command -v "$PY" >/dev/null 2>&1; then
  printf '    FAIL - no CPython (%s) on PATH — required for release hardening tests\n' "$PY"
  exit 1
fi

exec "$PY" "$HERE/host/test_release_hardening.py"

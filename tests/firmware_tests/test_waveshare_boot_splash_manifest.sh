#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
#
# ADR-0024 wrapper for S3-only splash manifest/source audit tests.

set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"

PY="${PYBLE_PYTHON:-python3}"
if ! command -v "$PY" >/dev/null 2>&1; then
  printf '    FAIL - no CPython (%s) on PATH — required for splash manifest tests\n' "$PY"
  exit 1
fi

exec "$PY" "$HERE/host/test_waveshare_boot_splash_manifest.py"

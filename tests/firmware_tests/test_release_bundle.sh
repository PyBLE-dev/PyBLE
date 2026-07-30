#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
#
# [red] X-10/X-11 — Browser-flashing release bundle gate (BLD-5…8, BLD-14,
# BLD-17…22). The CPython suite is hermetic: it creates synthetic ESP images,
# partition tables, build trees, dependency metadata, and bundles under a
# temporary directory. It never consumes or rewrites local firmware builds.

set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"

PY="${PYBLE_PYTHON:-python3}"
if ! command -v "$PY" >/dev/null 2>&1; then
  printf '    FAIL - no CPython (%s) on PATH — required for release-bundle tests\n' "$PY"
  exit 1
fi

exec "$PY" "$HERE/host/test_release_bundle.py"

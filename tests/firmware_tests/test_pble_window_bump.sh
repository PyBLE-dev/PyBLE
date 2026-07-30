#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
#
# Wrapper so run_tests.sh (globs test_*.sh) drives the native PUT sliding-window
# bump host coverage under CPython. [red] until the owning engineers land the
# constants [green]: identity-engineer (pble_info.c caps `window=` 4->8) and
# storage-engineer (pble_fs.c PBLE_FS_QDEPTH 6->10). A static-source assertion
# on the frozen FR-FS-4/NFR-PERF-2 (W=8) + FR-INFO-3 contract — no ESP-IDF, no
# hardware. Exit non-zero on any failure.

set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"

PY="${PYBLE_PYTHON:-python3}"
if ! command -v "$PY" >/dev/null 2>&1; then
  printf '    FAIL - no CPython (%s) on PATH — required to run the window-bump host tests\n' "$PY"
  exit 1
fi

exec "$PY" "$HERE/host/test_pble_window_bump.py"

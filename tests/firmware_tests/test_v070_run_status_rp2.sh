#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
set -eu
HERE="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
exec "${PYBLE_PYTHON:-python3}" "$HERE/host/test_v070_run_status_rp2.py"

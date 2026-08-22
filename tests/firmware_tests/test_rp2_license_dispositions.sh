#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.

set -eu

HERE="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
PYTHONDONTWRITEBYTECODE=1 python3 "$HERE/host/test_rp2_license_dispositions.py"

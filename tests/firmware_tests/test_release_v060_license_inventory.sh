#!/usr/bin/env sh
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
set -eu

HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PYTHON=${PYTHON:-python3}

exec "$PYTHON" "$HERE/host/test_release_v060_license_inventory.py"

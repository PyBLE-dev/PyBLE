#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
set -euo pipefail

here="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)"
python3 "$here/host/test_release_v060_rp2_depfile_closure.py"

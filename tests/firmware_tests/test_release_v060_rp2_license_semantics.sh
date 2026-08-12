#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
set -euo pipefail

here="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)"
status=0
python3 "$here/host/test_release_v060_rp2_license_semantics.py" || status=$?
python3 "$here/host/test_build_rp2_retained_source.py" || status=$?
exit "$status"

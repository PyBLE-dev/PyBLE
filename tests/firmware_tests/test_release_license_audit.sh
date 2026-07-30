#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
#
# Host entrypoint for the frozen BLD-8 repository, fixture, and behavior gates.

set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
PY="${PYTHON:-python3}"

exec "$PY" "$HERE/host/test_release_license_audit.py"

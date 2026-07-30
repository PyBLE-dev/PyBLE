#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
#
# Wrapper so run_tests.sh drives the HOST-RUNNABLE-NOW guard that the HIL bench's
# PBLE/1 wire codec (hil/_pble_wire.py) matches the shared cross-language corpus
# byte-for-byte. No hardware; runs on a plain CPython host.

set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
exec python3 "$HERE/host/conformance/test_hil_wire.py"

#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
#
# Host-gate umbrella (CON-6, NFR-MAINT-4, CON-12). Runs every gate that needs no
# ESP-IDF/hardware: no-leak, SPDX-header lint, and zero-patch policy. Mirrors the
# host-runnable subset of what CI enforces on every push/PR. Non-zero if any gate
# fails.
#
#   Usage:  check.sh

set -u

HERE="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
REPO_ROOT="$(cd "$HERE/../.." && pwd)"
CI="$REPO_ROOT/tools/ci"

rc=0
run() {
  echo "== $1 =="
  shift
  if "$@"; then :; else rc=1; fi
}

run "no-leak"        "$CI/no_leak.sh"
run "spdx-lint"      "$CI/spdx_lint.sh"
run "patches-policy" "$CI/patches_policy.sh"

echo "----------------------------------------"
if [ "$rc" -ne 0 ]; then
  echo "check: one or more host gates FAILED"
  exit 1
fi
echo "check: all host gates passed"
exit 0

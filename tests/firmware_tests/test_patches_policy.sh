#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
#
# [red] F-15 — Zero-patch policy (CON-12, BLD-15).
# AC: "The default upstream patch count is zero; any unavoidable patch lives
#      under firmware/patches/micropython-<tag>/ with a written reason, applies
#      only at build prep..."
#
# Contract asserted for the production gate (HAND-OFF: build-smith,
# tools/ci/patches_policy.sh):
#   patches_policy.sh [PATCHES_DIR]  — inspects PATCHES_DIR (default
#     firmware/patches); exit 0 if empty/absent OR every *.patch under a
#     micropython-<tag>/ subdir has a sibling non-empty REASON.md; exit non-zero
#     if any patch lacks a written reason.
#
# RED NOW: tools/ci/patches_policy.sh does not exist -> require_gate records a fail.

set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
. "$HERE/lib/common.sh"
. "$HERE/lib/assert.sh"
_ASSERT_NAME="test_patches_policy"

run() {
  require_gate "$PATCHES_POLICY" "build-smith · tools/ci/patches_policy.sh" || return 0

  # (a) Zero patches (the default) is accepted.
  local empty; empty="$(mk_tmp)"; mkdir -p "$empty/patches"
  check "patches_policy ACCEPTS an empty patches dir (default zero patches)" \
    "$PATCHES_POLICY" "$empty/patches"

  # (b) A patch with no written reason is refused.
  local bad; bad="$(mk_tmp)"; mkdir -p "$bad/patches/micropython-v1.28.0"
  printf -- '--- a\n+++ b\n@@ -1 +1 @@\n-x\n+y\n' > "$bad/patches/micropython-v1.28.0/nimble.patch"
  check_fail "patches_policy REFUSES a non-empty patch with no written REASON.md" \
    "$PATCHES_POLICY" "$bad/patches"

  # (c) A patch WITH a written reason is accepted.
  local good; good="$(mk_tmp)"; mkdir -p "$good/patches/micropython-v1.28.0"
  printf -- '--- a\n+++ b\n@@ -1 +1 @@\n-x\n+y\n' > "$good/patches/micropython-v1.28.0/nimble.patch"
  printf 'Reason: upstream bug #12345 breaks NimBLE MTU 247 on esp32c3.\n' \
    > "$good/patches/micropython-v1.28.0/REASON.md"
  check "patches_policy ACCEPTS a patch that carries a non-empty REASON.md" \
    "$PATCHES_POLICY" "$good/patches"

  rm -rf "$empty" "$bad" "$good"

  # The shipped patches dir must currently be empty (default zero patches).
  if [ -d "$REPO_ROOT/firmware/patches" ]; then
    local n
    n="$(find "$REPO_ROOT/firmware/patches" -name '*.patch' 2>/dev/null | wc -l | tr -d ' ')"
    check_eq "shipped firmware/patches carries zero .patch files" "0" "$n"
  else
    note "firmware/patches not present yet (build-smith scaffolds patches/.gitkeep)"
  fi
}

run
finish

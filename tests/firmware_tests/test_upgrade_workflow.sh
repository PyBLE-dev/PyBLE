#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
#
# [red] F-15 — Controlled upgrade bumps versions.lock in its own commit (BLD-9).
# AC: "upgrade_micropython.sh performs the controlled upgrade: bump
#      versions.lock in its own commit, rebuild mpy-cross, pass gates, validate
#      on all three chips before the pin is frozen."
#
# Contract asserted for the production script (HAND-OFF: build-smith,
# firmware/scripts/upgrade_micropython.sh):
#   upgrade_micropython.sh --dry-run <ref> <commit>  — prints the plan without
#     touching the working tree or creating a commit; the plan MUST state that
#     it edits versions.lock and lands it in a dedicated (own) commit. A real
#     run needs network + submodule and is DEFERRED to a toolchain machine.
#
# RED NOW: firmware/scripts/upgrade_micropython.sh does not exist.

set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
. "$HERE/lib/common.sh"
. "$HERE/lib/assert.sh"
_ASSERT_NAME="test_upgrade_workflow"

run() {
  require_gate "$UPGRADE_SH" "build-smith · firmware/scripts/upgrade_micropython.sh" || return 0

  local lock="$REPO_ROOT/firmware/versions.lock"
  local before_sum head_before out rc
  before_sum="$(shasum "$lock" 2>/dev/null | awk '{print $1}')"
  head_before="$(git -C "$REPO_ROOT" rev-parse HEAD 2>/dev/null)"

  out="$("$UPGRADE_SH" --dry-run v1.29.0 deadbeefdeadbeefdeadbeefdeadbeefdeadbeef 2>&1)"; rc=$?
  check_eq "upgrade --dry-run exits 0" "0" "$rc"

  printf '%s\n' "$out" | grep -qiE 'versions\.lock' \
    && pass "dry-run plan names versions.lock as the file it bumps" \
    || fail "dry-run plan must name versions.lock"

  printf '%s\n' "$out" | grep -qiE 'own commit|separate commit|dedicated commit|its own commit' \
    && pass "dry-run plan states the bump lands in its OWN commit (BLD-9)" \
    || fail "dry-run plan must state the bump lands in a dedicated/own commit"

  # A dry-run must not mutate the tracked lock nor create a commit.
  local after_sum head_after
  after_sum="$(shasum "$lock" 2>/dev/null | awk '{print $1}')"
  head_after="$(git -C "$REPO_ROOT" rev-parse HEAD 2>/dev/null)"
  check_eq "dry-run leaves versions.lock unmodified" "$before_sum" "$after_sum"
  check_eq "dry-run creates no new commit" "$head_before" "$head_after"

  note "DEFERRED: a real upgrade (fetch tag, rebuild mpy-cross, 3-chip validate) runs on a toolchain machine."
}

run
finish

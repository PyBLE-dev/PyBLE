#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
#
# [red] X-01 — DCO sign-off enforcement (CON-6 posture).
# AC: "DCO sign-off (git commit -s) is documented in CONTRIBUTING and required
#      for merge."
#
# Contract asserted for the production gate (HAND-OFF: build-smith,
# tools/ci/dco_check.sh):
#   dco_check.sh [REPO_DIR]  — inspects commit messages in REPO_DIR (default:
#     repo root) over the range in $PYBLE_DCO_RANGE (default: the PR range);
#     exits non-zero if any commit lacks a `Signed-off-by:` trailer, 0 if all
#     are signed.
# If build-smith instead enforces DCO via the GitHub DCO app (no host script),
# that is a routing decision to confirm — this test pins a host-runnable check.
#
# RED NOW: tools/ci/dco_check.sh does not exist -> require_gate records a fail.

set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
. "$HERE/lib/common.sh"
. "$HERE/lib/assert.sh"
_ASSERT_NAME="test_dco_signoff"

run() {
  require_gate "$DCO_CHECK" "build-smith · tools/ci/dco_check.sh (or confirm GitHub DCO app)" || return 0

  # GitHub checks out a synthetic merge commit for pull_request events. The DCO
  # range must stop at the contributor-owned PR head, otherwise the unsigned
  # GitHub-generated merge commit is incorrectly treated as contributor work.
  check "PR DCO range ends at the contributor-owned head SHA" \
    grep -Fq 'PYBLE_DCO_RANGE="origin/${{ github.base_ref }}..${{ github.event.pull_request.head.sha }}"' \
      "$REPO_ROOT/.github/workflows/ci.yml"

  # Build a throwaway repo with one signed and one unsigned commit.
  local tmp; tmp="$(mk_tmp)"
  git init -q "$tmp"
  local G=(git -C "$tmp" -c user.name=Test -c user.email=t@example.com -c commit.gpgsign=false)

  printf 'a\n' > "$tmp/a.txt"; "${G[@]}" add a.txt
  "${G[@]}" commit -q -s -m "signed commit" >/dev/null
  local signed_range; signed_range="$("${G[@]}" rev-parse HEAD)"

  # Signed-only history passes.
  check "dco_check PASSES a history where every commit is Signed-off-by" \
    env PYBLE_DCO_RANGE="${signed_range}~1..${signed_range}" "$DCO_CHECK" "$tmp"

  printf 'b\n' > "$tmp/b.txt"; "${G[@]}" add b.txt
  "${G[@]}" commit -q -m "unsigned commit (no -s)" >/dev/null
  local head; head="$("${G[@]}" rev-parse HEAD)"

  # A range containing the unsigned commit fails.
  check_fail "dco_check FAILS when a commit is missing Signed-off-by" \
    env PYBLE_DCO_RANGE="${head}~1..${head}" "$DCO_CHECK" "$tmp"

  rm -rf "$tmp"
}

run
finish

#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
#
# X-01 / CON-6 — DCO sign-off enforcement. Every commit in the inspected range
# must carry a `Signed-off-by:` trailer (produced by `git commit -s`, documented
# in CONTRIBUTING.md).
#
#   Usage:  dco_check.sh [REPO_DIR]        (REPO_DIR defaults to the repo root)
#   Range:  $PYBLE_DCO_RANGE selects the commits to inspect. If unset, defaults
#           to the PR range in CI (origin/<base>..HEAD) or HEAD~1..HEAD locally.
#   Exit:   non-zero if any inspected commit lacks Signed-off-by; 0 if all signed.

set -u

HERE="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
DIR="${1:-$(cd "$HERE/../.." && pwd)}"

# Resolve the commit range.
if [ -n "${PYBLE_DCO_RANGE:-}" ]; then
  RANGE="$PYBLE_DCO_RANGE"
elif [ -n "${GITHUB_BASE_REF:-}" ]; then
  RANGE="origin/${GITHUB_BASE_REF}..HEAD"
else
  RANGE="HEAD~1..HEAD"
fi

# rev-list the range; if the low endpoint is unreachable (e.g. root commit's
# parent), fall back to the range's endpoint alone so a single-commit history
# is still inspected instead of erroring out.
if ! commits="$(git -C "$DIR" rev-list "$RANGE" 2>/dev/null)"; then
  endpoint="${RANGE##*..}"
  commits="$(git -C "$DIR" rev-list "$endpoint" 2>/dev/null)" || commits=""
fi

if [ -z "$commits" ]; then
  echo "dco_check: no commits to inspect in range '$RANGE'"
  exit 0
fi

bad=0
for c in $commits; do
  if git -C "$DIR" log -1 --format='%B' "$c" \
       | grep -qiE '^[[:space:]]*Signed-off-by:[[:space:]]+.+<.+@.+>'; then
    :
  else
    subj="$(git -C "$DIR" log -1 --format='%h %s' "$c")"
    printf 'dco_check: missing Signed-off-by — %s\n' "$subj" >&2
    bad=1
  fi
done

if [ "$bad" -ne 0 ]; then
  echo "dco_check: one or more commits are not signed off (run: git commit -s --amend)" >&2
  exit 1
fi

echo "dco_check: all commits in '$RANGE' are Signed-off-by"
exit 0

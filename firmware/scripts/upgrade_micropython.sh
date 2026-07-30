#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
#
# F-15 / BLD-9 — Controlled MicroPython pin upgrade. This is the ONLY sanctioned
# way to move the pin (never hand-edit versions.lock mid-build). It bumps the
# [micropython] ref+commit in versions.lock in ITS OWN dedicated commit, then
# rebuilds mpy-cross and re-runs every gate before the new pin is trusted.
#
#   upgrade_micropython.sh <ref> <commit>            perform the upgrade
#   upgrade_micropython.sh --dry-run <ref> <commit>  print the plan; touch nothing
#
# The bump lands in its own commit so the pin change is atomic and revertible; a
# real upgrade also fetches the tag, rebuilds mpy-cross, runs the gate suite, and
# is validated on all three chips before the pin is frozen (architect decides the
# freeze — OI-2).

set -u

HERE="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
FW="$(cd "$HERE/.." && pwd)"
REPO_ROOT="$(cd "$FW/.." && pwd)"
LOCK="$FW/versions.lock"
UPSTREAM_DIR="$FW/upstream/micropython"

DRY=0
if [ "${1:-}" = "--dry-run" ]; then
  DRY=1
  shift
fi

REF="${1:-}"
COMMIT="${2:-}"
if [ -z "$REF" ] || [ -z "$COMMIT" ]; then
  echo "usage: upgrade_micropython.sh [--dry-run] <ref> <commit>" >&2
  exit 2
fi

if [ "$DRY" -eq 1 ]; then
  cat <<EOF
# upgrade plan (dry-run — nothing is modified, no commit is created)
target pin : MicroPython $REF ($COMMIT)
step 1     : edit firmware/versions.lock — set [micropython] ref="$REF", commit="$COMMIT"
step 2     : commit versions.lock in ITS OWN dedicated commit
             git commit -s firmware/versions.lock -m "[chore] bump MicroPython pin to $REF"
step 3     : git submodule update --init; checkout $COMMIT; verify SHA (sha_drift gate)
step 4     : rebuild mpy-cross from the new pin
step 5     : re-run the full gate suite (no-leak, spdx, sha-drift, patches, build matrix)
step 6     : validate on all three chips (esp32 / esp32-s3 / esp32-c3) before the
             architect freezes the pin
note       : the versions.lock bump is isolated in its own commit so the pin move
             is atomic and revertible.
EOF
  exit 0
fi

# ---- Real upgrade ----------------------------------------------------------
if ! git -C "$REPO_ROOT" diff --quiet -- "$LOCK"; then
  echo "upgrade: firmware/versions.lock has uncommitted changes — commit or stash first" >&2
  exit 1
fi

tmp="$LOCK.tmp.$$"
awk -v ref="$REF" -v commit="$COMMIT" '
  /^\[/ { insec = ($0 == "[micropython]") }
  insec && /^[[:space:]]*ref[[:space:]]*=/    { print "ref    = \"" ref "\""; next }
  insec && /^[[:space:]]*commit[[:space:]]*=/ { print "commit = \"" commit "\""; next }
  { print }
' "$LOCK" > "$tmp"
mv "$tmp" "$LOCK"

git -C "$REPO_ROOT" add "$LOCK"
git -C "$REPO_ROOT" commit -s -m "[chore] bump MicroPython pin to $REF" -- "$LOCK"
echo "upgrade: versions.lock bumped to $REF ($COMMIT) in its own commit"

git -C "$REPO_ROOT" submodule update --init "$UPSTREAM_DIR" || true
git -C "$UPSTREAM_DIR" fetch --tags origin
git -C "$UPSTREAM_DIR" checkout "$COMMIT"

"$REPO_ROOT/tools/ci/sha_drift.sh" || { echo "upgrade: SHA-drift after bump — aborting" >&2; exit 1; }
make -C "$UPSTREAM_DIR/mpy-cross" || { echo "upgrade: mpy-cross rebuild failed" >&2; exit 1; }
"$HERE/check.sh" || { echo "upgrade: host gates failed after bump" >&2; exit 1; }

echo "upgrade: pin moved to $REF. Now validate all three chips before the architect freezes it."
exit 0

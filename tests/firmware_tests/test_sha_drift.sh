#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
#
# [red] X-03 — SHA-drift build gate (BLD-1, BLD-2).
# AC: "Build prep verifies the checked-out submodule SHA against versions.lock
#      and refuses to proceed on mismatch; the SHA-drift gate runs on every PR."
#
# Contract asserted for the production gate (HAND-OFF: build-smith,
# tools/ci/sha_drift.sh):
#   sha_drift.sh  — reads the [micropython] commit from $PYBLE_LOCK_FILE
#     (default firmware/versions.lock) and compares it to
#     `git -C $PYBLE_UPSTREAM_DIR rev-parse HEAD`
#     (default firmware/upstream/micropython). Exit 0 iff equal; exit non-zero
#     on mismatch OR when the submodule is absent/uninitialized.
#
# Hermetic: uses a fake temp git repo as the "submodule" and a fake lock, via
# the PYBLE_* env overrides — no 150 MB fetch.
#
# RED NOW: tools/ci/sha_drift.sh does not exist -> require_gate records a fail.

set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
. "$HERE/lib/common.sh"
. "$HERE/lib/assert.sh"
_ASSERT_NAME="test_sha_drift"

write_lock() { # $1=path $2=commit
  cat > "$1" <<EOF
[micropython]
repo   = "https://github.com/micropython/micropython"
ref    = "v1.28.0"
commit = "$2"
EOF
}

run() {
  require_gate "$SHA_DRIFT" "build-smith · tools/ci/sha_drift.sh" || return 0

  local tmp; tmp="$(mk_tmp)"
  local up="$tmp/up"
  git init -q "$up"
  local G=(git -C "$up" -c user.name=Test -c user.email=t@example.com -c commit.gpgsign=false)
  printf 'x\n' > "$up/f"; "${G[@]}" add f; "${G[@]}" commit -q -m init >/dev/null
  local real_sha; real_sha="$("${G[@]}" rev-parse HEAD)"

  # (a) Match: lock commit == checked-out HEAD -> proceed (exit 0).
  write_lock "$tmp/lock_match" "$real_sha"
  check "sha_drift PROCEEDS when checked-out SHA equals versions.lock" \
    env PYBLE_LOCK_FILE="$tmp/lock_match" PYBLE_UPSTREAM_DIR="$up" "$SHA_DRIFT"

  # (b) Mismatch: lock commit != HEAD -> refuse (exit non-zero).
  write_lock "$tmp/lock_drift" "0000000000000000000000000000000000000000"
  check_fail "sha_drift REFUSES when checked-out SHA differs from versions.lock" \
    env PYBLE_LOCK_FILE="$tmp/lock_drift" PYBLE_UPSTREAM_DIR="$up" "$SHA_DRIFT"

  # (c) Uninitialized submodule (no git repo) -> refuse.
  local empty="$tmp/empty"; mkdir -p "$empty"
  write_lock "$tmp/lock_any" "$real_sha"
  check_fail "sha_drift REFUSES when the submodule is absent/uninitialized" \
    env PYBLE_LOCK_FILE="$tmp/lock_any" PYBLE_UPSTREAM_DIR="$empty" "$SHA_DRIFT"

  rm -rf "$tmp"
}

run
finish

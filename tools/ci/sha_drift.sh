#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
#
# X-03 — SHA-drift build gate (BLD-1, BLD-2). versions.lock is the single source
# of truth for the MicroPython pin; the build refuses to proceed unless the
# checked-out submodule HEAD matches the [micropython] commit in the lock.
#
#   Env:  PYBLE_LOCK_FILE     lock to read (default firmware/versions.lock)
#         PYBLE_UPSTREAM_DIR  submodule dir  (default firmware/upstream/micropython)
#   Exit: 0 iff checked-out HEAD == lock commit; non-zero on mismatch OR when the
#         submodule is absent/uninitialized (never proceeds on drift).

set -u

HERE="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
REPO_ROOT="$(cd "$HERE/../.." && pwd)"

LOCK="${PYBLE_LOCK_FILE:-$REPO_ROOT/firmware/versions.lock}"
UP="${PYBLE_UPSTREAM_DIR:-$REPO_ROOT/firmware/upstream/micropython}"

if [ ! -f "$LOCK" ]; then
  echo "sha_drift: versions.lock not found at $LOCK" >&2
  exit 1
fi

# Pull the commit from the [micropython] section only (the lock also pins ESP-IDF).
want="$(awk -F'"' '
  /^\[micropython\]/ { f=1; next }
  /^\[/              { f=0 }
  f && /^[[:space:]]*commit[[:space:]]*=/ { print $2; exit }
' "$LOCK")"

if [ -z "$want" ]; then
  echo "sha_drift: no [micropython] commit pin found in $LOCK" >&2
  exit 1
fi

# The submodule must actually be initialized: a bare/empty dir has no .git, and
# rev-parse would otherwise walk up to the outer repo and report a wrong SHA.
if [ ! -e "$UP/.git" ]; then
  echo "sha_drift: MicroPython submodule not initialized at $UP" >&2
  echo "  run: git submodule update --init firmware/upstream/micropython" >&2
  exit 1
fi

if ! got="$(git -C "$UP" rev-parse HEAD 2>/dev/null)"; then
  echo "sha_drift: cannot read HEAD of the submodule at $UP (uninitialized?)" >&2
  echo "  run: git submodule update --init firmware/upstream/micropython" >&2
  exit 1
fi

if [ "$want" = "$got" ]; then
  echo "sha_drift: OK — submodule HEAD matches versions.lock ($got)"
  exit 0
fi

echo "sha_drift: DRIFT — refusing to build" >&2
echo "  versions.lock [micropython] commit = $want" >&2
echo "  checked-out submodule HEAD          = $got" >&2
echo "  reconcile via firmware/scripts/upgrade_micropython.sh (never hand-edit mid-build)" >&2
exit 1

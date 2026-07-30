#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
#
# F-15 — Zero-patch policy (CON-12, BLD-15). The default upstream patch count is
# ZERO. Any unavoidable patch must live under firmware/patches/micropython-<tag>/
# with a written reason (a non-empty sibling REASON.md), applied only at build
# prep and re-reviewed for retirement at every upgrade.
#
#   Usage:  patches_policy.sh [PATCHES_DIR]   (default firmware/patches)
#   Exit:   0 if the dir is empty/absent OR every *.patch has a non-empty
#           REASON.md beside it; non-zero if any patch lacks a written reason.

set -u

HERE="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
REPO_ROOT="$(cd "$HERE/../.." && pwd)"

DIR="${1:-$REPO_ROOT/firmware/patches}"

# Absent or empty patches dir == the default (zero patches) == accepted.
if [ ! -d "$DIR" ]; then
  echo "patches_policy: no patches dir ($DIR) — default zero patches, OK"
  exit 0
fi

bad=0
found=0
while IFS= read -r p; do
  found=1
  d="$(dirname "$p")"
  if [ -s "$d/REASON.md" ]; then
    echo "patches_policy: '$p' documented by $d/REASON.md"
  else
    echo "patches_policy: '$p' has NO non-empty REASON.md — refused (CON-12/BLD-15)" >&2
    bad=1
  fi
done < <(find "$DIR" -type f -name '*.patch' 2>/dev/null)

if [ "$bad" -ne 0 ]; then
  echo "patches_policy: every patch must carry a written reason (micropython-<tag>/REASON.md)" >&2
  exit 1
fi

if [ "$found" -eq 0 ]; then
  echo "patches_policy: zero patches (default) — OK"
else
  echo "patches_policy: all patches carry a written reason — OK"
fi
exit 0

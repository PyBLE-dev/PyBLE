#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
#
# [red] F-15 — Pristine pinned submodule + ESP-IDF is gitignored, not a submodule
#              (CON-1/2, BLD-11).
# AC:
#  - Upstream MicroPython is a pinned git submodule, never edited in place.
#  - ESP-IDF is installed from the pin into a gitignored directory, not an outer
#    submodule.
#
# Host-verifiable slice (the actual pristine 150 MB checkout is DEFERRED):
#  - .gitmodules exists at root and declares firmware/upstream/micropython at
#    the MicroPython URL.
#  - .gitmodules does NOT declare esp-idf (IDF must not be a submodule).
#  - .gitignore ignores the ESP-IDF install/tools dir.
#
# RED NOW: .gitmodules is MISSING at root (build-smith adds it with the submodule).

set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
. "$HERE/lib/common.sh"
. "$HERE/lib/assert.sh"
_ASSERT_NAME="test_submodule_idf"

run() {
  local gm="$REPO_ROOT/.gitmodules"

  if [ -f "$gm" ]; then
    pass ".gitmodules exists at repo root"
    check_grep ".gitmodules declares firmware/upstream/micropython" \
      "path *= *firmware/upstream/micropython" "$gm"
    check_grep ".gitmodules points at the MicroPython upstream URL" \
      "github\.com/micropython/micropython" "$gm"
    if grep -qiE 'esp-?idf' "$gm"; then
      fail "ESP-IDF must NOT be a submodule (found esp-idf in .gitmodules)"
    else
      pass "ESP-IDF is not declared as a submodule in .gitmodules (BLD-11)"
    fi
  else
    fail "MISSING .gitmodules at repo root — HAND-OFF: build-smith (git submodule add micropython)"
  fi

  # ESP-IDF install/tools dir must be gitignored (not tracked, not a submodule).
  check_grep ".gitignore ignores the ESP-IDF tools/install dir" \
    "\.idf_tools/|esp-idf|idf_install" "$REPO_ROOT/.gitignore"

  # Pristine-submodule rationale is documented.
  check_grep "upstream/README documents 'never edit ... in place'" \
    "never edit" "$REPO_ROOT/firmware/upstream/README.md"

  note "DEFERRED: proving the checked-out submodule is byte-pristine needs the real fetch on a toolchain machine."
}

run
finish

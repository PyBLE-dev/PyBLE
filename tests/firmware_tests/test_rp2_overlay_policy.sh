#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
#
# [red] F-26 — PYBLE_RPI_PICO2_W overlay policy (port spec ports/rpi-pico2-w.md
# P9; ADR-0030; firmware.md §4.1/§6).
# AC:
#  - firmware/board_overlays/rpi-pico2-w/ holds EXACTLY the five frozen files:
#    _boot.py, manifest.py, mpconfigboard.cmake, mpconfigboard.h,
#    mpconfigvariant.cmake — nothing else, no partitions.csv (rp2 has none).
#  - manifest.py never freezes $(PORT_DIR)/modules wholesale; it DOES freeze
#    the overlay _boot.py from $(BOARD_DIR) and the copied-in pyble package
#    (the agent is image-embedded, never a user-deletable vfs file).
#  - mpconfigvariant.cmake pins PICO_PLATFORM to rp2350 (mandatory: it is only
#    loaded from the board dir by the upstream rp2 CMake).
#  - _boot.py has NO vfs main.py start path (autorun is the agent's
#    maybe_autorun contract, cold-boot safe — never an unstoppable main.py).
#  - prepare.sh rpi-pico2-w lands ports/rp2/boards/PYBLE_RPI_PICO2_W/ (with
#    the pyble package copied alongside), copies NO partitions.csv anywhere,
#    and leaves the upstream tracked tree pristine (CON-1/CON-4 pattern).
#    Verified against a shared-object clone of the pinned submodule so the
#    test never mutates the real checkout.
#
# RED NOW: the overlay directory does not exist and prepare.sh rejects the
# rpi-pico2-w target.

set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
. "$HERE/lib/common.sh"
. "$HERE/lib/assert.sh"
_ASSERT_NAME="test_rp2_overlay_policy"

OVERLAY="$REPO_ROOT/firmware/board_overlays/rpi-pico2-w"

check_overlay_files() {
  if [ ! -d "$OVERLAY" ]; then
    fail "MISSING overlay dir: $OVERLAY — HAND-OFF: build-smith · firmware/board_overlays/rpi-pico2-w/"
    return 1
  fi

  local got want
  got="$(ls -1 "$OVERLAY" | LC_ALL=C sort | tr '\n' ' ')"
  want="_boot.py manifest.py mpconfigboard.cmake mpconfigboard.h mpconfigvariant.cmake "
  check_eq "overlay holds exactly the five frozen files (P9)" "$want" "$got"

  # manifest: never wholesale-freeze the port modules dir (that would drag in
  # upstream extras and hide what the image actually ships).
  if grep -qE 'freeze\([^)]*PORT_DIR[^)]*/modules' "$OVERLAY/manifest.py" 2>/dev/null; then
    fail "manifest.py must NOT freeze \$(PORT_DIR)/modules wholesale"
  else
    pass "manifest.py has no wholesale freeze of \$(PORT_DIR)/modules"
  fi
  check_grep "manifest.py freezes the overlay _boot.py from \$(BOARD_DIR)" \
    '_boot\.py.*BOARD_DIR|BOARD_DIR.*_boot\.py' "$OVERLAY/manifest.py"
  check_grep "manifest.py freezes the pyble agent package (image-embedded agent)" \
    'pyble' "$OVERLAY/manifest.py"

  # variant: PICO_PLATFORM must be pinned to rp2350 from the board dir.
  check_grep "mpconfigvariant.cmake sets PICO_PLATFORM to rp2350" \
    'PICO_PLATFORM[^)]*rp2350' "$OVERLAY/mpconfigvariant.cmake"

  # _boot.py: the agent supervisor owns the main thread; a vfs main.py start
  # path would defeat cold-boot safety (firmware.md §5) — comments excluded.
  if grep -vE '^[[:space:]]*#' "$OVERLAY/_boot.py" 2>/dev/null | grep -q 'main\.py'; then
    fail "_boot.py must not start a vfs main.py (autorun is the agent's job)"
  else
    pass "_boot.py has no vfs main.py start path"
  fi

  # No ESP-style partition table in the rp2 overlay.
  if [ -e "$OVERLAY/partitions.csv" ]; then
    fail "rp2 overlay must not carry a partitions.csv"
  else
    pass "overlay carries no partitions.csv (rp2 has no ESP partition table)"
  fi
  return 0
}

check_prepare_lands_board() {
  require_gate "$PREPARE_SH" "build-smith · firmware/scripts/prepare.sh" || return 0

  # Cheap red guard: prepare.sh must know the target at all before we spend a
  # clone on the behavioural check.
  if ! grep -q 'rpi-pico2-w' "$PREPARE_SH"; then
    fail "prepare.sh must accept the rpi-pico2-w target (port dimension, X-13)"
    return 0
  fi

  # Behavioural: run prepare against a shared-object clone of the pinned
  # submodule (HEAD == the [micropython] pin, so the SHA-drift gate is real),
  # keeping the developer's checkout untouched.
  local tmp up out rc
  tmp="$(mk_tmp)"; up="$tmp/micropython"
  if ! git clone -q -s "$REPO_ROOT/firmware/upstream/micropython" "$up" 2>/dev/null; then
    fail "cannot clone the pinned MicroPython submodule for the prepare check"
    rm -rf "$tmp"
    return 0
  fi

  out="$(PYBLE_UPSTREAM_DIR="$up" "$PREPARE_SH" rpi-pico2-w 2>&1)"; rc=$?
  check_eq "prepare.sh rpi-pico2-w exits 0 against the pinned tree" "0" "$rc"
  if [ "$rc" -ne 0 ]; then
    printf '    ..   - prepare.sh said: %s\n' "$(printf '%s' "$out" | tail -1)"
    rm -rf "$tmp"
    return 0
  fi

  local dst="$up/ports/rp2/boards/PYBLE_RPI_PICO2_W"
  if [ -d "$dst" ]; then
    pass "prepare.sh lands ports/rp2/boards/PYBLE_RPI_PICO2_W/"
  else
    fail "prepare.sh must land ports/rp2/boards/PYBLE_RPI_PICO2_W/ (got none)"
  fi
  check_file "landed board dir has mpconfigboard.cmake"    "$dst/mpconfigboard.cmake"
  check_file "landed board dir has mpconfigvariant.cmake"  "$dst/mpconfigvariant.cmake"
  check_file "landed board dir has mpconfigboard.h"        "$dst/mpconfigboard.h"
  check_file "landed board dir has manifest.py"            "$dst/manifest.py"
  check_file "landed board dir has _boot.py"               "$dst/_boot.py"
  if [ -d "$dst/pyble" ]; then
    pass "prepare.sh copies the pyble package alongside for the manifest freeze"
  else
    fail "prepare.sh must copy firmware/pyble into the board dir (manifest freeze input)"
  fi

  # rp2 must copy NO partitions.csv — not into the port dir, not into the board.
  if [ -e "$up/ports/rp2/partitions.csv" ] || [ -e "$dst/partitions.csv" ]; then
    fail "prepare.sh rpi-pico2-w must copy no partitions.csv (ESP-only input)"
  else
    pass "prepare.sh rpi-pico2-w copies no partitions.csv"
  fi

  # Submodule stays pristine: copy-in only, never an edit of tracked files.
  if git -C "$up" diff --quiet --ignore-submodules=untracked -- 2>/dev/null; then
    pass "upstream tracked tree stays pristine after prepare (CON-1)"
  else
    fail "prepare.sh must never modify tracked upstream files (CON-1)"
  fi

  rm -rf "$tmp"
}

run() {
  check_overlay_files || :
  check_prepare_lands_board
}

run
finish

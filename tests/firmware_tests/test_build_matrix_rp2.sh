#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
#
# [red] X-13 — rp2 build plane (port spec ports/rpi-pico2-w.md P9, RP2-BLD;
# ADR-0030). Mirrors test_build_matrix.sh for the sibling build_rp2.sh.
# AC:
#  - build_rp2.sh --plan rpi-pico2-w is TOOLCHAIN-FREE (exit 0 with no ARM GNU
#    install) and prints: board PYBLE_RPI_PICO2_W, the artifact set
#    firmware.uf2 firmware.elf firmware.bin pyble-build-provenance.json, and
#    the hard image-size gate 1572864.
#  - Unknown / missing target -> non-zero with a clean message.
#  - A REAL build with the pinned ARM GNU toolchain MISSING or VERSION-
#    MISMATCHED fails cleanly (BLD-4 equivalent) — never a silent substitution
#    of whatever arm-none-eabi-gcc is first on PATH, never fake success.
#  - The target -> board lookup reads versions.lock [targets_rp2] (behavioural:
#    a lock with the section stripped must make the plan fail).
#  - The RP2 plane preserves the already-integrated ESP inputs and four logical
#    variants. The build.sh --plan esp32 contract remains unchanged (modulo the
#    inherently per-commit source_commit/source_date_epoch lines).
#
# Contract asserted for the production script (HAND-OFF: build-smith,
# firmware/scripts/build_rp2.sh):
#   build_rp2.sh --plan <target>  — dry-run, needs NO ARM toolchain; exit 0.
#   build_rp2.sh <target>         — real build; honors PYBLE_LOCK_FILE and
#     PYBLE_ARM_TOOLCHAIN_DIR (the pinned install root, default
#     firmware/.arm-gnu; gcc at <dir>/bin/arm-none-eabi-gcc) and verifies the
#     compiler against versions.lock [arm_gnu_toolchain] gcc_version, else
#     fails with an actionable message.
#
# RED NOW: firmware/scripts/build_rp2.sh does not exist and versions.lock has
# no [targets_rp2] section.

set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
. "$HERE/lib/common.sh"
. "$HERE/lib/assert.sh"
_ASSERT_NAME="test_build_matrix_rp2"

BUILD_RP2="${PYBLE_BUILD_RP2:-$REPO_ROOT/firmware/scripts/build_rp2.sh}"
LOCK="$REPO_ROOT/firmware/versions.lock"

# lock_section <name> — the section's header + non-comment, non-blank lines.
lock_section() {
  awk -v s="[$1]" '
    /^\[/ { f = ($0 == s) }
    f && $0 !~ /^[[:space:]]*(#|$)/ { print }
  ' "$LOCK"
}

# ---- versions.lock: rp2 additions preserve integrated ESP source inputs ----
check_lock() {
  check_grep "versions.lock gains a [targets_rp2] section (X-13)" \
    '^\[targets_rp2\]' "$LOCK"
  check_grep "versions.lock [targets_rp2] maps rpi-pico2-w -> RPI_PICO2_W" \
    '^"rpi-pico2-w"[[:space:]]*=[[:space:]]*"RPI_PICO2_W"' "$LOCK"
  check_grep "versions.lock gains an [arm_gnu_toolchain] pin section (BLD-4 eq)" \
    '^\[arm_gnu_toolchain\]' "$LOCK"
  check_grep "combined source reserves agent version 0.6.0" \
    '^agent_version[[:space:]]*=[[:space:]]*"0\.6\.0"' "$LOCK"

  # The ESP input sections remain exact (normalized to their key/value lines
  # so an appended rp2 comment block cannot false-fail this).
  local got want
  got="$(lock_section micropython; lock_section esp_idf; lock_section targets; lock_section toolchain)"
  want='[micropython]
repo   = "https://github.com/micropython/micropython"
ref    = "v1.28.0"
commit = "e0e9fbb17ed6fd06bb76e266ae554784c9c80804"
[esp_idf]
repo   = "https://github.com/espressif/esp-idf"
ref    = "v5.5.1"
commit = "fcae32885b0296b32044cb99ecbdc50d98dddb83"
[targets]
"esp32"    = "esp32"
"esp32-s3" = "esp32s3"
"waveshare-esp32-s3-lcd-147b" = "esp32s3"
"esp32-c3" = "esp32c3"
[toolchain]
source    = "pinned-esp-idf"
mpy_cross = "rebuilt-from-pinned-micropython"'
  if [ "$got" = "$want" ]; then
    pass "versions.lock preserves the integrated four-variant ESP source inputs"
  else
    fail "versions.lock ESP source inputs changed while adding the rp2 plane"
  fi
}

# ---- build.sh --plan esp32 output is unchanged by the rp2 build plane -------
check_esp32_plan_regression() {
  require_gate "$BUILD_SH" "build-smith · firmware/scripts/build.sh" || return 0
  local plan rc
  plan="$("$BUILD_SH" --plan esp32 2>&1)"; rc=$?
  check_eq "build.sh --plan esp32 still exits 0" "0" "$rc"
  printf '%s\n' "$plan" | grep -qE '^source_commit=[0-9a-f]{40}$' \
    && pass "esp32 plan keeps its source_commit line" \
    || fail "esp32 plan must keep its source_commit=<40-hex> line"
  printf '%s\n' "$plan" | grep -qE '^source_date_epoch=[0-9]+$' \
    && pass "esp32 plan keeps its source_date_epoch line" \
    || fail "esp32 plan must keep its source_date_epoch=<int> line"
  # Byte-identical modulo the two per-commit lines and the absolute repo prefix.
  local got want
  got="$(printf '%s\n' "$plan" \
    | grep -vE '^source_(commit|date_epoch)=' \
    | sed "s|$REPO_ROOT/||g")"
  want='# build plan (dry-run; no ESP-IDF required)
target=esp32
idf_target=esp32
overlay=firmware/board_overlays/esp32
pin_lock=firmware/versions.lock
output_root=firmware/build
artifacts: firmware.bin micropython.bin micropython.elf bootloader.bin partition-table.bin flasher_args.json pyble-build-provenance.json'
  if [ "$got" = "$want" ]; then
    pass "build.sh --plan esp32 preserves the integrated contract"
  else
    fail "build.sh --plan esp32 output changed — the rp2 plane must not touch it"
  fi
}

check_build_rp2() {
  require_gate "$BUILD_RP2" "build-smith · firmware/scripts/build_rp2.sh" || return 0

  # Unknown / missing target rejected (fail-clean contract shared with build.sh).
  check_fail "build_rp2.sh rejects an unknown target"    "$BUILD_RP2" --plan bogus-9000
  check_fail "build_rp2.sh rejects a missing target arg" "$BUILD_RP2" --plan

  # Plan is toolchain-free: force an empty pinned-toolchain dir and expect 0.
  local plan rc
  plan="$(PYBLE_ARM_TOOLCHAIN_DIR="$(mk_tmp)" "$BUILD_RP2" --plan rpi-pico2-w 2>&1)"; rc=$?
  check_eq "build_rp2.sh --plan rpi-pico2-w exits 0 with NO ARM toolchain installed" "0" "$rc"
  printf '%s\n' "$plan" | grep -qE 'PYBLE_RPI_PICO2_W' \
    && pass "plan resolves board PYBLE_RPI_PICO2_W" \
    || fail "plan must print the board PYBLE_RPI_PICO2_W"
  local art
  for art in 'firmware\.uf2' 'firmware\.elf' 'firmware\.bin' 'pyble-build-provenance\.json'; do
    printf '%s\n' "$plan" | grep -qE "$art" \
      && pass "plan lists artifact $art (P9)" \
      || fail "plan must list artifact $art"
  done
  printf '%s\n' "$plan" | grep -qE '1572864' \
    && pass "plan surfaces the hard image-size gate 1572864 (P9)" \
    || fail "plan must surface the 1,572,864-byte size gate"

  # Board lookup goes through versions.lock [targets_rp2], not a hardcode:
  # with the section stripped from the lock, the plan MUST fail.
  local tmp stripped
  tmp="$(mk_tmp)"; stripped="$tmp/versions.lock"
  awk '
    /^\[targets_rp2\]/ { skip=1; next }
    /^\[/              { skip=0 }
    !skip              { print }
  ' "$LOCK" > "$stripped"
  if PYBLE_LOCK_FILE="$stripped" "$BUILD_RP2" --plan rpi-pico2-w >/dev/null 2>&1; then
    fail "build_rp2.sh must fail when the lock has no [targets_rp2] (lookup must use the lock)"
  else
    pass "build_rp2.sh board lookup reads versions.lock [targets_rp2] (fails without it)"
  fi

  # Never fake a build: a REAL build with the pinned toolchain MISSING must
  # fail cleanly — even though an unpinned arm-none-eabi-gcc may be on PATH.
  local out
  out="$(PYBLE_ARM_TOOLCHAIN_DIR="$(mk_tmp)" "$BUILD_RP2" rpi-pico2-w 2>&1)"; rc=$?
  if [ "$rc" -ne 0 ]; then
    pass "real build with no pinned ARM toolchain exits non-zero (never substitutes PATH)"
  else
    fail "build_rp2.sh rpi-pico2-w must NOT exit 0 without the pinned ARM toolchain"
  fi
  printf '%s\n' "$out" | grep -qiE 'arm-none-eabi|arm[- ]gnu|toolchain|install_arm_toolchain|not (installed|found)' \
    && pass "missing-toolchain failure message is actionable" \
    || fail "build_rp2.sh must explain the missing pinned ARM toolchain (actionable)"
  printf '%s\n' "$out" | grep -qiE 'build_rp2\.sh: OK|success' \
    && fail "missing-toolchain failure must not print success" \
    || pass "missing-toolchain failure prints no success line"

  # Version-mismatched toolchain: present but wrong gcc — verify-or-fail, never
  # a silent substitution (BLD-4 equivalent against [arm_gnu_toolchain]).
  local fake
  fake="$(mk_tmp)"
  mkdir -p "$fake/bin"
  printf '#!/bin/sh\necho "arm-none-eabi-gcc (Fake GNU Toolchain) 99.9.9"\nexit 0\n' \
    > "$fake/bin/arm-none-eabi-gcc"
  chmod +x "$fake/bin/arm-none-eabi-gcc"
  out="$(PYBLE_ARM_TOOLCHAIN_DIR="$fake" "$BUILD_RP2" rpi-pico2-w 2>&1)"; rc=$?
  if [ "$rc" -ne 0 ]; then
    pass "real build with a version-mismatched arm-none-eabi-gcc exits non-zero"
  else
    fail "build_rp2.sh must refuse a gcc that disagrees with [arm_gnu_toolchain]"
  fi
  printf '%s\n' "$out" | grep -qiE 'version|mismatch|pinned|14\.2' \
    && pass "mismatched-toolchain failure names the version/pin problem" \
    || fail "build_rp2.sh must name the gcc-version mismatch against the lock pin"
}

run() {
  check_lock
  check_esp32_plan_regression
  check_build_rp2
}

run
finish

#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
#
# X-13 — rp2 per-target firmware build (port spec ports/rpi-pico2-w.md P9,
# RP2-BLD; ADR-0030). Sibling of build.sh with the same --plan/fail-clean
# contract; the frozen three-ESP build.sh/build_all.sh contracts are untouched.
#
#   build_rp2.sh <target>          real build: prep (SHA-drift + overlay +
#                                  patches), verify the PINNED ARM GNU
#                                  toolchain, rebuild mpy-cross, invoke the rp2
#                                  port with the frozen manifest, and emit
#                                  firmware.uf2 (primary) + firmware.elf +
#                                  firmware.bin + provenance.
#   build_rp2.sh --plan <target>   dry-run: needs NO ARM toolchain; prints the
#                                  resolved board, overlay path, size gate, and
#                                  planned artifact set.
#
# Target -> upstream rp2 board mapping comes from versions.lock [targets_rp2]
# (BLD-4 equivalent) — no hardcode, no silent toolchain substitution. The
# compiler is ONLY the pinned install (PYBLE_ARM_TOOLCHAIN_DIR, default
# firmware/.arm-gnu) verified against versions.lock [arm_gnu_toolchain]
# gcc_version — never whatever arm-none-eabi-gcc is first on PATH. A real
# build with no/mismatched toolchain FAILS CLEANLY with an actionable message;
# it never fakes a result.
#
# Hard image-size gate: firmware.bin must be <= 1,572,864 bytes (the 1536 KiB
# region implied by the upstream MICROPY_HW_FLASH_STORAGE_BYTES reservation).

set -u

HERE="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd -P)"
FW="$(cd "$HERE/.." && pwd -P)"
REPO_ROOT="$(cd "$FW/.." && pwd -P)"

LOCK="${PYBLE_LOCK_FILE:-$FW/versions.lock}"
UPSTREAM_DIR="${PYBLE_UPSTREAM_DIR:-$FW/upstream/micropython}"
TOOLCHAIN_DIR="${PYBLE_ARM_TOOLCHAIN_DIR:-$FW/.arm-gnu}"
BUILD_ROOT="${PYBLE_BUILD_ROOT:-$FW/build}"
SHA_DRIFT="$REPO_ROOT/tools/ci/sha_drift.sh"
PREPARE="$HERE/prepare.sh"

SIZE_GATE_BYTES=1572864
ARTIFACTS="firmware.uf2 firmware.elf firmware.bin pyble-build-provenance.json"

usage() {
  echo "usage: build_rp2.sh [--plan] <rpi-pico2-w>" >&2
}

# rp2_board_for <pyble-target> -> the upstream rp2 board from [targets_rp2].
rp2_board_for() {
  awk -F'"' -v t="$1" '
    /^\[targets_rp2\]/ { f=1; next }
    /^\[/              { f=0 }
    f && $2==t         { print $4; exit }
  ' "$LOCK"
}

# lock_field <section> <key> -> the double-quoted value from the lock.
lock_field() {
  awk -F'"' -v sec="[$1]" -v key="$2" '
    /^\[/ { insec = ($0 == sec) }
    insec && $0 ~ ("^[[:space:]]*" key "[[:space:]]*=") { print $2; exit }
  ' "$LOCK"
}

lock_commit() {
  lock_field "$1" commit
}

file_size() {
  stat -f%z "$1" 2>/dev/null || stat -c%s "$1"
}

MODE=build
if [ "${1:-}" = "--plan" ]; then
  MODE=plan
  shift
fi
TARGET="${1:-}"

if [ -z "$TARGET" ]; then
  echo "build_rp2.sh: no target given" >&2
  usage
  exit 2
fi

# Board lookup goes through versions.lock [targets_rp2] — a lock without the
# section (or an unknown target) fails here, plan and real build alike.
UP_BOARD="$(rp2_board_for "$TARGET")"
if [ -z "$UP_BOARD" ]; then
  echo "build_rp2.sh: unknown target '$TARGET' — no versions.lock [targets_rp2] mapping (valid: rpi-pico2-w)" >&2
  usage
  exit 2
fi
BOARD="PYBLE_$UP_BOARD"

OVERLAY="firmware/board_overlays/$TARGET"

# Freeze every source/time input to one exact PyBLE commit (same contract as
# build.sh: derived values only, injected mismatches rejected).
ACTUAL_PYBLE_COMMIT="$(git -C "$REPO_ROOT" rev-parse HEAD 2>/dev/null || true)"
case "$ACTUAL_PYBLE_COMMIT" in
  *[!0-9a-f]*) echo "build_rp2.sh: cannot resolve the full PyBLE source commit" >&2; exit 1 ;;
esac
[ "${#ACTUAL_PYBLE_COMMIT}" -eq 40 ] || {
  echo "build_rp2.sh: cannot resolve the full PyBLE source commit" >&2
  exit 1
}
if [ -n "${PYBLE_SOURCE_COMMIT:-}" ] && [ "$PYBLE_SOURCE_COMMIT" != "$ACTUAL_PYBLE_COMMIT" ]; then
  echo "build_rp2.sh: frozen source commit is not current HEAD" >&2
  exit 1
fi
PYBLE_SOURCE_COMMIT="$ACTUAL_PYBLE_COMMIT"
ACTUAL_SOURCE_DATE_EPOCH="$(git -C "$REPO_ROOT" show -s --format=%ct "$PYBLE_SOURCE_COMMIT" 2>/dev/null || true)"
case "$ACTUAL_SOURCE_DATE_EPOCH" in
  ""|*[!0-9]*)
    echo "build_rp2.sh: cannot derive SOURCE_DATE_EPOCH from the PyBLE source commit" >&2
    exit 1
    ;;
esac
if [ -n "${SOURCE_DATE_EPOCH:-}" ] && [ "$SOURCE_DATE_EPOCH" != "$ACTUAL_SOURCE_DATE_EPOCH" ]; then
  echo "build_rp2.sh: injected SOURCE_DATE_EPOCH disagrees with the source commit" >&2
  exit 1
fi
SOURCE_DATE_EPOCH="$ACTUAL_SOURCE_DATE_EPOCH"
export PYBLE_SOURCE_COMMIT SOURCE_DATE_EPOCH

assert_pyble_source_state() {
  current="$(git -C "$REPO_ROOT" rev-parse HEAD 2>/dev/null || true)"
  [ "$current" = "$PYBLE_SOURCE_COMMIT" ] || {
    echo "build_rp2.sh: PyBLE HEAD changed during the build" >&2
    return 1
  }
  status="$(git -C "$REPO_ROOT" status --porcelain \
    --untracked-files=normal --ignore-submodules=untracked 2>/dev/null || true)"
  if [ -n "$status" ]; then
    echo "build_rp2.sh: PyBLE source tree is not clean:" >&2
    printf '%s\n' "$status" >&2
    return 1
  fi
}

if [ "$MODE" = "plan" ]; then
  echo "# build plan (dry-run; no ARM toolchain required)"
  echo "target=$TARGET"
  echo "port=rp2"
  echo "board=$BOARD"
  echo "overlay=$OVERLAY"
  echo "pin_lock=firmware/versions.lock"
  echo "output_root=$BUILD_ROOT"
  echo "size_gate_bytes=$SIZE_GATE_BYTES"
  echo "source_commit=$PYBLE_SOURCE_COMMIT"
  echo "source_date_epoch=$SOURCE_DATE_EPOCH"
  echo "artifacts: $ARTIFACTS"
  exit 0
fi

# ---- Real build ------------------------------------------------------------
echo "build_rp2.sh: building $TARGET (board=$BOARD) from the pinned tree"

# 1. SHA-drift gate + submodule presence (BLD-2 twin). Refuses on drift.
if ! "$SHA_DRIFT"; then
  echo "build_rp2.sh: cannot build $TARGET — the pinned MicroPython submodule is not ready." >&2
  echo "  run: git submodule update --init firmware/upstream/micropython" >&2
  echo "  (then verify its SHA matches firmware/versions.lock)" >&2
  exit 1
fi

if ! UPSTREAM_DIR="$(cd "$UPSTREAM_DIR" 2>/dev/null && pwd -P)"; then
  echo "build_rp2.sh: cannot resolve the retained MicroPython checkout" >&2
  exit 1
fi
export PYBLE_UPSTREAM_DIR="$UPSTREAM_DIR"

# 2. The PINNED ARM GNU toolchain must be installed and match the lock
# (BLD-4 equivalent). Never a silent substitution of whatever
# arm-none-eabi-gcc is first on PATH; never faked.
GCC="$TOOLCHAIN_DIR/bin/arm-none-eabi-gcc"
if [ ! -x "$GCC" ]; then
  echo "build_rp2.sh: pinned ARM GNU toolchain not installed — no arm-none-eabi-gcc at $GCC" >&2
  echo "  run: firmware/scripts/install_arm_toolchain.sh   (installs the pinned release from versions.lock [arm_gnu_toolchain])" >&2
  echo "  an unpinned arm-none-eabi-gcc on PATH is deliberately NOT used (no silent substitution)" >&2
  exit 1
fi
WANT_GCC="$(lock_field arm_gnu_toolchain gcc_version)"
WANT_RELEASE="$(lock_field arm_gnu_toolchain release)"
if [ -z "$WANT_GCC" ]; then
  echo "build_rp2.sh: versions.lock [arm_gnu_toolchain] has no gcc_version pin" >&2
  exit 1
fi
GOT_GCC="$("$GCC" --version 2>/dev/null | head -n 1)"
case "$GOT_GCC" in
  *"$WANT_GCC"*) : ;;
  *)
    echo "build_rp2.sh: ARM toolchain version mismatch — refusing to build (BLD-4 equivalent)." >&2
    echo "  pinned : gcc $WANT_GCC (ARM GNU ${WANT_RELEASE:-?}, versions.lock [arm_gnu_toolchain])" >&2
    echo "  found  : $GOT_GCC" >&2
    echo "  at     : $GCC" >&2
    echo "  run: firmware/scripts/install_arm_toolchain.sh   (reinstalls the pinned release)" >&2
    exit 1
    ;;
esac
echo "build_rp2.sh: pinned ARM toolchain OK — $GOT_GCC"

# Release provenance may say clean=true only after this check.
assert_pyble_source_state || exit 1

MICROPYTHON_COMMIT="$(git -C "$UPSTREAM_DIR" rev-parse HEAD 2>/dev/null || true)"
if [ "$MICROPYTHON_COMMIT" != "$(lock_commit micropython)" ]; then
  echo "build_rp2.sh: actual MicroPython commit disagrees with versions.lock" >&2
  exit 1
fi

# 3. Build prep: overlay copy-in + patch apply + drift recheck (CON-4/12).
if ! "$PREPARE" "$TARGET"; then
  echo "build_rp2.sh: build prep failed for $TARGET" >&2
  exit 1
fi

BOARD_DST="$UPSTREAM_DIR/ports/rp2/boards/$BOARD"

# 3b. Generate the agent version from versions.lock [pyble] (BLD-12) into the
# COPIED board dir: pble_version.h feeds the overlay mpconfigboard.h board
# name; pyble/_version.py is frozen with the agent package so caps single-
# source their SemVer. Neither is ever hand-edited.
AGENT_VER="$(awk -F' *= *' '/^\[/{s=$0} s=="[pyble]"&&/^agent_version/{gsub(/"/,"",$2);print $2;exit}' "$LOCK")"
PROTO_VER="$(awk -F' *= *' '/^\[/{s=$0} s=="[pyble]"&&/^protocol_version/{gsub(/"/,"",$2);print $2;exit}' "$LOCK")"
{
  echo "// SPDX-License-Identifier: MIT"
  echo "// GENERATED by firmware/scripts/build_rp2.sh from firmware/versions.lock [pyble] — do not edit."
  echo "#ifndef PBLE_VERSION_H"
  echo "#define PBLE_VERSION_H"
  echo "#define PBLE_AGENT_VERSION \"${AGENT_VER:-0.0.0-dev}\""
  echo "#define PBLE_PROTOCOL_VERSION \"${PROTO_VER:-PBLE/1}\""
  echo "#endif  // PBLE_VERSION_H"
} > "$BOARD_DST/pble_version.h"
{
  echo "# SPDX-License-Identifier: MIT"
  echo "# GENERATED by firmware/scripts/build_rp2.sh from firmware/versions.lock [pyble] — do not edit."
  echo "AGENT_VERSION = \"${AGENT_VER:-0.0.0-dev}\""
  echo "PROTOCOL_VERSION = \"${PROTO_VER:-PBLE/1}\""
} > "$BOARD_DST/pyble/_version.py"
echo "build_rp2.sh: agent version ${AGENT_VER:-0.0.0-dev} (${PROTO_VER:-PBLE/1}) -> pble_version.h + pyble/_version.py"

# 4. Build. The pinned toolchain is selected EXPLICITLY: its bin/ is prepended
# for this build only, and PICO_TOOLCHAIN_PATH pins the pico-sdk compiler
# discovery to the same install.
PORT_DIR="$UPSTREAM_DIR/ports/rp2"
mkdir -p "$BUILD_ROOT"
if ! BUILD_ROOT="$(cd "$BUILD_ROOT" 2>/dev/null && pwd -P)"; then
  echo "build_rp2.sh: cannot resolve the firmware build root" >&2
  exit 1
fi
OUT="$BUILD_ROOT/$TARGET"
mkdir -p "$OUT"

export PATH="$TOOLCHAIN_DIR/bin:$PATH"
export PICO_TOOLCHAIN_PATH="$TOOLCHAIN_DIR"

# Never allow ambient compiler/make flags to influence the pinned build.
unset \
  CFLAGS_EXTRA \
  EXTRA_CPPFLAGS \
  EXTRA_CFLAGS \
  EXTRA_CXXFLAGS \
  CFLAGS \
  CXXFLAGS \
  CPPFLAGS \
  MAKEFLAGS \
  MFLAGS \
  GNUMAKEFLAGS \
  MAKEOVERRIDES

make -C "$UPSTREAM_DIR/mpy-cross" || { echo "build_rp2.sh: mpy-cross build failed" >&2; exit 1; }

make -C "$PORT_DIR" \
  submodules \
  BOARD="$BOARD" \
  BUILD="$OUT" ||
  { echo "build_rp2.sh: rp2 port submodules failed" >&2; exit 1; }

make -C "$PORT_DIR" \
  BOARD="$BOARD" \
  BUILD="$OUT" \
  || { echo "build_rp2.sh: rp2 port build failed for $TARGET" >&2; exit 1; }

# 5. Artifacts (P9): firmware.uf2 is the primary BOOTSEL/picotool-flashable
# image; elf + bin ride along for size/debug work.
for art in firmware.uf2 firmware.elf firmware.bin; do
  [ -f "$OUT/$art" ] || { echo "build_rp2.sh: expected artifact missing: $OUT/$art" >&2; exit 1; }
done

# 6. Hard image-size gate (P9): the LFS2 user filesystem region must survive.
BIN_SIZE="$(file_size "$OUT/firmware.bin")"
case "$BIN_SIZE" in
  ""|*[!0-9]*)
    echo "build_rp2.sh: cannot determine firmware.bin size" >&2
    exit 1
    ;;
esac
if [ "$BIN_SIZE" -gt "$SIZE_GATE_BYTES" ]; then
  echo "build_rp2.sh: firmware.bin is $BIN_SIZE bytes — exceeds the hard size gate ($SIZE_GATE_BYTES)" >&2
  exit 1
fi
echo "build_rp2.sh: firmware.bin $BIN_SIZE bytes (gate $SIZE_GATE_BYTES) — headroom $((SIZE_GATE_BYTES - BIN_SIZE))"
"$TOOLCHAIN_DIR/bin/arm-none-eabi-size" "$OUT/firmware.elf" || true

assert_pyble_source_state || exit 1

PICOTOOL_VER="$(picotool version 2>/dev/null | head -n 1 || true)"

PROVENANCE="$OUT/pyble-build-provenance.json"
PROVENANCE_TMP="$OUT/.pyble-build-provenance.json.$$"
{
  printf '{\n'
  printf '  "schema_version": 1,\n'
  printf '  "target": "%s",\n' "$TARGET"
  printf '  "port": "rp2",\n'
  printf '  "board": "%s",\n' "$BOARD"
  printf '  "source_date_epoch": %s,\n' "$SOURCE_DATE_EPOCH"
  printf '  "pyble": {"commit": "%s", "clean": true},\n' "$PYBLE_SOURCE_COMMIT"
  printf '  "micropython": {"commit": "%s"},\n' "$MICROPYTHON_COMMIT"
  printf '  "arm_gnu_toolchain": {"release": "%s", "gcc": "%s"},\n' "${WANT_RELEASE:-}" "$GOT_GCC"
  printf '  "picotool": "%s",\n' "$PICOTOOL_VER"
  printf '  "firmware_bin_bytes": %s\n' "$BIN_SIZE"
  printf '}\n'
} > "$PROVENANCE_TMP"
mv "$PROVENANCE_TMP" "$PROVENANCE"

echo "build_rp2.sh: OK — $TARGET release inputs in $OUT"
exit 0

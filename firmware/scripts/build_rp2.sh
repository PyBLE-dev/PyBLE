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

# Build helpers must not leave checkout-local bytecode whose payload embeds
# host paths and mutates the retained source evidence.
PYTHONDONTWRITEBYTECODE=1
export PYTHONDONTWRITEBYTECODE

HERE="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd -P)"
FW="$(cd "$HERE/.." && pwd -P)"
REPO_ROOT="$(cd "$FW/.." && pwd -P)"

LOCK="${PYBLE_LOCK_FILE:-$FW/versions.lock}"
CANONICAL_UPSTREAM="${PYBLE_CANONICAL_UPSTREAM_DIR:-$FW/upstream/micropython}"
TOOLCHAIN_DIR="${PYBLE_ARM_TOOLCHAIN_DIR:-$FW/.arm-gnu}"
BUILD_ROOT="${PYBLE_BUILD_ROOT:-$FW/build}"
SHA_DRIFT="$REPO_ROOT/tools/ci/sha_drift.sh"
PREPARE="$HERE/prepare.sh"

SIZE_GATE_BYTES=1572864
ARTIFACTS="firmware.uf2 firmware.bin firmware.elf firmware.elf.map CMakeCache.txt CMakeFiles/firmware.dir/link.txt CMakeFiles/firmware.dir/DependInfo.cmake pyble-build-provenance.json"
RP2_SUBMODULES="lib/btstack lib/cyw43-driver lib/lwip lib/mbedtls lib/micropython-lib lib/pico-sdk lib/tinyusb"

CREATED_SOURCE=""
CREATED_OUT=""
SOURCE_INCOMING=""
BUILD_COMPLETE=0

cleanup_failed_build() {
  rc=$?
  trap - EXIT HUP INT TERM
  if [ "$BUILD_COMPLETE" -ne 1 ]; then
    if [ -n "$CREATED_OUT" ] && [ -e "$CREATED_OUT" ] && [ ! -L "$CREATED_OUT" ]; then
      rm -rf -- "$CREATED_OUT"
    fi
    if [ -n "$CREATED_SOURCE" ] && [ -e "$CREATED_SOURCE" ] && [ ! -L "$CREATED_SOURCE" ]; then
      rm -rf -- "$CREATED_SOURCE"
    fi
    if [ -n "$SOURCE_INCOMING" ] && [ -e "$SOURCE_INCOMING" ] && [ ! -L "$SOURCE_INCOMING" ]; then
      rm -rf -- "$SOURCE_INCOMING"
    fi
  fi
  exit "$rc"
}

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

single_origin() {
  checkout="$1"
  origins="$(git -C "$checkout" remote get-url --all origin 2>/dev/null || true)"
  [ -n "$origins" ] || return 1
  [ "$(printf '%s\n' "$origins" | wc -l | tr -d ' ')" = "1" ] || return 1
  printf '%s\n' "$origins"
}

assert_checkout_clean() {
  checkout="$1"
  label="$2"
  if [ -L "$checkout" ] || [ ! -d "$checkout" ] || [ ! -e "$checkout/.git" ]; then
    echo "build_rp2.sh: $label is missing, symlinked, or not Git: $checkout" >&2
    return 1
  fi
  tracked="$(git -C "$checkout" status --porcelain --untracked-files=no \
    --ignore-submodules=none 2>/dev/null || true)"
  if [ -n "$tracked" ]; then
    echo "build_rp2.sh: $label has tracked source changes" >&2
    return 1
  fi
}

assert_outer_identity() {
  checkout="$1"
  label="$2"
  assert_checkout_clean "$checkout" "$label" || return 1
  head="$(git -C "$checkout" rev-parse HEAD 2>/dev/null || true)"
  [ "$head" = "$MICROPYTHON_COMMIT" ] || {
    echo "build_rp2.sh: $label HEAD differs from versions.lock" >&2
    return 1
  }
  origin="$(single_origin "$checkout" || true)"
  [ "$origin" = "$MICROPYTHON_REPO" ] || {
    echo "build_rp2.sh: $label origin differs from versions.lock" >&2
    return 1
  }
}

submodule_identity() {
  outer="$1"
  submodule_path="$2"
  gitlink="$(git -C "$outer" ls-files --stage -- "$submodule_path" 2>/dev/null |
    awk '$1 == "160000" { print $2; count++ } END { if (count != 1) exit 1 }' || true)"
  [ -n "$gitlink" ] || {
    echo "build_rp2.sh: required RP2 gitlink is missing: $submodule_path" >&2
    return 1
  }
  submodule_name="$(git -C "$outer" config -f .gitmodules \
    --get-regexp '^submodule\..*\.path$' 2>/dev/null |
    awk -v wanted="$submodule_path" '
      $2 == wanted {
        name = $1
        sub(/^submodule\./, "", name)
        sub(/\.path$/, "", name)
        print name
        count++
      }
      END { if (count != 1) exit 1 }
    ' || true)"
  [ -n "$submodule_name" ] || {
    echo "build_rp2.sh: required RP2 gitlink has no unique .gitmodules owner: $submodule_path" >&2
    return 1
  }
  submodule_origin="$(git -C "$outer" config -f .gitmodules \
    --get "submodule.$submodule_name.url" 2>/dev/null || true)"
  [ -n "$submodule_origin" ] || {
    echo "build_rp2.sh: required RP2 gitlink has no canonical URL: $submodule_path" >&2
    return 1
  }
  printf '%s\n%s\n%s\n' "$gitlink" "$submodule_name" "$submodule_origin"
}

assert_submodule_identity() {
  outer="$1"
  submodule_path="$2"
  label="$3"
  identity="$(submodule_identity "$outer" "$submodule_path")" || return 1
  gitlink="$(printf '%s\n' "$identity" | sed -n '1p')"
  canonical_origin="$(printf '%s\n' "$identity" | sed -n '3p')"
  checkout="$outer/$submodule_path"
  assert_checkout_clean "$checkout" "$label $submodule_path" || return 1
  head="$(git -C "$checkout" rev-parse HEAD 2>/dev/null || true)"
  [ "$head" = "$gitlink" ] || {
    echo "build_rp2.sh: $label $submodule_path HEAD differs from its gitlink" >&2
    return 1
  }
  origin="$(single_origin "$checkout" || true)"
  [ "$origin" = "$canonical_origin" ] || {
    echo "build_rp2.sh: $label $submodule_path origin differs from .gitmodules" >&2
    return 1
  }
}

assert_source_graph() {
  outer="$1"
  label="$2"
  assert_outer_identity "$outer" "$label" || return 1
  for submodule_path in $RP2_SUBMODULES; do
    assert_submodule_identity "$outer" "$submodule_path" "$label" || return 1
  done
}

initialize_local_submodule() {
  retained="$1"
  submodule_path="$2"
  identity="$(submodule_identity "$CANONICAL_UPSTREAM" "$submodule_path")" || return 1
  submodule_name="$(printf '%s\n' "$identity" | sed -n '2p')"
  submodule_origin="$(printf '%s\n' "$identity" | sed -n '3p')"
  canonical_child="$CANONICAL_UPSTREAM/$submodule_path"
  assert_submodule_identity "$CANONICAL_UPSTREAM" "$submodule_path" canonical || return 1
  if ! git -C "$retained" \
    -c protocol.file.allow=always \
    -c "submodule.$submodule_name.url=$canonical_child" \
    submodule update --quiet --init --no-fetch -- "$submodule_path"
  then
    echo "build_rp2.sh: local initialization failed: $submodule_path" >&2
    return 1
  fi
  git -C "$retained/$submodule_path" remote set-url origin "$submodule_origin" || return 1
  assert_submodule_identity "$retained" "$submodule_path" retained || return 1
}

assert_regular_file() {
  path="$1"
  label="$2"
  if [ -L "$path" ] || [ ! -f "$path" ]; then
    echo "build_rp2.sh: expected regular non-symlink $label missing: $path" >&2
    return 1
  fi
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

# 1. Freeze the exact canonical source graph before creating any build state.
MICROPYTHON_COMMIT="$(lock_commit micropython)"
MICROPYTHON_REPO="$(lock_field micropython repo)"
case "$MICROPYTHON_COMMIT" in
  *[!0-9a-f]*) echo "build_rp2.sh: invalid MicroPython commit pin" >&2; exit 1 ;;
esac
[ "${#MICROPYTHON_COMMIT}" -eq 40 ] && [ -n "$MICROPYTHON_REPO" ] || {
  echo "build_rp2.sh: incomplete MicroPython source identity in versions.lock" >&2
  exit 1
}
if ! CANONICAL_UPSTREAM="$(cd "$CANONICAL_UPSTREAM" 2>/dev/null && pwd -P)"; then
  echo "build_rp2.sh: cannot resolve canonical MicroPython checkout" >&2
  exit 1
fi
PYBLE_UPSTREAM_DIR="$CANONICAL_UPSTREAM" "$SHA_DRIFT" || {
  echo "build_rp2.sh: canonical MicroPython checkout disagrees with versions.lock" >&2
  exit 1
}
assert_source_graph "$CANONICAL_UPSTREAM" canonical || exit 1

# 2. The PINNED ARM GNU toolchain must be installed and match the lock
# (BLD-4 equivalent). Never a silent substitution of whatever
# arm-none-eabi-gcc is first on PATH; never faked.
if [ -d "$TOOLCHAIN_DIR" ]; then
  TOOLCHAIN_DIR="$(cd "$TOOLCHAIN_DIR" && pwd -P)" || {
    echo "build_rp2.sh: cannot resolve the pinned ARM GNU toolchain" >&2
    exit 1
  }
  PYBLE_ARM_TOOLCHAIN_DIR="$TOOLCHAIN_DIR"
  export PYBLE_ARM_TOOLCHAIN_DIR
fi
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

# 3. Materialize one target-scoped retained source graph strictly from the
# already-validated local canonical graph. Final source/output names never
# contain a partial build: the trap removes exactly the paths this invocation
# created unless provenance is admitted at the end.
mkdir -p "$BUILD_ROOT" || exit 1
if ! BUILD_ROOT="$(cd "$BUILD_ROOT" 2>/dev/null && pwd -P)"; then
  echo "build_rp2.sh: cannot resolve the firmware build root" >&2
  exit 1
fi
SOURCE_OWNER="$BUILD_ROOT/.sources/$TARGET"
RETAINED_UPSTREAM="$SOURCE_OWNER/micropython"
OUT="$BUILD_ROOT/$TARGET"
if [ -e "$RETAINED_UPSTREAM" ] || [ -L "$RETAINED_UPSTREAM" ]; then
  echo "build_rp2.sh: refusing pre-existing retained checkout: $RETAINED_UPSTREAM" >&2
  exit 1
fi
if [ -e "$OUT" ] || [ -L "$OUT" ]; then
  echo "build_rp2.sh: refusing pre-existing target build directory: $OUT" >&2
  exit 1
fi
mkdir -p "$SOURCE_OWNER" || exit 1
trap cleanup_failed_build EXIT HUP INT TERM
SOURCE_INCOMING="$(mktemp -d "$SOURCE_OWNER/.micropython.incoming.XXXXXX")" || {
  echo "build_rp2.sh: cannot create retained source staging directory" >&2
  exit 1
}
if ! git clone --quiet --no-hardlinks --no-checkout \
  "$CANONICAL_UPSTREAM" "$SOURCE_INCOMING"
then
  echo "build_rp2.sh: local retained MicroPython clone failed" >&2
  exit 1
fi
git -C "$SOURCE_INCOMING" checkout --quiet --detach "$MICROPYTHON_COMMIT" || {
  echo "build_rp2.sh: retained MicroPython checkout failed" >&2
  exit 1
}
git -C "$SOURCE_INCOMING" remote set-url origin "$MICROPYTHON_REPO" || exit 1
for submodule_path in $RP2_SUBMODULES; do
  initialize_local_submodule "$SOURCE_INCOMING" "$submodule_path" || exit 1
done
assert_source_graph "$SOURCE_INCOMING" retained-staging || exit 1
CREATED_SOURCE="$RETAINED_UPSTREAM"
mv -- "$SOURCE_INCOMING" "$RETAINED_UPSTREAM" || {
  echo "build_rp2.sh: cannot atomically admit retained source checkout" >&2
  exit 1
}
SOURCE_INCOMING=""
assert_source_graph "$RETAINED_UPSTREAM" retained || exit 1
PYBLE_UPSTREAM_DIR="$RETAINED_UPSTREAM"
export PYBLE_UPSTREAM_DIR

# 4. Build prep: overlay copy-in + patch apply + drift recheck (CON-4/12).
if ! "$PREPARE" "$TARGET"; then
  echo "build_rp2.sh: build prep failed for $TARGET" >&2
  exit 1
fi

BOARD_DST="$RETAINED_UPSTREAM/ports/rp2/boards/$BOARD"

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

# 5. Build. The pinned toolchain is selected EXPLICITLY: its bin/ is prepended
# for this build only, and PICO_TOOLCHAIN_PATH pins the pico-sdk compiler
# discovery to the same install.
CREATED_OUT="$OUT"
mkdir -p "$OUT"
PORT_DIR="$RETAINED_UPSTREAM/ports/rp2"

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
  ASMFLAGS \
  CPPFLAGS \
  MAKEFLAGS \
  MFLAGS \
  GNUMAKEFLAGS \
  MAKEOVERRIDES \
  BUILD \
  MICROPY_MPYCROSS

make -C "$RETAINED_UPSTREAM/mpy-cross" BUILD=build || {
  echo "build_rp2.sh: mpy-cross build failed" >&2
  exit 1
}
MICROPY_MPYCROSS="$RETAINED_UPSTREAM/mpy-cross/build/mpy-cross"
if [ -L "$MICROPY_MPYCROSS" ] || [ ! -f "$MICROPY_MPYCROSS" ] || [ ! -x "$MICROPY_MPYCROSS" ]; then
  echo "build_rp2.sh: rebuilt retained mpy-cross is missing, symlinked, or not executable" >&2
  exit 1
fi
export MICROPY_MPYCROSS

# CMake consumes CFLAGS/CXXFLAGS/ASMFLAGS only during its fresh configure.
# Prefixes are ordered broad-to-specific because GCC keeps the last matching
# mapping. The retained checkout mapping therefore wins over /PYBLE_BUILD.
DETERMINISTIC_CFLAGS="\
-ffile-prefix-map=$REPO_ROOT=/PYBLE \
-ffile-prefix-map=$BUILD_ROOT=/PYBLE_BUILD \
-ffile-prefix-map=$OUT=/RP2_BUILD \
-ffile-prefix-map=$RETAINED_UPSTREAM=/MICROPYTHON \
-ffile-prefix-map=$TOOLCHAIN_DIR=/ARM_GNU"
CFLAGS_EXTRA="$DETERMINISTIC_CFLAGS"
CFLAGS="$DETERMINISTIC_CFLAGS"
CXXFLAGS="$DETERMINISTIC_CFLAGS"
ASMFLAGS="$DETERMINISTIC_CFLAGS"
export CFLAGS_EXTRA CFLAGS CXXFLAGS ASMFLAGS

make -C "$PORT_DIR" \
  BOARD="$BOARD" \
  BUILD="$OUT" \
  || { echo "build_rp2.sh: rp2 port build failed for $TARGET" >&2; exit 1; }

# 6. Artifacts and license-observer inputs must all be regular non-symlink
# files before provenance can mark the build complete.
for art in \
  firmware.uf2 \
  firmware.bin \
  firmware.elf \
  firmware.elf.map \
  CMakeCache.txt \
  CMakeFiles/firmware.dir/link.txt \
  CMakeFiles/firmware.dir/DependInfo.cmake
do
  assert_regular_file "$OUT/$art" "$art" || exit 1
done

CMAKE_CACHE="$OUT/CMakeCache.txt"
for expected_cache_line in \
  "CMAKE_HOME_DIRECTORY:INTERNAL=$PORT_DIR" \
  "MICROPY_BOARD_DIR:UNINITIALIZED=$PORT_DIR/boards/$BOARD" \
  "PICO_SDK_PATH:PATH=$RETAINED_UPSTREAM/lib/pico-sdk"
do
  grep -Fx "$expected_cache_line" "$CMAKE_CACHE" >/dev/null || {
    echo "build_rp2.sh: CMake cache does not bind retained source: $expected_cache_line" >&2
    exit 1
  }
done
for expected_compiler in \
  "$TOOLCHAIN_DIR/bin/arm-none-eabi-gcc" \
  "$TOOLCHAIN_DIR/bin/arm-none-eabi-g++"
do
  grep -F "=$expected_compiler" "$CMAKE_CACHE" >/dev/null || {
    echo "build_rp2.sh: CMake cache does not bind the pinned ARM compiler: $expected_compiler" >&2
    exit 1
  }
done

# Fail the complete ELF, not merely symbol/debug subsets, if any physical
# source/build/toolchain prefix escaped the compiler mappings.
for forbidden_path in \
  "$REPO_ROOT" \
  "$BUILD_ROOT" \
  "$OUT" \
  "$RETAINED_UPSTREAM" \
  "$CANONICAL_UPSTREAM" \
  "$TOOLCHAIN_DIR"
do
  if LC_ALL=C grep -aF "$forbidden_path" "$OUT/firmware.elf" >/dev/null; then
    echo "build_rp2.sh: ELF retains an unmapped host path prefix: $forbidden_path" >&2
    exit 1
  fi
done

# 7. Hard image-size gate (P9): the LFS2 user filesystem region must survive.
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
assert_source_graph "$CANONICAL_UPSTREAM" canonical-final || exit 1
assert_source_graph "$RETAINED_UPSTREAM" retained-final || exit 1

# The retained outer checkout now contains only explicit generated build inputs
# and mpy-cross output. Any tracked mutation still fails via assert_source_graph;
# nested checkouts remain exactly clean and independently attributable.

PICOTOOL_VER="$(picotool version 2>/dev/null | head -n 1 || true)"
case "$PICOTOOL_VER" in
  "picotool v"[0-9]*.[0-9]*.[0-9]*) : ;;
  *) echo "build_rp2.sh: picotool version identity is missing or invalid" >&2; exit 1 ;;
esac

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

BUILD_COMPLETE=1
trap - EXIT HUP INT TERM
echo "build_rp2.sh: OK — $TARGET release inputs in $OUT"
exit 0

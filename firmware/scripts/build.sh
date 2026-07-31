#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
#
# X-03 — Per-target firmware build (BLD-3/4/5, CON-4/11). Builds exactly one of
# esp32 / esp32-s3 / esp32-c3 from the single pin in versions.lock. One
# MicroPython + ESP-IDF pin drives all three chips; per-chip differences live
# ONLY in firmware/board_overlays/<target>/ (copied in at prep, submodule stays
# pristine).
#
#   build.sh <target>          real build: prep (SHA-drift + overlay + patches),
#                              install/verify ESP-IDF, rebuild mpy-cross, invoke
#                              the esp32 port with the frozen manifest, and emit
#                              merged firmware.bin + application + bootloader +
#                              partition table + authoritative flasher args.
#   build.sh --plan <target>   dry-run: needs NO ESP-IDF; prints the resolved IDF
#                              target, overlay path, and planned artifact set.
#
# Target -> IDF target mapping comes from versions.lock [targets] (BLD-4) — no
# silent toolchain substitution. A real build with no ESP-IDF/submodule FAILS
# CLEANLY with an actionable message; it never fakes success.

set -u

HERE="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd -P)"
FW="$(cd "$HERE/.." && pwd -P)"
REPO_ROOT="$(cd "$FW/.." && pwd -P)"

LOCK="${PYBLE_LOCK_FILE:-$FW/versions.lock}"
UPSTREAM_DIR="${PYBLE_UPSTREAM_DIR:-$FW/upstream/micropython}"
IDF_DIR="${PYBLE_IDF_DIR:-$FW/.esp-idf}"
BUILD_ROOT="${PYBLE_BUILD_ROOT:-$FW/build}"
SHA_DRIFT="$REPO_ROOT/tools/ci/sha_drift.sh"
PREPARE="$HERE/prepare.sh"

usage() {
  echo "usage: build.sh [--plan] <esp32|esp32-s3|esp32-c3>" >&2
}

# idf_target_for <pyble-target> -> the IDF target from versions.lock [targets].
idf_target_for() {
  awk -F'"' -v t="$1" '
    /^\[targets\]/ { f=1; next }
    /^\[/          { f=0 }
    f && $2==t     { print $4; exit }
  ' "$LOCK"
}

MODE=build
if [ "${1:-}" = "--plan" ]; then
  MODE=plan
  shift
fi
TARGET="${1:-}"

if [ -z "$TARGET" ]; then
  echo "build.sh: no target given" >&2
  usage
  exit 2
fi

IDF_TARGET="$(idf_target_for "$TARGET")"
if [ -z "$IDF_TARGET" ]; then
  echo "build.sh: unknown target '$TARGET' — valid: esp32 esp32-s3 esp32-c3" >&2
  usage
  exit 2
fi

OVERLAY="firmware/board_overlays/$TARGET"

# Freeze every source/time input to one exact PyBLE commit. build_all.sh supplies
# these values once for its matrix; a direct build derives the same values and
# rejects an injected mismatch.
ACTUAL_PYBLE_COMMIT="$(git -C "$REPO_ROOT" rev-parse HEAD 2>/dev/null || true)"
case "$ACTUAL_PYBLE_COMMIT" in
  *[!0-9a-f]*) echo "build.sh: cannot resolve the full PyBLE source commit" >&2; exit 1 ;;
esac
[ "${#ACTUAL_PYBLE_COMMIT}" -eq 40 ] || {
  echo "build.sh: cannot resolve the full PyBLE source commit" >&2
  exit 1
}
if [ -n "${PYBLE_SOURCE_COMMIT:-}" ] && [ "$PYBLE_SOURCE_COMMIT" != "$ACTUAL_PYBLE_COMMIT" ]; then
  echo "build.sh: frozen source commit is not current HEAD" >&2
  exit 1
fi
PYBLE_SOURCE_COMMIT="$ACTUAL_PYBLE_COMMIT"
ACTUAL_SOURCE_DATE_EPOCH="$(git -C "$REPO_ROOT" show -s --format=%ct "$PYBLE_SOURCE_COMMIT" 2>/dev/null || true)"
case "$ACTUAL_SOURCE_DATE_EPOCH" in
  ""|*[!0-9]*)
    echo "build.sh: cannot derive SOURCE_DATE_EPOCH from the PyBLE source commit" >&2
    exit 1
    ;;
esac
if [ -n "${SOURCE_DATE_EPOCH:-}" ] && [ "$SOURCE_DATE_EPOCH" != "$ACTUAL_SOURCE_DATE_EPOCH" ]; then
  echo "build.sh: injected SOURCE_DATE_EPOCH disagrees with the source commit" >&2
  exit 1
fi
SOURCE_DATE_EPOCH="$ACTUAL_SOURCE_DATE_EPOCH"
export PYBLE_SOURCE_COMMIT SOURCE_DATE_EPOCH

assert_pyble_source_state() {
  current="$(git -C "$REPO_ROOT" rev-parse HEAD 2>/dev/null || true)"
  [ "$current" = "$PYBLE_SOURCE_COMMIT" ] || {
    echo "build.sh: PyBLE HEAD changed during the build" >&2
    return 1
  }
  status="$(git -C "$REPO_ROOT" status --porcelain \
    --untracked-files=normal --ignore-submodules=untracked 2>/dev/null || true)"
  if [ -n "$status" ]; then
    echo "build.sh: PyBLE source tree is not clean:" >&2
    printf '%s\n' "$status" >&2
    return 1
  fi
}

lock_commit() {
  section="$1"
  awk -F'"' -v wanted="[$section]" '
    /^\[/ { active = ($0 == wanted) }
    active && /^[[:space:]]*commit[[:space:]]*=/ { print $2; exit }
  ' "$LOCK"
}

if [ "$MODE" = "plan" ]; then
  echo "# build plan (dry-run; no ESP-IDF required)"
  echo "target=$TARGET"
  echo "idf_target=$IDF_TARGET"
  echo "overlay=$OVERLAY"
  echo "pin_lock=firmware/versions.lock"
  echo "output_root=$BUILD_ROOT"
  echo "source_commit=$PYBLE_SOURCE_COMMIT"
  echo "source_date_epoch=$SOURCE_DATE_EPOCH"
  echo "artifacts: firmware.bin micropython.bin micropython.elf bootloader.bin partition-table.bin flasher_args.json pyble-build-provenance.json"
  exit 0
fi

# ---- Real build ------------------------------------------------------------
echo "build.sh: building $TARGET (idf_target=$IDF_TARGET) from the pinned tree"

# 1. SHA-drift gate + submodule presence (BLD-2). Refuses on drift/uninitialized.
if ! "$SHA_DRIFT"; then
  echo "build.sh: cannot build $TARGET — the pinned MicroPython submodule is not ready." >&2
  echo "  run: git submodule update --init firmware/upstream/micropython" >&2
  echo "  (then verify its SHA matches firmware/versions.lock)" >&2
  exit 1
fi

# Use the physical checkout prefix seen by CMake and the compiler. This matters
# on hosts such as macOS where /var and /private/var name the same directory.
if ! UPSTREAM_DIR="$(cd "$UPSTREAM_DIR" 2>/dev/null && pwd -P)"; then
  echo "build.sh: cannot resolve the retained MicroPython checkout" >&2
  exit 1
fi
export PYBLE_UPSTREAM_DIR="$UPSTREAM_DIR"

# 2. ESP-IDF toolchain must be installed from the pin (BLD-11). Never faked.
if [ ! -f "$IDF_DIR/export.sh" ]; then
  echo "build.sh: ESP-IDF toolchain not installed at $IDF_DIR." >&2
  echo "  run: firmware/scripts/install_esp_idf.sh   (installs the pinned ESP-IDF)" >&2
  echo "  this environment has no ESP-IDF; the real 3-chip cross-compile runs in CI / on a toolchain machine." >&2
  exit 1
fi

# Use the same physical checkout prefix that ESP-IDF exports to CMake. This is
# also the prefix covered by the final, more-specific deterministic path map.
if ! IDF_DIR="$(cd "$IDF_DIR" 2>/dev/null && pwd -P)"; then
  echo "build.sh: cannot resolve the pinned ESP-IDF checkout" >&2
  exit 1
fi
export PYBLE_IDF_DIR="$IDF_DIR"

# Release provenance may say clean=true only after this check. Generated build
# outputs and overlay copies are ignored/submodule-untracked and do not weaken
# tracked source cleanliness.
assert_pyble_source_state || exit 1

MICROPYTHON_COMMIT="$(git -C "$UPSTREAM_DIR" rev-parse HEAD 2>/dev/null || true)"
ESP_IDF_COMMIT="$(git -C "$IDF_DIR" rev-parse HEAD 2>/dev/null || true)"
if [ "$MICROPYTHON_COMMIT" != "$(lock_commit micropython)" ]; then
  echo "build.sh: actual MicroPython commit disagrees with versions.lock" >&2
  exit 1
fi
if [ "$ESP_IDF_COMMIT" != "$(lock_commit esp_idf)" ]; then
  echo "build.sh: actual ESP-IDF commit disagrees with versions.lock" >&2
  exit 1
fi

# 3. Build prep: overlay copy-in + patch apply + drift recheck (CON-4/12).
if ! "$PREPARE" "$TARGET"; then
  echo "build.sh: build prep failed for $TARGET" >&2
  exit 1
fi

# 3b. Generate the agent version header from versions.lock [pyble] (BLD-12) so the
# native agent surfaces its SemVer in caps. Like the upstream pins, the version is
# single-sourced in versions.lock and never hand-edited in C. Generated (gitignored),
# with an "__has_include"-guarded default in pble_info.c for dev/editor builds.
AGENT_VER="$(awk -F' *= *' '/^\[/{s=$0} s=="[pyble]"&&/^agent_version/{gsub(/"/,"",$2);print $2;exit}' "$LOCK")"
PROTO_VER="$(awk -F' *= *' '/^\[/{s=$0} s=="[pyble]"&&/^protocol_version/{gsub(/"/,"",$2);print $2;exit}' "$LOCK")"
VER_H="$FW/user_c_modules/pyble/pble_version.h"
{
  echo "// SPDX-License-Identifier: MIT"
  echo "// GENERATED by firmware/scripts/build.sh from firmware/versions.lock [pyble] — do not edit."
  echo "#ifndef PBLE_VERSION_H"
  echo "#define PBLE_VERSION_H"
  echo "#define PBLE_AGENT_VERSION \"${AGENT_VER:-0.0.0-dev}\""
  echo "#define PBLE_PROTOCOL_VERSION \"${PROTO_VER:-PBLE/1}\""
  echo "#endif  // PBLE_VERSION_H"
} > "$VER_H"
echo "build.sh: agent version ${AGENT_VER:-0.0.0-dev} (${PROTO_VER:-PBLE/1}) -> $(basename "$VER_H")"

# 4-7. Rebuild mpy-cross, invoke the esp32 port for the mapped IDF target with
# the frozen manifest + USER_C_MODULES slot, emit firmware.bin + bootloader +
# partition table. (Runs only on a machine with the pinned ESP-IDF exported.)
# shellcheck disable=SC1091
. "$IDF_DIR/export.sh"

# Recovery text is release-critical, not illustrative. Exercise its exact
# underscore subcommand with the Python environment selected by the pinned
# ESP-IDF export before spending time on the target build.
if ! python -m esptool --chip "$IDF_TARGET" write_flash --help >/dev/null 2>&1; then
  echo "build.sh: pinned esptool rejects the recovery write_flash command for $IDF_TARGET" >&2
  exit 1
fi
echo "build.sh: pinned esptool accepts recovery write_flash for $IDF_TARGET"

BOARD="PYBLE_$(printf '%s' "$TARGET" | tr 'a-z-' 'A-Z_')"
PORT="$UPSTREAM_DIR/ports/esp32"
mkdir -p "$BUILD_ROOT"
if ! BUILD_ROOT="$(cd "$BUILD_ROOT" 2>/dev/null && pwd -P)"; then
  echo "build.sh: cannot resolve the firmware build root" >&2
  exit 1
fi
OUT="$BUILD_ROOT/$TARGET"
mkdir -p "$OUT"

# Never allow ambient compiler flags to influence the pinned mpy-cross build.
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
  MAKEOVERRIDES \
  BUILD \
  MICROPY_MPYCROSS
make -C "$UPSTREAM_DIR/mpy-cross" BUILD=build ||
  { echo "build.sh: mpy-cross build failed" >&2; exit 1; }
MICROPY_MPYCROSS="$UPSTREAM_DIR/mpy-cross/build/mpy-cross"
if [ ! -x "$MICROPY_MPYCROSS" ]; then
  echo "build.sh: rebuilt mpy-cross is missing or not executable" >&2
  exit 1
fi
export MICROPY_MPYCROSS

# ESP-IDF maps its project, build, component, and toolchain paths when
# CONFIG_APP_REPRODUCIBLE_BUILD=y, but MicroPython sources above ports/esp32
# and PyBLE USER_C_MODULES sit outside those prefixes. -ffile-prefix-map is the
# pinned GCC spelling that covers debug paths and macro/file expansions. GCC
# gives the final matching map precedence, so order broad prefixes before the
# more-specific target build, retained MicroPython checkout, and ESP-IDF
# checkout. The IDF mapping must remain last because a repo-local pinned
# checkout is nested below REPO_ROOT and must keep ESP-IDF's stable /IDF
# spelling rather than the broader /PYBLE spelling.
DETERMINISTIC_CFLAGS="\
-ffile-prefix-map=$REPO_ROOT=/PYBLE \
-ffile-prefix-map=$OUT=/IDF_BUILD \
-ffile-prefix-map=$UPSTREAM_DIR=/MICROPYTHON \
-ffile-prefix-map=$IDF_DIR=/IDF"

make -C "$PORT" \
  submodules \
  BOARD="$BOARD" \
  BUILD="$OUT" \
  CFLAGS_EXTRA="$DETERMINISTIC_CFLAGS" \
  EXTRA_CPPFLAGS="$DETERMINISTIC_CFLAGS" ||
  { echo "build.sh: port submodules failed" >&2; exit 1; }

# Native USER_C_MODULES are optional: the empty/frozen-Python agent has none yet
# (native pble_*.c arrive in a later sprint). Only pass the slot if it exists.
UCM="$FW/user_c_modules/pyble/micropython.cmake"
UCM_ARG=""
[ -f "$UCM" ] && UCM_ARG="USER_C_MODULES=$UCM"

# shellcheck disable=SC2086
make -C "$PORT" \
  BOARD="$BOARD" \
  IDF_TARGET="$IDF_TARGET" \
  $UCM_ARG \
  BUILD="$OUT" \
  CFLAGS_EXTRA="$DETERMINISTIC_CFLAGS" \
  EXTRA_CPPFLAGS="$DETERMINISTIC_CFLAGS" \
  || { echo "build.sh: ESP-IDF port build failed for $TARGET" >&2; exit 1; }

for art in \
  firmware.bin \
  micropython.bin \
  micropython.elf \
  bootloader/bootloader.bin \
  partition_table/partition-table.bin \
  flasher_args.json
do
  [ -f "$OUT/$art" ] || { echo "build.sh: expected artifact missing: $OUT/$art" >&2; exit 1; }
done

# The application descriptor hashes the whole ELF, including debug sections.
# Fail here if a compiler path escaped the controlled mappings: otherwise two
# clean build directories can produce identical code but different flash bytes.
for forbidden_path in "$REPO_ROOT" "$BUILD_ROOT" "$UPSTREAM_DIR"; do
  if LC_ALL=C grep -aF "$forbidden_path" "$OUT/micropython.elf" >/dev/null; then
    echo "build.sh: ELF retains an unmapped host path prefix: $forbidden_path" >&2
    exit 1
  fi
done

assert_pyble_source_state || exit 1

PROVENANCE="$OUT/pyble-build-provenance.json"
PROVENANCE_TMP="$OUT/.pyble-build-provenance.json.$$"
{
  printf '{\n'
  printf '  "schema_version": 1,\n'
  printf '  "target": "%s",\n' "$TARGET"
  printf '  "source_date_epoch": %s,\n' "$SOURCE_DATE_EPOCH"
  printf '  "pyble": {"commit": "%s", "clean": true},\n' "$PYBLE_SOURCE_COMMIT"
  printf '  "micropython": {"commit": "%s"},\n' "$MICROPYTHON_COMMIT"
  printf '  "esp_idf": {"commit": "%s"}\n' "$ESP_IDF_COMMIT"
  printf '}\n'
} > "$PROVENANCE_TMP"
mv "$PROVENANCE_TMP" "$PROVENANCE"

echo "build.sh: OK — $TARGET release inputs in $OUT"
exit 0

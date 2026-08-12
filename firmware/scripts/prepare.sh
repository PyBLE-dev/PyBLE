#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
#
# F-15 / X-03 — Build-tree preparation (CON-4, CON-12, BLD-2/15). Runs before the
# per-port MicroPython build:
#   1. SHA-drift gate — refuse unless the checked-out submodule matches the pin.
#   2. Zero-patch policy — refuse an undocumented patch; apply documented ones.
#   3. Overlay copy-in — copy firmware/board_overlays/<target>/ into the upstream
#      ports/<port>/boards/PYBLE_<BOARD>/ tree; the submodule stays PRISTINE
#      because we only ever copy INTO it, never edit its tracked files.
#      The frozen-Python agent package firmware/pyble/ is copied alongside so
#      the overlay manifest.py can freeze it.
#
#   Usage:  prepare.sh <esp32|esp32-s3|waveshare-esp32-s3-lcd-147b|esp32-c3|rpi-pico2-w>
#
# Port dimension (X-13, ports/rpi-pico2-w.md P9): esp32-family targets land in
# ports/esp32 with a partitions.csv copy; the rpi-pico2-w target lands in
# ports/rp2 via the versions.lock [targets_rp2] board lookup and copies NO
# partition table (rp2 has none).
#
# This never edits upstream tracked files in place (CON-1). It is idempotent.

set -eu

HERE="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
FW="$(cd "$HERE/.." && pwd)"
REPO_ROOT="$(cd "$FW/.." && pwd)"

LOCK="${PYBLE_LOCK_FILE:-$FW/versions.lock}"
UPSTREAM_DIR="${PYBLE_UPSTREAM_DIR:-$FW/upstream/micropython}"
SHA_DRIFT="$REPO_ROOT/tools/ci/sha_drift.sh"
PATCHES_POLICY="$REPO_ROOT/tools/ci/patches_policy.sh"

TARGET="${1:-}"
case "$TARGET" in
  esp32|esp32-s3|waveshare-esp32-s3-lcd-147b|esp32-c3) PORT="esp32" ;;
  rpi-pico2-w)             PORT="rp2" ;;
  *) echo "prepare.sh: unknown/missing target '$TARGET' — valid: esp32 esp32-s3 waveshare-esp32-s3-lcd-147b esp32-c3 rpi-pico2-w" >&2; exit 2 ;;
esac

OVERLAY="$FW/board_overlays/$TARGET"
[ -d "$OVERLAY" ] || { echo "prepare.sh: missing overlay $OVERLAY" >&2; exit 1; }

# 1. SHA-drift gate (BLD-2).
"$SHA_DRIFT"

# The upstream checkout may contain only PyBLE's generated overlay copies and
# documented compiler outputs. Any tracked edit or unowned untracked path is
# ambiguous source input and fails before preparation mutates the tree.
git -C "$UPSTREAM_DIR" diff --quiet --ignore-submodules=untracked -- || {
  echo "prepare.sh: tracked upstream files are modified" >&2
  exit 1
}
git -C "$UPSTREAM_DIR" diff --cached --quiet --ignore-submodules=untracked -- || {
  echo "prepare.sh: staged upstream files are modified" >&2
  exit 1
}
while IFS= read -r -d '' generated; do
  case "$generated" in
    ports/esp32/boards/PYBLE_ESP32/*|\
    ports/esp32/boards/PYBLE_ESP32_S3/*|\
    ports/esp32/boards/PYBLE_WAVESHARE_ESP32_S3_LCD_147B/*|\
    ports/esp32/boards/PYBLE_ESP32_C3/*|\
    ports/esp32/partitions.csv|\
    ports/esp32/build-PYBLE_ESP32/*|\
    ports/esp32/build-PYBLE_ESP32_S3/*|\
    ports/esp32/build-PYBLE_WAVESHARE_ESP32_S3_LCD_147B/*|\
    ports/esp32/build-PYBLE_ESP32_C3/*|\
    ports/rp2/boards/PYBLE_RPI_PICO2_W/*|\
    mpy-cross/build/*) : ;;
    *)
      echo "prepare.sh: unowned upstream generated path: $generated" >&2
      exit 1
      ;;
  esac
done < <(git -C "$UPSTREAM_DIR" ls-files --others --exclude-standard -z)

# 2. Zero-patch policy (CON-12/BLD-15).
"$PATCHES_POLICY" "$FW/patches"

# The MicroPython tag drives the patch subdir name (firmware/patches/micropython-<ref>/).
REF="$(awk -F'"' '/^\[micropython\]/{f=1; next} /^\[/{f=0} f&&/^[[:space:]]*ref[[:space:]]*=/{print $2; exit}' "$LOCK")"

# 3. Overlay copy-in (CON-4). Submodule stays pristine — we only add a board dir.
if [ "$PORT" = "rp2" ]; then
  # rp2 targets resolve their upstream board via versions.lock [targets_rp2]
  # (X-13; BLD-4 equivalent — the lock is the single source, never a hardcode).
  UP_BOARD="$(awk -F'"' -v t="$TARGET" '/^\[targets_rp2\]/{f=1; next} /^\[/{f=0} f&&$2==t{print $4; exit}' "$LOCK")"
  if [ -z "$UP_BOARD" ]; then
    echo "prepare.sh: versions.lock [targets_rp2] has no board for '$TARGET'" >&2
    exit 1
  fi
  BOARD="PYBLE_$UP_BOARD"
else
  BOARD="PYBLE_$(printf '%s' "$TARGET" | tr 'a-z-' 'A-Z_')"
fi
BOARD_DST="$UPSTREAM_DIR/ports/$PORT/boards/$BOARD"
rm -rf "$BOARD_DST"
mkdir -p "$BOARD_DST"
cp -R "$OVERLAY"/. "$BOARD_DST"/
# Copy the frozen-Python agent package so manifest.py can freeze it.
cp -R "$FW/pyble" "$BOARD_DST/pyble"
# The optional clean-room display runtime is exact-board-only Layer-4 content.
# Keep the canonical source outside the overlay, then materialize it only for
# the dedicated Waveshare build. Every family/generic target must stay lean.
if [ "$TARGET" = "waveshare-esp32-s3-lcd-147b" ]; then
  cp "$FW/python_modules/pyble_st7789.py" "$BOARD_DST/pyble_st7789.py"
fi
# ESP-IDF resolves CONFIG_PARTITION_TABLE_CUSTOM_FILENAME relative to the esp32
# PORT project dir, not the board dir — so place the overlay's partition table
# there too (per-target, overwritten each build). The submodule's TRACKED files
# stay pristine (CON-1); this is an untracked build-input alongside build-*/.
# rp2 carries no partition table at all (its overlay has no partitions.csv).
if [ "$PORT" = "esp32" ] && [ -f "$OVERLAY/partitions.csv" ]; then
  cp "$OVERLAY/partitions.csv" "$UPSTREAM_DIR/ports/esp32/partitions.csv"
fi
echo "prepare.sh: copied overlay $TARGET -> $BOARD_DST (board $BOARD)"

# 4. Apply any documented patches for this tag (default: zero).
PATCH_DIR="$FW/patches/micropython-$REF"
if [ -d "$PATCH_DIR" ]; then
  applied=0
  for p in "$PATCH_DIR"/*.patch; do
    [ -f "$p" ] || continue
    echo "prepare.sh: applying patch $(basename "$p")"
    git -C "$UPSTREAM_DIR" apply --check "$p"
    git -C "$UPSTREAM_DIR" apply "$p"
    applied=$((applied+1))
  done
  [ "$applied" -eq 0 ] || echo "prepare.sh: applied $applied patch(es) for $REF"
fi

echo "prepare.sh: build tree ready for $TARGET"
exit 0

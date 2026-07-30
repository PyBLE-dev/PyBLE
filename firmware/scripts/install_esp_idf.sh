#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
#
# F-15 / BLD-11 — Install ESP-IDF from the pin in versions.lock into a GITIGNORED
# directory (NOT an outer submodule). Clones the pinned repo, checks out the
# pinned commit, verifies the SHA, and runs the IDF installer for the three
# targets PyBLE builds (esp32, esp32s3, esp32c3).
#
#   Usage:  install_esp_idf.sh [DEST]   (DEST defaults to firmware/.esp-idf)
#
# Network + disk required — this runs in CI or on a toolchain machine, not in the
# host gate environment. It never fabricates a toolchain.

set -eu

HERE="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
FW="$(cd "$HERE/.." && pwd)"
LOCK="${PYBLE_LOCK_FILE:-$FW/versions.lock}"
DEST="${1:-${PYBLE_IDF_DIR:-$FW/.esp-idf}}"

field() { # $1=section $2=key
  awk -F'"' -v sec="[$1]" -v key="$2" '
    $0 ~ "^\\["      { insec = ($0 == sec) }
    insec && $0 ~ ("^[[:space:]]*" key "[[:space:]]*=") { print $2; exit }
  ' "$LOCK"
}

REPO="$(field esp_idf repo)"
REF="$(field esp_idf ref)"
COMMIT="$(field esp_idf commit)"

if [ -z "$REPO" ] || [ -z "$COMMIT" ]; then
  echo "install_esp_idf: could not read [esp_idf] pin from $LOCK" >&2
  exit 1
fi

echo "install_esp_idf: pin ${REF:-?} ($COMMIT) from $REPO -> $DEST"

if [ ! -d "$DEST/.git" ]; then
  # Shallow-clone the pinned tag directly (fast); HEAD is then the pinned commit.
  # Falls back to a full clone + checkout if no ref is pinned.
  if [ -n "$REF" ]; then
    git clone --branch "$REF" --depth 1 "$REPO" "$DEST"
  else
    git clone "$REPO" "$DEST" && git -C "$DEST" checkout "$COMMIT"
  fi
fi
git -C "$DEST" submodule update --init --recursive --depth 1

got="$(git -C "$DEST" rev-parse HEAD)"
if [ "$got" != "$COMMIT" ]; then
  echo "install_esp_idf: SHA mismatch — wanted $COMMIT, got $got (refusing, no silent sub)" >&2
  exit 1
fi

# Install the toolchains for exactly the three PyBLE targets (BLD-4 map).
"$DEST/install.sh" esp32,esp32s3,esp32c3

echo "install_esp_idf: ESP-IDF ready at $DEST — run: . $DEST/export.sh"
exit 0

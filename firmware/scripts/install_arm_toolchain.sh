#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
#
# X-13 / BLD-4 equivalent — Install the PINNED ARM GNU bare-metal toolchain for
# the rp2 port from versions.lock [arm_gnu_toolchain] into a GITIGNORED
# directory (sibling of install_esp_idf.sh). Fetches the pinned tarball,
# verifies its SHA-256 against the lock, extracts it, and verifies the
# resulting arm-none-eabi-gcc version — refusing at every step rather than
# substituting. It never fabricates a toolchain.
#
#   Usage:  install_arm_toolchain.sh [DEST]   (DEST defaults to firmware/.arm-gnu)
#
#   PYBLE_ARM_TARBALL=<path>  use an already-downloaded tarball (still
#                             SHA-256-verified) instead of fetching.
#
# Network + disk required — this runs in CI or on a toolchain machine, not in
# the host gate environment.

set -eu

HERE="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
FW="$(cd "$HERE/.." && pwd)"
LOCK="${PYBLE_LOCK_FILE:-$FW/versions.lock}"
DEST="${1:-${PYBLE_ARM_TOOLCHAIN_DIR:-$FW/.arm-gnu}}"

field() { # $1=key (in [arm_gnu_toolchain])
  awk -F'"' -v key="$1" '
    /^\[/ { insec = ($0 == "[arm_gnu_toolchain]") }
    insec && $0 ~ ("^[[:space:]]*" key "[[:space:]]*=") { print $2; exit }
  ' "$LOCK"
}

RELEASE="$(field release)"
GCC_VERSION="$(field gcc_version)"
SHA256="$(field sha256)"
URL="$(field url)"

if [ -z "$URL" ] || [ -z "$SHA256" ] || [ -z "$GCC_VERSION" ]; then
  echo "install_arm_toolchain: could not read the [arm_gnu_toolchain] pin from $LOCK" >&2
  exit 1
fi

echo "install_arm_toolchain: pin ARM GNU ${RELEASE:-?} (gcc $GCC_VERSION) -> $DEST"

sha256_of() {
  if command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$1" | awk '{print $1}'
  else
    sha256sum "$1" | awk '{print $1}'
  fi
}

# Already installed and matching? Idempotent no-op.
GCC="$DEST/bin/arm-none-eabi-gcc"
if [ -x "$GCC" ]; then
  got_ver="$("$GCC" --version 2>/dev/null | head -n 1)"
  case "$got_ver" in
    *"$GCC_VERSION"*)
      echo "install_arm_toolchain: already installed and matching the pin — $got_ver"
      exit 0
      ;;
    *)
      echo "install_arm_toolchain: existing install at $DEST does not match the pin ($got_ver) — reinstalling" >&2
      rm -rf "$DEST"
      ;;
  esac
fi

TARBALL="${PYBLE_ARM_TARBALL:-}"
TMP_TARBALL=""
if [ -z "$TARBALL" ]; then
  TMP_TARBALL="$(mktemp "${TMPDIR:-/tmp}/arm-gnu-toolchain.XXXXXX.tar.xz")"
  TARBALL="$TMP_TARBALL"
  echo "install_arm_toolchain: fetching $URL"
  curl -fL --retry 3 -o "$TARBALL" "$URL" || {
    echo "install_arm_toolchain: download failed (refusing, no silent sub)" >&2
    rm -f "$TMP_TARBALL"
    exit 1
  }
fi
[ -f "$TARBALL" ] || { echo "install_arm_toolchain: no tarball at $TARBALL" >&2; exit 1; }

got_sha="$(sha256_of "$TARBALL")"
if [ "$got_sha" != "$SHA256" ]; then
  echo "install_arm_toolchain: SHA-256 mismatch — wanted $SHA256, got $got_sha (refusing, no silent sub)" >&2
  [ -n "$TMP_TARBALL" ] && rm -f "$TMP_TARBALL"
  exit 1
fi
echo "install_arm_toolchain: SHA-256 verified"

# Extract into DEST with the release's single top-level dir stripped, so gcc
# lands at DEST/bin/arm-none-eabi-gcc regardless of the tarball's dir name.
mkdir -p "$DEST"
tar -xJf "$TARBALL" -C "$DEST" --strip-components=1 || {
  echo "install_arm_toolchain: extraction failed" >&2
  rm -rf "$DEST"
  [ -n "$TMP_TARBALL" ] && rm -f "$TMP_TARBALL"
  exit 1
}
[ -n "$TMP_TARBALL" ] && rm -f "$TMP_TARBALL"

got_ver="$("$GCC" --version 2>/dev/null | head -n 1 || true)"
case "$got_ver" in
  *"$GCC_VERSION"*) : ;;
  *)
    echo "install_arm_toolchain: installed gcc does not match the pin — wanted $GCC_VERSION, got: ${got_ver:-none} (refusing)" >&2
    exit 1
    ;;
esac

echo "install_arm_toolchain: ARM GNU toolchain ready at $DEST — $got_ver"
exit 0

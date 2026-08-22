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

integer_field() { # $1=integer key (in [arm_gnu_toolchain])
  awk -F'=' -v key="$1" '
    /^\[/ { insec = ($0 == "[arm_gnu_toolchain]") }
    insec && $0 ~ ("^[[:space:]]*" key "[[:space:]]*=") {
      value = $2
      sub(/[[:space:]]*#.*/, "", value)
      gsub(/[[:space:]]/, "", value)
      print value
      exit
    }
  ' "$LOCK"
}

RELEASE="$(field release)"
GCC_VERSION="$(field gcc_version)"
SHA256="$(field sha256)"
URL="$(field url)"
ARCHIVE_FILENAME="$(field archive_filename)"
ARCHIVE_BYTES="$(integer_field archive_bytes)"
ARCHIVE_FORMAT="$(field archive_format)"
ARCHIVE_ROOT="$(field archive_root)"
RELEASE_MANIFEST_PATH="$(field release_manifest_path)"
RELEASE_MANIFEST_SHA256="$(field release_manifest_sha256)"
C_ASM_FRONTEND_PATH="$(field c_asm_frontend_path)"
C_ASM_FRONTEND_SHA256="$(field c_asm_frontend_sha256)"
CXX_FRONTEND_PATH="$(field cxx_frontend_path)"
CXX_FRONTEND_SHA256="$(field cxx_frontend_sha256)"

if [ -z "$URL" ] || [ -z "$SHA256" ] || [ -z "$GCC_VERSION" ] \
  || [ -z "$ARCHIVE_FILENAME" ] || [ -z "$ARCHIVE_BYTES" ] \
  || [ "$ARCHIVE_FORMAT" != "tar.xz" ] || [ -z "$ARCHIVE_ROOT" ] \
  || [ -z "$RELEASE_MANIFEST_PATH" ] || [ -z "$RELEASE_MANIFEST_SHA256" ] \
  || [ -z "$C_ASM_FRONTEND_PATH" ] || [ -z "$C_ASM_FRONTEND_SHA256" ] \
  || [ -z "$CXX_FRONTEND_PATH" ] || [ -z "$CXX_FRONTEND_SHA256" ]; then
  echo "install_arm_toolchain: could not read the [arm_gnu_toolchain] pin from $LOCK" >&2
  exit 1
fi

case "$ARCHIVE_BYTES" in
  ''|*[!0-9]*)
    echo "install_arm_toolchain: archive_bytes is not an integer" >&2
    exit 1
    ;;
esac
[ "${URL##*/}" = "$ARCHIVE_FILENAME" ] || {
  echo "install_arm_toolchain: archive filename disagrees with the pinned URL" >&2
  exit 1
}
for relative in "$RELEASE_MANIFEST_PATH" "$C_ASM_FRONTEND_PATH" "$CXX_FRONTEND_PATH"; do
  case "$relative" in
    ''|/*|../*|*/../*|*/..|*//* )
      echo "install_arm_toolchain: unsafe pinned archive member: $relative" >&2
      exit 1
      ;;
  esac
done

echo "install_arm_toolchain: pin ARM GNU ${RELEASE:-?} (gcc $GCC_VERSION) -> $DEST"

sha256_of() {
  if command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$1" | awk '{print $1}'
  else
    sha256sum "$1" | awk '{print $1}'
  fi
}

size_of() {
  if stat -f %z "$1" >/dev/null 2>&1; then
    stat -f %z "$1"
  else
    stat -c %s "$1"
  fi
}

regular_file_matches() { # $1=path $2=sha256
  [ -f "$1" ] && [ ! -L "$1" ] && [ "$(sha256_of "$1")" = "$2" ]
}

installed_tree_matches() {
  retained="$DEST/.pyble-dist/$ARCHIVE_FILENAME"
  regular_file_matches "$retained" "$SHA256" \
    && [ "$(size_of "$retained")" = "$ARCHIVE_BYTES" ] \
    && regular_file_matches "$DEST/$RELEASE_MANIFEST_PATH" "$RELEASE_MANIFEST_SHA256" \
    && regular_file_matches "$DEST/$C_ASM_FRONTEND_PATH" "$C_ASM_FRONTEND_SHA256" \
    && regular_file_matches "$DEST/$CXX_FRONTEND_PATH" "$CXX_FRONTEND_SHA256"
}

# Already installed and matching? Idempotent no-op.
GCC="$DEST/$C_ASM_FRONTEND_PATH"
if [ -x "$GCC" ]; then
  got_ver="$("$GCC" --version 2>/dev/null | head -n 1)"
  case "$got_ver" in
    *"$GCC_VERSION"*)
      if installed_tree_matches; then
        echo "install_arm_toolchain: already installed and matching the complete pin — $got_ver"
        exit 0
      fi
      echo "install_arm_toolchain: existing install lacks the exact retained distribution evidence — reinstalling" >&2
      ;;
    *)
      echo "install_arm_toolchain: existing install at $DEST does not match the pin ($got_ver) — reinstalling" >&2
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
[ -f "$TARBALL" ] && [ ! -L "$TARBALL" ] || {
  echo "install_arm_toolchain: no regular tarball at $TARBALL" >&2
  [ -n "$TMP_TARBALL" ] && rm -f "$TMP_TARBALL"
  exit 1
}

got_bytes="$(size_of "$TARBALL")"
if [ "$got_bytes" != "$ARCHIVE_BYTES" ]; then
  echo "install_arm_toolchain: archive size mismatch — wanted $ARCHIVE_BYTES, got $got_bytes" >&2
  [ -n "$TMP_TARBALL" ] && rm -f "$TMP_TARBALL"
  exit 1
fi

got_sha="$(sha256_of "$TARBALL")"
if [ "$got_sha" != "$SHA256" ]; then
  echo "install_arm_toolchain: SHA-256 mismatch — wanted $SHA256, got $got_sha (refusing, no silent sub)" >&2
  [ -n "$TMP_TARBALL" ] && rm -f "$TMP_TARBALL"
  exit 1
fi
echo "install_arm_toolchain: SHA-256 verified"

# Validate member names and internal hardlinks before invoking tar. The pinned
# official archive contains internal hardlinks but no symlinks or special
# files; every member and hardlink target remains below the one exact root.
python3 - "$TARBALL" "$ARCHIVE_ROOT" <<'PY' || {
import pathlib
import sys
import tarfile

archive_path, expected_root = sys.argv[1:]
seen = set()
with tarfile.open(archive_path, mode="r:xz") as archive:
    members = archive.getmembers()
    if not members:
        raise SystemExit("empty ARM toolchain archive")
    for member in members:
        path = pathlib.PurePosixPath(member.name)
        if path.is_absolute() or ".." in path.parts or not path.parts:
            raise SystemExit("unsafe ARM toolchain archive path")
        if path.parts[0] != expected_root or member.name in seen:
            raise SystemExit("ARM toolchain archive root/duplicate mismatch")
        seen.add(member.name)
        if member.issym() or not (member.isfile() or member.isdir() or member.islnk()):
            raise SystemExit("unsupported ARM toolchain archive member")
        if member.islnk():
            target = pathlib.PurePosixPath(member.linkname)
            if target.is_absolute() or ".." in target.parts or not target.parts:
                raise SystemExit("unsafe ARM toolchain hardlink")
            if target.parts[0] != expected_root:
                raise SystemExit("escaped ARM toolchain hardlink")
PY
  echo "install_arm_toolchain: archive topology validation failed" >&2
  [ -n "$TMP_TARBALL" ] && rm -f "$TMP_TARBALL"
  exit 1
}

DEST_PARENT="$(dirname "$DEST")"
mkdir -p "$DEST_PARENT"
if [ -L "$DEST" ]; then
  echo "install_arm_toolchain: destination must not be a symlink" >&2
  [ -n "$TMP_TARBALL" ] && rm -f "$TMP_TARBALL"
  exit 1
fi
INCOMING="$(mktemp -d "$DEST_PARENT/.arm-gnu.incoming.XXXXXX")"
cleanup_incoming() {
  rm -rf "$INCOMING"
  [ -n "$TMP_TARBALL" ] && rm -f "$TMP_TARBALL"
}
trap cleanup_incoming EXIT HUP INT TERM

# Extract into a fresh sibling and admit it only after every pinned byte is
# verified. --strip-components keeps the installed layout independent of the
# archive's single reviewed top-level directory.
tar -xJf "$TARBALL" -C "$INCOMING" --strip-components=1 || {
  echo "install_arm_toolchain: extraction failed" >&2
  exit 1
}

regular_file_matches "$INCOMING/$RELEASE_MANIFEST_PATH" "$RELEASE_MANIFEST_SHA256" \
  && regular_file_matches "$INCOMING/$C_ASM_FRONTEND_PATH" "$C_ASM_FRONTEND_SHA256" \
  && regular_file_matches "$INCOMING/$CXX_FRONTEND_PATH" "$CXX_FRONTEND_SHA256" || {
    echo "install_arm_toolchain: extracted manifest/frontend digest mismatch" >&2
    exit 1
  }

mkdir -p "$INCOMING/.pyble-dist"
cp "$TARBALL" "$INCOMING/.pyble-dist/$ARCHIVE_FILENAME"
regular_file_matches "$INCOMING/.pyble-dist/$ARCHIVE_FILENAME" "$SHA256" || {
  echo "install_arm_toolchain: retained archive digest mismatch" >&2
  exit 1
}

got_ver="$("$INCOMING/$C_ASM_FRONTEND_PATH" --version 2>/dev/null | head -n 1 || true)"
case "$got_ver" in
  *"$GCC_VERSION"*) : ;;
  *)
    echo "install_arm_toolchain: installed gcc does not match the pin — wanted $GCC_VERSION, got: ${got_ver:-none} (refusing)" >&2
    exit 1
    ;;
esac

if [ -e "$DEST" ]; then
  rm -rf "$DEST"
fi
mv "$INCOMING" "$DEST"
trap - EXIT HUP INT TERM
[ -n "$TMP_TARBALL" ] && rm -f "$TMP_TARBALL"

echo "install_arm_toolchain: ARM GNU toolchain ready at $DEST — $got_ver"
exit 0

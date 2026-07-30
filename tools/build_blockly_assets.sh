#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
#
# Build the minimal offline Blockly runtime admitted by ADR-0013. The source
# submodule must remain pristine and at the exact reviewed commit.

set -euo pipefail

readonly EXPECTED_BLOCKLY_SHA='f4ad3f5117d6744120b05ccc5af666fcdc29df5f'
readonly SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
readonly REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd -P)"
readonly UPSTREAM_DIR="$REPO_ROOT/app/upstream/blockly"
readonly BLOCKLY_PACKAGE_DIR="$UPSTREAM_DIR/packages/blockly"
readonly ASSET_DIR="$REPO_ROOT/app/assets/blockly"
readonly VENDOR_DIR="$ASSET_DIR/vendor"

fail() {
  printf 'build_blockly_assets: %s\n' "$*" >&2
  exit 1
}

[ -e "$UPSTREAM_DIR/.git" ] ||
  fail "Blockly submodule is not initialized at $UPSTREAM_DIR"

actual_sha="$(git -C "$UPSTREAM_DIR" rev-parse HEAD 2>/dev/null)" ||
  fail 'cannot read the Blockly submodule revision'
[ "$actual_sha" = "$EXPECTED_BLOCKLY_SHA" ] ||
  fail "revision mismatch: expected $EXPECTED_BLOCKLY_SHA, got $actual_sha"

git -C "$UPSTREAM_DIR" diff --quiet -- ||
  fail 'Blockly submodule has tracked working-tree changes'
git -C "$UPSTREAM_DIR" diff --cached --quiet -- ||
  fail 'Blockly submodule has staged changes'
upstream_status="$(
  git -C "$UPSTREAM_DIR" status --porcelain --untracked-files=normal
)"
[ -z "$upstream_status" ] ||
  fail 'Blockly submodule has untracked files'

command -v npm >/dev/null 2>&1 || fail 'npm is required'
command -v node >/dev/null 2>&1 || fail 'node is required'
command -v file >/dev/null 2>&1 || fail 'file is required'

(
  cd "$UPSTREAM_DIR"
  npm ci --no-audit --no-fund
  npm run build --workspace=blockly
)

git -C "$UPSTREAM_DIR" diff --quiet -- ||
  fail 'Blockly build changed tracked upstream files'
git -C "$UPSTREAM_DIR" diff --cached --quiet -- ||
  fail 'Blockly build changed staged upstream files'
upstream_status="$(
  git -C "$UPSTREAM_DIR" status --porcelain --untracked-files=normal
)"
[ -z "$upstream_status" ] ||
  fail 'Blockly build left untracked upstream files'

readonly CORE_SOURCE="$BLOCKLY_PACKAGE_DIR/dist/blockly_compressed.js"
readonly BLOCKS_SOURCE="$BLOCKLY_PACKAGE_DIR/dist/blocks_compressed.js"
readonly PYTHON_SOURCE="$BLOCKLY_PACKAGE_DIR/dist/python_compressed.js"
readonly EN_SOURCE="$BLOCKLY_PACKAGE_DIR/build/msg/en.js"
readonly CATEGORY_EN_SOURCE="$BLOCKLY_PACKAGE_DIR/demos/code/msg/en.js"
readonly MEDIA_SOURCE="$BLOCKLY_PACKAGE_DIR/media"
readonly LICENSE_SOURCE="$UPSTREAM_DIR/LICENSE"

for required_path in \
  "$CORE_SOURCE" \
  "$BLOCKS_SOURCE" \
  "$PYTHON_SOURCE" \
  "$EN_SOURCE" \
  "$CATEGORY_EN_SOURCE" \
  "$MEDIA_SOURCE" \
  "$LICENSE_SOURCE"; do
  [ -e "$required_path" ] ||
    fail "expected build output is missing: $required_path"
done

mkdir -p "$ASSET_DIR"
BUILD_TMP="$(mktemp -d "$ASSET_DIR/.vendor.XXXXXX")"
readonly BUILD_TMP
cleanup() {
  if [ -n "${BUILD_TMP:-}" ] && [ -d "$BUILD_TMP" ]; then
    rm -rf -- "$BUILD_TMP"
  fi
}
trap cleanup EXIT

mkdir -p "$BUILD_TMP/msg" "$BUILD_TMP/media"
cp "$CORE_SOURCE" "$BUILD_TMP/blockly_compressed.js"
cp "$BLOCKS_SOURCE" "$BUILD_TMP/blocks_compressed.js"
node "$SCRIPT_DIR/normalize_blockly_python_asset.mjs" \
  "$PYTHON_SOURCE" \
  "$BUILD_TMP/python_compressed.js"
cp "$EN_SOURCE" "$BUILD_TMP/msg/en.js"
cp "$CATEGORY_EN_SOURCE" "$BUILD_TMP/msg/categories_en.js"
cp -R "$MEDIA_SOURCE/." "$BUILD_TMP/media/"
cp "$LICENSE_SOURCE" "$BUILD_TMP/LICENSE"

printf '%s\n' \
  '{' \
  '  "SPDX-License-Identifier": "MIT",' \
  '  "name": "Blockly offline runtime",' \
  '  "source": "https://github.com/RaspberryPiFoundation/blockly",' \
  "  \"commit\": \"$EXPECTED_BLOCKLY_SHA\"," \
  '  "release": "blockly-v13.1.0",' \
  '  "upstreamLicense": "Apache-2.0",' \
  '  "upstreamLicenseFile": "LICENSE",' \
  '  "generatedBy": "tools/build_blockly_assets.sh",' \
  '  "contents": [' \
  '    "blockly_compressed.js",' \
  '    "blocks_compressed.js",' \
  '    "python_compressed.js",' \
  '    "msg/en.js",' \
  '    "msg/categories_en.js",' \
  '    "media/"' \
  '  ]' \
  '}' \
  >"$BUILD_TMP/manifest.json"

find "$BUILD_TMP" -type d -exec chmod 0755 {} +
find "$BUILD_TMP" -type f -exec chmod 0644 {} +

while IFS= read -r -d '' vendor_asset; do
  asset_kind="$(file -b "$vendor_asset")"
  case "$asset_kind" in
    *"script"*"executable"*)
      fail "vendored data looks executable: $vendor_asset ($asset_kind)"
      ;;
  esac
done < <(find "$BUILD_TMP" -type f -print0)

case "$VENDOR_DIR" in
  "$REPO_ROOT/app/assets/blockly/vendor") ;;
  *) fail "refusing to replace unexpected path: $VENDOR_DIR" ;;
esac

rm -rf -- "$VENDOR_DIR"
mv "$BUILD_TMP" "$VENDOR_DIR"
trap - EXIT

printf 'build_blockly_assets: wrote %s from %s\n' \
  "$VENDOR_DIR" "$EXPECTED_BLOCKLY_SHA"

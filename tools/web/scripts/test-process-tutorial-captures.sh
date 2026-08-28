#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd -P)"
PROCESSOR="$SCRIPT_DIR/process-tutorial-captures.sh"
SCREENSHOTS_ROOT="$REPO_ROOT/ScreenShots"
TEST_ROOT=""

fail() {
  printf 'tutorial capture processor test failed: %s\n' "$*" >&2
  exit 1
}

cleanup() {
  if [ -n "$TEST_ROOT" ] && [ -d "$TEST_ROOT" ]; then
    find "$TEST_ROOT" -mindepth 1 -depth -delete
    rmdir "$TEST_ROOT"
  fi
}

trap cleanup EXIT HUP INT TERM

command -v magick >/dev/null 2>&1 || fail "ImageMagick's magick is required"
[ -x "$PROCESSOR" ] || fail "processor is not executable: $PROCESSOR"

CAPTURE_TABLE="$($PROCESSOR --list)"
[ "$(printf '%s\n' "$CAPTURE_TABLE" | wc -l | tr -d ' ')" = 18 ] ||
  fail "capture table must expose eighteen reviewed derivatives"
[ "$(printf '%s\n' "$CAPTURE_TABLE" | awk -F '\t' 'NF != 6 { bad = 1 } END { print bad + 0 }')" = 0 ] ||
  fail "capture rows must name source, key, width, height, crop x, and crop y"
[ "$(printf '%s\n' "$CAPTURE_TABLE" | cut -f1 | sort -u | wc -l | tr -d ' ')" = 13 ] ||
  fail "capture table must bind thirteen distinct raw frames"
[ "$(printf '%s\n' "$CAPTURE_TABLE" | cut -f2 | sort -u | wc -l | tr -d ' ')" = 18 ] ||
  fail "capture keys must be unique"

mkdir -p "$SCREENSHOTS_ROOT"
TEST_ROOT=$(mktemp -d "$SCREENSHOTS_ROOT/.capture-processor-test.XXXXXX")
INPUT_DIR="$TEST_ROOT/raw"
OUTPUT_DIR="$TEST_ROOT/reviewed"
UNMANAGED_DIR="$TEST_ROOT/unmanaged"
mkdir "$INPUT_DIR" "$UNMANAGED_DIR"

first_source=""
while IFS=$'\t' read -r source_name _capture_key; do
  if [ -z "$first_source" ]; then
    first_source="$INPUT_DIR/$source_name"
    magick -size 2000x1200 \
      gradient:'#102030-#d0e0f0' \
      -fill '#ff3355' \
      -draw 'rectangle 0,36 1999,64' \
      -set comment 'raw fixture metadata must not survive' \
      -depth 8 \
      "PNG32:$first_source"
  else
    cp "$first_source" "$INPUT_DIR/$source_name"
  fi
done < <("$PROCESSOR" --list)

"$PROCESSOR" --input-dir "$INPUT_DIR" --output-dir "$OUTPUT_DIR"

[ "$(wc -l <"$OUTPUT_DIR/tutorial-captures.tsv" | tr -d ' ')" = 9 ] ||
  fail "stable-key manifest must have one header and eight captures"
[ "$(wc -l <"$OUTPUT_DIR/SHA256SUMS" | tr -d ' ')" = 8 ] ||
  fail "reviewed checksum manifest must have eight captures"
[ "$(wc -l <"$OUTPUT_DIR/SOURCE_SHA256SUMS" | tr -d ' ')" = 8 ] ||
  fail "raw checksum manifest must have eight captures"

(cd "$OUTPUT_DIR" && shasum -a 256 -c SHA256SUMS >/dev/null)
(cd "$INPUT_DIR" && shasum -a 256 -c \
  "$OUTPUT_DIR/SOURCE_SHA256SUMS" >/dev/null)

tail -n +2 "$OUTPUT_DIR/tutorial-captures.tsv" |
  while IFS=$'\t' read -r capture_key output_name reviewed_sha256 \
    source_name raw_sha256; do
    case "$output_name" in
      "pyble-app-0.2.0-build-5-${capture_key}-${reviewed_sha256:0:12}.png") ;;
      *) fail "content-versioned filename does not match its manifest row" ;;
    esac
    [ "$(shasum -a 256 "$OUTPUT_DIR/$output_name" | awk '{print $1}')" = \
      "$reviewed_sha256" ] || fail "reviewed SHA-256 mismatch: $output_name"
    [ "$(shasum -a 256 "$INPUT_DIR/$source_name" | awk '{print $1}')" = \
      "$raw_sha256" ] || fail "raw SHA-256 mismatch: $source_name"
    [ "$(magick identify -format '%w %h %z' \
      "$OUTPUT_DIR/$output_name")" = '2000 1092 8' ] ||
      fail "unexpected reviewed dimensions: $output_name"
    [ -z "$(magick identify -format '%c' "$OUTPUT_DIR/$output_name")" ] ||
      fail "reviewed capture retained a PNG comment: $output_name"
    metric=$(
      magick "$INPUT_DIR/$source_name" -crop 2000x1092+0+36 +repage miff:- |
        magick compare -metric AE miff:- "$OUTPUT_DIR/$output_name" null: 2>&1
    ) || fail "reviewed capture differs from exact crop: $output_name"
    case "$metric" in
      0 | '0 (0)') ;;
      *) fail "reviewed capture changed app pixels: $output_name ($metric)" ;;
    esac
  done

cp "$OUTPUT_DIR/tutorial-captures.tsv" "$TEST_ROOT/first-manifest.tsv"
if "$PROCESSOR" --input-dir "$INPUT_DIR" --output-dir "$OUTPUT_DIR" \
  >"$TEST_ROOT/refusal.log" 2>&1; then
  fail "processor overwrote an existing review directory without --force"
fi

"$PROCESSOR" --input-dir "$INPUT_DIR" --output-dir "$OUTPUT_DIR" --force \
  >/dev/null
cmp "$TEST_ROOT/first-manifest.tsv" "$OUTPUT_DIR/tutorial-captures.tsv" ||
  fail "identical inputs did not produce an identical manifest"

printf 'unmanaged review note\n' >"$UNMANAGED_DIR/review-note.txt"
if "$PROCESSOR" --input-dir "$INPUT_DIR" --output-dir "$UNMANAGED_DIR" \
  --force >"$TEST_ROOT/unmanaged-refusal.log" 2>&1; then
  fail "processor replaced an output directory containing an unmanaged file"
fi

printf 'tutorial capture processor test: pass\n'

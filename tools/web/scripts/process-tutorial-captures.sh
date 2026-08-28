#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
#
# Produce local, reviewable tutorial screenshot derivatives. This command is
# deliberately unable to publish into tools/web/public: visual and privacy
# review is a separate promotion step.

set -euo pipefail

readonly OUTPUT_WIDTH=2000
readonly OUTPUT_HEIGHT=1092
readonly SOURCE_WIDTH=2000
readonly SOURCE_HEIGHT=1200
readonly CROP_TOP=36
readonly APP_VERSION=0.2.0
readonly APP_BUILD=5
readonly OUTPUT_PREFIX="pyble-app-${APP_VERSION}-build-${APP_BUILD}"

# Keep the finalized source-to-stable-key contract in one easy-to-audit table.
CAPTURE_TABLE=$(cat <<'EOF'
06-setup-scan-results-production-release.raw.png	setup-scan-results
07-setup-connected-identity-production-release.raw.png	setup-connected-identity
08-first-program-editor-console-production-release.raw.png	first-program-editor-console
09-files-multi-delete-review-production-release.raw.png	files-multi-delete-review
10-github-import-branch-chooser-production-release.raw.png	github-import-branch-chooser
11-github-import-prewrite-review-production-release.raw.png	github-import-prewrite-review
12-examples-import-complete-production-release.raw.png	examples-import-complete
20-blocks-hello-workspace-production-release.raw.png	blocks-hello-workspace
EOF
)
readonly CAPTURE_TABLE

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd -P)"
SCREENSHOTS_ROOT="$REPO_ROOT/ScreenShots"
STAGE_DIR=""

usage() {
  cat <<'EOF'
Usage:
  process-tutorial-captures.sh --input-dir ABSOLUTE_PATH \
    --output-dir ABSOLUTE_PATH [--force]
  process-tutorial-captures.sh --list

Both directories must be below this repository's ignored ScreenShots/
workspace. Use reviewed-tutorial-set/ for this capture set. The output
directory is replaced only when --force is explicit. The script never
publishes files into tools/web/public/.
EOF
}

fail() {
  printf 'tutorial capture processing failed: %s\n' "$*" >&2
  exit 1
}

cleanup_directory() {
  local directory="$1"

  if [ -n "$directory" ] && [ -d "$directory" ]; then
    find "$directory" -mindepth 1 -depth -delete
    rmdir "$directory"
  fi
}

cleanup() {
  if [ -n "$STAGE_DIR" ]; then
    cleanup_directory "$STAGE_DIR"
  fi
}

trap cleanup EXIT HUP INT TERM

sha256_file() {
  local path="$1"

  if command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$path" | awk '{print $1}'
  elif command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$path" | awk '{print $1}'
  else
    fail "shasum or sha256sum is required"
  fi
}

canonical_directory() {
  local directory="$1"

  [ -d "$directory" ] || fail "directory does not exist: $directory"
  (cd "$directory" && pwd -P)
}

require_screenshot_descendant() {
  local path="$1"
  local label="$2"

  case "$path/" in
    "$SCREENSHOTS_ROOT/"*) ;;
    *) fail "$label must be below $SCREENSHOTS_ROOT" ;;
  esac
}

validate_capture_table() {
  local source_name capture_key count=0

  while IFS=$'\t' read -r source_name capture_key; do
    [ -n "$source_name" ] || fail "capture table contains an empty source"
    [ -n "$capture_key" ] || fail "capture table contains an empty key"
    case "$source_name" in
      */* | .* | *..* | *[!A-Za-z0-9._-]*)
        fail "unsafe source filename in capture table: $source_name"
        ;;
      *.raw.png) ;;
      *) fail "source filename must end in .raw.png: $source_name" ;;
    esac
    case "$capture_key" in
      */* | .* | *..* | *[!a-z0-9-]*)
        fail "unsafe key in capture table: $capture_key"
        ;;
    esac
    count=$((count + 1))
  done <<<"$CAPTURE_TABLE"

  [ "$count" -eq 8 ] || fail "capture table must contain exactly eight rows"
}

is_managed_output_name() {
  local name="$1"
  local _source_name capture_key prefix hash

  case "$name" in
    SHA256SUMS | SOURCE_SHA256SUMS | tutorial-captures.tsv)
      return 0
      ;;
  esac

  while IFS=$'\t' read -r _source_name capture_key; do
    prefix="${OUTPUT_PREFIX}-${capture_key}-"
    case "$name" in
      "$prefix"*.png)
        hash="${name#"$prefix"}"
        hash="${hash%.png}"
        if [ "${#hash}" -eq 12 ]; then
          case "$hash" in
            *[!0-9a-f]*) ;;
            *) return 0 ;;
          esac
        fi
        ;;
    esac
  done <<<"$CAPTURE_TABLE"
  return 1
}

validate_existing_output_directory() {
  local output_directory="$1"
  local entry name

  while IFS= read -r -d '' entry; do
    [ ! -L "$entry" ] || fail "output directory contains a symlink: $entry"
    [ -f "$entry" ] || fail "output directory contains a non-file: $entry"
    name="${entry##*/}"
    is_managed_output_name "$name" ||
      fail "output directory contains an unmanaged file: $entry"
  done < <(find "$output_directory" -mindepth 1 -maxdepth 1 -print0)
}

validate_source_image() {
  local source_path="$1"
  local properties

  [ -f "$source_path" ] || fail "missing raw capture: $source_path"
  [ ! -L "$source_path" ] || fail "raw capture cannot be a symlink: $source_path"
  properties=$(magick identify -ping \
    -format '%n %w %h %m %z' "$source_path") ||
    fail "cannot identify raw capture: $source_path"
  [ "$properties" = "1 $SOURCE_WIDTH $SOURCE_HEIGHT PNG 8" ] ||
    fail "raw capture must be one 2000x1200 8-bit PNG: $source_path ($properties)"
}

verify_reviewed_image() {
  local source_path="$1"
  local output_path="$2"
  local properties metric

  properties=$(magick identify -ping \
    -format '%n %w %h %m %z' "$output_path") ||
    fail "cannot identify reviewed capture: $output_path"
  [ "$properties" = "1 $OUTPUT_WIDTH $OUTPUT_HEIGHT PNG 8" ] ||
    fail "reviewed capture has unexpected properties: $output_path ($properties)"

  metric=$(
    magick "$source_path" \
      -crop "${OUTPUT_WIDTH}x${OUTPUT_HEIGHT}+0+${CROP_TOP}" \
      +repage miff:- |
      magick compare -metric AE miff:- "$output_path" null: 2>&1
  ) || fail "reviewed capture pixels differ from the fixed crop: $output_path"
  case "$metric" in
    0 | '0 (0)') ;;
    *) fail "reviewed capture changed app pixels: $output_path ($metric)" ;;
  esac
}

replace_output_directory() {
  local staged_directory="$1"
  local output_directory="$2"
  local output_parent output_name backup_directory

  if [ ! -e "$output_directory" ]; then
    mv "$staged_directory" "$output_directory"
    STAGE_DIR=""
    return
  fi

  output_parent="${output_directory%/*}"
  output_name="${output_directory##*/}"
  backup_directory=$(mktemp -d \
    "$output_parent/.${output_name}.backup.XXXXXX")
  rmdir "$backup_directory"
  mv "$output_directory" "$backup_directory"
  if mv "$staged_directory" "$output_directory"; then
    STAGE_DIR=""
    cleanup_directory "$backup_directory"
    return
  fi

  mv "$backup_directory" "$output_directory" ||
    fail "could not restore the previous output directory: $output_directory"
  fail "could not install the reviewed captures: $output_directory"
}

validate_capture_table

if [ "${1:-}" = "--list" ]; then
  [ "$#" -eq 1 ] || fail "--list does not accept other arguments"
  printf '%s\n' "$CAPTURE_TABLE"
  exit 0
fi

INPUT_ARGUMENT=""
OUTPUT_ARGUMENT=""
FORCE=false
while [ "$#" -gt 0 ]; do
  case "$1" in
    --input-dir)
      [ "$#" -ge 2 ] || fail "--input-dir requires a path"
      [ -z "$INPUT_ARGUMENT" ] || fail "--input-dir was provided twice"
      INPUT_ARGUMENT="$2"
      shift 2
      ;;
    --output-dir)
      [ "$#" -ge 2 ] || fail "--output-dir requires a path"
      [ -z "$OUTPUT_ARGUMENT" ] || fail "--output-dir was provided twice"
      OUTPUT_ARGUMENT="$2"
      shift 2
      ;;
    --force)
      [ "$FORCE" = false ] || fail "--force was provided twice"
      FORCE=true
      shift
      ;;
    --help | -h)
      usage
      exit 0
      ;;
    *)
      usage >&2
      fail "unknown argument: $1"
      ;;
  esac
done

[ -n "$INPUT_ARGUMENT" ] || fail "--input-dir is required"
[ -n "$OUTPUT_ARGUMENT" ] || fail "--output-dir is required"
case "$INPUT_ARGUMENT" in /*) ;; *) fail "--input-dir must be absolute" ;; esac
case "$OUTPUT_ARGUMENT" in /*) ;; *) fail "--output-dir must be absolute" ;; esac
command -v magick >/dev/null 2>&1 || fail "ImageMagick's magick is required"
[ -d "$SCREENSHOTS_ROOT" ] || fail "ignored workspace is missing: $SCREENSHOTS_ROOT"

INPUT_DIR=$(canonical_directory "$INPUT_ARGUMENT")
require_screenshot_descendant "$INPUT_DIR" "input directory"

if [ -L "$OUTPUT_ARGUMENT" ]; then
  fail "output directory cannot be a symlink: $OUTPUT_ARGUMENT"
fi
if [ -e "$OUTPUT_ARGUMENT" ]; then
  OUTPUT_DIR=$(canonical_directory "$OUTPUT_ARGUMENT")
else
  OUTPUT_PARENT_ARGUMENT="${OUTPUT_ARGUMENT%/*}"
  OUTPUT_NAME="${OUTPUT_ARGUMENT##*/}"
  [ -n "$OUTPUT_NAME" ] || fail "output directory needs a final component"
  case "$OUTPUT_NAME" in . | ..) fail "unsafe output directory" ;; esac
  OUTPUT_PARENT=$(canonical_directory "$OUTPUT_PARENT_ARGUMENT")
  OUTPUT_DIR="$OUTPUT_PARENT/$OUTPUT_NAME"
fi
require_screenshot_descendant "$OUTPUT_DIR" "output directory"
[ "$OUTPUT_DIR" != "$INPUT_DIR" ] || fail "input and output directories must differ"

if [ -e "$OUTPUT_DIR" ]; then
  validate_existing_output_directory "$OUTPUT_DIR"
  if [ "$FORCE" = false ] &&
    [ -n "$(find "$OUTPUT_DIR" -mindepth 1 -maxdepth 1 -print -quit)" ]; then
    fail "output directory is not empty; use --force to replace managed outputs"
  fi
fi

while IFS=$'\t' read -r source_name _capture_key; do
  validate_source_image "$INPUT_DIR/$source_name"
done <<<"$CAPTURE_TABLE"

STAGE_DIR=$(mktemp -d "$SCREENSHOTS_ROOT/.tutorial-captures.stage.XXXXXX")
printf 'capture_key\treviewed_filename\treviewed_sha256\traw_filename\traw_sha256\n' \
  >"$STAGE_DIR/tutorial-captures.tsv"
while IFS=$'\t' read -r source_name capture_key; do
  source_path="$INPUT_DIR/$source_name"
  temporary_output="$STAGE_DIR/.${capture_key}.png"
  magick "$source_path" \
    -crop "${OUTPUT_WIDTH}x${OUTPUT_HEIGHT}+0+${CROP_TOP}" \
    +repage \
    -strip \
    -depth 8 \
    -define png:exclude-chunks=date,time \
    -define png:compression-level=9 \
    -define png:compression-filter=5 \
    -define png:compression-strategy=1 \
    "$temporary_output"
  verify_reviewed_image "$source_path" "$temporary_output"
  reviewed_sha256=$(sha256_file "$temporary_output")
  output_name="${OUTPUT_PREFIX}-${capture_key}-${reviewed_sha256:0:12}.png"
  output_path="$STAGE_DIR/$output_name"
  mv "$temporary_output" "$output_path"
  raw_sha256=$(sha256_file "$source_path")
  printf '%s\t%s\t%s\t%s\t%s\n' \
    "$capture_key" "$output_name" "$reviewed_sha256" \
    "$source_name" "$raw_sha256" \
    >>"$STAGE_DIR/tutorial-captures.tsv"
done <<<"$CAPTURE_TABLE"

tail -n +2 "$STAGE_DIR/tutorial-captures.tsv" |
  awk -F '\t' '{print $3 "  " $2}' >"$STAGE_DIR/SHA256SUMS"

tail -n +2 "$STAGE_DIR/tutorial-captures.tsv" |
  awk -F '\t' '{print $5 "  " $4}' >"$STAGE_DIR/SOURCE_SHA256SUMS"

replace_output_directory "$STAGE_DIR" "$OUTPUT_DIR"
printf 'Prepared 8 reviewed captures in %s\n' "$OUTPUT_DIR"
printf 'Review SHA-256 manifest: %s/SHA256SUMS\n' "$OUTPUT_DIR"
printf 'Raw SHA-256 manifest: %s/SOURCE_SHA256SUMS\n' "$OUTPUT_DIR"
printf 'Stable-key manifest: %s/tutorial-captures.tsv\n' "$OUTPUT_DIR"

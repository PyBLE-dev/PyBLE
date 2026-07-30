#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
#
# Validate the exported iOS payload, including the script-like Flutter asset
# classification that codesign --deep does not detect but App Store validation
# rejects as unsigned nested code.

set -euo pipefail

readonly REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
readonly IPA_PATH="${1:-$REPO_ROOT/app/build/ios/ipa/PyBLE.ipa}"

fail() {
  printf 'validate_ios_ipa: %s\n' "$*" >&2
  exit 1
}

[ -f "$IPA_PATH" ] || fail "IPA does not exist: $IPA_PATH"
command -v codesign >/dev/null 2>&1 || fail 'codesign is required'
command -v ditto >/dev/null 2>&1 || fail 'ditto is required'
command -v file >/dev/null 2>&1 || fail 'file is required'
command -v plutil >/dev/null 2>&1 || fail 'plutil is required'
command -v xcrun >/dev/null 2>&1 || fail 'xcrun is required'
SWINFO_PATH="$(xcrun --find swinfo 2>/dev/null)" ||
  fail 'Xcode swinfo is unavailable'
readonly SWINFO_PATH
[ -x "$SWINFO_PATH" ] || fail "Xcode swinfo is unavailable: $SWINFO_PATH"

VERIFY_DIR="$(mktemp -d /tmp/pyble-ios-ipa.XXXXXX)"
readonly VERIFY_DIR
cleanup() {
  if [ -n "${VERIFY_DIR:-}" ] && [ -d "$VERIFY_DIR" ]; then
    rm -R "$VERIFY_DIR"
  fi
}
trap cleanup EXIT

ditto -x -k "$IPA_PATH" "$VERIFY_DIR"

app_count="$(
  find "$VERIFY_DIR/Payload" -mindepth 1 -maxdepth 1 -type d -name '*.app' |
    wc -l |
    tr -d '[:space:]'
)"
[ "$app_count" = '1' ] ||
  fail "expected one application in Payload, found $app_count"

APP_PATH="$(find "$VERIFY_DIR/Payload" -mindepth 1 -maxdepth 1 -type d -name '*.app')"
readonly APP_PATH
readonly FLUTTER_ASSETS="$APP_PATH/Frameworks/App.framework/flutter_assets"
[ -d "$FLUTTER_ASSETS" ] ||
  fail "Flutter assets are missing: $FLUTTER_ASSETS"

codesign --verify --deep --strict --verbose=4 "$APP_PATH"

script_like_files=0
while IFS= read -r -d '' file_path; do
  file_kind="$(file -b "$file_path")"
  lowercase_kind="$(printf '%s' "$file_kind" | tr '[:upper:]' '[:lower:]')"
  case "$lowercase_kind" in
    *script*executable*)
      printf 'validate_ios_ipa: unsigned script-like file: %s (%s)\n' \
        "${file_path#"$APP_PATH"/}" \
        "$file_kind" >&2
      script_like_files=$((script_like_files + 1))
      ;;
  esac
done < <(find "$APP_PATH" -type f -print0)
[ "$script_like_files" = '0' ] ||
  fail "$script_like_files file(s) would be treated as unsigned nested code"

invalid_executables=0
while IFS= read -r -d '' file_path; do
  file_kind="$(file -b "$file_path")"
  case "$file_kind" in
    Mach-O*)
      ;;
    *)
      printf 'validate_ios_ipa: non-Mach-O file has executable mode: %s (%s)\n' \
        "${file_path#"$APP_PATH"/}" \
        "$file_kind" >&2
      invalid_executables=$((invalid_executables + 1))
      ;;
  esac
done < <(find "$APP_PATH" -type f -perm +111 -print0)
[ "$invalid_executables" = '0' ] ||
  fail "$invalid_executables non-Mach-O file(s) have executable mode"

readonly SWINFO_PLIST="$VERIFY_DIR/swinfo.plist"
readonly SWINFO_ERRORS="$VERIFY_DIR/swinfo-errors.json"
if ! "$SWINFO_PATH" -f "$IPA_PATH" -prettyprint false \
  >"$SWINFO_PLIST" 2>"$VERIFY_DIR/swinfo.stderr"; then
  cat "$VERIFY_DIR/swinfo.stderr" >&2
  fail 'Xcode swinfo could not analyze the IPA'
fi

if plutil -extract product-errors json -o "$SWINFO_ERRORS" \
  "$SWINFO_PLIST" 2>/dev/null; then
  swinfo_error_count="$(
    plutil -extract product-errors raw -o - "$SWINFO_PLIST"
  )"
  unexpected_swinfo_errors=0
  ignored_resource_bundles=0
  swinfo_error_index=0
  while [ "$swinfo_error_index" -lt "$swinfo_error_count" ]; do
    swinfo_error_path="$(
      plutil -extract "product-errors.$swinfo_error_index.path" raw -o - \
        "$SWINFO_PLIST"
    )"
    swinfo_error_code="$(
      plutil -extract "product-errors.$swinfo_error_index.code-string" raw \
        -o - "$SWINFO_PLIST"
    )"
    swinfo_error_status="$(
      plutil -extract "product-errors.$swinfo_error_index.osstatus" raw -o - \
        "$SWINFO_PLIST"
    )"

    case "$swinfo_error_path" in
      Runner.app/*.bundle)
        if [ "$swinfo_error_code" = \
          'ITunesSoftwareServiceUnableToAnalyzeSigningInformation' ] &&
          [ "$swinfo_error_status" = '-67062' ]; then
          ignored_resource_bundles=$((ignored_resource_bundles + 1))
        else
          unexpected_swinfo_errors=$((unexpected_swinfo_errors + 1))
        fi
        ;;
      *)
        unexpected_swinfo_errors=$((unexpected_swinfo_errors + 1))
        ;;
    esac
    swinfo_error_index=$((swinfo_error_index + 1))
  done

  if [ "$unexpected_swinfo_errors" != '0' ]; then
    plutil -extract product-errors xml1 -o - "$SWINFO_PLIST" |
      plutil -p - >&2
    fail "Xcode swinfo reported $unexpected_swinfo_errors unexpected error(s)"
  fi
  if [ "$ignored_resource_bundles" != '0' ]; then
    printf \
      'validate_ios_ipa: ignored %s expected unsigned resource-bundle record(s)\n' \
      "$ignored_resource_bundles"
  fi
fi

printf 'validate_ios_ipa: valid App Store payload: %s\n' "$IPA_PATH"

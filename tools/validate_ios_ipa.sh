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
readonly IOS_DEPLOYMENT_FLOOR='15.0'

fail() {
  printf 'validate_ios_ipa: %s\n' "$*" >&2
  exit 1
}

version_at_least() {
  local actual="$1"
  local floor="$2"
  awk -v actual="$actual" -v floor="$floor" '
    function valid(version, parts, count, part_index) {
      count = split(version, parts, ".")
      if (count < 1 || count > 3) {
        return 0
      }
      for (part_index = 1; part_index <= count; part_index += 1) {
        if (parts[part_index] !~ /^[0-9]+$/) {
          return 0
        }
      }
      return 1
    }
    function component(version, wanted, parts, count) {
      count = split(version, parts, ".")
      return wanted <= count ? parts[wanted] + 0 : 0
    }
    BEGIN {
      if (!valid(actual) || !valid(floor)) {
        exit 2
      }
      for (part_index = 1; part_index <= 3; part_index += 1) {
        actual_component = component(actual, part_index)
        floor_component = component(floor, part_index)
        if (actual_component > floor_component) {
          exit 0
        }
        if (actual_component < floor_component) {
          exit 1
        }
      }
      exit 0
    }
  '
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
VTOOL_PATH="$(xcrun --find vtool 2>/dev/null)" ||
  fail 'Xcode vtool is unavailable'
readonly VTOOL_PATH
[ -x "$VTOOL_PATH" ] || fail "Xcode vtool is unavailable: $VTOOL_PATH"

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

readonly APP_INFO_PLIST="$APP_PATH/Info.plist"
APP_MINIMUM_IOS="$(
  plutil -extract MinimumOSVersion raw -o - "$APP_INFO_PLIST" 2>/dev/null
)" || fail 'top-level application MinimumOSVersion is missing'
readonly APP_MINIMUM_IOS
APP_EXECUTABLE_NAME="$(
  plutil -extract CFBundleExecutable raw -o - "$APP_INFO_PLIST" 2>/dev/null
)" || fail 'top-level application CFBundleExecutable is missing'
readonly APP_EXECUTABLE_NAME
case "$APP_EXECUTABLE_NAME" in
  '' | '.' | '..' | */*)
    fail "unsafe top-level application executable: $APP_EXECUTABLE_NAME"
    ;;
esac
readonly APP_EXECUTABLE_PATH="$APP_PATH/$APP_EXECUTABLE_NAME"
[ -f "$APP_EXECUTABLE_PATH" ] ||
  fail "top-level application executable is missing: $APP_EXECUTABLE_NAME"
APP_BUILD_INFO="$(
  "$VTOOL_PATH" -show-build "$APP_EXECUTABLE_PATH" 2>/dev/null
)" || fail 'Xcode vtool could not inspect the top-level application executable'
readonly APP_BUILD_INFO

version_at_least "$APP_MINIMUM_IOS" "$IOS_DEPLOYMENT_FLOOR" ||
  fail "expected iOS deployment floor >= $IOS_DEPLOYMENT_FLOOR; app plist has $APP_MINIMUM_IOS"

build_record_count=0
while IFS=$'\t' read -r build_platform build_minimum; do
  [ -n "$build_platform" ] || continue
  build_record_count=$((build_record_count + 1))
  [ "$build_platform" = 'IOS' ] ||
    fail "unexpected compiled platform $build_platform in $APP_EXECUTABLE_NAME"
  version_at_least "$build_minimum" "$IOS_DEPLOYMENT_FLOOR" ||
    fail "compiled iOS minimum $build_minimum is below $IOS_DEPLOYMENT_FLOOR"
done < <(
  printf '%s\n' "$APP_BUILD_INFO" |
    awk '$1 == "platform" { platform = $2 }
         $1 == "minos" { print platform "\t" $2; platform = "" }'
)
[ "$build_record_count" -gt 0 ] ||
  fail "compiled iOS minimum is missing from $APP_EXECUTABLE_NAME"

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

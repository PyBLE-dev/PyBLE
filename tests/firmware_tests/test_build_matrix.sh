#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
#
# [red] X-03 — Build matrix + target mapping (BLD-3/4/5, CON-11).
# AC:
#  - build.sh <target> builds exactly one of esp32 / esp32-s3 / esp32-c3;
#    build_all.sh builds all three.
#  - Each PyBLE target maps to its IDF target (esp32->esp32, esp32-s3->esp32s3,
#    esp32-c3->esp32c3) with the matching overlay; no silent toolchain sub.
#  - Each successful per-target build emits firmware.bin + bootloader + partition.
#
# Contract asserted for the production scripts (HAND-OFF: build-smith,
# firmware/scripts/build.sh + build_all.sh):
#   build.sh --plan <target>  — dry-run, needs NO ESP-IDF; exits 0 and prints
#     the resolved IDF target as `idf_target=<mapped>`, the overlay path
#     board_overlays/<target>, and the planned artifact set (bootloader,
#     partition-table, firmware.bin). Unknown target -> exit non-zero.
#   build.sh <target>  — a REAL build with no ESP-IDF/submodule MUST exit
#     non-zero with an actionable message and MUST NOT print success (never fake).
#   build_all.sh --plan  — plans all three targets.
#
# RED NOW: firmware/scripts/build.sh + build_all.sh do not exist.

set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
. "$HERE/lib/common.sh"
. "$HERE/lib/assert.sh"
_ASSERT_NAME="test_build_matrix"

# assert_plan_maps <pyble_target> <expected_idf_target>
assert_plan_maps() {
  local t="$1" idf="$2" out
  out="$("$BUILD_SH" --plan "$t" 2>&1)"
  printf '%s\n' "$out" | grep -qiE "idf[_-]?target[[:space:]]*[:=][[:space:]]*${idf}([^0-9a-z]|$)" \
    && pass "build.sh --plan $t maps to idf target $idf (no silent sub)" \
    || fail "build.sh --plan $t must print idf_target=$idf"
  printf '%s\n' "$out" | grep -qiE "board_overlays/${t}([^0-9a-z-]|$)" \
    && pass "build.sh --plan $t selects overlay board_overlays/$t" \
    || fail "build.sh --plan $t must select overlay board_overlays/$t"
}

run() {
  require_gate "$BUILD_SH" "build-smith · firmware/scripts/build.sh" || return 0

  # Unknown / missing target rejected.
  check_fail "build.sh rejects an unknown target"     "$BUILD_SH" --plan bogus-9000
  check_fail "build.sh rejects a missing target arg"  "$BUILD_SH" --plan

  # Target -> IDF mapping, no silent substitution.
  assert_plan_maps "esp32"    "esp32"
  assert_plan_maps "esp32-s3" "esp32s3"
  assert_plan_maps "esp32-c3" "esp32c3"

  # Planned artifact set (BLD-5) surfaced in the plan.
  local plan; plan="$("$BUILD_SH" --plan esp32 2>&1)"
  printf '%s\n' "$plan" | grep -qiE 'firmware\.bin' \
    && pass "plan lists firmware.bin as a build artifact (BLD-5)" \
    || fail "plan must list firmware.bin"
  printf '%s\n' "$plan" | grep -qiE 'bootloader' \
    && pass "plan lists the bootloader artifact (BLD-5)" \
    || fail "plan must list the bootloader"
  printf '%s\n' "$plan" | grep -qiE 'partition' \
    && pass "plan lists the partition table artifact (BLD-5)" \
    || fail "plan must list the partition table"

  # Never fake a build: a REAL build with no ESP-IDF must fail loudly.
  local out rc
  out="$(PYBLE_UPSTREAM_DIR="$(mk_tmp)" "$BUILD_SH" esp32 2>&1)"; rc=$?
  if [ "$rc" -ne 0 ]; then
    pass "build.sh esp32 with no ESP-IDF/submodule exits non-zero (never fakes success)"
  else
    fail "build.sh esp32 must NOT exit 0 without a real toolchain"
  fi
  printf '%s\n' "$out" | grep -qiE 'esp-?idf|submodule|toolchain|not (installed|found|initiali[sz]ed)' \
    && pass "build.sh emits an actionable missing-toolchain message" \
    || fail "build.sh must explain the missing ESP-IDF/submodule (actionable)"

  # build_all plans all three targets.
  if require_gate "$BUILD_ALL" "build-smith · firmware/scripts/build_all.sh"; then
    local all; all="$("$BUILD_ALL" --plan 2>&1)"
    printf '%s\n' "$all" | grep -qiE 'esp32([^0-9a-z-]|$)' && \
    printf '%s\n' "$all" | grep -qiE 'esp32s3' && \
    printf '%s\n' "$all" | grep -qiE 'esp32c3' \
      && pass "build_all.sh --plan drives all three targets (esp32, esp32s3, esp32c3)" \
      || fail "build_all.sh --plan must drive all three targets"
  fi
}

run
finish

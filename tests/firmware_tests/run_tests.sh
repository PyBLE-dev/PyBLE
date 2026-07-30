#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
#
# Host test runner for the firmware gate tests. Runs every test_*.sh in this
# directory as its own process; a non-zero exit is a failed test file. No
# hardware, no ESP-IDF, no submodule fetch required.
#
# Usage:  tests/firmware_tests/run_tests.sh            # run all
#         tests/firmware_tests/run_tests.sh test_no_leak.sh   # run one/some

set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"

if [ "$#" -gt 0 ]; then
  tests=("$@")
else
  tests=()
  for t in "$HERE"/test_*.sh; do
    tests+=("$(basename "$t")")
  done
fi

total=0; failed=0; failed_names=""
for name in "${tests[@]}"; do
  path="$HERE/$name"
  [ -f "$path" ] || { printf '  MISSING test file: %s\n' "$name"; failed=$((failed+1)); total=$((total+1)); continue; }
  total=$((total+1))
  printf '\n== %s ==\n' "$name"
  if bash "$path"; then
    :
  else
    failed=$((failed+1))
    failed_names="$failed_names $name"
  fi
done

printf '\n========================================\n'
printf 'firmware_tests: %d files, %d failed\n' "$total" "$failed"
if [ "$failed" -ne 0 ]; then
  printf 'RED (expected at S1 until [green] lands):%s\n' "$failed_names"
  exit 1
fi
printf 'ALL GREEN\n'
exit 0

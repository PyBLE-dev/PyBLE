#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
#
# Minimal host-runnable assertion helpers for the firmware gate tests.
# No external deps; POSIX-ish bash (works on macOS bash 3.2). Each test file
# sources this, wraps its body in a `run` function, then calls `finish`.
#
# Counters are process-global; run_tests.sh runs each test file as its own
# process and treats a non-zero exit as a failed test file.

_ASSERT_RUN=0
_ASSERT_FAIL=0
_ASSERT_NAME="${_ASSERT_NAME:-$(basename "${0:-test}")}"

# pass DESC — record a passing check.
pass() {
  _ASSERT_RUN=$((_ASSERT_RUN + 1))
  printf '    ok   - %s\n' "$1"
}

# fail DESC — record a failing check.
fail() {
  _ASSERT_RUN=$((_ASSERT_RUN + 1))
  _ASSERT_FAIL=$((_ASSERT_FAIL + 1))
  printf '    FAIL - %s\n' "$1"
}

# note MSG — informational line, not a check (used for DEFERRED / hand-off).
note() {
  printf '    ..   - %s\n' "$1"
}

# check DESC CMD... — passes iff CMD exits 0.
check() {
  local desc="$1"; shift
  if "$@" >/dev/null 2>&1; then pass "$desc"; else fail "$desc"; fi
}

# check_fail DESC CMD... — passes iff CMD exits non-zero.
# WARNING: never use this to test a gate script's rejection path without first
# proving the script exists (require_gate), or a MISSING script (rc 127) would
# masquerade as a passing rejection.
check_fail() {
  local desc="$1"; shift
  if "$@" >/dev/null 2>&1; then fail "$desc"; else pass "$desc"; fi
}

# check_eq DESC EXPECTED ACTUAL
check_eq() {
  if [ "$2" = "$3" ]; then pass "$1"; else fail "$1 (expected [$2], got [$3])"; fi
}

# check_file DESC PATH — file exists.
check_file() {
  if [ -f "$2" ]; then pass "$1"; else fail "$1 (no file: $2)"; fi
}

# check_grep DESC PATTERN PATH — case-insensitive extended-regex match in file.
check_grep() {
  if grep -qiE "$2" "$3" 2>/dev/null; then pass "$1"; else fail "$1 (pattern not found: $2 in $3)"; fi
}

# require_gate PATH HANDOFF — the production gate script must exist and be
# executable. If not, record ONE failure (with the routing note) and return 1
# so the caller can skip behavioural asserts that would otherwise false-pass.
# This is what keeps every test RED for the intended reason while the [green]
# production code is still owed by another engineer.
require_gate() {
  if [ -x "$1" ]; then
    return 0
  fi
  fail "MISSING production gate: $1 — HAND-OFF: $2"
  return 1
}

# finish — print a one-line summary and exit non-zero if any check failed.
finish() {
  printf '# %s: %d checks, %d failed\n' "$_ASSERT_NAME" "$_ASSERT_RUN" "$_ASSERT_FAIL"
  [ "$_ASSERT_FAIL" -eq 0 ] || return 1
  return 0
}

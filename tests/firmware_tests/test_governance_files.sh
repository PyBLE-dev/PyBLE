#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
#
# X-01 — Governance files present + DCO documented.
# AC: "The repo ships an MIT LICENSE at root, plus README, CONTRIBUTING, and
#      CODE_OF_CONDUCT" and "DCO sign-off (git commit -s) is documented in
#      CONTRIBUTING".
#
# NOTE: these criteria are satisfied by the X-01 [green] bootstrap artifacts,
# which already exist at root — so this test is expected to pass NOW. It is the
# standing regression guard for the contributable-repo criterion, not a [red]
# test. The RED parts of X-01 are the SPDX and DCO *lint* checks
# (test_spdx_header.sh, test_dco_signoff.sh).

set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
. "$HERE/lib/common.sh"
. "$HERE/lib/assert.sh"
_ASSERT_NAME="test_governance_files"

run() {
  check_file "MIT LICENSE at repo root"        "$REPO_ROOT/LICENSE"
  check_file "README at repo root"             "$REPO_ROOT/README.md"
  check_file "CONTRIBUTING at repo root"       "$REPO_ROOT/CONTRIBUTING.md"
  check_file "CODE_OF_CONDUCT at repo root"    "$REPO_ROOT/CODE_OF_CONDUCT.md"

  check_grep "LICENSE is MIT" "MIT License|Permission is hereby granted, free of charge" "$REPO_ROOT/LICENSE"
  check_grep "CONTRIBUTING documents DCO sign-off via 'git commit -s'" \
    "git commit -s" "$REPO_ROOT/CONTRIBUTING.md"
  check_grep "CONTRIBUTING references the Developer Certificate of Origin (DCO)" \
    "developer certificate of origin|DCO" "$REPO_ROOT/CONTRIBUTING.md"
}

run
finish

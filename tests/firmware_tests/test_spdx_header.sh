#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
#
# [red] X-01 — SPDX-MIT header lint (NFR-MAINT-4).
# AC: "Every PyBLE firmware source file carries an SPDX-License-Identifier: MIT
#      header, enforced by a lint check."
#
# Contract asserted for the production gate (HAND-OFF: build-smith,
# tools/ci/spdx_lint.sh):
#   spdx_lint.sh [ROOT]  — scans source files (.py/.c/.h/.dart/.sh) under ROOT
#     (default repo root); exits 0 iff every source file carries the header;
#     exits non-zero and names the offender if any file is missing it.
#
# RED NOW: tools/ci/spdx_lint.sh does not exist -> require_gate records a fail.

set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
# shellcheck source=lib/common.sh
. "$HERE/lib/common.sh"
# shellcheck source=lib/assert.sh
. "$HERE/lib/assert.sh"
_ASSERT_NAME="test_spdx_header"

run() {
  require_gate "$SPDX_LINT" "build-smith · tools/ci/spdx_lint.sh" || return 0

  local tmp; tmp="$(mk_tmp)"
  mkdir -p "$tmp/firmware/pyble"

  # A compliant source file: has the header.
  printf '# SPDX-License-Identifier: MIT\nprint("ok")\n' \
    > "$tmp/firmware/pyble/with_header.py"
  check "spdx_lint PASSES a tree where every source file carries the header" \
    "$SPDX_LINT" "$tmp"

  # A non-compliant source file: no header.
  printf 'print("no header here")\n' \
    > "$tmp/firmware/pyble/missing_header.py"
  check_fail "spdx_lint FAILS when a source file is missing SPDX-License-Identifier: MIT" \
    "$SPDX_LINT" "$tmp"

  rm -rf "$tmp"

  # The public Next.js site is authored PyBLE source and follows the same rule.
  local web; web="$(mk_tmp)"
  mkdir -p "$web/tools/web/src/app"
  printf 'export default function Page() { return null; }\n' \
    > "$web/tools/web/src/app/page.tsx"
  check_fail "spdx_lint FAILS when website TSX is missing the SPDX-MIT header" \
    "$SPDX_LINT" "$web"
  rm -rf "$web"

  # Meta: every committed script in this test tree must itself carry the header.
  local miss=0 f
  while IFS= read -r f; do
    grep -q 'SPDX-License-Identifier: MIT' "$f" || { miss=1; note "self-check: missing header in $f"; }
  done < <(find "$HERE" -type f \( -name '*.sh' -o -name '*.py' \) )
  check_eq "every committed firmware_tests script carries an SPDX-MIT header" "0" "$miss"
}

run
finish

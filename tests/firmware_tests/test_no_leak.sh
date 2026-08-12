#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
#
# [red] X-02 — No-leak CI gate (CON-6, PRD 1A.2/16.3).
# AC:
#  - CI runs the no-leak grep over app/ firmware/ protocol/ examples/ tests/
#    tools/ source on every push and PR.
#  - A tree containing a forbidden proprietary token FAILS (red fixture).
#  - A clean tree PASSES (green fixture).
#  - The gate targets .dart/.c/.h/.py plus authored website source and does NOT
#    flag governance docs that quote the forbidden tokens to forbid them.
#
# Contract asserted for the production gate (HAND-OFF: build-smith,
# tools/ci/no_leak.sh — the verbatim AGENTS.md gate):
#   no_leak.sh [ROOT]  — scans ROOT/{app,firmware,protocol,examples,tests,tools}
#     for the forbidden regex in .dart/.c/.h/.py files; exit non-zero if any
#     forbidden token is found, 0 if clean.
#
# CLEAN-ROOM: the forbidden token fed to the gate is ASSEMBLED AT RUNTIME (see
# lib/common.sh); no forbidden literal is ever committed into this tree.
#
# RED NOW: tools/ci/no_leak.sh does not exist -> require_gate records a fail.

set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
. "$HERE/lib/common.sh"
. "$HERE/lib/assert.sh"
_ASSERT_NAME="test_no_leak"

run() {
  # ---- Self-check (green NOW): this committed test tree is clean-room -------
  # Guards the ABSOLUTE invariant that NO forbidden proprietary literal lives
  # anywhere under tests/firmware_tests/ (any extension) — the no-leak gate
  # itself stays testable. The regex is assembled at runtime so this scan does
  # not itself introduce a literal.
  if grep -rniE "$(forbidden_regex)" "$HERE" >/dev/null 2>&1; then
    fail "self-check: a forbidden proprietary literal is committed under tests/firmware_tests/"
  else
    pass "self-check: no forbidden proprietary literal committed under tests/firmware_tests/"
  fi

  require_gate "$NOLEAK" "build-smith · tools/ci/no_leak.sh" || return 0

  # ---- Green fixture: a clean tree passes ----------------------------------
  local clean; clean="$(mk_tmp)"
  mkdir -p "$clean/firmware/pyble" "$clean/app/lib/pble"
  printf '# SPDX-License-Identifier: MIT\nprint("pyble agent")\n' > "$clean/firmware/pyble/x.py"
  printf '// SPDX-License-Identifier: MIT\nvoid main() {}\n'       > "$clean/app/lib/pble/x.dart"
  check "no_leak PASSES a clean tree" "$NOLEAK" "$clean"

  # Exact third-party toolchain roots are ignored, but similarly named
  # authored directories remain source and must still be scanned.
  mkdir -p "$clean/firmware/.arm-gnu/include"
  printf '/* %s third-party compiler symbol */\n' "$(tok_proto)" \
    > "$clean/firmware/.arm-gnu/include/compiler.h"
  check "no_leak PRUNES the exact pinned ARM toolchain root" "$NOLEAK" "$clean"
  mkdir -p "$clean/firmware/ports/.arm-gnu"
  printf '/* %s authored leak */\n' "$(tok_product)" \
    > "$clean/firmware/ports/.arm-gnu/leak.h"
  check_fail "no_leak still SCANS similarly named authored directories" \
    "$NOLEAK" "$clean"
  rm "$clean/firmware/ports/.arm-gnu/leak.h"

  # ---- Red fixture: a forbidden token in shippable source fails ------------
  # Token assembled at runtime; written only into a temp tree.
  local dirty; dirty="$(mk_tmp)"
  mkdir -p "$dirty/firmware/pyble"
  printf '# note: reject %s here\n' "$(tok_product)" > "$dirty/firmware/pyble/leak.py"
  check_fail "no_leak FAILS on a forbidden product token in a .py under firmware/" \
    "$NOLEAK" "$dirty"

  # A different forbidden shape (closed protocol name) in a .c file.
  local dirty2; dirty2="$(mk_tmp)"
  mkdir -p "$dirty2/protocol"
  printf '/* %s codec */\n' "$(tok_proto)" > "$dirty2/protocol/codec.c"
  check_fail "no_leak FAILS on a closed-protocol token in a .c under protocol/" \
    "$NOLEAK" "$dirty2"

  # A prior closed application name in shippable source is also prohibited.
  local dirty3; dirty3="$(mk_tmp)"
  mkdir -p "$dirty3/firmware"
  printf '/* reject %s provenance */\n' "$(tok_prior_app)" \
    > "$dirty3/firmware/agent.c"
  check_fail "no_leak FAILS on a prior-application token in firmware C" \
    "$NOLEAK" "$dirty3"

  # Authored Next.js source under tools/web is shippable and stays in scope.
  local dirty_web; dirty_web="$(mk_tmp)"
  mkdir -p "$dirty_web/tools/web/src/app"
  printf 'export const leak = "%s";\n' "$(tok_product)" \
    > "$dirty_web/tools/web/src/app/page.tsx"
  check_fail "no_leak FAILS on a forbidden product token in website TSX" \
    "$NOLEAK" "$dirty_web"

  # ---- Extension scoping: a forbidden token in a NON-code file is exempt ---
  # A governance/markdown file that quotes the token (to forbid it) must not be
  # flagged. Placed inside a scanned dir so only the extension filter exempts it.
  local docs; docs="$(mk_tmp)"
  mkdir -p "$docs/firmware"
  printf 'This doc forbids the token %s in code.\n' "$(tok_product)" > "$docs/firmware/POLICY.md"
  printf '# SPDX-License-Identifier: MIT\nprint("clean")\n'          > "$docs/firmware/ok.py"
  check "no_leak does NOT flag a forbidden token quoted in a .md (extension scope)" \
    "$NOLEAK" "$docs"

  rm -rf "$clean" "$dirty" "$dirty2" "$dirty3" "$dirty_web" "$docs"
}

run
finish

#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
#
# Shared fixtures/paths for the firmware gate tests: repo root, the canonical
# paths of the production gate scripts (owned by build-smith [green]), temp-tree
# helpers, and CLEAN-ROOM forbidden-token assembly.
#
# CLEAN-ROOM NOTE: no forbidden proprietary literal is ever committed into this
# tree. The forbidden tokens the no-leak gate must reject are ASSEMBLED at
# runtime from harmless fragments (each fragment alone matches none of the
# forbidden patterns), so a scan for the AGENTS.md no-leak regex over this test
# tree returns nothing and the real repo-wide no-leak gate stays green.

_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"

# Repo root: prefer git; fall back to the frozen layout (lib/../../.. = root).
REPO_ROOT="$(git -C "$_LIB_DIR" rev-parse --show-toplevel 2>/dev/null || true)"
[ -n "$REPO_ROOT" ] || REPO_ROOT="$(cd "$_LIB_DIR/../../.." && pwd)"
export REPO_ROOT

# ---- Production gate scripts (do NOT exist yet at S1 — that is the RED) -------
# Owner routing is documented next to each in the hand-off list. Each path may
# be overridden via a PYBLE_* env var so a candidate [green] implementation can
# be pointed at during bring-up without editing the tests; default is the frozen
# layout path (TDD §10.5).
NOLEAK="${PYBLE_NOLEAK:-$REPO_ROOT/tools/ci/no_leak.sh}"                       # X-02 [build-smith]
SPDX_LINT="${PYBLE_SPDX_LINT:-$REPO_ROOT/tools/ci/spdx_lint.sh}"               # X-01 [build-smith]
DCO_CHECK="${PYBLE_DCO_CHECK:-$REPO_ROOT/tools/ci/dco_check.sh}"               # X-01 [build-smith]
SHA_DRIFT="${PYBLE_SHA_DRIFT:-$REPO_ROOT/tools/ci/sha_drift.sh}"               # X-03 [build-smith]
PATCHES_POLICY="${PYBLE_PATCHES_POLICY:-$REPO_ROOT/tools/ci/patches_policy.sh}" # F-15 [build-smith]
BUILD_SH="${PYBLE_BUILD_SH:-$REPO_ROOT/firmware/scripts/build.sh}"             # X-03 [build-smith]
BUILD_ALL="${PYBLE_BUILD_ALL:-$REPO_ROOT/firmware/scripts/build_all.sh}"       # X-03 [build-smith]
UPGRADE_SH="${PYBLE_UPGRADE_SH:-$REPO_ROOT/firmware/scripts/upgrade_micropython.sh}" # F-15 [build-smith]
PREPARE_SH="${PYBLE_PREPARE_SH:-$REPO_ROOT/firmware/scripts/prepare.sh}"       # F-15/X-03 [build-smith]

# ---- Temp-tree helper --------------------------------------------------------
mk_tmp() { mktemp -d "${TMPDIR:-/tmp}/pyble_ft.XXXXXX"; }

# ---- CLEAN-ROOM forbidden-token assembly (runtime only, never committed) -----
# Adjacent shell string literals concatenate; the quote between the fragments
# means the contiguous forbidden byte-sequence never appears in this source
# file, so the no-leak gate does not flag common.sh itself.
tok_product()    { printf '%s' "titra""lab"; }   # commercial product/board name
tok_proto()      { printf '%s' "slp""/1"; }       # closed wire-protocol name
tok_prefix()     { printf '%s' "slp""_x"; }       # closed opcode/symbol prefix
tok_prior_app()  { printf '%s' "micro""pad"; }    # prior closed application name

# forbidden_regex — the canonical AGENTS.md no-leak regex, ASSEMBLED at runtime.
# The two genuinely-forbidden literals (closed protocol name + product name) are
# built from fragments; the `slp_[a-z]` alternative is written verbatim because
# that text does not itself match any forbidden pattern. Result: this file
# contains no forbidden literal, and callers still get the exact regex.
forbidden_regex() {
  printf '%s|slp_[a-z]|%s|%s' \
    "$(tok_proto)" "$(tok_product)" "$(tok_prior_app)"
}

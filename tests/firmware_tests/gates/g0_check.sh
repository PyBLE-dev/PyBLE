#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
#
# G0 exit-gate checklist (milestone M0 "Foundations").
# Enumerates the retained G0 foundation criteria and reports
# PASS / FAIL / DEFERRED(CI|HIL|TOOLCHAIN) for each.
#
# Rules (per 02_milestones.md): a milestone gate is green only on a real-hardware
# HIL demo, and gates are CUMULATIVE. This script verifies only the HOST-runnable
# slice; the 3-chip cross-compile and any HIL/CI-runtime evidence are reported as
# DEFERRED and MUST be closed on a toolchain machine / in CI before G0 is signed.
#
# Exit non-zero if any HOST-verifiable criterion FAILs (DEFERRED does not fail).

set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
FT="$(cd "$HERE/.." && pwd)"
. "$FT/lib/common.sh"

G0_FAIL=0

hdr() { printf '\n### %s\n' "$1"; }
row() { # STATUS  TEXT
  printf '  [%-9s] %s\n' "$1" "$2"
  case "$1" in FAIL) G0_FAIL=$((G0_FAIL+1));; esac
}

# run_test FILE -> echoes PASS/FAIL by running a host test file quietly.
run_test() {
  if bash "$FT/$1" >/dev/null 2>&1; then echo PASS; else echo FAIL; fi
}

printf '# PyBLE G0 (M0 Foundations) exit-gate checklist\n'
printf '# repo: %s\n' "$REPO_ROOT"

# --- Criterion 1: contributable repo + no-leak CI live ------------------------
hdr "G0.1 Contributable repo (MIT/CONTRIBUTING/DCO) + no-leak CI live  [X-01, X-02]"
row "$(run_test test_governance_files.sh)" "LICENSE/README/CONTRIBUTING/CoC present; DCO documented (git commit -s)"
row "$(run_test test_spdx_header.sh)"       "SPDX-MIT header lint enforced (tools/ci/spdx_lint.sh)"
row "$(run_test test_dco_signoff.sh)"       "DCO sign-off lint enforced (tools/ci/dco_check.sh)"
row "$(run_test test_no_leak.sh)"           "no-leak gate rejects forbidden tokens, passes clean tree (tools/ci/no_leak.sh)"
row "DEFERRED-CI" "no-leak + SPDX + DCO wired to run on every push/PR (.github/workflows) — verify in CI"

# --- Criterion 2: empty agent builds for all three chips from the pin ---------
hdr "G0.2 Empty agent builds for esp32 / -s3 / -c3 from versions.lock pin  [X-03, F-15]"
row "$(run_test test_build_matrix.sh)"      "build.sh target->IDF mapping + artifact plan + never-fake-build (host)"
row "DEFERRED-TOOLCHAIN" "actual 3-chip cross-compile emitting firmware.bin+bootloader+partition — toolchain machine"

# --- Criterion 3: SHA-drift gate refuses on mismatch, runs on every PR --------
hdr "G0.3 SHA-drift gate refuses on submodule mismatch + runs every PR  [X-03]"
row "$(run_test test_sha_drift.sh)"         "sha_drift refuses on mismatch/uninitialized, proceeds on match (host)"
row "DEFERRED-CI" "SHA-drift gate wired into the build workflow on every PR — verify in CI"

# --- Criterion 4: pristine pinned submodule, default zero patches -------------
hdr "G0.4 Pristine pinned submodule, default zero patches  [F-15]"
row "$(run_test test_submodule_idf.sh)"     ".gitmodules declares micropython; IDF gitignored not a submodule"
row "$(run_test test_patches_policy.sh)"    "zero-patch policy; patch without written reason refused"
row "$(run_test test_upgrade_workflow.sh)"  "upgrade bumps versions.lock in its own commit (dry-run)"
row "DEFERRED-TOOLCHAIN" "byte-pristine 150 MB submodule checkout verified — toolchain machine"

# --- Criterion 5: PBLE/1 §2 + §3 frozen --------------------------------------
hdr "G0.5 PBLE/1 transport (§2) + framing (§3) FROZEN  [spec prereq for F-01, F-02]"
PROTO="$REPO_ROOT/docs/specifications/protocol.md"
if grep -qiE '§2 BLE transport.*FROZEN' "$PROTO" 2>/dev/null; then row PASS "protocol.md §2 marked FROZEN for v1.0 (G0)"; else row FAIL "protocol.md §2 not marked FROZEN"; fi
if grep -qiE '§3 Framing.*FROZEN' "$PROTO" 2>/dev/null; then row PASS "protocol.md §3 marked FROZEN for v1.0 (G0)"; else row FAIL "protocol.md §3 not marked FROZEN"; fi

printf '\n----------------------------------------\n'
if [ "$G0_FAIL" -ne 0 ]; then
  printf 'G0: %d host-verifiable criteria FAILING — G0 NOT met (plus DEFERRED CI/HIL/toolchain items).\n' "$G0_FAIL"
  exit 1
fi
printf 'G0: all host-verifiable criteria PASS. Remaining DEFERRED items (3-chip build, CI wiring, HIL) MUST close before G0 sign-off.\n'
exit 0

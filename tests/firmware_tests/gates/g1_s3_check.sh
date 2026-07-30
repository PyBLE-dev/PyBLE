#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
#
# G1 exit-gate checklist — SPRINT S3 SLICE ("Identify and run").
# S3 belongs to milestone M1 / gate G1 (02_milestones.md: G1 spans S2–S6); it
# does NOT open a new milestone gate. This script advances the G1 ladder with
# the S3 stories: F-03 (HELLO/DEVICE_INFO/caps), F-16 (version+capability guard),
# F-22 (device label + advertised-name derivation), F-04 (RUN file + RUN_STATE).
#
# CUMULATIVE RULE (02_milestones.md / PRD §1B.7): a later gate is never green
# while an earlier one regressed. This script FIRST re-runs the G0 and the G1
# S2-slice host checks and REFUSES to sign any S3 item if either regressed.
#
# A milestone gate is green ONLY on a real-hardware HIL demo. This script
# verifies the HOST-runnable S3 conformance slice and reports the HIL items as
# DEFERRED-HIL. RED is EXPECTED now: the S3 pyble_* modules are not yet [green],
# AND the [red] S3 conformance suites are DoR-BLOCKED until protocol.md §6/§7/§9
# freeze + the specs.md FR mirror lands (see host/test_pyble_*.py banners and
# host/conformance/s3_pending.json). Do not sign S3 conformance before that.
#
# Exit non-zero if any cumulative earlier slice regressed, OR if a host-runnable
# S3 criterion FAILs. DEFERRED does not fail.

set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
FT="$(cd "$HERE/.." && pwd)"
. "$FT/lib/common.sh"

S3_FAIL=0
CUM_FAIL=0

hdr() { printf '\n### %s\n' "$1"; }
row() { # STATUS  TEXT
  printf '  [%-13s] %s\n' "$1" "$2"
  case "$1" in FAIL) S3_FAIL=$((S3_FAIL+1));; esac
}
crow() { # cumulative row: a FAIL here is a REGRESSION and blocks the gate
  printf '  [%-13s] %s\n' "$1" "$2"
  case "$1" in FAIL) CUM_FAIL=$((CUM_FAIL+1));; esac
}
note() { printf '  %s %s\n' '..' "$1"; }
run_test() { if bash "$FT/$1" >/dev/null 2>&1; then echo PASS; else echo FAIL; fi; }

printf '# PyBLE G1 (M1) exit-gate checklist — S3 SLICE (Identify and run)\n'
printf '# repo: %s\n' "$REPO_ROOT"

# --- Cumulative guard: G0 + G1 S2 slice must still hold ----------------------
hdr "G1.S3.0 CUMULATIVE — G0 and the G1 S2 slice must not regress"
if bash "$FT/gates/g0_check.sh" >/dev/null 2>&1; then
  crow PASS "G0 host slice still green"
else
  crow FAIL "G0 host slice REGRESSED — cannot sign any S3 item while G0 is red"
fi
if bash "$FT/gates/g1_check.sh" >/dev/null 2>&1; then
  crow PASS "G1 S2 slice (pyble_proto codec/CRC/frag/dispatch, pyble_ble pure helpers) still green"
else
  crow FAIL "G1 S2 slice REGRESSED — cannot sign S3 while the S2 slice is red"
fi

# --- Spec-freeze precondition (SDD): §6/§7/§9 must be FROZEN before S3 [green]
hdr "G1.S3.1 SDD precondition — protocol.md §6/§7/§9 FROZEN before S3 conformance"
PROTO="$REPO_ROOT/docs/specifications/protocol.md"
chk_frozen() { # SECTION_REGEX  LABEL
  if grep -qiE "$1.*FROZEN" "$PROTO" 2>/dev/null; then row PASS "$2"; else row DEFERRED-DOCS "$2 (still DRAFT — architect/project-architect [docs] freeze)"; fi
}
chk_frozen '§6 Run'        "protocol.md §6 (Run/Console) FROZEN — DoR for F-04 [red]"
chk_frozen '§7 HELLO'      "protocol.md §7 (HELLO/caps) FROZEN — DoR for F-03/F-16/F-22 [red]"
chk_frozen '§9 Version'    "protocol.md §9 (Versioning) FROZEN — DoR for F-16 [red]"

# --- S3 host conformance slice (RED-EXPECTED until [green]) -------------------
hdr "G1.S3.2 F-03 HELLO/DEVICE_INFO/caps conformance  [pyble_info — identity-engineer]"
row "$(run_test test_pyble_info.sh)" "caps field set complete+typed; INFO read == DEVICE_INFO; version negotiate/refuse (FR-INFO-1..5, FR-PROTO-10)"

hdr "G1.S3.3 F-16 version + capability guard conformance  [pyble_proto — protocol-engineer]"
row "$(run_test test_pyble_proto_version_guard.sh)" "accept only VER 0x01; EUNSUPPORTED for unknown opcode (FR-PROTO-7/9)"

hdr "G1.S3.4 F-22 device label + advertised-name conformance  [pyble_device_config — identity-engineer]"
row "$(run_test test_pyble_device_config.sh)" "default PyBLE-XXXX; label replaces/clears; over-length ERANGE; 24B bound; identity never gates access (FR-BLE-5/12, FR-IDENT-1, SEC-10/11)"

hdr "G1.S3.5 F-04 RUN file + RUN_STATE + EBUSY conformance  [pyble_runner — runtime-engineer]"
row "$(run_test test_pyble_runner.sh)" "run->running->done/error state machine; RUN_STATE per transition; single-program EBUSY (FR-RUN-1/4/7/9)"

note "the four rows above are RED until [green]; they are also DoR-BLOCKED until §6/§7/§9 freeze — see the file banners"

# --- Shared cross-language corpus (firmware <-> Dart pble) --------------------
hdr "G1.S3.6 Shared PBLE/1 corpus advanced for S3 (frozen frame-level only)"
row "$(run_test test_pyble_proto.sh)" "corpus.json still byte-verifies incl. run_rsp_*/set_label_rsp_* frozen frame vectors"
note "payload-semantic S3 vectors (caps/RUN/SET_LABEL body) held in conformance/s3_pending.json until §6/§7/§9 freeze"

# --- No-leak (cumulative clean-room gate) ------------------------------------
hdr "G1.S3.7 Clean-room no-leak still clean over the test tree  [F-22 gate carries no-leak]"
if grep -rniE "$(forbidden_regex)" "$FT" --include='*.py' --include='*.sh' --include='*.json' >/dev/null 2>&1; then
  row FAIL "no-leak: forbidden token found in tests/firmware_tests"
else
  row PASS "no-leak: tests/firmware_tests free of forbidden proprietary tokens"
fi

# --- S3 HIL demo items (real esp32 / -s3 / -c3) ------------------------------
hdr "G1.S3.8 S3 behaviours on real hardware  [HIL — the truth for the gate]"
row "DEFERRED-HIL" "F-03: from a test client, read the INFO characteristic BEFORE subscribing; value == DEVICE_INFO (FR-INFO-4)"
row "DEFERRED-HIL" "F-03/F-16: HELLO is the FIRST exchange; version+caps negotiated; agent refuses an unsatisfiable-version client (FR-INFO-2/5)"
row "DEFERRED-HIL" "F-22: SET_LABEL persists across reboot; scan list shows the LABEL, then PyBLE-XXXX after an empty clear (FR-BLE-12, FR-IDENT-1)"
row "DEFERRED-HIL" "F-22: identity is display-only — a command runs identically whether or not a label is set (SEC-11/CON-7)"
row "DEFERRED-HIL" "F-04: RUN file executes on a task SEPARATE from the NimBLE host task; the BLE link stays responsive during a run (FR-RUN-3, NFR-SAFE-2)"
row "DEFERRED-HIL" "F-04: RUN_STATE(running) then (done); a crashing script yields (error); a second RUN while running -> EBUSY (FR-RUN-1/4/7/9)"

printf '\n----------------------------------------\n'
if [ "$CUM_FAIL" -ne 0 ]; then
  printf 'G1 S3 slice: CUMULATIVE REGRESSION (%d) — an earlier gate is red; S3 CANNOT be signed (PRD §1B.7).\n' "$CUM_FAIL"
  exit 1
fi
if [ "$S3_FAIL" -ne 0 ]; then
  printf 'G1 S3 slice: %d host criteria FAILING — EXPECTED RED until the S3 pyble_* modules land [green] (and only after §6/§7/§9 freeze). Plus DEFERRED-HIL items. G1 NOT advanced.\n' "$S3_FAIL"
  exit 1
fi
printf 'G1 S3 slice: host-runnable S3 criteria PASS. G1 still requires the DEFERRED-HIL demo before sign-off, and remains open through S6.\n'
exit 0

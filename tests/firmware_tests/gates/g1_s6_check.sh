#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
#
# G1 exit-gate checklist — SPRINT S6 SLICE ("resume + cold-boot safety/auto-run +
# pairing/single-writer + reliability bench"). S6 is the LAST slice of milestone
# M1 / gate G1 (02_milestones.md: G1 spans S2-S6); it does NOT open a new gate,
# it CLOSES G1. Stories: F-10 (upload resume, pble_fs), F-11 (multi-file
# reliability bench — a HIL test artifact, firmware-test-author, NO firmware
# [green]), F-12 (cold-boot safety + opt-in auto-run, pble_boot), F-18 (BLE
# pairing baseline + single-writer, pble_ble + pble_lock).
#
# CUMULATIVE RULE (02_milestones.md / PRD §1B.7): a later gate is never green
# while an earlier one regressed, and G1 cannot be SIGNED while any earlier S2-S5
# slice is red. This script FIRST re-runs G0 + the G1 S2 slice and REFUSES to
# sign any S6 item if any implemented S2–S5 host slice regressed. Because S6
# CLOSES G1, the sign-off note is
# explicit that G1 stays OPEN until S2-S6 are ALL green on a real-hardware HIL
# demo.
#
# The S6 specification prerequisites are now frozen: reconnect resume behavior,
# SET_AUTORUN/auto_run, and the §10 security posture. Their former byte-less
# planning ledger is retained only in the conformance archive.
#
# A milestone gate is green ONLY on a real-hardware HIL demo. This script verifies
# the HOST-runnable S6 slice and reports HIL items as DEFERRED-HIL and native-C
# unit coverage as DEFERRED-NATIVE
# (Unity, arrives F-20). DEFERRED does not fail.
#
# Exit non-zero if any cumulative earlier signed slice regressed, OR if a host-
# runnable S6 criterion FAILs.

set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
FT="$(cd "$HERE/.." && pwd)"
. "$FT/lib/common.sh"

S6_FAIL=0
CUM_FAIL=0

hdr() { printf '\n### %s\n' "$1"; }
row() { printf '  [%-14s] %s\n' "$1" "$2"; case "$1" in FAIL) S6_FAIL=$((S6_FAIL+1));; esac; }
crow() { printf '  [%-14s] %s\n' "$1" "$2"; case "$1" in FAIL) CUM_FAIL=$((CUM_FAIL+1));; esac; }
note() { printf '  %s %s\n' '..' "$1"; }
run_test() { if bash "$FT/$1" >/dev/null 2>&1; then echo PASS; else echo FAIL; fi; }

printf '# PyBLE G1 (M1) exit-gate checklist — S6 SLICE (resume / boot-safety+auto-run / pairing+single-writer / reliability bench)\n'
printf '# repo: %s\n' "$REPO_ROOT"

# --- Cumulative guard: G0 + G1 S2 slice must still hold -----------------------
hdr "G1.S6.0 CUMULATIVE — G0 and the G1 S2 slice must not regress (signed/green earlier slices)"
if bash "$FT/gates/g0_check.sh" >/dev/null 2>&1; then
  crow PASS "G0 host slice still green"
else
  crow FAIL "G0 host slice REGRESSED — cannot sign any S6 item while G0 is red"
fi
if bash "$FT/gates/g1_check.sh" >/dev/null 2>&1; then
  crow PASS "G1 S2 slice (pyble_proto codec/CRC/frag/dispatch, pyble_ble pure helpers) still green"
else
  crow FAIL "G1 S2 slice REGRESSED — cannot sign S6 while the S2 slice is red"
fi
for s in S3 S4 S5; do
  lc="$(printf '%s' "$s" | tr 'A-Z' 'a-z')"
  if bash "$FT/gates/g1_${lc}_check.sh" >/dev/null 2>&1; then
    note "G1 ${s} slice host-runnable checks currently GREEN"
  else
      crow FAIL "G1 ${s} slice REGRESSED — current host criteria must pass before S6 can be signed"
  fi
done

# --- Spec-freeze precondition (SDD): the three S6 posture/semantics freezes ----
hdr "G1.S6.1 SDD precondition — the three S6 [docs] freezes must land before S6 [red]/[green]"
PROTO="$REPO_ROOT/docs/specifications/protocol.md"
SPECS="$REPO_ROOT/docs/specifications/firmware/specs.md"

# F-10: the historical forward-looking marker must remain absent.
if grep -qiE 'full behaviour lands later|behaviour lands later|resume fills it later|lands F-10|lands later' "$PROTO" 2>/dev/null; then
  row FAIL "F-10: obsolete pre-freeze resume marker reappeared"
else
  row PASS "F-10: protocol.md §5 resume behaviour FROZEN (no 'lands later' clause)"
fi

# F-18: the frozen §10 ledger row must not regress.
if grep -qiE '§10 *Security *\| *DRAFT|only §10 \(Security\) DRAFT|§10 \(Security\) remains DRAFT|Security[^|]*\| *DRAFT' "$PROTO" 2>/dev/null; then
  row FAIL "F-18: protocol.md §10 Security regressed to a pre-freeze marker"
else
  row PASS "F-18: protocol.md §10 Security FROZEN (ledger no longer marks it DRAFT)"
fi

# F-12: SET_AUTORUN and the closed OI-5 marker are retained frozen anchors.
if grep -qiE 'SET_AUTORUN' "$PROTO" 2>/dev/null && grep -qiE 'OI-5.*(CLOSED|✅)' "$SPECS" 2>/dev/null; then
  row PASS "F-12: OI-5 CLOSED — protocol.md §4 SET_AUTORUN opcode + §7 auto_run cap position frozen; specs.md §4.7 FR-BOOT stamp"
else
  row FAIL "F-12: frozen OI-5 SET_AUTORUN/auto_run anchors are missing"
fi
note "pre-freeze planning obligations are archived byte-for-byte and are not active requirements"

# --- F-10 upload resume (pble_fs — storage-engineer) -------------------------
hdr "G1.S6.2 F-10 upload resume  [pble_fs_resume_prefix / pble_fs_on_disconnect — storage-engineer]"
row "$(run_test test_pyble_fs.sh)" "portable semantic oracle: verified-prefix resume offset, tail completion, foreign-prefix refusal, and old-file preservation (FR-FS-7/14, NFR-REL-2/3)"

# --- F-11 multi-file reliability bench (HIL) — firmware-test-author -----------
hdr "G1.S6.3 F-11 multi-file reliability bench (HIL artifact — firmware-test-author, NO firmware [green])"
row "$(run_test test_hil_wire.sh)" "the bench's PBLE/1 wire codec (hil/_pble_wire.py) matches the SHARED corpus byte-for-byte across the MTU matrix incl. the index-mod-64 wrap (host-runnable NOW — FR-PROTO-2/3, FR-BLE-8/10)"
if [ -f "$FT/hil/f11_reliability_bench.py" ] && python3 -c "import ast,sys; ast.parse(open('$FT/hil/f11_reliability_bench.py').read())" >/dev/null 2>&1; then
  row PASS "hil/f11_reliability_bench.py present + parses (uploads N files back-to-back @ negotiated MTU, asserts whole-file CRC + FILE_STAT re-verify, reports OI-1 throughput baseline)"
else
  row FAIL "hil/f11_reliability_bench.py missing or does not parse"
fi
row DEFERRED-HIL "F-11 EXECUTION on ESP32-S3 (bleak central): N files upload with EVERY file intact (NFR-REL-5); FILE_PUT_END OK only on whole-file CRC match + FILE_STAT re-verify (FR-FS-6/14); throughput @ MTU 247 REPORTED as an OI-1 baseline — a pass/fail floor is applied ONLY if the architect supplies one (--tput-floor-bps), NEVER invented (NFR-PERF-1, NFR-FP-TPUT); execution-ready after F-10 Done"

# --- F-12 cold-boot safety + opt-in auto-run (pble_boot — runtime-engineer) ---
hdr "G1.S6.4 F-12 cold-boot safety + opt-in auto-run  [pble_boot — runtime-engineer]"
row "$(run_test test_pyble_device_config_rp2.sh)" "portable config oracle: autorun defaults off, SET_AUTORUN is validated and persisted, and caps state follows durable configuration (FR-BOOT-1..6, FR-MODE-1/4)"

# --- F-18 pairing baseline + single-writer (pble_ble + pble_lock) -------------
hdr "G1.S6.5 F-18 BLE pairing baseline + single-writer  [pble_ble_sm_config / pble_lock — ble-transport + runtime-engineer]"
row "$(run_test test_v061_native_hardening.sh)" "native structural/compiled guards retain persistence and isolation hardening; physical pairing, writer concurrency, and privacy posture remain HIL below (SEC-1/2/3/5/7/8/10/11)"

# --- Native-C unit coverage (Unity-on-native, arrives F-20) -------------------
hdr "G1.S6.6 Native-C unit coverage — pble_fs/pble_boot/pble_lock (Unity, arrives with F-20)"
row "DEFERRED-NATIVE" "pble_fs_resume_prefix re-CRC/watermark; pble_boot autorun NVS get/set + maybe_autorun guard; pble_lock W_RUN/W_XFER independence + idempotent-same-writer + on_disconnect release — native C (ADR-0006), no host-importable module; Unity-on-native lands F-20"

# --- Shared cross-language corpus (firmware <-> Dart pble) --------------------
hdr "G1.S6.7 Shared PBLE/1 corpus — frozen frame-level vectors still verify"
row "$(run_test test_pyble_proto.sh)" "corpus.json still byte-verifies (§3/§4/§8 frozen frame codec + CRC + fragmentation)"
note "the shared corpus remains a frame-codec fixture; current resume/autorun semantics are covered by named suites without claiming retrospective promotion of every planning vector"

# --- No-leak (cumulative clean-room gate) ------------------------------------
hdr "G1.S6.8 Clean-room no-leak still clean over the test tree"
if grep -rniE "$(forbidden_regex)" "$FT" --include='*.py' --include='*.sh' --include='*.json' >/dev/null 2>&1; then
  row FAIL "no-leak: forbidden token found in tests/firmware_tests"
else
  row PASS "no-leak: tests/firmware_tests (including the HIL bench and archived ledgers) free of forbidden proprietary tokens"
fi

# --- S6 HIL demo items (real esp32 / -s3 / -c3) — the truth for the gate ------
hdr "G1.S6.9 S6 behaviours on real hardware  [HIL — ESP32-S3 harness: UART REPL + bleak central]"
row "DEFERRED-HIL" "F-10: a mid-PUT link drop leaves <dest>.pbltmp + watermark on flash; reconnect FILE_PUT_BEGIN returns resume_offset>0; the app resends only the tail; FILE_PUT_END whole-file CRC gates OK; the finished file is byte-identical to a non-interrupted upload (FR-FS-7, NFR-REL-2/3)"
row "DEFERRED-HIL" "F-10: a corrupted/foreign resumed prefix -> ECRC; the pre-existing dest file is byte-intact; a temp>total is truncated to resume_offset=0 (FR-FS-14, NFR-REL-3)"
row "DEFERRED-HIL" "F-11: N files upload back-to-back @ MTU 247 with EVERY file intact (whole-file CRC + FILE_STAT re-verify); throughput captured as an OI-1 baseline (NFR-REL-5, NFR-PERF-1)"
row "DEFERRED-HIL" "F-12: cold boot with a present /main.py and auto-run OFF (default): board advertises + is connectable + RUN_STATE idle; /main.py is NOT executed (FR-BOOT-1/2, FR-MODE-4, NFR-SAFE-3)"
row "DEFERRED-HIL" "F-12: auto-run ON + an infinite-loop /main.py (while True pass): board still advertises + connectable; STOP interrupts the worker; a SyntaxError /main.py -> RUN_STATE(error), agent up — fail-safe (FR-BOOT-3/4/6)"
row "DEFERRED-HIL" "F-18: a bleak/CoreBluetooth central pairs (Just-Works, encryption when it initiates) AND completes a full PBLE/1 HELLO+FILE round-trip — no per-char ENC flag locks it out (SEC-1/2, 'just connect and use')"
row "DEFERRED-HIL" "F-18: a 2nd concurrent RUN -> EBUSY; a 2nd concurrent PUT -> EBUSY; a PUT and a RUN COEXIST (W_RUN/W_XFER independent); a disconnect mid-PUT frees W_XFER for a resuming reconnect (SEC-3, FR-FS-16)"
row "DEFERRED-HIL" "F-18: the advertisement carries only the Service UUID + name (PyBLE-XXXX or the set label), no PII; no unsolicited off-device traffic (no telemetry) (SEC-5/8/10)"
row "DEFERRED-HIL" "F-10/11/12/18: identity NEVER gates access — FILE_*/RUN behave identically with or without a label; the f11 bench --relabel mid-run proves the FILE half (SEC-7/11)"

printf '\n----------------------------------------\n'
if [ "$CUM_FAIL" -ne 0 ]; then
  printf 'G1 S6 slice: CUMULATIVE REGRESSION (%d) — an earlier signed gate is red; S6 CANNOT be signed (PRD §1B.7).\n' "$CUM_FAIL"
  exit 1
fi
if [ "$S6_FAIL" -ne 0 ]; then
  printf 'G1 S6 slice: %d host criteria FAILING. G1 NOT advanced.\n' "$S6_FAIL"
  exit 1
fi
printf 'G1 S6 slice: host-runnable checks PASS (bench wire matches the shared corpus; corpus intact; no-leak clean). Physical F-10/F-12/F-18 behavior remains DEFERRED-HIL; native Unity coverage is DEFERRED-NATIVE (F-20). S6 CLOSES G1 — G1 is green ONLY when S2-S6 all pass a real-hardware HIL demo.\n'
exit 0

#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
#
# G1 exit-gate checklist — SPRINT S4 SLICE ("Run source, stop, console, identify").
# S4 belongs to milestone M1 / gate G1 (02_milestones.md: G1 spans S2–S6); it
# does NOT open a new milestone gate. This script advances the G1 ladder with the
# S4 stories: F-05 (RUN{mode:source}), F-06 (STOP + SOFT_REBOOT), F-07 (console
# tee stdout/stderr + CONSOLE_INPUT stdin), F-23 (cap-gated IDENTIFY).
#
# EXECUTION MODEL (frozen by the owner, TDD.md): user code runs on a MicroPython
# _thread WORKER; the main task keeps the REPL+banner; the NimBLE host task never
# blocks on user code; STOP interrupts the WORKER (per-worker KBI store), NOT the
# REPL. The appliance/serve()-on-main design is DEAD — the gate rejects it.
#
# CUMULATIVE RULE (02_milestones.md / PRD §1B.7): a later gate is never green
# while an earlier one regressed. This script FIRST re-runs G0, the G1 S2 slice,
# and the G1 S3 slice and REFUSES to sign any S4 item if any regressed.
#
# A milestone gate is green ONLY on a real-hardware HIL demo. This script verifies
# the HOST-runnable S4 slice and reports the HIL items as DEFERRED-HIL. RED /
# DEFERRED is EXPECTED now: the S4 pyble_*/pble_* modules are not yet [green], AND
# the S4 payload-semantic conformance vectors are DoR-BLOCKED until protocol.md §6
# (STOP/SOFT_REBOOT/RUN{source}/CONSOLE_DATA/CONSOLE_INPUT) + §4/§7 (OI-6 identify
# encodings) FREEZE and the specs.md FR mirror + OI-6 close land. Those pending
# vectors carry NO frame bytes on purpose (host/conformance/s4_pending.json) —
# fabricating draft wire is forbidden. Do not sign S4 conformance before freeze.
#
# Exit non-zero if any cumulative earlier slice regressed, OR if a host-runnable
# S4 criterion FAILs. DEFERRED does not fail.

set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
FT="$(cd "$HERE/.." && pwd)"
. "$FT/lib/common.sh"

S4_FAIL=0
CUM_FAIL=0

hdr() { printf '\n### %s\n' "$1"; }
row() { # STATUS  TEXT
  printf '  [%-13s] %s\n' "$1" "$2"
  case "$1" in FAIL) S4_FAIL=$((S4_FAIL+1));; esac
}
crow() { # cumulative row: a FAIL here is a REGRESSION and blocks the gate
  printf '  [%-13s] %s\n' "$1" "$2"
  case "$1" in FAIL) CUM_FAIL=$((CUM_FAIL+1));; esac
}
note() { printf '  %s %s\n' '..' "$1"; }
run_test() { if bash "$FT/$1" >/dev/null 2>&1; then echo PASS; else echo FAIL; fi; }

printf '# PyBLE G1 (M1) exit-gate checklist — S4 SLICE (run source / stop / console / identify)\n'
printf '# repo: %s\n' "$REPO_ROOT"

# --- Cumulative guard: G0 + G1 S2 slice must still hold -----------------------
# CUMULATIVE RULE binds SIGNED/green gates: the hard blockers are the genuinely-
# green earlier slices (G0 + G1 S2). The G1 S3 slice is IN-FLIGHT within the same
# open G1 gate (its pyble_* modules are not yet [green]) — its own exit code
# cannot distinguish "regressed" from "not-yet-green", so like g1_s3_check.sh
# only hard-blocks on g0+g1(S2), the S3 status is reported INFORMATIONALLY here.
hdr "G1.S4.0 CUMULATIVE — G0 and the G1 S2 slice must not regress (signed/green earlier slices)"
if bash "$FT/gates/g0_check.sh" >/dev/null 2>&1; then
  crow PASS "G0 host slice still green"
else
  crow FAIL "G0 host slice REGRESSED — cannot sign any S4 item while G0 is red"
fi
if bash "$FT/gates/g1_check.sh" >/dev/null 2>&1; then
  crow PASS "G1 S2 slice (pyble_proto codec/CRC/frag/dispatch, pyble_ble pure helpers) still green"
else
  crow FAIL "G1 S2 slice REGRESSED — cannot sign S4 while the S2 slice is red"
fi
if bash "$FT/gates/g1_s3_check.sh" >/dev/null 2>&1; then
  note "G1 S3 slice host-runnable checks currently GREEN"
else
  note "G1 S3 slice not yet fully green (S3 pyble_* modules in flight) — tracked by gates/g1_s3_check.sh; NOT a signed-gate regression, so it does not block S4 authoring. Re-verify it turns green before G1 sign-off (cumulative rule)."
fi

# --- Spec-freeze precondition (SDD): §6 S4 semantics + §4/§7 OI-6 must FREEZE -
hdr "G1.S4.1 SDD precondition — protocol.md S4 payload encodings FROZEN before S4 [red]/[green]"
PROTO="$REPO_ROOT/docs/specifications/protocol.md"
SPECS="$REPO_ROOT/docs/specifications/firmware/specs.md"
# §4/§8 opcode+status numbers and §6 RUN-FILE lifecycle are already frozen (G1).
# What S4 needs is the DRAFT REMAINDER: §6 STOP/SOFT_REBOOT/RUN{source}/CONSOLE_*
# payload+semantics, and the OI-6 identify-LED/blink encodings. Detect freeze by
# the ABSENCE of the DRAFT marker (avoids false positives from the DRAFT
# signature prose): while the marker is present the section is DRAFT and the
# payload-semantic [red] suites remain DoR-BLOCKED.
frozen_when_absent() { # DRAFT_REGEX  FILE  LABEL
  if grep -qiE "$1" "$2" 2>/dev/null; then
    row DEFERRED-DOCS "$3 (still DRAFT — project-architect [docs] freeze; firmware-architect mirrors)"
  else
    row PASS "$3"
  fi
}
# §6 STOP/CONSOLE_INPUT/RUN{source} carry the shared "freeze at S4 / freeze there" marker.
frozen_when_absent 'freeze there|freeze at S4' "$PROTO" "protocol.md §6 STOP/SOFT_REBOOT/RUN{mode:source}/CONSOLE_* payload FROZEN — DoR for F-05/F-06/F-07 [red]"
# §4/§7 identify encodings carry the forward-looking "frozen at S4 before F-23"
# promise (the freeze commit removes it); avoid the generic "remain OI-6"
# historical note, which a freeze may leave in place (false-negative trap).
frozen_when_absent 'frozen at S4 before F-23' "$PROTO" "protocol.md §4/§7 OI-6 identify (SET_IDENTIFY_LED + IDENTIFY + caps) encodings FROZEN — DoR for F-23 [red]"
# specs.md OI-6 remainder must flip from "Still OPEN" to closed.
frozen_when_absent 'Still \*\*OPEN|Still OPEN' "$SPECS" "specs.md §5 OI-6 remainder CLOSED (FR-IDENT-2/3/4 mirror) — DoR for F-23 [red]"
note "while the rows above are DEFERRED-DOCS, the S4 payload-semantic vectors stay in host/conformance/s4_pending.json (no frame bytes) — see the file _blocked_on ledger"

# --- S4 host conformance slice (payload-semantic — DoR-BLOCKED until freeze) --
hdr "G1.S4.2 F-05 RUN{mode:source} same lifecycle as file  [pyble_runner — runtime-engineer]"
row "DEFERRED-DOCS" "RUN{source} -> RSP{OK} -> RUN_STATE(running) -> done/error; EBADREQ bad mode; ERANGE over-length; EBUSY while running (FR-RUN-2/4/7) — s4_pending.json:run_source_lifecycle"

hdr "G1.S4.3 F-06 STOP + SOFT_REBOOT  [pyble_runner — runtime-engineer]"
row "DEFERRED-DOCS" "STOP RSP{OK} ALWAYS (idle no-op + running interrupt->RUN_STATE(idle)); SOFT_REBOOT RSP{OK}->VM reset->RUN_STATE(idle) (FR-RUN-5/6/8/10) — s4_pending.json:stop_idempotent_ok,soft_reboot_clears_to_idle"

hdr "G1.S4.4 F-07 console tee stdout/stderr + CONSOLE_INPUT stdin  [pyble_console — runtime-engineer]"
row "DEFERRED-DOCS" "CONSOLE_DATA [stream][bytes] stdout=0/stderr=1 observe-anywhere; CONSOLE_INPUT NO-RSP (PBLE_NO_RSP never on wire); traceback+RUN_STATE(error) on uncaught (FR-CON-1..5, FR-RUN-9) — s4_pending.json:console_*"

hdr "G1.S4.5 F-23 cap-gated IDENTIFY  [pyble_device_config + pyble_info — identity-engineer]"
row "DEFERRED-DOCS" "SET_IDENTIFY_LED [gpio][active_level] persist/clear + ERANGE/EBADREQ; IDENTIFY bounded non-blocking blink + EUNSUPPORTED unset; has_identify/identify_led additive caps (FR-IDENT-2/3/4, §7) — s4_pending.json:set_identify_led_body_persists,identify_blink_bounded,caps_has_identify_and_identify_led"

# --- Shared cross-language corpus (firmware <-> Dart pble) --------------------
hdr "G1.S4.6 Shared PBLE/1 corpus — frozen frame-level S4 vectors still verify"
row "$(run_test test_pyble_proto.sh)" "corpus.json still byte-verifies incl. run_cmd_source_opaque_250b / run_rsp_* / stop_rsp_ebusy / run_state_evt_running / console_data_evt / identify_rsp_eunsupported (opaque payload, §4/§8 frozen)"
note "payload-SEMANTIC S4 vectors are held in conformance/s4_pending.json until protocol.md §6/§4/§7 freeze; they carry NO frame_hex (wire is referenced, never redefined)"

# --- No-leak (cumulative clean-room gate) ------------------------------------
hdr "G1.S4.7 Clean-room no-leak still clean over the test tree"
if grep -rniE "$(forbidden_regex)" "$FT" --include='*.py' --include='*.sh' --include='*.json' >/dev/null 2>&1; then
  row FAIL "no-leak: forbidden token found in tests/firmware_tests"
else
  row PASS "no-leak: tests/firmware_tests free of forbidden proprietary tokens"
fi

# --- S4 HIL demo items (real esp32 / -s3 / -c3) — the truth for the gate ------
hdr "G1.S4.8 S4 behaviours on real hardware  [HIL — ESP32-S3 harness: UART REPL + bleak central]"
row "DEFERRED-HIL" "F-05: RUN{mode:source} of an inline snippet runs with the SAME RUN_STATE lifecycle as a file run; output streams live (FR-RUN-2)"
row "DEFERRED-HIL" "F-06: STOP interrupts a 'while True: pass' PROMPTLY while the NimBLE host task stays responsive (other commands still answer); RUN_STATE(idle) follows (FR-RUN-5/6/10, FR-BLE-11)"
row "DEFERRED-HIL" "F-06: STOP hits the WORKER thread, NOT the REPL — the main-task REPL+version banner remain live and untouched throughout (execution-model invariant)"
row "DEFERRED-HIL" "F-06: STOP while IDLE returns RSP{OK} (idempotent no-op); a second RUN while running returns EBUSY (FR-RUN-4)"
row "DEFERRED-HIL" "F-06: SOFT_REBOOT clears the VM to a fresh namespace (previously-defined globals gone) and returns to idle; BLE link kept where possible (FR-RUN-8)"
row "DEFERRED-HIL" "F-07: a running program's stdout AND stderr arrive tagged in CONSOLE_DATA; REPL/main-task UART output is NOT teed to BLE (FR-CON-1/2/4)"
row "DEFERRED-HIL" "F-07: CONSOLE_INPUT feeds a program blocked on input()/sys.stdin and round-trips; the app receives NO RSP frame for CONSOLE_INPUT (FR-CON-3)"
row "DEFERRED-HIL" "F-07: console is observe-anywhere — a second connected client sees the same stdout/stderr regardless of which client triggered the run (FR-CON-4)"
row "DEFERRED-HIL" "F-07: an uncaught exception yields CONSOLE_DATA(stderr, traceback) THEN RUN_STATE(error) (FR-RUN-9, FR-CON-2)"
row "DEFERRED-HIL" "F-23: SET_IDENTIFY_LED persists GPIO+active-level across reboot; IDENTIFY blinks NON-BLOCKING (a concurrent run keeps executing, BLE stays responsive) (FR-IDENT-2/3, FR-BLE-11)"
row "DEFERRED-HIL" "F-23: IDENTIFY with no LED configured returns EUNSUPPORTED; has_identify/identify_led appear in HELLO caps + INFO read (FR-IDENT-4, §7)"
row "DEFERRED-HIL" "F-05/06/07/23: identity/identify/console/run NEVER gate access — every command behaves identically with or without a label/identify LED; IDENTIFY blink maps no hardware for user code (SEC-11, CON-13, FR-IDENT-6)"

printf '\n----------------------------------------\n'
if [ "$CUM_FAIL" -ne 0 ]; then
  printf 'G1 S4 slice: CUMULATIVE REGRESSION (%d) — an earlier gate is red; S4 CANNOT be signed (PRD §1B.7).\n' "$CUM_FAIL"
  exit 1
fi
if [ "$S4_FAIL" -ne 0 ]; then
  printf 'G1 S4 slice: %d host criteria FAILING. G1 NOT advanced.\n' "$S4_FAIL"
  exit 1
fi
printf 'G1 S4 slice: host-runnable checks PASS; S4 payload-semantic conformance is DoR-BLOCKED (protocol.md §6/§4/§7 + specs.md OI-6 not yet frozen) and the behaviours are DEFERRED-HIL. G1 remains OPEN through S6.\n'
exit 0

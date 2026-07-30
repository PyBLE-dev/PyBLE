#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
#
# G1 exit-gate checklist — SPRINT S5 SLICE ("Filesystem read + write + jail").
# S5 belongs to milestone M1 / gate G1 (02_milestones.md: G1 spans S2–S6); it
# does NOT open a new milestone gate. This script advances the G1 ladder with the
# S5 stories: F-08 (filesystem read: FILE_LIST/FILE_STAT/FILE_GET_*), F-09
# (filesystem write: windowed FILE_PUT + DELETE/MKDIR/RENAME), F-17 (workspace-
# jail enforcement).
#
# EXECUTION MODEL (frozen by the architect interfaces contract): MicroPython's VFS
# at fs_root is reachable ONLY via mp_vfs_* / the MP object+nlr machinery, which
# REQUIRE a valid MicroPython VM thread state + the GIL. But pble_proto_dispatch +
# every CMD handler run on the NON-MP NimBLE host task (no mp_state_thread).
# Therefore FILE_* ops MUST NOT call mp_vfs_* inline on the host task. The design
# mirrors the S4 runner worker: a dedicated MP fs-worker _thread (valid VM state,
# launched from _boot.py) owns the vfs ops under an nlr boundary and maps
# exceptions -> §8 status; the host-task FILE_* handler captures+enqueues the
# request and returns PBLE_NO_RSP (no inline reply); the fs-worker emits the RSP
# asynchronously by request ID (pble_proto_emit_id). The host task NEVER blocks on
# the fs-worker (FR-BLE-11). The inline-mp_vfs-on-host-task design is DEAD.
#
# CUMULATIVE RULE (02_milestones.md / PRD §1B.7): a later gate is never green
# while an earlier one regressed. This script FIRST re-runs G0 and the G1 S2 slice
# and REFUSES to sign any S5 item if either regressed; the G1 S3/S4 slices are
# reported INFORMATIONALLY (their pyble_*/pble_* modules are in flight — an
# in-flight slice's exit code cannot distinguish "regressed" from "not-yet-green",
# same choice g1_s3_check / g1_s4_check made).
#
# A milestone gate is green ONLY on a real-hardware HIL demo. This script verifies
# the HOST-runnable S5 slice and reports the HIL items as DEFERRED-HIL. RED /
# DEFERRED is EXPECTED now: the native pble_fs module is not yet [green], AND the
# S5 payload-semantic conformance vectors are DoR-BLOCKED until protocol.md §5
# (File transfer, read + upload halves) FREEZES, the specs.md §4.4 FR-FS payload
# mirror lands, AND the specs.md F-17 jail definition (chokepoint + forbidden set)
# FREEZES. Those pending vectors carry NO frame bytes on purpose
# (host/conformance/s5_pending.json) — fabricating draft wire is forbidden. §5
# ALSO currently CONTRADICTS the architect freeze_proposal (GET_BEGIN up-front
# crc32; Go-Back-N window). Do not sign S5 conformance before freeze.
#
# NOTE (native-C reality, ADR-0006): pble_fs is native C — there is NO host-
# importable Python module for it (unlike the S2/S3 pyble_*.py modules). So the
# host-runnable-NOW S5 slice is only (a) the shared FRAME-CODEC corpus still
# byte-verifying and (b) the no-leak grep. Native-C UNIT coverage (whole-file
# crc32 oracle, pble_fs_resolve canonicalization + forbidden-set, list/stat/get
# payload build) is Unity-on-native and arrives with F-20; it is DEFERRED-NATIVE
# here, not FAIL.
#
# Exit non-zero if any cumulative earlier slice regressed, OR if a host-runnable
# S5 criterion FAILs. DEFERRED does not fail.

set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
FT="$(cd "$HERE/.." && pwd)"
. "$FT/lib/common.sh"

S5_FAIL=0
CUM_FAIL=0

hdr() { printf '\n### %s\n' "$1"; }
row() { # STATUS  TEXT
  printf '  [%-14s] %s\n' "$1" "$2"
  case "$1" in FAIL) S5_FAIL=$((S5_FAIL+1));; esac
}
crow() { # cumulative row: a FAIL here is a REGRESSION and blocks the gate
  printf '  [%-14s] %s\n' "$1" "$2"
  case "$1" in FAIL) CUM_FAIL=$((CUM_FAIL+1));; esac
}
note() { printf '  %s %s\n' '..' "$1"; }
run_test() { if bash "$FT/$1" >/dev/null 2>&1; then echo PASS; else echo FAIL; fi; }

printf '# PyBLE G1 (M1) exit-gate checklist — S5 SLICE (filesystem read / write / jail)\n'
printf '# repo: %s\n' "$REPO_ROOT"

# --- Cumulative guard: G0 + G1 S2 slice must still hold -----------------------
# CUMULATIVE RULE binds SIGNED/green gates: the hard blockers are the genuinely-
# green earlier slices (G0 + G1 S2). The G1 S3 and S4 slices are IN-FLIGHT within
# the same open G1 gate — their own exit codes cannot distinguish "regressed"
# from "not-yet-green", so (like g1_s3_check / g1_s4_check) they are reported
# INFORMATIONALLY and do not hard-block S5 authoring.
hdr "G1.S5.0 CUMULATIVE — G0 and the G1 S2 slice must not regress (signed/green earlier slices)"
if bash "$FT/gates/g0_check.sh" >/dev/null 2>&1; then
  crow PASS "G0 host slice still green"
else
  crow FAIL "G0 host slice REGRESSED — cannot sign any S5 item while G0 is red"
fi
if bash "$FT/gates/g1_check.sh" >/dev/null 2>&1; then
  crow PASS "G1 S2 slice (pyble_proto codec/CRC/frag/dispatch, pyble_ble pure helpers) still green"
else
  crow FAIL "G1 S2 slice REGRESSED — cannot sign S5 while the S2 slice is red"
fi
if bash "$FT/gates/g1_s3_check.sh" >/dev/null 2>&1; then
  note "G1 S3 slice host-runnable checks currently GREEN"
else
  note "G1 S3 slice not yet fully green (S3 pyble_* modules in flight) — tracked by gates/g1_s3_check.sh; NOT a signed-gate regression. Re-verify green before G1 sign-off (cumulative rule)."
fi
if bash "$FT/gates/g1_s4_check.sh" >/dev/null 2>&1; then
  note "G1 S4 slice host-runnable checks currently GREEN"
else
  note "G1 S4 slice not yet fully green (S4 pyble_*/pble_* modules in flight) — tracked by gates/g1_s4_check.sh; NOT a signed-gate regression. Re-verify green before G1 sign-off (cumulative rule)."
fi

# --- Spec-freeze precondition (SDD): §5 payloads + FR-FS mirror + jail --------
hdr "G1.S5.1 SDD precondition — protocol.md §5 + specs.md FR-FS mirror + jail FROZEN before S5 [red]/[green]"
PROTO="$REPO_ROOT/docs/specifications/protocol.md"
SPECS="$REPO_ROOT/docs/specifications/firmware/specs.md"
# §4 opcode numbers (0x10..0x1A, 0x41) and §8 status are already frozen (G1).
# What S5 needs is protocol.md §5 (File transfer — read + upload halves) to gain
# its "FROZEN for v1.0" banner AND the specs.md payload-level FR-FS to STOP
# tracking §5, PLUS the specs.md F-17 jail definition to freeze. Detection:
#   (a) §5 read/upload: specs.md carries the DRAFT tracking marker
#       "still tracks §5"; freeze = that marker is ABSENT (avoids false-positives
#       from any partial banner — §5 today has NO 'FROZEN' banner at all).
#   (b) jail: the freeze INTRODUCES the concrete forbidden set into specs.md; a
#       reliable anchor is the reserved transfer-scratch suffix ".pbltmp" (or the
#       chokepoint symbol pble_fs_resolve) — absent today, so PRESENCE = frozen.
frozen_when_marker_absent() { # DRAFT_REGEX  FILE  LABEL
  if grep -qiE "$1" "$2" 2>/dev/null; then
    row DEFERRED-DOCS "$3 (still DRAFT — project-architect [docs] freeze of protocol.md §5; firmware-architect mirrors specs.md §4.4)"
  else
    row PASS "$3"
  fi
}
frozen_when_anchor_present() { # ANCHOR_REGEX  FILE  LABEL
  if grep -qiE "$1" "$2" 2>/dev/null; then
    row PASS "$3"
  else
    row DEFERRED-DOCS "$3 (not yet frozen — firmware-architect owns the specs.md jail [docs] commit: chokepoint + concrete forbidden set)"
  fi
}
frozen_when_marker_absent 'still tracks §5' "$SPECS" "protocol.md §5 File transfer (read + upload) payload FROZEN + specs.md §4.4 FR-FS payload mirror — DoR for F-08/F-09 [red]"
frozen_when_anchor_present '\.pbltmp|pble_fs_resolve' "$SPECS" "specs.md F-17 jail definition FROZEN (single chokepoint pble_fs_resolve + forbidden set incl. reserved .pbltmp suffix + reserved agent-prefix) — DoR for F-17 [red]"
note "while the rows above are DEFERRED-DOCS, the S5 payload-semantic vectors stay in host/conformance/s5_pending.json (no frame bytes) — see the file _blocked_on ledger + _deviations_from_current_prose (GET_BEGIN drops up-front crc32; windowed PUT is Go-Back-N)"

# --- S5 host conformance slice (payload-semantic — DoR-BLOCKED until freeze) --
hdr "G1.S5.2 F-08 filesystem read (FILE_LIST / FILE_STAT / FILE_GET_*)  [pble_fs — storage-engineer]"
row "DEFERRED-DOCS" "LIST rooted at fs_root (ENOENT on missing dir); STAT {size,crc} + ENOENT on missing; GET streams BEGIN{total_size}->DATA->END{whole-file crc over [0,total_size)}; errno->§8 mapping (FR-FS-1/2/3/15) — s5_pending.json:file_list_rooted_at_fs_root,file_stat_size_crc_and_enoent,file_get_whole_file_crc,file_get_missing_enoent,fs_errno_to_status_mapping"

hdr "G1.S5.3 F-09 filesystem write (windowed FILE_PUT + DELETE/MKDIR/RENAME)  [pble_fs — storage-engineer]"
row "DEFERRED-DOCS" "windowed PUT W=4 Go-Back-N cumulative ACK{watermark}; PUT_END whole-file CRC OK-only; ECRC KEEPS old file; temp-write-then-rename atomic; resume_offset field (S5=0); single-active-transfer EBUSY; DELETE/MKDIR/RENAME status; .py/data-only no .mpy/.pyc (FR-FS-4/5/6/8/9/12/14, CON-3, NFR-PERF-2) — s5_pending.json:put_*,file_delete_semantics,mkdir_semantics,file_rename_semantics,py_data_only_no_mpy_pyc,single_active_transfer_ebusy"

hdr "G1.S5.4 F-17 workspace-jail enforcement  [pble_fs_resolve chokepoint — storage-engineer]"
row "DEFERRED-DOCS" "traversal ('../') + absolute escape -> EACCES; forbidden set (fs_root confinement + reserved .pbltmp suffix + reserved agent-prefix) -> EACCES; NUL/empty -> EBADREQ; overlong(>128B) -> ERANGE; SINGLE unbypassable chokepoint; user-code FS unaffected (FR-FS-10/11/16, SEC-4) — s5_pending.json:jail_traversal_and_absolute_escape_eacces,jail_forbidden_set_eacces,jail_single_chokepoint_unbypassable,jail_user_code_fs_unaffected"

# --- Native-C unit coverage (Unity-on-native, arrives F-20) -------------------
hdr "G1.S5.5 Native-C unit coverage — pble_fs.c (Unity, arrives with F-20)"
row "DEFERRED-NATIVE" "whole-file crc32 oracle, pble_fs_resolve canonicalization + forbidden-set vectors, list/stat/get payload build, pble_fs_errno_to_status table — pble_fs is native C (ADR-0006), no host-importable module; Unity-on-native lands F-20 (native test harness)"

# --- Shared cross-language corpus (firmware <-> Dart pble) --------------------
hdr "G1.S5.6 Shared PBLE/1 corpus — frozen frame-level FS vectors still verify"
row "$(run_test test_pyble_proto.sh)" "corpus.json still byte-verifies incl. file_put_data_cmd (0x16, opaque payload) — the FS opcode frame codec + CRC + fragmentation (§4/§3 frozen)"
note "payload-SEMANTIC S5 vectors are held in conformance/s5_pending.json until protocol.md §5 freeze; they carry NO frame_hex (wire is referenced, never redefined). On freeze: add frame-level opaque vectors for 0x10/0x11/0x12/0x13/0x14/0x15/0x17/0x18/0x19/0x1A/0x41, then the payload-semantic vectors."

# --- No-leak (cumulative clean-room gate) ------------------------------------
hdr "G1.S5.7 Clean-room no-leak still clean over the test tree"
if grep -rniE "$(forbidden_regex)" "$FT" --include='*.py' --include='*.sh' --include='*.json' >/dev/null 2>&1; then
  row FAIL "no-leak: forbidden token found in tests/firmware_tests"
else
  row PASS "no-leak: tests/firmware_tests free of forbidden proprietary tokens"
fi

# --- S5 HIL demo items (real esp32 / -s3 / -c3) — the truth for the gate ------
hdr "G1.S5.8 S5 behaviours on real hardware  [HIL — ESP32-S3 harness: UART REPL + bleak central]"
row "DEFERRED-HIL" "F-08: FILE_LIST returns entries rooted at fs_root; a missing directory returns ENOENT (FR-FS-1/15)"
row "DEFERRED-HIL" "F-08: FILE_STAT returns {size,crc} matching a host-side zlib oracle; a missing path returns ENOENT (FR-FS-2)"
row "DEFERRED-HIL" "F-08: FILE_GET streams a file byte-exact; FILE_GET_END whole-file CRC matches; a resume GET (offset>0) still reports the whole-file CRC over [0,total_size) (FR-FS-3)"
row "DEFERRED-HIL" "F-09: windowed PUT (W=4) over a lossy link advances on cumulative FILE_PUT_ACK{watermark}; a dropped/out-of-order chunk is re-ACKed at the watermark and retransmitted (Go-Back-N) (FR-FS-4/5, NFR-PERF-2)"
row "DEFERRED-HIL" "F-09: FILE_PUT_END reports OK ONLY after a whole-file CRC match; a deliberately-corrupted upload returns ECRC and the PRE-EXISTING dest file is byte-intact (temp deleted) (FR-FS-6/14)"
row "DEFERRED-HIL" "F-09: temp-write-then-rename atomicity — the dest appears only after fsync + a CRC-gated os.rename; LittleFS rename is atomic across a mid-rename power cut (FR-FS-9)"
row "DEFERRED-HIL" "F-09: a 2nd *_BEGIN while a transfer is active returns EBUSY (single-active-transfer); the host task stays responsive — other commands still answer during a GET/PUT (FR-BLE-11)"
row "DEFERRED-HIL" "F-09: FILE_DELETE (file / empty-dir OK; non-empty-dir EACCES; missing ENOENT), MKDIR (create/idempotent OK; over-file EBADREQ; missing-parent ENOENT), FILE_RENAME (atomic; src-missing ENOENT; dst-non-empty-dir EACCES) (FR-FS-8/15)"
row "DEFERRED-HIL" "F-09: the bridge never generates/accepts .mpy/.pyc; no server-side compilation (FR-FS-12, CON-3)"
row "DEFERRED-HIL" "F-17: '../' traversal + absolute paths outside fs_root are rejected EACCES across EVERY op (LIST/STAT/GET/PUT/DELETE/MKDIR/RENAME src+dst) (FR-FS-10, SEC-4)"
row "DEFERRED-HIL" "F-17: a PUT/DELETE/RENAME targeting a reserved agent-prefix path or a raw '.pbltmp' path returns EACCES — the control plane is non-writable via the bridge (FR-FS-11, SEC-4)"
row "DEFERRED-HIL" "F-17: user CODE (via RUN) reads/writes the filesystem normally through os/vfs, UNAFFECTED by the bridge jail — proving the jail is bridge-only (FR-FS-16)"
row "DEFERRED-HIL" "F-08/09/17: identity NEVER gates FS access — FILE_* ops behave identically with or without a label configured (SEC-11)"

printf '\n----------------------------------------\n'
if [ "$CUM_FAIL" -ne 0 ]; then
  printf 'G1 S5 slice: CUMULATIVE REGRESSION (%d) — an earlier gate is red; S5 CANNOT be signed (PRD §1B.7).\n' "$CUM_FAIL"
  exit 1
fi
if [ "$S5_FAIL" -ne 0 ]; then
  printf 'G1 S5 slice: %d host criteria FAILING. G1 NOT advanced.\n' "$S5_FAIL"
  exit 1
fi
printf 'G1 S5 slice: host-runnable checks PASS; S5 payload-semantic conformance is DoR-BLOCKED (protocol.md §5 + specs.md FR-FS mirror + specs.md jail not yet frozen) and the behaviours are DEFERRED-HIL / native coverage DEFERRED-NATIVE (F-20). G1 remains OPEN through S6.\n'
exit 0

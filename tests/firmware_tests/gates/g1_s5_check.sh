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
# and REFUSES to sign any S5 item if an earlier implemented host slice regressed.
#
# A milestone gate is green ONLY on a real-hardware HIL demo. This script verifies
# the implemented HOST-runnable S5 slice and reports physical items as
# DEFERRED-HIL. Protocol §5, its FR-FS mirror, and the F-17 jail are frozen;
# their former planning ledger is retained only in the conformance archive.
#
# NOTE (native-C reality, ADR-0006): pble_fs is native C — there is NO host-
# importable Python module for it (unlike the S2/S3 pyble_*.py modules). So the
# portable twin supplies host-executable filesystem semantics and focused source
# guards cover native hardening. A true Unity-on-native harness remains
# DEFERRED-NATIVE and is not substituted by those host checks.
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
# green earlier slices (G0 + G1 S2–S4).
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
  crow FAIL "G1 S3 slice REGRESSED — current host criteria must pass before S5 can be signed"
fi
if bash "$FT/gates/g1_s4_check.sh" >/dev/null 2>&1; then
  note "G1 S4 slice host-runnable checks currently GREEN"
else
  crow FAIL "G1 S4 slice REGRESSED — current host criteria must pass before S5 can be signed"
fi

# --- Spec-freeze precondition (SDD): §5 payloads + FR-FS mirror + jail --------
hdr "G1.S5.1 SDD precondition — protocol.md §5 + specs.md FR-FS mirror + jail FROZEN before S5 [red]/[green]"
PROTO="$REPO_ROOT/docs/specifications/protocol.md"
SPECS="$REPO_ROOT/docs/specifications/firmware/specs.md"
# §4 opcode numbers (0x10..0x1A, 0x41) and §8 status are already frozen (G1).
# The historical pre-freeze marker must remain absent and the concrete jail
# anchor must remain present. Either regression fails this current gate.
frozen_when_marker_absent() { # DRAFT_REGEX  FILE  LABEL
  if grep -qiE "$1" "$2" 2>/dev/null; then
    row FAIL "$3 (obsolete pre-freeze marker reappeared)"
  else
    row PASS "$3"
  fi
}
frozen_when_anchor_present() { # ANCHOR_REGEX  FILE  LABEL
  if grep -qiE "$1" "$2" 2>/dev/null; then
    row PASS "$3"
  else
    row FAIL "$3 (frozen jail anchor missing)"
  fi
}
frozen_when_marker_absent 'still tracks §5' "$SPECS" "protocol.md §5 File transfer (read + upload) payload FROZEN + specs.md §4.4 FR-FS payload mirror — DoR for F-08/F-09 [red]"
frozen_when_anchor_present '\.pbltmp|pble_fs_resolve' "$SPECS" "specs.md F-17 jail definition FROZEN (single chokepoint pble_fs_resolve + forbidden set incl. reserved .pbltmp suffix + reserved agent-prefix) — DoR for F-17 [red]"
note "pre-freeze planning vectors are archived byte-for-byte and are not active requirements"

# --- S5 host conformance slice ------------------------------------------------
FS_HOST_STATUS="$(run_test test_pyble_fs.sh)"
hdr "G1.S5.2 F-08 filesystem read (FILE_LIST / FILE_STAT / FILE_GET_*)  [pble_fs — storage-engineer]"
row "$FS_HOST_STATUS" "portable semantic oracle: LIST root/ENOENT, STAT size+CRC, GET extent+whole-file CRC, and errno mapping (FR-FS-1/2/3/15)"

hdr "G1.S5.3 F-09 filesystem write (windowed FILE_PUT + DELETE/MKDIR/RENAME)  [pble_fs — storage-engineer]"
row "$FS_HOST_STATUS" "portable semantic oracle: windowed PUT, cumulative ACK, CRC-gated replace, mutations, resume field, transfer exclusion, and source/data-only policy (FR-FS-4/5/6/8/9/12/14)"

hdr "G1.S5.4 F-17 workspace-jail enforcement  [pble_fs_resolve chokepoint — storage-engineer]"
row "$FS_HOST_STATUS" "portable semantic oracle: traversal/absolute/reserved rejection, malformed and overlong bounds, and bridge-only jail behavior (FR-FS-10/11/16, SEC-4)"

# --- Native-C unit coverage (Unity-on-native, arrives F-20) -------------------
hdr "G1.S5.5 Native-C unit coverage — pble_fs.c (Unity, arrives with F-20)"
row "DEFERRED-NATIVE" "whole-file crc32 oracle, pble_fs_resolve canonicalization + forbidden-set vectors, list/stat/get payload build, pble_fs_errno_to_status table — pble_fs is native C (ADR-0006), no host-importable module; Unity-on-native lands F-20 (native test harness)"

# --- Shared cross-language corpus (firmware <-> Dart pble) --------------------
hdr "G1.S5.6 Shared PBLE/1 corpus — frozen frame-level FS vectors still verify"
row "$(run_test test_pyble_proto.sh)" "corpus.json still byte-verifies incl. file_put_data_cmd (0x16, opaque payload) — the FS opcode frame codec + CRC + fragmentation (§4/§3 frozen)"
note "the shared corpus retains its frame-level vectors; current filesystem semantics are exercised by the portable oracle and native guards without claiming retrospective corpus promotion"

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
row "DEFERRED-HIL" "F-09: windowed PUT (advertised W=8) over a lossy link advances on cumulative FILE_PUT_ACK{watermark}; a dropped/out-of-order chunk is re-ACKed at the watermark and retransmitted (Go-Back-N) (FR-FS-4/5, NFR-PERF-2)"
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
printf 'G1 S5 slice: host-runnable checks PASS; physical behaviours remain DEFERRED-HIL and Unity-on-native coverage remains DEFERRED-NATIVE (F-20). G1 remains OPEN through S6.\n'
exit 0

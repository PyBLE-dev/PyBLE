#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
#
# G1 exit-gate checklist (milestone M1 "Firmware agent on classic ESP32").
# Enumerates the retained G1 firmware-agent criteria and reports
# PASS / FAIL / DEFERRED(HIL|STORY) for each.
#
# CUMULATIVE RULE (02_milestones.md): gates are cumulative — G1 is never green
# while an earlier gate regresses. This script FIRST re-runs the G0 host slice
# and refuses to sign any G1 item if G0 regressed. A milestone gate is green ONLY
# on a real-hardware HIL demo; this script verifies only the HOST-runnable slice.
#
# SCOPE: G1 spans sprints S2–S6. THIS sprint (S2) delivers the HELLO/DEVICE_INFO
# + framing SLICE (F-01 pyble_ble pure helpers, F-02 pyble_proto codec/CRC/
# fragmentation/dispatch/conformance). Later G1 rows (F-03 info, F-04..07 run/
# console, F-08..11/17 fs+jail, F-12 boot, F-18 pairing, F-22/23 label+identify)
# are reported DEFERRED-STORY until their sprints. **G1 does NOT close at S2.**
#
# Exit non-zero if any HOST-verifiable S2-slice criterion FAILs (RED is expected
# now: the pyble_* modules are not yet implemented). DEFERRED does not fail.

set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
FT="$(cd "$HERE/.." && pwd)"
. "$FT/lib/common.sh"

G1_FAIL=0

hdr() { printf '\n### %s\n' "$1"; }
row() { # STATUS  TEXT
  printf '  [%-13s] %s\n' "$1" "$2"
  case "$1" in FAIL) G1_FAIL=$((G1_FAIL+1));; esac
}
note() { printf '  %s %s\n' '..' "$1"; }  # informational, not a checklist row
run_test() { if bash "$FT/$1" >/dev/null 2>&1; then echo PASS; else echo FAIL; fi; }

printf '# PyBLE G1 (M1 Agent on classic ESP32) exit-gate checklist — S2 SLICE\n'
printf '# repo: %s\n' "$REPO_ROOT"

# --- Cumulative guard: G0 must still hold ------------------------------------
hdr "G1.0 CUMULATIVE — G0 host slice must not regress"
if bash "$FT/gates/g0_check.sh" >/dev/null 2>&1; then
  row PASS "G0 host-verifiable slice still green (cumulative rule holds)"
else
  row FAIL "G0 host slice REGRESSED — G1 cannot be signed while G0 is red"
fi

# --- S2 host slice: PBLE/1 framing core (F-02) -------------------------------
hdr "G1.1 PBLE/1 framing core: codec + IEEE CRC-32 + fragmentation + dispatch  [F-02]"
row "$(run_test test_pyble_proto.sh)" "pyble_proto host unit + conformance corpus green (§3.1/§3.2/§4/§8)"
note "conformance corpus host/conformance/corpus.json is the SHARED cross-language guard (firmware <-> Dart pble)"

# --- S2 host slice: BLE pure helpers (F-01) ----------------------------------
hdr "G1.2 BLE peripheral pure helpers: PyBLE-XXXX name, INFO payload, MTU sizing  [F-01]"
row "$(run_test test_pyble_ble.sh)" "pyble_ble PURE helpers host-green (name derivation, INFO pass-through, payload = MTU-4)"

# --- S2 HIL-deferred: the NimBLE peripheral itself ---------------------------
hdr "G1.3 BLE peripheral on real hardware  [F-01 — HIL on classic ESP32]"
row "DEFERRED-HIL" "one GATT service on the PyBLE UUID base; RX Write/WWR, TX Notify, INFO Read (FR-BLE-1..4)"
row "DEFERRED-HIL" "advertises Service UUID + PyBLE-XXXX; app scans FILTERED to the Service UUID (FR-BLE-5/6)"
row "DEFERRED-HIL" "accepts MTU 247; subscribe TX + read INFO succeed (FR-BLE-7)"
row "DEFERRED-HIL" "NimBLE only, Bluedroid not built; fully offline; no HW-output/calib/safety logic (FR-BLE-9/CON-5, NFR-OFF-1/2, NFR-SAFE-4) — source review + HIL"

# --- G1 criterion this slice feeds (needs F-03, HIL) -------------------------
hdr "G1.4 From a test client on a classic ESP32: HELLO + DEVICE_INFO succeed  [F-01, F-02, F-03]"
row "DEFERRED-HIL" "end-to-end HELLO + DEVICE_INFO round-trip on a classic ESP32 (also needs F-03 pyble_info, S3)"

# --- Remaining G1 criteria (later sprints S3–S6) -----------------------------
hdr "G1.5 Remaining G1 criteria — DEFERRED to later M1 sprints (S3–S6)"
row "DEFERRED-STORY" "put/get/list/delete file round-trip + CRC + resume, reliability bench (F-08..11, S5–S6)"
row "DEFERRED-STORY" "RUN(file|source) / STOP vs while-True / live console (F-04..07, S3–S4)"
row "DEFERRED-STORY" "workspace jail rejects escapes; BLE pairing baseline (F-17, F-18, S6)"
row "DEFERRED-STORY" "device label sets/clears PyBLE-XXXX pre-connect; cap-gated IDENTIFY; identity never gates access (F-22, F-23, S3–S4)"

printf '\n----------------------------------------\n'
if [ "$G1_FAIL" -ne 0 ]; then
  printf 'G1 (S2 slice): %d host-verifiable criteria FAILING — expected RED until [green] pyble_proto/pyble_ble land. Plus DEFERRED HIL/STORY items. G1 NOT met.\n' "$G1_FAIL"
  exit 1
fi
printf 'G1 (S2 slice): host-verifiable S2 criteria PASS. G1 still requires the DEFERRED HIL demo + later-sprint stories (S3–S6) before sign-off.\n'
exit 0

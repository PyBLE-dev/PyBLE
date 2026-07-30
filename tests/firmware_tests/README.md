# Firmware gate tests (`tests/firmware_tests/`)

Host-runnable `[red]` gate tests + fixtures for the firmware track. **S1 / M0 /
G0** is the build-machinery slice (`test_*.sh` gate tests); **S2 / M1 / G1** adds
the PBLE/1 protocol + BLE agent slice as **CPython host unit + conformance tests**
under `host/`. No hardware, no ESP-IDF, and no MicroPython submodule fetch are
required — these run on a plain host and pin the *behaviour* the `[green]`
production modules must satisfy. The three-chip cross-compile and the HIL demo run
later on a toolchain machine / real hardware and are reported as **DEFERRED**.

## Layout (S2 additions)

```
host/
  _support.py                 # path + MicroPython-guard wiring; corpus loader; red-with-a-reason
  _fakes/{bluetooth,machine}.py  # HOST-ONLY import guards (NimBLE/machine NEVER faked — HIL only)
  conformance/corpus.json     # SHARED cross-language PBLE/1 byte corpus (firmware <-> Dart pble)
  test_pyble_proto.py         # F-02 [red] — frame codec, CRC-32, fragmentation, dispatch, status
  test_pyble_ble.py           # F-01 [red] — PURE helpers only (name/INFO/MTU); peripheral is HIL
test_pyble_proto.sh           # wrapper so run_tests.sh drives the F-02 CPython suite
test_pyble_ble.sh             # wrapper so run_tests.sh drives the F-01 CPython suite
gates/g1_check.sh             # G1 (M1) exit-gate checklist — S2 slice (cumulative: re-runs G0)
```

Authored by **firmware-test-author** (sole author of `[red]` tests). The
production gate scripts these tests invoke are owed by **build-smith**
(`[green]`) and do **not** exist yet — so the suite is **RED by design** at S1.

## Run

```sh
# all gate tests
tests/firmware_tests/run_tests.sh

# a single test file
tests/firmware_tests/run_tests.sh test_no_leak.sh

# the G0 / G1 exit-gate checklists (PASS / FAIL / DEFERRED per criterion)
tests/firmware_tests/gates/g0_check.sh
tests/firmware_tests/gates/g1_check.sh

# the S2 host suites directly (CPython)
python3 tests/firmware_tests/host/test_pyble_proto.py
python3 tests/firmware_tests/host/test_pyble_ble.py
```

Exit code is non-zero while any gate is unmet (expected at S1).

## Story → test mapping

| Story | Test file | Acceptance criterion captured |
|---|---|---|
| X-01 | `test_spdx_header.sh` | Every source file carries `SPDX-License-Identifier: MIT`, enforced by a lint (NFR-MAINT-4). |
| X-01 | `test_dco_signoff.sh` | A commit missing `Signed-off-by` is rejected; signed history passes (CON-6). |
| X-01 | `test_governance_files.sh` | MIT LICENSE + README + CONTRIBUTING + CoC present; CONTRIBUTING documents `git commit -s`. *(green now — standing guard.)* |
| X-02 | `test_no_leak.sh` | Forbidden-token tree fails, clean tree passes, non-code files exempt (CON-6, PRD 1A.2/16.3); plus a self-check that this tree has zero forbidden literals. |
| F-15 | `test_patches_policy.sh` | Default zero patches; a patch with no written reason is refused (CON-12/BLD-15). |
| F-15 | `test_upgrade_workflow.sh` | `upgrade_micropython.sh` bumps `versions.lock` in its own commit (dry-run) (BLD-9). |
| F-15 | `test_submodule_idf.sh` | `.gitmodules` declares the pinned micropython submodule; ESP-IDF is gitignored, not a submodule (CON-1/2, BLD-11). |
| X-03 | `test_sha_drift.sh` | Build prep refuses on submodule-SHA vs `versions.lock` mismatch, proceeds on match (BLD-1/2). |
| X-03 | `test_build_matrix.sh` | `build.sh` maps `esp32-s3→esp32s3` / `esp32-c3→esp32c3`, rejects unknown target, plans the artifact set, never fakes a build; `build_all.sh` drives all three (BLD-3/4/5, CON-11). |
| F-01 | `host/test_pyble_ble.py` | PURE host helpers only: `PyBLE-XXXX` name from the last 2 MAC bytes uppercase hex (FR-BLE-5), advertised-name = label-else-default (FR-BLE-5/12), INFO read = DEVICE_INFO payload verbatim (FR-BLE-4), payload sizing = MTU−4 (FR-BLE-8). NimBLE peripheral (GATT/adv/scan-filter/MTU-247/subscribe) is **HIL-DEFERRED** (`gates/g1_check.sh`). |
| F-02 | `host/test_pyble_proto.py` | §3.1 frame encode/decode vs the shared corpus (FR-PROTO-2), IEEE CRC-32 over VER…PAYLOAD (FR-PROTO-3), CRC-fail→`EVT ERROR(ECRC)` ref opcode + drop (FR-PROTO-3), ID correlation / EVT ID=0 (FR-PROTO-4), opcode dispatch (FR-PROTO-5), full §4 opcode set (FR-PROTO-1) + §8 status set (FR-PROTO-6), malformed→`EBADREQ` (FR-PROTO-8), unknown→`EUNSUPPORTED` (FR-PROTO-9, fwd F-16), fragment/reassemble byte-identical over the MTU matrix incl. index-mod-64 wrap (FR-BLE-8/10). |
| F-11 | `hil/f11_reliability_bench.py` | **HIL bench** (firmware-test-author, no firmware `[green]`): uploads N files back-to-back at MTU 247 over BLE (`bleak`) and asserts every file's whole-file CRC (`FILE_PUT_END`) + an independent `FILE_STAT` re-verify (NFR-REL-5, FR-FS-6/14); reports a throughput baseline (NFR-PERF-1 / NFR-FP-TPUT) — **never** a hardcoded ceiling (OI-1: floor applied only via `--tput-floor-bps`). `--relabel` proves identity never gates access (SEC-11). HIL-only. |
| F-11 | `host/conformance/test_hil_wire.py` (`test_hil_wire.sh`) | **Host-runnable NOW:** the bench's PBLE/1 codec (`hil/_pble_wire.py`) matches the SHARED corpus byte-for-byte across the MTU matrix incl. the index-mod-64 wrap (FR-PROTO-2/3, FR-BLE-8/10) — the HIL harness cannot drift from the firmware↔Dart wire. |
| F-10 / F-12 / F-18 | `host/conformance/s6_pending.json` | **DoR-BLOCKED** semantic obligations (no frame bytes): F-10 resume (verified prefix → `resume_offset>0`, byte-identical resume, ECRC-keeps-old-file); F-12 cold-boot advertise-and-wait + opt-in auto-run + fail-safe; F-18 pairing-active-not-access-gating + single-writer + no-MAC-gating/no-telemetry/no-PII-adv. Blocked on three `[docs]` freezes (§5 resume behaviour; §10 Security/§9 SEC; OI-5 auto_run+SET_AUTORUN/§4.7 FR-BOOT). |
| G0 | `gates/g0_check.sh` | Enumerates the five G0 exit-gate criteria as PASS / FAIL / DEFERRED. |
| G1 | `gates/g1_check.sh` | S2 slice of the G1 (M1) ladder: host-PASS (F-01/F-02) vs HIL-DEFERRED (peripheral, HELLO/DEVICE_INFO bench) vs DEFERRED-STORY (S3–S6). Cumulative: re-runs `g0_check.sh` and refuses to sign while G0 regresses. |
| G1 | `gates/g1_s6_check.sh` | **S6 slice (CLOSES G1):** F-11 host wire-guard PASS + bench present; F-10/F-12/F-18 DEFERRED-DOCS (three freezes) + DEFERRED-HIL; native coverage DEFERRED-NATIVE (F-20). Cumulative: re-runs G0 + G1 S2, reports S3/S4/S5 informationally. |

## Production-code contracts (HAND-OFF to build-smith)

These tests define, and assert against, the interfaces the `[green]` scripts must
provide. All are missing at S1 (the RED reason). To keep the tests hermetic and
CI-scoped, several accept env/flag overrides:

| Script | Interface the tests assert |
|---|---|
| `tools/ci/no_leak.sh [ROOT]` | Scans `ROOT/{app,firmware,protocol,examples,tests,tools}` `.dart/.c/.h/.py`; non-zero on any forbidden token. |
| `tools/ci/spdx_lint.sh [ROOT]` | Non-zero if any source file under `ROOT` lacks `SPDX-License-Identifier: MIT`. |
| `tools/ci/dco_check.sh [REPO_DIR]` | Honours `$PYBLE_DCO_RANGE`; non-zero if any commit lacks `Signed-off-by:`. |
| `tools/ci/sha_drift.sh` | Honours `$PYBLE_LOCK_FILE` / `$PYBLE_UPSTREAM_DIR`; non-zero on SHA mismatch or uninitialized submodule. |
| `tools/ci/patches_policy.sh [DIR]` | Non-zero if any `*.patch` lacks a sibling non-empty `REASON.md`; zero on empty. |
| `firmware/scripts/build.sh` | `--plan <target>` prints `idf_target=<mapped>`, `board_overlays/<target>`, and the `firmware.bin`/bootloader/partition artifact set; unknown target non-zero; a real build with no ESP-IDF exits non-zero with an actionable message (never fakes success). |
| `firmware/scripts/build_all.sh` | `--plan` drives all three targets. |
| `firmware/scripts/upgrade_micropython.sh` | `--dry-run <ref> <commit>` prints a plan naming `versions.lock` and an "own commit"; mutates nothing. |
| `firmware/pyble/pyble_proto.py` (**protocol-engineer**) | `VER`, `OPCODES`/`STATUS` (frozen §4/§8 maps), `crc32`, `encode`, `decode(→Frame)`, `fragment`/`reassemble`, `Dispatcher.register`/`.on_message` (RSP echoes id+opcode; CRC-fail→EVT ECRC id=0; unknown→EUNSUPPORTED; malformed→EBADREQ). Interface pinned by `host/test_pyble_proto.py`. |
| `firmware/pyble/pyble_ble.py` (**ble-transport-engineer**) | PURE helpers `device_id_from_mac(mac)→"XXXX"`, `advertised_name(device_id,label="")`, `payload_size(mtu)=mtu−4`, `info_read_value(payload)` (verbatim). Guard/defer `import bluetooth` so these import on the host. Interface pinned by `host/test_pyble_ble.py`. Peripheral itself is HIL. |

## Clean-room

No forbidden proprietary literal is ever committed here. The tokens the no-leak
gate must reject are **assembled at runtime** from harmless fragments
(`lib/common.sh`), so a scan for the forbidden proprietary identifiers (the
AGENTS.md no-leak regex) over this tree returns nothing and the repo-wide
no-leak gate stays green. `test_no_leak.sh` self-checks this invariant.

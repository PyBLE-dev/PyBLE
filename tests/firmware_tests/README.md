# Firmware gate tests (`tests/firmware_tests/`)

Host-runnable tests and fixtures for the complete firmware track. **S1 / M0 /
G0** introduced the build-machinery gates; **S2–S6 / M1 / G1** added the PBLE/1
protocol and BLE-agent slices; later suites cover five-profile release and
v0.6.1 hardening contracts. No hardware is required for the host suites. Exact
cross-build, resource, recovery, and physical HIL evidence remain separate
release gates and are never inferred from host success.

## Selected layout

```
host/
  _support.py                 # path + MicroPython-guard wiring; corpus loader; red-with-a-reason
  _fakes/{bluetooth,machine}.py  # HOST-ONLY import guards (NimBLE/machine NEVER faked — HIL only)
  conformance/corpus.json     # retained shared PBLE/1 frame/CRC corpus
  conformance/v061_*.json     # active v0.6.1 semantic parity vectors
  conformance/archive/        # immutable byte-less pre-freeze planning ledgers
  test_pyble_proto.py         # F-02 [red] — frame codec, CRC-32, fragmentation, dispatch, status
  test_pyble_ble.py           # F-01 [red] — PURE helpers only (name/INFO/MTU); peripheral is HIL
test_pyble_proto.sh           # wrapper so run_tests.sh drives the F-02 CPython suite
test_pyble_ble.sh             # wrapper so run_tests.sh drives the F-01 CPython suite
gates/g1_check.sh             # G1 (M1) exit-gate checklist — S2 slice (cumulative: re-runs G0)
```

Historical `[red]` banners preserve the commit-stage provenance of each test;
they do not mean the current branch is expected to fail. The corresponding
production modules and gate scripts now exist, and a host failure is a current
regression.

## Run

```sh
# all gate tests
tests/firmware_tests/run_tests.sh

# a single test file
tests/firmware_tests/run_tests.sh test_no_leak.sh

# the G0 / G1 exit-gate checklists (PASS / FAIL / DEFERRED per criterion)
tests/firmware_tests/gates/g0_check.sh
tests/firmware_tests/gates/g1_check.sh
tests/firmware_tests/gates/g1_s6_check.sh

# the S2 host suites directly (CPython)
python3 tests/firmware_tests/host/test_pyble_proto.py
python3 tests/firmware_tests/host/test_pyble_ble.py
python3 tests/firmware_tests/host/test_firmware_roadmap_ledger.py
```

A nonzero host exit is a regression. `DEFERRED-HIL` rows remain honest physical
work and do not become passed merely because the script itself exits zero.

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
| X-03 | `test_build_matrix.sh` | `build.sh` maps the generic and exact-board S3 variants to `esp32s3`, maps `esp32-c3→esp32c3`, rejects unknown targets, plans the artifact set, and never fakes a build; `build_all.sh` drives all four variants over three chips (BLD-3/4/5, CON-11). |
| F-01 | `host/test_pyble_ble.py` | PURE host helpers only: `PyBLE-XXXX` name from the last 2 MAC bytes uppercase hex (FR-BLE-5), advertised-name = label-else-default (FR-BLE-5/12), INFO read = DEVICE_INFO payload verbatim (FR-BLE-4), payload sizing = MTU−4 (FR-BLE-8). NimBLE peripheral (GATT/adv/scan-filter/MTU-247/subscribe) is **HIL-DEFERRED** (`gates/g1_check.sh`). |
| F-02 | `host/test_pyble_proto.py` | §3.1 frame encode/decode vs the shared corpus (FR-PROTO-2), IEEE CRC-32 over VER…PAYLOAD (FR-PROTO-3), CRC-fail→`EVT ERROR(ECRC)` ref opcode + drop (FR-PROTO-3), ID correlation / EVT ID=0 (FR-PROTO-4), opcode dispatch (FR-PROTO-5), full §4 opcode set (FR-PROTO-1) + §8 status set (FR-PROTO-6), malformed→`EBADREQ` (FR-PROTO-8), unknown→`EUNSUPPORTED` (FR-PROTO-9, fwd F-16), fragment/reassemble byte-identical over the MTU matrix incl. index-mod-64 wrap (FR-BLE-8/10). |
| F-11 | `hil/f11_reliability_bench.py` | **HIL bench** (firmware-test-author, no firmware `[green]`): uploads N files back-to-back at MTU 247 over BLE (`bleak`) and asserts every file's whole-file CRC (`FILE_PUT_END`) + an independent `FILE_STAT` re-verify (NFR-REL-5, FR-FS-6/14); reports a throughput baseline (NFR-PERF-1 / NFR-FP-TPUT) — **never** a hardcoded ceiling (OI-1: floor applied only via `--tput-floor-bps`). `--relabel` proves identity never gates access (SEC-11). HIL-only. |
| F-11 | `host/conformance/test_hil_wire.py` (`test_hil_wire.sh`) | **Host-runnable NOW:** the bench's PBLE/1 codec (`hil/_pble_wire.py`) matches the SHARED corpus byte-for-byte across the MTU matrix incl. the index-mod-64 wrap (FR-PROTO-2/3, FR-BLE-8/10) — the HIL harness cannot drift from the firmware↔Dart wire. |
| v0.6.1 protocol/session | `host/conformance/v061_session_vectors.json`, `host/test_v061_protocol_session.py`, `host/test_v061_pble_wire_native.py` | Shared exact HELLO grammar, negotiation, inbound direction/ID, validation precedence, and native/portable semantic parity. |
| v0.6.1 payload/label | `host/conformance/v061_payload_grammar_vectors.json`, `host/conformance/v061_label_vectors.json` | Existing-opcode payload validation and strict UTF-8 label semantics without adding a wire key or operation. |
| Archived S3–S6 ledgers | `host/conformance/archive/pre-freeze/` | Byte-identical historical planning records only. Their pre-freeze status and obsolete `max_file_size` references are not current requirements. |
| G0 | `gates/g0_check.sh` | Enumerates the five G0 exit-gate criteria as PASS / FAIL / DEFERRED. |
| G1 | `gates/g1_check.sh` | Retained S2 slice of the G1 (M1) ladder: implemented host checks plus explicit HIL deferrals. Cumulative: re-runs `g0_check.sh` and refuses to sign while G0 regresses. |
| G1 | `gates/g1_s6_check.sh` | **S6 slice (closes the host ladder):** frozen specification prerequisites and implemented host checks pass; physical F-10/F-11/F-12/F-18 rows remain `DEFERRED-HIL`, and true native-device coverage remains separately identified. |

## Retained production-code contracts

These tests define and assert the interfaces supplied by the production
scripts. Historical ownership notes explain the original red→green handoff.
To keep the tests hermetic and CI-scoped, several accept env/flag overrides:

| Script | Interface the tests assert |
|---|---|
| `tools/ci/no_leak.sh [ROOT]` | Scans `ROOT/{app,firmware,protocol,examples,tests,tools}` `.dart/.c/.h/.py`; non-zero on any forbidden token. |
| `tools/ci/spdx_lint.sh [ROOT]` | Non-zero if any source file under `ROOT` lacks `SPDX-License-Identifier: MIT`. |
| `tools/ci/dco_check.sh [REPO_DIR]` | Honours `$PYBLE_DCO_RANGE`; non-zero if any commit lacks `Signed-off-by:`. |
| `tools/ci/sha_drift.sh` | Honours `$PYBLE_LOCK_FILE` / `$PYBLE_UPSTREAM_DIR`; non-zero on SHA mismatch or uninitialized submodule. |
| `tools/ci/patches_policy.sh [DIR]` | Non-zero if any `*.patch` lacks a sibling non-empty `REASON.md`; zero on empty. |
| `firmware/scripts/build.sh` | `--plan <target>` prints `idf_target=<mapped>`, `board_overlays/<target>`, and the `firmware.bin`/bootloader/partition artifact set; unknown target non-zero; a real build with no ESP-IDF exits non-zero with an actionable message (never fakes success). |
| `firmware/scripts/build_all.sh` | `--plan` drives all four variants over three chips. |
| `firmware/scripts/upgrade_micropython.sh` | `--dry-run <ref> <commit>` prints a plan naming `versions.lock` and an "own commit"; mutates nothing. |
| `firmware/pyble/pyble_proto.py` (**protocol-engineer**) | `VER`, `OPCODES`/`STATUS` (frozen §4/§8 maps), `crc32`, `encode`, `decode(→Frame)`, `fragment`/`reassemble`, `Dispatcher.register`/`.on_message` (RSP echoes id+opcode; CRC-fail→EVT ECRC id=0; unknown→EUNSUPPORTED; malformed→EBADREQ). Interface pinned by `host/test_pyble_proto.py`. |
| `firmware/pyble/pyble_ble.py` (**ble-transport-engineer**) | PURE helpers `device_id_from_mac(mac)→"XXXX"`, `advertised_name(device_id,label="")`, `payload_size(mtu)=mtu−4`, `info_read_value(payload)` (verbatim). Guard/defer `import bluetooth` so these import on the host. Interface pinned by `host/test_pyble_ble.py`. Peripheral itself is HIL. |

## Clean-room

No forbidden proprietary literal is ever committed here. The tokens the no-leak
gate must reject are **assembled at runtime** from harmless fragments
(`lib/common.sh`), so a scan for the forbidden proprietary identifiers (the
AGENTS.md no-leak regex) over this tree returns nothing and the repo-wide
no-leak gate stays green. `test_no_leak.sh` self-checks this invariant.

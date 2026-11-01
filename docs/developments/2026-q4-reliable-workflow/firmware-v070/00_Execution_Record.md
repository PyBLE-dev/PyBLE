<!-- SPDX-License-Identifier: MIT -->
<!-- Part of PyBLE (https://pyble.dev) — see /LICENSE. -->

# Firmware v0.7 development — committed run/session status

Started 1 November 2026 under the user's firmware-roadmap request and preceding
recommendation to deliver PYB-017.1 → PYB-018 first. The user supplied Lenovo,
iPad and all five boards. This record owns the selected increment's engineering
evidence, without announcing a complete Reliable Projects release.
Engineering evidence closeout: 1 November 2026. Both tablets pass all five R5
normal UI rows; actual Android ATT23/247 passes on every profile. Historical
client compatibility has nine passes and one Partial (recovered) result.
Implementation is ready for review; full release admission remains pending.

## Scope and source boundaries

| Item | Selection |
|---|---|
| Contract | [PBLE/1 §6.1](../../../specifications/protocol.md#61-additive-runsession-status--selected-v07-increment), [ADR-0049](../../../decisions/0049-query-run-state-after-reconnect.md); normative commit `27811da` preceded implementation |
| Executed firmware | Development `0.7.0-dev.1`, frozen source `1093bab3de811469c14bb1b8e77d4f91b29fa962`; five exact builds, existing pinned tools/dependencies |
| Final app freeze, R5 | Development `0.4.0+10`, source `b07e24dc95ad8f72c3e1ee4415cbbb49bac36cac`, app tree `14b056be0c23ebdd84ddedb461c1d07bdc2c5449` |
| Historical client | Rebuilt normal `0.3.0+9` from `bef67bded9e5b83437e3eb0e2ec4be6a4cfd1a64`, app tree `60b3a68b693551af5d83076547c502f69838e052`; private bundle, no store-binary equivalence claim |
| Tracking | [PR #47](https://github.com/PyBLE-dev/PyBLE/pull/47), [milestone 2](https://github.com/PyBLE-dev/PyBLE/milestone/2); agents [#44](https://github.com/PyBLE-dev/PyBLE/issues/44), app [#45](https://github.com/PyBLE-dev/PyBLE/issues/45), physical verification [#46](https://github.com/PyBLE-dev/PyBLE/issues/46) |
| Implemented | Committed snapshots, native/portable parity, capability-gated query/events, initial app synchronization, revision merge/cache and bounded refresh |
| Remaining roadmap | Directory streaming, project-aware execution, transfer status/abort, diagnostics/loss and new recovery operations remain proposed |
| Release boundary | Targeted evidence does not complete resource/workspace/recovery/provenance or full release admission; no public firmware release, store upload or PyBLE Ready award |

The first-increment scope is an implementation assumption following the
recommendation and user's request, not a separate explicit choice between this
increment and the complete roadmap. The full request is not declared complete.
October's app-only acceptance remains historical and does not qualify new firmware.

RUN_STATE omitted without a live session cannot establish idle after reconnect.
The new empty query and opt-in event carry a fixed 25-byte committed snapshot.
Accepted response handoff or autorun admission commits a run; provisional
reservations and failed response transmission do not. Ephemeral random boot
identity, run ID, revision, origin, terminal reason and flags support
reconstruction without hardware identity or program contents. Existing 24
operations retain their encodings.

Native snapshots use bounded allocation-free state and whole-message control
notification pacing. Portable updates respect the pinned VM's pending-at-jumps
boundary, with functional STOP/successor/terminal race tests. Session ownership
prevents old work targeting a new link. The app synchronizes before Ready/Running,
merges revisions, seeds late views from cache and preserves legacy fallback.
Parallel work used independent native/portable/app/integration and focused-fix
Git worktrees. Executed-firmware and full-host checkouts remain frozen.
Later firmware changes are the README and strict release-source validator;
all 72 runtime inputs compare byte-identically between `1093bab` and `b07e24d`,
including both working trees. The independent firmware audit rehashed 144
retained file bindings without a mismatch. Whole firmware trees differ only at
README.md and release_bundle.py, so do not claim whole-tree equality.

### Tracking-order deviation

Specification preceded behavior tests and implementation. Focused issues and
milestone were created after initial red/green work began, although roadmap §9
orders issue creation first. Later tracking does not retroactively satisfy that
ordering or create a waiver for future work.

## Automated verification

| Evidence | Result and boundary |
|---|---|
| Final ordinary app suite | **1,072 pass** at R5 `b07e24d`; analyzer and focused download/transport/lifecycle/editor/conformance checks pass |
| Frozen complete host suite | **2,006 tests; OK with 19 skips**, immutable `c4ac9af`; newer 17 load-probe and six roadmap-ledger tests pass independently |
| Generated runtime contracts | Six unchanged checks pass against frozen `1093bab` source, pinned MicroPython/SDK and retained four-ESP outputs |
| CI at R5 code freeze | All **36 checks pass**, including pinned goldens, Android WebView, four ESP builds and RP2; complete host job: **2,023 tests, OK with 24 skips** |
| Physical firmware artifacts | All five exact builds pass with manifests/hashes retained |
| Source gates | No-leak, DCO, import/locale/source policies, publication tests and public Markdown links pass |

The 19 host skips comprise 18 retired schema-v1 license fixtures replaced by
schema-v2 coverage and the generated-runtime class absent from the default
build path. The latter six checks then passed explicitly against real outputs.
The Linux CI host job additionally skips five Darwin-only isolation cases,
which run in the complete local macOS suite. Local golden differences reproduce
on unchanged main; no baseline was replaced,
and pinned CI goldens pass.

## Five-profile hardware matrix

All five service-filtered baseline advertisements/HELLOs reported 0.6.1 without
`run_status`. ROM/flash identities were checked against retained bindings;
a USB name alone does not identify a profile. All five now have verified full
backups and exact frozen candidate programming. Pico verifies every byte outside
the UF2 footprint; ESP verifies current ranges complementary to component writes.
Later owned file/config transactions have logical restoration receipts, without
claiming identical filesystem journal bytes relative to the original raw backup.

| Exact profile | Backup / candidate verification | Mac fragments 23/247 | Autorun / load | R5 Lenovo UI | R5 iPad UI | Actual Android ATT23/247 | Old 0.3 client, Lenovo/iPad |
|---|---|---|---|---|---|---|---|
| esp32-4mb | Full 4 MB; device component MD5 and protected ranges verified | Pass / pass | Pass / pass | Pass | Pass | Pass / pass | Pass / pass |
| esp32-s3-n16r8 | Full 16 MB; MD5/full readback SHA-256 and protected ranges verified | Pass / pass | Pass / pass | Pass | Pass | Pass / pass | Pass / pass |
| waveshare-esp32-s3-lcd-147b | Full 16 MB; MD5/full readback SHA-256 and protected ranges verified after targeted USB recovery | Pass / pass | Pass / pass | Pass | Pass | Pass / pass | Pass / Partial (recovered) |
| esp32-c3-4mb | Full 4 MB; MD5/full readback SHA-256 and protected ranges verified; candidate restored after legacy roundtrip | Pass / pass | Pass / pass | Pass | Pass | Pass / pass | Pass / pass |
| rpi-pico2-w | Full 4 MB; program footprint and unchanged remaining flash verified | Pass / pass | Pass / pass | Pass | Pass | Pass / pass | Pass / pass |

The ten Mac cases use actual ATT247 and separately record command-fragment
limits. They cover exact empty grammar, same boot/run after query-only reconnect,
STOP/idempotence, done/error terminals and VM boot rotation. They do **not**
establish actual ATT23. Android's separate central requires observed GATT and
HELLO MTU, CRC-valid 25-byte tagged events and expected two fragments at 23 / one
at 247, plus same-run reconnect, STOP, normal completion and exception. Protocol
central results remain separate from normal tablet UI rows.

All five autorun probes refuse an existing `main.py`, enabled autorun or active
program. They prove owned bytes/CRC readback, new-boot origin 3, same-run reconnect
and stopped terminal, then restore `auto_run=0`, remove only their fixture and
verify initial idle after reboot. Five load probes prove unique stdout markers,
three coherent active-run queries for both tight-loop and console-flood cases,
and owned STOP without file/config changes. Latency observations are not an SLO.

Each R5 normal UI row verifies opening the exact owned empty file without a
transfer overlay, balanced source entry, Run/console and explicit reconnect
while the same finite program continues. No new Run/upload occurs between
disconnect and recovered Running controls/cache. After Stop, clearing only the
known local fixture buffer and reopening the unchanged remote file proves
nonempty GET independently of stale editor text. Exact path/source and absence
of a transfer overlay are checked, then only the owned file is deleted, absence
verified and the link disconnected. Linked continuations preserve UI-harness
failures rather than silently promoting an interrupted attempt to a pass.

### Cross-version and restoration

Both R5 tablets pass absent-capability fallback on C3's exact original 0.6.1
application: empty/nonempty GET, Run/console/Stop and owned cleanup. The temporary
application-only swap protects current boot/table/NVS/PHY/VFS ranges. Mandatory
restoration verified the exact frozen `1093bab` application SHA-256 and protected
ranges, then runtime `0.7.0-dev.1`, `run_status=1`, initial idle and `auto_run=0`.
This is the original observer baseline, not equivalence with the separately
published v0.6.1 artifact.

Old-client rows use a fresh rebuilt historical normal app in an isolated bundle.
Android's fresh clone displayed a recovery-storage error and used its explicit
Continue without recovery action: those rows establish BLE interoperability in
volatile mode, not recovery success or store-binary equivalence. The preexisting
qualifier's pending `blocks.py` draft was untouched. The iPad clone showed no
such prompt.

Historical iPad0.3/Waveshare is **Partial (recovered)**: the first exact owned
empty-file Open stalled before any typing or Run, retaining the prior editor
document. One normal Open retry adopted the correct empty file; its guarded
Run/console/Stop/delete/absence/disconnect sequence then passed. Both receipts
remain linked; the retry does not turn the initial failure into an unqualified
pass. No wire trace was collected for that old-client failure: association with
the known historical download timing issue is an inference, not a demonstrated
firmware regression or a completed compatibility admission.

Waveshare initially had no usable ROM USB endpoint. One fixed-target USB
re-enumeration recovered the bound board, without a hub/radio reset, interface
detach or privilege escalation. ROM identity and full 16 MB backup preceded writes.
Maintained loader entry and exact programming preserved complementary ranges.
Initial runtime-discovery timeout and later successful re-enumeration/HELLO
remain retained; no second USB reset or extra flash write occurred. The earlier
physical BOOT/replug request became unnecessary after software recovery.

## Artifact and receipt identities

Private R5 manifests bind normal entry points, 366 tracked app files and four
reviewed identity/display overrides. Both real platform builds, strict iOS
signature verification and isolated installations pass; store apps are preserved.

| Artifact / receipt | SHA-256 |
|---|---|
| Four-variant ESP build receipt | `aa56c6526ec87ebd963d8cb9db86b8ab9e0d3e2069b1fc08ef500f74a45a7a1e` |
| Pico artifact receipt | `2b715f8af5b6e73222f4364278ecca25485a5f1c24ebde4bf5be6948ecb01fb1` |
| Pico firmware.bin, 865,148 bytes | `dc4041d956768b38e7e918d8679a56fb71c9dfa7a692070f0a36041ff8228caf` |
| Pico UF2 | `dcb7cc5e25724e65826dbcc7a59028d25dcd6e991c71db7a009d7fbb84bcff29` |
| R5 Android APK, private `dev.pyble.firmwarequalification5` | `36872f2a0c25ba18da388ed8b22c83636b96096a0c350613dc215b18281be38e` |
| R5 signed iOS app archive, same bundle | `4b727d6708450a67e324bcbd4cb8d8844f58e91fb6f0f0a1ad11c7a85b9166bc` |
| C3 mandatory candidate-restore receipt | `2f0e7f2146d8c5a5f2a89c426cd401a1192e94ef5e883d66834a8716973889aa` |
| Waveshare full-backup receipt | `25478f4c37c2c89d250eeae1f7baf74e190cabd396d0d868bc4a411575c029e2` |
| Waveshare exact-programming receipt | `36d9efe0003542b0c1d5ef7863ec6c81619c91950297d9d9cb529e3ecf7b5b74` |
| Final Android R5 result index, all five profiles / four evidence planes / owned-app cleanup | `768edafe87d7733607cc31924c6aef6f03b91713b9adb2191d0a04f4938ce8ad` |
| Final iPad result index, five R5 passes / four old-client passes + one Partial | `5b3593e90e250c8c7dd947f5332f453cbd6d72744fb5037fd2acab80cd3fa7b8` |
| Independent five-profile firmware audit (144 rehashed bindings, 72 runtime inputs) | `84b9c8839d3c92dc3ddb318b6cd8a861b8446eed8859a6eff71e0731e3f43f2b` |
| Waveshare runtime HELLO proof | `1c080f6e00a0e39bc7136b07c806068a91427cd76db88a2eced3a7dada2459e6` |

Earlier functional/autorun receipts lack an embedded bench SHA: retain invocations,
unchanged harness content and source history, without inventing an embedded
field afterward. Load receipts also record the bench commit. Classic has actual
device component MD5 but no independent full-component SHA-256 readback file;
other ESP profiles retain that stronger independent readback. R1–R4 remain
exact-source history and are not silently promoted to R5 evidence.

## Failures retained and corrected

| Finding | Correction and evidence |
|---|---|
| Retired automatic status failure could disconnect a successor | Generation guard; `[red] 7c1c6bf` → `[green] bb470fb` |
| Rich editor duplicated normally typed closing delimiters | Spec `2d25677`, red `75fa6d6` → green `c4ac9af`; disable optional insertion, retain indentation/Tab; native-input tests and physical balanced buffers |
| Actual ATT23 RUN/STATUS fragments interleaved | Spec `69c8192`, red `90a47af` → green `a8b0c6d`; bounded whole-frame FIFO, concurrent response waits, original deadlines, physical-write ownership and generation retirement; original partially successful attempt remains failed |
| R4 empty GET lost END before final BEGIN write ACK | Spec `d31d81f`, red `85f9ce2` → green `b07e24d`; validated download context at ordered response acceptance, no pre-BEGIN buffering, synchronous receive FIFO, early-error/reentrancy/strict grammar/CRC tests, physical R5 empty/nonempty GET |
| Android initial pre-MTU/HELLO GATT133; C3 query-only reconnect GATT133 after accepted RUN | Retain negatives; no source/MTU workaround or blind accepted-RUN retry. Independent C3 ownership/idle preflight confirmed natural completion before normal reboot and a fresh standalone pass. A Classic attempt had competing foreground runners; retain invalid setup and subsequent exclusive-runner pass |
| Pico bench confused command cap with negotiated MTU | Red/green correction records both separately; no invented actual ATT23 result |
| Missing pinned dependencies/stale host source/version checks | Initialize exact dependencies; strict explicit source allowlist and source-bound version validation; preserve failures and frozen final results |
| Moving HEAD invalidated a source-bound host run | Keep unsuitable run; regression passes separately and complete final suite uses immutable checkout |
| Automation text/focus/navigation/clear failures | Keep failed guards and linked continuations; exact source/path before Run or accepted GET, owned cleanup; no product pass inferred from harness failure |
| Updated roadmap checkbox selection | Six ledger tests pass; future unselected approvals stay unchecked |

Raw backups, binaries, signing material, captures and machine identities remain
in ignored `local/v070/`. Backup directories are 0700 and raw images 0600.
Owned remote fixtures/configuration are cleaned with receipts; preexisting
apps/drafts and the user's stash remain preserved. Final R5 preview apps remain
installed. The iPad preview retains only its generated local test draft; the
normal offline recovery sheet is read-only and no forced storage reset was used.
Cleanup inventories prove removal of only this task's obsolete 23 Android and
five iPad app installations; every outside app and preexisting helper remains.
All five boards and both tablets are released, with explicit BLE disconnects.
Store reviews, Android audience/CDM, participant outcomes and full v0.7 release
admission remain separate work.

The C3 historical Android UI receipt omits its own source/tree fields and is
bound through the enclosing historical-artifact and final index context; do not
claim self-contained source provenance for that individual receipt.

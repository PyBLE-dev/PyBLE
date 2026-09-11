<!-- SPDX-License-Identifier: MIT -->

# Firmware v0.6.1 five-board engineering checks — 2026-09-06

Status: **Archived engineering chronology. Automated final-candidate qualification was stopped at the owner's request; v0.6.1 was subsequently published on the owner's confirmation.**
Last updated: **2026-09-11**.

The progress statements below describe their historical observation times, not
current publication status. See the [publication record](firmware-v0.6.1-publication-2026-09-11.md)
and [complete website deployment](website/site-v061-consistency-2026-09-11.md).
Incomplete or failed automated evidence remains unchanged; owner confirmation
does not retroactively turn it into a passing automated result.

## Scope and exact inputs

The maintainer resumed the paused five-board qualification with VPN
disconnected and both Lenovo Android and iPad available. The existing explicit
authorization for disposable-media qualification covers backup followed by
full-flash erase. Owner flash backups and all unsuccessful attempts are retained
privately; no raw captures, firmware binaries, or device identifiers belong in
this document or Git.

The historical physical checks below use the clean qualification source
`f0b05f4c0e7a0d07a51e00ca104a0b716d1e4eb6` and the already admitted, reproducible
v0.6.1 baseline inputs. Those inputs are **not** a protected final candidate.
The earlier Lenovo-only application-preservation tests remain separate
[engineering evidence](firmware-v0.6.1-lenovo-engineering-2026-09-05.md).

## Historical physical progress before the observer correction

| Exact profile | Installation/readback | Live BLE identity smoke |
| --- | --- | --- |
| `esp32-4mb` | Passed: exact image and complete 4 MiB readback before first boot | Passed: v0.6.1, MTU 247, chunk 229, window 8 |
| `esp32-s3-n16r8` | Passed: exact image and complete 16 MiB erased-tail proof before first boot | Passed on a separately retained second smoke attempt: v0.6.1, MTU 247, chunk 229, window 8 |
| `waveshare-esp32-s3-lcd-147b` | Full erase and firmware write/hash verified; final full readback interrupted by USB disappearance, so installation result remains failed | Passed after rediscovery: v0.6.1, MTU 247, chunk 229, window 8 |
| `esp32-c3-4mb` | Passed: exact image and complete 4 MiB readback before first boot | Passed: v0.6.1, MTU 247, chunk 229, window 8 |
| `rpi-pico2-w` | Passed: exact UF2 payload, documented loader padding, and complete 4 MiB readback before first boot | Passed: v0.6.1, MTU 247, chunk 229, window 4 |

A passing installation or smoke test is not an OI-1 baseline fragment,
seven-scenario hardening result, provisioning receipt, or physical app-platform
completion. No final iPad/Android qualification row has been emitted.

The generic S3's first eight-second service-filtered scan missed its
advertisement. A later fresh scan observed it, a passive UART capture showed a
healthy v0.6.1 boot without a commanded reset, and a distinct second smoke
attempt passed. The failed first attempt is retained; its cause has not been
established, and the retry is not a substitute for the frozen no-retry OI-1
timing workload.

Waveshare's two original 16 MiB backups match. The maintained loader completed
the exact 1,798,416-byte firmware write and reported its data hash verified.
The subsequent whole-flash read lost the USB endpoint, and the attempted
cleanup reset could not reach it. This is not a complete whole-flash
before-first-boot proof. The unsuccessful result and logs are retained, with
no automatic re-erase and no assumed cause for the USB loss.
Its subsequent service advertisement and full maintained HELLO/DEVICE_INFO/INFO
smoke passed on v0.6.1. That runtime success does not repair or replace the
interrupted full-readback evidence.

Read-only device metadata identifies the available Lenovo capture app as
`0.2.0+5` and the iPad app as `0.2.0+6`. Availability and installed version alone
do not establish a passing app-platform test. Neither app was reinstalled.

Pico's reviewed loader footprint includes the pinned picotool's explicit
sector-aligned zero padding: 859,904 UF2 payload bytes plus 256 zero bytes,
followed by erased bytes through the end of flash. This behavior was verified
against the [pinned upstream loader source](https://github.com/raspberrypi/picotool/blob/6f6458d792b93685a11423b244a585eaa99eafcf/main.cpp#L5299-L5308),
not assumed from a failed comparison. The original stricter comparison failure
and the fresh, corrected full readback remain separate private records.

## Release-test observability correction

The [frozen workspace receipt contract](../specifications/firmware/specs.md)
requires physically acquired first-boot format/remount counts and zero write
operations during incompatible-media refusal. The historical baseline's shared
`pyble_workspace` helper and five boot overlays expose neither retained counts
nor a complete measurement interface. The actual builds do not enable the
upstream trace/counter alternatives inspected during this audit.

The receipt-creation tool validates supplied canonical observations; it does
not acquire those facts from a board. An accessible filesystem after a blank
boot does not distinguish one format from repeated formats. Unchanged flash
bytes do not rule out idempotent writes. Therefore those observations must not
be converted into invented operation counters or passing receipts.

The maintainer subsequently authorized continuous completion. The isolated
`release/v0.6.1-qualification` worktree now contains specification-first,
red-to-green work on a bounded retained boot observer in PyBLE-authored code,
all five boot overlays, actual flash/response acquisition, and complete
private evidence validation. The erased scan's status guard also now rejects
boolean `False` and noninteger values that compare equal to zero. No upstream
source or release gate has been weakened.

Focused observer/read-status tests pass 44 methods; all 77 existing firmware
shell-test files and the source checks pass during integration. Hardware
adapter regression/review is complete: core 28, Pico 20, acquisition 19 and
collector 13 focused tests pass. The measured-observer implementation is signed
commit `8dd3cbac3f4497803af598b9761e424af4ed3351`; a one-line finalization
test-fixture correction is signed commit
`96497b9cf642ab2078842ce8a321c3c84b6714b2`. The qualification checkout is clean
and frozen at the latter source for new builds.

The first complete host run executed 1,892 tests with two fixture errors and
19 skips. Both errors came from old synthetic finalization fixtures missing
the newly required workspace evidence closure; the focused correction passes
all three affected result-set tests. The fresh full run **passed all 1,892
tests with 19 documented skips** in 1,137.103 seconds. Eighteen skipped tests
are superseded schema-v1 fixtures covered by the active schema-v2 suites; the
generated-runtime class was separately run against both complete build roots,
passing all six tests for each root. One
intermediate rerun was explicitly interrupted after a restrictive process
umask changed synthetic pinned-package modes; an unchanged focused test passes
under the fixture's expected umask. No production permission check was relaxed.

Both fresh five-target builds completed, including their generated-runtime
checks. All five install artifacts are byte-identical across the independent
roots. Maintained baseline-input admission and the private installer's all-five
source/tool/input checks passed. All five new-source baseline installations now
pass: fresh full-chip backup, complete erased-byte proof, exact admitted image
write, full-chip readback before first boot, one runtime reset/boot request and
adapter cleanup. These are pre-policy baseline bytes, not a final candidate.

| New-source profile | Full-flash installation | Live retained boot observer |
| --- | --- | --- |
| `esp32-4mb` | Passed | Passed; 2 MiB workspace |
| `esp32-s3-n16r8` | Passed | Passed; 14,614,528-byte workspace |
| `waveshare-esp32-s3-lcd-147b` | Passed on separately retained attempt 02 | Healthy first-boot record acquired over USB; retained BLE connection ended after closing tablet PyBLE sessions |
| `esp32-c3-4mb` | Passed | Passed; 2 MiB workspace |
| `rpi-pico2-w` | Passed on separately retained attempt 02 | Passed; 2.5 MiB workspace |

Each passing live check independently verified the exact silicon identity,
fresh challenge, attached workspace and a complete fault-free retained
first-boot record: one format/completion and one remount/completion.
The four BLE checks verified v0.6.1 HELLO; Waveshare's USB fallback verified
the v0.6.1 runtime banner, not a successful BLE HELLO.
These engineering getter checks do not create final workspace receipts.

Waveshare and Pico attempt 01 stopped at BLE advertisement discovery before
any flash access, erase, write or reboot. A retained 20-second passive scan did
not establish their presence or explain the absence; narrowly scoped Lenovo
inspection did not prove an active connection. After the maintainer confirmed
manual bootloader entry, actual USB/loader identity was checked independently
before each distinct attempt 02. No failed attempt was overwritten or promoted.
The new Waveshare readback success does not repair its historical failed run.
Its expected application USB identity later reappeared after a period of
absence. A distinct Mac BLE lookup still timed out before connecting. USB then
independently confirmed the exact silicon identity and v0.6.1 board banner.
The first long diagnostic print was truncated and remains a failed acquisition.
A fresh readout using bounded, paced hexadecimal chunks yielded complete
nonce/length/offset-checked diagnostic bytes without rebooting or changing
firmware. The retained workspace record proves erased media, one completed
format/remount, attached filesystem, two program/two erase calls and no fault,
overflow or recovery. Its workspace has 14,614,528 bytes.

The same Waveshare readout reports BLE ready and the retained splash sequence
through frame-show, resources-released and backlight-high, returning true.
The maintainer first reported a blank LCD, then explicitly confirmed that the
Waveshare device showed the correct information on its LCD. This confirms the
current visible display recovered, without another flash write. It is not the
complete repeated-reboot/independent-QR-scan display qualification gate, which
remains incomplete. The maintainer's original photograph subsequently showed
the v0.6.1 splash, green BLE READY indicator and installation QR. Apple Vision
decoded the unchanged JPEG's QR as `https://pyble.dev/app`; a different decoder's
earlier non-decode remains retained. This is photo-based engineering evidence,
not a replacement for the final independent-device QR/reboot gate.

Live diagnostic snapshots then established an active physical BLE epoch,
despite the qualification apps showing logical Disconnected state. A fresh
snapshot after narrowly closing the two iPad PyBLE processes and the Lenovo
qualification process showed that same epoch ended and no active connection.
No Bluetooth-wide reset, board reboot, app-data clearing or firmware write was
used. This establishes physical closure after app-process termination, not a
passing ordinary UI Disconnect test or identification of the individual peer.
Earlier discovery failures remain failed observations. A separate 25-second
Mac scan after closure observed all five exact bound identifiers, with no
overflow, connection requests or controller changes; scanning stopped cleanly.
A separate, read-only
generic-S3 adapter commissioning run retained a complete 16 MiB read with device
MD5 checks before and after. Immutable old firmware matched; differences in
mutable NVS were recorded separately. One reset returned normal runtime and the
serial descriptors were closed. This does not qualify the new build.

These host checks and build results do not
qualify changed firmware bytes; a clean source freeze, fresh baseline/final
builds, OI-1 and hardening/provisioning/recovery gates, and all ten physical
app-platform rows remain required.

A separate test-only iPad automation runner successfully performed one
foreground-only inspection of the installed official app after an earlier
setup timeout. It captured the disconnected PyBLE screen and accessibility
tree without tapping controls; PyBLE itself remains 0.2.0+6, not reinstalled.
This establishes a usable automation route, not a final app-platform pass.
Raw artifacts remain private. No physical power-cycle, visual confirmation,
wire timing, or candidate result has been inferred from these checks.

A later iPad connect-inspection pilot verified the actual About version but
failed a navigation-settle guard before scanning or connecting. The outgoing
About accessibility tree was still present after Back. Its failure evidence is
retained; a private test-harness wait is being corrected without changing the
official app. The unmodified app's screen cannot prove STOP response ordering
or the frozen 500 ms wire bound. A separately identified qualification-only
real-app tracing derivative has therefore been prepared and tested. Its default
suite passes 921 tests, with three enabled-only tests separately covered in a
19-test enabled subset. The reviewed iOS and clean Android packages have
distinct qualification-only application identifiers; at that preparation stage
neither was installed or counted as a passing physical-app result. An Android incremental-packaging
mismatch was caught before installation, retained as failed audit evidence and
corrected with a clean build whose packaged AOT matches the fresh intermediates.

Root subsequently independently rechecked the reviewed artifacts, installed the
separate `PyBLE Qual` copies on both physical tablets and launched them. The
official iPad app's queried identity/version/install URL remained exactly
unchanged; Lenovo's installed qualification APK was pulled back and matched the
reviewed package byte-for-byte. Lenovo About reports 0.2.0 (6), and the private
trace controls render correctly. No trace was armed or program run by these
app pilots. iPad's minimal no-taps screen/prompt inspection passed one test
in 1.342 seconds, with both queried app identities unchanged. It showed
Disconnected, Bluetooth On, Scan Idle and five board entries; the pilot did not
initiate the scan, and the list is not proof of a current board connection.
Its raw screenshot framing remains imperfect and is not publication-ready.
No system permission
has been automatically accepted by the automation.

A source/evidence review corrected an unnecessary prerequisite in the private
plan: the frozen bench inventory explicitly accepts electronically identified
generic ESP boards using retained esptool chip/revision observations. Those
facts and exact-device installation guards already exist, so new carrier photos
are not required to begin their OI baseline runs. This does not waive actual
physical power/reset observations or C3's separate final board/pin confirmation.

Independent review caught an offline analyzer mismatch with the ordinary app's
actual Run callback → verified upload → file RUN sequence. A separate private,
specification-first red/green correction admits only the exact UI-owned verified
upload before RUN, preserving all timing, source, lifecycle and unrelated-control
guards. The corrected analyzer passes 33 Python test groups; a host test using
the actual RunController/ProgramActions confirms upload-before-RUN behavior.
These are test-tool results, not hardware qualification.

A private exact-file app trace collector is also prepared. It restricts reads
to the identified qualification package and actual UI-exported filename,
preserves two unchanged byte copies and checks source, installation metadata,
external bindings and the strict analyzer. Review reproduced a timeout cleanup
gap when a subprocess leader exited before its descendant. A narrow correction
terminates that owned process group on failure and preserves the original raw
failure evidence. All 31 temporary-fixture tests pass, including the parent's
independent rerun. No actual app trace was collected by this preparation.

After the navigation fix, a distinct C3 connect-inspection test passed in the
official iPad app: actual Ready state, firmware 0.6.1 and the expected chip were
visible, with no file/editor/Run actions. A subsequent single UI Disconnect
test also passed. **That cleanup proved logical UI detachment, not physical
BLE closure.** Source inspection and a separate HELLO-ready host diagnostic
confirm that `PbleConnection.dispose()` never calls its owned link's
`disconnect()`; the recording link remained connected. The user has been asked
whether to fix this app issue in a separate branch. No application behavior fix
or complete disconnect/reconnect qualification is claimed. Private trace close
events must preserve this distinction.

## Evidence and publication boundaries

The first maintained OI baseline runs on the frozen observer source now retain
actual failed hardware results:

| Profile | Controlled reset / HELLO | Transfer workload | Overall baseline |
| --- | --- | --- | --- |
| `esp32-4mb` | All 10 acquired; advertisement latency 1,124–1,450 ms | Physical BLE link lost during the first 64 KiB PUT's DATA phase | Failed; no fragment emitted |
| `esp32-s3-n16r8` | All 10 acquired; heap and settled-link facts acquired | Physical BLE link lost during the first 64 KiB PUT's DATA phase | Failed; no fragment emitted |

Both runs reached successful directory creation and PUT_BEGIN before the DATA
failure. The backend's cleared service cache and nonconnected peripheral state
establish connection loss, not an omitted initial service-discovery operation.
The generic S3 cleanup also attempted its retained-link probe on the lost link;
the complete chained traceback remains retained. Neither raw log establishes
the underlying firmware reset, controller, or radio cause. No failed sample is
trimmed, replaced, or promoted into passing evidence. Neither run reached its
final physical power-cycle observation.

A separate single-transfer engineering diagnostic subsequently captured the
cause without changing firmware. It independently checked the exact live
silicon identity and flash size, then retained original UART, CoreBluetooth
disconnect, DATA-command and ACK observations. Eight complete DATA sends used
command ID zero; no ACK arrived. UART reported local-host termination
`0x216`, with zero TX mbuf starvation and no subsequent panic/reboot observed
in the retained capture. CoreBluetooth reported peripheral disconnect.

The original maintained benchmark hard-codes ID zero for valid PUT_DATA traffic, whereas
[PBLE/1](../specifications/protocol.md) requires command IDs 1–255.
The actual firmware wire reducer drops zero-ID commands as violations and
terminates the exact session on the eighth. This explains the captured eight
chunks/no ACK/local termination; relaxing firmware admission is not the fix.
The five affected valid-transfer helpers are now corrected in the separate
host-tool checkout at signed commit
`6f70155f596f83e47cb08157927810b261eb7c42`. All 301 affected host checks pass,
including actual sender frames checked by the unchanged compiled native wire
admission code. Independent review and the parent's seven-test rerun pass.
Data and retry commands use the caller's shared nonzero-ID allocator; timing,
payloads, window/ACK behavior and intentional malformed-ID tests are unchanged.
Neither the diagnosis nor a later corrected run repairs the failed records.

A fresh complete classic ESP32 baseline has started with that clean, frozen
host executor. The firmware proof checkout remains clean at `96497b9`; its
admitted images and actual installations are unchanged. The baseline contract
binds firmware/build provenance to the proof checkout, not to the host helper's
HEAD, so this host-only correction does not require another baseline rebuild.
Separate private executor source and file-hash records preserve that distinction.
The fresh classic run completed all ten reset/HELLO checks (1,130–1,449 ms),
settled-link capture, all five 64 KiB roundtrips and all twenty 16 KiB reliability
transfers. Canonical PUT goodput is 7,356–7,612 bytes/s; GET goodput is 14,266–14,756
bytes/s. All payloads verified, with zero retransmissions, integrity failures,
failed statuses or unexpected disconnects. The operator subsequently confirmed
actual power removal and reconnection; the maintained silence/fresh-advertisement
check passed, the complete run exited zero, and its baseline fragment was emitted.
Its raw-log digest and before/after executor records match. The same-session
terminal TX-mbuf starvation count is 5,371; it is retained as the contract's
report-only quantity, not concealed or used to replace measured goodput.

The generic S3 and C3 then each completed a separate full automated workload
using the same frozen executor and unchanged exact-profile installed images.
At 06:05 UTC all three runs were waiting at their first final physical-power-off
prompt. All three subsequently completed their operator-confirmed physical
power cycles, with actual silence and fresh advertisements checked:

| Profile | 10 reset samples, range | 5 PUT/GET roundtrips | PUT / GET goodput range, bytes/s | Reliability | Final physical cycle |
| --- | --- | --- | --- | --- | --- |
| `esp32-4mb` | 1,130–1,449 ms | All verified | 7,356–7,612 / 14,266–14,756 | 20/20 verified | Passed; complete baseline emitted |
| `esp32-s3-n16r8` | 853–1,516 ms | All verified | 14,278–20,604 / 28,331–35,790 | 20/20 verified | Passed; complete baseline emitted |
| `esp32-c3-4mb` | 529–1,181 ms | All verified | 12,628–13,403 / 19,147–20,422 | 20/20 verified | Passed; complete baseline emitted |
| `rpi-pico2-w` | 13–50 ms, operator-acknowledgement proxy | All verified | 13,910–14,374 / 7,182–7,327 | 20/20 verified | Passed; complete baseline emitted |
| `waveshare-esp32-s3-lcd-147b` | 8–21 ms, operator-acknowledgement proxy | All verified | 14,185–14,657 / 27,633–28,353 | 20/20 verified | Passed in the separate fresh attempt; complete baseline emitted |

Every row retains all sixteen heap snapshots, zero retransmissions/rewinds,
zero integrity failures, zero failed statuses and zero unexpected disconnects.
The additional same-session report-only starvation counts are 2,854 (S3) and
3,870 (C3). All five complete baseline fragments have now been emitted; this
does not constitute final-candidate qualification. Actual disconnect,
sealed link facts, the first prompt and closed USB endpoints were checked before
the next board started. That first prompt holds no active scan or measured
timer; its following reconnect prompt would hold a scanner and cannot be shared.
No physical answer has been supplied on the operator's behalf. Waveshare and
Pico full OI runs require the documented manual reset/power sequence. Waveshare
completed all ten actual operator-held/released RESET samples and their HELLO,
heap and link-settlement checks. Its recorded 10–47 ms values use the frozen
operator-acknowledgement-to-next-advertisement proxy, not the physical switch
edge or physical boot time. No native-USB reset substitute was used.

That Wave attempt then **failed its first 64 KiB GET**, timing out after
39,846 verified bytes. It emitted no roundtrip, reliability, final power-cycle,
completion or baseline fragment. All 44 raw events and its exit-one result
remain retained; unchanged before/after executor records do not turn the failed
workload into a pass. Neither host RX loss, a filesystem read exception nor
firmware TX backpressure has yet been established as the cause. The board and
owned test file were preserved for the separate read-only diagnostic below.

Pico completed all ten actual operator-confirmed reset samples, all five
64 KiB PUT/GET roundtrips and all twenty 16 KiB reliability files. Its retained
events show zero retransmissions, rewinds, integrity failures, failed statuses
or unexpected disconnects. The operator separately confirmed final all-power-off
and normal power-on, after which the runner recorded the physical-cycle pass,
emitted the complete baseline and exited zero. Its 13–50 ms reset values use the
same explicitly limited acknowledgement-to-callback proxy, not physical boot
times. Independent host audit confirmed exact replay of all 58 raw events,
the complete observation, source/executor/build/install pins, UF2/raw-image
agreement and derived thresholds. Final qualification and publication remain
pending.

A separate, explicitly non-qualification Wave diagnostic subsequently read
the preserved failed-transfer file on one connection without resetting,
reflashing or writing/deleting files. Exact STAT size/CRC and the complete
65,536-byte GET passed in approximately 2.01 seconds, with no retransmissions.
Before/after identity and boot observations agreed; raw notifications,
reassembly observations and passive UART bytes were retained, and BLE/USB
cleanup completed without errors or capture overflow. The preceding ended
link reported 536 mbuf-starvation observations; the diagnostic link reported
267 after GET. These report-only counters do not establish the cause of the
original interruption. The retained native USB output is incomplete Python
stdout, not low-level firmware error coverage: this build sends ESP-IDF logs
to UART0 and hardware USB Serial/JTAG, while the connected application endpoint
uses TinyUSB CDC. Missing native USB error text therefore cannot exclude an
earlier firmware error. This successful engineering read neither
repairs the failed baseline nor qualifies Wave for release. It preceded the
bounded engineering series and separate complete baseline acquisition below.

One separately reviewed, bounded Wave engineering sequence then completed
ten fresh 64 KiB PUT/GET roundtrips on a single connection. The original
maintained helper's PUT, STAT verification and GET sequence, window, chunk,
timeouts and internal retransmission behavior were unchanged. A fresh,
previously absent nonce-owned directory isolated all temporary files from the
original failed-run file. Each transfer verified all 65,536 bytes in both
directions, with zero reported retransmissions or rewinds. PUT durations were
approximately 4.89–5.18 seconds; GET durations were 2.93–3.31 seconds. Same-boot
identity and settled link facts were retained before/after; the link ended
only during explicit host cleanup. The capture contains 17,602 records and
reports no overflow, observation fault or cleanup error. All ten successfully
verified generated files were removed by the unchanged helper; the original
failed-run file was untouched and the isolated empty directory remains.

The diagnostic driver itself received a prelaunch two-test red/green correction:
recording a command-start event must not exhaust the trace and still allow an
unrecorded backend write. Both parent and independent reviewer passed all
eleven host guards on the corrected driver before its single hardware run.
This private host-only correction changed no firmware or maintained helper.

These engineering successes do not explain the original interruption or supply
any missing baseline samples. A separately planned, complete fresh Wave
baseline is permitted by the frozen attempt rules. One such new run has now
completed all ten actual operator-held/released RESET samples, all five
64 KiB roundtrips and all twenty 16 KiB reliability files. It records zero
retransmissions, rewinds, integrity failures, failed statuses or unexpected
disconnects, and retains its measured link facts. The operator confirmed final
all-power-off at 10:15:45 UTC and reconnect at 10:24:10 UTC. The runner then
recorded physical-cycle success, emitted the complete Wave fragment and exited
zero. Independent audit checked all 58 raw events, exact replay, build/install
and source/executor pins, and thresholds. None of the failed attempt's samples
or engineering diagnostic transfers were reused. The earlier intermittent
failure remains retained and its cause has not been established.

At 10:45:42 UTC, the maintained assembler admitted all five complete fragments
on clean proof source `96497b9cf642ab2078842ce8a321c3c84b6714b2`, producing
`docs/validation/firmware/oi1/96497b9cf642ab2078842ce8a321c3c84b6714b2.json`
and mechanically updating `firmware/qualification/oi1-gates.json` in the
separate qualification worktree. The baseline SHA256 is
`007e19f0c0281801a3c065f01742ba9606e340bce07b5e67920f036cea375c76`.
The fixed product transfer/reset limits and derivation rules are unchanged;
resource limits derive from these newly measured firmware images. Review and
host tests precede committing this policy and freezing the combined final source.

The maintainer explicitly approved the separate App Disconnect lifecycle fix.
Root reviewed and accepted clean source
`4f7cdce1752dc45e30b13a1d9b2544009e92e0fd`: 922 author full-suite Flutter tests,
44 independently selected tests and 25 root lifecycle tests passed, with clean
analysis. A fresh isolated tracing derivative is being prepared from that exact
source; neither tablet has received the new artifact yet. Ordinary Android/iPad
disconnect/reconnect qualification is not complete. These baselines and host
tests are not final release evidence; publication remains gated on the full
final-candidate evidence set.

The separate native-USB output correction has completed specification-first,
signed red/green work through `6ff052b`, with 185 affected host test methods
passing and two independent reviews. It emits the same device-generated
observation line using bounded paced output, preserving raw bytes, identity,
nonce, deadlines, control-line policy and refusal behavior. It changes no
firmware image or app source and still requires final physical acquisition.

A separate Wave-only healthy USB diagnostic subsequently exercised the exact
committed native-output emitter on hardware. The parent read the complete
private diagnostic and reran all eight host guards before its single physical
execution. Exact board identity, installed-image/source bindings and the loaded
frozen package's v0.6.1 version were checked. The unmodified paced emitter
returned a complete 742-byte raw transcript and one fresh-nonce, healthy attached
boot record with no fault or overflow. The boot ID agrees with the earlier
retained record. No reset, flash write, configuration change, candidate phase
or refused-media state was manufactured. This verifies healthy Wave USB output,
not final refused-media qualification. Healthy Pico was deliberately not probed
through USB REPL: its running supervisor owns that execution path.

Private acquisition scripts, guard tests, backups, readbacks, failures, and
results are retained below the ignored
`local/qualification/v0.6.1-20260905/` workspace. The resumed run is indexed by
`resume-20260906-Z3M4lD/RESUME.md` and its workspace-observability audit.

## Final source and updated private app checks

The independently measured baseline and mechanically derived policy have now
been integrated with the reviewed host-acquisition and App Disconnect fixes.
The separate final-candidate worktree is clean at
`6cc74e2101d4733a3abc69cfec081f6e2836fd07`. Seven signed, test-only integration
commits align active-policy and completion fixtures with the exact measured
baseline; historical fixtures and fixed product limits remain intact. The
initial failed integration run is retained, not relabeled as passing.

The complete final-source host run passed: 1,924 tests in 1,077.321 seconds,
with 19 documented skips. Eighteen are superseded license fixtures; the
generated-runtime class must separately pass against each new build matrix.
All 77 firmware shell-test files also passed, as did the standalone clean-room,
license-header and patch-policy gates. Both complete five-profile build matrices
have since passed, as have all six generated-runtime tests in each root without
skips and the maintained five-profile reproducibility comparison.

The actual offline license audit then stopped because its RP2 build-driver
parser rejected the current script: it accepted uppercase-only variable names
and incorrectly included the later pinned offline CMake configuration in the
`unset` variable list. A separate signed specification/red/green correction
accepts case-sensitive shell identifiers and validates that configuration as
an exact, separate block. Missing scrub coverage, duplicate names, malformed
continuations, injected commands and changed offline settings remain rejected;
the actual checked-in driver now reaches the next observer stage. All 31 Arm
closure tests pass independently. The firmware and build driver are unchanged.
The correction is being independently reviewed before a clearly labeled
diagnostic audit of the preserved builds. Final evidence will require a new
clean source freeze, fresh build matrices and a successful audit; the earlier
failed audit will not be overwritten or relabeled.

The separate diagnostic audit passed the corrected parser boundary, then
failed while looking up `pyble_workspace.py` in the generated ESP board
snapshot. The retained file exists under the board's `pyble/` directory and
matches the reviewed canonical source byte-for-byte. The reconstruction loop
instead looks at the board root for this flat frozen-module destination.
That distinct source-to-copy mapping defect is being corrected separately;
the unsuccessful diagnostic and its explicitly different tool/build-source
identities remain retained. No final source freeze or new build has followed it.

The reviewed production App source also passed its full 922-test suite and
static analysis. A new, separately identified tracing derivative was built
from the accepted Disconnect fix, audited and installed as private
`PyBLE Qual` version 0.2.0 (7) on both tablets. Lenovo's installed APK was read
back and matched the admitted artifact exactly. Official apps were preserved:
the current exact package queries show Lenovo 0.1.0 (4) and iPad 0.2.0 (6).
The earlier Lenovo 0.2.0+5 statement above does not establish the current
official package identity; no official app was changed by this update.

Fresh no-taps inspections of both private apps succeeded and showed
Disconnected, Bluetooth On and Scan Idle, without a permission prompt or
board operation. The iPad inspection passed one actual test in 2.663 seconds;
its screenshot still has framing limitations and is not suitable for public
tutorial use. No trace has been armed or exported by these new app checks.
The private trace collector's 41 host tests pass, including exact installed-app
identity and rejection before copying on an incorrect APK hash.

The subsequent iPad engineering lifecycle test passed in 22.591 seconds. It
verified the actual build-7 About screen, connected to the exact generic S3,
used ordinary Disconnect, connected to that same board again and disconnected
normally once more. Both connections showed the expected v0.6.1 identity and
idle controls; no files, programs or trace controls were touched. The scoped
captures and unchanged installed-app identities are retained. This functional
UI result is not independent radio-event evidence or a final-candidate row.

The equivalent Lenovo pilot stopped before any tap or board connection because
the private app was already scanning, contrary to its idle setup precondition.
Its failed setup and actual screen observations remain retained. Source review
finds no automatic scan-start hook, but the evidence does not identify who or
what initiated that scan. No firmware failure or passing Lenovo row is inferred.

A separately reviewed setup operation then used one ordinary Stop scan action
and verified Disconnected, Bluetooth On and Scan Idle. A fresh attempt of the
unchanged Lenovo lifecycle test passed all eight planned UI actions: actual
build-7 About verification, two exact generic-S3 connections and two ordinary
disconnects. Before/after installed-app identities and source guards agree.
The original failed setup is retained. This is an engineering functional pass,
not a final-candidate or independent physical-radio receipt.

A separate iPad helper for ordinary file creation, editing, saving and exact
readback has built successfully and passed 19 host guards. The preflight review
corrected two helper assumptions: the compact iOS dirty indicator includes both
its accessibility label and tooltip, and a new folder's listing settles after
its path changes. The planned pilot uses only a fresh nonce-owned directory and
two retained test files, without Run, Stop, trace, deletion or owner-document
replacement. Its first physical execution reached the exact S3 and entered the
new folder name, but stopped before pressing Create because the on-screen
keyboard covered the dialog action. The authored capture shows the single
enabled button behind the keyboard; no folder or file was created. The failed
attempt and unchanged before/after app metadata are retained.

A fresh helper adds a normal, uniquely identified Hide keyboard action before
Create, with an unchanged-name check before and after. Six actual-capture and
scope regressions pass independently. A separately gated setup will cancel only
the exact known unsubmitted dialog and disconnect; it is not automatic failure
cleanup or a passing file-operation result. Neither that setup nor the corrected
full pilot has run yet. Select All and exact edit/save/readback remain physically
uncommissioned.

The VPS's existing password-protected candidate site was checked read-only;
anonymous page and firmware requests are denied. Its old candidate and the
public site have not been replaced. There is still no new protected final
candidate, release tag, passing final receipt, GitHub publication or website
deployment from this run. Public `/flash` and `/learn` are unchanged.

## September 11 resume

The maintainer explicitly resumed the September 6 pause. Read-only checks found
all five board USB interfaces and both tablets available. Their current firmware
and UI state are not inferred from their availability or from five-day-old
observations. Both exact iPad app metadata records still agree with the retained
admissions. The fresh no-tap iPad inspection subsequently stopped in Xcode's
automation startup: the runner launched, but timed out enabling automation
before any actual test began. It produced zero executed tests and no screen
attachments. This is not an App or firmware test failure, nor evidence of the
current dialog state. No dialog cancellation or board action followed; the
maintainer was asked to check the iPad screen and any automation prompt.

The initial isolated final source was clean at `6cc74e2`. Both complete build matrices,
all ten source-provenance records and the saved test/audit log hashes remain
intact. Pinned source trees, compilers and offline audit inputs are available.
The source-to-copy path correction now has signed red/green commits, twelve
passing focused regressions and independent review. A new diagnostic license
audit passed, with all evidence hashes checked independently. Its executing
auditor differs from the preserved build source, so this output is explicitly
diagnostic and cannot serve as final release evidence.

The isolated release worktree was then fast-forwarded to reviewed, clean
`c8f549e`. Its fresh 1,947-test host suite passed in 1,111.682 seconds, with
19 documented skips: 18 superseded schema-v1 fixtures and the build-dependent
generated-runtime class. All 77 shell/conformance test files and standalone
source-policy checks also passed. The generated checks subsequently passed all
six tests against each fresh matrix, without skips.

Both fresh build matrices completed all five profiles. Their maintained
reproducibility comparison passed. Independent reviews also found identical
provenance, matching source/tool pins, and passing image/partition capacity
checks for both matrices. The same-source release license audit passed, covering
all five profiles and sixteen license roles.
The previous failed audits and complete earlier builds remain intact.

An early website dependency audit failed on newly indexed Next.js and sharp
security advisories, plus a moderate Vitest advisory. Deployment is held;
neither forced dependency repair nor a bypass of the audit gate is used. The
Windows-hosted and image-optimization conditions in the upstream advisories
do not establish exposure of this Linux/Nginx static deployment, but the
maintained dependency gate still requires remediation before the new build.

Security updates in a separate website-only checkout passed installation with
the original package manager, a zero-vulnerability dependency audit, all 336
website tests, and both static/Sites builds. The
existing staging code supports a website checkout distinct from the exact
firmware source root; independent code-path review confirmed that this retains
the same firmware license/qualification authority. Actual staging must still
pass the unmodified production validator. Firmware acquisition, completion and
finalization remain in the clean, frozen firmware checkout. Website and firmware
commits will be recorded separately; no firmware rebuild is inferred necessary
from website-only dependency changes.

The fresh Lenovo no-tap inspection passed. Actual installed private APK bytes
matched the admitted build both before and after inspection; private and official
package identities remained unchanged. The captured App screen shows Bluetooth
on, disconnected, scanning idle and no boards yet seen. No scan, connection,
file operation or firmware action was requested. The owned-file pilot is being
prepared separately; this screen observation is not a passing qualification row.

The subsequent owned-file pilot connected to the exact generic S3, created a
fresh test directory and two empty files, and focused the editor. It stopped
before typing code because the keyboard reduced the viewport and clipped the
chip label used by a test guard. A separately reviewed keyboard-hide step sent
one normal Back key. The follow-up guard then stopped on a test expectation of
`0 bytes` instead of the app's actual `0 B` file-size label. Both unsuccessful
attempts are retained, with no automatic retry or file cleanup.

A fresh read-only check independently confirmed that the keyboard is hidden,
the complete chip/Ready guards are restored, the owned editor is empty, clean
and focused, and both test files remain listed. Installed APK bytes, source
closure, and private/official app identities remain unchanged. A separately
reviewed continuation then typed the exact owned test source. Android reopened
the keyboard during typing, again clipping the chip label; the subsequent
helper observation timed out before Save. The actual captured editor contains
the exact expected dirty text and still reports the same Ready board. No Save,
Run, additional file operation or automatic cleanup followed. This failed stage
is preserved separately; these engineering observations are not final-candidate
HIL.

A new, independently reviewed keyboard-aware continuation subsequently passed
its complete remaining sequence. It saved the exact created buffer, replaced
only the known owned text, saved the edited buffer, hid the keyboard once,
opened the empty test file and reopened the ordinary test file through actual
GET operations. The reopened clean editor matched the expected edited text
exactly, followed by ordinary Disconnect and a disconnected UI observation.
Fresh before/after installed APK bytes, private/official identities and source
checks remained unchanged. This is a completed engineering continuation, not a
retrospective pass for prior failed stages, independent physical-radio proof,
Run/Stop result or final-candidate qualification row. The two test files remain
on the board; no owner file was removed.

The main workspace now contains separate Google Play build-8 work. That work is
preserved; its application artifacts do not replace the admitted private
qualification build. Firmware qualification continues in the existing isolated
worktrees. Read-only SSH checks confirm the public and protected-candidate site
selectors still point to their previous releases. No deployment, firmware write
or app reinstall has occurred during the resumed work so far.

The immutable five-profile candidate was subsequently created from clean
`c8f549ee`, with a local-only annotated `firmware-v0.6.1` tag. All 28 listed
candidate checksums passed a separate byte check. Its release metadata SHA-256
is `71f6aca6df07e31a1f54c7f70a48d82c7fe26b1c8ca0626a8ffc57c804fbb1bd`.
All five hardware records remain pending. The additional audited validation
passed. Candidate-selected local website staging and full web checks have now
started; the tag has not been pushed and no VPS content has changed.

The separately frozen website source is `06f98641`; it does not replace the
firmware provenance. The split-source snapshot helper passed all 24 fixture
tests independently, and its actual source-root/tag/validator-byte checks
passed. No real snapshot has been composed or transferred yet.

The retained five physical binding files also pass the current schema and
candidate-artifact checks. Read-only USB enumeration and alias-ownership checks
confirm the five application endpoints are present and idle. No serial port
was opened and no ROM identity, flash write or hardware qualification result is
inferred from this preflight.

The candidate's protected local stage subsequently passed its two audited
validations. Its selector binds the same release metadata and all five pending
profiles. Candidate-selected website formatting, lint, types, dependency audit
(zero vulnerabilities), license checks, all 336 tests and static route generation
have passed; the final Sites packaging validation is still running. This is not
yet a completed full web check or VPS deployment.

The Lenovo multiline engineering check also passed all 17 ordinary UI actions.
Actual Save and a subsequent GET reopened exactly `while True:\n    pass\n`
(21 UTF-8 bytes), including four indentation spaces and its final LF. A separate
GET confirmed the ordinary test file's unchanged 46 bytes. The app then
disconnected normally. Its APK/source and private/official identities remained
unchanged. No loop was run, no trace was armed and no final-candidate hardware
row was marked passed.

The complete candidate-selected website check subsequently exited successfully,
including final Sites packaging and clean-source postchecks. Its retained log
SHA-256 is `550d37e3ffe9c8bc09be743b456ff07a95d6f34b588ddf0267ca2d8e054f8ee0`.
The reviewed split-source composer then created and verified the real local
snapshot: 208 files, 25,577,284 bytes, inventory SHA-256
`165f589c58becb5cde50b367828b1ead19308584afb33f29b2d6fb806d179ba1`.
It includes Flash, Learn, all ten tutorial pages and their reviewed assets.
Canonical post-composition stage validation is running; no remote upload or
activation has occurred yet.

A fresh full 4 MiB owner-preservation backup of the exact Classic board also
completed. Device MD5 checks before and after the read matched the saved bytes;
the independently rehashed backup SHA-256 is
`2aa2280b9fa0d66bbd60e73d0858e8df62f8025aa1e93f1c900ea86eb36aca3e`.
The helper performed no persistent flash writes, then made one explicit runtime
reset and bounded capture before closing the port. This proves backup and
handoff completion, not runtime boot correctness or final-candidate HIL.

The Lenovo's longer multiline text test subsequently passed all 31 actions.
The exact 72-byte flood example was saved and reloaded through an actual GET;
the ordinary file remained exactly 46 bytes. Normal Disconnect and unchanged
application/source checks passed. This was text-entry and file-transfer
commissioning only: no RUN/STOP, trace, or final-candidate qualification claim.

Canonical post-composition stage validation passed. The first protected upload
then completed, but its incoming-tree verification failed: the laptop's Apple
openrsync preserved private 0700-directory/0600-file modes despite `--chmod`.
The candidate was not activated. The failed incoming tree and logs are retained;
the public and protected current links remain unchanged. A separate serving-mode
transport copy and new incoming name are being prepared, with no change to the
original private snapshot or acceptance checks.

The separate second-attempt transport copy passed complete byte, directory and
permission checks. Its corrected transfer retained no-overwrite and timeout
protections. The new protected incoming tree then passed verification, followed
by a successful protected-only activation at 05:21:08–09 UTC on 2026-09-11.
The activated release was independently reverified against the complete local
inventories and unchanged public/configuration guards. The previous candidate
and first failed incoming directory remain preserved. No public deployment,
authenticated-browser result or hardware qualification is inferred from this
staging activation. Browser authentication and final five-board HIL remain.

Post-activation HTTP and SSH checks passed: public Flash/Learn bytes, the public
current link and the three Nginx configuration hashes remain unchanged; the
protected routes still require their existing Basic authentication. A dedicated
Chrome window was opened for operator sign-in. Its first automated launch
admission stopped because the Mac listener tool resolved 127.0.0.1 to `localhost`.
A scoped numeric-address check confirmed the same owned browser listens only on
127.0.0.1. The original failure is retained; a separate numeric-only observation
variant passes its host tests but has not been used to observe the browser.
No authenticated-page proof or final firmware qualification follows. Staging
credentials have not been changed, collected or substituted with other accounts.

### 2026-09-11 06:01 UTC — private browser access and iPad readiness

The canonical public validator was run against the actual final candidate and
exited with `esp32-4mb is not HIL-passed`. All five final-candidate profiles and
their 40 check fields remain pending. Previous engineering tests do not qualify
the new final binaries. The public flasher still serves qualified v0.6.0.

The staging password obstacle was removed from the testing workflow without
changing the public website or the existing protected service. A separate HTTPS
listener binds only to the VPS loopback address, serves the exact immutable
candidate, and is reached through the laptop's existing authenticated SSH
connection. The laptop forwarding listener is also loopback-only. There was no
firewall opening, public DNS change, credential reset, certificate bypass, or
change to the three existing Nginx configuration files. The new configuration
passed `nginx -t`; independent checks confirmed public Flash/Learn byte identity,
continued Basic authentication on the original endpoint, rejection of external
access and wrong SNI/Host, and denial of hidden metadata paths.

A separate owned Chrome profile now displays the candidate without a password
prompt, using valid HTTPS and an exact-profile hostname mapping. The obsolete
owned password-prompt browser was closed; its profile and failed evidence were
preserved. A page-only screenshot was captured. Because the candidate's
`no-store` policy prevents cached HTML retrieval, its served HTML was verified
by an independent HTTPS GET, not misrepresented as a browser-cache hash. This
is browser-access evidence, not a board-installation or HIL pass.

After the user confirmed readiness, one unchanged iPad inspect-only test passed
(one test, zero failures). The private App reports Disconnected, Bluetooth On,
and Scan Idle, without a permission prompt. Both PyBLE App installations remain
unchanged. The screenshot is clipped; the retained accessibility tree is the
authoritative UI-state observation, not a substitute for workflow testing.

The next requested operator step is the Classic ESP32 browser connection using
`usbserial-0001`, stopping before erase/install confirmation. Its full owner
backup is preserved. The exact C3 carrier/model remains unconfirmed; GPIO8 has
not been driven. No final firmware row has been marked passed and no public
release has been deployed.

### 2026-09-11 07:04 UTC — Classic browser flash and runtime checks

The user reported successful `ESP32 · 4 MiB flash` installation through the
SSH-only HTTPS candidate. An explicit erase-stage observation was not supplied
and is not inferred from that report. The later page capture no longer displayed the
completion dialog, so it is not being presented as a captured install result.

Two actual runs of the maintained target-neutral BLE smoke passed, before and
after a diagnostic verification reset: chip `esp32`, agent `0.6.1`, negotiated
MTU 247, chunk 229 and window 8. Advertising identity, HELLO, DEVICE_INFO and the
read-only INFO characteristic agreed. Existing esptool verification also found
matching device/local checksums for all three frozen firmware components:
bootloader, partition table and application. No flash was erased or rewritten
by these diagnostic checks.

A preceding whole-merged-image checksum did not match. That span includes
mutable NVS/PHY storage; the exact differing bytes were not acquired, so the
record retains this diagnostic without asserting an NVS-only cause. The three
immutable-component checks passed independently. These results are not a
complete final-candidate HIL pass.

The next operator step is deliberate interruption during another Classic
browser write, followed by recovery with the same verified image and explicit
full-chip erase. Remaining workspace, OI, hardening and both-platform App
checks are still required. The public v0.6.0 flasher is unchanged.

At 07:07 UTC, the user reported deliberate Classic interruption. Both serial
endpoints were absent, and the captured browser dialog showed installation
failure with a stopped serial data stream. Recovery has been requested using
the same profile and the documented BOOT/RESET sequence, with the completion
dialog left open for observation. No serial reflash was substituted. Inspection
of the pinned installer confirms that this flow erases before writing and has
no erase checkbox; its confirmation states that all device data will be erased.

### 2026-09-11 07:31 UTC — Classic recovery and storage-test tooling defect

The user reported successful browser recovery. The later screenshot showed the
selected Classic v0.6.1 dashboard, not the completion banner. An actual BLE
smoke after recovery passed with chip `esp32` and agent `0.6.1`.

The subsequent controlled nonblank-storage acquisition at 460800 baud failed
during firmware readback. A fresh attempt at the original 115200 baud verified
the complete firmware image, wrote the deliberately incompatible workspace
prefix and read the complete workspace before boot. It then failed its runtime
USB identity wait. Neither attempt produced a passing storage receipt; both
sets of partial evidence remain preserved.

Read-only diagnosis found a host-tool defect: when runtime and loader use the
same UART bridge, the matcher treats the correctly present runtime endpoint as
the alternate loader endpoint. The Classic binding and physical USB identity
agree. A minimal regression-tested qualification-tool correction is being
prepared separately from the frozen firmware candidate. The firmware, release
thresholds and public website have not changed. Storage acquisition must be
rerun with the corrected tool before the remaining board and App workflows.

### 2026-09-11 07:53 UTC — measured recovery startup and serial handoff defect

The UART identity correction passed 106 host workspace tests in a separate,
clean qualification checkout. Its fresh physical acquisition passed complete
firmware and pre-boot workspace readback, then reached the recovery console
step and timed out. It did not produce a qualification receipt.

A passive, retained-serial-handle diagnostic subsequently observed the actual
recovery message, v0.6.1 banner and friendly REPL at approximately 22.56 seconds
after reset. The complete-storage scan runs before the console becomes ready.
The acquisition tool had captured six seconds, closed the serial connection,
then reopened it and allowed twelve seconds for console entry. The reopened
connection produced another ROM boot banner. Two preceding shorter diagnostics
also failed and remain preserved.

The diagnosis is a premature host-tool serial handoff, not a demonstrated
firmware hang. A separate, tested correction is being prepared to retain the
connection through first-boot observation while preserving the existing outer
acquisition deadlines and strict stdout framing/deadline. No diagnostic is being
promoted into a passing first-boot receipt. The frozen firmware and public
v0.6.0 deployment remain unchanged.

### 2026-09-11 08:18 UTC — corrected storage collector frozen

The retained-UART correction is frozen in a separate qualification checkout at
`3cbfc21032f5b0fa749742179600d8375ac3bf70`. All 122 workspace host tests and
an independent 65-test focused review passed. Firmware bytes and qualification
thresholds are unchanged.

Its first physical attempt failed during loader synchronization, before any
flash erase or write. A single read-only loader check subsequently identified
the expected Classic MAC and 4 MiB flash successfully. A fresh controlled
storage acquisition is now running at the original 115200 baud. The failed
attempt remains recorded; there is not yet a passing final storage receipt.
The public flasher remains on v0.6.0 pending complete qualification.

### 2026-09-11 08:30 UTC — Classic incompatible-storage check passed

The corrected collector completed the actual nonblank-media-refusal test.
The full 2 MiB workspace readbacks before and after boot match. The real
recovery observation reports no format, erase, program or remount operation,
and the workspace was not attached. Recovery startup completed in about
22.75 seconds on the retained serial connection.

The canonical receipt and required raw siblings validate against the unchanged
v0.6.1 candidate and exact Classic board binding. Its receipt SHA-256 is
`9cdc1b9cbdc8dfedf10d85d9bea8d18e77d10493d048a03272598c080038a050`.
The separate erased-media first-boot acquisition is now running. This is one
passing storage check, not completed board or five-board qualification.

### 2026-09-11 08:37 UTC — erased-storage attempt interrupted by USB loss

The erased-storage acquisition passed the firmware write and complete image
readback, then failed during the pre-boot workspace read with `Device not
configured`. macOS independently recorded removal of Classic's CP2102 bridge
at 08:35:31.486 UTC and its return 3.507 seconds later. The cause of that USB
interruption is not yet established; the same identity and port are present
and idle again.

No erased-storage receipt was produced, and all partial evidence is retained.
The completed incompatible-storage pass remains valid and independently
reviewed. The cable/power situation needs checking before a fresh erased test;
no automatic retry or publication has occurred.

### 2026-09-11 08:54 UTC — Classic workspace pair complete

After the user confirmed reconnection, a fresh erased-storage acquisition
completed successfully. Both receipts and all 18 required evidence files pass
independent validation against the same physical Classic board, unchanged
firmware candidate and frozen qualification tools.

The erased-storage test demonstrated exactly one completed format/remount and
a usable attached workspace; the incompatible-storage test demonstrated no
formatting or writes. The successful erased receipt SHA-256 is
`0f7fad51693f762626843352598be2154828418462a064d37fee6fe9fdb30f26`.
The interrupted attempt remains retained as a failure, not reused as evidence.

The measured BLE workload is now running. Its first ten reset-to-advertising
samples are 1111–1460 ms. Transfer, reliability, physical power-cycle,
hardening and real App checks still need to complete before board admission.
The public flasher is unchanged.

### 2026-09-11 09:44 UTC — Classic workload passed; hardening remains blocked

The actual off/on sequence completed after the user's separate power-off and
reconnection confirmations. The measured OI workload exited successfully and
passed independent review: ten reset samples, five 64 KiB PUT/GET round trips,
twenty verified 16 KiB reliability transfers, resource measurements and the
fresh physical power cycle. No transfer retransmissions or integrity failures
were observed. The observation SHA-256 is
`bf10ec5d40e3eb68f74417118ae68e41aa1c8597a7b210a9b648ed1265dbd987`.

The subsequent seven-scenario hardening run failed the GC free-memory floor at
sample two. Only its transport-session, fragment-hardening and run-isolation
scenarios passed. It produced no completed hardening result. The failure and
all subsequent diagnostic captures remain preserved; qualification is blocked.

Bounded diagnostics examined VM setup effects without changing the firmware
or resource policy. The latest diagnostic used one verified soft-reboot
boundary, ten fixed setup probes and fifty measured probes. All fifty measured
GC free-memory values were exactly 106608 bytes and passed the unchanged floors
and trend check. This is diagnostic evidence, not a qualification pass. A
documented, regression-tested host measurement-setup correction is being
prepared in a separate checkout. Its new tool revision will require fresh
storage receipts; existing receipts will not be relabelled.

Separately, the Lenovo ordinary-App attempt stopped after its first Save because
the UI helper required a transient saved-message notification. Repeated captures
showed the correct board, exact document text and clean editor state, but no
notification. No Run or Stop occurred, and the complete workflow did not pass.
The saved owned file and failed attempt are preserved. An actual guarded App
Disconnect succeeded. Corrections retain real subsequent file GET checks before
execution; the iPad workflow has not yet run. The public flasher remains on
v0.6.0 until the complete five-board release qualifies.

At 09:48 UTC, Classic also passed the maintained target RUN/STOP bench on the
unchanged candidate: real stdin round trip, tight-loop and print-flood Stop
responses followed by idle within the strict 500 ms deadline, same-link nonce
follow-ups, idempotent idle Stop and bounded file-mode Run. A fresh identity
and file-collision preflight preceded this run. Its retained log SHA-256 is
`ce02758fb61a8cb834a0eddf60ff4c6e46ed71c26c6993761a52f6050364ffde`.
This does not replace ordinary tablet workflows or the failed hardening check.

### 2026-09-11 10:26 UTC — Measurement tooling corrected; tablet checks incomplete

The isolated qualification-tool revision
`4f7fa2f7a42d87521ce4e466709f77e32164e7ef` now passes 200 relevant host tests
and independent review. It introduces the documented single VM boundary and
ten fixed setup probes before the fifty measured probes. Every resource floor
and the trend check remain unchanged, and every numeric sample is retained.
Firmware bytes are unchanged. This host result is not a hardware pass; fresh
source-bound workspace receipts and an actual hardening run are still required.

Lenovo successfully read back the first saved file, edited it and saved the
exact 76-byte replacement. Subsequent UI-helper attempts stopped on overly
specific editor geometry and focus expectations. The latest actual state shows
the newly created loop file empty, clean and focused; Run/Stop has not started.
These attempts remain failed and are being continued from their verified state,
without recreating files or substituting host tests for App evidence.

The first iPad attempt stopped immediately after foregrounding because the
accessibility view was not ready. No board controls or file operations were
dispatched. A bounded initial-view wait is prepared but not yet exercised.
Neither tablet workflow is complete, and the public flasher remains unchanged.

At 10:36 UTC, the Lenovo continuation completed all remaining actions and
exited successfully. Actual App observations cover file readback, NeoPixel
import and nonce output, loop Run/Stop, reconnect, soft reboot, post-reboot
readback/execution and final Disconnect. Private and official App identities
and the installed APK/source checks remained unchanged. The result SHA-256 is
`86044b6e8fb479adc5c261ff5a18b41c882a951e6c1b3806121cfd80d87fca48`.
The original saved-file readback is explicitly retained from its predecessor;
earlier failed automation attempts are not relabelled. This ordinary workflow
does not claim strict UI Stop timing or whole-release qualification.

After verifying Lenovo's final disconnected view, the reviewed iPad workflow
was started. The existing Apps and firmware were not replaced. A separate,
small positive-prefix upload-resume demonstration is also being prepared to
cover the existing FR-FS-7 requirement; it has not yet run.

The iPad attempt subsequently stopped before its first Save or Run. It had
connected to Classic and created its owned empty file, but typing the entire
Python expression caused extra auto-paired closing punctuation. The exact-text
guard correctly refused the altered buffer. Actual screenshots, accessibility
data and the failed result are retained; App identities remained unchanged.
A continuation with pair-aware text entry is being prepared from that same
owned unsaved buffer. The iPad still holds the Classic connection; no storage
or host BLE test may run until it explicitly disconnects.

### 2026-09-11 11:04 UTC — Genuine iPad transfer failure

Pair-aware text entry successfully saved the expected created and edited files.
However, creating the empty loop file then produced an actual App transfer
timeout during automatic opening. The file list shows `loop.py` at 0 bytes;
the editor still shows the previous clean `ordinary.py` at 76 bytes. No loop
Run/Stop or reboot occurred. This attempt remains failed, with its complete
result, screenshot and accessibility evidence preserved.

Source inspection identified a possible early-download-event race while the
App awaits BLE write completion. A host regression is being prepared in an
isolated checkout; the UI evidence alone does not prove the precise wire cause.
The iPad workflow remains incomplete. Firmware bytes and the public v0.6.0
flasher remain unchanged.

At 11:08 UTC, after actual iPad Disconnect, Classic passed a positive-prefix
upload-resume demonstration: ACK 229, real link loss and reconnect, unchanged
old-file readback, resumed BEGIN at 229, final ACK 458 and complete CRC/byte
verification. Its owned fixture was removed and absence verified. Evidence
SHA-256: `2180be1bcf912da7fa05f7cf24af839277ad340bad403a0ef68fec301e7a53df`.
This satisfies that demonstrated resume behavior, not whole-release approval.

The suspected App event-ordering defect is now reproducible in host tests for
both empty and nonempty files. A minimal correction is under independent review
in an isolated checkout. Fresh storage/hardening acquisition is proceeding on
the unchanged Classic firmware; the earlier failures remain preserved.

At 11:18 UTC, the new nonblank-media attempt failed during ROM synchronization
for its final readback. The candidate and complete pre-boot filesystem had been
verified, and the actual boot reported refusal with no format/program/erase.
However, no post-boot media bytes were acquired, so no passing receipt exists.
A subsequent read-only, no-reset ROM query succeeded with the expected physical
board identity and 4 MiB flash; this does not complete the failed acquisition.
Serial-loader handoff diagnosis is continuing before another storage attempt.

The isolated App GET correction is now committed as
`af4d96782c2c340cb1b6a2ad5e7fc44adace9d20`, following a failing regression
commit and independent review. Host tests pass: 761 default unit/conformance,
766 trace-enabled unit/conformance and 201 widget tests, with documented
compile-variant skips; static analysis reports no issues. Corrected private
test builds are being prepared. Official installed Apps remain unchanged.

At 11:33 UTC, one bounded diagnostic successfully used deasserted serial
controls before opening, one explicit sequential reset and a no-reset ROM
connection. Actual board identity, security state and flash ID matched, and
the owned handle closed cleanly without programming flash. This supports
testing that alternative handoff; it does not establish the exact failure
mechanism or qualify storage. A narrowly scoped macOS Classic host-tool change
is being prepared with fresh source-bound acquisitions still required.

Both corrected private Apps have now built and passed artifact verification,
including signatures and packaged code matching the new build outputs. They
have not been installed. Official Apps and the public flasher remain unchanged.

At 11:55 UTC, the narrowly scoped loader correction was frozen in clean signed
commit `98e72f57c646e56144e864334e17f2b17f2bf05e`, with independent review and
177 relevant tests passing. A new Classic nonblank-media acquisition is running
against that exact tool revision; it has not yet produced a passing receipt.

The corrected private Lenovo App has now been installed after fresh disconnected
UI and export-preservation checks. Its actual installed APK matches SHA-256
`582a18974933f475a3fb0b85d80c7dfeae99ae947be4976a62a43b1dc2424871`.
Private permissions and first-install time, and the official App identity, remain
unchanged. It has not yet been launched or hardware-tested. The iPad update is
awaiting a fresh no-tap screen inspection. No public release has been activated.

At 11:59 UTC, the iPad inspection passed and its complete accessibility tree
and screenshot showed a disconnected, non-editing App. The corrected private
iPad App was then installed with its signed artifact linked to the actual OS
installation receipt; the official App remained unchanged. Lenovo's corrected
App also opened and showed its initial disconnected screen. Neither corrected
App has yet completed its new hardware workflow.

At 12:03 UTC, the new Classic storage acquisition again failed at post-boot ROM
synchronization. Its full candidate/pre-media readbacks and actual no-write
refusal observation passed, but no post-media readback or completion receipt
exists. The host handoff change is therefore not yet proven effective. A
separate no-reset ROM query subsequently succeeded; it is diagnostic evidence,
not a replacement for the failed acquisition. The next diagnostic isolates the
runtime-to-loader transition without another erase/program cycle. Publication
remains blocked on genuine hardware qualification, not on App build readiness.

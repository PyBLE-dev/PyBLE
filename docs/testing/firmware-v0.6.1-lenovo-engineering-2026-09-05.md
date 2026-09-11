<!-- SPDX-License-Identifier: MIT -->

# Firmware v0.6.1 — Lenovo engineering checks, 2026-09-05

Status: **archived partial engineering validation from September 5**.
Later publication is recorded separately in the
[September 11 publication record](firmware-v0.6.1-publication-2026-09-11.md).
Statements about remaining work below describe this historical session only.
The ESP32-C3 baseline image completed the observed Android UI checks below.
This is not a final-candidate HIL report, an admitted Android release row, or
approval to publish the five-profile firmware release.

## Identified inputs

- Physical tablet: Lenovo TB J616X; Android 12, API 31.
- App: PyBLE 0.2.0, build 5; identified real-UI tutorial-capture build.
  This is not a new distribution build or a fake-transport test.
- App source: `4df378fc76c919f0e2481eb5b668f14115d38587`.
- Firmware profile: `esp32-c3-4mb`; ESP32-C3 revision v0.4, 4 MiB flash,
  no PSRAM required; observed firmware agent version `0.6.1`.
- Engineering source: `f0b05f4c0e7a0d07a51e00ca104a0b716d1e4eb6`.
- Frozen application: 1,689,024 bytes at flash offset `0x10000`; SHA-256
  `a8ad1b3d1afb2d173d5786f7a297d56d5c342bb26a1865e71892f08d9fb52968`.

These are admitted baseline inputs, not the subsequently rebuilt, tagged,
protected final candidate required by the release procedure. Android actions
used the ordinary app UI, driven and observed through USB ADB. The laptop VPN
was left unchanged; no iPad was used.

## Installation and owner-data protection

Two matching complete C3 flash backups were retained privately. A guarded,
application-only engineering installation used pinned esptool 4.12.0 after
checking the exact physical target, security state, bootloader and partition
table. No full-chip erase or merged-image install was performed.

A fresh full read preceded programming. A second full read, taken through the
same loader connection before application boot, proved the exact application
bytes and equality of all 2,502,656 bytes outside sectors
`[0x10000, 0x1ad000)`, including NVS and the complete VFS. An independent
retained-byte audit agreed. Reset and serial close then completed normally.
Fresh BLE HELLO and a recursive listing subsequently showed version `0.6.1`,
the expected target, unchanged configuration, and the same pre-existing paths.

This is preservation evidence at the stated observation boundaries, not a
destructive-provisioning receipt. UI writes were confined to a newly created
test-owned directory and its Python fixture. Autorun, Identify, device label
and GPIO configuration were not changed.

## Observed Android checks

“Observed” below means the stated real UI behavior was captured, not that its
complete wire-level qualification gate passed. Private capture numbers identify
the retained session sequence; raw captures are not published with this report.

| Check | Observed outcome | Private evidence sequence |
| --- | --- | --- |
| Fresh discovery and connection | Ordinary scan/connect reached Ready with firmware `0.6.1` and the correct `esp32-c3` target. | 07–09 |
| Create, edit, save and reopen | A test-owned file was created through Files, edited, saved, refreshed and reopened with exact expected source. | 10–14 |
| File RUN and live stdout | `LENOVO_V061_HELLO` then `42`; Finished, Ready, Run available and Stop disabled. | 15 |
| Fresh globals on consecutive file RUNs | Each run printed `FRESH True` then `SET 1`. | 16–17 |
| Idle stdin isolation | After verified idle submission, the successor stayed Running at `WAIT_INPUT`; only fresh input completed it with `ECHO:LENOVO_FRESH`. | 20–22 |
| Tight-loop Stop | Test input was submitted during a running tight loop, then the real Stop action reached Idle/Ready with Stop disabled. | 23–25 |
| Post-Stop globals and stdin isolation | Successor printed `FRESH True`, waited without consuming stale input, then completed with `ECHO:AFTER_STOP`. | 26–27 |
| Print-flood Stop and recovery | Live repeated output was visible; Stop reached Idle/Ready, followed by a successful HELLO/42 program without reboot recovery. | Raw capture 28; 29–30 |
| Expected exception and recovery | Deliberate `ValueError: LENOVO_EXPECTED` remained visible with Error; next run printed `FRESH True`, HELLO and `42`, then Finished. | 31–32 |
| Final fixture readback | Refreshed and reopened the exact 84-byte test fixture through Files. | 33 |
| Disconnect/reconnect persistence | Explicit disconnect, fresh scan and reconnect; the 84-byte file was reopened from Files and ran normally. Cached editor text alone was not treated as readback. | 34–38 |
| Soft-reboot functional recovery | After the UI action, a later observation showed Disconnected; fresh scan/reconnect, exact file reopen and normal RUN succeeded. | 39–43 |
| Supplemental laptop final inventory | Not completed: laptop BLE discovery/connect timed out before HELLO. A separate fresh laptop scan did not find C3; a subsequent Lenovo connection did reach Ready with `0.6.1`. Cause unresolved; no final inventory pass inferred. | Failed inventory attempt; 44–45 |
| Final Lenovo review state | The owned file was reopened and run again successfully; Lenovo was left connected to C3 with expected output and Finished/Ready. The test fixture was retained for review. | 46–47 |

## Excluded attempts and interpretation limits

- Initial editor auto-pairing and selection artifacts were corrected before
  measured RUNs. A malformed unsaved buffer was refused by the input preflight;
  it is a test-setup issue, not a demonstrated firmware defect.
- Capture 19 did **not** establish idle-input submission: the keyboard obscured
  Send and the field still held the text. Only the corrected sequence 20–22
  supports the idle-isolation observation. Ordinary MicroPython input echo was
  distinguished from the fixture's explicit `ECHO:` output.
- Continuous print output prevented UIAutomator from obtaining an idle
  hierarchy. A raw live screenshot and subsequent stopped/recovery captures
  were retained; no successful hierarchy snapshot 28 is claimed.
- An Android connection error 133 was visible before this firmware installation.
  Its cause is unresolved; later deliberate connections succeeded. It is not
  attributed to v0.6.1.
- UI snapshots do not establish PBLE response/event ordering or Stop latency
  below 500 ms. The gap between the initial post-reboot Ready observation and
  later Disconnected observation does not establish reboot latency either,
  including the hardening bench's separate 12-second disconnect expectation.
- The supplemental laptop discovery failure is retained separately from the
  successful Lenovo workflow. It does not prove a firmware defect or a
  VPN-related cause. Final session-wide inventory verification remains open.

## Remaining release work

Only C3 received the v0.6.1 engineering image in these observations. Classic
ESP32 now has two matching read-only full-flash backups at unchanged 115200
baud, with matching staged bootloader/partition geometry; it was not updated.
The generic S3's earlier RAM-stub acquisition failed. Waveshare still needs a
controlled BOOT/reset loader entry, and Pico needs BOOTSEL entry and backup.
None of those four profiles has a v0.6.1 qualification pass from this session.

Full qualification still requires all five fresh baseline measurements and
final-candidate builds; candidate-bound hardening, provisioning/recovery,
resource/performance and exact-board gates; and physical Android **and iPad**
app rows. Destructive media tests require appropriately designated test media.
This report does not replace the C3 full-chip-erased installation requirement,
prove inline-source RUN, or claim the seven-scenario hardening suite completed.

Authoritative procedure: [firmware roadmap](../planning/firmware-v0.6.1-v0.7.0-roadmap.md),
[HIL guide](../../tests/firmware_tests/hil/README.md), and
[C3 qualification contract](../specifications/firmware/ports/esp32-c3-4mb.md).

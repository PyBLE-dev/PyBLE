# ADR-0033 — Qualify v0.6.0 as one five-profile heterogeneous firmware release

- Status: **Accepted**
- Date: 2026-08-12
- Builds on: [ADR-0028](0028-separate-waveshare-lcd147b-firmware-profile.md),
  [ADR-0030](0030-pico2w-portable-python-agent-first.md), and
  [ADR-0032](0032-qualify-generic-esp32-c3-4mb-on-reference-hardware.md)
- Release contract:
  [firmware/browser-flashing.md](../specifications/firmware/browser-flashing.md)

## Context

The v0.6.0 source tree builds four ESP32-family variants and one RP2 target,
but a buildable image is not a qualified image. The prior release contract
still describes the unfinished v0.5.1 three-profile candidate, explicitly
defers C3 publication, and has no public RP2 artifact schema. The local
five-target preview intentionally labels every input unqualified because it
accepts engineering build outputs rather than a finalized exact-byte release.

PyBLE now needs one honest successor contract that can qualify all maintained
v0.6.0 targets without pretending that ESP Web Serial can provision an RP2
board. It must preserve the exact historical v0.4.2 public-beta bytes and the
v0.5.1 source/evidence identity while making every new profile independently
release-blocking.

## Decision

1. **Freeze one ordered v0.6.0 release scope.** The qualified v0.6.0 bundle
   contains exactly these profiles, in this order:

   1. `esp32-4mb`
   2. `esp32-s3-n16r8`
   3. `waveshare-esp32-s3-lcd-147b`
   4. `esp32-c3-4mb`
   5. `rpi-pico2-w`

   The set is atomic. A missing, substituted, reordered, pending, or failed
   profile leaves v0.6.0 unqualified and unavailable as a qualified public
   selector.

2. **Use two explicit provisioning backends.** The first four profiles ship
   independently built, profile-scoped merged `firmware.bin` images and
   ESP Web Tools manifests for Web Serial. `rpi-pico2-w` ships a
   profile-scoped `firmware.uf2`; the site verifies its exact size and SHA-256
   before offering a download, then instructs the user to copy those verified
   bytes manually to the board's BOOTSEL volume. Pico has no ESP manifest,
   offset, component map, `chipFamily`, or `navigator.serial` requirement.
   Direct WebUSB, automatic volume discovery, and browser writes to a mounted
   volume remain out of scope.

3. **Introduce heterogeneous successor schemas.** v0.6.0 uses release schema
   **4**, OI/resource-policy schema **3**, baseline-evidence schema **2**, and
   `PYBLE_HIL_RECORDS_V5` schema **5**. Every profile record shares candidate,
   artifact, common workload, integrity, BLE/PBLE, app-HIL, operator, and
   sign-off identity. A required discriminator selects exact target-specific
   fields:

   - ESP-IDF profiles bind manifest, merged image, components, offsets,
     partition/application headroom, ESP internal-heap observations, and
     NimBLE link-settlement facts.
   - RP2 binds UF2 and raw `firmware.bin`, the 1,572,864-byte image budget,
     image headroom, GC observations, BTstack transport facts, and the manual
     BOOTSEL install/recovery result.

   Thresholds are derived independently for all five rows from one controlled
   baseline set. A result from another profile, port, build, or provisioning
   backend cannot fill a row.

4. **Qualify exact bytes, twice built.** Candidate-freezing selects one clean
   source commit, the exact `versions.lock`, and agent version `0.6.0` before
   measurement or packaging. Two isolated clean builds must produce
   byte-identical released parts for every profile. The final candidate then
   runs the complete resource, reliability, BLE/PBLE, install, recovery, and
   real-app HIL matrix against those hash-locked bytes. Both one physical iPad
   and one physical Android tablet must pass the common app workflow for every
   profile.

5. **Carry existing target gates into release admission.** C3-G0 through
   C3-G6 remain mandatory and must all pass on the documented
   ESP32-C3-MINI-1-N4 reference before the C3 row can pass. Pico GP2 remains
   mandatory and expands to the common v0.6.0 resource/app/provisioning matrix
   on a physical Pico 2 W. This decision records no passed result: both
   summaries start `null`/`pending` and are populated only by strict
   finalization from validated private evidence.

6. **Keep promotion and rollback exact-byte operations.** HIL begins only
   after the protected candidate's `release.json` digest and every install
   artifact digest are frozen. Public finalization is copy-on-write and may
   change only `HIL_REPORT.md`, the corresponding HIL status/report digest
   fields in `release.json`, and their `SHA256SUMS` entries. It may not rebuild,
   replace, or normalize an artifact. Activation selects that immutable
   qualified directory; rollback selects a previous fully validated immutable
   directory and never mutates either release.

7. **Preserve history.** The published v0.4.2 two-profile public-beta tree,
   tag, schema, hashes, and evidence remain byte-for-byte historical. The
   unqualified v0.5.1 three-profile source candidate, its version identity, and
   any retained evidence also remain historical and must not be repackaged,
   retagged, promoted, or reinterpreted as v0.6.0 evidence.

## Consequences

- `/flash` can present one qualified five-profile release while keeping the
  provisioning action truthful for each platform.
- Release tooling, validators, OI baselines, HIL assemblers, recovery copy,
  and website selection require red-first successor-schema work.
- Qualification takes longer because one failing profile blocks the atomic
  v0.6.0 release. A smaller release would require a new spec-first decision and
  a new SemVer candidate; it cannot silently narrow this one.
- Until every gate passes and exact-byte finalization completes, the local
  preview remains **UNQUALIFIED** and production must not call v0.6.0 a
  qualified release.

<!-- SPDX-License-Identifier: MIT -->

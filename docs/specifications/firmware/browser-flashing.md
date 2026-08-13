# PyBLE Firmware Browser Provisioning and Release Bundle

Status: **FROZEN v1.31** · Owner: project maintainer · Frozen:
2026-08-12 (`[docs]`; ADR-0033 adds the exact five-profile v0.6.0 successor
with release schema 4, HIL V5, OI policy schema 3, four ESP Web Serial images,
and one verified-UF2/manual-BOOTSEL path; every new gate remains pending;
immutable v0.4.2 and v0.5.1 source-era contracts are preserved)

This document is the source of truth for the initial browser-provisioning
release bundle. It refines
[website.md §7](../website.md#7-firmware-installer-release-gate) and
[firmware requirements §8](specs.md#8-build-versioning--distribution-bld).
[ESP Web Tools](https://esphome.github.io/esp-web-tools/) defines the installer
manifest format and the ESP-IDF v4+ merged-image requirement; this document
defines the additional PyBLE compatibility, integrity, provenance, recovery,
and hardware-validation contract around it.

Browser flashing is a one-time, wired provisioning path. It does not add a USB
runtime transport: after provisioning, the app communicates with the board over
BLE and PBLE/1.

## 1. Release image profiles

The immutable v0.4.2 public-beta bundle contains exactly `esp32-4mb` and
`esp32-s3-n16r8`; it MUST NOT acquire another profile. The unqualified v0.5.1
source candidate targeted those two plus `waveshare-esp32-s3-lcd-147b`; its
identity and evidence remain historical. ADR-0033 freezes the following four
ESP profiles as the first four rows of the atomic v0.6.0 successor. This does
not assert that candidate binaries exist or qualify them for publication:

| Profile ID | ESP Web Tools `chipFamily` | Required target configuration | ESP image silicon window (`min_chip_rev_full`…`max_chip_rev_full`) | Merge settings | Browser image and component map |
|---|---|---|---|---|---|
| `esp32-4mb` | `ESP32` | Classic ESP32 with 4 MiB external SPI flash; no PSRAM assumption | `0`…`399` | DIO, 40 MHz, 4 MiB | merged `firmware.bin` at `0x1000`; bootloader `0x1000`; partition table `0x8000`; application `0x10000` |
| `esp32-s3-n16r8` | `ESP32-S3` | Lean ESP32-S3 with 16 MiB flash and 8 MiB **Octal** PSRAM (N16R8-class); no bundled TFT driver, exact-board companion, splash hook, QR, or splash-only native readiness seam | `0`…`99` | DIO, 80 MHz, 16 MiB | merged `firmware.bin` at `0x0000`; bootloader `0x0000`; partition table `0x8000`; application `0x10000` |
| `waveshare-esp32-s3-lcd-147b` | `ESP32-S3` | Exact Waveshare ESP32-S3-LCD-1.47B **B version** with 16 MiB flash and 8 MiB **Octal** PSRAM; includes the ST7789 runtime, companion, factory-enabled-after-erase splash hook/QR, persistent disable, and bounded native readiness seam | `0`…`99` | DIO, 80 MHz, 16 MiB | merged `firmware.bin` at `0x0000`; bootloader `0x0000`; partition table `0x8000`; application `0x10000` |
| `esp32-c3-4mb` | `ESP32-C3` | ESP32-C3 revision v0.3 or newer with 4 MiB external flash; no PSRAM assumption | `3`…`199` | DIO, 80 MHz, 4 MiB | merged `firmware.bin` at `0x0000`; bootloader `0x0000`; partition table `0x8000`; application `0x10000` |

The fifth row is deliberately heterogeneous:

| Profile ID | Upstream target | Required hardware | Public install artifact and action |
| --- | --- | --- | --- |
| `rpi-pico2-w` | `rp2` / `RPI_PICO2_W` | Raspberry Pi Pico 2 W (RP2350 + CYW43439) | verified `firmware.uf2` download followed by manual copy to the BOOTSEL mass-storage volume |

The exact profile order is `esp32-4mb`, `esp32-s3-n16r8`,
`waveshare-esp32-s3-lcd-147b`, `esp32-c3-4mb`, `rpi-pico2-w`. All five are
release-blocking. C3-G0…C3-G6 and Pico GP2 remain pending prerequisites; no
profile becomes active until the complete exact-byte v0.6.0 matrix passes.

### 1.1 Loopback-only five-target approval preview

The website MAY provide a maintainer-only engineering harness for approving
the pending five-target v0.6.0 selection experience and exercising exact local
clean-build artifacts. This harness is not part of the release bundle described by this
document. It does not add a profile to `release.json`, establish HIL, qualify a
port, make firmware public, or relax any candidate, public-beta, qualified-
release, activation, or rollback requirement.

Its exact target catalog and provisioning contracts are:

| Order | Target ID | Exact local artifact and action |
| --- | --- | --- |
| 1 | `esp32-4mb` | target-local single-build ESP Web Tools manifest; verified merged `firmware.bin` at `0x1000`; Web Serial |
| 2 | `esp32-s3-n16r8` | target-local single-build ESP Web Tools manifest; verified merged `firmware.bin` at `0x0000`; Web Serial |
| 3 | `waveshare-esp32-s3-lcd-147b` | target-local single-build ESP Web Tools manifest; verified exact-board merged `firmware.bin` at `0x0000`; Web Serial |
| 4 | `esp32-c3-4mb` | target-local single-build ESP Web Tools manifest for `ESP32-C3`; verified merged `firmware.bin` at `0x0000`; Web Serial |
| 5 | `rpi-pico2-w` | verified `firmware.uf2` download followed by manual copy to the board's BOOTSEL mass-storage volume |

All five inputs MUST come from exact clean builds of one full PyBLE source
commit and one firmware-agent version. A local preview descriptor MUST record
that version and full commit plus, for every artifact, its target ID, safe
relative preview path, exact byte size, and lowercase 64-hex SHA-256. Each ESP
entry additionally records the ESP Web Tools chip family, base offset, and its
own single-build manifest path and digest. The preview builder MUST reject a
dirty, mixed-commit, mixed-version, missing, escaped, symlinked, or digest-
mismatched input. It MUST NOT consume an arbitrary file merely because its name
is `firmware.bin` or `firmware.uf2`.

The four ESP paths retain the applicable manifest, image parsing, path,
compatibility, verification, and consent rules in §§1, 4, 5, and 7. Their
engineering manifests and artifacts live only in the local preview staging
tree; they are not public manifests or release metadata. ESP Web Tools receives
only the selected target's verified manifest. A connected chip-family match
does not prove flash capacity, PSRAM topology, silicon revision, or exact-board
wiring, and MUST NOT choose or substitute another target.

Pico 2 W has a deliberately different approval path:

1. the client fetches the local `firmware.uf2` with redirects rejected and
   verifies its exact byte size and SHA-256 with Web Crypto;
2. only after that verification and the visible overwrite/backup consent does
   it offer **Download verified UF2**;
3. that download is created from the verified in-memory bytes, not by navigating
   to or refetching the artifact pathname;
4. the page instructs the maintainer to disconnect the board, hold BOOTSEL
   while reconnecting USB, copy the downloaded UF2 to the mounted BOOTSEL
   mass-storage volume, wait for its automatic reboot, and then check for the
   expected PyBLE BLE advertisement; and
5. a verification failure removes the download action and does not offer an
   unverified fallback.

Pico 2 W MUST NOT receive an ESP Web Tools manifest, use the ESP installer
element, or require `navigator.serial`. This increment does not implement or
claim direct WebUSB, File System Access writes to the BOOTSEL volume, automatic
drive discovery, or automatic browser-to-board flashing. Those would be a new
provisioning backend requiring a later specification, threat review, tests,
and physical recovery evidence.

The preview starts only when `PYBLE_LOCAL_FLASH_PREVIEW=1` is explicitly set
for a development process bound to a loopback interface, and it activates only
for a document host of `localhost`, `127.0.0.1`, or `[::1]`. Its descriptor,
metadata, manifests, binaries, and UF2 file MUST be generated below a dedicated
gitignored, untracked staging directory. A production static export or Sites
build MUST reject the preview flag and reject or omit the staging tree. No
preview byte or descriptor may enter `out/`, `dist/`, the canonical versioned
firmware tree, `release.json`, `SHA256SUMS`, a selected-release descriptor, an
activation marker, a carry-forward marker, or a deployment upload.

The page and every selected-target detail panel MUST visibly say **LOCAL
ENGINEERING PREVIEW — UNQUALIFIED**. A successful local ESP flash or Pico UF2
copy is approval evidence only. In particular, C3 remains unavailable in
production until its existing exact-profile qualification and new-release
gates pass, and Pico 2 W remains absent from every active production selector
and support claim until GP2 plus the ADR-0033 RP2 publication contract pass. A
production build with no audited beta or
qualified selected release remains fail-closed.

The offsets and flash settings above are frozen from the matching ESP-IDF
`flasher_args.json` outputs. The release builder MUST compare generated
`flasher_args.json` with this table and fail on any difference; it MUST NOT
silently preserve stale or hand-copied offsets.

These are image-layout profiles, not GPIO-routing profiles and not an
app-runtime chip allowlist. ESP Web Tools detects the chip family, but that
detection does **not** prove flash capacity, PSRAM type, board wiring, power
quality, silicon revision, or which of the two S3 images is appropriate. The
lean image MUST be presented only as `esp32-s3-n16r8`; neither the website nor
release notes may call it generic for every ESP32-S3 board or claim its TFT
runtime. The exact image MUST be presented only as
`waveshare-esp32-s3-lcd-147b` for the documented B-version board; matching
N16R8 memory alone is insufficient. The C3 image MUST be presented as
requiring ESP32-C3 revision v0.3 or newer.

Before the install action appears, the user MUST explicitly select a profile
and affirm that the connected module meets its stated flash/PSRAM
configuration. The installer MUST then give ESP Web Tools only that profile's
single-build manifest. A family mismatch MUST therefore be rejected by ESP Web
Tools after connection; a shared multi-family manifest is forbidden because it
could silently select a different image than the profile the user affirmed. A
family match between the two S3 profiles is not proof of board identity, so the
exact-board action additionally requires an explicit B-version affirmation and
MUST NOT alias or redirect to the lean S3 manifest. A
USB VID/PID, serial-port name, browser user-agent, or previously saved BLE
board identity MUST NOT be treated as proof of a profile.

Adding or re-enabling a flash size, PSRAM topology, chip family, or board-
specific dependency set requires a new release candidate with the applicable
profile ID, artifact set,
compatibility copy, automated cases, and real-board HIL record. It MUST NOT
broaden an existing profile or mutate a published bundle by implication.

## 2. Version and provenance

One bundle represents one firmware-agent SemVer and one immutable source state.
For version `<version>`:

- `<version>` is canonical SemVer without a leading `v`;
- the annotated Git tag is `firmware-v<version>`;
- every binary is built from the exact tag commit in a clean checkout;
- the MicroPython and ESP-IDF refs and full 40-hex commit IDs are read from the
  frozen `firmware/versions.lock`;
- `agent_version` equals `<version>` and `protocol_version` equals `PBLE/1`;
- the build records the full PyBLE source commit, the clean/dirty state, build
  runner OS/architecture, compiler/tool versions, UTC build time, and upstream
  patch count;
- the same source commit and pinned toolchain MUST produce byte-identical
  released parts after documented deterministic-build normalization; a
  two-clean-build comparison is release-blocking; and
- no firmware binary may be rebuilt, renamed in place, or replaced after HIL
  begins. Any changed byte outside the administrative promotion envelope
  defined in §9 creates a new release candidate and invalidates prior HIL
  evidence for that file set.

Each of the two clean reproducibility build roots MUST retain this exact
relative source layout until the license audit, candidate validation, and
two-root byte comparison have completed:

```text
.sources/esp32-4mb/micropython/
.sources/esp32-s3-n16r8/micropython/
.sources/waveshare-esp32-s3-lcd-147b/micropython/
.sources/esp32-c3-4mb/micropython/
.sources/rpi-pico2-w/micropython/
```

Each path is an independent MicroPython checkout for exactly the named release
profile. The generic and Waveshare S3 variants both compile IDF target
`esp32s3`, but MUST NOT share mutable source/build state or collapse to one
artifact.
Its `HEAD` MUST equal the full `versions.lock [micropython].commit`, its
`origin` URL MUST equal the canonical `versions.lock [micropython].repo`, and
its tracked tree MUST be clean when admitted and validated. Each target's
authoritative application `project_description.json` `project_path` MUST
resolve to that target's retained checkout at `ports/esp32`, and the audit
receipt MUST bind the project-description bytes and checkout commit/origin
identity. The RP2 row instead binds its CMake cache, ELF, board, and pinned ARM
GNU provenance to its retained checkout at `ports/rp2`. A missing, escaped,
symlinked, dirty, wrong-origin, wrong-commit, or cross-target checkout is fatal.

Build preparation and ESP-IDF dependency materialization MUST be target-local.
In particular, no target may share, overwrite, or delete another target's
`ports/esp32/managed_components` or other mutable generated/source state. A
sequential build that leaves any earlier target described by source bytes from
a later target is invalid, even if released binaries happen to compare equal.

Before configuring or compiling an application, the build runner MUST replace
the target's exact retained MicroPython checkout prefix in compiler debug,
macro, and source-file paths with the target-stable logical prefix
`/MICROPYTHON`, and the exact PyBLE checkout prefix with `/PYBLE`. The more
specific MicroPython mapping MUST win if those paths are nested. ESP-IDF's
reproducible-build mapping MUST continue to replace the target build directory
with `/IDF_BUILD`. These mappings MUST be controlled by the runner and MUST
replace, not append to, any ambient compiler path-map input. A release build is
invalid if its whole ELF still contains either clean source/build root, or if
the two clean builds produce different whole-ELF hashes,
application-descriptor ELF hashes, application images, or merged images.
Generated frozen-content comments may retain their root-local input paths and
therefore are not cross-root release artifacts; each root's frozen content
MUST still independently reproduce and match its own generated build input
under the license-audit rules in §6.

These isolated build checkouts do not replace the canonical candidate proof
root. The exact `versions.lock`, board overlays, `firmware/pyble` sources,
literal manifests, release tools and license policy/evidence, and pinned
generator/compiler inputs under the canonical
`firmware/upstream/micropython` remain independently SHA-256-bound by the
semantic receipt and MUST agree with the corresponding selected build inputs.

For this release contract, **candidate-frozen** means that the exact
`versions.lock` bytes and the source commit containing them have been selected
as immutable inputs to one release candidate. Candidate-freezing MUST happen
before the two clean release builds, license audit, candidate packaging,
protected-site staging, or HIL. It is an input-selection state only: it does
**not** assert that the pins work on hardware and does not approve them for a
public release. Exact-profile HIL on all five v0.6.0 profiles in §1 remains the
successor public-release approval gate.
The v0.4.2 two-profile browser attestation remains historical evidence only and
MUST NOT satisfy this new candidate gate.

Changing either upstream pin after candidate-freezing creates a new source
state and a new candidate. The build, reproducibility comparison, license
audit, protected deployment, and complete current-release-profile HIL matrix
MUST then start again; evidence from the abandoned candidate MUST NOT be
carried forward.

For the historical v0.5.1 schema-2 OI contract, before the first OI-1 policy
can be committed, the release tool MUST provide a
`create-baseline-inputs` operation that breaks the policy/evidence dependency
cycle without weakening candidate validation. It MUST bind two distinct,
non-nested clean build roots to the clean PyBLE proof checkout, validate all
four maintained build variants and their retained source checkouts, require
the released inputs to compare byte-for-byte, and then atomically create one
new no-replace, access-controlled output tree containing exactly:

```text
esp32-4mb/
  manifest.json
  firmware.bin
  application.bin
  partition-table.bin
esp32-s3-n16r8/
  manifest.json
  firmware.bin
  application.bin
  partition-table.bin
waveshare-esp32-s3-lcd-147b/
  manifest.json
  firmware.bin
  application.bin
  partition-table.bin
```

The three manifest files MUST be generated by the same production manifest
function used by candidate packaging. The three binary files per profile MUST
be copied from the matching validated primary build variant. The generic and
exact S3 application and merged-image hashes MUST differ and each manifest
MUST bind only its owning bytes. The deferred C3 build MUST
participate in validation and reproducibility comparison but MUST NOT be
staged. This operation runs before, and therefore MUST NOT require, an OI-1
policy, baseline-evidence file, release tag, license evidence, or HIL approval.
Its output is measurement input only: it is not a release candidate and MUST
NOT be accepted by the website or public release validator.

For v0.6.0, the same no-replace operation instead validates and stages exactly
five ordered inputs: the three ESP directories above, an equivalent
`esp32-c3-4mb/` directory, and
`rpi-pico2-w/{firmware.uf2,firmware.bin}`. It accepts exactly five bench
fragments, derives the target-discriminated schema-3 policy in
[specs.md §5.3.5](specs.md#535-v060-five-profile-successor-policy-and-evidence),
and never mixes a historical fragment or source commit into the set. The two
clean roots must compare every released ESP part plus Pico `firmware.uf2`,
`firmware.bin`, and `firmware.elf` byte-for-byte before staging.

After both exact-profile baseline runs succeed, the release tool MUST provide
an `assemble-oi1-baseline` operation. It accepts the immutable staged baseline
input tree above, exactly two canonical single-profile fragments emitted by
the OI-1 bench, the clean canonical PyBLE proof checkout, and one explicit UTC
`created_at` value. It MUST derive `source_commit` from that checkout's exact
`HEAD` and `firmware_version` from its `versions.lock`; operator-supplied
substitutes for either identity are forbidden. Before writing, it MUST require
the proof checkout to be clean, require exactly one fragment for each profile
regardless of input order, validate every fragment and observation field,
bind each fragment's firmware hash, manifest hash, and build measurements to
the corresponding staged bytes, and mechanically derive all nine thresholds
with the frozen formulas.

The operation MUST canonicalize and create the baseline evidence at
`docs/validation/firmware/oi1/<HEAD>.json`, compute the digest of those exact
bytes, and atomically update `firmware/qualification/oi1-gates.json` with the
exact frozen policy shape and derived thresholds. The baseline path is
no-replace: any existing destination is fatal. The policy update MUST be an
atomic same-directory replacement, and both complete payloads MUST pass the
production baseline/policy validator. This operation is evidence assembly
only; it does not approve a release or mutate staged measurement inputs.

The protected candidate site's build-selected SHA-256 of `release.json` is the
root identity of the candidate exercised during HIL. The completed HIL
evidence MUST record that exact lowercase 64-hex digest. Public finalization
MUST verify it against the candidate source tree and MUST derive a new public
directory without mutating that source.

The maintainer MUST verify that the local annotated tag, embedded agent
version, `DEVICE_INFO`/HELLO version, manifest version, bundle metadata, and
public same-origin directory all identify the same version and source commit.
For v1.0 and later, the matching GitHub Release MUST identify that same version
and source commit as well. For a v0.x release, any optional mirror MUST meet the
same identity and byte-parity requirements, but absence of a mirror does not
block same-origin publication.

## 3. Same-origin, versioned layout

The canonical public files are static and use this exact layout:

```text
https://pyble.dev/firmware/v<version>/
  release.json
  release.schema.json
  SHA256SUMS
  THIRD_PARTY_LICENSES.txt
  RELEASE_NOTES.md
  RECOVERY.md
  HIL_REPORT.md
  esp32-4mb/
    manifest.json
    firmware.bin
    bootloader.bin
    partition-table.bin
    application.bin
  esp32-s3-n16r8/
    manifest.json
    firmware.bin
    bootloader.bin
    partition-table.bin
    application.bin
  waveshare-esp32-s3-lcd-147b/
    manifest.json
    firmware.bin
    bootloader.bin
    partition-table.bin
    application.bin
  esp32-c3-4mb/
    manifest.json
    firmware.bin
    bootloader.bin
    partition-table.bin
    application.bin
  rpi-pico2-w/
    firmware.uf2
    firmware.bin
```

This is the v0.6.0 schema-4 layout. Historical v0.4.2 and v0.5.1 source-era
layouts remain unchanged and MUST NOT acquire either new directory.

The two S3 directories are intentionally distinct. Their manifests use the
same `ESP32-S3` family and offset but their component and merged-image bytes
MUST differ: the lean directory excludes every display addition, while the
exact-board directory alone contains the frozen ST7789 runtime, companion,
splash-aware boot/QR, and native readiness seam. A symlink, hard link, copied
generic image, redirect, or shared manifest between them is invalid.

The profile's `firmware.bin` is the MicroPython/ESP-IDF-generated **merged**
image and is the only binary its profile-scoped ESP Web Tools manifest
installs. This follows ESP Web
Tools' ESP-IDF v4+ requirement: the browser tool cannot patch flash
mode/frequency/size headers across separate images on the fly. The manifest
therefore references one merged image at that image's base offset.

`application.bin` is the application component identified as `micropython.bin`
by the corresponding `flasher_args.json`. The bootloader, partition table, and
application components remain in the bundle for provenance, validation, and
advanced recovery, but the browser manifest MUST NOT flash them separately.
The release builder copies component bytes without transforming them and proves
that `firmware.bin` is the deterministic merge of those authoritative
components at the frozen settings and offsets.

The Pico `firmware.bin` is the raw RP2 image used for provenance and resource
measurement, not an ESP merged image or browser install fallback. The sole
Pico install artifact is `firmware.uf2`; it has no manifest, flash offset,
partition table, or component map.

Every manifest part path MUST be relative to its profile directory, remain in
that directory, and resolve on `https://pyble.dev`; absolute URLs, `..`,
redirects, cross-origin artifacts, and mutable aliases such as `latest` are
forbidden. For every v0.x release, the immutable same-origin directory is the
canonical public firmware distribution. A pre-v1 mirror is optional; when one
is published, every corresponding file and byte MUST equal the canonical
same-origin bundle. v1.0 and later MUST additionally publish the matching
byte-identical GitHub Release.

A published `v<version>/` directory is immutable. Successful artifact responses
(2xx and 304) receive immutable caching, but every 4xx or 5xx response below
`/firmware/` MUST receive `Cache-Control: no-store` and MUST NOT receive an
immutable directive. This prevents a transient publication or file-permission
failure from poisoning an edge cache for the lifetime of the release.

The signed metadata continues to contain canonical paths without query strings.
Browser retrieval MAY append exactly one deterministic `pyble_release` query
whose value is the build-selected `release.json` SHA-256. PyBLE MUST preserve
the canonical pathname, same-origin requirement, redirect rejection, exact
response URL check, size check, and SHA-256 check. The same deterministic query
MUST cover ESP Web Tools' later manifest and firmware fetches so an earlier
cached error cannot re-enter between verification and flashing.

HTML and the website's selected-release descriptor remain revalidating. A new
release updates the website's compile-time descriptor to a new exact version
path and expected `release.json` SHA-256; it never overwrites an old directory.

## 4. ESP Web Tools manifest

Each `<profile-id>/manifest.json` MUST use the documented ESP Web Tools schema,
contain only the installer fields understood by that tool, and contain exactly
one build for its owning profile. For example,
`esp32-s3-n16r8/manifest.json` is:

```json
{
  "name": "PyBLE",
  "version": "<version>",
  "new_install_prompt_erase": false,
  "new_install_improv_wait_time": 0,
  "builds": [
    {
      "chipFamily": "ESP32-S3",
      "parts": [{ "path": "firmware.bin", "offset": 0 }]
    }
  ]
}
```

`<version>` above is a template substitution, not literal released JSON.
`waveshare-esp32-s3-lcd-147b/manifest.json` has the same schema, family, and
offset, but it resides in the exact-board directory and references that
profile's different local `firmware.bin`; the two manifests and firmware paths
MUST never be substituted for one another.
The `esp32-4mb` manifest has the same shape and exactly one `ESP32` build with
offset `4096`; `esp32-c3-4mb` has exactly one `ESP32-C3` build at offset zero.
Pico has no manifest. The website MUST
set the custom element's manifest URL to the verified manifest for the selected
profile only. It MUST NOT pass an all-family catalog to ESP Web Tools or change
manifests after the browser has selected a serial device.

`new_install_prompt_erase: false` deliberately makes a new installation erase
the existing device. The website MUST explain this before activation and
require the user to acknowledge that the workspace and previous firmware will
be lost. PyBLE does not implement Improv Serial, so the manifest uses the
documented top-level zero Improv wait and does not invent a per-build field.

The manifest validator MUST reject unknown top-level/build/part keys, a missing
or extra build, a family other than the owning profile's family, a missing or
extra merged-image part, non-integer or out-of-range offsets, unsafe paths, a
version mismatch, or any difference from the profile table. It MUST also parse
the merged image, its ESP component images, and partition table sufficiently
to prove the expected chip target, base offset, image roles, component
placement, partition offsets/sizes, application fit, merge settings, and
declared flash capacity before publication.

## 5. Integrity metadata

The stock ESP Web Tools manifest has no artifact digest or byte-size fields.
PyBLE therefore MUST NOT invent non-standard digest fields inside
`manifest.json`. Integrity is carried separately by `release.json`, validated
by `release.schema.json` (JSON Schema draft 2020-12).

The release tool is the canonical producer of `release.schema.json`. Any
frozen consumer copy used by the web flasher MUST equal that generated JSON
object exactly, including deterministic array ordering; JSON-Schema semantic
equivalence is not sufficient for this fail-closed staging boundary. A
cross-component automated contract MUST compare the checked-in web copy with
the release-tool generator so the two cannot drift together with isolated
fixtures.

Every release-controlled JSON or TOML `schema_version` is type-strict: the
declared integer is accepted only as an integer, never as a boolean or
numerically-equal fractional value. This applies equally to build provenance,
the release-tool lock, license policy and shipment ledger, audit receipts, HIL
records, and `release.json`.

For historical split v0.5.x candidates, `release.json` schema version 3
MUST contain the following (the
version is the exact JSON integer `3`; booleans and numerically-equal
fractional values are invalid). Version 3 is an intentional incompatible
metadata revision: it freezes the exact three-profile order in §1 and MUST NOT
validate a shared/two-profile v0.5 candidate shape. Older immutable bundles
retain their own schema beside their metadata:

- `schema_version` = `3`;
- release identity: `version`, `tag`, `agent_version`, `protocol_version`, and
  UTC `built_at`;
- provenance: full PyBLE commit and clean state; MicroPython ref/commit;
  ESP-IDF ref/commit; patch count; runner and compiler/tool versions;
- one entry for each current release profile in the first table of §1,
  including profile ID, `chip_family`,
  flash/PSRAM requirements, flash mode/frequency, required
  `silicon_revision.minimum_full` and `silicon_revision.maximum_full` integers
  matching the §1 image window, and HIL status (`pending` for a candidate or
  the exact `v0.4.2` public beta, or `passed` for a qualified public bundle);
- one `manifest` entry per profile with its relative path, exact byte size, and
  lowercase 64-hex SHA-256;
- one `install` entry per profile for the merged image, with relative `path`,
  decimal base `offset`, exact byte `size`, and lowercase 64-hex `sha256`;
- exactly three `components` entries per profile for `bootloader`,
  `partition-table`, and `application`, each with its relative `path`, decimal
  flash `offset`, exact byte `size`, and lowercase 64-hex `sha256`;
- relative paths plus size/SHA-256 for `THIRD_PARTY_LICENSES.txt`,
  `RELEASE_NOTES.md`, `RECOVERY.md`, and `HIL_REPORT.md`; and
- the exact locally bundled `esp-web-tools` version used by the site.

The v0.6.0 successor MUST instead use release schema version `4` and exactly
the five-profile order in §1. It retains all schema-3 release identity,
provenance, document, and ESP profile fields and adds the required common
profile keys `target`, `provisioning_kind`, and `hil_status`. The four ESP
records use `provisioning_kind: "esp-web-serial"` and retain exact
`chip_family`, silicon/memory requirements, `manifest`, merged-image `install`
with offset, and three components. The Pico record uses
`provisioning_kind: "verified-uf2-bootsel"`, has exact target
`"rpi-pico2-w"`, and contains exactly:

- `board: "RPI_PICO2_W"`;
- `install: {path, size, sha256, format: "uf2"}` for
  `rpi-pico2-w/firmware.uf2`; and
- `resource_image: {path, size, sha256, image_limit_bytes: 1572864}` for
  `rpi-pico2-w/firmware.bin`.

The Pico record MUST reject `chip_family`, `silicon_revision`, `manifest`,
`offset`, `components`, or ESP flash/PSRAM fields. ESP records MUST reject
Pico `board`, `format`, `resource_image`, or BOOTSEL action fields. Schema 4
MUST reject a missing, extra, duplicated, or reordered profile.

The immutable public v0.4.2 bundle is the sole retained pre-split exception:
it keeps release schema version 2, exactly the historical ordered profiles
`esp32-4mb` and `esp32-s3-n16r8`, and its original files and hashes. Validation
MUST select that contract from exact release identity `0.4.2`, MUST reject a
third profile or schema 3 there, and MUST reject schema 2 or schema 3, any
two-/three-profile order, or historical artifacts for v0.6.0 source. No
validator, carry-forward
deployment, or website descriptor may reinterpret or expand the immutable
v0.4.2 tree.

All values are required; placeholders, `unknown`, and abbreviated commits fail
any bundle. `pending` is accepted only on an access-controlled candidate used
for HIL or the exact audited and digest-bound `v0.4.2` `public-beta` exception
in §10; an HIL
status other than `passed` fails every ordinary public bundle.
`release.schema.json`
itself is versioned and immutable beside the metadata. `SHA256SUMS` MUST use the
conventional lowercase-hex, two-space, relative-path format and cover every
file in the directory tree except `SHA256SUMS` itself.
The static website build embeds the exact versioned `release.json` URL and its
reviewed SHA-256. Before enabling the custom install element in a browser, the
client MUST:

1. fetch that same-origin metadata with redirects rejected;
2. verify the metadata bytes against the embedded SHA-256 using Web Crypto;
3. validate it against the local schema;
4. fetch the selected profile's declared `manifest.json` and merged install
   image;
5. verify every declared byte size and SHA-256;
6. cross-check that the manifest has exactly one build and that its version,
   family, path, offset, and install set match only the selected profile in the
   verified metadata; and
7. fail closed without rendering an active install control if any fetch,
   schema, path, size, digest, or cross-check fails.

The checked bytes and ESP Web Tools' subsequent requests are protected against
deployment races by immutable version paths. This checksum layer detects
corrupt or inconsistent publication; HTTPS and release-review controls remain
the trust boundary against a compromised origin.

## 6. Licensing and release notes

`THIRD_PARTY_LICENSES.txt` MUST be generated mechanically from the exact
resolved build inputs and include, for every redistributed dependency, its
name, version/ref, source URL, SPDX identifier, copyright notice, required
notice text, and complete license text. At minimum it covers upstream
MicroPython, the ESP-IDF components present in the binaries, and every frozen
MicroPython package. The build fails on an unrecognized, missing, or
license-incompatible dependency.

The firmware audit toolchain MUST pin `esp-idf-sbom` `1.2.0` and its complete
transitive Python closure by artifact hash in `firmware/release-tools.lock`.
The reviewed top-level wheel is
`esp_idf_sbom-1.2.0-py3-none-any.whl` with SHA-256
`a1444a7f23740c44cacbce4845efb5cbcb08927878b6a3852c33a52d8b2b5da9`
(upstream tag `v1.2.0`, commit
`d46a159ac239b9f843c59e0b4bfcfaff1859b862`). A changed tool or closure
requires review and a new lock; an unpinned environment MUST NOT generate a
public notice.

The conservative build audit runs against all eight authoritative ESP-IDF
descriptions: application and bootloader `project_description.json` for each
of the four ESP build variants. The v0.6.0 released notice classifies the
dependency union of all four packaged ESP profiles. A separate reviewed RP2
policy and observer MUST reconcile the exact linked ELF inputs, literal frozen
manifest, MicroPython core and `rp2` port, lwIP, Mbed TLS, littlefs, oofatfs,
libm, pico-sdk, BTstack, CYW43, TinyUSB, and pinned ARM GNU runtime/license
inputs. That inventory joins the released union without inventing or reusing
ESP-IDF SBOM evidence for RP2.
The immutable v0.4.2 replay instead retains its historical six descriptions
over three build targets and the redistributed dependency union of its two
packaged profiles. Validation MUST select the complete audit contract from
source identity and MUST NOT invent a Waveshare audit for v0.4.2.
The audit uses linked-only output (`--rem-unused --rem-config`) plus file tags,
runs with network access disabled, an isolated temporary home, and a committed
hash-pinned empty `SBOM_EXCLUDED_CVES_FILE`. UUIDs, timestamps, and absolute
paths in intermediate SPDX evidence are normalized before semantic comparison;
the released notice itself contains none of them.

`firmware/licenses/license-policy.json` is the reviewed, fail-closed mapping
from the exact raw package identities and resolved build inputs to immutable
source/ref metadata, SPDX expressions, applicability, complete license-text
path/SHA-256, required NOTICE path/SHA-256, and disposition. Raw tool metadata,
reviewed notice metadata, and resolved-input evidence are separate fields; a
stronger reviewed value MUST NOT be represented as if the raw tool emitted it.
Its `schema_version` is the exact JSON integer `2`; booleans and
numerically-equal fractional values are invalid.
The generator MUST:

- reconcile ESP-IDF SBOM packages with the archives actually included by both
  application and bootloader map files and with uniquely resolved
  `compile_commands.json` sources;
- inventory the exact frozen manifest inputs and reconcile them with the
  generated `frozen_content.c`, including the pinned upstream NeoPixel module;
- account explicitly for prebuilt ESP controller/PHY/Wi-Fi/coexistence blobs
  and compiler/newlib runtime archives, including the GCC Runtime Library
  Exception where applicable;
- treat a raw SBOM package's `NOASSERTION`/`NONE` as unresolved and
  release-blocking unless it uniquely matches an exact package identity,
  source/archive provenance, and profile/role applicability in a reviewed,
  hash-bound policy entry that supplies the SPDX expression, complete license
  texts, and required notices;
- reject a stale generated inventory, an unmapped or ambiguous object/archive,
  missing or ambiguous provenance, a missing or changed license/NOTICE text,
  an unknown SPDX identifier, an unapproved `LicenseRef`, or a policy-denied
  or review-required expression, and ensure the final generated inventory
  contains no `NOASSERTION`/`NONE`; and
- emit a stable, sorted union annotated by profile, deduplicating identical
  complete texts by their reviewed SHA-256, then produce byte-identical output
  in the second clean build.

**Independent RP2 policy and observer.**
`firmware/licenses/rp2-license-policy.json` is a separate reviewed, hash-bound
input. Its exact top-level keys are `schema_version`, `profile_id`, `target`,
and `source_owners`; `schema_version` is the exact JSON integer `1`, and the
identity is exactly `rpi-pico2-w`. Each canonical, identifier-sorted owner has
exactly `id`, `source_roots`, `source_ref`, `source_url`,
`source_spdx_expression`, `selected_spdx_expression`, `copyright`,
`license_texts`, `notice_files`, and `disposition`. A source root has exactly
`namespace` and `path`, where the namespace is `repo`, `micropython`, or
`arm-gnu-toolchain`; a license-text record has exactly `identifier`, `path`,
and `sha256`; and a notice record has exactly `path` and `sha256`. Lists are
nonempty where applicable, unique, and canonical. The most-specific lexical
root in one namespace owns an input; no owner or equal-specificity ambiguity
is fatal. Every owner MUST contribute an observed input, while every observed
input has exactly one owner. Separate owners are required where one dependency
contains linked subcomponents under different terms, and the source and
selected expressions remain distinct (including the Mbed TLS choice and the
compiler/newlib runtime classes). Thus the catalog represents every mandatory
dependency class below but is not an unsafe fixed-count allowlist. A boolean
or numerically equal fractional schema version is invalid. The policy MUST NOT
import an ESP package identity or resolution as proof for an RP2 input.

The observer starts from the exact retained `firmware.elf`, its
`CMakeFiles/firmware.dir/link.txt`, `firmware.elf.map`, CMake cache, build
provenance, archives, and direct objects. All are regular non-symlink files
below their admitted roots. It tokenizes `link.txt` as one shell-free argument
serialization: quoting and escaping are decoded, but shell control,
redirection, substitution, response-file syntax (including driver-wrapped
forms), duplicate operands, path escape, an unknown operand shape, or a
missing/extra link input is fatal. The GNU linker map is parsed structurally,
never by substring or basename. Exact archive/member contributors and direct
object `LOAD` records MUST reconcile one for one with the link arguments and
existing bytes; command-listed non-contributors are recorded as such and are
not presented as shipped. Every contributing object is owned by exactly one
source and one reviewed dependency class. An unowned, ambiguously owned,
duplicated, map-only, or link-only input is fatal.

The linked-object inventory also determines the complete compiler-dependency
closure. Each C/C++ object named by the final firmware target has exactly the
compiler depfile declared by its DependInfo record. Assembly records, for
which CMake emits no `.o.d`, bind their source bytes directly; depfiles for
unlinked host tools such as `pioasm` are not firmware inputs. Counts are
derived from the build and are never a policy allowlist. The observer parses
GNU Make depfile escaping and line continuation without invoking Make or a
shell, requires the one declared target to equal the corresponding object, and
hashes the depfile plus every unique dependency byte. A variable, function,
directive, second rule/target, malformed escape, missing or extra target depfile,
missing dependency, path escape, symlink, non-regular file, or dependency
outside the admitted repository, retained checkout, selected build, and ARM
GNU roots is fatal. Every dependency is attributed to one most-specific RP2
policy owner. A generated build dependency is admitted only through an exact
recorded derivation whose source/configuration inputs are themselves owned and
hashed; generated bytes never create an inferred license owner. The semantic
hash, all seven RP2 role documents where applicable, and public replay cover
the depfile bytes, object/source relationship, ordered dependency records,
owner identity, and dependency bytes.

This closure MUST distinguish license classes that a source-only link
inventory would collapse. In particular:

- `lib/libm/libm.h` is a compiled dependency with its combined retained
  musl/Sun attribution; it is not covered by the MIT-only `math.c` owner;
- `lib/libm/fdlibm.h` retains the Sun fdlibm grant and MicroPython adaptation
  terms and is owned with the exact fdlibm class, not a broad MicroPython or
  MIT-only fallback;
- the selected `lib/re1.5` compiler dependencies are BSD-3-Clause and the
  selected `lib/uzlib` compiler dependencies are Zlib; each observed file is
  assigned to its exact component owner rather than a broad `lib/` or
  MicroPython owner (unobserved differently licensed files in either
  directory cannot widen that root);
- CMSIS Core headers carrying Apache-2.0, the dual-marked RP2350 system source
  and system header, and Raspberry Pi BSD-3-Clause device/exception headers
  are separately owned at their most-specific paths;
- GCC built-in headers and newlib target headers are distinct ARM GNU owner
  classes and are not covered merely because a runtime archive was linked;
  and
- the selected Pico 2 W CYW43 payload closure is exactly
  `firmware/wb43439A0_7_95_49_00_combined.h` (Wi-Fi/CLM),
  `firmware/cyw43_btfw_43439.h` (Bluetooth), and
  `firmware/wifi_nvram_43439.h` (NVRAM), all below the selected retained
  CYW43 checkout. All three MUST occur in the exact depfile graph, be
  independently hashed and owned, and no same-directory alternate radio
  payload may substitute or be added.

The CYW43 directory is not one license owner. The ordinary driver sources are
one exact owner selected under the Raspberry-Pi-device grant, while each of
the three payload paths above is a separate, most-specific owner. For the
exact `rpi-pico2-w` closure, the Wi-Fi/CLM payload, signed Bluetooth firmware,
and Broadcom-attributed NVRAM are each selected under
`LicenseRef-PyBLE-CYW43-Raspberry-Pi`. Each owner MUST remain `allow`, retain
the complete non-commercial/Raspberry-Pi source choice and both exact license
texts, and select only the Raspberry Pi arm. The Broadcom NVRAM attribution
MUST also remain present.

That selection is an engineering compliance decision for one deliberately
narrow use, backed by the following frozen primary evidence:

- MicroPython pins cyw43-driver tag `v1.1.1`, commit
  `055d64274b014dd7b1c2fc94d26e8a18face7124`. Its 1,789-byte
  `LICENSE.RP` has SHA-256
  `67aca4f10d9edf489871f64cd8f0dcd6c5df3e4ce75bd39e1914fc54f99e40b3`
  and is byte-identical to the file introduced by cyw43-driver commit
  `195dfcc10bb6f379e3dea45147590db2203d3c7b`;
- commit `195dfcc10bb6f379e3dea45147590db2203d3c7b` is the immediate child of
  `92397a4b5954f02e17550d0b6a1d9597b4475adc`, which added the repository's
  Wi-Fi/CLM and NVRAM payload directory. The same maintainer committed the
  repository-wide Raspberry Pi grant nine seconds later, and the top-level
  README applies its license choices to "this cyw43-driver" without excluding
  `firmware/`;
- Raspberry Pi's official documentation at commit
  `41e21a979c608b2dcaaa38bc28cc994f1bcf6774` states that Raspberry Pi
  negotiated the special commercial rights for `libcyw43`, expressly includes
  the RP2350 + CYW43439 combination, and links cyw43-driver's `LICENSE.RP` as
  the full commercial license. The exact 32,478-byte source
  `documentation/asciidoc/microcontrollers/pico-series/about_pico.adoc` has
  SHA-256
  `34b7606e69e69a3786b81387f1cdf32a24319b02c9bbaf3185eab7b9ae1713ec`;
  and
- those official scope statements post-date the last selected payload-header
  changes and the selected `v1.1.1` tree retains the same grant without a
  file-specific conflicting license on any of the three selected paths.

The decision applies only when the exact three hash-bound payloads are bundled
with the pinned official cyw43-driver through the retained MicroPython/pico-sdk
integration, built for `PICO_BOARD=pico2_w` and RP2350, and used with the
board's CYW43439. The release MUST identify that hardware/profile restriction
and reproduce the complete grant notice, conditions, and disclaimer in its
third-party materials. It does not decide whether any blob may be redistributed
standalone, with a third-party Wi-Fi stack, for another radio, or for a
non-Raspberry-Pi semiconductor. cyw43-driver issue 1 asks that distinct
standalone/third-party-stack question and supplies no contrary answer for this
official-driver use. A target, driver, payload, or packaging-scope change
returns the affected owner to `review-required` pending a new review.

That no-gap ownership covers every linked or frozen input and, at minimum,
the selected MicroPython core and `ports/rp2` sources, lwIP, Mbed TLS,
littlefs (LFS1/LFS2), oofatfs, libm, pico-sdk, BTstack, CYW43 driver, TinyUSB,
and ARM GNU runtime archives. The exact compiler-supplied `libgcc`, newlib
`libc`/`libm`, and any other contributing runtime archive and its applicable
runtime exception/terms are observed rather than inferred from the compiler
name. A similarly named source tree, a configured but non-contributing
library, or a directory-wide scan cannot fill a gap.

The retained MicroPython checkout MUST equal the exact locked commit, clean
tree, and canonical origin in build provenance. Every selected nested
checkout—including `lib/lwip`, `lib/mbedtls`, `lib/pico-sdk`, `lib/btstack`,
`lib/cyw43-driver`, and `lib/tinyusb`—is independently bound to its exact
gitlink/submodule SHA, clean tree, canonical origin, and selected path. Nested
copies below pico-sdk do not substitute for the selected MicroPython paths:
the observer proves the actual CMake-selected checkout for each linked object.
A dirty checkout, missing gitlink, origin drift, SHA mismatch, alternate
worktree, symlink, or source path inconsistent with the CMake cache and map is
fatal.

The CMake identity is also exact rather than implied by a board-directory
name. For the initial RP2 release the cache MUST select `PICO_BOARD=pico2_w`,
`PICO_PLATFORM=rp2350-arm-s`, and the retained
`PYBLE_RPI_PICO2_W` MicroPython board directory. Its C and ASM compiler
frontends are the pinned `bin/arm-none-eabi-gcc`; its C++ frontend is the
pinned `bin/arm-none-eabi-g++`; and the corresponding `PICO_COMPILER_CC`,
`PICO_COMPILER_ASM`, and `PICO_COMPILER_CXX` values MUST agree. Every distinct
frontend is a regular, symlink-free, hash-bound input below the one selected
ARM GNU root. Missing, additional, mixed-root, PATH-selected, basename-only,
or disagreeing CMake/Pico compiler identities are fatal.

An installed ARM GNU version string is not distribution provenance. The
`[arm_gnu_toolchain]` lock binds the official binary-distribution HTTPS URL,
URL-basename filename, size, SHA-256, archive format/root, the exact installed
release-manifest relative path/SHA-256, and the required compiler frontend
relative paths/SHA-256 values. The installer retains the verified official
archive at the observer-derived
`<toolchain-root>/.pyble-dist/<URL-basename>`; neither policy nor caller may
supply another cache path. The observer safely parses that exact archive and
byte-compares every observed frontend, compiler/newlib header, runtime input,
and installed release manifest with its unique archive member below the
pinned top-level root. Unsafe/duplicate archive entries, an absent cache,
metadata disagreement, installed-only evidence, or any installed/archive byte
drift is fatal. The separate official source snapshot remains the source and
license-attribution proof; it does not replace this installed-binary proof.

The RP2-specific grants are selected literally rather than approximated by a
nearby license. In particular, BTstack retains both its stock non-commercial
license and pico-sdk's complete supplemental `pico_btstack/LICENSE.RP` grant,
and selects only that supplemental grant for use with Pico 2 W. The ordinary
CYW43 driver sources and each of its three separately owned, exact selected
payloads retain the complete Raspberry-Pi-device grant used for Pico 2 W and
select that grant under the evidence and scope restriction above. Sharing that
selection does not merge their owners or weaken their independent header and
embedded-byte bindings. Neither dependency's generic non-commercial file, nor
either Raspberry Pi grant, is relabelled as BSD or MIT.
Mbed TLS retains its source choice while recording the reviewed Apache-2.0
redistribution selection;
littlefs, lwIP, pico-sdk, oofatfs, TinyUSB, MicroPython, fdlibm-derived libm,
and each contributing ARM GNU/newlib class retain their own exact expressions,
exceptions, copyright notices, and complete texts. One broad MicroPython MIT
record or one toolchain expression cannot cover these distinct inputs.

RP2 frozen inputs are resolved without executing manifest code. Only the
reviewed literal manifest operations and literal arguments may select a
manifest, module, package, source, destination, optimization, or metadata
value. Imports, assignments, control flow, computed arguments, unknown calls,
directory recursion, unresolved variables, duplicate destinations, path
escape, and symlinks are fatal. Every traversed manifest and selected source
is hashed, and the literal result MUST reconcile exactly with the generated
frozen content and the linked object that contains it.

For every resolved RP2 dependency the policy identifies the complete reviewed
license bytes and every redistribution-required notice/attribution byte; a
filename, SPDX label, package directory, installed copy, or upstream URL alone
is not proof. Changed, missing, partial, ambiguous, incompatible, or
unreviewed bytes fail closed. The final notice may deduplicate identical
complete texts only by their reviewed SHA-256.

Approval of a custom `LicenseRef` is owner-scoped and adds no global approval
list to the schema. An `allow` or `project-owned` owner may use only the
`LicenseRef` tokens occurring in that same owner's exact source/selected
expressions and covered by that same owner's exact
`license_texts.identifier/path/sha256` records. A matching token or text on a
different owner grants no authority. A `review-required` owner remains fully
observable, hash-bound, and eligible for engineering evidence, but it is
release-blocking and generation publishes nothing until an independent review
changes that exact owner to `allow`; changing the disposition changes the
semantic hash.

The RP2 observer records a canonical semantic hash plus every exact input
path/SHA-256 before any of the eight v0.6 ESP SBOM executions. After those
executions and immediately before evidence and notice publication, it repeats
the complete observation and requires identical hashes and semantics. This
second observation includes the ELF, link command, map, CMake cache,
provenance, every archive/object/source, literal frozen inputs and generated
output, checkout/git metadata, policy, license/notice bytes, and toolchain
runtime inputs. Replacing bytes while restoring timestamps is therefore
fatal.

The v0.6 audit emits a canonical `audit-receipt.json` with exact JSON integer
`schema_version: 2`. It binds the notice, complete input/evidence hashes,
execution identity, release inventory, all eight ESP role identities, and
exactly these seven RP2 evidence roles: `linked-inputs`, `frozen-modules`,
`pico-sdk`, `btstack`, `cyw43`, `tinyusb`, and `arm-gnu-runtime`. The canonical
schema-v1 `release-inventory.json` contains exactly the five release profiles
in policy order, binds each packaged provenance, and distinguishes each ESP
application/bootloader raw and reviewed document from the Pico role
documents. A missing, extra, duplicated, reordered, cross-profile, or
self-consistently rehashed substitution is fatal. Generation uses a new
destination and publishes nothing unless the existing complete ESP audit and
this independent RP2 audit both pass; public verification repeats both from
the exact packaged builds.

The generated evidence directory and `THIRD_PARTY_LICENSES.txt` are one
publication unit, not two independently replaced paths. The production audit
accepts a single new publication root whose exact children are `evidence/`
and `THIRD_PARTY_LICENSES.txt`. It prepares and fsyncs both children in a
same-filesystem hidden sibling and commits the absent publication root with
one no-replace rename. The destination parent already exists and is a regular
non-symlink directory, while the publication root itself MUST be absent. A
crash before the rename leaves neither public child; a crash after it leaves
both. A concurrent creator wins without any byte being overwritten. An API
that accepts legacy evidence/notice paths MUST require those paths to have the
same absent parent and the exact child basenames above; arbitrary sibling
outputs below an existing mixed-content directory are rejected because POSIX
cannot commit them as one crash-atomic unit.

The following ESP-IDF resolution rules are part of that fail-closed mapping:

1. The v0.6 audit retains all eight **exact raw** `esp-idf-sbom` outputs and
   eight normalized reviewed SPDX documents. Retained source-era v0.5.1 and
   v0.4.2 evidence keeps its frozen historical count and shape; it is never
   expanded to resemble v0.6. Raw tag/value files use `.spdx.tag`;
   only normalized JSON files use `.spdx.json`. The receipt hashes both sets,
   the exact raw package-property sets and complete relationship multisets, the
   locked wheel closure and execution/isolation identity, and every exact
   build, policy, map, manifest, source, archive, license, and NOTICE input.
   Raw bytes are never overwritten by normalization or discarded after a
   successful audit.
2. Frozen files are resolved without executing manifest code, from the literal
   `include`, `require`, `package`, `module`, and non-selecting `metadata`
   operations of the hash-bound pinned manifests. Imports, assignments,
   control flow, computed arguments, unknown calls, unresolved variables,
   path escape, symlinks, duplicate destinations, and unrecognized package
   resolution are fatal. Directory recursion is not a manifest resolver.
   Every traversed manifest and selected source is receipt-hashed, and the
   resolved set MUST exactly equal `frozen_content.c`. Thus the pinned asyncio
   manifest includes its six declared `asyncio/*.py` files and root
   `uasyncio.py`, but not `manifest.py` or the C-provided `task.py`.
3. A System V/GNU/BSD archive is structurally parsed as an ordered multiset.
   Repeated member basenames are permitted because ESP-IDF legitimately
   produces them. Every first-column map occurrence MUST have a corresponding
   archive-member occurrence, and a map count exceeding the archive count is
   fatal. Malformed headers, names, long-name tables, sizes, padding, trailing
   bytes, symlinks, or special files are fatal. The exact archive and map bytes
   are receipt-bound, so duplicate basenames cannot admit an unrecorded
   archive or member.
4. Every `project_description.json` component `sources` entry MUST resolve
   without symlinks below the repository or selected build root. A regular-file
   entry MUST appear in `compile_commands.json` except for the following exact
   generated-header shape in an application `main` component: the entry is a
   direct regular-file child of the selected role build's `genhdr/` directory
   and its basename is exactly one of `compressed.data.h`, `moduledefs.h`,
   `mpversion.h`, `pins.h`, `qstrdefs.generated.h`, or `root_pointers.h`.
   Those six non-translation inputs are receipt-hashed but are not assigned an
   archive member.

   ESP-IDF may also emit an existing directory as a source marker; that marker
   is admitted only at or below the same component's declared source
   directory, and it describes only compile-command source files recursively
   below it. It does not recursively add uncompiled files to the license
   inventory.

   Every compile-command source MUST still be covered by an exact described
   file, an admitted described directory marker, or a `CONFIG_ONLY` component
   root, except for these pinned application-`main` inputs:

   - the nine repository-owned files
     `firmware/user_c_modules/pyble/{pble_proto,pble_ble,pble_info,pble_device_config,pble_runner,pble_console,pble_fs,pble_lock,pble_boot}.c`;
   - the fourteen files in the selected target's immutable retained
     `.sources/<target>/micropython/lib/berkeley-db-1.xx` tree:
     `btree/{bt_close,bt_conv,bt_debug,bt_delete,bt_get,bt_open,bt_overflow,bt_page,bt_put,bt_search,bt_seq,bt_split,bt_utils}.c`
     and `mpool/mpool.c`; and
   - the exact zero-byte role-root file
     `project_elf_src_<idf-target>.c`, where `<idf-target>` is the literal
     `project_description.json` target. The same anchor is the sole
     compile-source exception in each bootloader role.

   A missing file, unexpected basename, alternate or sibling retained tree,
   escaped path, near-match root, nonzero generated ELF anchor, or symlinked
   input is fatal.

5. A generated component archive has only a stable topology matcher in
   committed policy. An ordinary matcher contains exactly its ESP-IDF
   component name. A nested CMake archive produced below a `CONFIG_ONLY`
   owner additionally contains one explicit selector with the nested target,
   build-relative archive path, and build-relative object directory. The
   nested form is valid only when the named owner is exactly `CONFIG_ONLY`,
   has empty `file` and `sources` properties, the archive is a unique linked
   map input, every selected compile output is below the exact object
   directory, and the compile-output basename multiset equals the archive
   member multiset. Its logical source paths MUST remain below the immutable
   reviewed owner source tree. This is the narrowly admitted shape used by
   Mbed TLS's `mbedcrypto`, `mbedtls`, and `mbedx509` targets. Their separately
   compiled Everest and p256m object-library outputs are build-only/unlinked;
   they MUST NOT be assigned to `libmbedcrypto.a`. A synthetic component,
   path-only selector, or transitive object directory is not accepted.

   Ordinary component membership is selected by compile **output** topology,
   not by a set of unique source paths: the exact object root is
   `<archive-parent>/CMakeFiles/<component-lib>.dir`, using the component's
   literal `file` and `lib` fields. This distinction is required because each
   admitted PyBLE C source is compiled once into `libmain.a` and once directly
   into the application ELF. The selected output-basename multiset MUST equal
   the parsed archive-member multiset exactly. Each selected source MUST also
   belong to that same component's exact described file or directory marker;
   an application `main` archive may additionally own the exact nine pinned
   PyBLE sources above. A file or root described by one component MUST NOT
   authorize a linked output owned by another component, and the pinned
   Berkeley DB sources remain direct-object-only.

   A relative JSON `file` field resolves against the command's `directory` and
   MUST equal its literal `-c` source. A relative JSON `output` field resolves
   against the role build containing `compile_commands.json`, while the
   compiler's literal `-o` argument resolves against the command's
   `directory`; those output paths MUST resolve to the same existing regular,
   symlink-free file. This rejects plausible but wrong source/output evidence
   assembled under the wrong base. Operand traversal MUST be validated in its
   original lexical order: `..` MUST NOT be collapsed before checking an
   earlier symlink component. A string-form compiler `command` MUST be one
   shell-free argument serialization: shell control, redirection, command
   substitution, and response-file syntax (including driver-wrapped
   `-Wl,@...`) are fatal. An `arguments` array is already direct argv and is
   not interpreted as shell text, but response-file syntax is still fatal.

   ESP-IDF legitimately emits compile commands for build-only objects that the
   selected executable does not link. Therefore every **linked** compile output
   MUST be consumed exactly once, either by one generated archive member or by
   one exact direct-object `LOAD` path in the same linker map. Every exact map
   direct-object `LOAD` MUST resolve to one compile output. A remaining compile
   output is classified as unlinked and MUST NOT be assigned to a generated
   archive/input merely because its basename matches a linked member. Its
   logical source path remains in the hash-bound compile-command document and
   must still pass the source-root rules above, while its output and source
   bytes are excluded from the redistributed-input binding. They do not affect
   the shipped ELF and are not release inputs merely because ESP-IDF built
   them.

   Direct objects are admitted only in these pinned topologies:

   - `CMakeFiles/<app-elf>.dir/project_elf_src_<idf-target>.c.obj` for the
     zero-byte role-root ELF anchor;
   - application `CMakeFiles/micropython.elf.dir/<absolute-PyBLE-source>.obj`
     for the nine repository-owned PyBLE C sources; and
   - application
     `esp-idf/main/CMakeFiles/micropy_extmod_btree.dir/<absolute-retained-source>.obj`
     for the fourteen retained Berkeley DB sources.

   Each direct output MUST be a regular, symlink-free file below the selected
   role build, and the map MUST name its exact build-relative path once after
   the following one narrow lexical normalization. Within an otherwise exact
   direct-object `LOAD` token, a segment whose complete value is `.` is
   redundant and MUST be removed before build-root containment, component
   symlink checks, exact compile-output matching, and duplicate accounting.
   This syntax rule applies uniformly to every direct object; it is not a
   Berkeley DB source or topology exception. The raw map bytes remain
   receipt-bound. No other map-path normalization is permitted: `..`, an empty
   segment (including repeated `/`), a backslash, an absolute path, a symlinked
   component, or a normalized path absent from the exact compile-output set is
   fatal.
   Exact generated-header, source-exception, anchor, and direct-output
   topologies MUST be checked lexically for symlink components before any
   canonical-path equality check; an alternate path resolving to the same
   bytes is not equivalent. Receipt records for files below the selected build
   root MUST use `build/<build-relative-path>` even when that build root is
   itself nested below the repository root.
   ESP-IDF's Ninja generator does not emit
   `CMakeFiles/<app-elf>.dir/link.txt`; absence of that Makefile-generator
   artifact is not license evidence. The deterministic final-link source is
   instead the exact role-root `build.ninja` and its one literal
   `include CMakeFiles/rules.ninja`. The auditor MUST NOT execute Ninja, trust
   the build invocation/environment/log, or fabricate a `link.txt`. It uses a
   bounded, non-executing parser for only the pinned CMake-generated shape to
   reconstruct the final linker argv and direct-object set. Both graph inputs
   MUST be stable regular non-symlink files below the role build.

   The admitted graph has exactly one edge whose sole explicit output is the
   literal relative project-description `app_elf`, exactly one referenced rule
   declaration in the literal role-relative rules file, exactly one `|` and
   one `||` dependency separator, and the exact ten edge assignments `FLAGS`,
   `LINK_FLAGS`, `LINK_LIBRARIES`, `LINK_PATH`, `OBJECT_DIR`, `POST_BUILD`,
   `PRE_LINK`, `TARGET_COMPILE_PDB`, `TARGET_FILE`, and `TARGET_PDB`.
   `TARGET_FILE` MUST equal `app_elf`; `PRE_LINK` and `POST_BUILD` MUST each be
   the shell no-op `:`. The edge, assignments, and the rule's single `command`
   template permit no continuation, quote, escape, embedded newline, response
   file, substitution, or shell operator other than the rule's exact two `&&`
   separators around those no-ops. Expansion is confined to the known edge
   assignments plus Ninja's literal `$in`/`$out` values; no other variable or
   Ninja construct is interpreted. Edge-assignment values cannot themselves
   contain variables, which makes a variable cycle fatal; the rule's
   non-command description/restat metadata cannot add command inputs.

   After expansion, the safely tokenized command MUST contain one absolute
   compiler frontend already admitted by the toolchain contract, one exact
   `-o <app-elf>`, and a sorted-unique set of canonical build-relative
   `.o`/`.obj` operands. Absolute/escaping objects, duplicate operands, or any
   other output are fatal. That set MUST equal both the normalized map `LOAD`
   set and the exact linked subset of compile outputs. The receipt binds
   SHA-256 of the exact two Ninja files and `linker_command_sha256`, defined as
   SHA-256 of the reconstructed argv encoded as canonical compact JSON plus
   one final LF. The same derivation is repeated after all eight SBOM runs and
   during public replay. An alternate include, nested `include`/`subninja`,
   duplicate edge/output/rule/assignment, unknown escape or variable, path
   escape, or any graph/map/compile/ELF mismatch is fatal. Parsing is
   resource-bounded and never becomes a general Ninja interpreter.
   Basename-only matching is forbidden.

   One logical source may therefore have multiple compile outputs. Archive
   source records remain archive-only and unique by logical path. The role's
   generated `main` binding additionally contains:

   - `linker_command_sha256`, the canonical reconstructed-argv digest,
     `build_ninja_sha256`, and `rules_ninja_sha256` for the exact
     `build.ninja` and `CMakeFiles/rules.ninja` bytes;
   - `metadata_inputs`, the canonical logical path/SHA-256 records for the six
     application `genhdr/` inputs (empty for bootloader); and
   - `direct_objects`, canonical records containing each direct output's
     logical path/SHA-256 and its compile source's logical path/SHA-256.

   The `main` binding is invalid unless those three fields are present and
   exactly cover the role evidence. Duplicate linked consumption, an extra or
   missing direct `LOAD` or link-command object, a wrong direct-output root, an
   archive/output multiset mismatch, or treating an unlinked output as
   redistributed is fatal.

   `project_description.json`, `compile_commands.json`, map, canonical link
   command, and both Ninja-file SHA-256 values,
   generated source and auxiliary-input hashes, compile-output/direct-`LOAD`
   and linker-command reconciliation, direct object/source hashes, member
   lists, and the final archive SHA-256 are
   observations of one build. They MUST be retained in the validated receipt
   binding and MUST NOT appear in committed policy. Two clean builds in
   different absolute roots use the same stable policy even when their exact
   generated-document hashes differ. The receipt for each build still binds
   its own hashes, logical source inventory, member multiset, and archive
   digest. A policy field that attempts to predeclare or override one of those
   generated values is fatal. An opaque prebuilt archive, a frozen source
   tree, or a compiler/runtime archive has no such exception: its digest is
   predeclared in reviewed policy and MUST match exactly.

   After all eight v0.6 offline SBOM executions, the observer MUST rebuild this
   exact generated-input context and require byte-for-byte equality with the
   initial observations. A source-era verifier uses its frozen historical
   count. Rechecking only archive/tree digests is insufficient:
   project/compile/map/link/Ninja documents, metadata inputs, archive sources,
   direct outputs, and direct sources are all race-sensitive release inputs.

6. An archive outside the repository and build roots is admitted only below
   one versioned toolchain root proven by the exact compile-command
   executables and the locked ESP-IDF `tools/tools.json` entry. The policy
   predeclares the tool name, ESP-IDF version key, platform key, and one exact,
   nonempty `compiler_frontends` catalog. Each frontend record contains only
   its constrained installed-root-relative path and SHA-256; paths are unique
   and canonically ordered. The initial Xtensa and RISC-V catalogs contain
   exactly their prefixed `gcc` and `g++` frontend pair. A singular
   representative compiler is insufficient.

   Every compile-command entry's absolute executable MUST be consumed by
   exactly one declared frontend, and every declared frontend MUST be
   observed. Repeated commands using the same executable do not create a new
   frontend identity. Missing, extra, or duplicate frontend identities are
   fatal. All frontends for one toolchain MUST derive the same installed root,
   trusted ESP-IDF tools home, metadata entry, and cached distribution; a
   sibling installation or mixed tools homes is fatal.

   The distribution record contains exactly the HTTPS URL, logical filename
   (the URL basename), byte size, SHA-256, archive format, and top-level
   archive root. The archive root is distinct from the installed version
   directory: for example, the versioned installation may be
   `tools/xtensa-esp-elf/esp-14.2.0_20241119/xtensa-esp-elf` while the archive
   root is only `xtensa-esp-elf`. A repository-relative distribution `path`
   is forbidden; the 453 MB pinned Xtensa/RISC-V downloads are never vendored.

   The observer derives one trusted ESP-IDF tools home from the exact frontend
   path set, the installation layout, and the repository's pinned ESP-IDF
   metadata. It then derives the cache entry as
   `<tools-home>/dist/<logical-filename>`. Neither policy nor caller may supply
   a cache root/path, alternate metadata path, or arbitrary toolchain root.
   The metadata entry MUST exactly agree with the policy URL, filename, size,
   SHA-256, name, version, platform, export path, and archive root. The tools
   home, its `tools/` and `dist/` directories, the versioned installation, the
   frontend/runtime inputs, and the cached archive MUST have no symlink
   ancestor or terminal symlink and MUST remain below that tools home.
   Filename mismatch, missing cache bytes, size/digest mismatch, unsafe archive
   entry, root mismatch, or a sibling/caller-selected installation is fatal.

   During the offline audit the matching cached archive is size/digest
   verified and safely read. Every frontend MUST be a regular, non-symlink
   installed file, match its reviewed SHA-256, and be byte-identical to the
   corresponding member of that exact cached distribution. Every admitted
   compiler/runtime archive is likewise byte-compared with its counterpart in
   the distribution. Private observations retain the exact absolute frontend
   paths required to prove the build. Validated evidence and receipts record
   only logical metadata, semantic hashes, constrained relative frontend/member
   paths, and distribution identity; they MUST NOT contain a host-absolute
   tools-home, cache, frontend, installed-root, or runtime path.

7. Each raw package is matched exactly once by profile/role and its complete
   raw property set, including name, version state, download-location state,
   copyright state, declared/concluded license states, checksums, annotations,
   external references, and relationship multiset. `NOASSERTION`/`NONE` is an
   expected literal state, never a wildcard. SPDX `PackageVersion` is optional:
   if the raw tag/value document omits it, the parsed package and exact raw
   policy both omit `versionInfo`. Absence is not synthesized into `""`,
   `NOASSERTION`, or a reviewed version. The release build hydrates its
   isolated source copy with resolved ESP Component Manager metadata before
   SBOM generation. Every property the pinned tool then emits for a
   managed component—including version, supplier, originator, summary,
   download location, external references, copyright, and concluded
   expression—is retained as exact raw evidence and frozen in policy; it is
   not discarded merely because an earlier clean build emitted a sparse
   package. Presence/absence and any present bytes must agree exactly; an
   explicitly empty tag remains malformed.

   Policy keeps three distinct values: the exact raw concluded state, the
   reviewed raw-package expression used in normalized evidence, and each
   resolved redistributed input's expression used in the public notice. A
   concrete raw concluded expression MUST parse and equal the reviewed
   raw-package expression; it is preserved even when it describes the broad
   toolchain distribution rather than the narrower linked runtime inputs.
   When redistributed inputs have different reviewed terms, the reviewed
   package declares a nonempty, unique `reviewed_input_expressions` allowlist.
   If omitted, its only allowed input expression is the reviewed raw-package
   expression. A resolution expression MUST equal one complete allowlisted
   expression, not merely use an identifier subset. Complete license texts
   exactly cover the union of the raw-package and allowlisted-input
   expressions. Thus the concrete broad GCC/toolchain raw expression remains
   unchanged in normalized evidence while the exact reviewed
   GPL-with-GCC-exception/newlib runtime expression is used for the linked
   inputs and public notice. A raw unresolved expression may be resolved only
   by one exact source/input-bound reviewed entry, with attribution naming that
   entry. Immutable reviewed version/source/copyright values populate only the
   normalized document and notice; they are not falsely compared with weaker
   raw fields. Raw occurrences with different concrete concluded expressions
   MUST use distinct reviewed package records and resolutions even when they
   share the same SPDX ID in different profiles; a union expression MUST NOT
   be invented to make unlike occurrences share one review. Any unexpected
   property, value, package, relationship, resolution, or ambiguity is fatal.

8. A raw package that the pinned tool reports but that contributes no linked
   archive, compiled source, or aggregate project identity may be excluded
   from the redistribution notice only through an explicit `not-shipped`
   disposition and an exact zero-input proof for that profile/role. Committed
   zero-input proof contains only the exact profile/role and an empty
   `matched_input_ids`; it MUST NOT predeclare project-description,
   compile-command, or map hashes. The validator derives those three hashes
   from that build into the validated proof. The receipt semantic hash covers
   the derived proof, so a different build cannot reuse its receipt even
   though both builds share stable policy.

   A shipped aggregate/framework/source package with no exclusive input uses
   `allow-aggregate`, an empty `input_refs`, and exactly one proof per
   profile/role package reference. Each proof contains a nonempty simple path
   of exact raw SPDX relationships from the aggregate package to a raw package
   owned by a named `allow` resolution with nonempty inputs in the same
   profile/role. Every edge must occur in that raw document, consecutive edges
   must join, and the terminal package must actually be consumed by the named
   input-owning resolution. The aggregate appears in the public notice but
   consumes no input; pointing at another aggregate/not-shipped resolution,
   reusing the target's inputs, inventing an edge, cycling, crossing a
   profile/role, or substituting `not-shipped` is fatal. This form covers the
   shipped NimBLE, ESP-IDF, FreeRTOS, lwIP, project, and heap-TLSF aggregate or
   source occurrences that do not own an exclusive archive.

   Top-level policy field `shipment_review` contains exactly a
   repository-relative `path` and SHA-256 for an independent reviewed
   shipment ledger. That strict UTF-8 canonical JSON document has the exact
   JSON integer `schema_version: 1` (not a boolean or fractional number) and
   an `occurrences` array containing exactly
   `{profile_id, role, spdx_id, disposition}` per raw package occurrence,
   sorted lexically by `(profile_id, role, spdx_id)`. It covers every exact raw
   occurrence once with no extras, and each disposition is exactly `allow`,
   `allow-aggregate`, or `not-shipped`. The ledger contains no build hash and
   is not duplicated as another mutable field inside a resolution.

   Every resolution disposition MUST agree with its ledger occurrence.
   Therefore changing an otherwise fully formed aggregate resolution and its
   zero-input proof together to `not-shipped` remains fatal when the
   independent ledger says `allow-aggregate`. The receipt binds both the
   `shipment_review` policy record and the normalized occurrence
   classifications.

9. A redistributed dependency absent from the raw ESP-IDF package graph is a
   deterministic supplemental SPDX package, not misrepresented as raw tool
   output. In this release the exact frozen NeoPixel tree and the three linked
   Mbed TLS archives (`libmbedcrypto.a`, `libmbedtls.a`, and
   `libmbedx509.a`) omitted by the raw graph are supplemental packages related
   to their owning MicroPython/ESP-IDF package. Their source trees, generated
   inputs, license text, frozen/linked proof, and relationship are all
   receipt-bound. A supplemental package records its
   `source_spdx_expression` separately from its
   `selected_spdx_expression`. The selected expression must be one exact
   top-level choice arm admitted by the source expression. Complete reviewed
   evidence retains texts for every source-expression identifier; the
   redistribution notice emits the selected expression and its exact text
   subset. For Mbed TLS the source evidence remains
   `(Apache-2.0 OR GPL-2.0-or-later)` while the redistributed archives
   explicitly select `Apache-2.0`. Collapsing the source expression to the
   chosen arm, emitting both arms as simultaneous obligations, or selecting an
   expression that is not one source choice is fatal.

   Literal frozen-manifest resolution also produces canonical evidence for
   each target. It contains every recursively traversed manifest as one unique
   repository-logical path/SHA-256 record and every frozen destination mapped
   to its selected source's repository-logical path/SHA-256, literal
   optimization level (`null` or 0–3), and package metadata version (`null` or
   an ASCII token matching `[0-9A-Za-z][0-9A-Za-z._+-]{0,127}`). Both arrays
   are lexically ordered by their logical
   identity, contain no host-absolute path, and exactly describe the manifest
   walk that selected the frozen source tree. The semantic receipt binds this
   evidence. The public verifier independently repeats the literal traversal
   and recomputes the records, so changing a selected source or traversed
   manifest after the build is fatal even when the generated firmware artifact
   is otherwise unchanged.

   Filename agreement and current source hashes are not sufficient proof that
   the built frozen payload came from those bytes. For each target, the
   collector MUST therefore reconstruct the complete frozen payload in a new
   temporary build directory. It copies the built
   `genhdr/qstrdefs.preprocessed.h`, invokes the repository-pinned
   `tools/makemanifest.py` over the already literal-validated manifest with the
   exact board, port, MicroPython, micropython-lib, target architecture, and
   empty mpy-tool flag values, and forces a clean compile by starting with no
   retained `.mpy` or output file. The subprocess receives a small,
   release-defined environment containing only controlled temporary-home,
   temporary-directory, Python cache/isolation, hash-seed, locale, and timezone
   values plus `SOURCE_DATE_EPOCH`. That epoch MUST be the exact decimal
   committer timestamp of the candidate's full PyBLE source commit and MUST
   equal the build-provenance value used to create the admitted compiler;
   wall-clock date and caller overrides are forbidden. Inherited loader,
   Python, path, and executable overrides are not admitted. The pinned,
   regular, non-symlink
   `mpy-cross/build/mpy-cross` is the only admitted compiler. Once per audit,
   the collector also builds `mpy-cross` from the clean pinned MicroPython
   source into a fresh temporary `BUILD` directory with the controlled
   environment and explicit trusted build tools; the fresh executable MUST be
   byte-identical to the admitted compiler.

   The temporary `.mpy` destination set and every byte MUST equal the retained
   build's exact regular, non-symlink `frozen_mpy/` set. Because `mpy-tool.py`
   emits its input paths in non-semantic C comments, the final C comparison
   invokes that same pinned tool over the now-byte-proven retained `.mpy`
   paths, in literal manifest order, and combines its output with the clean
   reconstruction's string prefix. That complete reconstructed
   `frozen_content.c` MUST be byte-identical to the built file. Before that
   comparison, every generated board copy selected through `BOARD_DIR` MUST be
   byte-identical to its repository-logical overlay or `firmware/pyble` source.
   For each isolated ESP release target, that `BOARD_DIR` is exactly
   `<build-root>/.sources/<target>/micropython/ports/esp32/boards/<build-board>`
   in the retained target-local checkout named by the admitted build. The
   collector MUST audit that exact generated tree and record its paths in the
   host-independent `build/.sources/<target>/micropython/...` namespace. A
   missing, symlinked, or changed retained copy is fatal even if the ambient
   canonical MicroPython checkout contains a matching or decoy generated board
   tree; materializing such an ambient tree is neither an audit prerequisite
   nor substitute evidence for bytes used by the build.

   The collector MUST open every component of that exact retained `BOARD_DIR`
   descriptor-relatively without following links, capture its complete bytes
   and node identities, and materialize a byte-identical execution snapshot in
   fresh private audit staging. Clean frozen-payload reconstruction MUST consume
   only that immutable private snapshot; its temporary path is not evidence and
   does not replace the original `build/.sources/...` logical identity recorded
   above. After every `BOARD_DIR` consumer finishes, the collector MUST reopen
   and resnapshot the exact retained namespace without following links and
   require it to equal the initial capture. A component swap, transient symlink,
   replacement, or byte change at any phase is fatal even if an attacker restores
   the lexical path before a later path-based check.

   The collector then selects the unique compile-command entry whose exact
   source is this `frozen_content.c`, requires an unambiguous argument-vector
   command with one source and one `-o`, and replays it from its recorded
   directory with the same controlled environment while replacing only the
   output operand with a new temporary file. The rebuilt object bytes MUST
   equal the unique same-basename member bytes extracted from the owning
   linked MicroPython archive. The semantic record binds the repository-logical
   component/archive identity, member name, and object SHA-256. A regenerated C
   file that is internally consistent but differs from the object actually
   linked is therefore fatal.

   Each per-target semantic record additionally binds the exact architecture,
   qstr header digest, repository-logical path/SHA-256 identities of
   `makemanifest.py`, `manifestfile.py`, `mpy-tool.py`, the imported
   `mpy_cross` package files, and the `mpy-cross` executable, plus the sorted
   destination/SHA-256 inventory of retained `.mpy` files. No temporary or
   host-absolute path is retained. A source, metadata version, optimization
   level, module order, qstr header, `.mpy`, generator, compiler, architecture,
   copied-board byte, or frozen C mismatch is fatal.

10. Coverage is exact without asserting false package/archive cardinality.
    Every observed raw package, linked archive, compiled source, frozen
    destination, frozen source tree,
    prebuilt blob, and compiler/runtime input is consumed by exactly one
    resolution record; each record declares its complete many-to-many
    package/input attribution, and aggregate packages may own no archive
    directly only through rule 7. Every expected relationship is present, every
    declared stable matcher is observed exactly where applicable, and no
    unexpected record is accepted.

The initial runtime/input review explicitly includes `libgcc.a` and
`libstdc++.a` under `GPL-3.0-or-later WITH GCC-exception-3.1`;
`libc.a`, `libc_nano.a`, and `libm_nano.a` under the complete reviewed newlib
multi-license `LicenseRef`; and ESP-IDF's contributing Xtensa
`libxt_hal.a` under the pinned Tensilica MIT attribution. Command-line-listed
but non-contributing libraries are recorded for reconciliation and MUST NOT be
presented as linked unless the map proves a contributing member.

The reviewed license catalog is identifier-exact. Every identifier and
exception used by a raw, reviewed, resolved-input, or supplemental expression
MUST name one hash-bound complete text record; a text for a different
identifier is not interchangeable merely because both are permissive. The raw
v0.6 eight-document union for the frozen tool includes `Apache-2.0`,
`BSD-2-Clause`, `BSD-2-Clause-Views`, `BSD-3-Clause`, `CC0-1.0`, `ISC`, `MIT`,
`Unlicense`, and `LLVM-exception`. Linked or supplemental inputs additionally
require `BSD-1-Clause`, `GPL-2.0-or-later`, `GPL-3.0-or-later`,
`GCC-exception-3.1`, the reviewed newlib `LicenseRef`, and the reviewed
Berkeley DB 1.xx notice/rescission `LicenseRef`. A `LicenseRef` is approved
only with its exact complete reviewed text and attribution; it is never an
alias for a guessed SPDX identifier.

The schema-v2 policy also contains one nonempty, identifier-unique
`review_files` catalog. Each record contains exactly an identifier, purpose,
repository-relative path, SHA-256, and a nonempty unique list of immutable
source identities. It binds verbatim upstream NOTICE, COPYRIGHT, license,
SBOM, source, and binary-library attribution files that support a review but
are not themselves interchangeable with a complete SPDX license text. Every
path MUST be a regular non-symlink file below the repository and MUST match
its digest; every source identity MUST be explicit (commit, tree digest, or
managed-component content hash). Duplicate identifiers/paths, an empty
identity list, an unbound evidence file, or a changed byte is fatal. The
catalog participates in the policy semantic receipt hash and public
revalidation.

Toolchain and framework files that share a historical filename remain
different evidence records. In particular, ESP-IDF's component-level newlib
terms (SHA-256
`0681089a556e93791da82718d68011ba452de245f7f59c3846936304756ac0c0`)
MUST NOT stand in for the GCC distribution's runtime newlib terms (SHA-256
`422aa40293093fb54fc66e692a0d68fd0b24ed5602e5d1d33ad05ba3909057e9`).
The pinned GCC distribution's GPLv3 and Runtime Library Exception texts have
SHA-256
`8ceb4b9ee5adedde47b31e975c1d90c73ad27b6b165a1dcd80c7c545eb65b903`
and
`9d6b43ce4d8de0c878bf16b54d8e7a10d9bd42b75178153e3af6a815bdc90f74`
respectively. The audit safely extracts and byte-compares these records from
both pinned Xtensa and RISC-V distributions; an installed copy alone is not
proof.

The initial reviewed source closure also preserves:

- MicroPython application inputs under the union of MIT, BSD-1-Clause,
  BSD-3-Clause, Apache-2.0, and the exact Berkeley DB 1.xx
  notice/rescission `LicenseRef`, with NeoPixel retained separately as its
  pinned MIT supplemental tree;
- Mbed TLS's original dual-license evidence while recording ESP-IDF's explicit
  Apache-2.0 selection for the three linked supplemental archives;
- the NimBLE NOTICE, ESP-IDF third-party copyright summary, per-family
  controller/coexistence/PHY/Wi-Fi binary-library attribution, and the
  Tensilica `libxt_hal.a` MIT attribution; and
- exact managed-component lock/source/license identity for the linked ESP-IDF
  LAN867x and TinyUSB components. A diagnostic component-manager hash without
  the fetched candidate source and license bytes is insufficient. These ESP
  records do not prove the RP2 dependency: the Pico audit independently binds
  its selected MicroPython `lib/tinyusb` checkout, contributing inputs, and
  complete license/notice bytes in the required `tinyusb` role.

Raw records for BLE Mesh and controller families not selected by a profile
remain byte-exact in the raw graph and use `not-shipped` resolutions with
receipt-bound zero-input proof. Their notices MUST NOT be added to the
redistribution notice.

Intermediate SBOM/license inventories are retained as release-review evidence
outside the immutable public tree. They are necessary evidence, but do not
replace the complete texts in `THIRD_PARTY_LICENSES.txt`.

The complete audit, its retained evidence, and the final marker-free
`THIRD_PARTY_LICENSES.txt` MUST be verified against the exact packaged build
before the protected candidate is staged for HIL. A candidate-only notice
inventory does not qualify for that deployment. Public finalization MUST copy
the candidate notice byte for byte and revalidate it against the same build
inputs and retained evidence; it MUST NOT accept a replacement notice.

The locally bundled website dependency on ESP Web Tools is pinned to an exact
reviewed version in `package-lock.json`, is served from the PyBLE origin under
the site's existing `script-src 'self'` policy, and participates in the
website's dependency/license audit. No CDN or other third-party runtime request
is permitted. Website JavaScript notices are generated separately as
`WEBSITE_THIRD_PARTY_LICENSES.txt` from the exact bundled npm closure and linked
from `/flash`; they MUST NOT be misrepresented as dependencies embedded in the
firmware image.

`RELEASE_NOTES.md` MUST state the release date, supported profile IDs and exact
memory requirements, agent/PBLE/1/MicroPython/ESP-IDF versions and commits,
source/tag links, known limitations, destructive-install warning, upgrade
notes, recovery link, and support contact. It MUST explicitly state that the
two S3 images are separate, N16R8-class only, and byte-distinct; the lean image
has no bundled TFT/splash support and the exact-board image supports only the
Waveshare B version.

## 7. Installer capability and consent

The `/flash` document remains complete without JavaScript. Every enhanced
action requires a secure context, Web Crypto `subtle.digest`, and successful
verification under §5. An ESP action additionally requires
`navigator.serial`; a Pico verified download MUST NOT require it.

The implementation MUST NOT infer support from the browser user-agent. Its
unsupported state names a current desktop Chromium browser as the supported
path and explicitly states that iPadOS cannot perform the wired provisioning
step. The exact ESP Web Tools package is bundled locally; its activation button
is exposed only after profile selection, verification, and consent.
The Pico action offers only a download created from already verified in-memory
UF2 bytes, followed by visible manual BOOTSEL-copy instructions.

Before activation the user MUST affirm all of the following:

1. the exact selected hardware profile matches the connected board and, for
   `waveshare-esp32-s3-lcd-147b`, the board is the exact B-version model;
2. board files and any previous firmware have been backed up;
3. installation overwrites the board firmware and may erase user files;
4. a data-capable USB cable and stable power are in use; and
5. other serial monitors and applications using the port are closed.

The page MUST show the selected profile, firmware version, release date,
artifact verification result, destructive effect, and link to version-matched
recovery instructions adjacent to the button. It MUST never offer one profile
as a fallback after another family fails.

## 8. Recovery contract

The versioned `RECOVERY.md` and the visible `/flash` recovery section MUST
cover, in plain language:

- what is erased and how to back up user files before installing;
- normal USB connection, data-cable, stable-power, and serial-port selection;
- automatic reset plus the manual BOOT/RESET sequence, with a warning that
  button labels vary by board;
- safe retry after permission denial, disconnect, timeout, interrupted erase,
  interrupted write, verification failure, or a board that no longer boots;
- closing serial monitors, reconnecting USB, manually entering the ROM
  bootloader, and retrying the **same verified profile**;
- the exact version-matched `esptool` command for the merged image and base
  offset, plus the component offsets as an advanced diagnostic/recovery
  alternative using the same bundle bytes;
- post-flash hard reset/power cycle, expected `PyBLE-XXXX` BLE advertisement,
  and first connection from the app;
- symptoms of a wrong memory profile, an instruction to stop rather than try
  random images, and the support route/contact; and
- the diagnostic fields safe to share: release version, profile ID, board
  model/module marking, browser/OS versions, stage and error text, while
  excluding secrets and personal device labels.

A recovery instruction that has not itself been exercised on all five v0.6.0
profiles does not satisfy the release gate. C3 remains inactive until C3-G0…G6
pass; Pico remains inactive until GP2 passes.

For the pinned ESP-IDF 5.5 tool environment (`esptool.py` v4.12.dev3), every
generated and visible merged-image command MUST use the executable module form
`python -m esptool --chip <chip> write_flash <offset> <image>` with the
underscore subcommand `write_flash`. The unsupported hyphenated spelling
`write-flash` MUST NOT appear in a generated recovery document or the visible
installer recovery section. An automated gate MUST exercise the selected
subcommand against the pinned tool's command-line parser; rendering command-like
text without proving that the pinned parser accepts it is insufficient.
The v0.5 recovery document MUST emit separate commands for all three profiles;
the two S3 commands both use `--chip esp32s3` and offset `0x0` but MUST name
their distinct profile-local `firmware.bin` paths. A generic S3 path is never a
recovery alias for the exact-board image or vice versa.

The v0.6.0 recovery document adds the C3 command at offset `0x0` and a separate
Pico procedure. Pico recovery re-enters BOOTSEL, re-verifies the same
versioned UF2 size/SHA-256, recopies those verified bytes, waits for automatic
reboot, and confirms the expected BLE advertisement. It MUST NOT show an
`esptool`, offset, Web Serial, or random-image fallback for Pico. Physical HIL
must exercise a deliberately interrupted/failed UF2 copy followed by this
successful recovery using the final candidate bytes.

## 9. Automated and HIL acceptance

Automated release tests MUST cover:

- clean five-profile/four-chip build from one candidate-frozen pin set and commit;
- byte-for-byte second clean build;
- `flasher_args.json` → profile component-offset and merge-setting agreement;
- merged-image reproduction, ESP image target/role parsing, component placement,
  partition-table parsing, range/non-overlap, application fit, and
  flash-capacity checks;
- exact manifest schema, paths, profile parity, and forbidden redirect/origin
  cases;
- exact v0.6.0 five-profile resource-policy schema 3 and HIL V5 schema, plus
  historical schema-2/V4 replay,
  baseline/policy/candidate
  hash binding, derivation arithmetic, threshold-boundary and one-unit-crossing
  fixtures, and rejection of cross-target resource/transport fields;
- release-schema validation, SHA-256/size verification, corrupt/truncated/
  missing/swapped-part fixtures, and metadata/manifest disagreement;
- mechanically complete third-party license output;
- website feature-detection, unsupported/insecure/iPad copy, consent, fail-
  closed integrity states, keyboard accessibility, and no third-party request;
- loopback-preview isolation, its exact five-target order and action-specific
  capability gates, target-local manifest/UF2 size and SHA-256 verification,
  verified-byte UF2 download, unqualified labelling, and rejection of dirty,
  mixed-source, escaped, symlinked, or corrupt local inputs;
- production rejection or exclusion of the preview flag and staging tree,
  C3/Pico pending-state exclusion until their gates pass, and the unchanged
  fail-closed no-release state; and
- static-export and candidate/production-origin retrieval of every versioned
  byte.

For a split-source v0.5.x release core, one HIL record MUST be completed for
each of the three exact source-candidate profiles using the final, hash-locked
candidate. The immutable v0.4.2 history retains exactly one
embedded `PYBLE_HIL_RECORDS_V2` schema-2 object. Beginning with the `0.5.0`
release core, including v0.5.1 and prereleases, the report MUST contain exactly
one `PYBLE_HIL_RECORDS_V4` schema-4 object because the Waveshare functionality
is an independent third profile. The abandoned shared-image V3 engineering
shape MUST NOT qualify or publish a split-source release. A V1 marker, the
wrong source-era marker, an additional marker, or keys not defined below are
invalid. These are admission requirements; they do not assert that a v0.5.1
HIL report or qualified public bundle exists.

The v0.6.0 report instead contains exactly one
`PYBLE_HIL_RECORDS_V5` schema-5 object with five records in §1 order and the
target-discriminated contract in §9.5. V5 is required only for v0.6.0 and MUST
NOT reclassify V2/V4 history.

```text
<!-- PYBLE_HIL_RECORDS_V2
{ ...one JSON object... }
-->

<!-- PYBLE_HIL_RECORDS_V4
{ ...one JSON object... }
-->

<!-- PYBLE_HIL_RECORDS_V5
{ ...one JSON object... }
-->
```

### 9.1 Resource-qualification policy

Candidate generation MUST read
`firmware/qualification/oi1-gates.json`, verify it against the frozen
[firmware requirements §5.3](specs.md#53-footprint-gates-nfr-fp), and embed
both its parsed JSON object and the lowercase SHA-256 of its exact source
bytes. For split-source release cores at or after `0.5.0`, the required policy
object has exactly these keys:

| Key | Exact value/type |
|---|---|
| `schema_version` | integer `2` |
| `qualification_scope` | string `"pre-v1"` |
| `profile_order` | exact string array `["esp32-4mb", "esp32-s3-n16r8", "waveshare-esp32-s3-lcd-147b"]` |
| `deferred_profiles` | exact string array `["esp32-c3-4mb"]` |
| `workload` | exact object defined below |
| `derivation` | exact object defined below |
| `baseline_evidence` | exact object `{path, sha256}` |
| `profiles` | three policy-entry objects, in `profile_order` |

This is a qualification requirement for v0.5.1; it does not assert that the
checked-in policy has been regenerated or that qualification has passed.

`workload` has exactly these integer/string keys and values:

```json
{
  "reset_samples": 10,
  "reset_hold_ms": 1000,
  "advertising_timeout_ms": 15000,
  "post_hello_heap_samples": 10,
  "roundtrip_samples": 5,
  "roundtrip_payload_bytes": 65536,
  "payload_generator": "sha256-counter-v1",
  "post_roundtrip_heap_samples": 5,
  "reliability_files": 20,
  "reliability_file_bytes": 16384,
  "post_reliability_heap_samples": 1,
  "required_att_mtu": 247,
  "required_put_window": 8,
  "required_chunk_bytes": 229
}
```

`derivation` has exactly these string keys and values:

```json
{
  "application_image": "exact-byte-identical-two-root-v1",
  "application_headroom": "factory-minus-application-v1",
  "heap_floor": "floor-min-1024-v1",
  "boot_ceiling": "fixed-product-slo-3000-v3",
  "goodput_floor": "floor-95pct-min-100-v2"
}
```

This exact derivation object and policy schema 2 apply to v0.5.x split source
releases. The retained `0.4.2` source era instead requires policy
schema 1, its historical exact two-profile order, `ceil-max-10-v1`, and
`floor-min-100-v1` values; validation selects the complete policy contract by
firmware source era and never silently reinterprets published evidence.

`baseline_evidence.path` MUST match
`docs/validation/firmware/oi1/<40-lowercase-hex-source-commit>.json`;
`baseline_evidence.sha256` MUST be the lowercase 64-hex SHA-256 of that exact
canonical, redacted file. Retained baseline files are immutable history: a
controlled refresh MUST add a new source-commit-scoped file, retain every
earlier file, and replace the active evidence pointer and all three profile
threshold objects together. It MUST NOT mix profiles or successful samples
from different baselines. For a v0.5.x source release, the active baseline
firmware release core MUST be at least `0.5.0` and MUST NOT be newer than the
source release core; the retained pre-`0.5.0` contract keeps its historical
baseline semantics. A refreshed engineering baseline does not approve a
release: after the policy or source changes, the v0.5.x final candidate MUST
be rebuilt and verify-mode HIL MUST pass on all three exact profiles. The
successor v0.6.0 rules are in §9.5 and firmware specs §5.3.5.

A profile policy entry has exactly
`profile_id`, `target`, and `thresholds`. Targets are `esp32`, `esp32-s3`, then
`waveshare-esp32-s3-lcd-147b`. The latter two logical builds share the
underlying ESP-IDF `esp32s3` target, but their release targets and evidence
MUST remain distinct so generic-S3 measurements can never qualify the
exact-board image (or vice versa).
`thresholds` has exactly these positive integer keys:

```text
application_image_max_bytes
application_headroom_min_bytes
gc_free_min_bytes
idf_internal_free_min_bytes
idf_internal_largest_block_min_bytes
idf_internal_minimum_free_min_bytes
reset_to_service_advertisement_max_ms
put_committed_goodput_min_bytes_per_second
get_verified_goodput_min_bytes_per_second
```

Booleans MUST be rejected anywhere an integer is required. The policy MUST
have no C3 policy entry, and neither the baseline nor a source/build/license
result may be interpreted as C3 HIL qualification.

### 9.2 Embedded `PYBLE_HIL_RECORDS_V2` historical shape

The top-level object has exactly:

```text
schema_version
candidate_release_json_sha256
qualification_policy_sha256
qualification_policy
records
```

`schema_version` is integer `2`. `qualification_policy_sha256` is the
lowercase 64-hex digest of the exact committed policy bytes, and
`qualification_policy` is the byte-source's parsed object from §9.1.
`records` contains exactly two objects in policy `profile_order`. A pending
candidate uses an empty `candidate_release_json_sha256`; the completed report
MUST replace it with the lowercase 64-hex SHA-256 of the exact `release.json`
selected by the protected site during HIL.

Each record has exactly these keys:

```text
profile_id
status
board_manufacturer
board_model
module_marking
device_flash_capacity_bytes
device_psram_capacity_bytes
firmware_version
tag
source_commit
manifest_sha256
firmware_sha256
tested_at
operator
maintainer_signoff
desktop_os
chromium_version
ble_backend
ble_adapter
python_version
checks
oi1_policy
oi1_build
oi1_observation
redacted_console_log
```

`device_flash_capacity_bytes` and `device_psram_capacity_bytes` are observed
physical module capacities. They replace V1's ambiguous `observed_*` names and
MUST NOT be used as application footprint. Identity, hash, UTC, operator, and
non-empty public metadata constraints remain as in the prior contract.
`oi1_policy` MUST equal the matching object from
`qualification_policy.profiles`. `oi1_build` is generated before HIL and has
exactly:

```text
application_image_bytes
factory_partition_bytes
application_headroom_bytes
```

All three values are non-negative integers. The validator MUST compare
`application_image_bytes` to the exact bundled `application.bin`, parse
`factory_partition_bytes` from the bundled partition table, and recompute
`application_headroom_bytes` by subtraction. These values and the policy are
immutable across candidate finalization.

In a pending candidate, `status` is `pending`, both physical-capacity values
are integer zero, all operator/board/time/environment strings are empty, and
`oi1_observation` is null. In a completed public record, `status` is `passed`;
physical capacities equal the selected profile's frozen flash/PSRAM topology;
`tested_at` is UTC RFC3339; all board, operator, sign-off, OS/browser,
BLE-backend/adapter, Python-version, and redacted-log strings are non-empty;
the firmware/tag/source identity equals release identity; and manifest and
firmware digests equal the selected profile artifacts.

`checks` keeps exactly these keys:

```text
browser_erase_install
family_offsets_reset
advertising_info_hello
app_workflow
neopixel_reboot
footprint_reliability
interrupted_flash_recovery
```

In a candidate every value is `pending`. In a public report every value is
`passed`; `footprint_reliability` MUST be set by the validator only after the
V2 observations pass, not accepted as independent operator testimony.

The release tool MUST provide an `assemble-hil-report` operation so completing
this contract never requires hand-editing `HIL_REPORT.md`. It accepts one
immutable pending candidate, exactly two JSON completion fragments (one per
profile, in either input order), the canonical qualification checkout, and one
new no-replace output path. A completion fragment contains only the mutable
profile ID, physical board descriptions/capacities, UTC test time,
operator/sign-off and environment strings, the six operator-demonstration
checks other than `footprint_reliability`, one completed `oi1_observation`, and
the redacted console log. It MUST NOT accept status, release identity, artifact
hashes, policy, or build measurements from an operator fragment.

The assembler MUST validate the pending candidate first, compute the exact
candidate `release.json` SHA-256 itself, copy every candidate-frozen field from
the embedded pending records, require all six supplied checks to be `passed`,
validate the observation and every profile threshold, and only then insert
`footprint_reliability: passed` and `status: passed`. It MUST render exactly one
canonical `PYBLE_HIL_RECORDS_V2` marker, validate the completed payload against
the candidate bytes and committed policy, and write the output atomically. It
never mutates the candidate and does not perform public bundle promotion;
`finalize-public` remains the only promotion step.

`oi1_observation` is JSON `null` in a pending candidate. In a completed report
it is an object with exactly:

```text
observed_att_mtu
observed_window
observed_chunk_bytes
reset_to_service_advertisement_ms
heap_default_free_post_hello_bytes
heap_post_hello
put_unique_committed_bytes
put_duration_ns
put_committed_goodput_bytes_per_second
get_unique_verified_bytes
get_duration_ns
get_verified_goodput_bytes_per_second
put_retransmitted_chunks
put_retransmitted_bytes
get_retransmitted_chunks
get_retransmitted_bytes
roundtrip_integrity_verified
get_offset_sequences_validated
roundtrip_unexpected_disconnects
roundtrip_integrity_failures
heap_post_roundtrip
reliability
heap_post_reliability
physical_power_cycle_advertising
raw_log_sha256
```

The three observed transport values MUST be `247`, `8`, and `229`. Reset and
post-HELLO arrays have length 10. Every PUT/GET, retransmit, post-round-trip,
and duration array has length 5. Unique committed/verified byte entries are
each 65,536. Durations are positive monotonic nanoseconds; each reported
goodput integer MUST equal `floor(65536 * 10^9 / duration_ns)`.
`roundtrip_integrity_verified` and `get_offset_sequences_validated` are integer
`5`; both round-trip failure counts are integer `0`.
`physical_power_cycle_advertising` is string `passed`.
`raw_log_sha256` is the lowercase 64-hex digest of the access-controlled,
retained, redacted raw HIL log. Before its first byte is written, that log MUST
be created exclusively as a regular file with mode `0600`, independent of the
caller's umask. A pre-existing path MUST be rejected.

The physical power-cycle check MAY remove the same USB serial endpoint used
for controlled resets. After the completed off-interval and fresh-advertising
observations have been recorded, an operating-system "device disappeared"
error while deasserting or closing that stale serial handle is expected
cleanup, not a failed measurement. The harness MUST still close the handle,
MUST independently attempt to deassert both control lines and close the
underlying handle, MUST preserve and report the first non-disappearance cleanup
error, and MUST retain the complete redacted raw log. Terminal cleanup is
idempotent. This exception applies only to final cleanup after the physical
power-cycle observation; controlled-reset failures remain fatal.

Every heap snapshot object has exactly:

```text
gc_free_bytes
gc_allocated_bytes
idf_internal_free_bytes
idf_internal_largest_block_bytes
idf_internal_minimum_free_bytes
```

All values are non-negative integers. `heap_post_hello` has 10 snapshots,
`heap_post_roundtrip` has 5, and `heap_post_reliability` is one snapshot.
For each gated heap key, the validator concatenates those 16 observations and
compares the minimum with the matching policy floor. The 10
`heap_default_free_post_hello_bytes` values are diagnostic only.

`reliability` has exactly these non-negative integer keys:

```text
attempted_files
completed_files
verified_files
bytes_per_file
total_payload_bytes
unexpected_disconnects
integrity_failures
failed_statuses
retransmitted_chunks
retransmitted_bytes
rewinds
```

The first three values MUST all be 20, `bytes_per_file` MUST be 16,384,
`total_payload_bytes` MUST be 327,680, and disconnect/integrity/status-failure
counts MUST be zero. Retransmit and rewind counts are reported but are not
required to be zero.

### 9.3 `PYBLE_HIL_RECORDS_V4` three-profile exact-board release extension

V4 preserves every V2 per-record field, type, and promotion rule except for
the source-era-qualified `oi1_observation` addition below. It binds policy
schema 2 and contains exactly three records in the §9.1 order. Its
top-level object has exactly the five V2 keys plus
`waveshare_lcd147b_qualification`, and `schema_version` is the exact integer
`4`. A protected candidate and the completed three-profile operator report both
carry JSON `null` in that field. Finalization MUST reject a non-null input;
after admitting the private combined exact-board result, it alone replaces
null in the staged public report with the validator-derived summary.

For a split firmware source release core at or after `0.5.0`, each completed V4
record's `oi1_observation` has the exact V2 keys from §9.2 plus the required
`transfer_link_facts` object frozen in
[firmware specs §5.3.1](specs.md#531-frozen-metric-definitions).
The validator selects this shape from the report's bound firmware source era,
not from the validator checkout. A historical V2 `0.4.2` observation retains
the byte-exact §9.2 shape and MUST reject the extra field; a V4 `0.5.x`
observation MUST reject its absence. Candidate observations remain JSON null.
The abandoned two-profile V3 shared-image shape is retained only as rejected
engineering history: it MUST NOT validate, finalize, or activate any release.

The tenth reset owns the transfer session. Classic ESP32, generic S3, and C3
retain the ADR-0027 private-UART lifecycle: exact first-nine terminal drains,
buffer isolation before reset ten, settlement before timing, and the final
post-disconnect starvation record. Missing or duplicate termination fails
closed.

The exact Waveshare profile instead uses the ADR-0034 diagnostic compiled only
into its image. Through ordinary PBLE/1 RUN, a nonce-bound strict marker reads
one atomic `{active,last_ended}` snapshot from
`pble_ble._oi1_link_facts()`. Each of the first nine measured disconnects is
followed by a diagnostic reconnect with separate 20-second connect, 2-second
diagnostic-HELLO, and 2-second getter-RUN deadlines. It must show
the ended epoch and its exact non-wrapping active successor; both records are
discarded. Those first-nine boundary records may be unsettled because they are
not transfer evidence; they still require exact structure, finality, epoch
ordering, and no overflow. On reset ten, the
active epoch and settled facts are bound before timing and checked again after
the workload but before disconnect. One final diagnostic reconnect retains the
same three separate deadlines. Its getter RUN must expose that exact epoch as
immutable and final, plus its active
successor. Only the ended record's `facts` is sealed. Strict parsing rejects
null, stale, wrapped, non-successor, overflowed, unsettled, malformed,
duplicate, stderr, RUN-error, and timeout results, and discards arbitrary
console output; `unsettled` applies to the reset-ten transfer record, not the
discarded first-nine boundary pair. No serial endpoint, new opcode, public capability, BLE
identifier, connection handle, path, label, user source, or console text enters
the Waveshare report.

For both transports, the final PHY update
used to settle either S3 record MUST itself have status zero and `tx=2`, `rx=2`;
the final connection-parameter update MUST itself have status zero and match
the retained interval in the inclusive 12..24-unit range. Classic records
MUST instead carry the explicit compiled-out PHY shape. No BLE identifier,
serial path, device label, console text, or personal data enters the report.

That summary has exactly the fourteen keys frozen in
[TDD §14.3.1](TDD.md#1431-adr-0024-release-admission-boundary). It binds the
pre-HIL candidate `release.json` digest; exact profile, board model, and
firmware version; exact bundled
`waveshare-esp32-s3-lcd-147b` merged-image size/SHA-256; recomputed
immutable-span size/SHA-256; production-app evidence digest and canonical
active release path; the terminal chain digest; and the complete canonical
private-result digest. It contains no private result body, session, operator
input, BLE address/identity, source, raw console, or detailed lifecycle
record.

`finalize-public` MUST accept the private-result path only as an input. For a
V4-capable candidate it is mandatory. The finalizer MUST admit one bounded
canonical strict-JSON file that is a stable one-link mode-`0600` regular
non-symlink, validate it through the same pure schema implementation used by
the exclusive HIL writer, compare it to the exact candidate
`waveshare-esp32-s3-lcd-147b` install bytes,
and prove the input remained unchanged through late public validation. It
MUST NOT add the file to the release tree. V2 remains valid and byte-exact for
historical `0.4.2` replay; V2 or V3 MUST NOT finalize a split candidate and V4
MUST NOT reclassify an older release.

### 9.4 Required HIL demonstrations and evaluation

Besides the machine observations above, each completed record demonstrates:

1. full-chip erase and install from an access-controlled, production-equivalent
   HTTPS candidate `/flash` deployment containing the final static site code,
   manifest, and firmware binaries;
2. expected family detection, offsets, completion, and hard reset;
3. cold-boot `PyBLE-XXXX` advertising and version-matched INFO/HELLO;
4. app scan/connect plus edit, save, run, live console, STOP, soft reboot, and
   board-file round-trip;
5. `from neopixel import NeoPixel` before and after soft reboot;
6. every applicable application, heap, boot, transfer-reliability, and goodput gate for
   the profile; and
7. a deliberately interrupted browser flash followed by successful recovery
   using the published instructions and the same profile.

The lean `esp32-s3-n16r8` record additionally MUST prove after install and
soft reboot that `pyble_st7789` and `pyble_waveshare_lcd147b` are absent, no
splash hook or splash-only native readiness API is exposed, and ordinary BLE,
NeoPixel, and PBLE/1 workflows remain healthy. The
`waveshare-esp32-s3-lcd-147b` record MUST prove both modules are present and
MUST be accompanied by the exclusive TFT/splash/QR/driver-reuse qualification
in §9.3. These observations and boards are not interchangeable.

Simulation, a build-only result, a prior binary, or one ESP32-family board
standing in for another does not count. The maintainer signs off each row; the
maintainer may also be the HIL operator.

The validator MUST recompute and enforce:

- application-image/headroom arithmetic and the two static bounds;
- exact array/sample counts and workload constants;
- minimum of all 16 samples for each gated heap metric;
- maximum of the 10 reset-to-advertisement samples;
- every goodput value from its duration and the minimum of each five-sample
  direction;
- strict GET offset/byte/size/CRC integrity and exact reliability totals; and
- exact profile, policy, baseline, release, manifest, firmware, and source
  hash binding.

Missing or extra keys, wrong order/profile/unit/type/count, a bool accepted as
an integer, a manufactured MTU fallback, a C3 policy entry or record, an
identity/hash mismatch, or any threshold crossing MUST fail finalization. A
changed firmware, manifest, policy, or candidate identity resets the affected
record to untested. A changed baseline-evidence file requires a newly derived
policy and a new candidate.

Candidate-to-public promotion is a copy-on-write administrative operation. It
MUST create a new output directory atomically and MUST leave the protected
candidate unchanged. Exactly these changes are permitted:

- replace the pending `HIL_REPORT.md` with the completed report described
  above;
- change only each `release.json` profile `hil_status` from `pending` to
  `passed` and update only the `documents.hil_report` size and SHA-256 record;
  and
- regenerate `SHA256SUMS`, where only the `HIL_REPORT.md` and `release.json`
  entry digests may differ from the candidate.

Every other byte MUST remain identical, including `THIRD_PARTY_LICENSES.txt`,
`RELEASE_NOTES.md`, `RECOVERY.md`, `release.schema.json`, every manifest, and
every firmware/component image. Finalization MUST revalidate the completed
tree as public and compare every immutable path with the candidate. Within
either source-era payload, only the candidate release digest, record status,
physical-board
capacities and descriptions, time/operator/sign-off/environment strings,
checks, `oi1_observation`, and redacted console log may change. The profile
identity/hashes, `qualification_policy_sha256`, parsed policy, `oi1_policy`,
and `oi1_build` MUST remain exactly equal. V4 additionally permits only its
null-to-derived-passed exact-board summary transition. Publish nothing on any
failure. A
different byte or semantic field outside this envelope is a new candidate and
requires the complete three-profile HIL matrix again.

### 9.5 `PYBLE_HIL_RECORDS_V5` five-profile heterogeneous release

V5 binds OI policy schema 3 and contains exactly five records in §1 order. Its
top-level object has exactly:

```text
schema_version
candidate_release_json_sha256
qualification_policy_sha256
qualification_policy
records
waveshare_lcd147b_qualification
esp32_c3_qualification
rpi_pico2_w_qualification
```

`schema_version` is integer `5`. The three qualification summaries are JSON
`null` in both the protected candidate and operator-completed input. Only
copy-on-write finalization may replace each with a strict validator-derived
`passed` summary. Waveshare retains the §9.3 private-result contract. C3 binds
C3-G0…C3-G6; Pico binds GP0, GP1, and complete GP2. A missing private result,
non-null input summary, failed sub-gate, changed input, or identity/hash
mismatch leaves no public output.

Every V5 record has exactly the V2 identity/operator/environment keys, with
`manifest_sha256` replaced by common `install_sha256`, plus these required
keys:

```text
target
resource_kind
provisioning_kind
app_hil
profile_gate_summary
```

`checks` has exactly `provisioning_install`, `provisioning_recovery`,
`advertising_info_hello`, `pble_workflow`, `safe_boot_reconnect`,
`filesystem_resume_reliability`, and `footprint_reliability`. Every value is
`pending` in a candidate and `passed` after validation. `app_hil` has exactly
`ipad` and `android`; pending entries are JSON `null`, while each completed
entry has exactly non-empty `app_version`, `app_build`, `os_major`, and
`status: "passed"`. One platform cannot substitute for the other.

V5 completion JSON MUST be produced mechanically; an operator MUST NOT copy a
candidate record or hand-author its gate map. The release tool therefore
provides a `create-hil-completion` operation before `assemble-hil-report`. It
accepts exactly one pending candidate, one profile ID, that profile's
verify-mode OI observation, one canonical operator-input object, the canonical
qualification checkout, and one new no-replace output path. The
operator-input object contains exactly the physical board descriptions and
capacities, UTC test time, operator/sign-off and environment strings, the six
operator checks other than `footprint_reliability`, both completed `app_hil`
rows, and the redacted console log. It cannot contain status, release/source
identity, artifact digests, policy, build measurements, OI thresholds,
`footprint_reliability`, or `profile_gate_summary`.

For C3 and Pico the operation additionally requires that profile's exclusive
mode-`0600` private qualification result. It validates the result against the
candidate's exact `release.json` and install bytes and copies only the
validator-derived gate map into the completion fragment. It rejects a private
result for the other three profiles and rejects any operator-supplied gate
map. It validates the observation against the embedded policy, creates one
canonical exclusive mode-`0600` fragment without replacement, rereads it, and
changes no candidate byte. `assemble-hil-report` then accepts exactly five of
these fragments, in any input order, and still derives
`footprint_reliability` itself.

The C3/Pico gate module provides a separate `create-result` operation so the
private result never requires hand-authored identity or digest fields. It
accepts the immutable candidate directory, exact profile ID, one explicit
`--passed-gate` occurrence for every gate frozen for that profile, and a new
output path. The operation derives firmware version, candidate `release.json`
SHA-256, candidate install SHA-256, schema, status, and gate ordering; writes
canonical JSON as one exclusive mode-`0600` regular file; validates the file;
and refuses missing, duplicate, extra, non-passed, mixed-profile, changed, or
pre-existing inputs. Supplying the gate names is an operator attestation made
only after the corresponding build, unit/conformance, HIL, app, provisioning,
and physical-observation records have actually passed and remain retained.
The operation does not run a gate, infer a pass from a build, create a
threshold, or turn pending evidence into a result. This section freezes an
evidence-writing workflow and records no passed result.

The four ESP records use `resource_kind: "esp-idf"` and
`provisioning_kind: "esp-web-serial"`. Each additionally has exact
`manifest_sha256`; the V4 ESP `oi1_build`, heap observations, and
`transfer_link_facts` shapes remain unchanged. The C3 record's
`profile_gate_summary` has exactly keys `C3-G0` through `C3-G6`, all `passed`.
Other ESP records use JSON `null` except Waveshare, whose separate top-level
summary remains authoritative.

The Pico record uses `resource_kind: "rp2"` and
`provisioning_kind: "verified-uf2-bootsel"`; `manifest_sha256` and all
ESP-only keys are forbidden. Its install digest binds `firmware.uf2`; its
`oi1_build`, heap snapshots, transport facts, and policy row use the exact
[specs.md §5.3.5](specs.md#535-v060-five-profile-successor-policy-and-evidence)
RP2 shapes. In particular, `console_tx_budget_ms` is exactly `103`, the
source-derived empty-to-full refill horizon `ceil(2048 / 20)`; an operator
cannot supply or override it. Its `profile_gate_summary` has exactly `GP0`,
`GP1`, and `GP2`, all `passed`. Provisioning checks prove browser
size/SHA verification, download
from the verified in-memory bytes, manual BOOTSEL copy, automatic reboot, and
recovery from a deliberately interrupted/failed copy using the same UF2.

The C3 derived top-level summary has exactly `schema_version`, `status`,
`profile_id`, `firmware_version`, `candidate_release_json_sha256`,
`candidate_firmware_sha256`, `gates`, and `qualification_result_sha256`; Pico
uses the same keys with `candidate_uf2_sha256`. Each schema version is `1`,
status is `passed`, profile ID is exact, `gates` equals the record's exact gate
summary, and every digest is lowercase 64-hex recomputed by the finalizer.
Neither summary contains device serials, BLE addresses, labels, operator
input, raw INFO, or console bytes.

Candidate-to-public promotion retains the §9.4 three-file administrative
envelope: only `HIL_REPORT.md`, the corresponding HIL statuses/report digest
in `release.json`, and their `SHA256SUMS` entries may change. Every install,
resource, component, manifest, schema, license, release-note, and recovery byte
must equal the protected candidate. V5 finalization is atomic across all five
records and three summaries; partial promotion is forbidden. This section
freezes a contract and records no passed gate.

## 10. Activation and rollback

The qualified public action progresses through `candidate` → `verified` →
`published` → `active`. The public `pyble.dev/flash` action remains disabled
while candidate HIL runs on the access-controlled production-equivalent HTTPS
deployment. It
is valid for that protected candidate deployment alone to expose the action
with `hil_status: pending` after every non-HIL automated/integrity gate is
green; the candidate-mode selection MUST be build-time explicit, inaccessible
from the public deployment, and covered by a test that public builds reject
`pending`. Automated tests MUST start from the disabled public selection and
opt in explicitly when a case exercises candidate staging; inherited candidate
selector or staged-root environment variables MUST NOT reclassify public-page
or no-firmware Sites fixtures. The test runner MUST exercise this isolation
even when the surrounding release build exports candidate variables. The
public action may become `active` only when every automated gate is green,
all five v0.6.0 HIL rows say `passed`, the Waveshare, C3, and Pico derived
summaries are present and passed, the maintainer approves the exact hashes,
and the canonical same-origin bytes pass publication verification. If a
pre-v1 mirror exists, its files and bytes MUST agree before activation; v1.0 and
later require that mirror to be the matching GitHub Release. A missing,
pending, failed, extra, or substituted profile or summary blocks activation.
The activation deployment then
performs a non-destructive production-origin retrieval, redirect, size,
SHA-256, CSP, and render smoke test; it does not require another physical flash
after the public button is enabled.

Any missing or stale condition leaves the action unavailable with an accurate
status; availability MUST never be inferred from the mere presence of a
manifest. Rollback changes the website's selected-release descriptor to a
previous fully qualified immutable bundle and redeploys the site. It never
mutates or partially replaces the active version directory.

Once a public release is active, later website-only deployments MUST carry its
exact selector and immutable firmware tree forward
through authenticated retrieval and the canonical staged-release validation
path. Each website release with an active installer retains an unserved
canonical selector marker for this purpose. The preserved-public validator
MUST repeat every self-contained public bundle, schema, HIL, profile, artifact,
path, size, digest, descriptor, and annotated-tag check. It MUST prove exact
selected-byte continuity and MUST NOT accept a different version or byte. It
does not repeat the source/build license audit for a fully qualified release
whose passing evidence was required for the original activation of those same
immutable bytes. A preserved `v0.4.2` public beta MUST instead repeat canonical
`--audited-candidate` validation with the retained license-evidence directory
and exact release-build root, using the exact firmware-source checkout recorded
by the release as `--repo-root`, and MUST revalidate the annotated
`firmware-v0.4.2` tag. A
deployment MUST fail before the build if that state cannot be retrieved or
validated. Transitioning an active public installer to unavailable is a
separate reviewed operation requiring an explicit truth-valued disable flag
and a production smoke test of the disabled state; absence of staging input
alone is never authorization to disable it.

The pre-public `v0.4.1` candidate path was exposed without the required access
control and is permanently burned. The origin MUST quarantine
`/firmware/v0.4.1/` with a non-cacheable not-found response, MUST NOT select or
promote those bytes, and MUST retain any forensic copy outside public routing.

As a one-time transitional exception, the fresh audited `v0.4.2` candidate MAY
be published as a **hardware-tested public beta**. The selector deployment
mode MUST be `public-beta`, `accessControlled` MUST be `false`, both profile HIL
states and the aggregate `hilStatus` MUST remain `pending`, and the
`release.json` SHA-256 MUST equal
`5d1b0db8c4b90cccf054cd244530afb3b9112d489aa02f7c5da650e92161acde`.
The exact profile set is `esp32-4mb` plus `esp32-s3-n16r8`; C3 MUST remain
absent. Before staging or carrying the beta forward, the canonical release tool
MUST accept the exact bundle with `validate --audited-candidate`, its retained
license-evidence directory, its exact release-build root, and the exact
firmware-source checkout recorded by the release as `--repo-root`. The annotated
`firmware-v0.4.2` tag MUST exist and peel directly to the full PyBLE provenance
commit recorded in `release.json`, and deployment MUST bind the tag object
before and after the website build and before upload. The exact production
browser-flashing validation recorded in
`docs/validation/browser-flashing/v0.4.2-production.json` supports the narrower
claim that real-board Chrome installation, interruption, recovery, and reset
passed for both enabled exact profiles. Before the install control appears, the
website MUST state that completed scope and MUST separately say that complete
release qualification remains pending. It MUST NOT call the beta
access-controlled, protected, a qualified release, fully validated,
production-ready, or generally available.

The beta path MUST retain all existing audited-candidate, license, tag, schema,
checksum, manifest, image, same-origin, browser-capability,
profile-confirmation, consent, recovery, and production-smoke checks. The
exception changes only publication policy; it does not allow byte mutation,
substitute evidence, a different version/digest, or a new profile. A later
qualified public release therefore starts at a new immutable version and still
requires the complete current-source gate above.

<!-- SPDX-License-Identifier: MIT -->

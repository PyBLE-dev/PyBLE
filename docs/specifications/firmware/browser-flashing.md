# PyBLE ESP32-Family Browser Flashing and Release Bundle

Status: **FROZEN v1.27** · Owner: project maintainer · Frozen:
2026-07-31 (`[docs]`; pre-v1 two-profile release eligibility and explicit
C3 deferral; evidence-derived resource policy and exact HIL V2 records;
pre-policy two-root baseline-input staging and mechanical baseline/policy
assembly;
exact-profile manifest, C3 silicon-revision,
license-audit safety, candidate-finalization, and candidate pin-state
amendments, plus the real-tool license-evidence and exact license-catalog
models, trusted ESP-IDF tool-download-cache evidence, exact reviewed-source
evidence catalog, stable generated-input matchers, exact license-choice
semantics, relationship-bound aggregate-package evidence, an independent
shipment-review ledger, exact multi-frontend toolchain identity, canonical
literal-manifest evidence, byte-exact frozen-source reconstruction, and
retained per-target source-checkout isolation, deterministic retained-root
compiler path mapping, and fail-closed ESP-IDF described-source directory
markers, generated-header inputs, and direct-object reconciliation, plus
component-owned linked outputs, lexical exact-path validation, nested-build
logical paths, shell-free compiler/linker command receipts, executable
version-matched recovery-command syntax, and the canonical pre-v1 same-origin
publication channel with an optional byte-identical mirror, plus bounded
completed-HIL report assembly, on the same date)

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

The current pre-v1 public bundle contains exactly these two qualified
**provisioning image profiles**:

| Profile ID | ESP Web Tools `chipFamily` | Required target configuration | ESP image silicon window (`min_chip_rev_full`…`max_chip_rev_full`) | Merge settings | Browser image and component map |
|---|---|---|---|---|---|
| `esp32-4mb` | `ESP32` | Classic ESP32 with 4 MiB external SPI flash; no PSRAM assumption | `0`…`399` | DIO, 40 MHz, 4 MiB | merged `firmware.bin` at `0x1000`; bootloader `0x1000`; partition table `0x8000`; application `0x10000` |
| `esp32-s3-n16r8` | `ESP32-S3` | ESP32-S3 with 16 MiB flash and 8 MiB **Octal** PSRAM (N16R8-class) | `0`…`99` | DIO, 80 MHz, 16 MiB | merged `firmware.bin` at `0x0000`; bootloader `0x0000`; partition table `0x8000`; application `0x10000` |

`esp32-c3-4mb` remains a known provisioning profile and an initial v1
firmware target, with this frozen future qualification:

| Deferred profile ID | ESP Web Tools `chipFamily` | Required target configuration | ESP image silicon window (`min_chip_rev_full`…`max_chip_rev_full`) | Merge settings | Browser image and component map |
|---|---|---|---|---|---|
| `esp32-c3-4mb` | `ESP32-C3` | ESP32-C3 revision v0.3 or newer with 4 MiB external flash; no PSRAM assumption | `3`…`199` | DIO, 80 MHz, 4 MiB | merged `firmware.bin` at `0x0000`; bootloader `0x0000`; partition table `0x8000`; application `0x10000` |

That deferred profile is **not** part of the current public release: it MUST
NOT have an entry in `release.json`, a public manifest or binary directory, or
an installer selection. The website MUST show it separately as unavailable
pending exact-profile real-hardware validation. Re-enabling it requires a new
SemVer candidate, the complete automated gates, its own HIL row, and a new
immutable public bundle; it MUST NOT be added to an existing version.

The offsets and flash settings above are frozen from the matching ESP-IDF
`flasher_args.json` outputs. The release builder MUST compare generated
`flasher_args.json` with this table and fail on any difference; it MUST NOT
silently preserve stale or hand-copied offsets.

These are image-layout profiles, not GPIO-routing profiles and not an
app-runtime chip allowlist. ESP Web Tools detects the chip family, but that
detection does **not** prove flash capacity, PSRAM type, board wiring, power
quality, or silicon revision. In particular, the initial S3 image MUST be
presented only as `esp32-s3-n16r8`; neither the website nor release notes may
call it a generic image for every ESP32-S3 board. Any future C3 image MUST be
presented as requiring ESP32-C3 revision v0.3 or newer.

Before the install action appears, the user MUST explicitly select a profile
and affirm that the connected module meets its stated flash/PSRAM
configuration. The installer MUST then give ESP Web Tools only that profile's
single-build manifest. A family mismatch MUST therefore be rejected by ESP Web
Tools after connection; a shared multi-family manifest is forbidden because it
could silently select a different image than the profile the user affirmed. A
USB VID/PID, serial-port name, browser user-agent, or previously saved BLE
board identity MUST NOT be treated as proof of a profile.

Adding or re-enabling a flash size, PSRAM topology, or chip family requires a
new release candidate with the applicable profile ID, artifact set,
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
.sources/esp32/micropython/
.sources/esp32-s3/micropython/
.sources/esp32-c3/micropython/
```

Each path is an independent MicroPython checkout for exactly the named target.
Its `HEAD` MUST equal the full `versions.lock [micropython].commit`, its
`origin` URL MUST equal the canonical `versions.lock [micropython].repo`, and
its tracked tree MUST be clean when admitted and validated. Each target's
authoritative application `project_description.json` `project_path` MUST
resolve to that target's retained checkout at `ports/esp32`, and the audit
receipt MUST bind the project-description bytes and checkout commit/origin
identity. A missing, escaped, symlinked, dirty, wrong-origin, wrong-commit, or
cross-target checkout is fatal.

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
public release. Exact-profile HIL on both current release profiles,
`esp32-4mb` and `esp32-s3-n16r8`, remains the pre-v1 public-release approval
gate.

Changing either upstream pin after candidate-freezing creates a new source
state and a new candidate. The build, reproducibility comparison, license
audit, protected deployment, and complete current-release-profile HIL matrix
MUST then start again; evidence from the abandoned candidate MUST NOT be
carried forward.

Before the first OI-1 policy can be committed, the release tool MUST provide a
`create-baseline-inputs` operation that breaks the policy/evidence dependency
cycle without weakening candidate validation. It MUST bind two distinct,
non-nested clean build roots to the clean PyBLE proof checkout, validate all
three maintained ESP32 targets and their retained source checkouts, require
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
```

The two manifest files MUST be generated by the same production manifest
function used by candidate packaging. The three binary files per profile MUST
be copied from the validated primary build root. The deferred C3 build MUST
participate in validation and reproducibility comparison but MUST NOT be
staged. This operation runs before, and therefore MUST NOT require, an OI-1
policy, baseline-evidence file, release tag, license evidence, or HIL approval.
Its output is measurement input only: it is not a release candidate and MUST
NOT be accepted by the website or public release validator.

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
no-replace: an existing different file is fatal; an existing byte-identical
file is an idempotent input. The policy update MUST be an atomic same-directory
replacement, and both complete byte payloads MUST pass the production
baseline/policy validator before either destination is changed. This operation
is evidence assembly only; it does not approve a release or mutate staged
measurement inputs.

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
```

No `esp32-c3-4mb/` path exists in this release. Absence is intentional and is
part of the immutable release contract, not a missing upload.

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
      "parts": [
        { "path": "firmware.bin", "offset": 0 }
      ]
    }
  ]
}
```

`<version>` above is a template substitution, not literal released JSON.
The `esp32-4mb` manifest has the same shape and exactly one `ESP32` build with
offset `4096`. There is no C3 manifest in the current release. The website MUST
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

`release.json` schema version 2 MUST contain (the version is the exact JSON
integer `2`; booleans and numerically-equal fractional values are invalid).
Version 2 is an intentional incompatible metadata revision: it freezes the
two-profile pre-v1 release cardinality and MUST NOT validate the former
three-profile candidate shape. Older immutable bundles retain their own schema
beside their metadata:

- `schema_version` = `2`;
- release identity: `version`, `tag`, `agent_version`, `protocol_version`, and
  UTC `built_at`;
- provenance: full PyBLE commit and clean state; MicroPython ref/commit;
  ESP-IDF ref/commit; patch count; runner and compiler/tool versions;
- one entry for each current release profile in the first table of §1,
  including profile ID, `chip_family`,
  flash/PSRAM requirements, flash mode/frequency, required
  `silicon_revision.minimum_full` and `silicon_revision.maximum_full` integers
  matching the §1 image window, and HIL status (`pending` for a candidate or
  `passed` for a public bundle);
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

All values are required; placeholders, `unknown`, and abbreviated commits fail
any bundle. `pending` is accepted only on an access-controlled candidate used
for HIL; an HIL status other than `passed` fails a public bundle.
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

The conservative build audit runs against all six authoritative ESP-IDF
descriptions: application and bootloader `project_description.json` for each
of the three initial build targets. This preserves the v1 three-target build
and license gate even while the pre-v1 public bundle contains two profiles.
The released notice MUST classify as redistributed only the dependency union
of the two packaged profiles; C3-only observations remain retained review
evidence and MUST NOT be represented as a shipped C3 image or shipped profile.
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

The following resolution rules are part of that fail-closed mapping:

1. The audit retains all six **exact raw** `esp-idf-sbom` outputs and six
   normalized reviewed SPDX documents. Raw tag/value files use `.spdx.tag`;
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
   role build, and the map MUST name its exact build-relative path once.
   Exact generated-header, source-exception, anchor, and direct-output
   topologies MUST be checked lexically for symlink components before any
   canonical-path equality check; an alternate path resolving to the same
   bytes is not equivalent. Receipt records for files below the selected build
   root MUST use `build/<build-relative-path>` even when that build root is
   itself nested below the repository root.
   The role's exact `CMakeFiles/<app-elf>.dir/link.txt` MUST also be a regular,
   symlink-free receipt input. Its safely parsed direct `.o`/`.obj` argument
   set MUST equal the map's direct-object `LOAD` set exactly. Response files,
   including driver-wrapped forms, shell operators, duplicate object
   arguments, and path escape are fatal.
   Basename-only matching is forbidden.

   One logical source may therefore have multiple compile outputs. Archive
   source records remain archive-only and unique by logical path. The role's
   generated `main` binding additionally contains:

   - `linker_command_sha256`, the exact role `link.txt` digest;
   - `metadata_inputs`, the canonical logical path/SHA-256 records for the six
     application `genhdr/` inputs (empty for bootloader); and
   - `direct_objects`, canonical records containing each direct output's
     logical path/SHA-256 and its compile source's logical path/SHA-256.

   The `main` binding is invalid unless those three fields are present and
   exactly cover the role evidence. Duplicate linked consumption, an extra or
   missing direct `LOAD` or link-command object, a wrong direct-output root, an
   archive/output multiset mismatch, or treating an unlinked output as
   redistributed is fatal.

   `project_description.json`, `compile_commands.json`, and map SHA-256 values,
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

   After all six offline SBOM executions, the observer MUST rebuild this exact
   generated-input context and require byte-for-byte equality with the initial
   observations. Rechecking only archive/tree digests is insufficient:
   project/compile/map/link documents, metadata inputs, archive sources, direct
   outputs, and direct sources are all race-sensitive release inputs.
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
9. Coverage is exact without asserting false package/archive cardinality.
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
six-document union for the frozen tool includes `Apache-2.0`,
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
- exact managed-component lock/source/license identity for the linked LAN867x
  and TinyUSB components. A diagnostic component-manager hash without the
  fetched candidate source and license bytes is insufficient.

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
S3 image is N16R8-class only.

## 7. Installer capability and consent

The `/flash` document remains complete without JavaScript. The install control
is a client-only enhancement and MUST be activated by feature detection:

- a secure context;
- `navigator.serial`;
- Web Crypto `subtle.digest`; and
- successful verification under §5.

The implementation MUST NOT infer support from the browser user-agent. Its
unsupported state names a current desktop Chromium browser as the supported
path and explicitly states that iPadOS cannot perform the wired provisioning
step. The exact ESP Web Tools package is bundled locally; its activation button
is exposed only after profile selection, verification, and consent.

Before activation the user MUST affirm all of the following:

1. the exact chip/flash/PSRAM profile matches the connected module;
2. board files and any previous firmware have been backed up;
3. installation erases the device;
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

A recovery instruction that has not itself been exercised on both current
release profiles does not satisfy the release gate. The page MUST NOT offer a
C3 recovery command or binary while that profile is deferred.

For the pinned ESP-IDF 5.5 tool environment (`esptool.py` v4.12.dev3), every
generated and visible merged-image command MUST use the executable module form
`python -m esptool --chip <chip> write_flash <offset> <image>` with the
underscore subcommand `write_flash`. The unsupported hyphenated spelling
`write-flash` MUST NOT appear in a generated recovery document or the visible
installer recovery section. An automated gate MUST exercise the selected
subcommand against the pinned tool's command-line parser; rendering command-like
text without proving that the pinned parser accepts it is insufficient.

## 9. Automated and HIL acceptance

Automated release tests MUST cover:

- clean three-target build from one candidate-frozen pin set and commit;
- byte-for-byte second clean build;
- `flasher_args.json` → profile component-offset and merge-setting agreement;
- merged-image reproduction, ESP image target/role parsing, component placement,
  partition-table parsing, range/non-overlap, application fit, and
  flash-capacity checks;
- exact manifest schema, paths, profile parity, and forbidden redirect/origin
  cases;
- exact two-profile resource-policy and HIL V2 schema, baseline/policy/candidate
  hash binding, derivation arithmetic, threshold-boundary and one-unit-crossing
  fixtures, and rejection of any current C3 policy entry or HIL row;
- release-schema validation, SHA-256/size verification, corrupt/truncated/
  missing/swapped-part fixtures, and metadata/manifest disagreement;
- mechanically complete third-party license output;
- website feature-detection, unsupported/insecure/iPad copy, consent, fail-
  closed integrity states, keyboard accessibility, and no third-party request;
  and
- static-export and candidate/production-origin retrieval of every versioned
  byte.

One HIL record MUST be completed for each of the two exact current release
profiles using the final, hash-locked release candidate. The report contains
exactly one embedded JSON object marked `PYBLE_HIL_RECORDS_V2`; a V1 marker,
an additional marker, or keys not defined below are invalid.

```text
<!-- PYBLE_HIL_RECORDS_V2
{ ...one JSON object... }
-->
```

### 9.1 Resource-qualification policy

Candidate generation MUST read
`firmware/qualification/oi1-gates.json`, verify it against the frozen
[firmware requirements §5.3](specs.md#53-footprint-gates-nfr-fp), and embed
both its parsed JSON object and the lowercase SHA-256 of its exact source
bytes. The policy object has exactly these keys:

| Key | Exact value/type |
|---|---|
| `schema_version` | integer `1` |
| `qualification_scope` | string `"pre-v1"` |
| `profile_order` | exact string array `["esp32-4mb", "esp32-s3-n16r8"]` |
| `deferred_profiles` | exact string array `["esp32-c3-4mb"]` |
| `workload` | exact object defined below |
| `derivation` | exact object defined below |
| `baseline_evidence` | exact object `{path, sha256}` |
| `profiles` | two policy-entry objects, in `profile_order` |

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
  "boot_ceiling": "ceil-max-10-v1",
  "goodput_floor": "floor-min-100-v1"
}
```

`baseline_evidence.path` MUST match
`docs/validation/firmware/oi1/<40-lowercase-hex-source-commit>.json`;
`baseline_evidence.sha256` MUST be the lowercase 64-hex SHA-256 of that exact
canonical, redacted file. A profile policy entry has exactly
`profile_id`, `target`, and `thresholds`. Targets are `esp32` then `esp32-s3`.
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

### 9.2 Embedded `PYBLE_HIL_RECORDS_V2` shape

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
the candidate bytes and committed policy, write the output atomically, and
prove the candidate and completion-fragment inputs did not change during the
operation. It never mutates the candidate and does not perform public bundle
promotion; `finalize-public` remains the only promotion step.

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
retained, redacted raw HIL log.

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

### 9.3 Required HIL demonstrations and evaluation

Besides the machine observations above, each completed record demonstrates:

1. full-chip erase and install from an access-controlled, production-equivalent
   HTTPS candidate `/flash` deployment containing the final static site code,
   manifest, and firmware binaries;
2. expected family detection, offsets, completion, and hard reset;
3. cold-boot `PyBLE-XXXX` advertising and version-matched INFO/HELLO;
4. app scan/connect plus edit, save, run, live console, STOP, soft reboot, and
   board-file round-trip;
5. `from neopixel import NeoPixel` before and after soft reboot;
6. every V2 application, heap, boot, transfer-reliability, and goodput gate for
   the profile; and
7. a deliberately interrupted browser flash followed by successful recovery
   using the published instructions and the same profile.

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
tree as public and compare every immutable path with the candidate. Within the
V2 payload, only the candidate release digest, record status, physical-board
capacities and descriptions, time/operator/sign-off/environment strings,
checks, `oi1_observation`, and redacted console log may change. The profile
identity/hashes, `qualification_policy_sha256`, parsed policy, `oi1_policy`,
and `oi1_build` MUST remain exactly equal. Publish nothing on any failure. A
different byte or semantic field outside this envelope is a new candidate and
requires the complete two-profile HIL matrix again.

## 10. Activation and rollback

The public action progresses through `candidate` → `verified` → `published` →
`active`. The public `pyble.dev/flash` action remains disabled while candidate
HIL runs on the access-controlled production-equivalent HTTPS deployment. It
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
both current-release HIL rows say `passed`, the maintainer approves the exact
hashes, and the canonical same-origin bytes pass publication verification. If a
pre-v1 mirror exists, its files and bytes MUST agree before activation; v1.0 and
later require that mirror to be the matching GitHub Release. A C3 row MUST be
absent, not marked passed without evidence. The activation deployment then
performs a non-destructive production-origin retrieval, redirect, size,
SHA-256, CSP, and render smoke test; it does not require another physical flash
after the public button is enabled.

Any missing or stale condition leaves the action unavailable with an accurate
status; availability MUST never be inferred from the mere presence of a
manifest. Rollback changes the website's selected-release descriptor to a
previous fully qualified immutable bundle and redeploys the site. It never
mutates or partially replaces the active version directory.

Once a fully qualified public release is active, later website-only
deployments MUST carry its exact selector and immutable firmware tree forward
through authenticated retrieval and the canonical staged-release validation
path. Each website release with an active installer retains an unserved
canonical selector marker for this purpose. The preserved-public validator
MUST repeat every self-contained public bundle, schema, HIL, profile, artifact,
path, size, digest, descriptor, and annotated-tag check. It MUST prove exact
selected-byte continuity and MUST NOT accept a different version or byte. It
does not repeat the source/build license audit whose passing evidence was
required for the original activation of those same immutable bytes. A
deployment MUST fail before the build if that state cannot be retrieved or
validated. Transitioning an active public installer to unavailable is a
separate reviewed operation requiring an explicit truth-valued disable flag
and a production smoke test of the disabled state; absence of staging input
alone is never authorization to disable it.

The pre-public `v0.4.1` candidate path was exposed without the required access
control and is permanently burned. The origin MUST quarantine
`/firmware/v0.4.1/` with a non-cacheable not-found response, MUST NOT select or
promote those bytes, and MUST retain any forensic copy outside public routing.
A qualified public release therefore starts at a new immutable version.

<!-- SPDX-License-Identifier: MIT -->
<!-- Part of PyBLE (https://pyble.dev) — see /LICENSE. -->

# PyBLE public website

The statically authored Next.js site for `pyble.dev`. It explains the PyBLE
workflow and capability-defined board vision, distinguishes that vision from
the exact profiles available today, publishes privacy and support information,
and hosts the policy-gated browser installer. The live v0.4.2 selector offers a
hardware-tested beta for `esp32-4mb` and `esp32-s3-n16r8`; browser installation
and interrupted-flash recovery passed, while complete release qualification
remains pending, and that frozen exception remains exactly two profiles. A
qualified v0.5.1 activation instead requires `esp32-4mb`, lean generic
`esp32-s3-n16r8`, and the separate `waveshare-esp32-s3-lcd-147b` image; this
contract does not claim that v0.5.1 is currently public. ESP32-C3 is
unavailable.

## Why Next.js

The launch site is mostly durable public content. Next.js App Router gives each
route complete HTML and first-class metadata while still leaving a clean
client-component boundary for the future Web Serial installer.

`next build` produces the portable static export in `out/`. The canonical
production site serves that directory directly through Nginx on the
Cloudflare-fronted VPS; no Node.js process runs at the origin.

Sites requires a supported request entrypoint for the separate owner preview,
so vinext uses Vite at that deployment boundary to produce
`dist/server/index.js` and its complete client/server bundle. It does not
introduce a second page source or an application backend.

## Routes

| Route      | Purpose                                                                    |
| ---------- | -------------------------------------------------------------------------- |
| `/`        | Product story, verified capabilities, platform vision, and current targets |
| `/app`     | Stable app landing page for iPad and Android testing channels              |
| `/privacy` | Separate app and website privacy disclosures                               |
| `/support` | Beta quick start, troubleshooting, and report checklist                    |
| `/flash`   | Fail-closed Web Serial installer, exact profiles, and recovery             |

`pyble.dev` is canonical. `pyble.org` is redirected at the hosting edge, not by
this static application.

## Development

Use the Node version in `.node-version`.

```sh
npm ci
npm run dev
```

After a production build, `npm start` serves the vinext artifact locally.

The full release gate is:

```sh
npm run check
```

That command checks formatting, lint, strict types, unit/content contracts,
vinext compatibility, the portable Next.js export, and the Sites preview
artifact. Canonical VPS production files are written to `out/`; the
host-specific owner-preview bundle is written to `dist/`, including fully
prerendered launch routes, static discovery files, a static 404 boundary around
the vinext handler, and the exact Sites project binding.

No application backend, remote CMS, analytics service, or web-font request is
needed. A normal build needs no runtime or build-time environment variables.

### Temporary build-dependency exception

Vinext currently depends on `image-size` 2.0.2, and npm has no patched release
for GHSA-w3rx-r6r6-pgpr or GHSA-5p2g-fcmc-qvqq. The dependency is confined to
the owner-preview build: production deploys only `out/` and runs no Node.js
process. Until a compatible fix exists, the test gate forbids filesystem
metadata image routes under `src/app`, which are the vinext path that invokes
the parser. Recheck this exception on every vinext or `image-size` update; do
not describe `npm audit` as clean while the two related high findings remain.

## Production deployment

The tested Nginx configuration and atomic release helper live in `deploy/`.
They serve versioned `out/` releases below `/srv/pyble/releases/` through the
`/srv/pyble/current` symlink. See [DEPLOYMENT.md](DEPLOYMENT.md) for initial
VPS setup, Cloudflare Full (strict), certificate renewal, smoke tests, `.org`
activation, and rollback.

## Brand assets

`public/brand/pyble-prompt-chip.svg` is a byte-identical copy of the canonical
source in `app/assets/branding/`. The PNG files are derived from that source.
Keep the copies synchronized; never edit the website mark independently.

## Firmware installer boundary

The checked-in `/flash` selection is `null`, so an ordinary source build remains
fail-closed. A production deployment may inject only an explicitly staged and
validated selector; the current live deployment uses the exact v0.4.2
public-beta selector. A qualified v0.5.1 selector would instead contain exactly
three separate profiles; the v0.4.2 selector remains a digest-bound two-profile
exception. ESP Web Tools 10.4.0 is bundled locally, and the browser
loads it only after a selected profile's same-origin release metadata,
single-build manifest, merged image, exact size, and SHA-256 digest pass the
strict verifier. The website dependency closure and complete license texts are
published in `public/WEBSITE_THIRD_PARTY_LICENSES.txt`.

Enablement requires the release gate frozen in
`docs/specifications/website.md`. Activating v0.5.1 as a qualified public
release requires reviewed, independently HIL-qualified artifacts for all three
exact profiles:
`esp32-4mb`, `esp32-s3-n16r8`, and
`waveshare-esp32-s3-lcd-147b`. Both S3 profiles require N16R8 topology, but
they have separate single-build manifests and different immutable firmware
bytes. ESP Web Tools can identify their shared ESP32-S3 family but cannot
identify the onboard display, so the exact-board action requires its own
explicit B-version compatibility consent and never aliases the generic S3
manifest.

The live frozen v0.4.2 public beta instead requires reviewed artifacts for
exactly its two profiles (`esp32-4mb` and `esp32-s3-n16r8`), the canonical
audited-candidate and license gates, an annotated provenance tag, HTTPS,
capability detection, and recovery instructions. Production Chrome install and
interrupted-flash recovery passed on real hardware for both exact profiles;
complete app, PBLE/1, resource, and remaining firmware release qualification
continues. Its schema, digest, paths, and profile set remain immutable and MUST
NOT be treated as the v0.5.1 contract.
`esp32-c3-4mb` remains visibly unavailable and has no public release bytes
until a later exact-profile HIL-qualified candidate.

Firmware is never checked into `public/` or selected through a public
environment variable. `npm run firmware:stage` accepts an explicit external
bundle, verifies its complete `SHA256SUMS` coverage and release contract, then
writes an external immutable tree and a build-selection descriptor. A
qualified public bundle must have passed HIL on every profile. A pending
candidate is accepted
only with both `PYBLE_FLASH_DEPLOYMENT=candidate` and
`PYBLE_FLASH_ACCESS_CONTROLLED=1`, and must be built and hosted behind actual
access control. Supply both `PYBLE_FIRMWARE_STAGED_ROOT` and
`PYBLE_FLASH_SELECTION_FILE` to the protected build so the Sites adapter
revalidates and packages the external bytes without modifying `public/`. The
public VPS deploy helper rejects protected candidates. Candidate and exact
v0.4.2 public-beta staging require
`PYBLE_FIRMWARE_LICENSE_EVIDENCE_DIR` and
`PYBLE_FIRMWARE_LICENSE_BUILD_ROOT`, plus
`PYBLE_FIRMWARE_SOURCE_ROOT` for the exact release-source checkout, and invokes
the canonical audited-candidate gate against those retained inputs. Public and
public-beta activation require the exact local
annotated `firmware-v<version>` tag to peel to the `release.json` PyBLE
provenance commit. The helper canonically validates either the all-HIL-passed
public staging or the exact digest-bound audited v0.4.2 beta, freezes it in a
mode-0700 private snapshot, and proves exact staging,
packaged-output, and upload-snapshot byte equality. Final `out/` is copied to a
separate private read-only upload snapshot with a whole-site inventory; the VPS
authenticates that inventory separately and verifies the exact file set and all
hashes before publication or activation. The deploy helper rejects every
`tools/web/.env*` node before choosing a deployment mode. Canonical public
validation requires explicit
`PYBLE_FIRMWARE_LICENSE_EVIDENCE_DIR` and
`PYBLE_FIRMWARE_LICENSE_BUILD_ROOT` paths for the reviewed evidence and exact
release-build inputs, plus `PYBLE_FIRMWARE_SOURCE_ROOT` for their exact source
checkout. Activation is guarded by systemd rollback and
confirmation transactions until the public smoke suite succeeds.

MicroPython plus generic Bluetooth hardware is not itself a support claim.
Every advertised target needs a conforming PBLE/1 BLE GATT peripheral agent
port and the required build, conformance, resource/recovery, and HIL evidence.

Qualified public firmware v0.5.1 or newer names the Waveshare
ESP32-S3-LCD-1.47B as the separate
`waveshare-esp32-s3-lcd-147b` provisioning profile with its own manifest and
firmware binary. That exact-board image alone bundles `pyble_st7789`,
`pyble_waveshare_lcd147b`, and the factory-enabled-after-erase, persistently
disableable boot splash path. The lean `esp32-s3-n16r8` image retains the
common PyBLE agent and standard runtime but omits those display modules,
exact-board constants, and splash machinery. A provisioning profile selects
explicit flash bytes; it is not a PBLE/1 capability, automatic board detector,
or app connection gate. The exact v0.4.2 beta and all pending, protected,
unavailable, or otherwise unqualified selectors make no active exact-board
claim.

The qualified home and `/flash` presentations share the project-owned actual
board photograph at
`public/boards/esp32-s3-lcd-1.47b-pyble-v0.5.0.jpg`. The reviewed derivative is
a metadata-stripped `1600 × 1116` progressive JPEG (195079 bytes, SHA-256
`b939abb9b7ac19c7be8f429faaa61d08aadc7f027eac181582e036fd22949d12`), served
locally with an accurate caption and alternative text. It is omitted unless the
same qualified v0.5.1-or-newer release gate enables the exact-board copy.

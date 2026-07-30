<!-- SPDX-License-Identifier: MIT -->
<!-- Part of PyBLE (https://pyble.dev) — see /LICENSE. -->

# PyBLE public website

The statically authored Next.js site for `pyble.dev`. It explains the PyBLE
workflow and capability-defined board vision, distinguishes that vision from
the initial validated ESP32 / ESP32-S3 / ESP32-C3 firmware targets, publishes
privacy and support information, and stages the future browser firmware
installer without claiming that release artifacts are ready.

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

The checked-in `/flash` selection is `null`, so the public install button is
deliberately unavailable. ESP Web Tools 10.4.0 is bundled locally, and the
browser loads it only after a selected profile's same-origin release metadata,
single-build manifest, merged image, exact size, and SHA-256 digest pass the
strict verifier. The website dependency closure and complete license texts are
published in `public/WEBSITE_THIRD_PARTY_LICENSES.txt`.

Enablement requires the release gate frozen in
`docs/specifications/website.md`: reviewed artifacts for both current exact
profiles (`esp32-4mb` and `esp32-s3-n16r8`), automated checks, real-board
validation of the final bytes, HTTPS, capability detection, and recovery
instructions. The S3 profile specifically requires an N16R8 module.
`esp32-c3-4mb` remains visibly unavailable and has no public release bytes
until a later exact-profile HIL-qualified candidate.

Firmware is never checked into `public/` or selected through a public
environment variable. `npm run firmware:stage` accepts an explicit external
bundle, verifies its complete `SHA256SUMS` coverage and release contract, then
writes an external immutable tree and a build-selection descriptor. A public
bundle must have passed HIL on every profile. A pending candidate is accepted
only with both `PYBLE_FLASH_DEPLOYMENT=candidate` and
`PYBLE_FLASH_ACCESS_CONTROLLED=1`, and must be built and hosted behind actual
access control. Supply both `PYBLE_FIRMWARE_STAGED_ROOT` and
`PYBLE_FLASH_SELECTION_FILE` to the protected build so the Sites adapter
revalidates and packages the external bytes without modifying `public/`. The
public VPS deploy helper rejects candidates. Candidate staging requires
`PYBLE_FIRMWARE_LICENSE_EVIDENCE_DIR` and
`PYBLE_FIRMWARE_LICENSE_BUILD_ROOT`, and invokes the canonical audited-candidate
gate against those retained inputs. Public activation requires the exact local
annotated `firmware-v<version>` tag to peel to the `release.json` PyBLE
provenance commit. The helper canonically validates the all-HIL-passed public
staging, freezes it in a mode-0700 private snapshot, and proves exact staging,
packaged-output, and upload-snapshot byte equality. Final `out/` is copied to a
separate private read-only upload snapshot with a whole-site inventory; the VPS
authenticates that inventory separately and verifies the exact file set and all
hashes before publication or activation. The deploy helper rejects every
`tools/web/.env*` node before choosing a deployment mode. Canonical public
validation requires explicit
`PYBLE_FIRMWARE_LICENSE_EVIDENCE_DIR` and
`PYBLE_FIRMWARE_LICENSE_BUILD_ROOT` paths for the reviewed evidence and exact
release-build inputs. Activation is guarded by systemd rollback and
confirmation transactions until the public smoke suite succeeds.

MicroPython plus generic Bluetooth hardware is not itself a support claim.
Every advertised target needs a conforming PBLE/1 BLE GATT peripheral agent
port and the required build, conformance, resource/recovery, and HIL evidence.

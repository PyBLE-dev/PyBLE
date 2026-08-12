# PyBLE — Public Website Specification

Status: **FROZEN (pre-v1 and v1 launch surface)** · Owner: project maintainer · Last updated:
2026-08-07

This document is the source of truth for the first public website at
`pyble.dev`. It specifies only the public site; the Flutter app, PBLE/1, and
firmware remain governed by their own specifications.

## 1. Purpose and boundaries

The website MUST explain PyBLE accurately, help a beta user get started or ask
for support, publish the app's privacy posture, and provide a gated browser
firmware installer for the exact initial ESP32-family image profiles. The
installer MUST distinguish a hardware-tested public beta from a fully
qualified public release.

It MUST NOT imply that:

- the app or firmware is generally available before its release channel exists;
- every hardware-eligible MicroPython/Bluetooth board already has a maintained
  PyBLE agent port, or that every Python program is supported;
- a web flasher works before reviewed manifests and binaries are published;
- cloud sync, accounts, telemetry, charts, public issue tracking, or other
  backlog features have shipped.

Public statements MUST distinguish currently implemented behavior from
roadmap/beta behavior.

## 2. Domains and routes

`https://pyble.dev` is the canonical origin. HTTPS is mandatory. The deployment
edge MUST permanently redirect `pyble.org` and `www.pyble.org` to the same path
and query on `https://pyble.dev`.

The launch surface is:

| Route      | Contract                                                                                                                |
| ---------- | ----------------------------------------------------------------------------------------------------------------------- |
| `/`        | Product identity, BLE-first workflow, verified capabilities, compatibility, open-source posture, and beta status        |
| `/app`     | Stable first-party app landing page, current approved distribution link/QR, firmware setup, and support                 |
| `/privacy` | Separate, plain-language disclosures for the Flutter app and public website                                             |
| `/support` | Getting-started guidance, troubleshooting, diagnostics checklist, and a direct support contact                          |
| `/flash`   | Versioned browser provisioning, compatibility/erase consent, integrity status, recovery, and install action gated by §7 |

Every route MUST have a unique title and description. The site MUST publish a
canonical URL, sitemap, robots policy, web manifest, social metadata, and a
useful not-found page.

Document routes use no trailing slash, except the root `/`. The host MAY
permanently normalize a trailing-slash request to its slashless equivalent.

## 3. Information architecture and claims

The home page MAY make these verified claims:

- PyBLE means “Python over Bluetooth Low Energy.”
- It is a free, MIT-licensed, tablet-first MicroPython IDE designed for
  microcontroller boards that can run MicroPython and host a compatible
  Bluetooth Low Energy PyBLE agent.
- Classic ESP32, ESP32-S3, and ESP32-C3 are the initial beta firmware targets,
  not the permanent platform boundary.
- After one-time wired firmware provisioning, its normal workflow is BLE-first.
- The app can scan/connect, edit, save, run, stop, soft reboot, exchange board
  files, and provide a live console over PBLE/1.
- Blocks runs offline, includes editable beginner examples, supports the
  current explicit numeric-GPIO and standard MicroPython NeoPixel subset, and
  can reopen exact sidecars or import a deliberately bounded Python subset.
  Numeric GPIO and NeoPixel are initially validated on ESP32-family firmware
  and MUST NOT be promised for every future port. The bundled TFT authoring
  surface requires the separate exact-board firmware or a user-installed
  compatible runtime; it is not a generic-S3 firmware claim.
- PBLE/1 is an open PyBLE-owned protocol.

Compatibility copy MUST distinguish platform scope from current support:

- hardware eligibility requires MicroPython, a PBLE/1-capable BLE peripheral
  stack, sufficient resources, and a conforming agent port;
- actual support requires a published firmware image for the exact target and a
  truthful release state; browser-installation validation for a beta is
  narrower than complete release qualification;
- the current public-beta list remains the exact `v0.4.2` `esp32-4mb` and
  `esp32-s3-n16r8` profiles; that frozen two-profile exception MUST NOT be
  interpreted as the qualified `v0.5.1` release shape;
- the qualified `v0.5.1` release contract requires exactly `esp32-4mb`, the
  lean generic `esp32-s3-n16r8`, and the separate exact-board
  `waveshare-esp32-s3-lcd-147b` profile; this is an activation contract, not a
  claim that those release bytes are currently public; ESP32-C3 remains an
  initial firmware target but is planned/unavailable until its exact profile
  passes real-hardware HIL;
- the generic `esp32-s3-n16r8` image MUST NOT bundle `pyble_st7789`,
  `pyble_waveshare_lcd147b`, exact-board pin data, or the boot splash; the
  Waveshare profile MUST use its own manifest and different immutable firmware
  bytes containing those bounded display additions;
- matching ESP32-S3 chip family, 16 MiB flash, and 8 MiB Octal PSRAM does not
  identify onboard peripherals: the two S3 profiles MUST remain separate, and
  the Waveshare profile MUST NOT be evidence that every ESP32-S3 board is
  compatible;
- browser provisioning is offered only for the exact memory profiles in §7,
  including N16R8-class hardware for the initial ESP32-S3 image, and MUST show
  whether those bytes are a hardware-tested beta or a qualified release;
- users select pins for their exact board and wiring.

It MUST NOT imply that Bluetooth hardware or stock MicroPython alone is enough,
or promise that every eligible board has a firmware image today.

### 3.1 App beta distribution

The currently approved app-testing channels are:

- the public Apple external-testing invitation at
  `https://testflight.apple.com/join/yU4e8s6d`; and
- the restricted Android internal-testing listing at
  `https://play.google.com/store/apps/details?id=dev.pyble.pyble`, available
  only to approved testers signed in with the Google account that was invited.

While either channel is active, the home page and `/app` MUST:

- distinguish the iPad external beta from the Android internal test, without
  implying a production App Store or public Google Play release;
- explain that an unapproved or signed-out visitor may be unable to open the
  restricted Google Play listing;
- provide a normal HTTPS link that works on the device displaying the page;
- provide a high-contrast QR code encoding each channel's exact HTTPS
  destination for a user viewing the site on another screen; and
- keep the links and QR codes local to authored static content, with no URL
  shortener, tracking redirect, remote QR service, or third-party runtime
  request.

Each QR code MUST be accompanied by an accessible link and visible
instructions; it is an additional path, never the only way to open its testing
channel. A changed or withdrawn destination requires the specification, content
contract, and corresponding QR asset to change together before deployment.

`https://pyble.dev/app` is the stable first-party app-discovery destination
encoded by exact-board firmware. It MUST be a complete statically rendered
document, not an external redirect. It MUST have its own canonical metadata,
identify the iPad external beta and restricted Android internal test (not
production store releases), reuse `siteConfig.testFlightUrl` and
`siteConfig.googlePlayInternalTestUrl` as the approved destination sources,
present both local authored QR codes plus visible direct-URL fallbacks, and link
to `/flash` and `/support`. Its firmware wording MUST remain release-state-neutral
or derive from the same build-selected state as the home page; it MUST NOT copy
a version/profile claim that can become stale.

`/app/` MUST permanently normalize to `/app` while preserving the query. Exact
document routing MUST coexist with the existing `/app/*` real-app screenshot
asset namespace: adding or redirecting the document MUST NOT capture, rename,
or break those nested static paths. A website-only deployment that adds or
changes `/app` MUST preserve and revalidate the active `/flash` selector and
firmware bytes under §6.1.

### 3.2 Public source repository

The canonical public source repository is
`https://github.com/PyBLE-dev/PyBLE`. The home page MUST identify the app,
board-agent firmware, PBLE/1 protocol, tests, and documentation as public,
MIT-licensed source and provide a prominent, accessible link to that exact
repository. The global footer MUST provide the same repository link so it
remains available from every launch route.

Repository links MUST be ordinary HTTPS links and MUST NOT use a tracking
redirect, embedded GitHub widget, remote badge, or client-side network request
to present their primary information. If a link opens a new browsing context,
it MUST use `noopener noreferrer`.

### 3.3 Public-beta social metadata

The home page MUST publish a local `1200 × 630` social image and large-card
metadata suitable for the external beta announcement. The image MUST use the
canonical prompt-chip mark and a privacy-reviewed capture of the real app
described in §4. It MAY add authored brand text and framing, but MUST NOT
retouch or generate the pictured app interface. Its claims MUST be limited to
the current iPad external beta and the exact installer profiles and release
state actually available.

The social image MUST have useful alternative text, remain legible under
common center crops, and make no third-party runtime request. A QR code MUST
NOT be the only invitation path or be embedded in the wide social card, where
platform cropping can make it unreliable. A separate local square TestFlight
card MAY include the exact invitation QR, visible destination, and plain-text
instructions.

### 3.4 Transitional firmware beta claims and support intake

This subsection is a frozen source-era exception for `v0.4.2` only. Its exact
two-profile language and digest MUST NOT be generalized to, or used to validate,
the three-profile `v0.5.1` release contract.

Until the first firmware selector passes the complete qualified-release gate in
§7, the repository README and home page MUST NOT describe either `v0.4.2` profile
or its browser image as a qualified release. The exact audited `v0.4.2`
public-beta selector MAY make the `esp32-4mb` and `esp32-s3-n16r8` images
available under the exception in §7. Following the production browser-flashing
validation recorded in
`docs/validation/browser-flashing/v0.4.2-production.json`, every active
installer state MUST instead identify these exact bytes as a
**hardware-tested firmware beta** and say that real-board browser installation
and interrupted-flash recovery passed for both enabled exact profiles. It MUST
also distinguish that narrow result from complete release qualification and
MUST NOT say or imply that the beta is access-controlled, a qualified release,
fully validated, production-ready, or generally available. The home-page target
cards MUST identify the constraints as
`esp32-4mb` (classic ESP32, 4 MiB external SPI flash, no PSRAM assumed) and
`esp32-s3-n16r8` (ESP32-S3, 16 MiB flash, 8 MiB **Octal** PSRAM), and give each
the truthful hardware-tested-beta/release-qualification-pending state while
that selector is active.
`esp32-c3-4mb` remains a separate planned, unavailable profile and MUST NOT be
present in the beta selector, release metadata, public firmware tree, or
recovery commands.

The repository README, home-page hero, provisioning workflow, exact-profile
cards, TestFlight callout, support getting-started guide, and public roadmap
MUST agree with the build-selected installer state. While the exact beta
selector is active, each `v0.4.2` profile status MUST name `v0.4.2`,
**hardware-tested beta**, and **release qualification pending**; installation
instructions MUST direct users to the enabled `/flash` action while preserving
the exact profile, backup, erase, cable/power, and port acknowledgements. They
MUST name the completed browser installation and interrupted-flash recovery
scope rather than the stale blanket phrase **full HIL pending**. When no selector
is active, including an explicit installer-disable deployment, the generated
home and support pages MUST instead say that the installer is unavailable and
MUST NOT claim that the beta is available. The roadmap MUST mark the exact
`v0.4.2` two-profile browser-flashing validation complete while retaining the
broader app, PBLE/1, resource, and release-qualification work. Every one of
those surfaces MUST keep C3 explicitly unavailable.

README getting-started instructions MUST gate destructive flashing on `/flash`
showing an active version, exact profile, and enabled install action. While the
installer is unavailable, they MUST NOT instruct a reader to select or flash a
supposedly qualified public image. A real-app capture caption MUST describe only
what is visible; it MUST NOT claim that a physical board is pictured when the
capture shows only the app.

The wide social card MUST describe the workflow as one-time USB setup followed
by everyday use over BLE. If it advertises the enabled `v0.4.2` web flasher, it
MUST use the narrow claim **web flashing validated** and MUST NOT imply complete
release qualification. Its mechanically rendered PNG and authored SVG MUST
remain paired by reviewed content and exact-dimension tests.

Every changed social-card byte set MUST use a new content-versioned public
pathname before its metadata is deployed. Replacing a PNG or SVG at an existing
pathname is forbidden because the public CDN may retain the previous bytes
after an origin release changes. Tests MUST bind the metadata URL, local
pathname, dimensions, and reviewed SHA-256; production verification MUST fetch
that exact URL and compare the deployed bytes.

The support route MUST link directly to the preferred GitHub bug template at
`https://github.com/PyBLE-dev/PyBLE/issues/new?template=bug.yml`. Installer
intake MUST request the exact profile ID, board/model and module marking, flash
capacity, PSRAM capacity and type, browser name/version, desktop operating
system/version, failed installer stage, redacted error text, exact tablet/device
model, and tablet operating system/version (iPadOS or Android). The issue
template and support-page checklist MUST agree on those fields and remind users
to remove secrets and personal identifiers.

## 4. Brand and visual contract

The canonical prompt-chip SVG in `app/assets/branding/` is the source asset. A
byte-identical copy MAY be placed in the website's public directory so the
standalone package builds without reaching outside its root.

The visual system uses:

- deep navy `#081B35`;
- signal blue `#2F8CFF`;
- near-white `#F4F7FF`;
- the app's Signal seed `#2D5BFF` where a stronger interactive accent is needed.

The logo itself MUST NOT be recolored, given a gradient, distorted, or combined
with the Bluetooth trademark.

The home-page hero MUST show a privacy-reviewed capture of the current PyBLE
app, not a fabricated interface. The capture MAY come from a physical tablet or
an Apple/Android simulator running the production app surface. It MUST show a
complete, successful user state; use only public example code and generic board
details; and contain no personal label, device identifier, notification,
private file, traceback, error banner, or debug chrome. Its accessible
description and nearby caption MUST identify it as the actual app and state
what capability is visible. A capture may be losslessly reoriented for display,
but its interface content MUST NOT be retouched or generated.

Supplemental interface illustrations may be authored in HTML and CSS. Stale
screenshots, debug screens, and unresolved UI regressions MUST NOT be published.
Every committed app capture MUST be re-reviewed when the pictured surface
changes materially.

The layout MUST remain coherent from a 320 CSS-pixel phone viewport through
landscape tablets and wide desktop screens. Keyboard focus, semantic landmarks,
contrast, reduced-motion preferences, and a skip link are release requirements.

## 5. Privacy contract

At launch the website has no account, advertising, analytics, tracking pixel,
contact form, or non-essential cookie. It loads no runtime font, image, or script
from a third-party marketing service.

The route MUST be titled **PyBLE Privacy Policy**, display its effective date,
and identify PyBLE as an independent open-source project maintained by Viwat
Vchirawongkwin under the SciLabPro project name. It MUST state that PyBLE is not
an official Chulalongkorn University project or app; it MUST NOT claim that
SciLabPro is a legal entity.

The privacy route MUST keep these systems and data flows distinct:

- **PyBLE app:** no account, advertising, analytics, telemetry, crash-reporting,
  payment, or cloud service. The current production app makes no HTTP request;
  the placeholder GitHub-import package MUST NOT be described as a current
  feature. The developer receives no app project content.
- **User-selected board:** Save, Run, Files, and console actions transmit source
  code, paths or filenames, file content, Blocks companion data, or console
  input directly over BLE to the board the user selected. Board files remain on
  that board until the user overwrites or deletes them or erases the board.
  This expected device transfer MUST NOT be misrepresented as a transfer to a
  PyBLE or SciLabPro server.
- **Transport security:** PBLE/1 does not require pairing or BLE link encryption.
  The policy MUST NOT promise that board traffic is encrypted and MUST advise
  users not to send secrets without a separately verified secure environment or
  transport.
- **Nearby-board data and permissions:** BLE names or labels, platform device
  identifiers or suffixes, capabilities, and signal strength are processed
  locally for discovery and connection and are not sent to the developer.
  Android's legacy location permission exists only to support BLE scanning on
  older Android versions; PyBLE does not derive, store, or transmit physical
  location. If a board has a custom label, that board may advertise it to other
  nearby devices, so the label must contain no sensitive information.
- **Retention and deletion:** the policy MUST distinguish volatile app working
  data from content persisted on the selected board. It MUST explain how to
  clear or uninstall local app data, how to delete board files, and that deleting
  the app does not delete board or exported copies. Because the developer does
  not receive app project content, there is no PyBLE server-side project copy to
  retain or delete.
- **Third-party components and platforms:** the app contains no advertising,
  analytics, crash-reporting, or account SDK that receives app project content.
  Operating-system and distribution-platform services remain governed by their
  own policies.
- **Public website:** the site itself does not profile visitors. Cloudflare and
  the VPS hosting infrastructure may process ordinary request data such as IP
  address, user-agent, requested URL, timestamp, and security signals to deliver
  and protect the site. The policy MUST NOT invent a fixed log-retention period
  unless the infrastructure owner has verified one.

The policy MUST provide the current working contact method for privacy and
deletion questions. A proposed project-domain mailbox MUST NOT replace it until
the maintainer has verified that the mailbox exists and is monitored. Adding
analytics, forms, accounts, embedded media, functional network import, or other
data collection requires a spec and policy change before deployment.

## 6. Technical contract

The package lives at `tools/web/` and uses:

- Next.js App Router with static export;
- vinext's Vite-based adapter for the Sites deployment artifact;
- React and strict TypeScript;
- npm with a committed lockfile;
- local CSS and system fonts;
- Vitest and Testing Library for component/content contracts;
- ESLint, TypeScript checking, and both production build paths in CI.

No production page may depend on an application-owned backend, database, runtime
environment secret, remote CMS, or network request to render its primary
content. The package MUST be buildable with `npm ci && npm run check`.

`tools/web/out/` is the canonical, portable Next.js static export and the
production artifact for the canonical VPS origin. The Sites adapter MUST
additionally emit a generated, gitignored `tools/web/dist/` owner-preview and
hosting-compatibility artifact using a supported vinext entrypoint at
`dist/server/index.js`. That artifact MUST include the exact
`.openai/hosting.json` project binding at `dist/.openai/hosting.json`.

The vinext handler is a hosting envelope around the same authored routes, not an
application backend: all launch content remains build-time source, all routes
MUST return complete HTML without client JavaScript, and no route may introduce
a runtime data dependency. Every launch route and the not-found page MUST be
listed as `rendered` in `dist/server/vinext-prerender.json`; a skipped or dynamic
launch route fails the build. Robots, sitemap, and web-manifest responses MUST
be static public files rather than runtime metadata handlers. `npm run check`
MUST validate both the portable static export and the Sites artifact.

The Sites entrypoint MUST be a Cloudflare module-worker default export with a
`fetch(request, environment, context)` method. It MUST delegate launch routes,
their normalization redirects, and known static-asset paths to vinext, passing
the execution context as vinext's second argument. Any other pathname MUST
return the generated not-found HTML with status 404 directly, without entering
a dynamic route renderer.

Website source and tests participate in the no-leak gate. Comment-capable source
files carry the MIT SPDX header. Generated output and dependencies are ignored.

### 6.1 Canonical production origin

The canonical public deployment is Cloudflare in front of a dedicated HTTPS
VPS origin. The origin MUST:

- serve the checked `out/` tree as static files through Nginx, with no
  long-running Node.js website process;
- store immutable releases below `/srv/pyble/releases/` and atomically select
  the active release through `/srv/pyble/current`;
- bind every release to the exact committed source revision that produced it
  and retain at least one preceding known-good release for rollback;
- arm a transport-independent rollback watchdog before changing the active
  release and confirm it only after the public smoke suite succeeds; transient
  service-manager jobs MUST receive their embedded shell programs verbatim,
  with manager-side environment expansion disabled;
- map `/app`, `/privacy`, `/support`, and `/flash` to their exported HTML without
  changing the canonical slashless URL;
- normalize the corresponding trailing-slash URLs permanently, preserve query
  strings, and return the generated 404 document with status 404 for an unknown
  path;
- cache fingerprinted `/_next/static/` assets immutably while serving HTML with
  `Cache-Control: no-cache, no-transform`, so the public edge revalidates the
  release without rewriting its content;
- cache only successful versioned firmware responses immutably, serve every
  firmware 4xx/5xx with `Cache-Control: no-store`, and use the selected
  `release.json` SHA-256 as the deterministic cache key for both verification
  and ESP Web Tools retrieval;
- serve `/firmware/v0.4.2/` only while the exact audited public-beta selector
  defined in §7 is active; its successful immutable responses use the ordinary
  versioned-firmware cache policy, while every missing/error response remains
  `no-store`; its frozen two-profile schema and digest are immutable and MUST
  NOT be revalidated as a `v0.5.1` three-profile release;
- use a valid origin certificate with Cloudflare **Full (strict)** TLS, never
  Flexible mode; and
- expose only the required web and key-authenticated administration ports.

After a public installer is activated, an ordinary website-only deployment MUST
preserve that exact immutable selected release.
The deployment obtains the selector and firmware tree from the current managed
release over the authenticated deployment transport, validates them through
the preserved-public staged-release and checksum gates, and embeds the selector
at build time. That carry-forward gate repeats the self-contained bundle,
schema, HIL, profile, artifact, path, size, digest, descriptor, and
annotated-tag checks. A preserved qualified release does not repeat the
source/build license audit because the exact immutable bytes already passed that
audit during its original activation. The exact `v0.4.2` public beta is a fresh
pending candidate and MUST instead repeat canonical `--audited-candidate`
validation with its retained license-evidence directory and exact build root on
every deployment that carries it forward. That validation MUST receive the
exact firmware-source checkout recorded by the release, rather than substituting
the later website checkout. A preserved qualified release MUST NOT require
those retained beta source/build/evidence inputs.
It MUST NOT infer availability from the mere presence of a firmware directory
or accept a caller-supplied selector.

Each release carrying an active selector MUST retain a hidden, unserved copy of
the canonically validated selector as deployment state. A replacement staged
public release supersedes this carry-forward state only after the full §7
activation gate passes. Intentionally disabling an active installer requires a
dedicated, truth-valued deployment flag; the deployment MUST reject ambiguous
values and any invocation that both stages firmware and requests disablement.
The public smoke test MUST prove whether the resulting `/flash` page embeds the
expected active release or the explicitly disabled state. A missing selector,
failed carry-forward validation, or unreviewed implicit transition from active
to unavailable aborts before the website build or activation.

The public edge MUST redirect `www.pyble.dev`, `pyble.org`, and
`www.pyble.org` to the same path and query at `https://pyble.dev`. Origin
configuration SHOULD mirror those redirects as defense in depth once their DNS
and certificates are active. The public edge MUST preserve each launch-route
HTML response byte-for-byte; it MUST NOT rewrite contact addresses or inject a
runtime decoder script.

Host addresses, SSH and TLS private keys, Cloudflare credentials, and other
deployment secrets MUST NOT be committed.

## 7. Firmware installer release gate

The detailed, frozen release contract is
[firmware/browser-flashing.md](firmware/browser-flashing.md). It owns the exact
image profiles, offsets, same-origin layout, manifest, integrity/provenance
metadata, recovery content, and HIL matrix. This section owns the website state
and user experience.

The exact `v0.4.2` public-beta selector remains limited to `esp32-4mb` and
`esp32-s3-n16r8` and is governed only by the narrow exception below. It MUST
NOT be treated as a qualified release or broadened with a Waveshare profile.

For a qualified `v0.5.1` activation, the required public profiles are exactly,
and in this order: `esp32-4mb`, `esp32-s3-n16r8`, and
`waveshare-esp32-s3-lcd-147b`. The generic S3 and exact-board Waveshare images
both require 16 MiB flash plus 8 MiB Octal PSRAM, use ESP Web Tools family
`ESP32-S3`, and install a merged image at offset `0`, but they MUST have
separate single-build manifests and different immutable firmware bytes. The
generic image is intentionally lean: it contains the common PyBLE agent and
standard runtime but no `pyble_st7789`, `pyble_waveshare_lcd147b`, exact-board
pin constants, display boot hook, or splash. The exact-board image alone owns
those bounded display additions.

The known `esp32-c3-4mb` profile remains an initial v1 target but is explicitly
unavailable until exact-profile real-hardware validation is complete. It MUST
be shown separately as planned/unavailable and MUST NOT appear in the active
selector, release metadata, public firmware paths, or recovery commands. ESP
Web Tools' family detection is necessary but not sufficient to establish
memory topology, silicon revision, or board peripherals; in particular, it
cannot distinguish the two S3 profiles.

The `/flash` page MUST make the exact Waveshare ESP32-S3-LCD-1.47B discoverable
without weakening that profile boundary. When—and only when—the build-selected
qualified release is `v0.5.1` or newer, the page MUST:

- identify the board as the separate
  `waveshare-esp32-s3-lcd-147b` provisioning profile and direct its install
  action only to that profile's own single-build manifest and merged firmware
  image, never to the generic S3 manifest;
- state the exact 16 MiB flash / 8 MiB Octal-PSRAM requirement, the integrated
  172 × 320 ST7789V3 display, and its bundled `pyble_st7789` and
  `pyble_waveshare_lcd147b` runtimes; state equally clearly that the lean
  `esp32-s3-n16r8` image does not bundle them;
- require an explicit acknowledgement that the connected board is the exact
  ESP32-S3-LCD-1.47B **B-version** with the stated memory topology; matching
  `ESP32-S3` family detection alone MUST NOT satisfy this consent;
- explain that a fresh erased installation shows the cosmetic PyBLE/app-QR
  boot splash by default, that users may persistently disable or re-enable it,
  and that it does not detect or select the board; and
- show the same local, project-owned real-hardware photograph on the home page
  and in this `/flash` board section. The content-versioned public asset MUST
  be a metadata-stripped, progressive `1600 × 1116` JPEG no larger than 250000
  bytes at
  `/boards/esp32-s3-lcd-1.47b-pyble-v0.5.0.jpg`, with SHA-256
  `b939abb9b7ac19c7be8f429faaa61d08aadc7f027eac181582e036fd22949d12`.
  Its useful alternative text and visible caption MUST identify an actual
  ESP32-S3-LCD-1.47B displaying the PyBLE v0.5.0 splash and app QR; and
- label the home-page target group **Qualified public firmware targets** in
  both visible copy and its accessible name, with no stale beta wording; and
- keep the generic S3 warning, destructive-flash acknowledgements, integrity
  verification, recovery command, and all release gates unchanged.

An unavailable selector, a candidate, or a failed/pending public release MUST
NOT claim that the exact-board profile is active or expose its install action
or qualified-board photograph. The exact `v0.4.2` beta has only its two frozen
profiles and MUST NOT claim that either image contains the Waveshare display
modules or boot splash. A provisioning profile identifies distinct release
bytes for user-selected installation; it is not a PBLE/1 capability, app
runtime routing profile, automatic board-detection request, or automatic
splash enablement.

One narrow pre-qualification exception exists for the fresh audited `v0.4.2`
candidate. A build-time selector MAY use deployment mode `public-beta` only
when all of these facts are true:

- `version` is exactly `0.4.2`, `releaseJson.sha256` is exactly
  `5d1b0db8c4b90cccf054cd244530afb3b9112d489aa02f7c5da650e92161acde`,
  `hilStatus` is `pending`, and `accessControlled` is `false`;
- the selector contains exactly `esp32-4mb` and `esp32-s3-n16r8` with the
  frozen paths, offsets, memory requirements, and silicon windows; C3 is absent;
- the same-origin `release.json`, schema, manifests, firmware, documents, and
  `SHA256SUMS` pass the existing path, shape, size, and SHA-256 integrity checks;
- the canonical release tool accepts the exact bundle with
  `validate --audited-candidate`, the retained license-evidence directory, and
  the exact release-build root, using the exact firmware-source checkout
  recorded by the release as `--repo-root`; the annotated `firmware-v0.4.2` tag
  exists and peels directly to `release.json` provenance; and
- `/flash` visibly labels the firmware a **hardware-tested firmware beta**,
  names the completed real-board browser installation and interrupted-flash
  recovery scope for both enabled profiles, says complete release qualification
  remains pending, and never calls it protected, access-controlled, a qualified
  release, fully validated, production-ready, or generally available.

This exception attests the identity, integrity, provenance, and audited-candidate
license state of the exact bytes; it does not manufacture HIL evidence. It MUST
NOT accept another version or
digest, broaden either profile, enable C3, or satisfy any qualified-release
gate. Removing or replacing the beta requires an explicit deployment action and
production smoke verification. A later website-only deployment MAY carry the
same exact beta selector and byte tree forward only by repeating the same
audited-candidate, license-evidence, annotated-tag, and integrity gates.

Except for that exact transitional beta, the `/flash` action MUST fail closed
and remain explicitly unavailable until all of the following are true for one
exact immutable version:

1. two clean, provenance-recorded, reproducible builds produced
   byte-identical artifact sets for all three required release profiles from
   the frozen source/toolchain pins, while the maintained chip-target
   source/toolchain audit remained green;
2. the versioned, same-origin profile-scoped ESP Web Tools manifests and separate
   `release.json` size/SHA-256 metadata pass the automated artifact, image,
   partition, path, schema, license, and integrity gates;
3. the final hash-locked bytes passed the complete browser-install and
   interrupted-flash recovery HIL matrix independently on real hardware for all
   three exact required release profiles from an access-controlled,
   production-equivalent HTTPS candidate
   deployment, while the public action remained disabled;
4. the exact bytes, release notes, licenses, recovery guide, and HIL report are
   published in the canonical immutable
   `https://pyble.dev/firmware/v<version>/` directory; a v0.x mirror is optional
   and MUST be byte-identical if present, while v1.0 and later additionally
   require the matching byte-identical GitHub Release;
5. the website embeds that versioned `release.json` path and reviewed SHA-256,
   locally bundles an exact reviewed ESP Web Tools version, and makes no
   third-party runtime request; its exact bundled npm closure is covered by a
   mechanically generated `WEBSITE_THIRD_PARTY_LICENSES.txt` linked from
   `/flash`; and
6. the activation deployment passes a non-destructive production-origin
   retrieval, redirect, size, SHA-256, CSP, and render smoke test.

For either the exact public beta above or a release whose gate is green,
`/flash` MUST render an active action only after:

- secure-context, `navigator.serial`, and Web Crypto capability detection;
- exact profile selection and the compatibility/backup/erase/cable/power
  acknowledgements;
- for `waveshare-esp32-s3-lcd-147b`, separate explicit confirmation of the
  exact B-version board and its 16 MiB flash / 8 MiB Octal-PSRAM topology;
- verification of the selected profile's single-build manifest and binary
  bytes against the embedded
  metadata root; and
- a visible version, profile, integrity result, destructive-install warning,
  and version-matched recovery link.

Stock ESP Web Tools has no SHA-256/size fields in its manifest. The client MUST
therefore perform the separate verification defined by the firmware flashing
spec before exposing its locally bundled custom element, and MUST give that
element only the selected profile's verified single-build manifest. A failed request,
redirect, schema check, digest, size, path, offset, chip-family, or cross-file
check returns to an unavailable state; a mismatched connected family is
rejected instead of selecting another image.

Future non-ESP32 ports MAY require another reviewed provisioning backend and
artifact format. Adding one requires a specification and test change; it MUST
NOT weaken PyBLE's BLE-first runtime contract.

The installer is a browser-only component and MUST explain that this is
one-time wired provisioning, not PyBLE's runtime transport. Capability is
detected rather than guessed from the user-agent. The unsupported state MUST
explain that iPadOS cannot perform the wired Web Serial provisioning step and
direct the user to a supported desktop Chromium browser. The page's explanatory
content and recovery guidance remain available without client JavaScript.

## 8. Acceptance criteria

The v1 site is releasable when:

- all five routes and the not-found state render without client JavaScript;
- route metadata and canonical URLs are correct;
- navigation is accessible by pointer and keyboard at phone, tablet, and desktop
  widths;
- unit/content tests cover canonical domains, navigation, privacy promises, and
  every disabled/unsupported/verifying/failed/qualified flasher state;
- the hero uses a reviewed real-app capture with meaningful alternative text,
  a visible actual-app caption, and a responsive crop that never obscures the
  pictured Blocks workspace or generated Python;
- the current external iPad beta and restricted Android internal test are each
  exposed as an operable link and locally served, exact-URL QR code without
  claiming production availability;
- `/app` is canonical, statically rendered, uses both approved testing-channel
  destination/link/QR contracts, links setup and support, and its slash
  normalization does not break an existing nested `/app/*` screenshot asset;
- the home page publishes a local `1200 × 630` real-app social card with useful
  alternative text and large-card metadata, plus a separate local square
  TestFlight invitation card;
- the canonical public source repository is explained in a visible
  MIT-licensed-source section and linked from both that section and the global
  footer;
- lint, strict type checking, tests, static export, Sites vinext build, SPDX, and
  no-leak gates pass;
- the Sites artifact contains `dist/server/index.js` and the exact project
  binding at `dist/.openai/hosting.json`;
- every launch route is rendered in the vinext prerender manifest and robots,
  sitemap, and web manifest are static client files;
- an unknown pathname returns the generated not-found page with status 404;
- generated output contains no unsupported third-party runtime request;
- the active flasher, when selected, names an exact profile and its truthful
  beta-or-qualified state; verifies the embedded release-metadata root plus
  every manifest part; requires compatibility/backup/erase consent; and links
  the matching recovery guide;
- a qualified `v0.5.1`-or-newer active selector names
  `waveshare-esp32-s3-lcd-147b` separately from the lean
  `esp32-s3-n16r8`, gives each its own manifest and firmware bytes, and requires
  exact-board consent for the Waveshare action; the exact `v0.4.2` beta, pending,
  candidate, failed, and unavailable states make no active exact-board claim;
- three-profile release tests prove that the generic S3 image omits the
  Waveshare display runtime and splash while the exact-board image contains
  them, without treating either provisioning profile as an app connection gate;
- that same qualified selector renders the exact reviewed local board photo on
  both home and `/flash`, while all older or unqualified states omit it; tests
  bind its pathname, dimensions, byte ceiling, SHA-256, alternative text, and
  caption, and the static export makes no remote image request;
- all versioned firmware files are same-origin, immutable, byte-identical to
  the reviewed release, and retrievable from the public production origin;
- browser verification and the subsequent ESP Web Tools fetches use the same
  deterministic release-root cache key, while retaining exact-path,
  no-redirect, size, and SHA-256 validation;
- the VPS deployment contract is tested, the exact checked `out/` release is
  active through the atomic release symlink, and an origin configuration test
  passes before reload;
- a website-only deployment after public installer activation carries the
  exact selected release forward, while an intentional transition to the
  unavailable state requires the explicit disable flag and production smoke;
- rollback confirmation survives loss of its initiating SSH transport and
  executes its embedded shell variables without service-manager rewriting;
- every public launch-route HTML response is byte-identical to the checked
  `out/` file, including routes containing contact addresses;
- public HTTPS uses Cloudflare Full (strict), canonical and trailing-slash
  redirects preserve path/query as required, and an unknown public path returns
  status 404;
- the canonical site is reviewed before public deployment, and the `.org`
  redirect is verified after DNS activation.

# PyBLE — Public Website Specification

Status: **FROZEN (pre-v1 and v1 launch surface)** · Owner: project maintainer · Last updated:
2026-07-31

This document is the source of truth for the first public website at
`pyble.dev`. It specifies only the public site; the Flutter app, PBLE/1, and
firmware remain governed by their own specifications.

## 1. Purpose and boundaries

The website MUST explain PyBLE accurately, help a beta user get started or ask
for support, publish the app's privacy posture, and provide a gated browser
firmware installer for the qualified initial ESP32-family image profiles.

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
  Those hardware APIs are initially validated on ESP32-family firmware and
  MUST NOT be promised for every future port.
- PBLE/1 is an open PyBLE-owned protocol.

Compatibility copy MUST distinguish platform scope from current support:

- hardware eligibility requires MicroPython, a PBLE/1-capable BLE peripheral
  stack, sufficient resources, and a conforming agent port;
- actual support requires a released, validated firmware image for the target;
- the current pre-v1 release list is the exact `esp32-4mb` and
  `esp32-s3-n16r8` profiles; ESP32-C3 remains an initial firmware target but
  is planned/unavailable until its exact profile passes real-hardware HIL;
- browser provisioning is offered only for the exact qualified memory profiles
  in §7, including N16R8-class hardware for the initial ESP32-S3 image;
- users select pins for their exact board and wiring.

It MUST NOT imply that Bluetooth hardware or stock MicroPython alone is enough,
or promise that every eligible board has a firmware image today.

### 3.1 External beta distribution

The currently approved Apple external-testing channel is the public TestFlight
invitation at `https://testflight.apple.com/join/yU4e8s6d`. While that channel
is active, the home page MUST:

- describe the iPad app as open for external beta testing, without implying a
  production App Store release or an Android distribution channel;
- provide a normal HTTPS link that works on the device displaying the page;
- provide a high-contrast QR code encoding that exact HTTPS invitation for a
  user viewing the site on another screen; and
- keep the invitation link and QR local to authored static content, with no URL
  shortener, tracking redirect, remote QR service, or third-party runtime
  request.

The QR code MUST be accompanied by an accessible link and visible instructions;
it is an additional path, never the only way to open the invitation. A changed
or withdrawn invitation requires the specification, content contract, and QR
asset to change together before deployment.

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

The privacy route MUST keep these systems distinct:

- **PyBLE app:** no account, advertising, analytics, telemetry, or cloud workflow
  by default. Source files and settings stay on the tablet or connected board.
  BLE names, device identifiers/suffixes, and signal strength are processed
  locally for discovery and connection. A user-assigned board label may be
  broadcast by the board, so users must not put sensitive information in it.
- **Public website:** the site itself does not profile visitors. Its hosting and
  security providers may process ordinary request data such as IP address,
  user-agent, requested URL, timestamp, and security signals to deliver and
  protect the site.

The policy MUST provide a working contact method and display its effective date.
Adding analytics, forms, accounts, embedded media, or other data collection
requires a spec and policy change before deployment.

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
- map `/privacy`, `/support`, and `/flash` to their exported HTML without
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
- use a valid origin certificate with Cloudflare **Full (strict)** TLS, never
  Flexible mode; and
- expose only the required web and key-authenticated administration ports.

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

The current pre-v1 public profiles are exactly `esp32-4mb` and
`esp32-s3-n16r8`. The S3 image requires 16 MiB flash plus 8 MiB Octal PSRAM
and MUST NOT be described as suitable for every ESP32-S3 board. The known
`esp32-c3-4mb` profile remains an initial v1 target but is explicitly
unavailable until exact-profile real-hardware validation is complete. It MUST
be shown separately as planned/unavailable and MUST NOT appear in the active
selector, release metadata, public firmware paths, or recovery commands.
ESP Web Tools' family detection is necessary but not sufficient to establish
memory-profile or silicon-revision compatibility.

The `/flash` action MUST fail closed and remain explicitly unavailable until
all of the following are true for one exact immutable version:

1. two clean, provenance-recorded, reproducible builds produced
   byte-identical current release-profile artifact sets from the frozen
   source/toolchain pins, while the three-target source/build audit remained
   green;
2. the versioned, same-origin profile-scoped ESP Web Tools manifests and separate
   `release.json` size/SHA-256 metadata pass the automated artifact, image,
   partition, path, schema, license, and integrity gates;
3. the final hash-locked bytes passed the complete browser-install and
   interrupted-flash recovery HIL matrix on real hardware for both exact
   current release profiles from an access-controlled,
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

Once the gate is green, `/flash` MUST render an active action only after:

- secure-context, `navigator.serial`, and Web Crypto capability detection;
- exact profile selection and the compatibility/backup/erase/cable/power
  acknowledgements;
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

- all four routes and the not-found state render without client JavaScript;
- route metadata and canonical URLs are correct;
- navigation is accessible by pointer and keyboard at phone, tablet, and desktop
  widths;
- unit/content tests cover canonical domains, navigation, privacy promises, and
  every disabled/unsupported/verifying/failed/qualified flasher state;
- the hero uses a reviewed real-app capture with meaningful alternative text,
  a visible actual-app caption, and a responsive crop that never obscures the
  pictured Blocks workspace or generated Python;
- the current external iPad beta invitation is exposed as an operable link and
  a locally served, exact-URL QR code without claiming production availability;
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
- the active flasher, when selected, names an exact qualified profile; verifies
  the embedded release-metadata root plus every manifest part; requires
  compatibility/backup/erase consent; and links the matching recovery guide;
- all versioned firmware files are same-origin, immutable, byte-identical to
  the reviewed release, and retrievable from the public production origin;
- browser verification and the subsequent ESP Web Tools fetches use the same
  deterministic release-root cache key, while retaining exact-path,
  no-redirect, size, and SHA-256 validation;
- the VPS deployment contract is tested, the exact checked `out/` release is
  active through the atomic release symlink, and an origin configuration test
  passes before reload;
- rollback confirmation survives loss of its initiating SSH transport and
  executes its embedded shell variables without service-manager rewriting;
- every public launch-route HTML response is byte-identical to the checked
  `out/` file, including routes containing contact addresses;
- public HTTPS uses Cloudflare Full (strict), canonical and trailing-slash
  redirects preserve path/query as required, and an unknown public path returns
  status 404;
- the canonical site is reviewed before public deployment, and the `.org`
  redirect is verified after DNS activation.

# Changelog

Notable public changes to PyBLE are recorded here. App and firmware versions
are released independently from this monorepo.

## Unreleased

These app, website, and repository-source changes do not designate a new app
or firmware release. The qualified firmware release remains v0.6.0, built from
its annotated tag rather than from the newer branch tip.

The current compatible app feature set now targets `0.2.0`; its first local
beta candidate is build `5`. This candidate identity improves test and
evidence traceability but does not designate a qualified store release or
TestFlight handoff.

### App source

- Added Python syntax highlighting and synchronized one-based line numbers to
  the editor while retaining the plain-field fallback, offline boundary,
  smart-punctuation protection, and safe external-keyboard Tab behavior.
- Added localized, adaptive editor font-size controls with a 10–24 point
  editor-only app-session range. Code and gutter resize together, platform
  accessibility scaling remains active, and size changes preserve the document,
  board path, dirty state, selection, and undo history. Persistence remains
  intentionally deferred to the planned single Drift settings store.
- Pinned `flutter_code_editor` 0.3.5 behind the app-owned editor seam and
  recorded its complete dependency and licence closure, including the
  owner-ratified shipped `autotrie` 2.0.0 MPL-2.0 exception. Optional network,
  error, find, and autocomplete surfaces remain disabled.
- Added a connected Files action for browsing a canonical public GitHub
  repository without an account or token, resolving the requested ref once to
  a displayed immutable commit SHA, and lazily browsing bounded non-recursive
  Git trees.
- Added exact review and separate overwrite consent for importing selected
  ordinary lowercase `.py` files into the captured board folder. The complete
  size-bounded, strict-UTF-8 batch is fetched before sequential PBLE/1 writes;
  partial results identify succeeded, failed, and unattempted paths, refresh
  Files honestly, and never auto-open or auto-run downloaded code.
- Hardened GitHub import against redirects, unexpected hosts and object
  identities, incomplete board listings, reconnect/session races, response
  resource exhaustion, slow-trickle requests, and public API retry deadlines,
  with adaptive, keyboard-accessible, localized, and golden-tested states.
- Added session-bound multi-selection for eligible regular files shown in one
  board folder, with protected-path exclusion, exact confirmation, sequential
  fail-fast deletion, one reconciliation listing, and honest partial results.
  Folders retain their separate one-at-a-time empty-directory deletion.
- Advanced the independently versioned app source build from `0.1.0+2` to
  `0.1.0+3`, distinguishing this development build from TestFlight build 2.
- Advanced the independently versioned app source build from `0.1.0+3` to
  `0.1.0+4`, distinguishing this numbered-editor development build from build
  3.
- Started the compatible app `0.2.0` beta train at globally monotonic build
  `5`, synchronizing package metadata, PBLE/1 HELLO, and the public GitHub
  request identity without designating a qualified store release.
- Raised the maintained iOS/iPadOS deployment floor to `15.0` in every Xcode
  configuration and made the exported-IPA gate reject a lower app plist or
  compiled minimum. The retained build-5 iOS 13 artifact remains unchanged;
  this source-only change creates and uploads no build 6.
- Added the connected board's PBLE/1 board ID and PyBLE agent firmware version
  to Board info and retained both in the ready/running status pill, with
  localized missing-value handling, full accessibility context, and
  connection-session-safe updates.
- Added fail-closed Android upload signing and signed App Bundle CI contracts,
  while retaining invited Google Play testing as distinct from a public Play
  release.
- Extended every Blocks GPIO surface to accept explicit bounded MicroPython
  pin names such as `LED` while preserving numeric GPIOs, offline operation,
  and the app's board-neutral architecture.
- Hardened the Android WebView integration path so a named-pin edit made after
  preview is re-read from the live field before generated-code assertions.

### Website and repository source

- Added project-level `CITATION.cff` metadata and identified whole-project
  source snapshot `source-2026.08.23` with exact Zenodo DOI
  [`10.5281/zenodo.22064468`](https://doi.org/10.5281/zenodo.22064468) for
  scholarly citation while preserving the independently versioned app and
  firmware release identities.
- Established `PyBLE-dev/PyBLE` as the canonical public monorepo and added
  contributor, security, architecture, protocol, and validation documentation.
- Added an independent `/privacy` policy and stable `/app` landing page, with
  invited Android testing and public TestFlight presented as distinct channels.
- Patched the website PostCSS/Nanoid chain, upgraded vinext so `image-size` is
  absent from the installed dependency graph, and made high/critical npm audit
  findings fail the release gate.
- Hardened vinext's internally bundled image parser against the ICNS, HEIF, and
  JXL zero-length denial-of-service paths, with timeout-bounded regression
  inputs, fail-closed upstream-drift checks, static-image import guards, and
  complete MIT attribution while production remains a static-only deployment.
- Made publication CI fetch the complete source history required by
  ancestry-routed firmware gates, and made the RP2 runtime-closure fixture
  hermetic instead of depending on a retained local archive.
- Made RP2 builds report a missing or mismatched pinned Arm toolchain before
  evaluating the nested source graph, while preserving fail-closed source
  validation once the compiler is present.
- Corrected two C3 ADR links for the public repository layout.

## Website deployment — 2026-08-22

- Activated the validated v0.6.0 release descriptor on `pyble.dev`, so the
  home, flash, and support surfaces derive their current five-profile status
  from the selected immutable release instead of hard-coded board copy.
- Kept the exact-board Waveshare presentation separate from the lean generic
  S3 profile and retained the real-hardware image on the flash page.
- Published the firmware release notes, checksums, recovery instructions,
  license inventory, and exact profile artifacts under `/firmware/v0.6.0/`.

## Firmware 0.6.0 — 2026-08-21

_Firmware release only. At release qualification, the independently versioned
app source was `0.1.0+2`; later app-source work does not alter firmware
v0.6.0._

- Published and deployed the qualified five-profile release at
  [pyble.dev/flash](https://pyble.dev/flash): `esp32-4mb`,
  `esp32-s3-n16r8`, `waveshare-esp32-s3-lcd-147b`, `esp32-c3-4mb`, and
  `rpi-pico2-w`.
- Completed the exact-byte qualification matrix: all five HIL rows passed,
  including install and recovery, PBLE/1 workflows, run/stop and console
  behavior, filesystem reliability, fixed resource and timing limits, and app
  operation on iPadOS and Android.
- Provisioned the four ESP profiles through ESP Web Serial. Pico 2 W uses a
  verified UF2 download followed by a manual BOOTSEL copy; it is not a Web
  Serial target.
- Added qualified ESP32-C3 revision v0.3-or-newer support for the exact 4 MiB
  profile and qualified Raspberry Pi Pico 2 W support through the portable
  frozen-Python RP2 agent.
- Kept `esp32-s3-n16r8` lean and board-neutral while giving the exact
  Waveshare B-version profile its ST7789 runtime and fresh-install splash with
  persistent disable.
- Hardened response delivery, VM and run lifecycle, STOP and soft-reboot
  ordering, filesystem concurrency, and console flow across the ESP and RP2
  ports.
- Bound the immutable release to annotated tag `firmware-v0.6.0`, PyBLE source
  `0c7230d6708797c241160ba71fbd37e6b22f180a`, MicroPython v1.28.0 and
  ESP-IDF v5.5.1, agent `0.6.0`, protocol `PBLE/1`, and zero upstream patches.
- Published schema-4 metadata with SHA-256
  `c2940281a14feddb55c48de15ac18087e9317d1b7130e514fab5a209b046a1e6`
  and independently hashed artifacts, notices, release notes, and recovery
  instructions.
- Admitted the characterized Waveshare single-page largest-block transient
  with the fixed `98304` heap floor defined by ADR-0039; firmware bytes stayed
  unchanged while the final qualification policy was corrected.

## Firmware 0.5.1 — 2026-08-03

- Published the qualified three-profile release for `esp32-4mb`, the lean
  `esp32-s3-n16r8`, and the separate exact-board
  `waveshare-esp32-s3-lcd-147b` profile.
- Made the Waveshare PyBLE splash the fresh-install default while preserving a
  stored opt-out; kept its ST7789 runtime and board pin map out of the generic
  S3 image.
- Bound the release to annotated tag `firmware-v0.5.1`, source
  `bab472131f0a71c5c4a7efc689eab266189a1896`, MicroPython v1.28.0, and
  ESP-IDF v5.5.1. ESP32-C3 and Pico 2 W were not included in this release.

## Firmware 0.5.0 — 2026-08-03

- Published the first qualified three-profile bundle, adding the exact
  Waveshare ESP32-S3-LCD-1.47B B-version profile alongside the two generic ESP
  profiles.
- Added its isolated ST7789 MicroPython runtime and opt-in splash without
  adding board-specific display code to `esp32-s3-n16r8`.
- Bound the release to annotated tag `firmware-v0.5.0` and source
  `4ac661e610a00207246bc9e9863d96085e77854f`.

## Firmware 0.4.2 — 2026-07-31

- Published the exact hardware-tested beta for `esp32-4mb` and
  `esp32-s3-n16r8`; ESP32-C3 remains unavailable.
- Validated production Chrome installation, deliberate interruption,
  interrupted-flash recovery, and reset on real hardware for both exact
  profiles.
- Bound the public release to its annotated source tag, immutable metadata,
  binary hashes, and post-release production-browser attestation.
- The complete release qualification remains pending across the app, PBLE/1,
  resource, and remaining firmware matrices.

## App 0.1.0-beta — 2026-07-30

- Opened the iPad app for external testing through TestFlight.
- Added BLE discovery, PBLE/1 connection, code editing, run/stop, live console,
  and wireless file management.
- Added the offline Blockly workspace, beginner examples, GPIO and NeoPixel
  blocks, exact sidecar reopening, and bounded Python-to-block conversion.
- Added adaptive portrait and landscape layouts, About and license surfaces,
  and the production launcher icon.

## Firmware 0.4.1 — 2026-07-30

- Qualified browser-installable images for `esp32-4mb` and
  `esp32-s3-n16r8`.
- Added the native PBLE/1 BLE agent, filesystem bridge, run/stop engine,
  console streaming, transfer recovery, device identity, and standard
  MicroPython NeoPixel support.
- Added release-integrity, license, qualification, and browser-installer
  validation gates.

The pre-publication development history is intentionally archived outside this
repository. Public development starts from the audited source snapshot.
Firmware 0.4.1 therefore remains a legacy pre-publication release: its source
is present here, but its original commit identifier is not part of the public
history. Later firmware entries identify the annotated public source tag and
exact commit used for their immutable artifacts.

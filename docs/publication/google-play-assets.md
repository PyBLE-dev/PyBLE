<!-- SPDX-License-Identifier: MIT -->
<!-- Part of PyBLE (https://pyble.dev) — see /LICENSE. -->

# Google Play graphics and screenshot package

Prepared for the English open-testing listing on 2026-09-10. The submission
instructions and store copy are in
[google-play-open-testing.md](google-play-open-testing.md).

## Upload requirements checked on 2026-09-10

| Asset | Format and dimensions |
| --- | --- |
| App icon | 512 × 512, 32-bit PNG, at most 1024 KB |
| Feature graphic | 1024 × 500, JPEG or 24-bit PNG without alpha |
| Screenshots | At least two across device types; up to eight per type; JPEG or 24-bit PNG without alpha; 320–3840 px; longest side at most twice the shortest |

Google recommends four app screenshots at 1080 px or higher in 16:9 landscape
or 9:16 portrait for screenshot-based promotion. Its large-screen guidance
also calls for four screenshots and those aspect ratios. Provide accurate
device-specific captures and concise alt text. These are separate from the
basic screenshot upload limits. See the official
[preview asset requirements](https://support.google.com/googleplay/android-developer/answer/9866151?hl=en).

## Artwork

The canonical icon is
[`app/assets/branding/pyble-google-play-512.png`](../../app/assets/branding/pyble-google-play-512.png).
The package copies it without changes. It is derived from the project's MIT
Prompt Chip SVG; see the
[branding provenance](../../app/assets/branding/README.md).

The feature graphic is authored as
[`pyble-google-play-feature.svg`](../../tools/publication/pyble-google-play-feature.svg)
and exported as `pyble-feature-1024x500.png`. The text is:

> PyBLE
>
> MicroPython. Over Bluetooth.
>
> Build ideas on a compatible board.
>
> Editor · Blocks · Console · Files

This is a fresh editorial vector composition using the canonical PyBLE mark,
navy/blue palette, and a simple code/wireless illustration. It is not an app
screenshot. It includes no stock artwork, generated raster artwork, third-party
logos, store badges, or iPad imagery. Text uses the installed Helvetica Neue
and Menlo system fonts during raster export; no font files are redistributed.

| Asset | Alt text |
| --- | --- |
| Icon | PyBLE blue microcontroller with a white terminal prompt on a navy background. |
| Feature graphic | PyBLE: MicroPython over Bluetooth, with a code prompt and wireless signal illustration. |

## Reproducible local package

The completed package contains twelve upload PNGs, plus the asset manifest
and SHA-256 list, in the ignored workspace:

```text
local/publication/google-play/open-testing-2026-09-10/store-assets/
  pyble-icon-512.png
  pyble-feature-1024x500.png
  phone/                 # 3 current signed-build captures
  tablet-7-inch/         # 3 current signed-build captures
  tablet-10-inch/        # 4 reviewed physical-device feature captures
  asset-manifest.json
  SHA256SUMS
```

To export the icon and feature graphic alone:

```sh
python3 tools/publication/prepare_google_play_assets.py \
  --output-dir local/publication/google-play/open-testing-2026-09-10/artwork-new
```

The script requires Python 3.9+, Inkscape, and ImageMagick. It refuses to
overwrite an existing output directory. It writes an `asset-manifest.json`
with dimensions, SHA-256 hashes, source provenance, and alt text, plus
`SHA256SUMS`. The PNG outputs have the required color formats; the feature
graphic has no alpha channel.

For a screenshot set, pass `--capture-manifest` with a local JSON file whose
`environment` records app/package/build/device/source provenance and whose
`screenshots` contains `source`, `device_type`, `order`, `key`, and `alt_text`
for every capture. Source paths are relative to the manifest. Device types are
`phone`, `tablet-7-inch`, and `tablet-10-inch`. An optional `crop` records exact
`x`, `y`, `width`, and `height` to remove OS bars. The script checks dimensions,
strips metadata, converts to 24-bit PNG, and requires zero changed pixels
against every source or exact crop. It does not resize, annotate, or retouch
app content.

To reproduce the complete package, retaining the existing reviewed output:

```sh
python3 tools/publication/prepare_google_play_assets.py \
  --output-dir local/publication/google-play/open-testing-2026-09-10/store-assets-new \
  --capture-manifest local/publication/google-play/open-testing-2026-09-10/capture-manifest.json
```

## Physical tablet captures

The four reviewed captures below come from a physical Lenovo TB-J616X running
Android 12, PyBLE 0.2.0 build 5, on 2026-08-28. The installed capture package was
`dev.pyble.pyble.tutorialcapture`, built from
`4df378fc76c919f0e2481eb5b668f14115d38587`. These are real board sessions, with
the displayed PyBLE agent version 0.6.0. The capture build is not a Play binary.

These four app surfaces remain representative of the current source: the only
`app/lib/` change between that capture revision and preparation baseline
`ebbb427a17aacf58bdd7ea150520e63a6fb48acd` is a documentation-only change to
`pble/hello.dart`. The open-testing preparation adds an About privacy action
and policy page; it does not change the four depicted surfaces. Preserve this
provenance instead of relabeling these as newly captured build-8 images.

The source provenance contains original raw hashes, crop geometry, and device
and board session details:
[five-board screenshot record](../testing/tutorial-five-board-screenshot-provenance-2026-08-28.md).
Each reviewed frame is the original 2000 × 1092 app region, with only Android
system bars removed by the earlier reviewed crop. Those dimensions satisfy
the basic upload limits, but do not have the preferred 16:9 promotional ratio.
Retain the honest geometry; a future physical capture at 16:9 can replace it.

Upload these under **10-inch tablet screenshots**, in this order:

| Order / output filename | Source under `tools/web/public/learn/app/` | Alt text |
| --- | --- | --- |
| `01-editor-console.png` | `pyble-app-0.2.0-build-5-first-program-editor-console-f6928eea293b.png` | MicroPython editor, board files and Console showing Hello from PyBLE on a connected board. |
| `02-blocks-python.png` | `pyble-app-0.2.0-build-5-blocks-hello-workspace-adc069d73fba.png` | Blocks workspace with a Hello, PyBLE print block and the generated Python shown alongside it. |
| `03-board-discovery.png` | `pyble-app-0.2.0-build-5-setup-five-board-scan-a89dedab7efc.png` | Bluetooth discovery lists five nearby PyBLE boards with signal strength and a Scan again control. |
| `04-example-import.png` | `pyble-app-0.2.0-build-5-examples-import-complete-65fc3f839336.png` | A public Python example has downloaded to the board; the app confirms it was not opened or run automatically. |

The images were visually reviewed again for this package. They show only public
tutorial content, intentional documentation-board identifiers, and expected
app state. No account, private repository, token, notification, personal file,
debug badge, or device overlay appears in the selected app regions.

There is no video, Chromebook, TV, Wear OS, car, or XR asset in this package.
Do not duplicate tablet images into phone slots or describe
the existing iPad website hero as an Android capture.

## Current phone and 7-inch tablet captures

The production app shows its connection screen until a real compatible board
is ready; the IDE cannot be reached without that connection. Emulator captures
must preserve this actual state. The local Android emulator can supply current
connection/About images, but cannot supply genuine connected board, Python
execution, or file-transfer evidence.

The completed local manifest records exact capture builds, display geometry,
density, and screenshot filenames. Use its `phone/` output directory for the
phone slot and `tablet-7-inch/` for the 7-inch slot. Emulator screenshots
supplement the physical tablet feature images; they do not replace hardware
validation for the release candidate.

The six current screenshots were captured on 2026-09-10 from the signed
production APK, `dev.pyble.pyble`, version **0.2.0 (8)**:

- Source commit: `768fafe45beee7731d1a38480cc0463a2f5680cd`.
- App tree: `27fd1a264a576e68126c38f966db328559660249`.
- APK SHA-256: `3c98983a995c657f10a398d7b0f65a07c2d2af18e07c30e7d5dfc094eefcbdcf`.
- OS: Android 14 / API 34, using the installed Google APIs ARM64 system image.
- Phone: isolated phone AVD based on the Pixel 3a profile, 420 dpi, raw runtime
  display 1080 × 2046. The exact `1080x1920+0+63` crop removes 63-pixel status
  and navigation bars and retains the complete app region.
- 7-inch tablet: isolated Nexus 7 2013 AVD, 320 dpi, native 1200 × 1920,
  captured in landscape at 1920 × 1200. The exact `1920x1032+0+48` crop removes
  the 48-pixel status bar and 120-pixel Android taskbar. This preserves the
  entire app region and excludes other apps' taskbar icons.
- Default font scale 1.0, real disconnected app state, no account or board.
  No source code, providers, or connection results were changed for capture.

The phone PNGs are 1080 × 1920. The 7-inch PNGs are 1920 × 1032 and meet the
basic screenshot limits; they do not meet the preferred 1080-pixel minimum
short edge and 16:9 ratio for large-screen promotion. Neither the three-image
phone set nor the three-image 7-inch set claims the four-image promotional gate.

For **each** of the phone and 7-inch slots, upload in this order:

| Filename | Alt text |
| --- | --- |
| `01-setup.png` | PyBLE connection screen explains that a compatible board running the PyBLE agent is needed to edit and run MicroPython. |
| `02-about.png` | About PyBLE shows version 0.2.0 (8) and describes the open-source MicroPython IDE. |
| `03-privacy.png` | The in-app PyBLE Privacy Policy explains local work, project ownership and the optional public GitHub import. |

The APK installed and launched successfully on both configurations. The native
flow **Setup → About → Privacy policy → Android Back → About → Android Back →
Setup** passed on both, with visible titles verified in UI hierarchy captures.
The About page displayed the correct version and build. Visual review found no
clipped labels, debug badge, app crash, private content, or unrelated device
overlay in the exported app regions. Raw images and UI evidence remain under
`local/publication/google-play/open-testing-2026-09-10/raw/`; the result is
recorded in `native-ui-smoke.json` beside `capture-manifest.json`.

All ten screenshot exports passed exact pixel comparisons after the documented
system-bar crops and RGB conversion. These checks establish capture integrity
and native UI navigation; they do not establish BLE behavior on physical
hardware. The isolated emulator instances were stopped after capture without
saving snapshots; the user's original AVD configurations were not edited.

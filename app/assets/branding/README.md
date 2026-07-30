<!-- SPDX-License-Identifier: MIT -->
<!-- Part of PyBLE (https://pyble.dev) — see /LICENSE. -->

# PyBLE branding

`pyble-prompt-chip.svg` is the canonical, grid-defined source of truth for the
PyBLE launcher icon. `pyble-prompt-chip-master.png` and every platform image
are derived assets; do not edit them independently.

## Prompt Chip concept

- Flat deep-navy background (`#081B35`), electric-blue chip (`#2F8CFF`), and
  near-white terminal prompt (`#F4F7FF`).
- A rounded microcontroller frame, six restrained pins, and one radio arc
  communicate code running over a wireless board connection.
- The large terminal prompt (`>`) communicates Python without embedding a
  wordmark or third-party figure mark.
- The mark occupies Android's guaranteed 66×66 dp adaptive-icon core and stays
  legible at 20 px.
- No status light is baked into the identity; connection state belongs in the
  live app UI.
- No Bluetooth figure mark, Python logo, wordmark, or other third-party mark.
- No generated lighting, gradient, shadow, texture, or pre-rounded mask.

The user-provided `ScreenShots/logo_1.png` and `logo_2.png` established the
microcontroller, navy/cyan, and wireless composition. OpenAI's built-in
image-generation tool was used on 2026-07-29 to explore a simplified synthesis.
Actual-size comparison selected the Prompt Chip; its production geometry was
then rebuilt as the clean MIT SVG in this directory. The two reference PNGs are
design inputs, not platform assets.

## Derived assets

- iOS/iPadOS: one 1024 px default icon plus dark and grayscale-tinted
  appearances; legacy sizes remain reproducible for direct QA.
- Android: legacy density PNGs plus adaptive background/foreground and
  monochrome vector layers.
- Google Play: `pyble-google-play-512.png` (512 px RGBA).

Regenerate every derived image from the repo root:

```sh
bash tools/generate_app_icons.sh
cd app
flutter test test/unit/app_identity_manifest_test.dart
```

The generator requires Inkscape and ImageMagick. Release validation also builds
both the IPA and APK so Xcode's asset compiler and Android's resource compiler
verify the platform manifests.

<!-- SPDX-License-Identifier: MIT -->

# Tutorial five-board screenshot provenance — 2026-08-28

This record covers the Lenovo-only, five-board app captures prepared for local
review of the ten-part learning path. Technical integrity and privacy review
are complete. Final content approval and production publication remain
separate actions.

## Capture environment

- Capture date: `2026-08-28` (`Asia/Bangkok`; the UTC date was also
  `2026-08-28`)
- Physical capture device: `Lenovo TB-J616X`
- ADB serial and transport: `HA1HM0X8` over USB; wireless debugging was not
  enabled
- Operating system: `Android 12 (API 31)`
- App surface: `PyBLE 0.2.0 beta`, build `5`
- Capture-only package: `dev.pyble.pyble.tutorialcapture`
- App source revision:
  `4df378fc76c919f0e2481eb5b668f14115d38587`
- Capture APK SHA-256:
  `ad0a15a5f7f80005aac86f422ac53b888162fbca2b96920f4eacf1f1819fc679`
- PyBLE agent version on every connected board: `0.6.0`
- Raw directory (ignored):
  `ScreenShots/tutorials/android/lenovo-tb-j616x/0.2.0-beta/five-boards/`
- Reviewed directory (ignored):
  `ScreenShots/tutorials/android/lenovo-tb-j616x/0.2.0-beta/five-boards/reviewed-tutorial-set/`
- Processor: `ImageMagick 7.1.2-21 Q16-HDRI aarch64`

The release-mode capture package used a disposable local signing key and a
capture-only application ID so it could coexist with another installed build.
It is not a distributable release artifact. The key and generated build output
remain outside Git.

No iPad was used in this capture workflow. App installation, interaction, and
ADB capture targeted only the Lenovo tablet. The laptop-side processing and
review used only Lenovo raw inputs; no iPad capture entered the set. The Lenovo
stylus overlay was stopped before every selected raw frame. No selected
derivative contains the stylus affordance.

## Five-board session map and evidence boundary

The stopped discovery frame records exactly five distinct advertisements and
`Scan: Idle`. An advertisement proves only that a nearby PBLE agent advertised;
it does not prove installed firmware-profile bytes. Each connection frame
records a Ready status with board ID and agent version plus a read-only runtime
token.

| Advertisement / board ID | Maintained physical-session context | Captured state | Captured runtime token | Evidence boundary |
| --- | --- | --- | --- | --- |
| `PyBLE-5646` / `5646` | Generic ESP32-S3 N16R8, explicitly confirmed by the user | `Ready` / agent `0.6.0` | `esp32-s3` | The user-supplied physical context identifies this board; the runtime token alone is not generic-profile proof. |
| `PyBLE-8C9E` / `8C9E` | Generic/classic ESP32 session | `Ready` / agent `0.6.0` | `esp32` | The app does not prove flash capacity, carrier, pin map, or installed profile bytes. |
| `PyBLE-C81A` / `C81A` | Generic ESP32-C3 session | `Ready` / agent `0.6.0` | `esp32-c3` | The app does not prove flash capacity, carrier, pin map, or installed profile bytes. |
| `PyBLE-DA86` / `DA86` | Waveshare ESP32-S3-LCD-1.47B physical-session context | `Ready` / agent `0.6.0` | `esp32-s3` | The maintained physical-session context identifies the exact board; the runtime token alone does not prove the carrier or Waveshare profile. |
| `PyBLE-3DCB` / `3DCB` | Raspberry Pi Pico 2 W physical-session context | `Ready` / agent `0.6.0` | `rpi-pico2-w` | Exact-board/profile evidence remains the physical marking and installer record, not the token alone. |

The `5646` and `DA86` runtime derivatives intentionally have identical pixels
and the same SHA-256. That is expected evidence: both sessions report only
`esp32-s3` at this layer, so the app cannot distinguish their provisioning
profiles. The paired Ready and runtime derivatives are composed by semantic
HTML/CSS; no raster collage was produced.

These observations are tutorial-documentation evidence only. They are not
PBLE conformance, firmware release qualification, installed-byte proof, or
GPIO, display, wiring, electrical, or other hardware-in-the-loop evidence. No
GPIO or display behavior was exercised or qualified during this capture pass.

## Deterministic processing

[`process-tutorial-captures.sh`](../../tools/web/scripts/process-tutorial-captures.sh)
validated all 13 distinct raw images as one 2000×1200, 8-bit PNG each and
produced 18 derivatives:

| Derivative class | Distinct raw frames | Derivatives | Exact crop |
| --- | ---: | ---: | --- |
| Full app frame | 8 | 8 | `2000x1092+0+36` |
| Connected Ready status | 5 | 5 | `400x84+0+36` |
| Connected read-only runtime panel | Same 5 connected frames | 5 | `512x390+1488+330` |
| Total | 13 | 18 | Three fixed geometries |

The full-frame crop removes 36 pixels of Android status bar from the top and
72 pixels of Android navigation area from the bottom. The processor crops the
two identity regions independently from each connection raw, strips metadata,
forces 8-bit PNG output, excludes date/time chunks, and uses fixed PNG
compression settings. It does not resize, annotate, blur, recolor, generate,
or retouch app pixels. Every output passed an exact crop comparison with zero
changed pixels.

The review directory contains an 18-row `SHA256SUMS`, a deduplicated 13-row
`SOURCE_SHA256SUMS`, and the 18-row `tutorial-captures.tsv` used for the table
below. Reviewed filenames contain the app version, build, stable key, and first
12 characters of the reviewed digest.

## Interaction, writes, and cleanup

- The five-board scan was allowed to settle, then stopped before capture. It
  showed the five intended advertisements and `Scan: Idle`.
- `5646` was used for read-only identity and GitHub browsing/review frames. No
  GitHub file was downloaded to that board.
- On `8C9E`, `/tutorial-capture/hello.py` was created with 26 bytes and run
  once. The program was a hardware-free Console greeting. Two empty disposable
  files, `/tutorial-capture/delete_me_one.py` and
  `/tutorial-capture/delete_me_two.py`, were then created for the exact
  permanent-delete review. The confirmation shown in the selected frame was
  canceled and both files remained. A second selection of the same exact two
  files was then confirmed; only those two named disposable files were
  deleted. `/tutorial-capture/hello.py` and its folder were retained.
- On `C81A`, `/tutorial-capture` was created and the Hello PyBLE Blocks starter
  was opened in the editable workspace. It was not saved to the board and was
  not run.
- On `DA86`, `/examples` was created and
  `pyble_hello_console.py` was imported from the public examples repository at
  immutable commit `8f4529b3cd0d62e8d53d7deb4f37e5cd2a171fd1`. The imported
  file was not opened or run.
- `3DCB` was used only for read-only connection identity.
- The app was left disconnected after the capture session. No other board file
  was created, overwritten, or deleted as part of the selected workflow.

## Reviewed capture manifest

The raw and reviewed digests below are copied from the generated
`tutorial-captures.tsv` without abbreviation.

| Stable capture key | Crop | Raw filename | Raw SHA-256 | Reviewed filename | Reviewed SHA-256 |
| --- | --- | --- | --- | --- | --- |
| `setup-five-board-scan` | Full | `07-five-board-scan-stopped.raw.png` | `1d4fbf31f94f80d4d241b321137f316a42dc4770bd62985ec18f4d0b042fc71f` | `pyble-app-0.2.0-build-5-setup-five-board-scan-a89dedab7efc.png` | `a89dedab7efc472332e4280ba145400edf0be2cf2f68acb50d26dca1d2023bcf` |
| `identity-5646-ready` | Ready | `02-connected-5646.raw.png` | `66e63f77decae9a3654a0319b9c194db27c503be43fecbe33c2884fdf12c450e` | `pyble-app-0.2.0-build-5-identity-5646-ready-6b8ef886ea40.png` | `6b8ef886ea4039288e7af1c18921ac41b1b22a10f336a59f96cbf28a74cdb4d2` |
| `identity-5646-chip` | Runtime | `02-connected-5646.raw.png` | `66e63f77decae9a3654a0319b9c194db27c503be43fecbe33c2884fdf12c450e` | `pyble-app-0.2.0-build-5-identity-5646-chip-03edb94bcf73.png` | `03edb94bcf730b72028952962893a3ac26959a3d7c4bf948fbc252757a86e452` |
| `identity-8c9e-ready` | Ready | `03-connected-8c9e.raw.png` | `0af4ea76d1b8af6b920f213ae58d28e1b14bfac2176611927a9d2abad77cbdbc` | `pyble-app-0.2.0-build-5-identity-8c9e-ready-3b64e4b0b84c.png` | `3b64e4b0b84c2d1a81c32b190bfc45d0f294758998bdef1d3c1776d0a1879045` |
| `identity-8c9e-chip` | Runtime | `03-connected-8c9e.raw.png` | `0af4ea76d1b8af6b920f213ae58d28e1b14bfac2176611927a9d2abad77cbdbc` | `pyble-app-0.2.0-build-5-identity-8c9e-chip-0aa751bf86a3.png` | `0aa751bf86a3e7f247a731ecc9ac65b7b2fcb61188201e79c327ba0ca561a3a8` |
| `identity-c81a-ready` | Ready | `04-connected-c81a.raw.png` | `039c2c95dc2cba2a6d6c2848ab6dbf29a782cc519003da54e2561035a19bce01` | `pyble-app-0.2.0-build-5-identity-c81a-ready-8dea0554c432.png` | `8dea0554c432558f5f411a67a2175a5ff762e96c055fd9117ee3fb97906a1fd1` |
| `identity-c81a-chip` | Runtime | `04-connected-c81a.raw.png` | `039c2c95dc2cba2a6d6c2848ab6dbf29a782cc519003da54e2561035a19bce01` | `pyble-app-0.2.0-build-5-identity-c81a-chip-1c4d40085693.png` | `1c4d400856933184a8d37548240469c46850cafc9a76207f17d7b4f9b424c468` |
| `identity-da86-ready` | Ready | `05-connected-da86.raw.png` | `1a086f30edff93085e82326e1605424ab77c2ece69068b8b5f078f01efdcee58` | `pyble-app-0.2.0-build-5-identity-da86-ready-49595991ba1f.png` | `49595991ba1f422ca8e840594b198953d00e3938c1d13d6c9c5e2586d50a0972` |
| `identity-da86-chip` | Runtime | `05-connected-da86.raw.png` | `1a086f30edff93085e82326e1605424ab77c2ece69068b8b5f078f01efdcee58` | `pyble-app-0.2.0-build-5-identity-da86-chip-03edb94bcf73.png` | `03edb94bcf730b72028952962893a3ac26959a3d7c4bf948fbc252757a86e452` |
| `identity-3dcb-ready` | Ready | `06-connected-3dcb.raw.png` | `6e37f11806fc65798670e30c5f49b11d181bb41c7389cc20848384252e8407bf` | `pyble-app-0.2.0-build-5-identity-3dcb-ready-613559d187f3.png` | `613559d187f330e7c7ba3375f86123dbfc4a7ea51b7cb703d34659d9972463e2` |
| `identity-3dcb-chip` | Runtime | `06-connected-3dcb.raw.png` | `6e37f11806fc65798670e30c5f49b11d181bb41c7389cc20848384252e8407bf` | `pyble-app-0.2.0-build-5-identity-3dcb-chip-2b80ef41db8f.png` | `2b80ef41db8f86d5d0d1b79aebf97041fffbba2178817a2a4598ed038c717d96` |
| `first-program-editor-console` | Full | `08-first-program-classic-esp32.raw.png` | `c1e1eb4e6e09605c21e2c79088da290027f8c1ed60cdcf3cd37533d49b872e9c` | `pyble-app-0.2.0-build-5-first-program-editor-console-f6928eea293b.png` | `f6928eea293bd20bcddab94e3e56034033b74a6470cab0f9b018b6a31b969203` |
| `files-multi-delete-review` | Full | `17-files-multi-delete-classic-esp32-idle.raw.png` | `ed3841d421be85009e1019221170d43d6d9e8af61e129d4093d7101a0aa96471` | `pyble-app-0.2.0-build-5-files-multi-delete-review-42cfacddd965.png` | `42cfacddd9657146ba0edfb20273e87e56b5cf8ed9d646c6fd5878f77a728e31` |
| `github-branch-chooser` | Full | `16-github-branch-chooser-generic-s3-clean.raw.png` | `08fbe3108985dc8045d2212c1f6e84ac742bd0709504731979ad809679fb745a` | `pyble-app-0.2.0-build-5-github-branch-chooser-f0c52c24bc5b.png` | `f0c52c24bc5be7412d5e62e2cdbd2708037ed538949c543d121d31aaae5810d7` |
| `github-pinned-source` | Full | `12-github-pinned-source-generic-s3.raw.png` | `a282823b7f1c71d74c6e28b3dc82f9af435c82747ea3fc595769d1179bef3a81` | `pyble-app-0.2.0-build-5-github-pinned-source-68a784c12ada.png` | `68a784c12ada7ae3690e7268cf8b724268ecd81e024c0d92e20ad7870329e372` |
| `github-target-review` | Full | `11-github-target-review-generic-s3.raw.png` | `e13344241f035e46c760abd1ea587d9c70d1e52b218aa6a2ec3c74ed6768c620` | `pyble-app-0.2.0-build-5-github-target-review-16aafa28be77.png` | `16aafa28be77af34696eb61882610a02aa3f8943f5c130de40801b8112b26118` |
| `examples-import-complete` | Full | `14-examples-import-waveshare.raw.png` | `77fa143b86b5267b5c4ccf1e3b101910348279358156b9a0b499fc5628d208dd` | `pyble-app-0.2.0-build-5-examples-import-complete-65fc3f839336.png` | `65fc3f8393366948ee56d183b5ecfdbaf5550a6339e6519c31d0bb6d0ebc8b32` |
| `blocks-hello-workspace` | Full | `13-blocks-hello-c3-idle.raw.png` | `f85a8b92bb5b2567509450b3d7fbeb9ac61935fce27341fe015d11f9e1d17a8a` | `pyble-app-0.2.0-build-5-blocks-hello-workspace-adc069d73fba.png` | `adc069d73fbaab648f2e6b55dc536b38dade609c31aa03f18eb528a634a02f76` |

Technical and privacy review found no account, token, private repository,
notification, personal filename, debug label, integration-test label, or
unrelated board file in the selected derivatives. The public board IDs,
official examples URL, immutable public commit, tutorial source, and named
disposable tutorial files are intentional instructional evidence.

<!-- SPDX-License-Identifier: MIT -->

# Tutorial five-board screenshot provenance — TEMPLATE

Copy this template into the release review record. Raw captures and generated
review candidates remain below the repository's ignored `ScreenShots/`
workspace. Only an explicitly reviewed, provenance-recorded derivative may be
promoted to `tools/web/public/`.

## Capture environment

- Capture date and time zone: `YYYY-MM-DD — TIME_ZONE`
- Technical/privacy reviewer and date: `NAME — YYYY-MM-DD`
- Final content reviewer and date: `NAME — YYYY-MM-DD` or `pending`
- Physical capture device: `Lenovo TB-J616X`
- Android release / API level: `Android 12 / API 31`
- ADB transport and serial: `USB — SERIAL`
- PyBLE version and build: `VERSION (BUILD)`
- Installed package identity: `PACKAGE`
- APK source commit and SHA-256: `COMMIT — SHA256`
- PyBLE agent version: `VERSION`
- Raw directory (ignored): `ScreenShots/.../five-boards/`
- Review directory (ignored):
  `ScreenShots/.../five-boards/reviewed-tutorial-set/`
- ImageMagick version: output of `magick -version`
- Tablet-use boundary: `Confirm that only the Lenovo was used; no iPad use`
- Stylus-overlay state: `Confirm stopped before every selected raw frame`

## Five-board observation map

Record the app observation separately from the physical-board or installer
record. A Ready identity and runtime token do not prove installed profile
bytes, flash capacity, carrier wiring, or release qualification.

| Advertisement / board ID | Maintained physical-session context | Ready / agent | Observed runtime token | Evidence source and limitation reviewed |
| --- | --- | --- | --- | --- |
| `PyBLE-5646` / `5646` | Generic ESP32-S3 N16R8 | `Ready` / `VERSION` | `esp32-s3` | `yes/no` |
| `PyBLE-8C9E` / `8C9E` | Generic ESP32 | `Ready` / `VERSION` | `esp32` | `yes/no` |
| `PyBLE-C81A` / `C81A` | Generic ESP32-C3 | `Ready` / `VERSION` | `esp32-c3` | `yes/no` |
| `PyBLE-DA86` / `DA86` | Waveshare ESP32-S3-LCD-1.47B | `Ready` / `VERSION` | `esp32-s3` | `yes/no` |
| `PyBLE-3DCB` / `3DCB` | Raspberry Pi Pico 2 W | `Ready` / `VERSION` | `rpi-pico2-w` | `yes/no` |

Document who supplied each physical-session context. In particular, record
the user's confirmation that `5646` is the generic ESP32-S3 N16R8. Keep the
`5646` and `DA86` runtime-token evidence visibly equivalent: their shared
`esp32-s3` token cannot distinguish the generic and Waveshare profiles.

## Deterministic processing

Run from the repository root, using explicit absolute paths:

```sh
tools/web/scripts/process-tutorial-captures.sh \
  --input-dir /ABSOLUTE/PATH/TO/RAW-CAPTURES \
  --output-dir /ABSOLUTE/PATH/TO/RAW-CAPTURES/reviewed-tutorial-set
```

The processor accepts exactly 13 distinct named 2000×1200, 8-bit PNG inputs
and produces exactly 18 derivatives:

| Derivative class | Distinct raw frames | Derivatives | Exact crop |
| --- | ---: | ---: | --- |
| Full app frame | 8 | 8 | `2000x1092+0+36` |
| Connected Ready status | 5 | 5 | `400x84+0+36` |
| Connected read-only runtime panel | Same 5 connected frames | 5 | `512x390+1488+330` |
| Total | 13 | 18 | Three fixed geometries |

The full-frame crop removes 36 pixels from the top and 72 from the bottom. The
two connected derivatives for each board come from the same raw frame and may
be paired only with semantic HTML/CSS, never as a baked, annotated raster
collage. The processor strips metadata, excludes time-dependent PNG chunks,
and uses fixed PNG compression settings. It does not resize, annotate, blur,
recolor, generate, or retouch app pixels. It compares each derivative against
the exact source crop with a zero-pixel-difference requirement.

The command writes an 18-row reviewed `SHA256SUMS`, a 13-row deduplicated raw
`SOURCE_SHA256SUMS`, and `tutorial-captures.tsv`, which maps each stable key to
its raw file, content-versioned reviewed filename, and both full SHA-256
values. Reviewed filenames include the PyBLE app version, build, and first 12
hash characters.

Use `--force` only after reviewing the current directory. It replaces only a
directory containing the processor's managed filenames; any unmanaged entry
causes a safe failure. Publication remains a separate, deliberate action.
Preserve older review directories as historical local evidence.

Verify the processor contract itself with:

```sh
tools/web/scripts/test-process-tutorial-captures.sh
```

Verify an actual local set from its raw directory with:

```sh
capture_root=/ABSOLUTE/PATH/TO/RAW-CAPTURES
review_dir="$capture_root/reviewed-tutorial-set"
(cd "$review_dir" && shasum -a 256 -c SHA256SUMS)
(cd "$capture_root" && \
  shasum -a 256 -c "$review_dir/SOURCE_SHA256SUMS")
test "$(wc -l < "$review_dir/SHA256SUMS" | tr -d ' ')" -eq 18
test "$(wc -l < "$review_dir/SOURCE_SHA256SUMS" | tr -d ' ')" -eq 13
```

## Per-image review

Fill the reviewed filename and full raw/reviewed digests from
`tutorial-captures.tsv`. Review each derivative at its native dimensions.

| Stable capture key | Raw filename | Crop | Reviewed filename | Raw SHA-256 | Reviewed SHA-256 | State/privacy review | Approved |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `setup-five-board-scan` | `07-five-board-scan-stopped.raw.png` | Full frame | from manifest | `...` | `...` | `pass/fail` | `yes/no` |
| `identity-5646-ready` | `02-connected-5646.raw.png` | Ready | from manifest | `...` | `...` | `pass/fail` | `yes/no` |
| `identity-5646-chip` | `02-connected-5646.raw.png` | Runtime | from manifest | `...` | `...` | `pass/fail` | `yes/no` |
| `identity-8c9e-ready` | `03-connected-8c9e.raw.png` | Ready | from manifest | `...` | `...` | `pass/fail` | `yes/no` |
| `identity-8c9e-chip` | `03-connected-8c9e.raw.png` | Runtime | from manifest | `...` | `...` | `pass/fail` | `yes/no` |
| `identity-c81a-ready` | `04-connected-c81a.raw.png` | Ready | from manifest | `...` | `...` | `pass/fail` | `yes/no` |
| `identity-c81a-chip` | `04-connected-c81a.raw.png` | Runtime | from manifest | `...` | `...` | `pass/fail` | `yes/no` |
| `identity-da86-ready` | `05-connected-da86.raw.png` | Ready | from manifest | `...` | `...` | `pass/fail` | `yes/no` |
| `identity-da86-chip` | `05-connected-da86.raw.png` | Runtime | from manifest | `...` | `...` | `pass/fail` | `yes/no` |
| `identity-3dcb-ready` | `06-connected-3dcb.raw.png` | Ready | from manifest | `...` | `...` | `pass/fail` | `yes/no` |
| `identity-3dcb-chip` | `06-connected-3dcb.raw.png` | Runtime | from manifest | `...` | `...` | `pass/fail` | `yes/no` |
| `first-program-editor-console` | `08-first-program-classic-esp32.raw.png` | Full frame | from manifest | `...` | `...` | `pass/fail` | `yes/no` |
| `files-multi-delete-review` | `17-files-multi-delete-classic-esp32-idle.raw.png` | Full frame | from manifest | `...` | `...` | `pass/fail` | `yes/no` |
| `github-branch-chooser` | `16-github-branch-chooser-generic-s3-clean.raw.png` | Full frame | from manifest | `...` | `...` | `pass/fail` | `yes/no` |
| `github-pinned-source` | `12-github-pinned-source-generic-s3.raw.png` | Full frame | from manifest | `...` | `...` | `pass/fail` | `yes/no` |
| `github-target-review` | `11-github-target-review-generic-s3.raw.png` | Full frame | from manifest | `...` | `...` | `pass/fail` | `yes/no` |
| `examples-import-complete` | `14-examples-import-waveshare.raw.png` | Full frame | from manifest | `...` | `...` | `pass/fail` | `yes/no` |
| `blocks-hello-workspace` | `13-blocks-hello-c3-idle.raw.png` | Full frame | from manifest | `...` | `...` | `pass/fail` | `yes/no` |

Confirm that the selected scan is stopped and stable with exactly five
distinct advertisements, the identity crops show the expected Ready/agent and
runtime-token pairs, and each workflow frame shows only its stated action.
Record every board write, Run action, cancellation, cleanup, and retained
disposable artifact. State explicitly that the screenshots are documentation
evidence, not PBLE conformance, release qualification, GPIO, display, wiring,
or other HIL evidence.

Confirm that no selected image contains private notifications, account
details, credentials, personal filenames, private repositories, unpublished
code, debug labels, or integration-test labels. Intentionally documented
public board IDs are allowed. The Lenovo stylus affordance must be stopped
before every selected raw frame; do not remove it or any in-app pixel through
retouching. Confirm that no iPad was used for installation, interaction,
capture, processing, or selection in this set. Captions and alternative text
must describe the exact visible state before promotion.

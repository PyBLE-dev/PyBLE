<!-- SPDX-License-Identifier: MIT -->

# Tutorial screenshot provenance — TEMPLATE

Copy this template into the release review record. Raw captures and generated
review candidates remain below the repository's ignored `ScreenShots/`
workspace. Only an explicitly approved derivative may later be promoted to
`tools/web/public/`.

## Capture set

- Capture date (UTC): `YYYY-MM-DD`
- Reviewer and review date: `NAME — YYYY-MM-DD`
- Physical device: `Lenovo TB-J616X`
- Android release / API level: `Android 12 / API 31`
- PyBLE version and build: `VERSION (BUILD)`
- Installed package identity: `PACKAGE`
- APK source commit and SHA-256: `COMMIT — SHA256`
- Connected board and firmware: `BOARD — VERSION`
- Raw directory (ignored): `ScreenShots/...`
- Review directory (ignored): `ScreenShots/.../reviewed-tutorial-set`
- ImageMagick version: output of `magick -version`

## Deterministic processing

Run from the repository root, using explicit absolute paths:

```sh
tools/web/scripts/process-tutorial-captures.sh \
  --input-dir /ABSOLUTE/PATH/TO/RAW-CAPTURES \
  --output-dir /ABSOLUTE/PATH/TO/RAW-CAPTURES/reviewed-tutorial-set
```

The processor accepts exactly eight named 2000×1200, 8-bit PNG inputs. It
crops 36 pixels from the top and 72 from the bottom, yielding 2000×1092. It
then strips metadata and excludes time-dependent PNG chunks with fixed PNG
compression settings. It does not resize, annotate, blur, recolor, or retouch
app pixels. The command verifies every output against the exact source crop
and writes `SHA256SUMS` plus `SOURCE_SHA256SUMS`. It also writes
`tutorial-captures.tsv`, mapping each stable capture key to its raw file,
content-versioned reviewed filename, and both full SHA-256 values. Reviewed
filenames include the PyBLE app version, build, and first 12 hash characters.

Use `--force` only after reviewing the current directory. It replaces only a
directory containing the processor's managed filenames; any unmanaged entry
causes a safe failure. Publication remains a separate, deliberate action.
Preserve any older `reviewed/` directory as historical local evidence; this
capture set belongs in the distinct `reviewed-tutorial-set/` directory.

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
```

## Per-image review

| Tutorial / purpose | Raw filename | Reviewed filename | Raw SHA-256 | Reviewed SHA-256 | Visual state correct | Privacy review | Approved |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Setup — board discovery | `06-setup-scan-results-production-release.raw.png` | from manifest | `...` | `...` | `yes/no` | `pass/fail` | `yes/no` |
| Setup — connected identity | `07-setup-connected-identity-production-release.raw.png` | from manifest | `...` | `...` | `yes/no` | `pass/fail` | `yes/no` |
| First program — editor and Console | `08-first-program-editor-console-production-release.raw.png` | from manifest | `...` | `...` | `yes/no` | `pass/fail` | `yes/no` |
| Files — multi-delete review | `09-files-multi-delete-review-production-release.raw.png` | from manifest | `...` | `...` | `yes/no` | `pass/fail` | `yes/no` |
| GitHub — branch chooser | `10-github-import-branch-chooser-production-release.raw.png` | from manifest | `...` | `...` | `yes/no` | `pass/fail` | `yes/no` |
| GitHub — pre-write review | `11-github-import-prewrite-review-production-release.raw.png` | from manifest | `...` | `...` | `yes/no` | `pass/fail` | `yes/no` |
| Examples — completed import | `12-examples-import-complete-production-release.raw.png` | from manifest | `...` | `...` | `yes/no` | `pass/fail` | `yes/no` |
| Blocks — generated Python | `20-blocks-hello-workspace-production-release.raw.png` | from manifest | `...` | `...` | `yes/no` | `pass/fail` | `yes/no` |

Review each image at full resolution. Confirm that it contains no private
notifications, account details, credentials, personal filenames, device
identifiers beyond the intentionally documented test device/board, or debug or
integration-test labels. Raw captures 06–12 contain the Lenovo stylus edge
affordance; record it as disclosed, non-private device chrome and preserve it
rather than retouching app pixels. Capture 20 is overlay-free. Confirm that
captions and alt text describe the exact visible state before promotion.

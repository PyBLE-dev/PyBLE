<!-- SPDX-License-Identifier: MIT -->

# Tutorial screenshot provenance — 2026-08-28

> **Superseded and corrected:** use the
> [five-board Lenovo capture record](tutorial-five-board-screenshot-provenance-2026-08-28.md)
> for the current tutorial set. A later audit found the Lenovo stylus
> affordance in seven old raw frames (`06` through `12`), not six. This record
> is retained only as historical evidence for the earlier eight-image set.

This record covers the physical Android captures prepared for local review of
the ten-part learning path. Technical integrity and privacy review are
complete. Production publication remains pending explicit user approval of the
local website.

## Capture environment

- Capture date: `2026-08-28` (`Asia/Bangkok`; the UTC date was also
  `2026-08-28`)
- Physical device: `Lenovo TB-J616X`
- Operating system: `Android 12 (API 31)`
- App surface: `PyBLE 0.2.0 beta`, build `5`
- Capture-only package: `dev.pyble.pyble.tutorialcapture`
- App source revision:
  `4df378fc76c919f0e2481eb5b668f14115d38587`
- Capture APK SHA-256:
  `ad0a15a5f7f80005aac86f422ac53b888162fbca2b96920f4eacf1f1819fc679`
- Documentation board: `PyBLE-5646`, firmware `0.6.0`, runtime chip
  `esp32-s3`
- Raw directory (ignored):
  `ScreenShots/tutorials/android/lenovo-tb-j616x/0.2.0-beta/`
- Reviewed directory (ignored):
  `ScreenShots/tutorials/android/lenovo-tb-j616x/0.2.0-beta/reviewed-tutorial-set/`
- Processor: `ImageMagick 7.1.2-21 Q16-HDRI aarch64`

The release-mode capture package used a disposable local signing key and a
capture-only application ID so it could coexist with the installed Play build.
It is not a distributable release artifact. The key and build output remain
outside Git.

## Processing and interaction boundaries

[`process-tutorial-captures.sh`](../../tools/web/scripts/process-tutorial-captures.sh)
validated each raw image as one 2000×1200 8-bit PNG, cropped exactly
`2000x1092+0+36` to remove the Android status and navigation bars, stripped
metadata, and verified zero changed pixels against that crop. It did not resize,
annotate, blur, recolor, generate, or retouch app content. Reviewed filenames
contain the app version, build, stable capture key, and the first 12 characters
of the reviewed SHA-256.

The two-file deletion confirmation was canceled. The official example was
downloaded from immutable examples commit
`8f4529b3cd0d62e8d53d7deb4f37e5cd2a171fd1` into the disposable
`/examples/tutorial-capture` board folder and was neither opened nor run. The
Blocks starter was copied into the editable workspace but was not run.

## Reviewed captures

| Purpose | Raw capture | Published derivative | Reviewed SHA-256 | Privacy and state review |
| --- | --- | --- | --- | --- |
| Setup — board discovery | `06-setup-scan-results-production-release.raw.png` | `pyble-app-0.2.0-build-5-setup-scan-results-3558cadbe501.png` | `3558cadbe501d1865aafbacf4fe5dd9624ae969a2fb0ff7bbd457029bcf2c41c` | Pass; one documentation-board advertisement; Lenovo stylus edge control retained |
| Setup — connected identity | `07-setup-connected-identity-production-release.raw.png` | `pyble-app-0.2.0-build-5-setup-connected-identity-58f65b64a966.png` | `58f65b64a966d4ef2dcd0148442bf07dbe6b2008eda502f9d1e14cda4b7b36ce` | Pass; documentation board only; Lenovo stylus edge control retained |
| First program — Editor and Console | `08-first-program-editor-console-production-release.raw.png` | `pyble-app-0.2.0-build-5-first-program-editor-console-86552d68afaa.png` | `86552d68afaa7f9ea8b1151e0ffc812685815f3009bb64b7a3c823090ef42152` | Pass; public tutorial source/output only; Lenovo stylus edge control retained |
| Files — multi-delete review | `09-files-multi-delete-review-production-release.raw.png` | `pyble-app-0.2.0-build-5-files-multi-delete-review-b1df22dfa70a.png` | `b1df22dfa70a449356c05f34189ff897decdfbd418bf4630ae251365b6ed6b86` | Pass; disposable filenames; Delete was canceled; Lenovo stylus edge control retained |
| GitHub — branch chooser | `10-github-import-branch-chooser-production-release.raw.png` | `pyble-app-0.2.0-build-5-github-import-branch-chooser-4514d2f0522b.png` | `4514d2f0522bb3600ba38a75d9ed581255877d1949a8c153341af2d720da8ba7` | Pass; official public URL and public branch only; Lenovo stylus edge control retained |
| GitHub — pre-write review | `11-github-import-prewrite-review-production-release.raw.png` | `pyble-app-0.2.0-build-5-github-import-prewrite-review-faa68602fcd0.png` | `faa68602fcd0ef2761573e726c490fcbbfd3d953eecaff60d246511cfa0cb047` | Pass; immutable public source and disposable target; Lenovo stylus edge control retained |
| Examples — completed import | `12-examples-import-complete-production-release.raw.png` | `pyble-app-0.2.0-build-5-examples-import-complete-ab466a044a11.png` | `ab466a044a115a20bef8b1bf355d49867a5a6d439333e51ff3b8deb11d3c9317` | Pass; successful single-file result; no open or Run action; Lenovo stylus edge control retained |
| Blocks — generated Python | `20-blocks-hello-workspace-production-release.raw.png` | `pyble-app-0.2.0-build-5-blocks-hello-workspace-c37bd12f3102.png` | `c37bd12f31021c0a8dfcf1ecd8f592c1d8083c081a5d1d74582dbc8cf9998ee4` | Pass; public starter only; stylus overlay stopped before capture |

No capture contains an account, token, private repository, notification,
personal filename, debug label, integration-test label, or unrelated user board
file. The small edge control retained in seven frames belongs to Lenovo's
`com.lenovo.styluspen` system package; it contains no user data. It was left
truthful rather than removed by image retouching. The overlay was stopped
reversibly before the final Blocks capture. A future physical recapture may
replace those seven frames with new content-versioned assets after the tablet is
reconnected; existing published bytes must never be overwritten in place.

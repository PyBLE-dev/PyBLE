<!-- SPDX-License-Identifier: MIT -->

# PR #32 — CI correction and README refresh

## Observed failure

Both initial CI runs at `a6144f4` failed only the complete firmware host suite:
[pull-request run](https://github.com/PyBLE-dev/PyBLE/actions/runs/34618742875)
and [branch-push run](https://github.com/PyBLE-dev/PyBLE/actions/runs/34618673864).
Each ran 1,947 tests with one error and 24 skips. The failing test was
`test_visible_replacement_during_callback_is_rejected_and_preserved` in
`test_v061_hil_preflight_hardening.py`: its replacement file had disappeared.
The firmware shell phase and Android WebView checks passed. Firmware builds
were skipped because their host-test prerequisite failed; they did not report
compiler failures.

The host evidence writer closed its original descriptor before invoking the
validation callback. Linux could reuse that unlinked file's inode number for a
replacement. Cleanup then mistook the replacement for its own output and
removed it. The same lifetime gap existed in the shared v0.6.0-profile writer.

## Correction and boundaries

Both writers now retain the original descriptor until publication checks and
failure cleanup finish. The inode remains reserved while ownership is checked.
Existing replacement files, including replacements with identical bytes, are
rejected without deletion. Descriptor cleanup still occurs on success/failure.

Specification commit `8c7a1ff`, regression commit `0bde1e6`, and implementation
commit `8771c8b` preserve the specification-first red/green sequence. New tests
observe real descriptor lifetime without relying on filesystem inode-reuse
timing. They failed before the correction on this macOS host as well.

Only host qualification tools changed. Firmware runtime, native modules,
board overlays and version pins still match published source `c8f549e` exactly.
No release threshold was relaxed, failed evidence rewritten, board operated,
firmware rebuilt or live website changed.

## Verification before the update push

- Three deterministic inode-lifetime test methods passed for both writers,
  including success, failure cleanup and same-byte replacement cases.
- The affected five-file writer/gate suite passed all 80 tests under Python
  3.12, including the original failing regression.
- All 42 publication tests and the Markdown link gate passed.
- All six firmware roadmap/ledger tests passed after correcting the old
  expectation that v0.6.0 must still be the current public release.
- Website tests: 342 passed across 23 files.
- Clean-room, whitespace and PR-range DCO checks passed.

The full Python 3.12 host suite is also rerun independently. Its final outcome
and the subsequent Ubuntu CI results belong to the PR checks; focused host
tests above are not hardware qualification evidence.

## README and issue #24

The README now links the published v0.6.1 descriptor, exact source, owner
confirmation, recovery material, tutorials, diagram and official examples.
It documents the editable repository URL, branch selection, writable-folder
guidance, multi-file deletion, App source version and offline privacy policy.
Historical v0.6.0 citation metadata remains historical. Prepared store artifacts
are not advertised as proof of a live release or later source changes.

[Issue #24](https://github.com/PyBLE-dev/PyBLE/issues/24) describes the original
automated release-admission checklist, including five hardening results, ten
storage receipts and ten physical App/profile rows. The
[owner-confirmed publication](firmware-v0.6.1-publication-2026-09-11.md) is recorded,
but its retained descriptor still has five pending automated HIL rows. This PR
does not certify all of #24's original criteria and must not auto-close it as
completed. The maintainer may instead explicitly close that original workflow
as superseded by the owner-confirmed publication decision, preserving the
distinction. This follow-up neither closes the issue nor resumes hardware tests.

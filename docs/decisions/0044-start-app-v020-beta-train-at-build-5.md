# ADR-0044 — Start the app 0.2.0 beta train at build 5

- Status: **Accepted**
- Date: 2026-08-27
- Extends: [ADR-0040](0040-sha-pinned-connected-github-import.md)
- Extends: [ADR-0042](0042-prefill-official-examples-and-discover-branches.md)
- Extends: [ADR-0043](0043-session-bound-visible-file-multi-delete.md)

## Context

The installed app identity remains `0.1.0+4`, but build 4 is a retained
TestFlight handoff bound to an earlier source commit. Since that handoff, the
app source has gained a coherent set of compatible beta features: connected
board identity, the numbered and adjustable rich editor, SHA-pinned GitHub
import, the editable official examples-repository default with branch-only
discovery, session-bound visible-file multi-delete, and a one-row responsive
Files toolbar.

Reinstalling a different source state under the same version and build works
for local development, but it makes About, screenshots, HIL evidence, and
tester reports unable to distinguish the artifacts. A future TestFlight upload
also needs a unique build identity, and the shared Flutter build number becomes
Android's monotonically increasing `versionCode`.

The project reserves app `1.0.0` for its first production release and has not
previously assigned a numbered milestone to the current Unreleased app work.

## Decision

1. **Start a new compatible beta milestone.** The current coherent Unreleased
   feature set becomes the **PyBLE app 0.2.0 beta train**. This changes neither
   the independently versioned firmware agent (`0.6.0`) nor PBLE/1.

2. **Use build 5 for the first candidate.** The first local beta candidate is
   `0.2.0+5`, displayed as `0.2.0 (5)`. Later candidate artifacts increment the
   build number (`+6`, `+7`, …) even when the base version stays `0.2.0`.
   PyBLE does not reset the shared Flutter build sequence when the base version
   changes, preserving one simple iOS/Android ordering rule.

3. **Keep `pubspec.yaml` authoritative.** `app/pubspec.yaml` owns the complete
   base-version/build-number pair. The base version is mirrored at compile time
   by `kAppVersion` for PBLE/1 HELLO because the wire layer must not depend on
   runtime package metadata. The public GitHub request User-Agent derives from
   the same `kAppName` and `kAppVersion` constants instead of carrying another
   independently authored version literal.

4. **Make synchronization executable.** An automated test parses the package
   version, pins the declared 0.2.0 build-5 candidate, and proves its base
   version equals `kAppVersion`. GitHub-client tests require the exact
   `PyBLE/<kAppVersion>` User-Agent. A later version bump must update the
   candidate expectation and cannot silently drift package, HELLO, and HTTP
   identities.

5. **Distinguish a candidate from a qualified release.** A local install or
   TestFlight build carrying `0.2.0 (5)` is a beta candidate, not evidence that
   the app has completed release qualification. Store-signable artifacts,
   platform parity, compatibility declarations, automated gates, and required
   physical validation remain governed by the existing release requirements.

6. **Bind every external handoff to source and evidence.** If build 5 advances
   from local testing to TestFlight or another external handoff, its test plan
   records the exact accepted source commit, qualified agent release, PBLE/1
   baseline, focused test scope, and known boundaries. About must report the
   installed package identity, and physical evidence must name both app
   version/build and board firmware identity.

7. **Preserve historical identities.** The retained `0.1.0 (4)` TestFlight
   plan, prior changelog entries, and the `source-2026.08.23` citation snapshot
   remain unchanged. They describe immutable earlier artifacts rather than the
   moving branch tip.

8. **Keep delivery test-first and local until accepted.** The synchronization
   test lands red before the version implementation. The exact release build is
   installed and physically reviewed on iPad before any pull request or push
   for this combined feature branch.

## Consequences

- Testers can distinguish the new feature set from retained build 4 in About,
  screenshots, diagnostics, and any later TestFlight feedback.
- PBLE/1 sees app version `0.2.0` while remaining protocol-compatible with the
  qualified `0.6.0` agents.
- The official examples repository remains independently versioned and
  untrusted at the importer boundary.
- Future candidate builds pay the small cost of updating one explicit build
  expectation in exchange for deterministic cross-platform traceability.
- `1.0.0` remains unavailable until the production acceptance gates pass.

## Alternatives considered

- **Use `0.1.0+5`.** Valid for another iteration of the same beta milestone,
  but rejected because the accumulated compatible feature set now warrants an
  explicit minor beta milestone.
- **Reset to `0.2.0+1`.** Accepted by iOS for a new base version, but rejected
  because Android requires a greater `versionCode` and PyBLE ships one Flutter
  identity at platform parity.
- **Override only the build command.** Rejected because About could report an
  overridden package version while PBLE/1 HELLO and the GitHub User-Agent still
  advertise stale compile-time values.
- **Jump to `1.0.0`.** Rejected because version 1.0 is the first fully qualified
  production release, not a development or TestFlight milestone.

## Related

- [App build and version requirements](../specifications/App/specs.md#9-build-versioning--distribution--bld)
- [PRD release and versioning](../specifications/prd.md#18-release--versioning)
- [PyBLE 0.1.0 (4) retained TestFlight handoff](../testing/testflight/0.1.0-build-4.md)

<!-- SPDX-License-Identifier: MIT -->

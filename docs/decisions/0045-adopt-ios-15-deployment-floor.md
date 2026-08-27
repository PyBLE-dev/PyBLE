# ADR-0045 — Adopt iOS and iPadOS 15 as the app deployment floor

- Status: **Accepted**
- Date: 2026-08-27
- Extends: [ADR-0044](0044-start-app-v020-beta-train-at-build-5.md)

## Context

The retained PyBLE `0.2.0 (5)` TestFlight artifact was compiled with an
iOS/iPadOS deployment target of `13.0`. Transporter accepted the package far
enough to report advisory `90068`: Apple announced that App Store Connect will
require `MinimumOSVersion` `15.0` or later beginning in Spring 2027.

The existing IPA validator proved signing, entitlements, nested-code safety,
and Xcode software-information integrity, but did not enforce a deployment
floor. Its successful result was therefore compatible with the genuine `13.0`
value encoded in the app, frameworks, resource bundles, and Mach-O load
commands. Re-exporting or editing a signed archive cannot change that compiled
contract safely.

The project can retain iOS/iPadOS 13 and 14 compatibility temporarily, or move
the maintained source floor to 15 before Apple begins rejecting uploads. The
maintainer chose the latter so future features and distribution artifacts use
one forward-compatible default instead of deferring the migration to a release
deadline.

## Decision

1. **Raise the maintained source floor to 15.0.** Every Runner Xcode build
   configuration MUST set `IPHONEOS_DEPLOYMENT_TARGET` to `15.0`. Generated
   Flutter and Swift-package configuration must inherit that floor rather than
   introducing another authored version literal.

2. **Make the source setting executable.** A repository test MUST enumerate
   every authored Xcode deployment-target declaration, require the expected
   configuration count, and require exact value `15.0`. A missing, duplicate,
   lower, or independently changed configuration fails before merge.

3. **Enforce the compiled application payload.** The exported-IPA gate MUST
   require the top-level application's `MinimumOSVersion` and main Mach-O
   build-version command to encode an iOS minimum of at least `15.0`. A bundled
   dependency may retain a lower compatibility floor because it can still run
   inside a higher-floor application; it does not lower the application's
   installation requirement. This extends rather than replaces the existing
   signature, nested-code, and Xcode software-information checks.

4. **Require a clean rebuild.** A deployment-floor change MUST rebuild and
   re-archive the application and all embedded content from source. Editing an
   `Info.plist`, Mach-O load command, archive, or IPA after compilation/signing,
   or merely re-exporting an older archive, is prohibited.

5. **Preserve build 5 as history.** The retained `0.2.0 (5)` IPA, checksum,
   archive, source commit, and TestFlight plan continue to describe the exact
   iOS/iPadOS 13 artifact submitted through Transporter. They MUST NOT be
   relabelled as iOS/iPadOS 15.

6. **Do not create build 6 in this change.** The package identity remains
   `0.2.0+5` because this source-only change is not an external candidate or
   store upload. A later external artifact MUST receive the next globally
   monotonic build number under ADR-0044 and complete its own validation and
   handoff record.

## Consequences

- Future PyBLE iOS and iPadOS builds install only on version 15.0 or later;
  devices limited to versions 13 and 14 cannot install or update to those
  builds.
- The existing build-5 TestFlight artifact remains eligible on its encoded
  platform range and remains distinguishable from any later candidate.
- Store validation will fail locally if a project configuration or the
  compiled top-level application regresses below the maintained floor.
- Raising the deployment floor changes no PBLE/1 behavior, firmware baseline,
  application feature, Android minimum, or current app version/build identity.

## Alternatives considered

- **Wait until Spring 2027.** Temporarily preserves iOS/iPadOS 13 and 14 for
  new builds, but leaves a known distribution migration on the critical path
  and permits new features to keep treating the older floor as the default.
- **Patch or re-export build 5.** Rejected because the minimum is compiled into
  Mach-O load commands as well as bundle metadata, and because an uploaded
  build identity and signed historical artifact must remain immutable.
- **Upload build 6 immediately.** Rejected for this change because the
  maintainer requested a future-source default only; external candidate
  creation, physical acceptance, and TestFlight upload remain separate work.
- **Set only Release to 15.0.** Rejected because Debug/Profile divergence would
  hide compatibility failures during development and testing.

## Related

- [App build and distribution requirements](../specifications/App/specs.md#9-build-versioning--distribution--bld)
- [App test design](../specifications/App/TDD.md#159-ios-and-ipados-deployment-floor-gate)
- [Build 5 TestFlight handoff](../testing/testflight/0.2.0-build-5.md)
- [Apple `MinimumOSVersion`](https://developer.apple.com/documentation/BundleResources/Information-Property-List/MinimumOSVersion)

<!-- SPDX-License-Identifier: MIT -->

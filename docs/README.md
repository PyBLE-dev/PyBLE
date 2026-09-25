# PyBLE documentation

PyBLE keeps public contracts, design rationale, validation evidence, and
maintainer guidance beside the source they govern.

## Start here

- [Product scope](specifications/product.md)
- [Architecture](specifications/architecture.md)
- [PBLE/1 protocol](specifications/protocol.md)
- [App contract](specifications/app.md)
- [Firmware contract](specifications/firmware.md)
- [Hardware compatibility](specifications/hardware.md)
- [Public roadmap](ROADMAP.md)

## Proposed release plans

- [Firmware v0.6.1 and v0.7.0 roadmap](planning/firmware-v0.6.1-v0.7.0-roadmap.md)
  — v0.6.1 is published on owner confirmation; incomplete automated evidence
  remains pending, and Reliable Projects v0.7.0 remains proposed
- [Implementation strategy](planning/PyBLE_Implementation_Plan_and_Strategy_v1.0.md)
  — current outcomes, evidence gates and conditional expansion
- [Cycle 1 Scrum delivery package](developments/2026-q4-reliable-workflow/01_Overview_and_Scrum_Framework.md)
  — roadmap, milestones, stories and capacity forecasts
- [C1-S1 execution record](developments/2026-q4-reliable-workflow/c1-s1/00_Execution_Record.md)
  — channel evidence, pilot kit, recovery contract/sizing and validation recipe;
  physical installation and participant work remain blocked

## Detailed specifications

- [`specifications/App/`](specifications/App/) — app requirements, test design,
  and the Signal visual system
- [Bounded current-text recovery contract](specifications/App/current-draft-recovery.md)
  — specified in C1-S1; implementation and acceptance evidence remain pending
- [`specifications/firmware/`](specifications/firmware/) — firmware
  requirements, test design, browser flashing, release integrity, and HIL
  gates
- [Website](specifications/website.md) — public routes, privacy, compatibility,
  installer, and deployment contracts

PBLE/1 is the interoperability source of truth. Changes to wire behavior must
update the protocol specification, app and firmware implementations, and the
shared conformance corpus in one pull request.

## Rationale and evidence

- [Architecture Decision Records](decisions/README.md)
- [`validation/`](validation/) — retained release and hardware qualification
  evidence

## Related source repositories

- [PyBLE](https://github.com/PyBLE-dev/PyBLE) — canonical app, PBLE/1,
  firmware, product documentation, tests, and release tooling
- [PyBLE Examples](https://github.com/PyBLE-dev/examples) — separately
  governed official user-facing runnable-example collection; its
  [initial catalog plan](https://github.com/PyBLE-dev/examples/blob/0afe334a1435131f2bdc6189cad3b54cef59e3bc/docs/planning/examples-catalog-plan.md)
  records the founding scope

The current primary-maintainer sibling checkout for the examples collection is
`/Users/vyv/Working/SciLabPro/PyBLE-Examples`. This machine-local path is an
informational organization convention, not a contributor, build, application,
CI, or release requirement. [ADR-0041](decisions/0041-separate-official-examples-repository.md)
defines the boundary: official example implementation happens in that separate
repository and history, while this repository retains only the fixtures and
bundled offline examples required by its own product contracts.

## Testing and release handoff

- [Google Play open-testing submission packet](publication/google-play-open-testing.md)
  — app `0.2.0 (8)`, listing fields, graphics, declarations and tester setup
- [PyBLE 0.2.0 (5) TestFlight description and test
  plan](testing/testflight/0.2.0-build-5.md)
- [PyBLE 0.1.0 (4) TestFlight description and test
  plan](testing/testflight/0.1.0-build-4.md)
- [Current channel and artifact ledger](developments/2026-q4-reliable-workflow/c1-s1/01_Channel_and_Artifact_Ledger.md)
- [TestFlight metadata correction packet](developments/2026-q4-reliable-workflow/c1-s1/05_TestFlight_Metadata_Correction.md)
  — prepared replacement for the stale public description; store update pending

Reviewed delivery plans and redacted execution evidence live under
`developments/`. Raw observations, contact/consent records, device identifiers,
local worktree state and automated-agent orchestration remain outside Git.
Planning IDs are not GitHub issue numbers; link actual issues when created.

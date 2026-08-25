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

## Detailed specifications

- [`specifications/App/`](specifications/App/) — app requirements, test design,
  and the Signal visual system
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

- [PyBLE 0.1.0 (4) TestFlight description and test
  plan](testing/testflight/0.1.0-build-4.md)

Internal sprint notes and automated-agent orchestration are intentionally kept
outside the public source repository. Public work is planned through the
roadmap and GitHub issues.

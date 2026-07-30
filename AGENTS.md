# AGENTS.md — PyBLE contributor guidelines

These rules apply to humans and automated contributors working in this
repository.

## Project identity

**PyBLE** (“Python over BLE”) is a free, MIT-licensed, tablet-first
MicroPython IDE. The Flutter app communicates over Bluetooth Low Energy with a
compatible board running MicroPython and the portable PyBLE agent.

- App: `app/`
- Agent firmware: `firmware/`
- Open wire protocol: PBLE/1, specified in
  `docs/specifications/protocol.md`
- Initial validated ports: `esp32`, `esp32-s3`, and `esp32-c3`

Support is capability-defined, not tied to one chip family. A new port needs a
maintained PBLE/1 agent, BLE GATT peripheral support, sufficient resources, and
the project’s conformance and hardware-validation gates.

## Open-source and clean-room boundary

1. All PyBLE-authored source is MIT licensed.
2. Author changes fresh. Do not paste proprietary or unknown-licensed source,
   protocols, UUIDs, board profiles, examples, or product-specific pedagogy.
3. Keep PyBLE identifiers independent: `PBLE/1`, `pble_*`, `pyble_*`, the
   PyBLE UUID base, and the `PyBLE-` advertising prefix.
4. Run `tools/ci/no_leak.sh` before committing. The gate is the canonical,
   tested list of prohibited identifiers in shippable source.
5. Third-party dependencies remain under their own licenses and must be
   recorded in the relevant dependency and notice files.

## Spec-driven and test-driven development

1. `docs/specifications/` defines public behavior and architecture.
2. Change the relevant specification before implementation when a contract
   changes.
3. Work red → green → refactor:
   - add a failing test in a `[red]` commit;
   - implement the minimum passing change in a `[green]` commit;
   - clean up in a `[refactor]` commit while tests remain green.
4. No behavior is complete without an automated test. Hardware behavior also
   needs the documented HIL evidence.
5. Sign off every commit for DCO compliance: `git commit -s`.

Allowed commit prefixes are `[red]`, `[green]`, `[refactor]`, `[docs]`,
`[build]`, and `[chore]`.

## Repository layout

Keep the repository root limited to governance files and these directories:

```text
.github/  app/  docs/  firmware/  protocol/  examples/  tests/  tools/
```

Root governance files are:

```text
README.md  LICENSE  CONTRIBUTING.md  CODE_OF_CONDUCT.md  SECURITY.md
CHANGELOG.md  AGENTS.md  CLAUDE.md  .gitignore  .gitmodules
```

Put specifications and decisions under `docs/`, scripts under `tools/` or
`firmware/scripts/`, and examples under `examples/`. Keep screenshots, signing
material, builds, assistant state, and local notes out of Git.

## Naming

- Product and wordmark: **PyBLE**
- Domain: `pyble.dev`
- Protocol: **PBLE/1**
- Native modules: `pyble_agent`, `pyble_ble`, `pyble_runner`, `pyble_fs`,
  and related `pyble_*` / `pble_*` files
- Flutter packages: `lib/ble/`, `lib/pble/`, `lib/editor/`, `lib/console/`,
  `lib/files/`, `lib/blocks/`, and `lib/localization/`

## Hard boundaries

- Do not edit upstream MicroPython or Blockly in place. Pin upstream as
  submodules; isolate any unavoidable MicroPython patch under
  `firmware/patches/` with a written reason.
- Do not make USB serial or Wi-Fi the primary workflow. PyBLE is BLE-first.
- Do not introduce paid or closed features.
- Do not ship compiled `.mpy` examples; use readable `.py` files.
- Do not commit credentials, signing assets, firmware binaries, IPA files, or
  generated build directories.

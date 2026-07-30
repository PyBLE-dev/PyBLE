# ADR 0015 — Blocks exposes generic MicroPython digital GPIO through `machine.Pin`

**Status:** Accepted (2026-07-28). Extends the initial-toolbox decision in
[ADR-0013](0013-clean-room-blockly-one-way-file-backed.md); it does not change
that ADR's one-way workspace, bridge, file-backed action, offline-asset, or
persistence boundaries. It does not change the focused layout in
[ADR-0014](0014-focused-blocks-landscape-workspace.md), PBLE/1, the firmware, or
the read-only pin reference.

## Context

ADR-0013 deliberately shipped only Blockly's standard language categories and
required every later generic-hardware block contract and its tests to be frozen
before implementation. The language toolbox can compose calculations and
control flow, but it cannot yet construct or use MicroPython GPIO objects. A
visual MicroPython IDE must support the smallest useful digital-I/O loop without
introducing a board pin map, a routing profile, or another board-control path.

The supported ESP32 families do not share one valid-pin set or one set of
mode/pull restrictions. A pin number that is safe on one board may be reserved,
input-only, or absent on another. The app therefore cannot honestly validate
physical suitability from a generic workspace. That remains the board runtime's
responsibility, assisted only by PyBLE's separate informational pin reference.

## Decision

**The GPIO toolbox is a fresh, composable wrapper over standard MicroPython
`machine.Pin`; all physical choices remain explicit user program data.**

1. **One generic category and three stable blocks.** A PyBLE-authored **GPIO**
   category contains exactly this initial digital-I/O set:

   - `pyble_gpio_pin` is a value block with output connection check `Pin`. It
     has a required `Number` input named `GPIO`, with no connected shadow or
     preselected GPIO, a mode dropdown whose serialized values are `IN` and
     `OUT`, and a pull dropdown whose serialized values are `NONE`, `UP`, and
     `DOWN`; the latter two generate `Pin.PULL_UP` and `Pin.PULL_DOWN`.
   - `pyble_gpio_write` is a statement block with a required `Pin` value input
     named `PIN` and a level dropdown whose serialized values are `LOW` and
     `HIGH`.
   - `pyble_gpio_read` is a value block with a required `Pin` input named `PIN`
     and output connection check `Number`; it returns MicroPython's numeric
     digital value (`0` or `1`).

   Standard Blockly variable set/get blocks store and reuse the constructed
   `Pin` value. PyBLE adds no special declaration block and no implicit global
   pin object.

2. **Deterministic MicroPython generation.** If at least one
   `pyble_gpio_pin` exists, the GPIO generator owns the exact preamble
   `from machine import Pin` and emits it once, before executable statements.
   It registers the case-sensitive identifier `Pin` as reserved before Blockly
   allocates variable/procedure names, so user names cannot shadow the import.
   The generated forms are:

   ```python
   Pin(<gpio>, Pin.IN, None)
   Pin(<gpio>, Pin.OUT, None)
   Pin(<gpio>, Pin.IN, Pin.PULL_UP)
   Pin(<gpio>, Pin.IN, Pin.PULL_DOWN)
   <pin>.value(0)
   <pin>.value(1)
   <pin>.value()
   ```

   `NONE` emits an explicit third argument of `None`, which disables an
   existing pull instead of preserving a prior pin configuration. Whitespace
   and safe parenthesization may follow the pinned Blockly Python generator,
   but these calls and constants may not be replaced by a helper API.
   Constructing `Pin.OUT` does not promise or choose an initial electrical
   level; a program that requires a deterministic level must perform an
   explicit digital write.

3. **Two-layer structural validation.** The block definition constrains
   connections and dropdown choices, and the generator independently validates
   restored/tampered workspace data before publishing a snapshot. `GPIO` must be
   present as an explicit finite, non-negative integral numeric literal; missing,
   non-numeric, fractional, negative, or non-finite values are generator errors.
   Missing `Pin` receivers and unknown mode, pull, or level tokens are also
   generator errors. They use ADR-0013's existing error boundary: Blockly stays
   editable, stale Preview/Open/Save/Run actions are disabled, and a repaired
   workspace must publish a fresh valid snapshot before actions re-enable.
   Because deliberately empty required sockets are a normal intermediate edit,
   a generator-error bridge payload MUST also carry the current successfully
   serialized workspace and its next monotonic revision (plus the correlated
   request ID when applicable). Dart retains that JSON/revision even though it
   retains no actionable source. A structurally valid workspace-bearing error
   is an accepted, ready-but-invalid result even when it is the new host's first
   message: it stops the first-message watchdog and keeps the editable host
   mounted, but it does not enable a source action. Recreating the host restores
   this invalid but repairable workspace; source actions remain disabled until
   a later valid snapshot from the active host. If workspace serialization
   itself fails, ADR-0013's existing serialization/host recovery applies
   because there is no valid state to retain.

4. **No false physical validation.** The app does not carry an allowed-pin list,
   chip/board dropdown, named onboard component, routing table, or claimed
   default/safe GPIO. It does not reject a syntactically valid non-negative GPIO
   because of the connected board's reported chip, and it does not claim that a
   mode/pull combination is electrically supported. Standard MicroPython on the
   board validates the actual GPIO and combination at Run time; its unmodified
   exception remains visible in the console. The existing chip-keyed pin
   reference may inform the user, but it never changes workspace generation.
   The single `Pin` connection type also does not pretend to preserve `IN`/`OUT`
   mode through an untyped standard variable block; read/write generation is
   structurally valid, while the program and MicroPython runtime own whether the
   receiver's configured mode is appropriate.

5. **No new execution or firmware path.** GPIO blocks only add ordinary text to
   ADR-0013's generated `/blocks.py`. Preview, Open in editor, Save, and Run keep
   using the same fresh-snapshot and shared `ProgramActions` path. The WebView
   receives no `Connection`, device identity, chip value, capability set, BLE
   object, protocol opcode, or direct GPIO callback. No firmware or PBLE/1
   change is required.

6. **Clean-room and bounded scope.** The block definitions, identifiers, labels,
   tooltips, generator functions, toolbox entry, and tests are fresh MIT PyBLE
   work derived only from Blockly's public extension API and MicroPython's
   public `machine.Pin` API. No external product block catalog, source, asset,
   wording, styling, pin map, or lesson content is copied or shipped. PWM, ADC,
   interrupts, buses, timed/toggle helpers, and board-specific conveniences are
   outside this increment and require their own frozen contracts.

7. **Tests define the executable contract.** Before implementation, red tests
   must prove:

   - the GPIO category contains the three stable IDs and their connection types;
   - every mode/pull and LOW/HIGH branch emits the forms above;
   - several constructors produce exactly one import, while a workspace with no
     constructor produces none;
   - a standard variable assignment/reuse program preserves Blockly's normal
     Python variable-initialization preamble and generates:

     ```python
     from machine import Pin

     led = None
     button = None

     led = Pin(2, Pin.OUT, None)
     button = Pin(4, Pin.IN, Pin.PULL_UP)
     led.value(1)
     print(button.value())
     ```

   - `Pin` name collisions are sanitized rather than shadowing the import;
   - missing/invalid inputs and tampered dropdown tokens publish generator
     errors that retain workspace/revision, survive host recreation, and disable
     source actions until repair;
   - serialized GPIO blocks restore through an actual WebView host and generate
     the same source after recreation/rotation;
   - Preview/Save/Run still consume the fresh acknowledged source through the
     existing file-backed path on iPadOS and Android; and
   - asset-policy, offline, SPDX, license, localization, and no-leak gates remain
     green, with no board-specific pin catalog in shipped Blocks assets.

## Alternatives considered

- **A separate “set GPIO number high” block for every operation.** Rejected
  because repeated implicit construction obscures mode/pull ownership and
  prevents one configured `Pin` object from being reused through variables.
- **Named or board-filtered pin dropdowns.** Rejected because the app supports
  generic boards and cannot infer external wiring or a universally safe pin.
- **Validate against `DeviceInfo.chip`.** Rejected because that would feed board
  state into the offline WebView, turn informational cautions into an enforced
  profile, and still be incomplete for board-level wiring.
- **A blocks-only GPIO command over PBLE/1.** Rejected because ordinary
  MicroPython already owns GPIO and all generated programs must share the same
  inspectable file-backed execution path.
- **Set an implicit output level during construction.** Rejected because a
  hidden electrical transition is surprising; deterministic level changes must
  be visible as explicit write blocks.

## Consequences

Users can configure, read, and write generic digital GPIO while retaining
inspectable MicroPython and composability with variables, logic, and loops. The
same workspace remains offline and portable across supported chip families.
Physical validity is intentionally reported only by the actual MicroPython
runtime, so the block editor does not prevent every hardware mistake; this is
the honest tradeoff required by generic-board support.

## Related

- [App requirements §4.10](../specifications/App/specs.md)
- [App TDD §4.6 and §11.2](../specifications/App/TDD.md)
- [PRD §9.8 and §11.3](../specifications/prd.md)
- [Hardware support §3–§4](../specifications/hardware.md)
- [Public roadmap](../ROADMAP.md)
- [ADR-0013](0013-clean-room-blockly-one-way-file-backed.md)
- [ADR-0014](0014-focused-blocks-landscape-workspace.md)

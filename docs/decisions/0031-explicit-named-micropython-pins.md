# ADR 0031 — Blocks accepts explicit named MicroPython pins without a board profile

**Status:** Accepted (2026-08-12). Extends
[ADR-0015](0015-generic-micropython-gpio-blocks.md),
[ADR-0016](0016-offline-beginner-blockly-examples.md), and
[ADR-0017](0017-blocks-sidecar-and-bounded-python-import.md) under
[ADR-0021](0021-capability-defined-board-scope.md)'s capability-defined board
posture.

This decision supersedes **only** these numeric-only clauses:

1. ADR-0015 Decision 1's `Number`-only `GPIO` input and Decision 3's
   numeric-only pin validation become the integer-or-name union below.
2. ADR-0016 Decision 3's integer-only example roles, numeric-only uniqueness,
   and `math_number`-only materialization become the union, canonical
   uniqueness, and type-preserving materialization below.
3. ADR-0017 §5's numeric-only first argument to `Pin(...)` becomes the same
   integer-or-quoted-name union in the bounded importer.

Every other clause of those ADRs remains accepted and unchanged. In
particular, Time/range/configuration literals remain numeric; GPIO construction
still has no shadow or default; examples remain explicit, offline,
non-executing, and atomic; conversion remains bounded and all-or-nothing; and
the rejected named/board-filtered **dropdown** in ADR-0015 remains rejected.

## Context

Some conforming MicroPython ports expose hardware only through a named
`machine.Pin` identity. The Raspberry Pi Pico 2 W onboard LED is the concrete
validated case: the LED connected through the CYW43 radio is addressed as
`Pin("LED")`, not as an RP2350 numeric GPIO. PyBLE could scan, connect, and run
programs on that port, but its numeric-only Blocks surface could not express
the board's standard API without inventing a false GPIO number.

A per-board pin list would solve the immediate UI symptom while violating the
app's target-neutral architecture. It would require app releases to track
board aliases, turn `DeviceInfo` into a routing profile, and still be unable to
know the user's external wiring. The standard MicroPython call already has the
right ownership boundary: the user supplies a pin identity from the exact board
documentation, and the board runtime validates it.

## Decision

**Every existing Blocks GPIO slot accepts one explicit pin identity: either
the existing non-negative integer form or a bounded, user-entered MicroPython
pin name. PyBLE never discovers, suggests, or defaults that identity.**

### 1. One bounded identity union

A pin identity is exactly one of:

- an explicit non-negative integral decimal literal under the existing bound
  of the surface that consumes it (the example chooser and importer retain
  their JavaScript exact-safe-integer bound); or
- an ASCII, case-sensitive name matching
  `^[A-Za-z][A-Za-z0-9_]{0,15}$`.

The name branch is deliberately small and deterministic: one to sixteen ASCII
letters, digits, or underscores, beginning with a letter. `LED` and
`WL_GPIO0` are valid. Empty strings, digit-led or digits-only strings, spaces,
hyphens, non-ASCII text, escapes, names longer than sixteen characters,
variables, and arbitrary expressions are not pin identities. They use the
existing invalid-GPIO error path. This increment neither widens nor narrows the
existing integer branch.

### 2. Type-preserving Blockly representation and generation

`pyble_gpio_pin.GPIO` accepts Blockly `Number` or `String` values and retains
no shadow/default. An integer is represented by the ordinary `math_number`
block. A name is represented by the ordinary `text` block; it is not a new
board block or opaque metadata.

The production generator independently validates the connected value. It emits
integers bare and names as a double-quoted Python string:

```python
Pin(2, Pin.OUT, None)
Pin("LED", Pin.OUT, None)
```

A plain single- or double-quoted Blockly-generated string is accepted only
when its decoded content matches the name grammar. No other string or
expression is passed through. Import ownership, reserved-name handling,
mode/pull choices, error retention, snapshot acknowledgement, Save/Run, and
PBLE/1 remain unchanged.

### 3. Example roles use the same union

The native example chooser parses surrounding-whitespace-trimmed text into a
canonical integer or an exact name. It uses a normal text keyboard with
autocorrection and suggestions disabled because a pin name is an untranslated
technical identifier. New helper, validation, and duplicate-pin copy is
ARB-sourced.

Materialization deep-clones the immutable fixture and connects a
`math_number` block for an integer or a `text` block for a name. Mixed
integer/name roles are valid. Separate roles must remain pairwise distinct:
integers compare by integer value, names compare by exact case-sensitive text,
and the value type is part of the canonical identity. No catalog fixture
contains either kind of pin value, and no chooser remembers one after it
closes.

The production generator remains the only preview/source authority. Preview,
Create copy, and Replace workspace retain ADR-0016's explicit-action,
non-mutating/atomic, no-board-I/O boundaries.

### 4. The bounded importer admits quoted names only

ADR-0017's importer accepts the first `Pin(...)` argument when it is either
the existing non-negative decimal integer literal or a single- or
double-quoted string literal whose decoded value matches the name grammar. A
name maps to the ordinary Blockly `text` value connected to
`pyble_gpio_pin.GPIO`; an integer continues to map to `math_number`.

Quote spelling may normalize during generation, as ADR-0017 already permits,
but normalized semantic equality includes the identity kind and exact value.
An invalid name, variable identity, or one invalid `Pin` among otherwise valid
statements rejects the complete conversion with the existing `invalid_gpio`
diagnostic. Exact sidecar reopen is unchanged because it already verifies the
stored workspace and generated source byte-for-byte.

### 5. Target neutrality remains mandatory

The app ships no board-to-name map, named-pin dropdown, suggestion, default,
autocompletion list, capability gate, automatic example selection, or hidden
translation from a board name to a pin. It does not read `DeviceInfo` or a
provisioning profile while validating or generating a pin. `LED` is accepted
only because the user entered those exact characters; another supported board
may accept a different name or only integers.

The connected MicroPython runtime remains authoritative for whether a
syntactically accepted identity exists and supports the requested mode/pull.
Its original exception remains visible in the console. This decision changes
no firmware, PBLE/1 message, pin reference, or support/qualification gate.

### 6. Verification freezes the boundary

Red tests precede implementation and prove at least:

- asset definitions accept only `Number`/`String`, emit bare integers and
  quoted names, cover the sixteen-character boundary, and reject every invalid
  grammar family through the existing repairable error path;
- example parsing/materialization preserves integer/name types, accepts mixed
  roles, rejects duplicate canonical identities, leaves fixtures immutable,
  and invokes no board operation;
- the native chooser accepts `LED` with stable focus and localized copy on
  iPadOS and Android;
- the importer accepts both quote styles, produces ordinary text blocks,
  preserves semantic identity through generation/reparse, and rejects invalid
  input all-or-nothing;
- the existing numeric ESP32 example path, exact sidecar reopen, NeoPixel/TFT
  pin composition, offline/CSP, localization, license, and no-leak gates do not
  regress; and
- on the validated Pico 2 W, entering `LED` in the unchanged Blink example
  generates `Pin("LED", ...)`, runs through the normal file-backed path, and
  blinks the physical onboard LED without a board profile.

## Alternatives considered

- **Add a Pico-specific LED block or rewrite a number to `LED`.** Rejected:
  generated source would hide the real API and make the app board-aware.
- **Ship a dropdown of known aliases.** Rejected: aliases belong to individual
  ports/boards, become stale independently of the app, and cannot describe
  external wiring.
- **Accept any string or Python expression.** Rejected: it would bypass the
  inspectable bounded subset and make deterministic validation/round trips
  impossible.
- **Require users to leave Blocks and hand-edit Python.** Rejected: a standard
  MicroPython pin identity belongs in the same composable GPIO surface as a
  standard numeric identity.

## Consequences

Users can express standard named pins, including the Pico 2 W onboard LED,
without adding board logic to Flutter. Existing numeric workspaces and examples
remain valid. The extra union branch adds validation, localization, and
round-trip tests; the intentionally bounded grammar may not cover every future
port alias, which requires a later specified extension rather than an opaque
escape hatch.

## Related

- [App requirements FR-BLOCKS-1B and A-38](../specifications/App/specs.md)
- [App TDD §4.6 and §11.2](../specifications/App/TDD.md)
- [Pico 2 W port contract](../specifications/firmware/ports/rpi-pico2-w.md)
- [ADR-0015](0015-generic-micropython-gpio-blocks.md)
- [ADR-0016](0016-offline-beginner-blockly-examples.md)
- [ADR-0017](0017-blocks-sidecar-and-bounded-python-import.md)
- [ADR-0021](0021-capability-defined-board-scope.md)

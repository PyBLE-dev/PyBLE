# ADR 0016 — Blocks ships an offline, editable beginner-example library

**Status:** Accepted (2026-07-28). Extends the one-way Blockly surface in
[ADR-0013](0013-clean-room-blockly-one-way-file-backed.md), the focused Blocks
layout in [ADR-0014](0014-focused-blocks-landscape-workspace.md), and the
generic GPIO set in [ADR-0015](0015-generic-micropython-gpio-blocks.md). It
does not change the generated-program snapshot boundary, `/blocks.py` action
path, firmware, PBLE/1, or generic-board posture.

## Context

The standard Blockly toolbox and generic GPIO blocks make useful programs
possible, but an empty canvas does not show a first-time user how expressions,
statements, loops, variables, functions, and GPIO objects compose. PyBLE needs
a small progression that a beginner can inspect and edit without turning the
app into a classroom curriculum, copying another product's lesson catalog, or
claiming that one GPIO is safe on every ESP32 board.

Three safety and integrity constraints shape this feature:

- examples must remain fully offline and must never run, save, or alter a board
  merely because the user browsed or loaded one;
- an example must become an ordinary Blockly workspace rather than a special
  opaque document that cannot use the normal generator and recovery path; and
- GPIO examples cannot contain a preselected pin, including a number presented
  as merely illustrative, because users commonly interpret examples as safe
  defaults.

The requested Count and Blink examples also need a paced delay. The initial
toolbox has no MicroPython timing block, so a minimal generic timing contract
must be frozen with the library.

## Decision

**PyBLE ships six fresh, local starter templates. The app generates their
preview with the production generator and loads only an editable deep copy
after every required GPIO is explicitly selected.**

1. **A versioned local catalog with six stable IDs.** The bundled
   `app/assets/blockly/examples/catalog.json` has top-level catalog
   `version: 1` and exactly these ordered entries:

   | Stable ID | Beginner progression | Hardware roles |
   |---|---|---|
   | `hello-pyble` | Print a greeting to the console | none |
   | `count-repeatedly` | Change a variable in a paced repeat loop and print it | none |
   | `blink-led` | Configure an output Pin and alternate LOW/HIGH with delays | `led` |
   | `read-button` | Configure a pulled input Pin and print paced reads | `button` |
   | `button-controls-led` | Read a button, branch, and write an LED Pin | `button`, `led` |
   | `reusable-function` | Define and call a procedure with a parameter | none |

   Each entry contains only stable technical metadata and an ordinary object
   accepted by `Blockly.serialization.workspaces.load`: `id`, ARB lookup keys
   for title/summary/concepts/wiring notes, `workspace`, and zero or more
   `gpioRoles`. A GPIO role is
   `{role, labelKey, blockId, input: "GPIO"}` and points to a disconnected
   required `GPIO` socket in the catalog workspace. The catalog does not store
   generated source or a hand-maintained source template; the pinned production
   generator is the only source authority.

2. **A minimal generic timing block.** A fresh **Time** toolbox category
   contains `pyble_time_sleep_ms`, a statement block with required `Number`
   input `MILLISECONDS` and no connected shadow or default. Its generator
   accepts only an explicit finite, non-negative integral numeric literal,
   reserves `sleep_ms` before name allocation, installs exactly one
   `from time import sleep_ms` preamble when used, and emits:

   ```python
   sleep_ms(<milliseconds>)
   ```

   Missing, negative, fractional, non-finite, or tampered input is a normal
   generator error under ADR-0013's editable-workspace recovery boundary.
   Delay duration is program data, not a board profile. No new firmware,
   protocol, or direct board operation is introduced.

3. **GPIO choice precedes a runnable preview or copy.** Selecting a GPIO
   example presents one localized input for each role. Every role is required
   and accepts a finite, non-negative integer. When an example has multiple
   hardware roles, their numeric GPIO values must be pairwise distinct: reusing
   one GPIO for the example's separate input/output objects produces a localized
   duplicate-GPIO error and returns focus to a conflicting role field. This is
   graph-integrity validation for that example, not a board pin allowlist or a
   claim that either chosen GPIO is electrically suitable. PyBLE supplies no
   value, suggested pin, chip-derived choice, named onboard component, or
   remembered board default. It tells the user to consult the informational pin
   reference and their board documentation.

   Once the roles are valid, the host deep-clones the catalog workspace and
   connects ordinary `math_number` blocks containing the chosen values to the
   declared target sockets. It rejects a missing/duplicate role, a reused
   numeric value across separate roles, an unknown block or input, a target that
   is not `pyble_gpio_pin.GPIO`, or an already-connected target. No placeholder
   or role-binding metadata enters the loaded or persisted workspace. The
   resulting JSON is ordinary editable Blockly serialization and generation is
   identical to a workspace built by hand.

4. **One chooser, three explicit operations.**

   - **Preview** is non-mutating. It shows the localized summary, concepts,
     wiring note, selected GPIO roles when applicable, and selectable read-only
     Python generated from the candidate by the real generator. Browsing,
     changing a GPIO choice, closing the chooser, or previewing never changes
     the active workspace.
   - **Create copy** appears when the active workspace is semantically empty.
     It deep-clones the immutable catalog entry, materializes any explicit GPIO
     choices, validates and generates it, then submits that clone for restore.
     It becomes the active editable workspace only after the active host
     acknowledges the restored candidate with its first accepted snapshot.
   - **Replace workspace** appears instead when the active workspace contains
     any block, variable, or procedure, including an incomplete or
     generator-invalid graph. It requires a confirmation that the current
     workspace will be replaced. Cancel leaves the workspace byte-for-byte
     unchanged. A failed materialization, restore, or generation also leaves or
     restores the prior workspace rather than exposing a partially replaced
     graph.

   An example fixture is immutable. Editing a created copy never changes what
   the next user receives from the catalog.

5. **Discoverability without sacrificing canvas space.** A semantically empty
   Blocks workspace shows a prominent **Examples** call to action that
   disappears after the first user block, variable, or procedure is created.
   The Flutter-owned Blocks action strip retains an **Examples** entry at all
   times. At constrained widths Examples moves first into a labelled,
   keyboard- and screen-reader-reachable overflow; further non-Run actions may
   join it if necessary. Horizontal scrolling, clipping, or compressing targets
   is not the overflow contract. The Blockly toolbox also exposes an
   **Examples** category whose entries open the same host chooser; they do not
   insert opaque example blocks. An event with an absent or null optional
   example ID opens the chooser at its default selection; a non-string or
   unknown ID is ignored without changing host/document readiness. Every valid
   entry reaches the same catalog and the same
   Preview/Create-copy/Replace-workspace state machine.

6. **Wiring information is honest and generic.** Hardware examples distinguish
   the user-entered GPIO roles and include short wiring notes:

   - Blink and Button-controls-LED describe an external LED with an appropriate
     current-limiting resistor and do not assume an onboard LED.
   - Read-button and Button-controls-LED describe the example's input pull and
     active level so its condition is understandable.
   - Every hardware note says to verify the chosen pins, voltage, and wiring
     against the user's own board documentation.

   The catalog has no pin allowlist, chip/board selector, named board component,
   schematic tied to one product, or claim of electrical suitability. Actual
   pin/mode/pull validity remains MicroPython's runtime responsibility, and its
   original exception remains visible in the console.

7. **Loading is never execution.** Preview, Create copy, and Replace workspace
   perform no `Connection` call, board file write, Run, editor hand-off, or
   console mutation. Restore may show a loading state, but the app announces
   that an example is loaded only after the active host acknowledges the
   restored candidate snapshot; a failed restore rolls back and never emits
   success first. After acknowledgement, Preview/Open/Save/Run remain distinct
   user actions and retain ADR-0013's fresh-snapshot acknowledgement and action
   lock. Infinite-loop examples clearly say that they continue until the user
   presses Stop, but they are never started automatically.

8. **Localization, accessibility, and responsive behavior.** Titles,
   summaries, concepts, GPIO-role labels, wiring notes, warnings, buttons,
   confirmations, validation errors, and semantics labels are ARB-sourced.
   Stable IDs, workspace block IDs, Python, and GPIO numbers remain unlocalized
   technical data. The empty-state call to action, toolbar entry, catalog rows,
   role inputs, and dialog actions are keyboard reachable, expose names/roles
   and selected/disabled state, meet the 48 dp target rule, preserve focus on
   validation errors, announce each completed preview once, and announce a
   loaded result only after the active-host acknowledgement in item 7. The
   chooser scrolls rather than clipping at large text. At compact widths below
   600 dp it uses a scroll-controlled modal bottom sheet; at 600 dp and wider it
   uses a dialog. Neither presentation resizes the Blockly canvas behind it.

9. **Ordinary persistence and recovery.** Once loaded, an example copy uses the
   same `workspaceJson`/revision provider, host-epoch restore, invalid-workspace
   retention, rotation, and future A-24 durable-project hook as any hand-built
   workspace. Recreating the platform view never reopens the chooser or
   rematerializes a catalog fixture. A chooser may retain draft GPIO values
   only while it is open; they are not a board profile and are discarded on
   cancel. An unknown catalog version, malformed entry, invalid role binding,
   or generation failure produces a localized non-destructive error and never
   clears the active workspace.

10. **Fresh clean-room content, not a curriculum.** The six workspaces,
    metadata, strings, timing block, and tests are new MIT PyBLE work derived
    only from public Blockly and MicroPython APIs. They are small starter
    templates, not a copied tutorial sequence, classroom lesson framework,
    worksheet, grading system, or domain-specific lab exercise. No external
    source, wording, artwork, block layout, schematic, or pedagogy is imported.

11. **Tests define the executable contract.** Red tests must prove:

    - catalog v1 has exactly the six stable IDs, valid unique ARB keys, ordinary
      serializable workspaces, and valid/complete role bindings;
    - every non-GPIO workspace restores and generates using the actual pinned
      runtime; each GPIO workspace does so only after test-supplied, pairwise
      distinct role values are materialized, duplicate role values produce a
      localized field error, and no catalog fixture contains a numeric GPIO;
    - the Time block rejects invalid input, reserves its import name, and
      generates one exact import for one or many delays;
    - generated examples cover greeting, paced counting, paced GPIO blink/read,
      conditional button-to-LED control, and procedure definition/call without
      unknown or disabled block types;
    - Preview is non-mutating; empty Create copy loads an editable clone;
      non-empty Replace requires confirmation; cancel and all failure paths
      preserve the prior serialized workspace and revision; and loaded success
      is announced only after the active host acknowledges the candidate;
    - no catalog interaction invokes Preview/Open/Save/Run implicitly, performs
      board I/O, or replaces the text-editor document;
    - empty-state, persistent action-strip, and toolbox entries all reach the
      same chooser; absent/null and invalid toolbox IDs follow the non-destructive
      rules above; compact sheet, wider dialog, and constrained-width action
      overflow remain reachable; and actions/source state remain correct across
      navigation/recreation/rotation; and
    - locale parity, semantics/keyboard/large-text widget coverage, offline/CSP,
      asset-policy, SPDX/license, and no-leak gates remain green on iPadOS and
      Android.

## Alternatives considered

- **Hard-code common GPIO numbers in the examples.** Rejected because no pin is
  a truthful default across generic boards and example values are easily
  mistaken for safety guidance.
- **Show source strings stored beside each workspace.** Rejected because they
  can drift from the pinned generator and undermine the promise that inspected
  Python is the code generated from the shown blocks.
- **Insert a special “example” block.** Rejected because the result would not be
  an ordinary editable workspace and would require a second generation path.
- **Replace a non-empty workspace immediately.** Rejected because browsing
  beginner content must not destroy work.
- **Run an example as soon as it loads.** Rejected because loading cannot safely
  imply consent to upload code or change electrical outputs.
- **Fetch examples from a website.** Rejected because core learning and editing
  are offline-first, reproducible, and require no account or network.

## Consequences

Beginners gain a discoverable path from a greeting through reusable functions
and generic digital I/O, while every result remains inspectable standard
MicroPython and editable ordinary Blockly JSON. The costs are a small catalog
and localization surface, an extra explicit pin-selection step for hardware
examples, a minimal Time block, and validation/atomic-replacement logic. The
explicit step is intentional: PyBLE teaches the structure of a program without
pretending to know the user's board or wiring.

## Related

- [App requirements §4.10](../specifications/App/specs.md)
- [App TDD §4.6 and §11.2](../specifications/App/TDD.md)
- [PRD §9.8](../specifications/prd.md)
- [Public roadmap](../ROADMAP.md)
- [ADR-0013](0013-clean-room-blockly-one-way-file-backed.md)
- [ADR-0014](0014-focused-blocks-landscape-workspace.md)
- [ADR-0015](0015-generic-micropython-gpio-blocks.md)

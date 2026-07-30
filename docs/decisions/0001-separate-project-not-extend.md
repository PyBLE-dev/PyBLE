# ADR-0001 — Separate project, not an extension

- Status: **Accepted**
- Date: 2026-06-30

## Context

The author maintains a proprietary, closed-source, tablet-first MicroPython IDE built specifically for one chemistry-education board (classic ESP32). The desire arose to support **generic ESP32 boards for general use**. The question: extend that existing product, or start a new one?

The existing product is deliberately narrow and proprietary: its doctrine explicitly excludes generic boards, and every file is closed-source. Its connection stack (a custom BLE protocol, pairing, lease) is tightly coupled to that board.

## Decision

Build a **new, separate project** (PyBLE). Do not extend or refactor the existing product.

## Rationale

1. **Doctrine.** Generic-ESP32 support is an explicit non-goal of the existing product; bolting it on fights that product's purpose.
2. **Licensing posture.** The existing product is proprietary/closed; the new one is public/open-source. Mixing the two pollutes both postures.
3. **Connection stack is replaced wholesale.** A generic, wireless MicroPython IDE needs its own protocol and transport; little of the existing closed stack transfers.
4. **Reuse is still possible cleanly.** The board-agnostic UI (editor, file explorer, plots, blocks, localization) can be re-implemented / relicensed-MIT by the author into the new repo without dragging proprietary code along (see [ADR-0002](0002-fresh-protocol.md)).

## Consequences

- Two codebases; bug-fixes to shared-in-spirit widgets are hand-ported.
- A hard clean-room boundary must be maintained (no-leak CI gate).
- The new project is free to adopt an open-source identity and community model.

# ADR-0002 — Fresh, clean-room protocol (PBLE/1)

- Status: **Accepted**
- Date: 2026-06-30

## Context

PyBLE needs a wire protocol between the app and the board over BLE. The author owns a proven proprietary protocol from a prior product and could, in principle, reuse its design. But PyBLE is **open-source (MIT)** and must contain no proprietary intellectual property.

A separate truth: MicroPython ships **no BLE REPL**, so wireless edit/run genuinely requires a custom board-side agent and a protocol — there is no "stock" option to fall back on.

## Decision

Design a **fresh, clean-room protocol — PBLE/1** — with its own framing, opcodes, BLE UUIDs, and file-transfer scheme. Do **not** reuse the proprietary protocol's wire format or identifiers.

The author may **reference** their own prior art as a design blueprint (lessons learned about BLE flow control, stop semantics, reconnect/resume) and may **re-implement** board-agnostic UI widgets they own under MIT — but no proprietary protocol code, opcodes, or UUIDs are copied.

## Rationale

- An MIT public repo cannot legally or ethically contain closed-source protocol IP.
- A fresh protocol lets PyBLE shed board-specific command semantics it doesn't need.
- "Clean-room, informed by owned prior art" keeps the hard reliability problems (file-transfer flow control, resume) de-risked without copying.

## Consequences

- The reliability work (windowed upload, CRC, resume, stop-ladder) is **re-implemented and re-validated** on hardware — budgeted as the project's hardest part.
- A no-leak CI gate enforces the boundary on every push.
- PyBLE owns its protocol and can evolve it openly (PBLE/2, capability flags).

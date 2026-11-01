<!-- SPDX-License-Identifier: MIT -->
<!-- Part of PyBLE (https://pyble.dev) — see /LICENSE. -->

# ADR-0049 — Query committed execution state after reconnect

Date:2026-11-01. Status:accepted for the first selected v0.7 increment.

## Context

PBLE/1 omits events created without a live connection. A reconnecting client
cannot infer idle from silence; autorun may already be running. The user selected
firmware roadmap implementation and relevant app support. This first delivery
follows PYB-017.1 → PYB-018; other Reliable Projects capabilities remain proposed.

## Decision

Use the additive contract in [protocol §6.1](../specifications/protocol.md#61-additive-runsession-status--selected-v07-increment):
RUN_STATUS0x24, RUN_STATUS_CHANGED0x42 and run_status=1. Snapshots commit at existing
admission/terminal cuts and carry randomized ephemeral VM identity, run ID and
revision. Session observation is opt-in; old clients receive their legacy events.
Tagged revisions resolve response/event races, and the app caches synchronized
status before readiness. Querying does not run code or change board storage.

## Verification

Use signed red/green commits, shared payload vectors, compiled native harnesses,
portable dispatcher/runner tests and app handshake/race/fallback tests. Qualify
exact new firmware on five profiles and both tablet platforms before a release
claim. October app acceptance does not supply new firmware qualification. No
new ports, opcode changes to legacy operations or public 0.7.0 release are implied.

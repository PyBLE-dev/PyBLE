# ADR-0003 — MIT, free, donation-supported (Thonny model)

- Status: **Accepted**
- Date: 2026-06-30

## Context

PyBLE will be distributed publicly. Options ranged from commercial/closed, through open-core/freemium and "open source but sell the build," to fully free and open like Thonny.

The MicroPython tooling ecosystem (Thonny, Mu, mpremote, esptool) is overwhelmingly free and open-source. Trust matters because the tool flashes firmware onto users' boards and runs their code. Broad board support depends on community contributions.

## Decision

License the entire project (app + firmware agent + protocol) under the **MIT License**. Distribute it **free** — no paywall, no account, no telemetry-by-default. Fund it via **donations / GitHub Sponsors**, not sales. This mirrors the Thonny model.

## Rationale

- Maximizes adoption and lowers friction in an ecosystem that expects open tools.
- Builds trust for a tool that touches firmware and user code.
- Invites the community contributions (new boards, translations, fixes) that the project's breadth depends on.
- Permissive MIT (vs copyleft) further lowers the barrier to use and contribution.

## Consequences

- No direct revenue line; sustainability rests on sponsorship/donations.
- The clean-room boundary ([ADR-0002](0002-fresh-protocol.md)) becomes load-bearing and public — enforced by CI.
- Copied-from-prior-art widgets are relicensed MIT by the author at copy time (header replaced).
- Third-party dependencies must remain MIT/Apache/BSD-compatible; notices shipped in `THIRD_PARTY_LICENSES`.

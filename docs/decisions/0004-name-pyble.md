# ADR-0004 — Name: PyBLE

- Status: **Accepted**
- Date: 2026-06-30

## Context

The project needed a name for an open-source, BLE-first, MicroPython tablet IDE. Candidates were screened for meaning, friendliness (Thonny/Mu family), and **namespace availability** (GitHub org, pub.dev, App Store, domain). Several early ideas collided with existing products:

- *Wispy* → clashes with **Wi-Spy** spectrum analyzers (same wireless space).
- *Bleep* → many existing App Store / Play apps.
- *PyBeam* → several existing `pybeam` packages on PyPI/GitHub.
- *AirPy* → a past FPV-logger usage.

## Decision

Name the project **PyBLE** — a coining of **"Python over BLE."** Wordmark **PyBLE**; repository folder `PyBLE`; pronounced "PY-bull."

## Rationale

- Directly describes what the product does (Python, over Bluetooth Low Energy).
- Distinctive coined word with a likely-clean namespace.
- Friendly and short, in the Thonny/Mu family.

## Consequences

- Canonical identifiers: protocol **PBLE/1**, agent modules `pyble_*`, BLE name prefix `PyBLE-`, UUID base encoding `pybl`.
- Final handle reservations (GitHub org, pub.dev, App Store display name) confirmed in M0. Domains secured — see [ADR-0005](0005-standalone-domain.md).

# Firmware conformance fixtures

This directory contains the active host-consumed PBLE/1 fixtures. PBLE/1
§2–§10 is frozen for v1.0; none of the files at this directory level is a
placeholder waiting for a protocol freeze.

| Fixture | Current role |
| --- | --- |
| `corpus.json` | Legacy byte-exact frame, CRC, fragmentation, response, and event codec vectors shared by firmware and client tests. Its scope is intentionally frame-level for several older operations. |
| `v061_session_vectors.json` | v0.6.1 HELLO grammar, version negotiation, session, direction/ID, and validation-precedence semantics shared by portable and compiled-native tests. |
| `v061_payload_grammar_vectors.json` | Exact existing-opcode payload acceptance and rejection semantics used for native/portable parity. |
| `v061_label_vectors.json` | Strict UTF-8 label and control-codepoint cases shared by both agent implementations. |
| `test_hil_wire.py` | Proves the HIL client's frame codec continues to consume the active byte corpus exactly. |

The S3–S6 byte-less planning ledgers created before the corresponding protocol
freezes are preserved unchanged under `archive/pre-freeze/`. They explain why
wire bytes were deliberately not invented at that time; they are historical
records, not current requirements and not evidence that a test remains blocked.
Their individual ideas were implemented or superseded through the frozen
specifications and named portable/native host suites. No retrospective claim is
made that every old idea was copied into `corpus.json`.

Host success is not physical qualification. v0.6.1 still requires fresh
exact-byte HIL on all five profiles, including the iPadOS and Android rows,
before standard automated-qualified release admission or publication. Its
separate [owner-confirmed publication](../../../../docs/testing/firmware-v0.6.1-publication-2026-09-11.md)
preserves incomplete automated records and supplies no substitute pass.
The [C1-S1 operator inventory](../../../../docs/developments/2026-q4-reliable-workflow/c1-s1/04_Validation_Inventory_and_Operator_Recipe.md)
maps host evidence to the physical work and access still required.

<!-- SPDX-License-Identifier: MIT -->

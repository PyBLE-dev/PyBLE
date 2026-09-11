# Archived S3–S6 pre-freeze ledgers

These four JSON files are immutable planning records from the initial public
source snapshot. They describe the protocol/specification state observed by
their authors on 2026-07-01, before the dependent PBLE/1 sections were frozen.
Words such as `PENDING`, `DRAFT`, and `blocked_on` are preserved as historical
facts; they do not describe the current source tree and must not be consumed as
an active conformance gate.

The files were moved here without changing a byte. Their SHA-256 identities
are:

| File | SHA-256 |
| --- | --- |
| `s3_pending.json` | `7d9f9089c390a5f02a8b14ef8cc8fad77189a2270ab7a2132fbcbceed5b4327a` |
| `s4_pending.json` | `89f3f6f6e57172041715317cfa7f6cb0ca07c24ed0ac212632ef64a305a60b43` |
| `s5_pending.json` | `05e7b01e404155d332fb91c217d33214a92bb70aa1b3c3d0a3943cdc6cbbf737` |
| `s6_pending.json` | `96c51e3dbd0c591fdc2b3b148770ec9b1845f65e2ca22d09132035c8fad6a212` |

In particular, the S3/S5 references to a `max_file_size` capability are not a
current requirement. The frozen serialized caps never included that key, and
the v0.6.1 contract uses dynamic `FILE_PUT_BEGIN` storage admission instead.
See the parent [current fixture ledger](../../README.md) for active coverage.

<!-- SPDX-License-Identifier: MIT -->

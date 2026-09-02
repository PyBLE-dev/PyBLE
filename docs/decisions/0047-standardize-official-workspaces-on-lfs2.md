# ADR-0047 — Standardize official firmware workspaces on LFS2

- Status: **Accepted**
- Date: 2026-09-03
- Builds on: [ADR-0033](0033-qualify-v060-as-five-profile-heterogeneous-release.md)
- Normative contracts:
  [PBLE/1 §5](../specifications/protocol.md#5-file-transfer-the-reliability-core),
  [firmware requirements §4.4](../specifications/firmware/specs.md#44-filesystem-bridge--workspace-jail-fr-fs),
  and [firmware TDD §9.1](../specifications/firmware/TDD.md#91-vfs--littlefs)

## Context

The v0.6.1 roadmap originally asked upload admission and scratch safety to work
"across FAT and LFS2." That wording did not match the official profile design.
Pico 2 W already constructs an LFS2 workspace, while ESP partition tables use
the ESP-IDF subtype token `data,fat` with the label `vfs`. MicroPython uses that
label for LFS2 first-use provisioning; the subtype token is block-container
metadata and does not require an on-media FAT filesystem.

Leaving generic VFS auto-detection in the ESP boot path would nevertheless let
an old or foreign FAT workspace mount. It would also make PBLE/1's verified
scratch-to-target replacement depend on filesystem-specific rename behavior.
Automatically formatting incompatible nonblank media is not an acceptable way
to remove that ambiguity because it can destroy user files.

## Decision

1. Source-selected v0.6.1 and later official images use LFS2 for the internal
   workspace on all five supported profiles.
2. Every official overlay reaches one shared, frozen mount authority that
   constructs `VfsLfs2` explicitly. Generic filesystem auto-detection is not an
   official boot path.
3. First-use formatting is permitted only after a normal LFS2 mount fails and a
   complete read-only scan conclusively proves every device byte is erased.
   Invalid geometry, an unreadable block, an allocation failure, a non-erased
   byte, or any other uncertainty performs no format.
4. A nonblank incompatible or corrupt workspace fails closed without starting
   the PBLE/1 agent. Recovery or migration is an explicit operator action.
5. The ESP `data,fat` partition subtype remains unchanged because it identifies
   the flash block container; the `vfs` label and explicit constructor define
   the on-media LFS2 format.
6. The immutable qualified v0.6.0 release is not rebuilt, repackaged, or
   reinterpreted by this decision. Its fresh-install evidence remains
   historical; v0.6.1 requires new exact-profile qualification.
7. A future port may propose another VFS only through a specification-first
   decision defining atomic replacement, ordering, recovery, resource, and HIL
   semantics. It cannot silently broaden this five-profile LFS2 contract.

## Consequences

- PBLE/1 upload admission has one official filesystem geometry and reserve
  interpretation across the five-profile release set.
- Successful scratch-to-target rename relies on LFS2's atomic commit rather
  than a FAT delete-then-rename fallback.
- Devices carrying an incompatible nonblank workspace need an explicit backup,
  migration, or erase rather than automatic destructive repair.
- Release and HIL evidence must prove LFS2 mount, erased-media provisioning,
  incompatible-media refusal, and workspace preservation independently on all
  five profiles before v0.6.1 publication.

<!-- SPDX-License-Identifier: MIT -->

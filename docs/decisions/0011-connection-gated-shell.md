# ADR 0011 — Connection-gated shell: Connect is a full-screen pre-connection surface, not an IDE tab

**Status:** Accepted (2026-07-03). Refines the FR-UI-1 landscape three-pane layout and extends [ADR-0008](0008-signal-design-system.md) (Signal shell) and [ADR-0009](0009-runtime-connection-manager.md) (runtime session behind the seam). Scope: `lib/app/shell.dart` + `lib/app/providers.dart` only; no seam, wire, or feature-package change.

## Context

The Signal landscape shell renders a fixed three-pane IDE frame — **Files sidebar | centre surface | Pin-reference pane**, with a top toolbar and a bottom console strip — and "Connect" was plugged into the **centre** as one of four peer navigation surfaces (Connect / Editor / Console / Files). Two problems followed, both reported by the owner:

1. The **Files sidebar and Pin-reference pane flank Connect**, so "Files" appears on the Connect screen (and, before the S-of-S3 fix, twice at once). But **before a board is connected there are no files** (no board), **no chip pins** (no `DeviceInfo`), and **no console output** — the IDE chrome is meaningless pre-connection.
2. Treating Connect as a peer editing surface is the root cause: Connect is a **mode** (the pre-connection scan/connect experience), not a work surface you edit alongside files.

`ConnState` is a frozen 4-value enum (`disconnected`/`connecting`/`ready`/`running`) and the seam already yields a live, observable state ([ADR-0009](0009-runtime-connection-manager.md)). So the shell can gate on it.

## Decision

**The shell is connection-gated. With no board connected the app is a full-screen Connect experience with NO IDE chrome; the three-pane / stacked IDE appears only once a board is `ready` (or `running`). Connect is removed from the IDE navigation entirely — it is the pre-connection surface, reached again by disconnecting.** Concretely:

1. **`PybleShell` watches `connStateProvider`.** When the state is not `ready`/`running` it renders `_DisconnectedShell` — the status toolbar over a full-screen `ConnectPage`, with **no Files sidebar, Pin-reference pane, or console strip**. `connecting` stays on the Connect surface (which shows its own progress). Once `ready`/`running`, it renders the existing landscape or stacked IDE by width.

2. **The IDE navigation is Editor / Console / Files** (`_ideNavSurfaces`); **Connect is not an IDE tab.** In landscape the centre work surface is Editor or Console only (Files is the collapsible left sidebar, a rail toggle — see the FR-UI-1 sidebar note); it defaults to the editor. In the stacked layout Files is an ordinary destination and the default is likewise the editor.

3. **Disconnect lives on the toolbar.** When a board is connected the toolbar's connection action is an active **Disconnect** (`connectionManagerProvider.disconnect()`), which returns to the full-screen Connect flow. While disconnected it is an inert Connect slot (the live scan/connect flow is the surface below).

## Consequences

- Files/Pins/console never flank the pre-connection flow; the pre-connection state reads as a single, focused Connect screen (the owner's complaint is resolved at the layout level, not by hiding a pane).
- The connected experience is unchanged except that the rail no longer lists Connect and the toolbar gains Disconnect. Existing goldens were reseeded; a new `shell_ipad_landscape_disconnected` baseline locks the pre-connection state.
- The change is confined to the shell + providers; the `Connection` seam (D1/D2), the import boundary (no UI package imports `lib/ble`, CON-8), Riverpod (ADR-0007), and every §1A.3 rejection are unchanged.

Unchanged rejection list, seam, and layering as in [ADR-0009](0009-runtime-connection-manager.md)/[ADR-0010](0010-working-loop-in-memory-document.md).

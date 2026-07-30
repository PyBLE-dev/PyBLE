# ADR 0014 — Blocks uses a focused, canvas-first landscape workspace

**Status:** Accepted (2026-07-28). Supersedes only responsive-placement item 8
of [ADR-0013](0013-clean-room-blockly-one-way-file-backed.md). The one-way
workspace model, correlated bridge, file-backed actions, offline assets,
toolbox, and persistence boundary in ADR-0013 remain unchanged. Extends
[ADR-0008](0008-signal-design-system.md) (Signal visual system) and
[ADR-0011](0011-connection-gated-shell.md) (the connected IDE shell).

## Context

ADR-0013 made Blocks reachable in landscape by placing it in the text
workbench's narrow secondary pane. Visual validation on a physical tablet showed
that this preserved too many simultaneous surfaces: Files, Editor, Pins, a
full-height console strip, Blocks action/status chrome, and the Blockly canvas
all competed for the same landscape viewport. Portrait was already effective
because Blocks received a full-width stacked surface.

The corrected layout must:

- keep the connected app's identity, connection state, and recovery controls;
- give the visual workspace enough room for its toolbox and canvas;
- keep generated Python inspectable without making it a permanent tax at
  narrower widths;
- avoid duplicate Run controls with different source ownership;
- keep host notices and the console reachable without covering or crushing the
  canvas; and
- retain the serialized workspace when rotation recreates the platform view.

A reference-product review may inform these generic usability observations and
high-level layout behaviors only. It is not a source of implementation material.

## Decision

**Landscape Blocks is a first-class, focused IDE mode, not text-workbench
secondary content.**

1. **Two landscape workbenches.** The connected shell keeps its application
   toolbar and NavigationRail. The default text workbench MAY remain Files |
   Editor/Console | Pin Reference, with Plots joining the secondary host only
   when A-32 supplies a live view. Blocks is a first-class NavigationRail
   destination. Selecting it replaces all three text-workbench panes with one
   focused Blocks workspace below the retained top chrome. Returning to Editor,
   Console, or Files restores the text workbench.

2. **Exactly one Blocks Run.** The application toolbar keeps connection state,
   Disconnect, Stop, and Soft-reboot in focused Blocks mode but hides its
   editor-targeted Run. A Flutter-owned Blocks action strip contains Preview,
   Open in editor, Save, and the sole Blocks Run. That Run retains ADR-0013's
   fresh acknowledged snapshot and `/blocks.py` file-backed behavior. There is
   no second Run in app chrome, the WebView, or another Blocks toolbar.

3. **Canvas-first optional inspector.** Let `W` be usable focused content width
   after the NavigationRail and outer/divider chrome. For a selectable,
   read-only generated-Python inspector width `P ∈ [360 dp, 420 dp]` and
   divider/gutter `G`, it is present only when the remaining Blockly width
   `B = W − P − G` satisfies both `B ≥ 720 dp` and `B / W ≥ 0.60`. If either
   condition fails, the inspector is omitted and Blockly receives all of `W`.
   The host never squeezes Blockly below either bound merely to retain the
   inspector.

4. **Host state stays off the canvas.** Preview/actions and compact
   loading/action/generator notices are Flutter-owned siblings outside the
   WebView. They may relayout the remaining body but never float over the
   editable canvas. A generator notice leaves Blockly editable and source
   actions disabled. A terminal host failure replaces the canvas region with
   the accessible Retry/Start-fresh recovery panel instead of covering an
   interactive platform view.

5. **Console on demand.** Focused Blocks reuses the existing persistent console
   buffer behind a collapsed 48 dp title/toggle row. It expands on explicit user
   request, when Blocks Run begins, or when a new console event arrives. Expanded
   height follows the normal console formula. Expansion relayouts below the
   workspace; it does not overlay Blockly, recreate the WebView, or clear the
   workspace.

6. **Portrait and rotation.** Portrait keeps the existing stacked, full-width
   Blocks destination. Rotation preserves Blocks selection and the serialized
   workspace. If the platform view is recreated, ADR-0013's host-epoch restore
   handshake must publish a fresh revision before Preview/Open/Save/Run
   re-enable. The inspector remains subject to the same width rule and is
   therefore normally absent in portrait.

7. **Clean-room implementation and verification.** The focused mode,
   proportional width rule, and on-demand console are fresh PyBLE high-level
   layout decisions implemented with Signal tokens and PyBLE-authored Flutter
   composition. No third-party product source, assets, DOM/CSS, styling
   implementation, icons, identifiers, strings, or block catalog is copied,
   traced, or shipped. Widget tests assert sole-Run ownership, width behavior,
   notice placement, and console expansion; goldens cover wide and narrower
   landscape plus portrait on iPadOS and Android; integration tests rotate a
   real WebView host and verify workspace restoration.

## Alternatives considered

- **Keep Blocks in the landscape right pane.** Rejected: the permanent Files,
  Editor, Pins, and console surfaces leave too little usable canvas.
- **Show generated Python at every landscape width.** Rejected: inspectability
  does not justify shrinking the primary visual editor below a usable bound.
- **Keep both application and feature Run controls.** Rejected: duplicate
  controls obscure which source is uploaded and can diverge in availability.
- **Overlay notices or console on the WebView.** Rejected: overlays hide an
  interactive canvas, complicate semantics, and make recovery state ambiguous.
- **Copy a reference application's layout implementation or visual assets.**
  Rejected by PyBLE's clean-room and MIT posture. Only generic workflow
  observations may inform a fresh design.

## Consequences

Landscape Blocks gains a clear hierarchy and substantially more canvas space.
Generated Python remains available at genuinely wide sizes and through Preview
at every size. The console becomes less visually dominant while still surfacing
Run output automatically. Shell routing becomes mode-aware, and tests must cover
two landscape width classes plus platform-view restoration across rotation.

## Related

- [PRD §19.1](../specifications/prd.md)
- [App requirements FR-UI-1 and A-31 increment](../specifications/App/specs.md)
- [App TDD §11.2, §13.2, and §15](../specifications/App/TDD.md)
- [Signal design system §7.2, §7.5, and §7.12](../specifications/App/design-system.md)
- [Public roadmap](../ROADMAP.md)

# ADR 0008 — "Signal", the app's visual design system (adaptive Material 3, seed `#2D5BFF`)

**Status:** Accepted (2026-07-02). Establishes the App visual design system that satisfies [specs.md](../specifications/App/specs.md) **FR-UI-6** (clear connection/run state, large touch targets) and **NFR-A11Y-3** (large-font / high-contrast / contrast), under **NFR-COMPAT-1** (iPadOS ↔ Android parity) and **NFR-MAINT-2** (one consistent approach). Builds on [ADR-0007](0007-riverpod-state-management.md) (Riverpod) and [ADR-0003](0003-license-mit.md) (MIT). Token reference: [App/design-system.md](../specifications/App/design-system.md).

## Context

The A-05 shell frame ([app.md §2](../specifications/app.md), [TDD.md §13.2](../specifications/App/TDD.md#132-responsive-layout)) is structurally complete — responsive three-pane/stacked layouts, toolbar + console-strip slots, the read-only pin-reference host, the `Connection` seam — but it is **visually unstyled**. `app/lib/app/app.dart` sets `theme: ThemeData(useMaterial3: true)` with **no seed**, so the app renders in stock Material 3 defaults (baseline purple), there is **no theme or token layer** anywhere under `app/lib/`, and connection/run state is communicated only by ad-hoc `Colors.grey/orange/green/blue` literals inside the shell. The result reads as an unfinished skeleton and does not deliver the "clear state" and polish that **FR-UI-6 / NFR-USE-2** require.

The design direction is an owner decision (not re-litigated here): **"Signal" — a Material 3 Expressive-*leaning*, adaptive theme built from a single brand seed.** This ADR ratifies that direction as the app's design system so the shell (A-05) and every downstream feature package theme against **one** token source rather than inventing local styles.

Two hard product constraints shape the decision:

- **Offline-first.** The IDE must run with no network. Therefore **no runtime- or network-fetched fonts** (no `google_fonts`): the UI font is the Flutter/platform default sans (Roboto), and code/mono surfaces use the platform `monospace` family. This keeps the app fully functional and byte-identical offline and adds **zero** new dependencies.
- **Only stable theming APIs.** Expressiveness is delivered with the component-theming APIs present in the pinned Flutter (3.44 / Dart 3.12): `ColorScheme.fromSeed`, per-component `*ThemeData`, and `ThemeExtension`. The system does **not** depend on any unreleased "Material 3 Expressive" widget APIs — "expressive-leaning" here means generous rounded shapes, pill navigation, rich tonal surfaces, deliberate elevation, and explicit state color, all expressible today.

## Decision

**The PyBLE app adopts "Signal": one adaptive Material 3 design system generated from the brand seed `#2D5BFF` (pyble-blue), shipping a full light *and* dark theme, offline-first with no network fonts.** Concretely:

- A new **`app/lib/theme/`** package is the single design-system home. It holds the Signal tokens — color roles, the connection/run **state** colors, and the spacing / radius / elevation / type / motion scales — plus a `PybleTheme` that builds `light` and `dark` `ThemeData`. `app.dart` wires `theme:` / `darkTheme:` / `themeMode: ThemeMode.system`.
- **Color** comes from `ColorScheme.fromSeed(seedColor: 0xFF2D5BFF, brightness: …)` for **both** brightnesses (default `tonalSpot` variant — chosen for predictable neutrals and contrast; expressiveness comes from shape/elevation/state color, **not** from cranking chroma). No hand-painted per-role hexes; the tonal palette is authoritative for the scheme roles.
- **Connection/run state** is *not* left to the ColorScheme. Four semantic state colors — **disconnected / connecting / ready / running** — are frozen as a `ThemeExtension` (`SignalStateColors`), defined for light, dark, and high-contrast. Per the review fold-in they are used as **graphics** (per-state glyph + always-on pill border + tint fill, each ≥ 3:1), while the pill *label* uses `colorScheme.onSurface` (AA-safe at any hue) — not the low-contrast "state color as text on a same-hue tint" the first draft assumed. A sibling `SignalCodeColors` extension freezes the console streams (stdout/stderr/system) + editor chrome. Error as a *connection state* is deferred (the frozen `ConnState` has four members, no `error`); `ColorScheme.error` still drives destructive/error *actions*. The extensions are the single source the pill, toolbar, console, editor, and every feature surface read — no more `Colors.*` literals.
- **Shape** is expressive-leaning: a rounded radius scale (12–28 px) plus stadium pills for navigation and status; **spacing** is a 4-based scale; **elevation** uses M3 tonal surface containers deliberately rather than heavy shadows; **type** is the M3 type scale on the default sans, with a dedicated `code` style on the platform `monospace` family for editor/console.
- The design system is applied **consistently** (NFR-MAINT-2): surfaces theme through `Theme.of(context)` + the `SignalStateColors` extension only; no surface hard-codes brand or state colors.

The full, implementable token reference — every role, every hex, every component spec — lives in **[App/design-system.md](../specifications/App/design-system.md)** and is frozen with this ADR.

Unchanged by this ADR: the `Connection` seam (**D1**) and no-BLE-binding rule (CON-8, FR-UI-7), the responsive layout contract (FR-UI-1/2/5), the ARB localization path (new user-facing strings ship `en` same-commit; technical identifiers stay ASCII, FR-I18N-4), and the clean-room / no-leak rule.

## Alternatives considered

- **Stay on stock `ThemeData(useMaterial3: true)`.** Rejected: fails FR-UI-6 "clearly communicate state" and the product polish bar; leaves brand identity absent and state color ad-hoc.
- **`google_fonts` / a bundled custom typeface.** Rejected: `google_fonts` fetches at runtime, breaking offline-first; a bundled font adds weight and a license to track for marginal gain over Roboto. The default sans + platform monospace meet the need with zero dependencies.
- **Hand-authored per-role color palette (no `fromSeed`).** Rejected: high-maintenance, easy to drift out of M3 contrast guarantees across light/dark, and redundant when the tonal palette derives a coherent, accessible scheme from one seed.
- **Depend on Material 3 "Expressive" widget APIs.** Rejected: not present/stable in the pinned Flutter; would couple the design system to unreleased surface area. The expressive *look* is achieved with stable shape/elevation/color tokens today.
- **Per-package local styling.** Rejected: violates NFR-MAINT-2 and NFR-COMPAT-1 (parity drift between surfaces/platforms). One `lib/theme/` source keeps every surface and both platforms identical.

## Consequences

**Positive**
- One seed → a coherent, contrast-checked light+dark scheme; brand identity is present everywhere and connection/run state is communicated by frozen semantic colors (FR-UI-6, NFR-USE-2).
- One `lib/theme/` token source keeps every surface and both platforms visually identical (NFR-COMPAT-1, NFR-MAINT-2); feature engineers theme from tokens instead of inventing styles.
- Zero new dependencies; fully offline (no network fonts). Nothing to add to `app/DEPENDENCIES.md`.
- High-contrast / large-font support (NFR-A11Y-3) is a theme concern with a defined home, and state colors are pre-verified for WCAG AA text contrast in both brightnesses.

**Costs / mitigations**
- **Every golden is reseeded.** Adopting Signal changes the pixels of all `app/test/golden/goldens/*.png`. **Mitigation:** goldens are regenerated in the same change with `flutter test --update-goldens test/golden/app_shell_golden_test.dart` and left green; the widget test contract (four visible nav labels, no overflow at the five breakpoints, rebuild-on-ConnState) is preserved, so the reseed is a visual refresh, not a behavior change.
- The team standardizes on the Signal tokens. **Mitigation:** the A-05 shell lands the canonical `lib/theme/` the other engineers copy; state color literals are removed from the shell in the same change.

**Process**
- Spec-first: this ADR and [App/design-system.md](../specifications/App/design-system.md) land in a `[docs]` commit **before** the theme `[red]`/`[green]`, per SDD. The design-system doc is frozen alongside this ADR.
- No new pubspec dependency; the no-network-fonts rule is a standing invariant for the app.
- The reseeded goldens and any **new** user-facing string (each with its `en` ARB entry, same commit) go through the existing golden + locale-parity gates.

## Review fold-in (2026-07-02)

A 6-lens critique panel (testability/a11y, build/i18n, connect-UX, editor/console, files, viz) reviewed the frozen Signal spec. The design-system doc was re-frozen with these decisions; the token package (`app/lib/theme/`) implements them:

- **Reduced-motion is load-bearing.** The connecting/running pulse runs an `AnimationController` only while animations are enabled and holds a static frame under `MediaQuery.disableAnimations` — never a perpetual repeat. This is mandatory so the frozen `pumpAndSettle`-based widget suite does not time out.
- **Dynamic type: min-height, not fixed.** The toolbar and console strip are min-height (grow with text); the console resting height is a formula (≥ 6 code lines, ≈ 176–190 dp) so a short traceback fits. Explicit no-overflow bound: `textScaleFactor 2.0`; cosmetic chrome text clamps ≤ 1.3.
- **Pill accessibility.** Distinct per-state glyph (bluetooth_disabled / bluetooth_searching / check_circle / play_circle) so shape carries state independent of color/motion/text; `onSurface` label; always-on state-color border; `Semantics` label ("Connection status: {state}"); `ValueKey('connStatusPill')`. Contrast is asserted by a machine-checkable `app/test/theme/` test (author: app-test-author), not prose.
- **Monospace correctness on Apple.** `SignalType.code` leads its fallback with `Menlo` (guaranteed on iOS/iPadOS), then Android `monospace`; `RobotoMono`/`Consolas` removed. Never satisfied by `google_fonts`; a future guaranteed glyph is a bundled asset (offline).
- **Console tokens.** stdout/stderr/system + gutter/active-line/selection frozen in `SignalCodeColors`; the code well (editor field + console body) is one tonal tier (`surfaceContainerLowest`).
- **Toolbar UX.** Connect/Disconnect toggle (no connect dead-end); Run emphasized only in `ready`, Stop the sole error accent only in `running`.
- **Empty-state tone.** `SurfacePlaceholder` badge tint is a `SurfaceTone` parameter (action/informational/neutral) — Connect=action, pin-reference=informational (CON-7), others neutral. Files has two empty states (disconnected vs connected-empty).
- **Frozen component contracts for downstream:** file-list row + read-only row, transfer/CRC status, right-pane segmented switcher (landscape-only at M1), path/breadcrumb, multi-select bar, truncation banner. The categorical plot series palette is **delegated** to app-viz-engineer under stated CVD/parity constraints (fenced off from the state hues).

**Consequence — dark is gated at M1 (change from the original "may be added"):** the golden parity matrix is light **and** dark across all 5 surfaces. Goldens assert layout parity only (box font); real glyph/metric parity (incl. `Menlo` vs Android `monospace`) is a HIL/manual check. High-contrast is now implemented (`highContrastTheme`/`highContrastDarkTheme` via `contrastLevel: 1.0`), not a phantom gate; its goldens may be added but are not required at M1.

## Related

- Token reference frozen with this ADR: [App/design-system.md](../specifications/App/design-system.md).
- Satisfies [specs.md](../specifications/App/specs.md) **FR-UI-6**, **NFR-USE-2**, **NFR-A11Y-3**; under **NFR-COMPAT-1**, **NFR-MAINT-2**. Realizes [TDD.md §13.2](../specifications/App/TDD.md#132-responsive-layout) (responsive layout) visually.
- Builds on [ADR-0007](0007-riverpod-state-management.md) (Riverpod state seam) and [ADR-0003](0003-license-mit.md) (MIT); brand naming per [ADR-0004](0004-name-pyble.md).
- Consumed first by App story **A-05** (shell + state + theme foundation).

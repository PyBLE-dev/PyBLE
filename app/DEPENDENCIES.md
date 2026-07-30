# PyBLE app — dependency ledger (BLD-2)

> Governance record for the single Flutter package at `app/`. This is the
> human-authored rationale ledger; the machine-generated notice bundle
> (`THIRD_PARTY_LICENSES`, in-app Open-Source Notices — IF-6/BLD-6) is derived
> mechanically from the resolved set below at release time.
>
> This file lives under `app/` (never the repo root — GOLDEN RULE) and is a
> `.md`, so it is exempt from the SPDX-header and no-leak gates by extension.

## Policy

- **Permissive only.** Every dependency — direct **and** transitive — must be
  **MIT / BSD-2-Clause / BSD-3-Clause / Apache-2.0** (or another MIT-compatible
  permissive licence). Copyleft (GPL/LGPL/MPL) is rejected. PyBLE ships MIT
  (CON-6); no dependency may encumber that.
- **Recorded rationale + minimum version.** Each direct dependency below carries
  a rationale and a minimum (constraint) version.
- **Tracked lockfile.** `app/pubspec.lock` is committed; CI resolves against it
  with `flutter pub get --enforce-lockfile` and builds/tests from the pinned
  versions (BLD-2). A resolved-version change is a reviewable diff.
- **Minimal governed set (S1).** Only the dependencies required by the current
  sprint are admitted. New dependencies are added in the sprint that needs them,
  each with a ledger row + rationale.

Toolchain pin: **Flutter 3.44.1 (stable)** / Dart SDK `^3.12.1` (see
`pubspec.yaml`).

## Direct dependencies

| Package | Kind | Constraint | Resolved | SPDX | Rationale |
|---|---|---|---|---|---|
| `flutter` | runtime (SDK) | Flutter SDK | 3.44.1 | BSD-3-Clause | The app framework. One codebase targets iPadOS + Android (BLD-1); BLE-only, so no web/desktop targets are wired. |
| `flutter_localizations` | runtime (SDK) | Flutter SDK | 3.44.1 | BSD-3-Clause | The ARB/`gen-l10n` runtime + the `GlobalMaterial/Widgets/Cupertino` localization delegates (X-12). Activates `generate: true` (`app/l10n.yaml` → `AppLocalizations`) and is wired into `MaterialApp` at the shell-string migration (FR-I18N-1..5, BLD-5). Ships with the Flutter SDK (no separate version). |
| `flutter_riverpod` | runtime | `^2.6.1` | 2.6.1 | MIT | The single declarative state-management approach fixed by [ADR-0007](../docs/decisions/0007-riverpod-state-management.md) (NFR-MAINT-2). The one `Connection` is injected at a single `ProviderScope` root and read-only-derived downstream (TDD D1/D3). A 3.x major bump requires a new ledger row + rationale. |
| `flutter_blue_plus` | runtime | `^1.35.0` | 1.36.8 | BSD-3-Clause | The BLE transport (A-02; FR-BLE-1/2/3/5). The **sole** importer lives under `lib/ble/`; no other layer may import it (enforced by `tools/ci/import_boundary.sh`, CON-8). Min 1.35.0 is the floor carrying the GATT service-filtered scan + `requestMtu(247)` + write-without-response API the `lib/ble` adapter binds to. It is a **federated** plugin: it hard-depends on all platform backends (`_android`/`_darwin`/`_linux`/`_web`); only the Android + iOS (`_darwin`) backends compile into PyBLE's shipped targets — see the **copyleft carve-out** under the transitive table. |
| `intl` | runtime | `^0.20.2` | 0.20.2 | BSD-3-Clause | The ARB message runtime consumed by the generated `AppLocalizations` (X-12). The constraint is reconciled to the exact `intl` the pinned `flutter_localizations` (Flutter 3.44.1) admits — 0.20.2. |
| `package_info_plus` | runtime | `^10.2.1` | 10.2.1 | BSD-3-Clause | The sole `lib/app/app_build_info.dart` adapter reads the actual installed iOS/Android version and build number for the X-11 About page (FR-ABOUT-3). It is never imported by `lib/pble`; static ASCII `kAppVersion` remains the PBLE/1 HELLO identity. Min 10.2.1 supports PyBLE's pinned Flutter 3.44.1, Dart 3.12.1, iOS 13, Java 17, AGP 9.0.1, and Gradle 9.1 toolchain. |
| `webview_flutter` | runtime | `^4.14.1` | 4.14.1 | BSD-3-Clause | The offline platform-WebView host for the pinned Blockly runtime (A-31, ADR-0013). Min 4.14.1 matches PyBLE's Android 24 / iOS 13 platform floors and supplies `loadFlutterAsset`, JavaScript channels, and navigation delegates. Its sole importer is `lib/blocks/`; generated source and board actions stay in Dart behind the neutral `Connection` seam. |
| `flutter_test` | dev (SDK) | Flutter SDK | 3.44.1 | BSD-3-Clause | Widget/unit/golden test harness; the substrate for the G1 suites (NFR-MAINT-4). |
| `integration_test` | dev (SDK) | Flutter SDK | 3.44.1 | BSD-3-Clause | On-device Android/iPadOS parity coverage for the real Blockly platform WebView, local asset load, JavaScript bridge, generated Python, and file-backed actions (A-31). Ships with the Flutter SDK and is never part of a release build. |
| `flutter_lints` | dev | `^6.0.0` | 6.0.0 | BSD-3-Clause | Recommended Flutter lint set, activated via `analysis_options.yaml`; the static-analysis floor for the app CI gate. Toolchain-default major for Flutter 3.44.1. |

## Transitive dependencies (resolved by the lockfile)

All are pulled in by the direct dependencies above; PyBLE declares none of them
directly. Every one is permissive and MIT-compatible (verified against the
`LICENSE` file shipped in each package), **except** the two `‡`-marked `bluez` /
`dbus` packages — see the copyleft carve-out below the table.

| Package | Resolved | SPDX |
|---|---|---|
| `args` | 2.7.0 | BSD-3-Clause |
| `async` | 2.13.1 | BSD-3-Clause |
| `bluez` `‡` | 0.8.3 | MPL-2.0 |
| `boolean_selector` | 2.1.2 | BSD-3-Clause |
| `characters` | 1.4.1 | BSD-3-Clause |
| `clock` | 1.1.2 | Apache-2.0 |
| `collection` | 1.19.1 | BSD-3-Clause |
| `dbus` `‡` | 0.7.14 | MPL-2.0 |
| `fake_async` | 1.3.3 | Apache-2.0 |
| `ffi` | 2.2.0 | BSD-3-Clause |
| `ffi_leak_tracker` | 0.1.2 | BSD-3-Clause |
| `file` | 7.0.1 | BSD-3-Clause |
| `flutter_blue_plus_android` | 7.0.4 | BSD-3-Clause |
| `flutter_blue_plus_darwin` | 7.0.3 | BSD-3-Clause |
| `flutter_blue_plus_linux` | 7.0.3 | BSD-3-Clause |
| `flutter_blue_plus_platform_interface` | 7.0.0 | BSD-3-Clause |
| `flutter_blue_plus_web` | 7.0.2 | BSD-3-Clause |
| `flutter_driver` | (Flutter SDK) | BSD-3-Clause |
| `flutter_web_plugins` | (Flutter SDK) | BSD-3-Clause |
| `fuchsia_remote_debug_protocol` | (Flutter SDK) | BSD-3-Clause |
| `http` | 1.6.0 | BSD-3-Clause |
| `http_parser` | 4.1.2 | BSD-3-Clause |
| `leak_tracker` | 11.0.2 | BSD-3-Clause |
| `leak_tracker_flutter_testing` | 3.0.10 | BSD-3-Clause |
| `leak_tracker_testing` | 3.0.2 | BSD-3-Clause |
| `lints` | 6.1.0 | BSD-3-Clause |
| `matcher` | 0.12.19 | BSD-3-Clause |
| `material_color_utilities` | 0.13.0 | Apache-2.0 |
| `meta` | 1.18.0 | BSD-3-Clause |
| `package_info_plus_platform_interface` | 4.1.0 | BSD-3-Clause |
| `path` | 1.9.1 | BSD-3-Clause |
| `petitparser` | 7.0.2 | MIT |
| `platform` | 3.1.6 | BSD-3-Clause |
| `plugin_platform_interface` | 2.1.8 | BSD-3-Clause |
| `process` | 5.0.5 | BSD-3-Clause |
| `riverpod` | 2.6.1 | MIT |
| `rxdart` | 0.28.0 | Apache-2.0 |
| `sky_engine` | (Flutter SDK) | BSD-3-Clause |
| `source_span` | 1.10.2 | BSD-3-Clause |
| `stack_trace` | 1.12.1 | BSD-3-Clause |
| `state_notifier` | 1.0.0 | MIT |
| `stream_channel` | 2.1.4 | BSD-3-Clause |
| `string_scanner` | 1.4.1 | BSD-3-Clause |
| `sync_http` | 0.3.1 | BSD-3-Clause |
| `term_glyph` | 1.2.2 | BSD-3-Clause |
| `test_api` | 0.7.11 | BSD-3-Clause |
| `typed_data` | 1.4.0 | BSD-3-Clause |
| `vector_math` | 2.2.0 | BSD-3-Clause |
| `vm_service` | 15.2.0 | BSD-3-Clause |
| `web` | 1.1.1 | BSD-3-Clause |
| `webview_flutter_android` | 4.13.0 | BSD-3-Clause |
| `webview_flutter_platform_interface` | 2.15.1 | BSD-3-Clause |
| `webview_flutter_wkwebview` | 3.26.0 | BSD-3-Clause |
| `webdriver` | 3.1.0 | Apache-2.0 |
| `win32` | 6.3.0 | BSD-3-Clause |
| `xml` | 6.6.1 | MIT |

### `‡` Copyleft carve-out — `bluez` / `dbus` (MPL-2.0), Linux-only, never shipped

`flutter_blue_plus` is a **federated** plugin that hard-depends on every platform
backend, including `flutter_blue_plus_linux`. That Linux backend transitively
pulls `bluez` → `dbus`, both **MPL-2.0** (weak, file-level copyleft) — which the
policy above otherwise rejects. This is admitted under a bounded carve-out:

- **Never built, never distributed.** PyBLE ships **iPadOS + Android only**
  (BLD-1); no Linux/desktop or web target is wired. At build time only the
  Android (`flutter_blue_plus_android`) and iOS (`flutter_blue_plus_darwin`)
  backends compile in. `flutter_blue_plus_linux` and its `bluez`/`dbus` deps
  are **excluded from every shipped artifact**, so their MPL-2.0 files are not
  distributed and do not touch PyBLE's MIT release.
- **Cannot be pruned in `pubspec`.** `flutter_blue_plus` pins the Linux backend
  as a non-optional dependency; `pub` has no mechanism to drop one endorsed
  federated implementation without forking the plugin. Their presence in
  `pubspec.lock` is a resolution artifact, not a shipped dependency.
- **MPL-2.0 is file-scoped.** It obligates sharing modifications to the MPL
  files themselves; it imposes no terms on the larger combined work. PyBLE
  modifies none of these files, so no obligation attaches.
- **Notices are per-platform.** The mechanical `THIRD_PARTY_LICENSES` / in-app
  Open-Source Notices bundle (IF-6/BLD-6, X-11) is generated from the
  *per-target shipped* set (Android/iOS), which excludes `bluez`/`dbus`.

> **Requires app-architect ratification.** This carve-out relaxes the strict
> "transitive copyleft is rejected" wording for two non-shipped, unmodified,
> Linux-only backend deps. Flagged for the milestone parity/DoD sign-off; not
> self-certified.

## Vendored upstream (git submodules, not pub packages)

| Upstream | Path | Pin | SPDX | Rationale |
|---|---|---|---|---|
| `RaspberryPiFoundation/blockly` | `app/upstream/blockly` | `blockly-v13.1.0` (`f4ad3f511`) | Apache-2.0 | Source for the A-31 (S8) Blockly block editor's WebView asset bundle (FR-BLOCKS-1..4, PRD §9.8). **Pristine** — never edited in place (the same pinned-upstream discipline as `firmware/upstream/micropython`); the built assets are generated from this pin when A-31 starts. PyBLE records the repository owner declared by the pinned source itself (clean-room: its own fork/version choice, no third-party block sets or pedagogy). Apache-2.0 attribution ships in `THIRD_PARTY_LICENSES` + the in-app notices screen (X-11, PRD §17.2). Version bumps are a reviewable `.gitmodules`/ledger diff. |

## Deferred (NOT admitted in S1)

Admitted only in the sprint that needs them, each with its own ledger row +
rationale when added:

| Package | Sprint / story | Purpose |
|---|---|---|
| `drift`, `sqlite3` | S5 / A-24 | Local persistence. |
| `fl_chart` | later | Plotting surface. |
| direct `http` / `dio` client | later | Network fetch for the import flow. (`http` is currently transitive through `package_info_plus`, but PyBLE imports no network client for About and performs no metadata network request.) |
| `go_router` | — | Not planned for S1; navigation is index-based via a Riverpod `StateProvider` + `IndexedStack`. |

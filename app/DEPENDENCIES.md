# PyBLE app — dependency ledger (BLD-2)

> Governance record for the single Flutter package at `app/`. This is the
> human-authored rationale ledger; the machine-generated notice bundle
> (`THIRD_PARTY_LICENSES`, in-app Open-Source Notices — IF-6/BLD-6) is derived
> mechanically from the resolved set below at release time.
>
> This file lives under `app/` (never the repo root — GOLDEN RULE) and is a
> `.md`, so it is exempt from the SPDX-header and no-leak gates by extension.

## Policy

- **Permissive by default; exceptions are owner-ratified and package-specific.**
  Direct and transitive dependencies must normally be **MIT / BSD-2-Clause /
  BSD-3-Clause / Apache-2.0** (or another MIT-compatible permissive licence).
  GPL/LGPL and unknown licences are rejected. MPL is rejected unless an
  accepted decision explicitly names the exact package, shipped scope, and
  notice/source obligations. [ADR-0012](../docs/decisions/0012-flutter-code-editor-behind-editorsurface.md)
  is that owner ratification for unmodified `autotrie` 2.0.0 only; it does not
  relicense PyBLE's MIT source or admit other copyleft dependencies.
- **Recorded rationale + version policy.** Each direct dependency below carries
  a rationale and either a minimum compatible version or an exact pin.
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
| `flutter_code_editor` | runtime | `0.3.5` (exact) | 0.3.5 | Apache-2.0 AND MIT | The default rich Python editor behind PyBLE's app-owned `EditorSurface` seam (A-20, [ADR-0012](../docs/decisions/0012-flutter-code-editor-behind-editorsurface.md)). Exact pin because upstream is dormant and PyBLE owns the Tab/smart-punctuation safeguards plus the live plain-field fallback. The package `LICENSE` contains Apache-2.0 for the package and retains the MIT grant for its `code_field` ancestry. Optional network, error, find, and autocomplete UI stays disabled. Its unavoidable shipped `autotrie` dependency is covered by the owner-ratified `†` exception below. |
| `flutter_localizations` | runtime (SDK) | Flutter SDK | 3.44.1 | BSD-3-Clause | The ARB/`gen-l10n` runtime + the `GlobalMaterial/Widgets/Cupertino` localization delegates (X-12). Activates `generate: true` (`app/l10n.yaml` → `AppLocalizations`) and is wired into `MaterialApp` at the shell-string migration (FR-I18N-1..5, BLD-5). Ships with the Flutter SDK (no separate version). |
| `flutter_riverpod` | runtime | `^2.6.1` | 2.6.1 | MIT | The single declarative state-management approach fixed by [ADR-0007](../docs/decisions/0007-riverpod-state-management.md) (NFR-MAINT-2). The one `Connection` is injected at a single `ProviderScope` root and read-only-derived downstream (TDD D1/D3). A 3.x major bump requires a new ledger row + rationale. |
| `flutter_blue_plus` | runtime | `^1.35.0` | 1.36.8 | BSD-3-Clause | The BLE transport (A-02; FR-BLE-1/2/3/5). The **sole** importer lives under `lib/ble/`; no other layer may import it (enforced by `tools/ci/import_boundary.sh`, CON-8). Min 1.35.0 is the floor carrying the GATT service-filtered scan + `requestMtu(247)` + write-without-response API the `lib/ble` adapter binds to. It is a **federated** plugin: it hard-depends on all platform backends (`_android`/`_darwin`/`_linux`/`_web`); only the Android + iOS (`_darwin`) backends compile into PyBLE's shipped targets — see the **copyleft carve-out** under the transitive table. |
| `intl` | runtime | `^0.20.2` | 0.20.2 | BSD-3-Clause | The ARB message runtime consumed by the generated `AppLocalizations` (X-12). The constraint is reconciled to the exact `intl` the pinned `flutter_localizations` (Flutter 3.44.1) admits — 0.20.2. |
| `package_info_plus` | runtime | `^10.2.1` | 10.2.1 | BSD-3-Clause | The sole `lib/app/app_build_info.dart` adapter reads the actual installed iOS/Android version and build number for the X-11 About page (FR-ABOUT-3). It is never imported by `lib/pble`; static ASCII `kAppVersion` remains the PBLE/1 HELLO identity. Min 10.2.1 supports PyBLE's pinned Flutter 3.44.1, Dart 3.12.1, iOS 15, Java 17, AGP 9.0.1, and Gradle 9.1 toolchain. |
| `http` | runtime | `^1.6.0` | 1.6.0 | BSD-3-Clause | The bounded public GitHub REST client for the connected A-33 subset ([ADR-0040](../docs/decisions/0040-sha-pinned-connected-github-import.md)). The direct dependency is confined to `lib/github_import/`'s production composition point and `GithubRepositoryClient`; all feature consumers bind to the neutral `GithubApi` seam. The adapter accepts only canonical public repository input, sends no credential or user source, permits requests only to exact HTTPS host `api.github.com`, disables redirects, pins every browse to a full commit SHA, and bounds time and response bodies. Min 1.6.0 supplies the abortable request surface used by the cancellation contract on the pinned Dart/Flutter toolchain. |
| `highlight` | runtime | `^0.7.0` | 0.7.0 | MIT | Python grammar data consumed directly by `lib/editor`'s rich adapter (A-20). It also appears in `flutter_code_editor`'s closure, but PyBLE's direct import makes the dependency and compatible minimum explicit under BLD-2. |
| `webview_flutter` | runtime | `^4.14.1` | 4.14.1 | BSD-3-Clause | The offline platform-WebView host for the pinned Blockly runtime (A-31, ADR-0013). Min 4.14.1 is compatible with PyBLE's Android 24 / iOS 15 platform floors and supplies `loadFlutterAsset`, JavaScript channels, and navigation delegates. Its sole importer is `lib/blocks/`; generated source and board actions stay in Dart behind the neutral `Connection` seam. |
| `drift` | runtime | `^2.35.3` | 2.35.3 | MIT | ADR-0048 bounded current-text recovery. Typed atomic SQLite transactions and owned background native executor; no second persistence backend. |
| `sqlite3` | runtime | `3.5.0` (exact) | 3.5.0 | MIT | Native SQLite bindings/build hooks used by Drift; exact compatibility ceiling for Flutter 3.44.1's pinned `meta` 1.18.0. Later sqlite3 releases require newer hooks/meta; no dependency override is used. SQLite itself is public domain; default upstream SQLite build, no sqlite3mc/encryption fork. |
| `crypto` | runtime | `^3.0.8` | 3.0.8 | BSD-3-Clause | Exact UTF-8 SHA-256 identity checks for local recovery; accidental corruption detection, never board authority or authenticity. Promoted from transitive to explicit direct dependency. |
| `path_provider` | runtime | `^2.1.6` | 2.1.6 | BSD-3-Clause | Resolves the app-private persistent Application Support directory for the single Drift store. No temp/cache/external storage, source upload or remote sync. |
| `drift_dev` | dev | `^2.35.2` | 2.35.2 | MIT | Typed table generation and initial v1 schema export; build-time only. |
| `build_runner` | dev | `^2.15.1` | 2.15.1 | BSD-3-Clause | Reproducible Drift source generation. Resolved with the pinned SDK/meta without overrides; build-time only. |
| `flutter_test` | dev (SDK) | Flutter SDK | 3.44.1 | BSD-3-Clause | Widget/unit/golden test harness; the substrate for the G1 suites (NFR-MAINT-4). |
| `integration_test` | dev (SDK) | Flutter SDK | 3.44.1 | BSD-3-Clause | On-device Android/iPadOS parity coverage for the real Blockly platform WebView, local asset load, JavaScript bridge, generated Python, and file-backed actions (A-31). Ships with the Flutter SDK and is never part of a release build. |
| `flutter_lints` | dev | `^6.0.0` | 6.0.0 | BSD-3-Clause | Recommended Flutter lint set, activated via `analysis_options.yaml`; the static-analysis floor for the app CI gate. Toolchain-default major for Flutter 3.44.1. |

## Transitive dependencies (resolved by the lockfile)

All are pulled in by the direct dependencies above; PyBLE declares none of them
directly. Every one is permissive and MIT-compatible (verified against the
`LICENSE` file shipped in the exact locally resolved package), **except** the
`†`-marked shipped `autotrie` package and the two `‡`-marked Linux-only
`bluez` / `dbus` packages. Their distinct copyleft treatments are recorded
below the table.

| Package | Resolved | SPDX |
|---|---|---|
| `args` | 2.7.0 | BSD-3-Clause |
| `async` | 2.13.1 | BSD-3-Clause |
| `autotrie` `†` | 2.0.0 | MPL-2.0 |
| `bluez` `‡` | 0.8.3 | MPL-2.0 |
| `boolean_selector` | 2.1.2 | BSD-3-Clause |
| `characters` | 1.4.1 | BSD-3-Clause |
| `charcode` | 1.4.0 | BSD-3-Clause |
| `clock` | 1.1.2 | Apache-2.0 |
| `collection` | 1.19.1 | BSD-3-Clause |
| `dbus` `‡` | 0.7.14 | MPL-2.0 |
| `equatable` | 2.1.0 | MIT |
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
| `flutter_highlight` | 0.7.0 | MIT |
| `flutter_web_plugins` | (Flutter SDK) | BSD-3-Clause |
| `fuchsia_remote_debug_protocol` | (Flutter SDK) | BSD-3-Clause |
| `hive` | 2.2.3 | Apache-2.0 |
| `http_parser` | 4.1.2 | BSD-3-Clause |
| `leak_tracker` | 11.0.2 | BSD-3-Clause |
| `leak_tracker_flutter_testing` | 3.0.10 | BSD-3-Clause |
| `leak_tracker_testing` | 3.0.2 | BSD-3-Clause |
| `linked_scroll_controller` | 0.2.0 | BSD-3-Clause |
| `lints` | 6.1.0 | BSD-3-Clause |
| `matcher` | 0.12.19 | BSD-3-Clause |
| `material_color_utilities` | 0.13.0 | Apache-2.0 |
| `meta` | 1.18.0 | BSD-3-Clause |
| `mocktail` | 1.0.5 | MIT |
| `package_info_plus_platform_interface` | 4.1.0 | BSD-3-Clause |
| `path` | 1.9.1 | BSD-3-Clause |
| `petitparser` | 7.0.2 | MIT |
| `platform` | 3.1.6 | BSD-3-Clause |
| `plugin_platform_interface` | 2.1.8 | BSD-3-Clause |
| `process` | 5.0.5 | BSD-3-Clause |
| `riverpod` | 2.6.1 | MIT |
| `rxdart` | 0.28.0 | Apache-2.0 |
| `scrollable_positioned_list` | 0.3.8 | BSD-3-Clause |
| `sky_engine` | (Flutter SDK) | BSD-3-Clause |
| `source_span` | 1.10.2 | BSD-3-Clause |
| `stack_trace` | 1.12.1 | BSD-3-Clause |
| `state_notifier` | 1.0.0 | MIT |
| `stream_channel` | 2.1.4 | BSD-3-Clause |
| `string_scanner` | 1.4.1 | BSD-3-Clause |
| `sync_http` | 0.3.1 | BSD-3-Clause |
| `term_glyph` | 1.2.2 | BSD-3-Clause |
| `test_api` | 0.7.11 | BSD-3-Clause |
| `tuple` | 2.0.2 | BSD-2-Clause |
| `typed_data` | 1.4.0 | BSD-3-Clause |
| `url_launcher` | 6.3.2 | BSD-3-Clause |
| `url_launcher_android` | 6.3.32 | BSD-3-Clause |
| `url_launcher_ios` | 6.4.1 | BSD-3-Clause |
| `url_launcher_linux` | 3.2.2 | BSD-3-Clause |
| `url_launcher_macos` | 3.2.5 | BSD-3-Clause |
| `url_launcher_platform_interface` | 2.3.2 | BSD-3-Clause |
| `url_launcher_web` | 2.4.3 | BSD-3-Clause |
| `url_launcher_windows` | 3.1.5 | BSD-3-Clause |
| `vector_math` | 2.2.0 | BSD-3-Clause |
| `vm_service` | 15.2.0 | BSD-3-Clause |
| `web` | 1.1.1 | BSD-3-Clause |
| `webview_flutter_android` | 4.13.0 | BSD-3-Clause |
| `webview_flutter_platform_interface` | 2.15.1 | BSD-3-Clause |
| `webview_flutter_wkwebview` | 3.26.0 | BSD-3-Clause |
| `webdriver` | 3.1.0 | Apache-2.0 |
| `win32` | 6.3.0 | BSD-3-Clause |
| `xml` | 6.6.1 | MIT |

### Recovery dependency additions (PYB-006.2)

These additional locked transitive packages were checked against the exact package
`LICENSE` files on 31 October 2026. Build generators, analyzer and their helper
packages are development inputs; platform adapters compile only for their target.
The original transitive table plus this table covers the resolved graph.

| Package | Resolved | SPDX |
|---|---|---|
| `_fe_analyzer_shared` | 100.0.0 | BSD-3-Clause |
| `analyzer` | 13.0.0 | BSD-3-Clause |
| `build` | 4.0.7 | BSD-3-Clause |
| `build_config` | 1.3.3 | BSD-3-Clause |
| `build_daemon` | 4.1.7 | BSD-3-Clause |
| `built_collection` | 5.1.2 | BSD-3-Clause |
| `built_value` | 8.13.0 | BSD-3-Clause |
| `checked_yaml` | 2.0.4 | BSD-3-Clause |
| `cli_util` | 0.6.0 | BSD-3-Clause |
| `code_assets` | 1.2.1 | BSD-3-Clause |
| `convert` | 3.1.2 | BSD-3-Clause |
| `dart_style` | 3.1.9 | BSD-3-Clause |
| `fixnum` | 1.1.1 | BSD-3-Clause |
| `glob` | 2.2.0 | BSD-3-Clause |
| `graphs` | 2.3.2 | BSD-3-Clause |
| `hooks` | 2.0.2 | BSD-3-Clause |
| `http_multi_server` | 3.2.3 | BSD-3-Clause |
| `io` | 1.1.0 | BSD-3-Clause |
| `jni` | 1.1.1 | BSD-3-Clause |
| `jni_flutter` | 1.0.4+1 | BSD-3-Clause |
| `jni_util` | 1.0.0 | BSD-3-Clause |
| `json_annotation` | 4.12.0 | BSD-3-Clause |
| `logging` | 1.3.0 | BSD-3-Clause |
| `mime` | 2.1.0 | BSD-3-Clause |
| `native_toolchain_c` | 0.19.2 | BSD-3-Clause |
| `objective_c` | 9.5.0 | BSD-3-Clause |
| `package_config` | 2.2.0 | BSD-3-Clause |
| `path_provider_android` | 2.3.1 | BSD-3-Clause |
| `path_provider_foundation` | 2.6.0 | BSD-3-Clause |
| `path_provider_linux` | 2.2.2 | BSD-3-Clause |
| `path_provider_platform_interface` | 2.1.3 | BSD-3-Clause |
| `path_provider_windows` | 2.3.0 | BSD-3-Clause |
| `pool` | 1.5.3 | BSD-3-Clause |
| `pub_semver` | 2.2.1 | BSD-3-Clause |
| `pubspec_parse` | 1.7.0 | BSD-3-Clause |
| `recase` | 4.1.0 | BSD-2-Clause |
| `record_use` | 0.6.0 | BSD-3-Clause |
| `shelf` | 1.4.3 | BSD-3-Clause |
| `shelf_web_socket` | 3.0.0 | BSD-3-Clause |
| `source_gen` | 4.2.4 | BSD-3-Clause |
| `sqlparser` | 0.45.1 | MIT |
| `stream_transform` | 2.1.2 | BSD-3-Clause |
| `watcher` | 1.2.1 | BSD-3-Clause |
| `web_socket` | 1.0.1 | BSD-3-Clause |
| `web_socket_channel` | 3.0.3 | BSD-3-Clause |
| `xdg_directories` | 1.1.0 | BSD-3-Clause |
| `yaml` | 3.1.4 | MIT |
| `yaml_edit` | 2.2.4 | BSD-3-Clause |

### `†` Owner-ratified shipped carve-out — `autotrie` 2.0.0 (MPL-2.0)

`flutter_code_editor` constructs its autocomplete index with `autotrie`, even
when PyBLE leaves the package's autocomplete UI disabled. The dependency is
therefore part of the Android and iPadOS app rather than a lockfile-only
platform artifact. Accepted [ADR-0012](../docs/decisions/0012-flutter-code-editor-behind-editorsurface.md)
is the project owner's explicit ratification of this bounded exception:

- **Exact, unmodified scope.** The exception covers only the resolved
  `autotrie` 2.0.0 package required by exactly pinned
  `flutter_code_editor` 0.3.5. PyBLE vendors or modifies none of its files. A
  package/version change or a PyBLE-authored modification requires a fresh
  licence review and decision.
- **File-level boundary.** MPL-2.0 applies to the covered `autotrie` files; it
  does not relicense separate PyBLE-authored files or the app as a whole. The
  downstream `hive` package is Apache-2.0.
- **Distribution obligations remain active.** Release notices must include the
  complete MPL-2.0 text, exact package/version identity, and a durable way to
  obtain the corresponding unmodified source (the locked
  [pub.dev package](https://pub.dev/packages/autotrie/versions/2.0.0) and its
  [recorded upstream repository](https://github.com/AKushWarrior/autotrie)).
  Flutter's generated Pub-package `NOTICES.Z`/`LicenseRegistry` payload (the
  app's `THIRD_PARTY_LICENSES` bundle) must retain this entry on both shipped
  targets. The in-app **Open-source licenses** page reads that payload locally.
- **No general copyleft precedent.** This owner-approved exception does not
  admit another MPL package, GPL/LGPL code, or an unknown licence by analogy.

This is intentionally separate from the `‡` exception below: `autotrie` is
shipped and its MPL obligations apply, while `bluez` / `dbus` are not shipped.

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
| `fl_chart` | later | Plotting surface. |
| `go_router` | — | Not planned for S1; navigation is index-based via a Riverpod `StateProvider` + `IndexedStack`. |

## Recovery build and notice reproduction

- Run `dart run build_runner build` from `app/`, then
  `dart run drift_dev schema dump lib/data/draft_database.dart drift_schemas/`.
  The first generated database source and schema are reviewed and committed;
  `build.yaml` preserves the authored-source SPDX preamble on regeneration.
- Pub-package license texts remain in Flutter's mechanically generated
  `NOTICES.Z` and in-app LicenseRegistry. The SQLite native amalgamation's
  public-domain provenance is separately bundled in
  `assets/licenses/SQLite-PUBLIC-DOMAIN.txt`; PyBLE adds no custom SQLite code.
- The default `sqlite3` build hook obtains its upstream binaries from the
  package's release assets, with the package-pinned SHA-256 checks. No binaries,
  compiler outputs or native signing inputs are committed here.
- The database is `pyble.sqlite` in Application Support. Its `-wal`/`-shm`
  companions belong to the same store. Device/OS backup behavior is external
  to PyBLE's local checkpoint promise; no backup/sync feature is added.

// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

/// PyBLE `lib/localization/` — the intl + ARB localization framework: the `en`
/// scaffold (day one), generated `AppLocalizations`, locale resolution + an
/// optional in-settings override, and the ASCII-identifier convention
/// (technical identifiers are never localized) — see
/// docs/specifications/app.md §2 and FR-I18N-1..5.
///
/// X-12 framework barrel. Re-exports the generated [AppLocalizations] so
/// consumers depend on `package:pyble/localization/localization.dart` rather
/// than the generated path directly. The generated sources under
/// `lib/localization/gen/` are produced by `flutter gen-l10n` from
/// `lib/localization/arb/app_en.arb` (config: `app/l10n.yaml`) — never edited by
/// hand. Feature packages author their own `en` keys in the same commit as their
/// strings (CON-9); the locale-parity gate enforces key parity across locales.
///
/// The optional in-settings locale override (a `LocaleController` backed by the
/// SettingsStore, FR-I18N-5) and the MaterialApp delegate wiring land with the
/// shell-string migration (app-architect [green]); until then the app resolves
/// to the platform-default locale.
library;

export 'gen/app_localizations.dart';

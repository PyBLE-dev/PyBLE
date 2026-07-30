// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

/// PyBLE `lib/theme/` — the "Signal" design-system package (ADR-0008, token
/// reference: docs/specifications/App/design-system.md).
///
/// The SINGLE design-system home: the brand seed, both `ColorScheme`s, the
/// connection/run + code-surface color extensions, the spacing / radius /
/// elevation / motion scales, the custom `code` type role, and the `PybleTheme`
/// that assembles it all into light + dark (+ high-contrast) `ThemeData`.
///
/// Consumers depend on `package:pyble/theme/theme.dart` — not the individual
/// files. This package holds tokens/ThemeData ONLY and contains zero display
/// copy; all user-facing text is passed in from `lib/app` via `AppLocalizations`
/// (so the locale-parity gate, which scans `lib/app`, always covers it).
library;

export 'pyble_theme.dart';
export 'signal_colors.dart';
export 'signal_scales.dart';
export 'signal_type.dart';

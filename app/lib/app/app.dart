// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

/// A-05 — the root application widget. Wraps the responsive [PybleShell] in a
/// `MaterialApp`. The `ProviderScope` (and the [connectionProvider] override
/// that injects the app's [Connection]) lives one level up in `main.dart` /
/// the test harness, so [PybleApp] itself is transport-agnostic (CON-8, D1).
///
/// X-12/S2: the `MaterialApp` registers [AppLocalizations] delegates and lists
/// the supported locales (`en` day-one, CON-9); the app resolves the platform
/// locale by default (FR-I18N-1/5). Every user-facing shell string is sourced
/// from [AppLocalizations] — no display literals remain in the shell.
library;

import 'package:flutter/material.dart';

import 'package:pyble/localization/localization.dart';
import 'package:pyble/theme/theme.dart';

import 'shell.dart';

/// The PyBLE root widget: a `MaterialApp` hosting the responsive shell.
class PybleApp extends StatelessWidget {
  const PybleApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      // The app wordmark is a brand proper noun, sourced from the ARB (rendered
      // verbatim) so the OS task-switcher title follows the localization path.
      onGenerateTitle: (BuildContext context) =>
          AppLocalizations.of(context).appTitle,
      localizationsDelegates: AppLocalizations.localizationsDelegates,
      supportedLocales: AppLocalizations.supportedLocales,
      // "Signal" design system (ADR-0008): one seed → light + dark + high-
      // contrast, adaptive via ThemeMode.system.
      theme: PybleTheme.light,
      darkTheme: PybleTheme.dark,
      highContrastTheme: PybleTheme.highContrastLight,
      highContrastDarkTheme: PybleTheme.highContrastDark,
      themeMode: ThemeMode.system,
      debugShowCheckedModeBanner: false,
      home: const PybleShell(),
    );
  }
}

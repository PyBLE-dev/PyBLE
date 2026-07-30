// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

/// "Signal" theme builder (ADR-0008, design-system.md). Turns the one brand
/// seed into a full light + dark (+ high-contrast) `ThemeData`, applies the
/// component themes from the frozen spec, and registers the [SignalStateColors]
/// and [SignalCodeColors] extensions so every surface themes from
/// `Theme.of(context)` alone.
///
/// Wiring (next phase, `lib/app/app.dart`):
///
/// ```dart
/// MaterialApp(
///   theme: PybleTheme.light,
///   darkTheme: PybleTheme.dark,
///   highContrastTheme: PybleTheme.highContrastLight,
///   highContrastDarkTheme: PybleTheme.highContrastDark,
///   themeMode: ThemeMode.system,
///   ...
/// )
/// ```
///
/// Tokens/ThemeData only — no display copy lives in `lib/theme/`.
library;

import 'package:flutter/material.dart';

import 'signal_colors.dart';
import 'signal_scales.dart';

/// Static access to the four Signal `ThemeData` variants.
abstract final class PybleTheme {
  /// Light theme (normal contrast).
  static ThemeData get light => _build(
    Brightness.light,
    contrastLevel: 0.0,
    stateColors: SignalStateColors.light(),
  );

  /// Dark theme (normal contrast).
  static ThemeData get dark => _build(
    Brightness.dark,
    contrastLevel: 0.0,
    stateColors: SignalStateColors.dark(),
  );

  /// High-contrast light theme (`MediaQuery.highContrast` on iOS "Increase
  /// Contrast"). Uses a `contrastLevel: 1.0` scheme + the stronger state set.
  static ThemeData get highContrastLight => _build(
    Brightness.light,
    contrastLevel: 1.0,
    stateColors: SignalStateColors.highContrastLight(),
  );

  /// High-contrast dark theme.
  static ThemeData get highContrastDark => _build(
    Brightness.dark,
    contrastLevel: 1.0,
    stateColors: SignalStateColors.highContrastDark(),
  );

  static ThemeData _build(
    Brightness brightness, {
    required double contrastLevel,
    required SignalStateColors stateColors,
  }) {
    final ColorScheme scheme = ColorScheme.fromSeed(
      seedColor: kPybleBlue,
      brightness: brightness,
      contrastLevel: contrastLevel,
    );

    final RoundedRectangleBorder buttonShape = RoundedRectangleBorder(
      borderRadius: BorderRadius.circular(SignalRadius.sm),
    );

    return ThemeData(
      useMaterial3: true,
      colorScheme: scheme,

      // Top toolbar / app bar — tonal level 4, no shadow (§4, §7.1).
      appBarTheme: AppBarTheme(
        backgroundColor: scheme.surfaceContainerHighest,
        foregroundColor: scheme.onSurface,
        surfaceTintColor: Colors.transparent,
        elevation: 0,
        scrolledUnderElevation: 0,
      ),

      // Landscape navigation rail — level 4, stadium primaryContainer
      // indicator; M3 defaults already color selected onPrimaryContainer /
      // unselected onSurfaceVariant (§7.2).
      navigationRailTheme: NavigationRailThemeData(
        backgroundColor: scheme.surfaceContainerHighest,
        indicatorColor: scheme.primaryContainer,
        indicatorShape: SignalRadius.stadium,
        labelType: NavigationRailLabelType.all,
        useIndicator: true,
      ),

      // Stacked (portrait/phone) bottom navigation bar — labels always shown
      // (the four-visible-label contract), stadium indicator (§7.3).
      navigationBarTheme: NavigationBarThemeData(
        backgroundColor: scheme.surfaceContainerHighest,
        indicatorColor: scheme.primaryContainer,
        indicatorShape: SignalRadius.stadium,
        labelBehavior: NavigationDestinationLabelBehavior.alwaysShow,
        elevation: 0,
      ),

      // Cards / titled-pane surfaces — tonal, rounded, no shadow (§4, §7.4).
      cardTheme: CardThemeData(
        color: scheme.surfaceContainerLow,
        surfaceTintColor: Colors.transparent,
        elevation: 0,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(SignalRadius.md),
        ),
      ),

      // 1 px hairline separators between tonal tiers (§4).
      dividerTheme: DividerThemeData(
        color: scheme.outlineVariant,
        thickness: 1,
        space: 1,
      ),

      // Icon buttons keep a ≥ 48 dp target (FR-UI-6).
      iconButtonTheme: IconButtonThemeData(
        style: IconButton.styleFrom(minimumSize: const Size(48, 48)),
      ),

      // Primary filled buttons — ≥ 48 dp height, sm radius (§7.8).
      filledButtonTheme: FilledButtonThemeData(
        style: FilledButton.styleFrom(
          minimumSize: const Size(0, 48),
          shape: buttonShape,
        ),
      ),
      outlinedButtonTheme: OutlinedButtonThemeData(
        style: OutlinedButton.styleFrom(
          minimumSize: const Size(0, 48),
          shape: buttonShape,
        ),
      ),
      textButtonTheme: TextButtonThemeData(
        style: TextButton.styleFrom(
          minimumSize: const Size(0, 48),
          shape: buttonShape,
        ),
      ),

      // The two hand-authored semantic color sets (§1.3, §1.4).
      extensions: <ThemeExtension<dynamic>>[
        stateColors,
        SignalCodeColors.from(scheme),
      ],
    );
  }
}

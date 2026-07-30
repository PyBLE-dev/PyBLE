// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

/// "Signal" design-system scales (ADR-0008, docs/specifications/App/design-
/// system.md §2–§4, §6). Spacing, radius, elevation, and motion tokens — the
/// non-color half of the token contract. These are the ONLY sanctioned values;
/// surfaces never hard-code arbitrary paddings, radii, or durations.
///
/// This file (like all of `lib/theme/`) holds tokens ONLY — never display copy.
/// All user-facing text is passed in from `lib/app` via `AppLocalizations`.
library;

import 'package:flutter/material.dart';

/// 4-based spacing scale (§2). dp values.
abstract final class SignalSpacing {
  /// 4 — icon↔label gap, chip inner, tight stacks.
  static const double xs = 4;

  /// 8 — dense control padding, dot↔label in the status pill.
  static const double sm = 8;

  /// 12 — pane title padding, list-row vertical inset, default gap.
  static const double md = 12;

  /// 16 — standard content inset (toolbar sides, pane body, console).
  static const double lg = 16;

  /// 24 — empty-state padding, section separation.
  static const double xl = 24;

  /// 32 — empty-state internal breathing room, large gaps.
  static const double xxl = 32;

  /// 48 — major vertical rhythm on spacious empty states.
  static const double xxxl = 48;
}

/// Expressive-leaning radius scale, 12–28 px band (§3). px values.
abstract final class SignalRadius {
  /// 12 — buttons, text fields, small chips, list-tile hover/selection.
  static const double sm = 12;

  /// 16 — cards, the titled pane wrapper, dialogs' inner blocks.
  static const double md = 16;

  /// 20 — large cards, the empty-state illustration badge, dialogs.
  static const double lg = 20;

  /// 28 — bottom sheets, prominent containers, connect-flow board cards.
  static const double xl = 28;

  /// The stadium shape used for navigation indicators and the status pill
  /// (the "full" radius tier — a true pill, not a fixed px radius).
  static const StadiumBorder stadium = StadiumBorder();
}

/// Deliberate tonal elevation (§4). Expressive-leaning = surface-container
/// tiers, not heavy drop shadows; real shadow dp is reserved for M3 overlays.
abstract final class SignalElevation {
  /// Page background / pane bodies (tonal tier `surface`).
  static const double level0 = 0;

  /// Titled pane wrapper / resting cards (`surfaceContainerLow`).
  static const double level1 = 0;

  /// Console strip title bar (`surfaceContainer`).
  static const double level2 = 0;

  /// Selected/hover states, raised card headers (`surfaceContainerHigh`).
  static const double level3 = 0;

  /// Top toolbar / navigation rail (`surfaceContainerHighest`).
  static const double level4 = 0;

  /// Menus, dialogs, bottom sheets, drag feedback — the one place a real
  /// shadow is used (M3 default + `surfaceTint`).
  static const double overlay = 3;

  /// The resting tonal surface color for [level] (0–4). Elevation is expressed
  /// by surface tier, not shadow: components read their background from here so
  /// the tiers stay consistent across both brightnesses.
  static Color tier(ColorScheme scheme, int level) {
    switch (level) {
      case 0:
        return scheme.surface;
      case 1:
        return scheme.surfaceContainerLow;
      case 2:
        return scheme.surfaceContainer;
      case 3:
        return scheme.surfaceContainerHigh;
      case 4:
      default:
        return scheme.surfaceContainerHighest;
    }
  }
}

/// M3-aligned motion durations and easing (§6).
///
/// The [pulse] animation (connecting/running indicators) MUST be driven by an
/// `AnimationController` that is held on a single static frame when
/// `MediaQuery.of(context).disableAnimations` is true — never a perpetual
/// repeat. That reduced-motion gate is what keeps the existing
/// `pumpAndSettle()`-based widget suite from timing out, and is mandatory at
/// the pill widget (design-system.md §6, §7.6).
abstract final class SignalMotion {
  /// 120 ms — hover/press, ripple, small color fades.
  static const Duration fast = Duration(milliseconds: 120);

  /// 240 ms — surface swap on nav change, pill color transition.
  static const Duration standard = Duration(milliseconds: 240);

  /// 400 ms — layout/pane transitions, bottom-sheet in/out.
  static const Duration emphasized = Duration(milliseconds: 400);

  /// 1200 ms — the connecting/running indicator breathe (opacity 0.55↔1.0),
  /// repeat+reverse, but ONLY while animations are enabled (see class doc).
  static const Duration pulse = Duration(milliseconds: 1200);

  /// Standard easing.
  static const Curve standardCurve = Curves.easeInOutCubic;

  /// Emphasized easing (available in the pinned Flutter 3.44).
  static const Curve emphasizedCurve = Curves.easeInOutCubicEmphasized;
}

// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

/// "Signal" typography (ADR-0008, design-system.md §5). The UI type scale is
/// the stock Material 3 scale on the default sans (Roboto / platform default) —
/// no network or bundled font (offline-first). This file adds only the one
/// custom role the M3 scale lacks: [SignalType.code], the offline monospace
/// style for editor buffers, console output, and verbatim technical
/// identifiers (FR-I18N-4).
///
/// Tokens only — no display copy lives here.
library;

import 'package:flutter/material.dart';

/// The custom code/mono type role and helpers.
abstract final class SignalType {
  /// Monospace text style for code surfaces (editor, console) and any verbatim
  /// technical identifier (including port-defined chip values such as
  /// `esp32-s3`, filesystem paths, and PBLE/1 status names — never localized).
  ///
  /// **Apple-platform correctness (design-system.md §5, folded from review):**
  /// the family list leads with `Menlo` — the guaranteed-installed monospace on
  /// iOS/iPadOS — then the Android generic `monospace`. It deliberately does
  /// NOT name `monospace` first: on iOS/iPadOS the generic can resolve to the
  /// default *proportional* face (breaking code alignment on a first-class
  /// target), whereas `Menlo` always resolves there. On Android `Menlo` is
  /// absent, so resolution falls through to the real `monospace` family.
  ///
  /// The list contains ONLY genuinely-resolvable families (Apple `Menlo`,
  /// Android `monospace`). It must NOT be "completed" with `google_fonts` or
  /// any runtime/network-fetched face — that would break offline-first. If a
  /// guaranteed glyph on iPad ever proves necessary, bundle a mono font as a
  /// local asset and record its license in `app/DEPENDENCIES.md`.
  static const TextStyle code = TextStyle(
    fontFamilyFallback: <String>['Menlo', 'monospace'],
    fontSize: 14,
    height: 1.45,
  );

  /// [code] with the default on-surface color applied — the standard editor /
  /// console body color. Stream/severity coloring is supplied by
  /// `SignalCodeColors` (stdout/stderr/system).
  static TextStyle codeOn(ColorScheme scheme) =>
      code.copyWith(color: scheme.onSurface);
}

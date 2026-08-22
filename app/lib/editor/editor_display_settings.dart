// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

/// Session-wide editor presentation settings.
///
/// A-24 will hydrate this state through the single Drift `SettingsStore`.
/// Until that store exists the value deliberately survives navigation, but not
/// process restart; introducing a second preferences backend would violate D4.
library;

import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

/// Inclusive editor-font bounds and the Signal-code default (FR-EDIT-5).
const double kEditorMinFontSize = 10;
const double kEditorDefaultFontSize = 14;
const double kEditorMaxFontSize = 24;
const double kEditorFontSizeStep = 1;

@immutable
class EditorDisplaySettings {
  const EditorDisplaySettings({this.fontSize = kEditorDefaultFontSize});

  final double fontSize;

  @override
  bool operator ==(Object other) =>
      identical(this, other) ||
      other is EditorDisplaySettings && other.fontSize == fontSize;

  @override
  int get hashCode => fontSize.hashCode;
}

class EditorDisplaySettingsController extends Notifier<EditorDisplaySettings> {
  @override
  EditorDisplaySettings build() => const EditorDisplaySettings();

  void increaseFontSize() => setFontSize(state.fontSize + kEditorFontSizeStep);

  void decreaseFontSize() => setFontSize(state.fontSize - kEditorFontSizeStep);

  /// Applies a finite, whole-point value inside the frozen editor range.
  void setFontSize(double value) {
    final double normalized = value.isFinite
        ? value.roundToDouble().clamp(kEditorMinFontSize, kEditorMaxFontSize)
        : kEditorDefaultFontSize;
    if (normalized == state.fontSize) return;
    state = EditorDisplaySettings(fontSize: normalized);
  }
}

/// Kept alive at the application ProviderScope so zoom survives navigation.
final NotifierProvider<EditorDisplaySettingsController, EditorDisplaySettings>
editorDisplaySettingsProvider =
    NotifierProvider<EditorDisplaySettingsController, EditorDisplaySettings>(
      EditorDisplaySettingsController.new,
    );

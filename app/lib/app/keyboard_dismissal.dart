// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';

const MethodChannel _keyboardChannel = MethodChannel('dev.pyble/keyboard');

/// Requests dismissal of the current window's keyboard, including native
/// WebView fields. Completion does not assert that the keyboard is hidden;
/// layout continues to follow the actual view insets.
Future<void> dismissSoftwareKeyboard() async {
  if (!kIsWeb &&
      (defaultTargetPlatform == TargetPlatform.android ||
          defaultTargetPlatform == TargetPlatform.iOS)) {
    await _keyboardChannel.invokeMethod<void>('dismissKeyboard');
  } else {
    await SystemChannels.textInput.invokeMethod<void>('TextInput.hide');
  }
}

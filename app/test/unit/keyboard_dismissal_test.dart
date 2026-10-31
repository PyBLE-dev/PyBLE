// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

import 'package:flutter/foundation.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:pyble/app/keyboard_dismissal.dart';

void main() {
  testWidgets(
    'a platform without the app native handler uses the Flutter hide request',
    (WidgetTester tester) async {
      tester.testTextInput.log.clear();
      await dismissSoftwareKeyboard();
      expect(
        tester.testTextInput.log.map((call) => call.method),
        contains('TextInput.hide'),
      );
    },
    variant: TargetPlatformVariant(<TargetPlatform>{TargetPlatform.linux}),
  );
}

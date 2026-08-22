// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:pyble/editor/editor.dart';
import 'package:pyble/pble/pble.dart';

import '../support/feature_harness.dart';

void main() {
  testWidgets('Tab indents a multiline selection without deleting source', (
    WidgetTester tester,
  ) async {
    final FakeConnection fake = FakeConnection(initial: ConnState.ready);
    addTearDown(fake.dispose);
    const String source = 'a = 1\nb = 2\nc = 3\n';

    await pumpSurface(tester, const EditorView(), connection: fake);
    containerOf(tester)
        .read(editorDocumentProvider.notifier)
        .openFromBoard(path: '/main.py', content: source);
    await tester.pump();

    final EditableText editable = tester.widget<EditableText>(
      find.byType(EditableText),
    );
    editable.controller.selection = const TextSelection(
      baseOffset: 0,
      extentOffset: 12,
    );
    editable.focusNode.requestFocus();
    await tester.pump();

    await tester.sendKeyEvent(LogicalKeyboardKey.tab);
    await tester.pump();

    expect(
      containerOf(tester).read(editorDocumentProvider).content,
      '  a = 1\n  b = 2\nc = 3\n',
      reason: 'the selected source must be indented, never replaced by spaces',
    );
  });
}

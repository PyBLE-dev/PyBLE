// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:pyble/editor/editor.dart';
import 'package:pyble/pble/pble.dart';

import '../support/feature_harness.dart';
import '../support/recording_connection.dart';

/// Apply each platform edit to the actual current buffer and caret. Replacing
/// the buffer with an expected prefix would hide controller-inserted text.
Future<void> typeCharacters(WidgetTester tester, String source) async {
  final EditableText field = tester.widget<EditableText>(
    find.byType(EditableText),
  );
  field.focusNode.requestFocus();
  await tester.pump();
  await tester.showKeyboard(find.byType(EditableText));
  for (final int rune in source.runes) {
    final String character = String.fromCharCode(rune);
    final TextEditingValue before = field.controller.value;
    tester.testTextInput.updateEditingValue(
      TextEditingValue(
        text: before.text.replaceRange(
          before.selection.start,
          before.selection.end,
          character,
        ),
        selection: TextSelection.collapsed(
          offset: before.selection.start + character.length,
        ),
      ),
    );
    await tester.pump(const Duration(milliseconds: 120));
  }
}

void main() {
  for (final (String, EditorSurfaceBuilder) surface
      in <(String, EditorSurfaceBuilder)>[
        ('rich', richEditorSurfaceBuilder),
        ('plain fallback', plainEditorSurfaceBuilder),
      ]) {
    testWidgets('${surface.$1} preserves paced balanced Python typing', (
      WidgetTester tester,
    ) async {
      final RecordingConnection fake = RecordingConnection(
        initial: ConnState.ready,
      );
      addTearDown(fake.dispose);
      await pumpSurface(
        tester,
        const EditorView(),
        connection: fake,
        extra: <Override>[
          editorSurfaceBuilderProvider.overrideWithValue(surface.$2),
        ],
      );
      const String source = 'import time\nprint(7024)\ntime.sleep(30)\n';
      await typeCharacters(tester, source);

      final EditableText field = tester.widget<EditableText>(
        find.byType(EditableText),
      );
      expect(field.controller.text, source);
      expect(field.controller.selection.baseOffset, source.length);
      expect(containerOf(tester).read(editorDocumentProvider).content, source);
    });

    testWidgets('${surface.$1} preserves typed quotes and nested delimiters', (
      WidgetTester tester,
    ) async {
      final RecordingConnection fake = RecordingConnection(
        initial: ConnState.ready,
      );
      addTearDown(fake.dispose);
      await pumpSurface(
        tester,
        const EditorView(),
        connection: fake,
        extra: <Override>[
          editorSurfaceBuilderProvider.overrideWithValue(surface.$2),
        ],
      );
      const String source = 'print({"values": [1, (2, 3)], "label": \'ok\'})\n';
      await typeCharacters(tester, source);
      expect(containerOf(tester).read(editorDocumentProvider).content, source);
    });

    testWidgets('${surface.$1} preserves balanced whole-text paste', (
      WidgetTester tester,
    ) async {
      final RecordingConnection fake = RecordingConnection(
        initial: ConnState.ready,
      );
      addTearDown(fake.dispose);
      await pumpSurface(
        tester,
        const EditorView(),
        connection: fake,
        extra: <Override>[
          editorSurfaceBuilderProvider.overrideWithValue(surface.$2),
        ],
      );
      const String source = 'print({"values": [1, (2, 3)], "label": \'ok\'})\n';
      await tester.enterText(find.byType(EditableText), source);
      await tester.pump();
      final EditableText field = tester.widget<EditableText>(
        find.byType(EditableText),
      );
      expect(field.controller.text, source);
      expect(field.controller.selection.baseOffset, source.length);
      expect(containerOf(tester).read(editorDocumentProvider).content, source);
    });
  }
}

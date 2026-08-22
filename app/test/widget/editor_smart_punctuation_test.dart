// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.
//
// A-25 — end-to-end cover through the REAL EditorView widget.
//
// The unit tests pin the formatter in isolation; this pins its observable
// guarantee through both EditorSurface implementations, independent of where
// each adapter intercepts TextEditingValue updates.

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:pyble/editor/editor.dart';
import 'package:pyble/pble/pble.dart';

import '../support/feature_harness.dart';
import '../support/recording_connection.dart';

void main() {
  testWidgets('both editor adapters preserve the typing-safety configuration', (
    WidgetTester tester,
  ) async {
    for (final EditorSurfaceBuilder builder in <EditorSurfaceBuilder>[
      richEditorSurfaceBuilder,
      plainEditorSurfaceBuilder,
    ]) {
      await pumpSurface(
        tester,
        const EditorView(),
        connection: RecordingConnection(initial: ConnState.ready),
        extra: <Override>[
          editorSurfaceBuilderProvider.overrideWithValue(builder),
        ],
      );
      await tester.pumpAndSettle();

      final TextField field = tester.widget<TextField>(find.byType(TextField));
      expect(field.smartQuotesType, SmartQuotesType.disabled);
      expect(field.smartDashesType, SmartDashesType.disabled);
      expect(field.autocorrect, isFalse);
    }
  });

  for (final (String, EditorSurfaceBuilder) surface
      in <(String, EditorSurfaceBuilder)>[
        ('rich', richEditorSurfaceBuilder),
        ('plain fallback', plainEditorSurfaceBuilder),
      ]) {
    testWidgets(
      '${surface.$1} converts typed curly quotes before document storage',
      (WidgetTester tester) async {
        await pumpSurface(
          tester,
          const EditorView(),
          connection: RecordingConnection(initial: ConnState.ready),
          extra: <Override>[
            editorSurfaceBuilderProvider.overrideWithValue(surface.$2),
          ],
        );
        await tester.pumpAndSettle();

        // Exactly what iPadOS Smart Punctuation delivers, and exactly the bytes
        // recovered from the bench board's /test.py.
        await tester.enterText(
          find.byType(EditableText),
          'print(“Hello world!!”)',
        );
        await tester.pumpAndSettle();

        expect(
          containerOf(tester).read(editorDocumentProvider).content,
          'print("Hello world!!")',
          reason:
              'the document must never hold a character MicroPython rejects',
        );
      },
    );

    testWidgets('${surface.$1} removes pasted non-breaking spaces', (
      WidgetTester tester,
    ) async {
      await pumpSurface(
        tester,
        const EditorView(),
        connection: RecordingConnection(initial: ConnState.ready),
        extra: <Override>[
          editorSurfaceBuilderProvider.overrideWithValue(surface.$2),
        ],
      );
      await tester.pumpAndSettle();

      await tester.enterText(find.byType(EditableText), 'x = 1');
      await tester.pumpAndSettle();

      final String content = containerOf(
        tester,
      ).read(editorDocumentProvider).content;
      expect(content, 'x = 1');
      expect(content.codeUnits.contains(0x00A0), isFalse);
    });
  }
}

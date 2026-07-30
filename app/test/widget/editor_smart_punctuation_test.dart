// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.
//
// A-25 — end-to-end cover through the REAL EditorView widget.
//
// The unit tests pin the formatter in isolation; this pins that the editor
// actually WIRES it, so a future refactor cannot quietly drop `inputFormatters`
// and re-introduce `SyntaxError: invalid syntax` on a tablet.

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:pyble/editor/editor.dart';
import 'package:pyble/pble/pble.dart';

import '../support/feature_harness.dart';
import '../support/recording_connection.dart';

void main() {
  testWidgets('the editor field carries the smart-punctuation formatter', (
    WidgetTester tester,
  ) async {
    await pumpSurface(
      tester,
      const EditorView(),
      connection: RecordingConnection(initial: ConnState.ready),
    );
    await tester.pumpAndSettle();

    final TextField field = tester.widget<TextField>(find.byType(TextField));
    expect(
      field.inputFormatters?.whereType<SmartPunctuationFormatter>(),
      isNotEmpty,
      reason:
          'without this the iOS-only smartQuotesType hint is the ONLY '
          'defence, and it covers neither Android/macOS nor pasted text',
    );
    // The iOS hints must remain too — belt and braces.
    expect(field.smartQuotesType, SmartQuotesType.disabled);
    expect(field.smartDashesType, SmartDashesType.disabled);
    expect(field.autocorrect, isFalse);
  });

  testWidgets(
    'typing curly quotes into the editor stores ASCII in the document',
    (WidgetTester tester) async {
      await pumpSurface(
        tester,
        const EditorView(),
        connection: RecordingConnection(initial: ConnState.ready),
      );
      await tester.pumpAndSettle();

      // Exactly what iPadOS Smart Punctuation delivers, and exactly the bytes
      // recovered from the bench board's /test.py.
      await tester.enterText(find.byType(TextField), 'print(“Hello world!!”)');
      await tester.pumpAndSettle();

      expect(
        containerOf(tester).read(editorDocumentProvider).content,
        'print("Hello world!!")',
        reason: 'the document must never hold a character MicroPython rejects',
      );
    },
  );

  testWidgets('an invisible non-breaking space never reaches the document', (
    WidgetTester tester,
  ) async {
    await pumpSurface(
      tester,
      const EditorView(),
      connection: RecordingConnection(initial: ConnState.ready),
    );
    await tester.pumpAndSettle();

    await tester.enterText(find.byType(TextField), 'x = 1');
    await tester.pumpAndSettle();

    final String content = containerOf(
      tester,
    ).read(editorDocumentProvider).content;
    expect(content, 'x = 1');
    expect(content.codeUnits.contains(0x00A0), isFalse);
  });
}

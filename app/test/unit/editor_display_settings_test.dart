// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:pyble/editor/editor.dart';

void main() {
  group('editor display settings', () {
    late ProviderContainer container;

    setUp(() {
      container = ProviderContainer();
      addTearDown(container.dispose);
    });

    test('starts at the Signal code size and changes one point at a time', () {
      expect(kEditorDefaultFontSize, 14);
      expect(
        container.read(editorDisplaySettingsProvider).fontSize,
        kEditorDefaultFontSize,
      );

      container.read(editorDisplaySettingsProvider.notifier).increaseFontSize();
      expect(container.read(editorDisplaySettingsProvider).fontSize, 15);

      container.read(editorDisplaySettingsProvider.notifier).decreaseFontSize();
      expect(container.read(editorDisplaySettingsProvider).fontSize, 14);
    });

    test('clamps invalid input and disables movement beyond either bound', () {
      final EditorDisplaySettingsController controller = container.read(
        editorDisplaySettingsProvider.notifier,
      );

      controller.setFontSize(double.negativeInfinity);
      expect(
        container.read(editorDisplaySettingsProvider).fontSize,
        kEditorDefaultFontSize,
        reason: 'non-finite values fall back without poisoning layout',
      );

      controller.setFontSize(kEditorMinFontSize - 100);
      expect(
        container.read(editorDisplaySettingsProvider).fontSize,
        kEditorMinFontSize,
      );
      controller.decreaseFontSize();
      expect(
        container.read(editorDisplaySettingsProvider).fontSize,
        kEditorMinFontSize,
      );

      controller.setFontSize(kEditorMaxFontSize + 100);
      expect(
        container.read(editorDisplaySettingsProvider).fontSize,
        kEditorMaxFontSize,
      );
      controller.increaseFontSize();
      expect(
        container.read(editorDisplaySettingsProvider).fontSize,
        kEditorMaxFontSize,
      );
    });

    test('is app-session state rather than file or board state', () {
      final EditorDisplaySettingsController controller = container.read(
        editorDisplaySettingsProvider.notifier,
      );
      controller.setFontSize(19);

      container
          .read(editorDocumentProvider.notifier)
          .openFromBoard(path: '/first.py', content: 'first\n');
      container.read(editorDocumentProvider.notifier).newDocument();

      expect(container.read(editorDisplaySettingsProvider).fontSize, 19);
      expect(container.read(editorDocumentProvider).name, 'untitled.py');
    });
  });
}

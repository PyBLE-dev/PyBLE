// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:pyble/editor/editor.dart';
import 'package:pyble/pble/pble.dart';

import '../support/feature_harness.dart';

const String _source = '''def greet(name):
    message = f"Hello, {name}"
    print(message)

greet("PyBLE")
''';

void main() {
  for (final ({String name, Size size}) surface in <({String name, Size size})>[
    (name: 'ipad_landscape', size: const Size(1024, 768)),
    (name: 'phone_portrait', size: const Size(390, 844)),
  ]) {
    testWidgets('numbered editor @ ${surface.name}', (
      WidgetTester tester,
    ) async {
      final FakeConnection fake = FakeConnection(initial: ConnState.ready);
      addTearDown(fake.dispose);
      await pumpSurface(
        tester,
        const EditorView(),
        connection: fake,
        size: surface.size,
      );
      containerOf(tester)
          .read(editorDocumentProvider.notifier)
          .openFromBoard(path: '/main.py', content: _source);
      await tester.pump();

      await expectLater(
        find.byType(EditorView),
        matchesGoldenFile('goldens/editor_${surface.name}.png'),
      );
    }, tags: const <String>['golden']);
  }
}

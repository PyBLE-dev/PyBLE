// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:pyble/data/draft_repository.dart';
import 'package:pyble/editor/draft_recovery.dart';
import 'package:pyble/editor/editor_document.dart';
import 'package:pyble/editor/recovery_gate.dart';
import 'package:pyble/editor/recovery_panel.dart';
import 'package:pyble/pble/pble.dart';

import '../support/feature_harness.dart';

class _Store implements DraftRepository {
  DraftRead slot = DraftRead(generation: 1, snapshot: DraftSnapshot(
    name: 'main.py', content: 'prior text', originPath: '/main.py',
    generation: 1, checkpointTime: DateTime.utc(2026, 10, 31),
  ));
  Completer<DraftRead>? delayed;
  bool failClear = false;
  @override
  Future<DraftRead> load() async => delayed == null ? slot : delayed!.future;
  @override
  Future<int> clear({required int expectedGeneration}) async {
    if (failClear) throw const DraftStorageException(DraftStorageFailure.unavailable);
    slot = DraftRead(generation: slot.generation + 1);
    return slot.generation;
  }
  @override
  Future<void> write(DraftSnapshot snapshot, {required int expectedGeneration}) async {
    slot = DraftRead(generation: snapshot.generation, snapshot: snapshot);
  }
  @override
  Future<void> close() async {}
}

Future<void> _pump(WidgetTester tester, _Store store) async {
  final FakeConnection connection = FakeConnection();
  addTearDown(connection.dispose);
  await pumpSurface(tester, const RecoveryGate(
    child: Text('connection workflow mounted'),
  ), connection: connection, extra: <Override>[
    draftRepositoryProvider.overrideWithValue(store),
  ]);
  await tester.pump();
}

void main() {
  testWidgets('startup resolves explicit local choice before mounting connection workflow',
      (WidgetTester tester) async {
    final _Store store = _Store();
    await _pump(tester, store);
    expect(find.text('connection workflow mounted'), findsNothing);
    expect(find.text('prior text'), findsOneWidget);
    expect(containerOf(tester).read(editorDocumentProvider).content, isEmpty);
    await tester.tap(find.byKey(kRecoveryRestoreKey));
    await tester.pumpAndSettle();
    expect(find.text('connection workflow mounted'), findsOneWidget);
    final EditorDocument restored = containerOf(tester).read(editorDocumentProvider);
    expect(restored.content, 'prior text');
    expect(restored.boardPath, isNull);
    expect(restored.dirty, isTrue);
    expect(store.slot.snapshot!.content, 'prior text');
  });

  testWidgets('failed discard retains preview and confirmation choices',
      (WidgetTester tester) async {
    final _Store store = _Store()..failClear = true;
    await _pump(tester, store);
    await tester.tap(find.byKey(kRecoveryDiscardKey));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(kRecoveryConfirmDiscardKey));
    await tester.pumpAndSettle();
    expect(find.text('connection workflow mounted'), findsNothing);
    expect(find.text('prior text'), findsOneWidget);
    expect(find.byKey(kRecoveryRestoreKey), findsOneWidget);
    expect(store.slot.snapshot!.content, 'prior text');
    expect(find.textContaining('could not be read or written'), findsOneWidget);
  });

  testWidgets('timeout offers explicit volatile session and ignores a late startup result',
      (WidgetTester tester) async {
    final _Store store = _Store()..delayed = Completer<DraftRead>();
    await _pump(tester, store);
    expect(find.text('connection workflow mounted'), findsNothing);
    await tester.pump(const Duration(seconds: 10));
    expect(find.byKey(kRecoveryRetryKey), findsOneWidget);
    expect(find.byKey(kRecoveryContinueKey), findsOneWidget);
    await tester.tap(find.byKey(kRecoveryContinueKey));
    await tester.pump();
    expect(find.text('connection workflow mounted'), findsOneWidget);
    expect(find.textContaining('Recovery is off'), findsOneWidget);
    containerOf(tester).read(editorDocumentProvider.notifier).setContent('live text');
    store.delayed!.complete(store.slot);
    await tester.pump();
    expect(containerOf(tester).read(editorDocumentProvider).content, 'live text');
    expect(find.text('prior text'), findsNothing);
  });

  testWidgets('retry previews both live text and stored draft before explicit replacement',
      (WidgetTester tester) async {
    final _Store store = _Store()..delayed = Completer<DraftRead>();
    await _pump(tester, store);
    await tester.pump(const Duration(seconds: 10));
    await tester.tap(find.byKey(kRecoveryContinueKey));
    await tester.pump();
    containerOf(tester).read(editorDocumentProvider.notifier).setContent('live text');
    store.delayed!.complete(store.slot);
    await tester.pump();
    store.delayed = null;
    await tester.tap(find.byKey(kRecoveryRetryKey));
    await tester.pump();
    await tester.pump();
    expect(find.text('live text'), findsOneWidget);
    expect(find.text('prior text'), findsOneWidget);
    expect(containerOf(tester).read(editorDocumentProvider).content, 'live text');
  });
}

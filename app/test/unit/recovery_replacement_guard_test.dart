// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:pyble/data/draft_repository.dart';
import 'package:pyble/editor/board_target_guard.dart';
import 'package:pyble/editor/draft_recovery.dart';
import 'package:pyble/editor/editor_document.dart';

/// A previously committed slot whose storage becomes unavailable for writes.
/// Failure must never be interpreted as permission to delete the old copy.
class _UnavailableStore implements DraftRepository {
  final DraftSnapshot snapshot = DraftSnapshot(
    name: 'retained.py',
    content: 'previous exact text',
    originPath: '/lib/retained.py',
    generation: 7,
    checkpointTime: DateTime.utc(2026, 10, 31),
  );
  int writes = 0;
  int clears = 0;

  @override
  Future<DraftRead> load() async =>
      DraftRead(generation: 7, snapshot: snapshot);

  @override
  Future<void> write(
    DraftSnapshot snapshot, {
    required int expectedGeneration,
  }) async {
    writes++;
    throw const DraftStorageException(DraftStorageFailure.unavailable);
  }

  @override
  Future<int> clear({required int expectedGeneration}) async {
    clears++;
    throw const DraftStorageException(DraftStorageFailure.unavailable);
  }

  @override
  Future<void> close() async {}
}

void main() {
  const EditorDocument replacement = EditorDocument(
    name: 'replacement.py',
    content: 'replacement text',
    dirty: false,
    boardPath: '/replacement.py',
  );

  Future<ProviderContainer> setup(
    _UnavailableStore store,
    Future<bool> Function()? confirm,
  ) async {
    final ProviderContainer container = ProviderContainer(
      overrides: <Override>[
        draftRepositoryProvider.overrideWithValue(store),
        editorVolatileReplacementConfirmationProvider.overrideWithValue(
          confirm,
        ),
      ],
    );
    addTearDown(container.dispose);
    final DraftRecoveryController recovery = container.read(
      draftRecoveryProvider.notifier,
    );
    await recovery.start();
    expect(recovery.restore(), isTrue);
    return container;
  }

  Future<bool> replace(
    ProviderContainer container, {
    bool Function()? isStillValid,
  }) {
    final int epoch = container.read(editorDocumentEpochProvider);
    // The app's helper deliberately takes a Ref. This small provider exercises
    // that public seam without mounting widgets or creating a board transport.
    final Provider<Future<bool>> action = Provider<Future<bool>>(
      (Ref ref) => Future<bool>.microtask(
        () => replaceEditorDocument(
          ref,
          replacement,
          expectedEpoch: epoch,
          isStillValid: isStillValid,
        ),
      ),
    );
    return container.read(action);
  }

  void expectRetained(_UnavailableStore store) {
    expect(store.snapshot.content, 'previous exact text');
    expect(store.snapshot.generation, 7);
    expect(store.clears, 0);
  }

  test(
    'failed replacement keeps live text until volatile choice is declined',
    () async {
      final _UnavailableStore store = _UnavailableStore();
      final Completer<void> asked = Completer<void>();
      final Completer<bool> choice = Completer<bool>();
      int prompts = 0;
      final ProviderContainer container = await setup(store, () {
        prompts++;
        asked.complete();
        return choice.future;
      });
      final Future<bool> replacing = replace(container);
      await asked.future;
      expect(
        container.read(editorDocumentProvider).content,
        store.snapshot.content,
      );
      expect(
        container.read(draftRecoveryProvider).status,
        DraftRecoveryStatus.failed,
      );
      expectRetained(store);
      choice.complete(false);
      expect(await replacing, isFalse);
      expect(
        container.read(editorDocumentProvider).content,
        store.snapshot.content,
      );
      expect(
        container.read(draftRecoveryProvider).status,
        DraftRecoveryStatus.failed,
      );
      expect(store.writes, 1);
      expect(prompts, 1);
      expectRetained(store);
    },
  );

  test(
    'explicit volatile acceptance adopts replacement and preserves stored copy',
    () async {
      final _UnavailableStore store = _UnavailableStore();
      int prompts = 0;
      final ProviderContainer container = await setup(store, () async {
        prompts++;
        return true;
      });
      expect(await replace(container), isTrue);
      expect(container.read(editorDocumentProvider), replacement);
      expect(
        container.read(draftRecoveryProvider).status,
        DraftRecoveryStatus.volatile,
      );
      expect(
        await container.read(draftRecoveryProvider.notifier).saveRecoveryCopy(),
        isFalse,
      );
      expect(store.writes, 1);
      expect(prompts, 1);
      expectRetained(store);
    },
  );

  test(
    'edit away and back during volatile confirmation revokes captured choice',
    () async {
      final _UnavailableStore store = _UnavailableStore();
      final Completer<void> asked = Completer<void>();
      final Completer<bool> choice = Completer<bool>();
      final ProviderContainer container = await setup(store, () {
        asked.complete();
        return choice.future;
      });
      final Future<bool> replacing = replace(container);
      await asked.future;
      final EditorDocumentController editor = container.read(
        editorDocumentProvider.notifier,
      );
      editor.setContent('temporary new work');
      editor.setContent(store.snapshot.content);
      choice.complete(true);
      expect(await replacing, isFalse);
      expect(
        container.read(editorDocumentProvider).content,
        store.snapshot.content,
      );
      expect(container.read(editorDocumentProvider).name, 'retained.py');
      expect(
        container.read(draftRecoveryProvider).status,
        isNot(DraftRecoveryStatus.volatile),
      );
      expect(store.writes, 1);
      expectRetained(store);
    },
  );

  test(
    'board-session guard change during volatile confirmation refuses adoption',
    () async {
      final _UnavailableStore store = _UnavailableStore();
      final Completer<void> asked = Completer<void>();
      final Completer<bool> choice = Completer<bool>();
      Object currentSession = Object();
      final Object capturedSession = currentSession;
      final ProviderContainer container = await setup(store, () {
        asked.complete();
        return choice.future;
      });
      final Future<bool> replacing = replace(
        container,
        isStillValid: () => identical(currentSession, capturedSession),
      );
      await asked.future;
      currentSession = Object();
      choice.complete(true);
      expect(await replacing, isFalse);
      expect(
        container.read(editorDocumentProvider).content,
        store.snapshot.content,
      );
      expect(
        container.read(draftRecoveryProvider).status,
        DraftRecoveryStatus.failed,
      );
      expect(store.writes, 1);
      expectRetained(store);
    },
  );

  test(
    'already volatile session adopts without another failing write or prompt',
    () async {
      final _UnavailableStore store = _UnavailableStore();
      int prompts = 0;
      final ProviderContainer container = await setup(store, () async {
        prompts++;
        return false;
      });
      container.read(draftRecoveryProvider.notifier).continueWithoutRecovery();
      expect(await replace(container), isTrue);
      expect(container.read(editorDocumentProvider), replacement);
      expect(
        container.read(draftRecoveryProvider).status,
        DraftRecoveryStatus.volatile,
      );
      expect(store.writes, 0);
      expect(prompts, 0);
      expectRetained(store);
    },
  );

  test(
    'missing volatile confirmation preserves live text and old recovery copy',
    () async {
      final _UnavailableStore store = _UnavailableStore();
      final ProviderContainer container = await setup(store, null);
      expect(await replace(container), isFalse);
      expect(
        container.read(editorDocumentProvider).content,
        store.snapshot.content,
      );
      expect(
        container.read(draftRecoveryProvider).status,
        DraftRecoveryStatus.failed,
      );
      expect(store.writes, 1);
      expectRetained(store);
    },
  );
}

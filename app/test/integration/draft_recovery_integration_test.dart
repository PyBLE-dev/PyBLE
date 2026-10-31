// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

import 'dart:io';

import 'package:drift/native.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:pyble/data/draft_repository.dart';
import 'package:pyble/data/drift_draft_repository.dart';
import 'package:pyble/editor/draft_recovery.dart';
import 'package:pyble/editor/editor_document.dart';

void main() {
  late Directory directory;
  late File file;
  final List<ProviderContainer> containers = <ProviderContainer>[];
  final List<DraftRepository> repositories = <DraftRepository>[];

  ProviderContainer container(DraftRepository repository) {
    final ProviderContainer result = ProviderContainer(
      overrides: <Override>[
        draftRepositoryProvider.overrideWithValue(repository),
      ],
    );
    containers.add(result);
    return result;
  }

  Future<DriftDraftRepository> open() async {
    final DriftDraftRepository repository = await DriftDraftRepository.open(
      file,
    );
    repositories.add(repository);
    return repository;
  }

  setUp(() async {
    directory = await Directory.systemTemp.createTemp(
      'pyble-recovery-integration-',
    );
    file = File('${directory.path}/pyble.sqlite');
  });
  tearDown(() async {
    for (final ProviderContainer container in containers.reversed) {
      // Each container is disposed once below as soon as its app session ends.
      // ProviderContainer.dispose is idempotent for teardown fallback.
      container.dispose();
    }
    containers.clear();
    for (final DraftRepository repository in repositories.reversed) {
      await repository.close();
    }
    repositories.clear();
    await directory.delete(recursive: true);
  });

  test(
    'checkpoint, reopen, explicit offline restore and New tombstone round-trip',
    () async {
      const String source = '# café 🐍\r\nprint("exact text")\n\t \n';
      final DriftDraftRepository first = await open();
      final ProviderContainer initial = container(first);
      final DraftRecoveryController writer = initial.read(
        draftRecoveryProvider.notifier,
      );
      await writer.start();
      initial
          .read(editorDocumentProvider.notifier)
          .openGenerated(name: 'generated.py', content: source);
      expect(await writer.saveRecoveryCopy(), isTrue);
      expect(
        initial.read(draftRecoveryProvider).status,
        DraftRecoveryStatus.saved,
      );
      expect((await first.load()).snapshot!.content, source);
      initial.dispose();
      await first.close();

      final DriftDraftRepository second = await open();
      final ProviderContainer restarted = container(second);
      final DraftRecoveryController reader = restarted.read(
        draftRecoveryProvider.notifier,
      );
      await reader.start();
      expect(
        restarted.read(draftRecoveryProvider).status,
        DraftRecoveryStatus.decision,
      );
      expect(
        restarted.read(editorDocumentProvider),
        const EditorDocument.untitled(),
      );
      expect(restarted.read(draftRecoveryProvider).candidate!.content, source);
      expect(reader.restore(), isTrue);
      final EditorDocument restored = restarted.read(editorDocumentProvider);
      expect(restored.content, source);
      expect(restored.name, 'generated.py');
      expect(restored.dirty, isTrue);
      expect(restored.boardPath, isNull);
      expect(restarted.read(editorRecoveredDraftProvider), isTrue);
      expect(
        await reader.replaceDocument(
          const EditorDocument.untitled(),
          expectedEpoch: restarted.read(editorDocumentEpochProvider),
        ),
        isTrue,
      );
      final int clearedGeneration = (await second.load()).generation;
      expect(clearedGeneration, greaterThan(1));
      expect((await second.load()).snapshot, isNull);
      restarted.dispose();
      await second.close();

      final DriftDraftRepository third = await open();
      final ProviderContainer afterNew = container(third);
      await afterNew.read(draftRecoveryProvider.notifier).start();
      expect(
        afterNew.read(draftRecoveryProvider).status,
        DraftRecoveryStatus.saved,
      );
      expect(afterNew.read(draftRecoveryProvider).candidate, isNull);
      expect(
        afterNew.read(editorDocumentProvider),
        const EditorDocument.untitled(),
      );
      expect((await third.load()).generation, clearedGeneration);
    },
  );

  test(
    'real SQLite full failure preserves live edits and previous recoverable text',
    () async {
      final DriftDraftRepository first = await open();
      final ProviderContainer initial = container(first);
      final DraftRecoveryController writer = initial.read(
        draftRecoveryProvider.notifier,
      );
      await writer.start();
      initial
          .read(editorDocumentProvider.notifier)
          .setContent('previous checkpoint');
      expect(await writer.saveRecoveryCopy(), isTrue);
      initial.dispose();
      await first.close();

      final DriftDraftRepository limited = DriftDraftRepository.forTesting(
        NativeDatabase(
          file,
          setup: (db) {
            final int pages =
                db.select('PRAGMA page_count').single.values.single as int;
            db.execute('PRAGMA max_page_count = ${pages + 2}');
          },
        ),
      );
      repositories.add(limited);
      final ProviderContainer editing = container(limited);
      final DraftRecoveryController recovery = editing.read(
        draftRecoveryProvider.notifier,
      );
      await recovery.start();
      expect(recovery.restore(), isTrue);
      final String source = 'x' * 100000;
      editing.read(editorDocumentProvider.notifier).setContent(source);
      expect(await recovery.saveRecoveryCopy(), isFalse);
      expect(editing.read(editorDocumentProvider).content, source);
      expect(
        editing.read(draftRecoveryProvider).status,
        DraftRecoveryStatus.failed,
      );
      expect(
        editing.read(draftRecoveryProvider).failure,
        DraftStorageFailure.unavailable,
      );
      expect((await limited.load()).snapshot!.content, 'previous checkpoint');
      editing.dispose();
      await limited.close();

      final DriftDraftRepository reopened = await open();
      final ProviderContainer restarted = container(reopened);
      await restarted.read(draftRecoveryProvider.notifier).start();
      expect(
        restarted.read(draftRecoveryProvider).status,
        DraftRecoveryStatus.decision,
      );
      expect(
        restarted.read(draftRecoveryProvider).candidate!.content,
        'previous checkpoint',
      );
    },
  );
}

// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:pyble/data/draft_repository.dart';
import 'package:pyble/data/drift_draft_repository.dart';

void main() {
  late Directory directory;
  late File file;
  late DriftDraftRepository repository;
  final DateTime checkpoint = DateTime.utc(2026, 10, 31, 12, 34, 56, 123);

  DraftSnapshot snapshot(String content, {int generation = 1, String name = 'main.py', String? originPath}) =>
      DraftSnapshot(name: name, content: content, generation: generation,
        checkpointTime: checkpoint, originPath: originPath);

  Matcher failure(DraftStorageFailure reason) => throwsA(isA<DraftStorageException>()
      .having((DraftStorageException e) => e.reason, 'reason', reason));

  setUp(() async {
    directory = await Directory.systemTemp.createTemp('pyble-draft-');
    file = File('${directory.path}/draft.sqlite');
    repository = await DriftDraftRepository.open(file);
  });
  tearDown(() async {
    await repository.close();
    await directory.delete(recursive: true);
  });

  test('first creation is an empty generation-zero slot', () async {
    final DraftRead read = await repository.load();
    expect(read.generation, 0);
    expect(read.snapshot, isNull);
  });

  test('exact Unicode, whitespace, metadata survive closing and reopening', () async {
    const String source = '# café 🐍\r\nprint(“text”)\n\t \n';
    await repository.write(snapshot(source, originPath: '/lib/main.py'), expectedGeneration: 0);
    await repository.close();
    repository = await DriftDraftRepository.open(file);
    final DraftRead read = await repository.load();
    expect(read.generation, 1);
    expect(read.snapshot!.content, source);
    expect(read.snapshot!.name, 'main.py');
    expect(read.snapshot!.originPath, '/lib/main.py');
    expect(read.snapshot!.checkpointTime, checkpoint);
  });

  test('empty named file remains recoverable', () async {
    await repository.write(snapshot(''), expectedGeneration: 0);
    expect((await repository.load()).snapshot!.content, '');
  });

  test('clear persists a newer empty tombstone and rejects stale writes', () async {
    await repository.write(snapshot('first'), expectedGeneration: 0);
    expect(await repository.clear(expectedGeneration: 1), 2);
    await expectLater(repository.write(snapshot('stale', generation: 3), expectedGeneration: 1), failure(DraftStorageFailure.conflict));
    await repository.close();
    repository = await DriftDraftRepository.open(file);
    expect((await repository.load()).generation, 2);
    expect((await repository.load()).snapshot, isNull);
  });

  test('generation cannot regress or reuse the committed revision', () async {
    await repository.write(snapshot('first'), expectedGeneration: 0);
    await expectLater(repository.write(snapshot('older'), expectedGeneration: 1), failure(DraftStorageFailure.conflict));
    expect((await repository.load()).snapshot!.content, 'first');
  });

  test('two writers cannot overwrite a checkpoint using the same predecessor', () async {
    final DriftDraftRepository other = await DriftDraftRepository.open(file);
    try {
      await repository.write(snapshot('winner'), expectedGeneration: 0);
      await expectLater(other.write(snapshot('loser'), expectedGeneration: 0), failure(DraftStorageFailure.conflict));
      expect((await other.load()).snapshot!.content, 'winner');
    } finally { await other.close(); }
  });

  test('UTF-8 admission accepts exact limit and refuses one byte over', () async {
    await repository.write(snapshot('é' * (1024 * 1024 ~/ 2)), expectedGeneration: 0);
    await expectLater(repository.write(snapshot('${'a' * (1024 * 1024)}x', generation: 2), expectedGeneration: 1), failure(DraftStorageFailure.tooLarge));
    expect((await repository.load()).generation, 1);
  });

  test('one byte content and surrogate pairs round-trip without normalization', () async {
    await repository.write(snapshot('a'), expectedGeneration: 0);
    await repository.write(snapshot('🐍', generation: 2), expectedGeneration: 1);
    expect((await repository.load()).snapshot!.content, '🐍');
  });

  test('unpaired UTF-16 is refused without losing prior checkpoint', () async {
    await repository.write(snapshot('safe'), expectedGeneration: 0);
    await expectLater(repository.write(snapshot(String.fromCharCode(0xd800), generation: 2), expectedGeneration: 1), failure(DraftStorageFailure.invalidText));
    expect((await repository.load()).snapshot!.content, 'safe');
  });

  test('unsafe filenames and historical paths are refused', () async {
    for (final String name in <String>['', '.', '..', '../x.py', 'a/b.py', 'a\\b.py', 'a\n.py', 'é' * 65]) {
      await expectLater(repository.write(snapshot('x', name: name), expectedGeneration: 0), failure(DraftStorageFailure.invalidMetadata));
    }
    for (final String path in <String>['relative.py', '/../x.py', '/a/../b.py', '/a\n.py', '/${'a' * 128}']) {
      await expectLater(repository.write(snapshot('x', originPath: path), expectedGeneration: 0), failure(DraftStorageFailure.invalidMetadata));
    }
    expect((await repository.load()).snapshot, isNull);
  });
}

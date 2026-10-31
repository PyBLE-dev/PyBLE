// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

import 'dart:io';
import 'dart:convert';

import 'package:drift/drift.dart' show driftRuntimeOptions;
import 'package:drift/native.dart' show NativeDatabase;
import 'package:sqlite3/sqlite3.dart' as sqlite;

import 'package:flutter_test/flutter_test.dart';
import 'package:pyble/data/draft_repository.dart';
import 'package:pyble/data/drift_draft_repository.dart';

void main() {
  late Directory directory;
  late File file;
  late DriftDraftRepository repository;
  final DateTime checkpoint = DateTime.utc(2026, 10, 31, 12, 34, 56, 123);

  DraftSnapshot snapshot(
    String content, {
    int generation = 1,
    String name = 'main.py',
    String? originPath,
  }) => DraftSnapshot(
    name: name,
    content: content,
    generation: generation,
    checkpointTime: checkpoint,
    originPath: originPath,
  );

  Matcher failure(DraftStorageFailure reason) => throwsA(
    isA<DraftStorageException>().having(
      (DraftStorageException e) => e.reason,
      'reason',
      reason,
    ),
  );

  setUpAll(() {
    // Explicitly exercise separate competing connections to the same file.
    driftRuntimeOptions.dontWarnAboutMultipleDatabases = true;
  });

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

  test(
    'exact Unicode, whitespace, metadata survive closing and reopening',
    () async {
      const String source = '# café 🐍\r\nprint(“text”)\n\t \n';
      await repository.write(
        snapshot(source, originPath: '/lib/main.py'),
        expectedGeneration: 0,
      );
      await repository.close();
      repository = await DriftDraftRepository.open(file);
      final DraftRead read = await repository.load();
      expect(read.generation, 1);
      expect(read.snapshot!.content, source);
      expect(read.snapshot!.name, 'main.py');
      expect(read.snapshot!.originPath, '/lib/main.py');
      expect(read.snapshot!.checkpointTime, checkpoint);
    },
  );

  test('empty named file remains recoverable', () async {
    await repository.write(snapshot(''), expectedGeneration: 0);
    expect((await repository.load()).snapshot!.content, '');
  });

  test(
    'clear persists a newer empty tombstone and rejects stale writes',
    () async {
      await repository.write(snapshot('first'), expectedGeneration: 0);
      expect(await repository.clear(expectedGeneration: 1), 2);
      await expectLater(
        repository.write(
          snapshot('stale', generation: 3),
          expectedGeneration: 1,
        ),
        failure(DraftStorageFailure.conflict),
      );
      await repository.close();
      repository = await DriftDraftRepository.open(file);
      expect((await repository.load()).generation, 2);
      expect((await repository.load()).snapshot, isNull);
    },
  );

  test('generation cannot regress or reuse the committed revision', () async {
    await repository.write(snapshot('first'), expectedGeneration: 0);
    await expectLater(
      repository.write(snapshot('older'), expectedGeneration: 1),
      failure(DraftStorageFailure.conflict),
    );
    expect((await repository.load()).snapshot!.content, 'first');
  });

  test(
    'two writers cannot overwrite a checkpoint using the same predecessor',
    () async {
      final DriftDraftRepository other = await DriftDraftRepository.open(file);
      try {
        await repository.write(snapshot('winner'), expectedGeneration: 0);
        await expectLater(
          other.write(snapshot('loser'), expectedGeneration: 0),
          failure(DraftStorageFailure.conflict),
        );
        expect((await other.load()).snapshot!.content, 'winner');
      } finally {
        await other.close();
      }
    },
  );

  test(
    'UTF-8 admission accepts exact limit and refuses one byte over',
    () async {
      await repository.write(
        snapshot('é' * (1024 * 1024 ~/ 2)),
        expectedGeneration: 0,
      );
      await expectLater(
        repository.write(
          snapshot('${'a' * (1024 * 1024)}x', generation: 2),
          expectedGeneration: 1,
        ),
        failure(DraftStorageFailure.tooLarge),
      );
      expect((await repository.load()).generation, 1);
    },
  );

  test('128 UTF-8 byte filename is accepted without renaming', () async {
    final String name = 'é' * 64;
    await repository.write(snapshot('x', name: name), expectedGeneration: 0);
    expect((await repository.load()).snapshot!.name, name);
  });

  test(
    'one byte content and surrogate pairs round-trip without normalization',
    () async {
      await repository.write(snapshot('a'), expectedGeneration: 0);
      await repository.write(
        snapshot('🐍', generation: 2),
        expectedGeneration: 1,
      );
      expect((await repository.load()).snapshot!.content, '🐍');
    },
  );

  test('unpaired UTF-16 is refused without losing prior checkpoint', () async {
    await repository.write(snapshot('safe'), expectedGeneration: 0);
    await expectLater(
      repository.write(
        snapshot(String.fromCharCode(0xd800), generation: 2),
        expectedGeneration: 1,
      ),
      failure(DraftStorageFailure.invalidText),
    );
    expect((await repository.load()).snapshot!.content, 'safe');
  });

  test('unsafe filenames and historical paths are refused', () async {
    for (final String name in <String>[
      '',
      '.',
      '..',
      '../x.py',
      'a/b.py',
      'a\\b.py',
      'a\n.py',
      'é' * 65,
    ]) {
      await expectLater(
        repository.write(snapshot('x', name: name), expectedGeneration: 0),
        failure(DraftStorageFailure.invalidMetadata),
      );
    }
    for (final String path in <String>[
      'relative.py',
      '/../x.py',
      '/a/../b.py',
      '/a\n.py',
      '/${'a' * 128}',
    ]) {
      await expectLater(
        repository.write(
          snapshot('x', originPath: path),
          expectedGeneration: 0,
        ),
        failure(DraftStorageFailure.invalidMetadata),
      );
    }
    expect((await repository.load()).snapshot, isNull);
  });

  test('production connection uses WAL and synchronous FULL', () async {
    await repository.write(snapshot('safe'), expectedGeneration: 0);
    final sqlite.Database db = sqlite.sqlite3.open(file.path);
    try {
      expect(db.select('PRAGMA journal_mode').single.values.single, 'wal');
      // synchronous is connection-local; production verifies it at each open.
      // A new connection starts at FULL, and the persistent mode remains WAL.
      expect(db.select('PRAGMA synchronous').single.values.single, 2);
    } finally {
      db.close();
    }
  });

  test('schema fixture recreates the exact v1 tables', () async {
    final Map<String, dynamic> exported =
        jsonDecode(
              await File('drift_schemas/drift_schema_v1.json').readAsString(),
            )
            as Map<String, dynamic>;
    final sqlite.Database db = sqlite.sqlite3.open(file.path);
    try {
      final List<String> actual = db
          .select(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name",
          )
          .map((sqlite.Row row) => row['sql'] as String)
          .toList();
      final sqlite.Database fixture = sqlite.sqlite3.openInMemory();
      try {
        for (final dynamic entry in exported['fixed_sql'] as List<dynamic>) {
          for (final dynamic statement in entry['sql'] as List<dynamic>) {
            fixture.execute(statement['sql'] as String);
          }
        }
        final List<String> expected = fixture
            .select(
              "SELECT sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name",
            )
            .map((sqlite.Row row) => row['sql'] as String)
            .toList();
        expect(actual..sort(), expected..sort());
      } finally {
        fixture.close();
      }
      expect(db.userVersion, 1);
    } finally {
      db.close();
    }
  });

  test(
    'bad content hash refuses hydration without deleting database',
    () async {
      await repository.write(snapshot('safe'), expectedGeneration: 0);
      await repository.close();
      final sqlite.Database db = sqlite.sqlite3.open(file.path);
      db.execute("UPDATE project_files SET content_hash='wrong'");
      db.close();
      final List<int> before = await file.readAsBytes();
      await expectLater(
        DriftDraftRepository.open(file),
        failure(DraftStorageFailure.corrupt),
      );
      expect(await file.readAsBytes(), before);
    },
  );

  test('invalid metadata and unknown recovery format fail closed', () async {
    await repository.close();
    final sqlite.Database db = sqlite.sqlite3.open(file.path);
    db.execute('UPDATE settings SET value=?', <Object>[
      '{"version":2,"generation":0,"empty":true}',
    ]);
    db.close();
    await expectLater(
      DriftDraftRepository.open(file),
      failure(DraftStorageFailure.unsupportedVersion),
    );
    final sqlite.Database corrupt = sqlite.sqlite3.open(file.path);
    corrupt.execute('UPDATE settings SET value=?', <Object>['broken']);
    corrupt.close();
    await expectLater(
      DriftDraftRepository.open(file),
      failure(DraftStorageFailure.corrupt),
    );
    expect(await file.exists(), isTrue);
  });

  test('newer database schema is refused without downgrade or reset', () async {
    await repository.write(snapshot('safe'), expectedGeneration: 0);
    await repository.close();
    final sqlite.Database db = sqlite.sqlite3.open(file.path);
    db.userVersion = 99;
    db.close();
    final List<int> before = await file.readAsBytes();
    await expectLater(
      DriftDraftRepository.open(file),
      failure(DraftStorageFailure.unsupportedVersion),
    );
    expect(await file.readAsBytes(), before);
  });

  test('existing zero-version and truncated files are preserved', () async {
    await repository.close();
    final sqlite.Database db = sqlite.sqlite3.open(file.path);
    db.userVersion = 0;
    db.close();
    await expectLater(
      DriftDraftRepository.open(file),
      failure(DraftStorageFailure.corrupt),
    );
    await file.writeAsBytes(<int>[83, 81, 76, 105, 116, 101]);
    final List<int> before = await file.readAsBytes();
    await expectLater(
      DriftDraftRepository.open(file),
      failure(DraftStorageFailure.corrupt),
    );
    expect(await file.readAsBytes(), before);
  });

  test(
    'metadata transaction abort rolls back content and clear tombstone',
    () async {
      await repository.write(snapshot('safe'), expectedGeneration: 0);
      final sqlite.Database db = sqlite.sqlite3.open(file.path);
      db.execute(
        "CREATE TRIGGER reject_metadata BEFORE UPDATE ON settings BEGIN SELECT RAISE(ABORT, 'injected'); END",
      );
      db.close();
      await expectLater(
        repository.write(
          snapshot('must rollback', generation: 2),
          expectedGeneration: 1,
        ),
        failure(DraftStorageFailure.unavailable),
      );
      await expectLater(
        repository.clear(expectedGeneration: 1),
        failure(DraftStorageFailure.unavailable),
      );
      expect((await repository.load()).snapshot!.content, 'safe');
      expect((await repository.load()).generation, 1);
    },
  );

  test('real SQLITE_FULL keeps prior content and generation', () async {
    await repository.write(snapshot('safe'), expectedGeneration: 0);
    await repository.close();
    repository = DriftDraftRepository.forTesting(
      NativeDatabase(
        file,
        setup: (db) {
          final int pages =
              db.select('PRAGMA page_count').single.values.single as int;
          db.execute('PRAGMA max_page_count = ${pages + 2}');
        },
      ),
    );
    await expectLater(
      repository.write(
        snapshot('x' * 100000, generation: 2),
        expectedGeneration: 1,
      ),
      failure(DraftStorageFailure.unavailable),
    );
    expect((await repository.load()).snapshot!.content, 'safe');
    expect((await repository.load()).generation, 1);
  });

  test('read-only storage rejects writes and preserves checkpoint', () async {
    await repository.write(snapshot('safe'), expectedGeneration: 0);
    await repository.close();
    repository = DriftDraftRepository.forTesting(
      NativeDatabase(
        file,
        setup: (db) {
          db.execute('PRAGMA query_only = ON');
        },
      ),
    );
    await expectLater(
      repository.write(
        snapshot('in memory only', generation: 2),
        expectedGeneration: 1,
      ),
      failure(DraftStorageFailure.unavailable),
    );
    await repository.close();
    repository = await DriftDraftRepository.open(file);
    expect((await repository.load()).snapshot!.content, 'safe');
  });

  test(
    'process kill before, during and after commit yields only whole checkpoints',
    () async {
      for (final String point in <String>['before', 'during', 'after']) {
        if ((await repository.load()).generation == 0) {
          await repository.write(snapshot('safe'), expectedGeneration: 0);
        }
        await repository.close();
        final Process process = await Process.start('dart', <String>[
          'run',
          'test/data/helpers/crash_writer.dart',
          file.path,
          point,
        ]);
        final Future<String> stderr = process.stderr
            .transform(utf8.decoder)
            .join();
        try {
          await process.stdout
              .transform(utf8.decoder)
              .transform(const LineSplitter())
              .firstWhere((String line) => line == 'READY')
              .timeout(const Duration(seconds: 45));
          expect(process.kill(ProcessSignal.sigkill), isTrue);
          await process.exitCode;
          expect(
            (await stderr).replaceAll('Running build hooks...', '').trim(),
            isEmpty,
          );
        } finally {
          process.kill(ProcessSignal.sigkill);
          await process.exitCode;
        }
        repository = await DriftDraftRepository.open(file);
        final DraftRead read = await repository.load();
        expect(read.snapshot!.content, point == 'after' ? 'complete' : 'safe');
        expect(read.generation, point == 'after' ? 2 : 1);
      }
    },
    timeout: const Timeout(Duration(minutes: 3)),
  );
}

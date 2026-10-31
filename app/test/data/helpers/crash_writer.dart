// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

// Fault-controlled child writer. The parent kills this process after READY;
// neither graceful disposal nor an app lifecycle callback can flush its work.
import 'dart:convert';
import 'dart:io';

import 'package:pyble/data/draft_repository.dart';
import 'package:pyble/data/drift_draft_repository.dart';
import 'package:sqlite3/sqlite3.dart';

Future<void> main(List<String> arguments) async {
  final File file = File(arguments[0]);
  final String point = arguments[1];
  final List<Object> retained = <Object>[];
  if (point == 'during') {
    final Database db = sqlite3.open(file.path);
    retained.add(db);
    db.execute('PRAGMA synchronous = FULL');
    db.execute('BEGIN IMMEDIATE');
    // Deliberately incomplete content/metadata pair. SQLite must roll this
    // uncommitted mutation back when the process dies, including its WAL.
    db.execute('UPDATE project_files SET content=?', <Object>[
      utf8.encode('partial'),
    ]);
  } else if (point == 'after') {
    final DraftRepository repository = await DriftDraftRepository.open(file);
    retained.add(repository);
    await repository.write(
      DraftSnapshot(
        name: 'main.py',
        content: 'complete',
        generation: 2,
        checkpointTime: DateTime.utc(2026, 10, 31),
      ),
      expectedGeneration: 1,
    );
  }
  stdout.writeln('READY');
  await stdout.flush();
  await stdin.first;
  for (final Object resource in retained) {
    if (resource is Database) resource.close();
    if (resource is DraftRepository) await resource.close();
  }
}

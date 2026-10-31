// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

import 'package:drift/drift.dart';

import 'draft_repository.dart';

part 'draft_database.g.dart';

/// The internal current-draft project is not a project-management UI.
class Projects extends Table {
  TextColumn get id => text()();
  TextColumn get name => text()();
  IntColumn get createdAt => integer()();
  IntColumn get updatedAt => integer()();
  @override
  Set<Column<Object>> get primaryKey => <Column<Object>>{id};
}

class ProjectFiles extends Table {
  TextColumn get id => text()();
  TextColumn get projectId => text().references(Projects, #id)();
  TextColumn get path => text()();
  BlobColumn get content => blob()();
  IntColumn get size => integer()();
  TextColumn get contentHash => text()();
  IntColumn get updatedAt => integer()();
  @override
  Set<Column<Object>> get primaryKey => <Column<Object>>{id};
}

/// The one SettingsStore, initially holding only versioned recovery metadata.
class Settings extends Table {
  TextColumn get key => text()();
  TextColumn get value => text()();
  @override
  Set<Column<Object>> get primaryKey => <Column<Object>>{key};
}

@DriftDatabase(tables: <Type>[Projects, ProjectFiles, Settings])
class DraftDatabase extends _$DraftDatabase {
  DraftDatabase(super.executor);

  @override
  int get schemaVersion => 1;

  @override
  MigrationStrategy get migration => MigrationStrategy(
    onCreate: (Migrator m) async {
      await m.createAll();
      await customStatement(
        'INSERT INTO settings (key, value) VALUES (?, ?)',
        <Object>[
          'current_text_draft',
          '{"version":1,"generation":0,"empty":true}',
        ],
      );
    },
    // There is no released v0 disk draft and no supported downgrade. Future
    // versions add explicit transactional forward migrations and fixtures.
    onUpgrade: (Migrator m, int from, int to) async =>
        throw const DraftStorageException(
          DraftStorageFailure.unsupportedVersion,
        ),
  );
}

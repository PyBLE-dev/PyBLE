// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:isolate';

import 'package:crypto/crypto.dart';
import 'package:drift/drift.dart';
import 'package:drift/native.dart';
import 'package:drift/isolate.dart' show DriftRemoteException;

import 'draft_database.dart';
import 'draft_repository.dart';

const int maxDraftBytes = 1024 * 1024;
const String _slotKey = 'current_text_draft';
const String _projectId = 'pyble.internal.current_text';
const String _fileId = 'pyble.internal.current_text.file';

/// Drift-backed, app-private slot. Every database statement runs on the owned
/// native background executor; large UTF-8/hash work runs in another isolate.
/// No method deletes, repairs, truncates or recreates an existing store.
class DriftDraftRepository implements DraftRepository {
  DriftDraftRepository._(this._database);

  /// Test seam for real SQLite fault injection (read-only/full/abort). Runtime
  /// composition always uses [open]'s owned background executor and pragmas.
  DriftDraftRepository.forTesting(QueryExecutor executor)
    : _database = DraftDatabase(executor);

  final DraftDatabase _database;
  Future<void> _tail = Future<void>.value();
  bool _closed = false;
  bool _accepting = true;
  Future<void>? _closeFuture;

  /// Opens one file-backed connection. The existing-file check is deliberately
  /// outside SQLite's schema handling: a version-zero existing database is
  /// unreadable state, never permission to recreate user storage.
  static Future<DriftDraftRepository> open(File file) async {
    final bool existed = await file.exists();
    final DraftDatabase database = DraftDatabase(
      NativeDatabase.createInBackground(
        file,
        setup: (db) {
          final int version =
              db.select('PRAGMA user_version').single.values.single as int;
          if (version > 1) {
            throw const DraftStorageException(
              DraftStorageFailure.unsupportedVersion,
            );
          }
          if (existed && version == 0) {
            throw const DraftStorageException(DraftStorageFailure.corrupt);
          }
          db.execute('PRAGMA busy_timeout = 5000');
          db.execute('PRAGMA foreign_keys = ON');
          final Object? mode = db
              .select('PRAGMA journal_mode = WAL')
              .single
              .values
              .single;
          db.execute('PRAGMA synchronous = FULL');
          final Object? sync = db
              .select('PRAGMA synchronous')
              .single
              .values
              .single;
          if (mode != 'wal' || sync != 2) {
            throw const DraftStorageException(DraftStorageFailure.unavailable);
          }
        },
      ),
    );
    final DriftDraftRepository repository = DriftDraftRepository._(database);
    try {
      await repository.load();
      return repository;
    } catch (_) {
      await database.close();
      rethrow;
    }
  }

  Future<T> _serialized<T>(Future<T> Function() operation) {
    if (!_accepting) {
      return Future<T>.error(
        const DraftStorageException(DraftStorageFailure.unavailable),
      );
    }
    final Completer<T> result = Completer<T>();
    _tail = _tail.then((_) async {
      try {
        if (_closed) {
          throw const DraftStorageException(DraftStorageFailure.unavailable);
        }
        result.complete(await operation());
      } catch (error, stack) {
        result.completeError(_safeException(error), stack);
      }
    });
    return result.future;
  }

  @override
  Future<DraftRead> load() => _serialized(() => _database.transaction(_read));

  Future<DraftRead> _read() async {
    // Bound untrusted SQLite values on the database isolate before sending
    // strings to the UI isolate or decoding their JSON. This also keeps a
    // corrupt-but-readable database from monopolizing startup's timer.
    final QueryRow settingsBound = await _database
        .customSelect(
          'SELECT COUNT(*) AS row_count, COALESCE(MAX(LENGTH(CAST(value AS BLOB))), 0) AS max_bytes FROM settings WHERE key = ?',
          variables: <Variable<Object>>[const Variable<String>(_slotKey)],
        )
        .getSingle();
    if (settingsBound.read<int>('row_count') != 1 ||
        settingsBound.read<int>('max_bytes') > 4096) {
      throw const DraftStorageException(DraftStorageFailure.corrupt);
    }
    final List<Setting> settings = await (_database.select(
      _database.settings,
    )..where((Settings t) => t.key.equals(_slotKey))).get();
    if (settings.length != 1) {
      throw const DraftStorageException(DraftStorageFailure.corrupt);
    }
    final Map<String, Object?> metadata;
    try {
      metadata = (jsonDecode(settings.single.value) as Map<String, dynamic>)
          .cast<String, Object?>();
    } catch (_) {
      throw const DraftStorageException(DraftStorageFailure.corrupt);
    }
    if (metadata['version'] is! int || (metadata['version'] as int) < 1) {
      throw const DraftStorageException(DraftStorageFailure.corrupt);
    }
    if (metadata['version'] != 1) {
      throw const DraftStorageException(DraftStorageFailure.unsupportedVersion);
    }
    final Object? generation = metadata['generation'];
    if (generation is! int ||
        generation < 0 ||
        generation > 0x1fffffffffffff ||
        metadata['empty'] is! bool) {
      throw const DraftStorageException(DraftStorageFailure.corrupt);
    }
    final QueryRow bound = await _database
        .customSelect(
          'SELECT COUNT(*) AS row_count, COALESCE(MAX(LENGTH(CAST(content AS BLOB))), 0) AS max_bytes, '
          'COALESCE(MAX(MAX(LENGTH(CAST(id AS BLOB)), LENGTH(CAST(project_id AS BLOB)), '
          'LENGTH(CAST(path AS BLOB)), LENGTH(CAST(content_hash AS BLOB)))), 0) AS metadata_bytes, '
          "COALESCE(MIN(TYPEOF(size) = 'integer' AND TYPEOF(updated_at) = 'integer'), 1) AS valid_numbers FROM project_files",
        )
        .getSingle();
    if (bound.read<int>('row_count') > 1 ||
        bound.read<int>('max_bytes') > maxDraftBytes ||
        bound.read<int>('metadata_bytes') > 128 ||
        bound.read<int>('valid_numbers') != 1) {
      throw const DraftStorageException(DraftStorageFailure.corrupt);
    }
    final QueryRow projectsBound = await _database
        .customSelect(
          'SELECT COUNT(*) AS row_count, COALESCE(MAX(MAX(LENGTH(CAST(id AS BLOB)), '
          'LENGTH(CAST(name AS BLOB)))), 0) AS max_bytes, '
          "COALESCE(MIN(TYPEOF(created_at) = 'integer' AND TYPEOF(updated_at) = 'integer'), 1) AS valid_numbers FROM projects",
        )
        .getSingle();
    if (projectsBound.read<int>('row_count') > 1 ||
        projectsBound.read<int>('max_bytes') > 128 ||
        projectsBound.read<int>('valid_numbers') != 1) {
      throw const DraftStorageException(DraftStorageFailure.corrupt);
    }
    final List<ProjectFile> files = await _database
        .select(_database.projectFiles)
        .get();
    final List<Project> projects = await _database
        .select(_database.projects)
        .get();
    if (metadata['empty'] == true) {
      if (files.isNotEmpty || projects.isNotEmpty) {
        throw const DraftStorageException(DraftStorageFailure.corrupt);
      }
      return DraftRead(generation: generation);
    }
    if (files.length != 1 || projects.length != 1) {
      throw const DraftStorageException(DraftStorageFailure.corrupt);
    }
    final ProjectFile file = files.single;
    final Project project = projects.single;
    if (file.id != _fileId ||
        file.projectId != _projectId ||
        project.id != _projectId ||
        metadata['documentId'] != _fileId ||
        metadata['name'] != file.path ||
        metadata['size'] != file.size ||
        metadata['hash'] != file.contentHash ||
        metadata['time'] != file.updatedAt ||
        metadata['time'] is! int) {
      throw const DraftStorageException(DraftStorageFailure.corrupt);
    }
    // Isolate the potentially megabyte-sized UTF-8 conversion, validation and
    // SHA-256. No source is passed to loggers or platform channels.
    final Uint8List bytes = file.content;
    final String name = file.path;
    final String hash = file.contentHash;
    final Object? origin = metadata['originPath'];
    final int time = file.updatedAt;
    return _decodeInBackground(
      bytes,
      name,
      hash,
      origin,
      time,
      generation,
      file.size,
    );
  }

  @override
  Future<void> write(
    DraftSnapshot snapshot, {
    required int expectedGeneration,
  }) => _serialized(() async {
    _checkNext(snapshot.generation, expectedGeneration);
    final _Prepared prepared = await _prepareInBackground(snapshot);
    await _database.transaction(() async {
      final DraftRead current = await _read();
      if (current.generation != expectedGeneration) {
        throw const DraftStorageException(DraftStorageFailure.conflict);
      }
      final int time = snapshot.checkpointTime.toUtc().millisecondsSinceEpoch;
      await _database
          .into(_database.projects)
          .insertOnConflictUpdate(
            ProjectsCompanion.insert(
              id: _projectId,
              name: _projectId,
              createdAt: time,
              updatedAt: time,
            ),
          );
      await _database
          .into(_database.projectFiles)
          .insertOnConflictUpdate(
            ProjectFilesCompanion.insert(
              id: _fileId,
              projectId: _projectId,
              path: snapshot.name,
              content: prepared.bytes,
              size: prepared.bytes.length,
              contentHash: prepared.hash,
              updatedAt: time,
            ),
          );
      await _storeMetadata(<String, Object?>{
        'version': 1,
        'generation': snapshot.generation,
        'empty': false,
        'documentId': _fileId,
        'name': snapshot.name,
        'size': prepared.bytes.length,
        'hash': prepared.hash,
        'time': time,
        'originPath': snapshot.originPath,
      });
    });
  });

  @override
  Future<int> clear({required int expectedGeneration}) => _serialized(() async {
    final int next = expectedGeneration + 1;
    _checkNext(next, expectedGeneration);
    return _database.transaction(() async {
      if ((await _read()).generation != expectedGeneration) {
        throw const DraftStorageException(DraftStorageFailure.conflict);
      }
      await _database.delete(_database.projectFiles).go();
      await _database.delete(_database.projects).go();
      await _storeMetadata(<String, Object?>{
        'version': 1,
        'generation': next,
        'empty': true,
      });
      return next;
    });
  });

  Future<void> _storeMetadata(Map<String, Object?> value) => _database
      .into(_database.settings)
      .insertOnConflictUpdate(
        SettingsCompanion.insert(key: _slotKey, value: jsonEncode(value)),
      )
      .then((_) {});

  static void _checkNext(int next, int expected) {
    if (expected < 0 || next <= expected || next > 0x1fffffffffffff) {
      throw const DraftStorageException(DraftStorageFailure.conflict);
    }
  }

  @override
  Future<void> close() => _closeFuture ??= _close();

  Future<void> _close() async {
    _accepting = false;
    await _tail;
    if (_closed) return;
    _closed = true;
    await _database.close();
  }
}

class _Prepared {
  const _Prepared(this.bytes, this.hash);
  final Uint8List bytes;
  final String hash;
}

_Prepared _prepare(DraftSnapshot snapshot) {
  _validateName(snapshot.name);
  final String? origin = snapshot.originPath;
  if (origin != null) {
    if (!origin.startsWith('/') ||
        origin == '/' ||
        origin.contains('\\') ||
        origin
            .split('/')
            .skip(1)
            .any((String s) => s.isEmpty || s == '.' || s == '..') ||
        _hasControls(origin) ||
        !_wellFormed(origin) ||
        utf8.encode(origin).length > 128) {
      throw const DraftStorageException(DraftStorageFailure.invalidMetadata);
    }
  }
  if (!_wellFormed(snapshot.content)) {
    throw const DraftStorageException(DraftStorageFailure.invalidText);
  }
  final Uint8List bytes = utf8.encode(snapshot.content);
  if (bytes.length > maxDraftBytes) {
    throw const DraftStorageException(DraftStorageFailure.tooLarge);
  }
  return _Prepared(bytes, sha256.convert(bytes).toString());
}

void _validateName(String name) {
  if (name.isEmpty ||
      name == '.' ||
      name == '..' ||
      name.contains('/') ||
      name.contains('\\') ||
      _hasControls(name) ||
      !_wellFormed(name) ||
      utf8.encode(name).length > 128) {
    throw const DraftStorageException(DraftStorageFailure.invalidMetadata);
  }
}

bool _hasControls(String value) =>
    value.runes.any((int c) => c < 0x20 || (c >= 0x7f && c <= 0x9f));

bool _wellFormed(String value) {
  for (int i = 0; i < value.length; i++) {
    final int unit = value.codeUnitAt(i);
    if (unit >= 0xd800 && unit <= 0xdbff) {
      if (++i >= value.length) return false;
      final int next = value.codeUnitAt(i);
      if (next < 0xdc00 || next > 0xdfff) return false;
    } else if (unit >= 0xdc00 && unit <= 0xdfff) {
      return false;
    }
  }
  return true;
}

Future<_Prepared> _prepareInBackground(DraftSnapshot snapshot) =>
    Isolate.run(() => _prepare(snapshot));

Future<DraftRead> _decodeInBackground(
  Uint8List bytes,
  String name,
  String hash,
  Object? origin,
  int time,
  int generation,
  int expectedSize,
) => Isolate.run(() {
  try {
    if (origin != null && origin is! String) {
      throw const DraftStorageException(DraftStorageFailure.corrupt);
    }
    final String content = utf8.decode(bytes, allowMalformed: false);
    final DraftSnapshot snapshot = DraftSnapshot(
      name: name,
      content: content,
      originPath: origin as String?,
      generation: generation,
      checkpointTime: DateTime.fromMillisecondsSinceEpoch(time, isUtc: true),
    );
    final _Prepared prepared = _prepare(snapshot);
    if (bytes.length != expectedSize ||
        prepared.hash != hash ||
        prepared.bytes.length != bytes.length) {
      throw const DraftStorageException(DraftStorageFailure.corrupt);
    }
    return DraftRead(generation: generation, snapshot: snapshot);
  } catch (_) {
    throw const DraftStorageException(DraftStorageFailure.corrupt);
  }
});

DraftStorageException _safeException(Object error) {
  if (error is DriftRemoteException) return _safeException(error.remoteCause);
  if (error is DraftStorageException) return error;
  if (error is SqliteException && <int>{11, 26}.contains(error.resultCode)) {
    return const DraftStorageException(DraftStorageFailure.corrupt);
  }
  return const DraftStorageException(DraftStorageFailure.unavailable);
}

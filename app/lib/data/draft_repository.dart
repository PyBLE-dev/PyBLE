// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

/// Neutral local current-text recovery seam (ADR-0048).
library;

/// One complete, immutable local checkpoint. Origin is historical context,
/// never authority to write to a board.
class DraftSnapshot {
  const DraftSnapshot({
    required this.name,
    required this.content,
    this.originPath,
    required this.generation,
    required this.checkpointTime,
  });

  final String name;
  final String content;
  final String? originPath;
  final int generation;
  final DateTime checkpointTime;
}

/// A committed slot, including a high-water generation for an empty tombstone.
class DraftRead {
  const DraftRead({required this.generation, this.snapshot});
  final int generation;
  final DraftSnapshot? snapshot;
}

/// Bounded reasons suitable for localized UI; never includes user source/path.
enum DraftStorageFailure {
  unavailable,
  corrupt,
  unsupportedVersion,
  invalidMetadata,
  invalidText,
  tooLarge,
  conflict,
}

class DraftStorageException implements Exception {
  const DraftStorageException(this.reason);
  final DraftStorageFailure reason;

  @override
  String toString() => 'DraftStorageException(${reason.name})';
}

/// Sole serialized writer for one local slot. A successful Future means that
/// its matching transaction committed, not that a board was contacted.
abstract interface class DraftRepository {
  Future<DraftRead> load();
  Future<void> write(DraftSnapshot snapshot, {required int expectedGeneration});
  Future<int> clear({required int expectedGeneration});
  Future<void> close();
}

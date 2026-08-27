// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

import 'dart:async';
import 'dart:typed_data';

/// The only repository URL shape accepted by the public GitHub importer.
final class RepositoryLocator {
  const RepositoryLocator._({
    required this.canonicalRoot,
    required this.owner,
    required this.repo,
  });

  /// Parses `https://github.com/<owner>/<repo>` without accepting a broader
  /// web URL or silently discarding authority/path components.
  factory RepositoryLocator.parse(String value) {
    if (value != value.trim() || value.isEmpty) {
      throw const GithubFailure(GithubFailureKind.invalidInput);
    }

    final Uri? candidate = Uri.tryParse(value);
    final int authorityStart = value.indexOf('://') + 3;
    final int authorityEnd = value.indexOf('/', authorityStart);
    final String rawAuthority = authorityStart >= 3 && authorityEnd >= 0
        ? value.substring(authorityStart, authorityEnd)
        : '';
    if (candidate == null ||
        !candidate.hasAuthority ||
        candidate.scheme != 'https' ||
        candidate.host != 'github.com' ||
        rawAuthority != 'github.com' ||
        candidate.userInfo.isNotEmpty ||
        candidate.hasPort ||
        candidate.hasQuery ||
        candidate.hasFragment) {
      throw const GithubFailure(GithubFailureKind.invalidInput);
    }

    // GitHub repository owner/name syntax is ASCII, so percent escapes are
    // unnecessary here. Rejecting them also prevents encoded separators and
    // non-canonical dot segments from changing the logical path after decode.
    final String rawPath = candidate.path;
    if (rawPath.contains('%')) {
      throw const GithubFailure(GithubFailureKind.invalidInput);
    }
    final String normalizedPath = rawPath.endsWith('/')
        ? rawPath.substring(0, rawPath.length - 1)
        : rawPath;
    final List<String> segments = normalizedPath.split('/');
    if (segments.length != 3 || segments.first.isNotEmpty) {
      throw const GithubFailure(GithubFailureKind.invalidInput);
    }

    final String owner = segments[1];
    final String repo = segments[2];
    if (!_isOwner(owner) ||
        !_isRepositoryName(repo) ||
        repo.toLowerCase().endsWith('.git')) {
      throw const GithubFailure(GithubFailureKind.invalidInput);
    }

    return RepositoryLocator._(
      canonicalRoot: Uri(
        scheme: 'https',
        host: 'github.com',
        pathSegments: <String>[owner, repo],
      ),
      owner: owner,
      repo: repo,
    );
  }

  final Uri canonicalRoot;
  final String owner;
  final String repo;

  static final RegExp _ownerPattern = RegExp(r'^[A-Za-z0-9][A-Za-z0-9-]*$');
  static final RegExp _repoPattern = RegExp(r'^[A-Za-z0-9_.-]+$');

  static bool _isOwner(String value) =>
      value.length <= 39 &&
      _ownerPattern.hasMatch(value) &&
      !value.endsWith('-') &&
      !value.contains('--');

  static bool _isRepositoryName(String value) =>
      value.length <= 100 &&
      value != '.' &&
      value != '..' &&
      _repoPattern.hasMatch(value);

  @override
  bool operator ==(Object other) =>
      other is RepositoryLocator &&
      canonicalRoot == other.canonicalRoot &&
      owner == other.owner &&
      repo == other.repo;

  @override
  int get hashCode => Object.hash(canonicalRoot, owner, repo);

  @override
  String toString() => canonicalRoot.toString();
}

/// One immutable repository snapshot and its root Git tree.
final class PinnedRepository {
  const PinnedRepository({
    required this.locator,
    required this.requestedRef,
    required this.resolvedRef,
    required this.commitSha,
    required this.rootTreeSha,
  });

  final RepositoryLocator locator;
  final String requestedRef;
  final String resolvedRef;
  final String commitSha;
  final String rootTreeSha;
}

/// One complete, bounded branch catalog for a public repository.
final class GithubBranchCatalog {
  GithubBranchCatalog({
    required this.locator,
    required this.defaultBranch,
    required List<String> branches,
  }) : branches = List<String>.unmodifiable(branches);

  final RepositoryLocator locator;
  final String defaultBranch;
  final List<String> branches;
}

enum GithubEntryKind { regularFile, directory, ineligible }

/// A direct child returned by one non-recursive Git tree request.
final class GithubEntry {
  const GithubEntry({
    required this.name,
    required this.remotePath,
    required this.kind,
    required this.objectSha,
    required this.declaredSize,
  });

  final String name;
  final String remotePath;
  final GithubEntryKind kind;
  final String objectSha;
  final int declaredSize;

  /// Only ordinary Git blobs with a lowercase `.py` suffix may be selected.
  bool get isSelectablePythonFile =>
      kind == GithubEntryKind.regularFile && name.endsWith('.py');
}

/// The verified result of reading exactly one Git tree.
final class GithubDirectory {
  GithubDirectory({
    required this.remotePath,
    required this.treeSha,
    required List<GithubEntry> entries,
  }) : entries = List<GithubEntry>.unmodifiable(entries);

  final String remotePath;
  final String treeSha;
  final List<GithubEntry> entries;
}

/// Stable error categories consumed by controller and localized UI layers.
enum GithubFailureKind {
  invalidInput,
  offline,
  notFound,
  privateOrForbidden,
  rateLimited,
  server,
  malformedResponse,
  tooManyBranches,
  invalidTarget,
  protectedRootTarget,
  duplicateTarget,
  pathTooLong,
  blockingConflict,
  overwriteRequired,
  invalidUtf8,
  nulByte,
  fileTooLarge,
  batchTooLarge,
  conflictChanged,
  incompleteBoardListing,
  staleSession,
  board,
  cancelled,
}

/// Per-operation cancellation passed to the HTTP adapter.
///
/// Completing [whenCancelled] is compatible with package:http's abortable
/// requests. A token is single-use and carries no repository or board data.
final class GithubCancellation {
  final Completer<void> _trigger = Completer<void>();

  bool get isCancelled => _trigger.isCompleted;
  Future<void> get whenCancelled => _trigger.future;

  void cancel() {
    if (!_trigger.isCompleted) _trigger.complete();
  }
}

/// A sanitized failure: it carries no response body, fetched bytes, or cause.
final class GithubFailure implements Exception {
  const GithubFailure(
    this.kind, {
    this.path,
    this.rateLimitRemaining,
    this.rateLimitReset,
    this.retryAfter,
  });

  final GithubFailureKind kind;
  final String? path;
  final int? rateLimitRemaining;
  final DateTime? rateLimitReset;
  final Duration? retryAfter;

  @override
  String toString() => path == null
      ? 'GithubFailure(${kind.name})'
      : 'GithubFailure(${kind.name}, path: $path)';
}

/// Injected, board-independent seam for immutable public repository reads.
abstract interface class GithubApi {
  Future<GithubBranchCatalog> listBranches(
    RepositoryLocator locator, {
    GithubCancellation? cancellation,
  });

  Future<PinnedRepository> resolve(
    RepositoryLocator locator, {
    String ref = '',
    GithubCancellation? cancellation,
  });

  Future<GithubDirectory> listDirectory(
    PinnedRepository repository, {
    required String treeSha,
    required String remotePath,
    GithubCancellation? cancellation,
  });

  Future<Uint8List> fetchFile(
    PinnedRepository repository,
    GithubEntry entry, {
    GithubCancellation? cancellation,
  });
}

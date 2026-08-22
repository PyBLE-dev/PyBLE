// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:http/http.dart' as http;

import 'github_models.dart';

enum _AbortCause { none, cancelled, timeout }

/// Public, unauthenticated GitHub REST adapter used by the import controller.
///
/// Every content read is addressed by a Git object SHA reached from one pinned
/// commit. Returned links are never followed and redirects are disabled.
final class GithubRepositoryClient implements GithubApi {
  GithubRepositoryClient({
    required http.Client httpClient,
    Duration timeout = const Duration(seconds: 20),
  }) : this._(httpClient, timeout);

  GithubRepositoryClient._(this._httpClient, this._timeout);

  static const String _apiHost = 'api.github.com';
  static const String _accept = 'application/vnd.github+json';
  static const String _apiVersion = '2026-03-10';
  static const String _userAgent = 'PyBLE/0.1.0';
  static const int _metadataBodyLimit = 1024 * 1024;
  static const int _treeBodyLimit = 2 * 1024 * 1024;
  static const int _blobBodyLimit = 2 * 1024 * 1024;
  static const int _maximumDirectTreeEntries = 512;

  final http.Client _httpClient;
  final Duration _timeout;

  @override
  Future<PinnedRepository> resolve(
    RepositoryLocator locator, {
    String ref = '',
    GithubCancellation? cancellation,
  }) async {
    final String requestedRef = _normalizeRequestedRef(
      ref,
      path: locator.canonicalRoot.toString(),
    );
    String resolvedRef = requestedRef;

    if (resolvedRef.isEmpty) {
      final _RestResponse metadata = await _get(
        _repositoryUri(locator),
        failurePath: locator.canonicalRoot.toString(),
        maximumBodyBytes: _metadataBodyLimit,
        cancellation: cancellation,
      );
      final Map<String, Object?> object = _decodeObject(
        metadata.bytes,
        path: locator.canonicalRoot.toString(),
      );
      final Object? defaultBranch = object['default_branch'];
      if (defaultBranch is! String ||
          !_isValidRef(defaultBranch) ||
          defaultBranch.trim() != defaultBranch) {
        throw GithubFailure(
          GithubFailureKind.malformedResponse,
          path: locator.canonicalRoot.toString(),
        );
      }
      resolvedRef = defaultBranch;
    }

    final _RestResponse commitResponse = await _get(
      _repositoryUri(locator, <String>['commits', resolvedRef]),
      failurePath: locator.canonicalRoot.toString(),
      maximumBodyBytes: _metadataBodyLimit,
      cancellation: cancellation,
    );
    final Map<String, Object?> commit = _decodeObject(
      commitResponse.bytes,
      path: locator.canonicalRoot.toString(),
    );
    final String commitSha = _requiredObjectSha(
      commit['sha'],
      path: locator.canonicalRoot.toString(),
    );
    final Map<String, Object?> commitDetails = _requiredObject(
      commit['commit'],
      path: locator.canonicalRoot.toString(),
    );
    final Map<String, Object?> tree = _requiredObject(
      commitDetails['tree'],
      path: locator.canonicalRoot.toString(),
    );
    final String rootTreeSha = _requiredObjectSha(
      tree['sha'],
      path: locator.canonicalRoot.toString(),
    );

    return PinnedRepository(
      locator: locator,
      requestedRef: requestedRef,
      resolvedRef: resolvedRef,
      commitSha: commitSha,
      rootTreeSha: rootTreeSha,
    );
  }

  @override
  Future<GithubDirectory> listDirectory(
    PinnedRepository repository, {
    required String treeSha,
    required String remotePath,
    GithubCancellation? cancellation,
  }) async {
    if (!_isObjectSha(treeSha) || !_isSafeRemoteDirectory(remotePath)) {
      throw GithubFailure(GithubFailureKind.invalidInput, path: remotePath);
    }

    final _RestResponse response = await _get(
      _repositoryUri(repository.locator, <String>['git', 'trees', treeSha]),
      failurePath: remotePath,
      maximumBodyBytes: _treeBodyLimit,
      cancellation: cancellation,
    );
    final Map<String, Object?> object = _decodeObject(
      response.bytes,
      path: remotePath,
    );
    if (object['sha'] != treeSha || object['truncated'] != false) {
      throw GithubFailure(
        GithubFailureKind.malformedResponse,
        path: remotePath,
      );
    }
    final Object? rawEntries = object['tree'];
    if (rawEntries is! List<Object?>) {
      throw GithubFailure(
        GithubFailureKind.malformedResponse,
        path: remotePath,
      );
    }
    if (rawEntries.length > _maximumDirectTreeEntries) {
      throw GithubFailure(
        GithubFailureKind.malformedResponse,
        path: remotePath,
      );
    }

    final List<GithubEntry> entries = <GithubEntry>[];
    for (final Object? rawEntry in rawEntries) {
      final Map<String, Object?> entry = _requiredObject(
        rawEntry,
        path: remotePath,
      );
      final String name = _requiredDirectChildName(
        entry['path'],
        path: remotePath,
      );
      final Object? rawMode = entry['mode'];
      final Object? rawType = entry['type'];
      if (rawMode is! String || rawType is! String) {
        throw GithubFailure(
          GithubFailureKind.malformedResponse,
          path: _joinRemotePath(remotePath, name),
        );
      }
      final String objectSha = _requiredObjectSha(
        entry['sha'],
        path: _joinRemotePath(remotePath, name),
      );
      final GithubEntryKind kind = _entryKind(mode: rawMode, type: rawType);
      final Object? rawSize = entry['size'];
      final int declaredSize;
      if (kind == GithubEntryKind.regularFile) {
        if (rawSize is! int || rawSize < 0) {
          throw GithubFailure(
            GithubFailureKind.malformedResponse,
            path: _joinRemotePath(remotePath, name),
          );
        }
        declaredSize = rawSize;
      } else if (rawSize == null) {
        declaredSize = 0;
      } else if (rawSize is int && rawSize >= 0) {
        declaredSize = rawSize;
      } else {
        throw GithubFailure(
          GithubFailureKind.malformedResponse,
          path: _joinRemotePath(remotePath, name),
        );
      }

      entries.add(
        GithubEntry(
          name: name,
          remotePath: _joinRemotePath(remotePath, name),
          kind: kind,
          objectSha: objectSha,
          declaredSize: declaredSize,
        ),
      );
    }

    return GithubDirectory(
      remotePath: remotePath,
      treeSha: treeSha,
      entries: entries,
    );
  }

  @override
  Future<Uint8List> fetchFile(
    PinnedRepository repository,
    GithubEntry entry, {
    GithubCancellation? cancellation,
  }) async {
    if (!entry.isSelectablePythonFile || !_isObjectSha(entry.objectSha)) {
      throw GithubFailure(
        GithubFailureKind.invalidInput,
        path: entry.remotePath,
      );
    }

    final _RestResponse response = await _get(
      _repositoryUri(repository.locator, <String>[
        'git',
        'blobs',
        entry.objectSha,
      ]),
      failurePath: entry.remotePath,
      maximumBodyBytes: _blobBodyLimit,
      cancellation: cancellation,
    );
    final Map<String, Object?> object = _decodeObject(
      response.bytes,
      path: entry.remotePath,
    );
    if (object['sha'] != entry.objectSha || object['encoding'] != 'base64') {
      throw GithubFailure(
        GithubFailureKind.malformedResponse,
        path: entry.remotePath,
      );
    }
    final Object? rawContent = object['content'];
    final Object? rawSize = object['size'];
    if (rawContent is! String || rawSize is! int || rawSize < 0) {
      throw GithubFailure(
        GithubFailureKind.malformedResponse,
        path: entry.remotePath,
      );
    }

    try {
      final String compactContent = rawContent.replaceAll(
        RegExp(r'[\t\n\r ]'),
        '',
      );
      final Uint8List bytes = base64.decode(compactContent);
      if (rawSize != entry.declaredSize || bytes.length != rawSize) {
        throw GithubFailure(
          GithubFailureKind.malformedResponse,
          path: entry.remotePath,
        );
      }
      return bytes;
    } on FormatException {
      throw GithubFailure(
        GithubFailureKind.malformedResponse,
        path: entry.remotePath,
      );
    }
  }

  Uri _repositoryUri(
    RepositoryLocator locator, [
    List<String> suffix = const <String>[],
  ]) => Uri(
    scheme: 'https',
    host: _apiHost,
    pathSegments: <String>['repos', locator.owner, locator.repo, ...suffix],
  );

  Future<_RestResponse> _get(
    Uri uri, {
    required String failurePath,
    required int maximumBodyBytes,
    GithubCancellation? cancellation,
  }) async {
    if (uri.scheme != 'https' ||
        uri.host != _apiHost ||
        uri.hasPort ||
        uri.userInfo.isNotEmpty) {
      throw GithubFailure(GithubFailureKind.invalidInput, path: failurePath);
    }

    if (cancellation?.isCancelled ?? false) {
      throw GithubFailure(GithubFailureKind.cancelled, path: failurePath);
    }

    final Completer<void> abortTrigger = Completer<void>();
    _AbortCause abortCause = _AbortCause.none;
    void abort(_AbortCause cause) {
      if (abortCause != _AbortCause.none) return;
      abortCause = cause;
      abortTrigger.complete();
    }

    final GithubCancellation? operationCancellation = cancellation;
    if (operationCancellation != null) {
      unawaited(
        operationCancellation.whenCancelled.then(
          (_) => abort(_AbortCause.cancelled),
        ),
      );
    }

    final http.AbortableRequest request =
        http.AbortableRequest('GET', uri, abortTrigger: abortTrigger.future)
          ..followRedirects = false
          ..maxRedirects = 0
          ..headers.addAll(const <String, String>{
            'Accept': _accept,
            'X-GitHub-Api-Version': _apiVersion,
            'User-Agent': _userAgent,
          });

    Future<_RestResponse> sendAndRead() async {
      final http.StreamedResponse streamed = await _httpClient.send(request);
      final GithubFailure? statusFailure = _statusFailure(
        streamed.statusCode,
        streamed.headers,
        path: failurePath,
      );
      if (statusFailure != null) {
        await _cancelResponseBody(streamed, abort: abort);
        throw statusFailure;
      }
      final int? declaredLength = streamed.contentLength;
      if (declaredLength != null && declaredLength > maximumBodyBytes) {
        await _cancelResponseBody(streamed, abort: abort);
        throw GithubFailure(
          GithubFailureKind.malformedResponse,
          path: failurePath,
        );
      }

      final BytesBuilder body = BytesBuilder(copy: false);
      int received = 0;
      await for (final List<int> chunk in streamed.stream) {
        received += chunk.length;
        if (received > maximumBodyBytes) {
          throw GithubFailure(
            GithubFailureKind.malformedResponse,
            path: failurePath,
          );
        }
        body.add(chunk);
      }
      return _RestResponse(bytes: body.takeBytes());
    }

    try {
      return await sendAndRead().timeout(
        _timeout,
        onTimeout: () {
          final bool wasCancelled = abortCause == _AbortCause.cancelled;
          abort(_AbortCause.timeout);
          if (wasCancelled) {
            throw GithubFailure(GithubFailureKind.cancelled, path: failurePath);
          }
          throw TimeoutException('GitHub request deadline expired');
        },
      );
    } on GithubFailure {
      rethrow;
    } on http.RequestAbortedException {
      throw GithubFailure(
        abortCause == _AbortCause.timeout
            ? GithubFailureKind.offline
            : GithubFailureKind.cancelled,
        path: failurePath,
      );
    } on TimeoutException {
      throw GithubFailure(GithubFailureKind.offline, path: failurePath);
    } on SocketException {
      throw GithubFailure(GithubFailureKind.offline, path: failurePath);
    } on http.ClientException {
      throw GithubFailure(
        abortCause == _AbortCause.cancelled
            ? GithubFailureKind.cancelled
            : GithubFailureKind.offline,
        path: failurePath,
      );
    }
  }

  Future<void> _cancelResponseBody(
    http.StreamedResponse response, {
    required void Function(_AbortCause cause) abort,
  }) async {
    try {
      final StreamSubscription<List<int>> subscription = response.stream.listen(
        (_) {},
        onError: (Object _, StackTrace _) {},
      );
      await subscription.cancel().timeout(
        _timeout,
        onTimeout: () => abort(_AbortCause.timeout),
      );
    } catch (_) {
      // Preserve the already-classified response failure while still asking an
      // abort-aware transport to release the rejected response resources.
      abort(_AbortCause.cancelled);
    }
  }

  static GithubFailure? _statusFailure(
    int statusCode,
    Map<String, String> headers, {
    required String path,
  }) {
    if (statusCode == HttpStatus.ok) {
      return null;
    }

    final int? remaining = _boundedIntegerHeader(
      headers,
      'x-ratelimit-remaining',
      maximum: 1000000000,
    );
    final DateTime? reset = _rateLimitReset(headers);
    final Duration? retryAfter = _retryAfter(headers);
    final bool isRateLimited =
        statusCode == HttpStatus.tooManyRequests ||
        (statusCode == HttpStatus.forbidden &&
            (remaining == 0 || retryAfter != null));
    if (isRateLimited) {
      return GithubFailure(
        GithubFailureKind.rateLimited,
        path: path,
        rateLimitRemaining: remaining,
        rateLimitReset: reset,
        retryAfter: retryAfter,
      );
    }
    if (statusCode == HttpStatus.notFound) {
      return GithubFailure(GithubFailureKind.notFound, path: path);
    }
    if (statusCode == HttpStatus.unauthorized ||
        statusCode == HttpStatus.forbidden) {
      return GithubFailure(GithubFailureKind.privateOrForbidden, path: path);
    }
    if (statusCode >= 500 && statusCode <= 599) {
      return GithubFailure(GithubFailureKind.server, path: path);
    }
    return GithubFailure(GithubFailureKind.malformedResponse, path: path);
  }

  static int? _boundedIntegerHeader(
    Map<String, String> headers,
    String name, {
    required int maximum,
  }) {
    final String? raw = _header(headers, name);
    final int? value = raw == null ? null : int.tryParse(raw);
    return value != null && value >= 0 && value <= maximum ? value : null;
  }

  static DateTime? _rateLimitReset(Map<String, String> headers) {
    const int maximumUnixSeconds = 253402300799;
    final int? seconds = _boundedIntegerHeader(
      headers,
      'x-ratelimit-reset',
      maximum: maximumUnixSeconds,
    );
    return seconds == null
        ? null
        : DateTime.fromMillisecondsSinceEpoch(seconds * 1000, isUtc: true);
  }

  static Duration? _retryAfter(Map<String, String> headers) {
    const int maximumRetrySeconds = 24 * 60 * 60;
    final String? raw = _header(headers, 'retry-after');
    if (raw == null) {
      return null;
    }
    final int? seconds = int.tryParse(raw);
    if (seconds != null) {
      return seconds >= 0 && seconds <= maximumRetrySeconds
          ? Duration(seconds: seconds)
          : null;
    }
    try {
      final Duration delay = HttpDate.parse(
        raw,
      ).toUtc().difference(DateTime.now().toUtc());
      return !delay.isNegative && delay <= const Duration(days: 1)
          ? delay
          : null;
    } on FormatException {
      return null;
    } on HttpException {
      return null;
    }
  }

  static String? _header(Map<String, String> headers, String name) {
    for (final MapEntry<String, String> header in headers.entries) {
      if (header.key.toLowerCase() == name) {
        return header.value.trim();
      }
    }
    return null;
  }

  static Map<String, Object?> _decodeObject(
    Uint8List bytes, {
    required String path,
  }) {
    try {
      final Object? decoded = jsonDecode(
        utf8.decode(bytes, allowMalformed: false),
      );
      return _requiredObject(decoded, path: path);
    } on FormatException {
      throw GithubFailure(GithubFailureKind.malformedResponse, path: path);
    }
  }

  static Map<String, Object?> _requiredObject(
    Object? value, {
    required String path,
  }) {
    if (value is Map<String, Object?>) {
      return value;
    }
    throw GithubFailure(GithubFailureKind.malformedResponse, path: path);
  }

  static String _requiredObjectSha(Object? value, {required String path}) {
    if (value is String && _isObjectSha(value)) {
      return value;
    }
    throw GithubFailure(GithubFailureKind.malformedResponse, path: path);
  }

  static String _requiredDirectChildName(
    Object? value, {
    required String path,
  }) {
    if (value is String &&
        value.isNotEmpty &&
        value != '.' &&
        value != '..' &&
        !value.contains('/') &&
        !value.contains(r'\') &&
        !value.contains('\u0000') &&
        !value.runes.any((int rune) => rune < 0x20 || rune == 0x7f)) {
      return value;
    }
    throw GithubFailure(GithubFailureKind.malformedResponse, path: path);
  }

  static GithubEntryKind _entryKind({
    required String mode,
    required String type,
  }) {
    if (type == 'blob' && (mode == '100644' || mode == '100755')) {
      return GithubEntryKind.regularFile;
    }
    if (type == 'tree' && mode == '040000') {
      return GithubEntryKind.directory;
    }
    return GithubEntryKind.ineligible;
  }

  static String _normalizeRequestedRef(String value, {required String path}) {
    final String raw = value;
    final String trimmed = raw.trim();
    if (trimmed.isEmpty) {
      return '';
    }
    if (raw != trimmed || !_isValidRef(raw)) {
      throw GithubFailure(GithubFailureKind.invalidInput, path: path);
    }
    return raw;
  }

  static bool _isValidRef(String value) =>
      value.isNotEmpty &&
      utf8.encode(value).length <= 256 &&
      !value.contains('\u0000') &&
      !value.contains(r'\') &&
      !value.runes.any((int rune) => rune < 0x20 || rune == 0x7f);

  static bool _isObjectSha(String value) =>
      RegExp(r'^(?:[0-9a-f]{40}|[0-9a-f]{64})$').hasMatch(value);

  static bool _isSafeRemoteDirectory(String value) {
    if (value.isEmpty) {
      return true;
    }
    if (value.startsWith('/') ||
        value.endsWith('/') ||
        value.contains(r'\') ||
        value.contains('\u0000')) {
      return false;
    }
    final List<String> segments = value.split('/');
    return segments.every(
      (String segment) =>
          segment.isNotEmpty &&
          segment != '.' &&
          segment != '..' &&
          !segment.runes.any((int rune) => rune < 0x20 || rune == 0x7f),
    );
  }

  static String _joinRemotePath(String directory, String name) =>
      directory.isEmpty ? name : '$directory/$name';
}

final class _RestResponse {
  const _RestResponse({required this.bytes});

  final Uint8List bytes;
}

// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:http/http.dart' as http;

import 'github_models.dart';
import 'github_repository_client.dart';

/// The sole production public-REST composition point.
///
/// Presentation imports only this neutral [GithubApi] provider. Tests replace
/// it with an in-memory adapter, and the owned client closes with its container.
final Provider<GithubApi> githubApiProvider = Provider<GithubApi>((Ref ref) {
  final http.Client client = http.Client();
  ref.onDispose(client.close);
  return GithubRepositoryClient(httpClient: client);
});

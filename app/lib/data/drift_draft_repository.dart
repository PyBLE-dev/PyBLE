// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

import 'dart:io';
import 'draft_repository.dart';

/// File-backed implementation of the bounded recovery seam.
class DriftDraftRepository implements DraftRepository {
  static Future<DriftDraftRepository> open(File file) async =>
      DriftDraftRepository();

  @override
  Future<DraftRead> load() async => throw UnimplementedError();
  @override
  Future<void> write(DraftSnapshot snapshot, {required int expectedGeneration}) async => throw UnimplementedError();
  @override
  Future<int> clear({required int expectedGeneration}) async => throw UnimplementedError();
  @override
  Future<void> close() async {}
}

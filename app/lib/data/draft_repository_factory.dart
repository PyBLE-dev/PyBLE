// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

import 'dart:io';

import 'package:path_provider/path_provider.dart';

import 'draft_repository.dart';
import 'drift_draft_repository.dart';

/// App-private Application Support, never temporary/cache/external storage.
/// Directory discovery is a platform-channel operation; SQLite and its source
/// validation/hash work run off the UI isolate. The caller handles failure
/// through the same preserved-store startup choices as a later I/O error.
Future<DraftRepository> openDraftRepository() async {
  try {
    final Directory directory = await getApplicationSupportDirectory();
    await directory.create(recursive: true);
    return await DriftDraftRepository.open(
      File('${directory.path}/pyble.sqlite'),
    );
  } on DraftStorageException {
    rethrow;
  } catch (_) {
    throw const DraftStorageException(DraftStorageFailure.unavailable);
  }
}

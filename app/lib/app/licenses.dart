// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

/// Registers licenses for vendored runtime assets that Pub cannot discover.
library;

import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';

bool _registered = false;

/// Adds the pinned Blockly Apache-2.0 text to Flutter's license registry.
///
/// Pub plugins register themselves, but the generated Blockly JavaScript is an
/// app asset built from a git submodule and therefore needs an explicit entry.
void registerBundledLicenses() {
  if (_registered) return;
  _registered = true;
  LicenseRegistry.addLicense(() async* {
    final String text = await rootBundle.loadString(
      'assets/licenses/PyBLE-LICENSE.txt',
    );
    yield LicenseEntryWithLineBreaks(<String>['PyBLE'], text);
  });
  LicenseRegistry.addLicense(() async* {
    final String text = await rootBundle.loadString(
      'assets/blockly/vendor/LICENSE',
    );
    yield LicenseEntryWithLineBreaks(<String>['Blockly'], text);
  });
}

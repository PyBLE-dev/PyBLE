// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

/// Runtime package metadata for the About page (FR-ABOUT-3).
///
/// This adapter is deliberately separate from `app_info.dart`: `kAppVersion`
/// is the static ASCII PBLE/1 HELLO identifier, while this file reads the
/// version and build number of the package that is actually installed.
library;

import 'package:flutter/foundation.dart';
import 'package:package_info_plus/package_info_plus.dart';

/// Immutable display metadata returned by [AppBuildInfoLoader].
@immutable
final class AppBuildInfo {
  const AppBuildInfo({required this.version, required this.buildNumber});

  /// Platform package version (`CFBundleShortVersionString` / `versionName`).
  final String version;

  /// Platform build number (`CFBundleVersion` / `versionCode`).
  final String buildNumber;
}

/// Injectable metadata seam so widget tests never depend on a platform channel.
typedef AppBuildInfoLoader = Future<AppBuildInfo> Function();

/// Reads metadata for the package that is actually running.
Future<AppBuildInfo> defaultAppBuildInfoLoader() async {
  final PackageInfo info = await PackageInfo.fromPlatform();
  final String version = info.version.trim();
  if (version.isEmpty) {
    throw const FormatException('installed package version is empty');
  }
  return AppBuildInfo(version: version, buildNumber: info.buildNumber.trim());
}

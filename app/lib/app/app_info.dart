// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

/// A-22 — the app's ASCII identity constants used on the PBLE/1 wire.
///
/// These are the `appName` / `appVersion` the production [PbleConnectionManager]
/// sends in HELLO (protocol.md §HELLO). They are HELLO WIRE IDENTIFIERS, not
/// user-facing copy, so they are deliberately NOT localized (FR-I18N-4) and MUST
/// stay 7-bit ASCII. Kept as plain consts (no `package_info_plus`, BLD-2) so the
/// wire identity is fixed and offline-derivable at build time.
///
/// The wordmark is also rendered in-app verbatim via the ARB (`appTitle`); this
/// const is the wire-facing twin, not a second display string.
library;

/// The PyBLE wordmark, sent as the HELLO client name (ASCII, FR-I18N-4).
const String kAppName = 'PyBLE';

/// The client version sent in HELLO (ASCII semver). Kept in step with the
/// `version:` field in `app/pubspec.yaml` (currently `0.2.0+5`); the build-
/// metadata suffix (`+5`) is dropped so the wire value is a clean semver.
const String kAppVersion = '0.2.0';

// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

/// PyBLE `lib/data/` — local, offline-first persistence for projects, settings,
/// and saved boards (Drift over SQLite) — see docs/specifications/app.md §2.
/// On-device content only: no accounts, no telemetry, no cloud, no
/// managed-fleet/classroom tables (SEC, DAT-8). Binds to the seam, not the wire.
///
/// The first implemented subset is one bounded current-text recovery slot
/// (ADR-0048 / PYB-006.2). Full projects, history and saved boards remain A-24.
library;

export 'draft_repository.dart';
export 'draft_repository_factory.dart';

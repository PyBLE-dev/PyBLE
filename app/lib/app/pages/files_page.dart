// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

/// The Files surface page (design-system.md §8; FR-FILES, FR-UI-6). This page is
/// a thin host that delegates to the feature-owned [FilesView] (A-30, ADR-0010,
/// TDD §11.6d): the live board file explorer, which itself renders the
/// disconnected guidance / connected explorer treatments keyed off the
/// read-only [connStateProvider] through the [Connection] seam (CON-8 — never
/// `lib/ble`). No display literal is authored here.
library;

import 'package:flutter/material.dart';

import 'package:pyble/files/files.dart';

/// The Files surface. A thin delegate onto the feature-owned [FilesView].
class FilesPage extends StatelessWidget {
  const FilesPage({super.key});

  @override
  Widget build(BuildContext context) => const FilesView();
}

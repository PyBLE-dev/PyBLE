// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

/// A-21 — the Console surface host. Delegates to the live [ConsoleView] in
/// `lib/console` (owner: app-editor-console-engineer), which renders the bounded
/// ring buffer subscribed to `Connection.console` (ADR-0010). This page is a
/// thin app-layer host: it bears no display copy (all strings live in the
/// feature view, sourced from `AppLocalizations`) and binds to no transport type
/// (CON-8, D2).
library;

import 'package:flutter/material.dart';

import 'package:pyble/console/console.dart';

/// The Console surface — the live console output + stdin.
class ConsolePage extends StatelessWidget {
  const ConsolePage({super.key});

  @override
  Widget build(BuildContext context) => const ConsoleView();
}

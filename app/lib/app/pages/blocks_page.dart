// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

/// Thin app-layer host for the A-31 Blocks feature.
library;

import 'package:flutter/material.dart';

import 'package:pyble/blocks/blocks.dart';

class BlocksPage extends StatelessWidget {
  const BlocksPage({super.key, this.onRunStarted});

  final VoidCallback? onRunStarted;

  @override
  Widget build(BuildContext context) => BlocksView(onRunStarted: onRunStarted);
}

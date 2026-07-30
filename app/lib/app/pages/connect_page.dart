// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

/// The Connect surface host (FR-CONNECT-1/2/5, A-22). A thin delegator to
/// [ConnectScreen] (owner: app-connect-engineer, `lib/connect`), which owns the
/// real scan → connect → use flow, connection diagnostics, and Board-info proof.
///
/// The shell references [ConnectPage] in its surface [IndexedStack]; keeping this
/// shim stable means the shell is unaffected as `lib/connect` evolves. The screen
/// binds only to the neutral [Connection]/`Scanner` seam — never `lib/ble`
/// (CON-8, FR-BLE-8).
library;

import 'package:flutter/material.dart';

import 'package:pyble/connect/connect.dart';

/// The Connect surface — hosts the scan/connect flow.
class ConnectPage extends StatelessWidget {
  const ConnectPage({super.key});

  @override
  Widget build(BuildContext context) => const ConnectScreen();
}

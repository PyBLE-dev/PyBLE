// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

/// A-21 — the working-loop console buffer (ADR-0010, TDD §11.6c, specs.md
/// FR-CONSOLE §4.7). A bounded ring subscribed to `Connection.console`, alive
/// independent of any console widget so output is captured even before the
/// Console surface is first opened AND survives tab/nav switches
/// (FR-CONSOLE-5/7). The shell keeps it alive from an always-mounted point.
///
/// The ring is the backpressure: it caps at [kConsoleMaxEvents], dropping the
/// oldest events. Bytes are stored raw — `lib/pble` never trims or decodes, and
/// this buffer keeps them verbatim so the console UI can render the raw
/// traceback (FR-ERR-2). Binds through the seam only (CON-8); mirroring to
/// `console_logs` (DAT-5) is the A-24 hook and is deliberately not done here.
library;

import 'dart:async';

import 'package:flutter/foundation.dart' show ValueListenable, ValueNotifier;
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'package:pyble/app/providers.dart';
import 'package:pyble/pble/pble.dart';

/// The console ring capacity: the oldest event is dropped past this bound.
const int kConsoleMaxEvents = 4000;

/// Subscribes the live `Connection.console` stream into a bounded, ordered ring
/// of [ConsoleEvent]s (ADR-0010, TDD §11.6c).
///
/// The ring is exposed two ways, always in lock-step:
///   * as the Notifier [state] (a `List<ConsoleEvent>`), which the contract's
///     `read(consoleBufferProvider)` API and the unit suites consume; and
///   * as [events], a [ValueListenable] the console WIDGETS observe via a
///     `ValueListenableBuilder`. Widgets deliberately do NOT `ref.watch` the
///     provider for rendering: flutter_riverpod flushes changes that originate
///     OUTSIDE the widget tree (a console stream event) via a post-frame
///     callback, so a `ref.watch` render would lag a frame; observing the
///     listenable directly rebuilds in the same frame the event arrives (the
///     same pattern the connection-status pill uses for `ConnState`).
class ConsoleBufferController extends Notifier<List<ConsoleEvent>> {
  final ValueNotifier<List<ConsoleEvent>> _events =
      ValueNotifier<List<ConsoleEvent>>(const <ConsoleEvent>[]);

  /// The ring as a directly-observable listenable (1-frame render for widgets).
  ValueListenable<List<ConsoleEvent>> get events => _events;

  @override
  List<ConsoleEvent> build() {
    // Re-subscribe if the seam identity ever changes; in production the facade
    // identity is stable, so this runs once and the buffer persists across the
    // widget lifecycle (kept alive by the shell, FR-CONSOLE-7).
    final Connection connection = ref.watch(connectionProvider);
    final StreamSubscription<ConsoleEvent> sub = connection.console.listen(
      _append,
    );
    ref.onDispose(sub.cancel);
    return _events.value;
  }

  void _append(ConsoleEvent event) {
    final List<ConsoleEvent> next = <ConsoleEvent>[..._events.value, event];
    final int overflow = next.length - kConsoleMaxEvents;
    if (overflow > 0) {
      next.removeRange(0, overflow);
    }
    _events.value = next;
    state = next;
  }

  /// Empties the ring (the console "clear" action, FR-CONSOLE-6).
  void clear() {
    _events.value = const <ConsoleEvent>[];
    state = const <ConsoleEvent>[];
  }

  /// Forwards a stdin line to the board (FR-CONSOLE-4). Fire-and-forget at the
  /// seam: the firmware sends no reply, so this never awaits one.
  Future<void> sendInput(String text) =>
      ref.read(connectionProvider).sendInput(text);
}

/// The single console-buffer seam every console surface (page + landscape strip)
/// renders. A plain (non-autoDispose) provider so output survives navigation.
final NotifierProvider<ConsoleBufferController, List<ConsoleEvent>>
consoleBufferProvider =
    NotifierProvider<ConsoleBufferController, List<ConsoleEvent>>(
      ConsoleBufferController.new,
    );

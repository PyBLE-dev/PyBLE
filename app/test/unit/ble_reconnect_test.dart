// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.
//
// A-03 [red] — reconnect + connection-state transitions in lib/ble, verified
// against a MOCKED transport that injects link loss (the DoR's verification
// method; no radio, no ESP32). Frozen policy: TDD §7.3.
//
//   • BleLinkState is the extended four-value enum
//     {disconnected, connecting, connected, reconnecting} (additive to S2);
//   • BleBackoff carries the FROZEN bounded policy — 0.5, 1, 2, 4, 8, 8 s over
//     6 attempts, no jitter — and is injectable so tests can shrink it;
//   • on an UNEXPECTED drop the link auto-reattempts to the REMEMBERED id and
//     surfaces the ordered transitions connected → reconnecting → connected;
//   • when the backoff policy is exhausted it settles on `disconnected`;
//   • a USER-initiated disconnect() disables auto-reattempt (no reconnect after
//     an intentional teardown).
//
// This pins the transport-agnostic reconnect seam that makes reconnect testable
// without a radio: a self-reconnecting BleLink wrapper (proposed name
// `ReconnectingBleLink`) factored out of the flutter_blue_plus-coupled link, plus
// `BleBackoff`. The neutral BleLinkException surfaced on exhaustion is a lib/pble
// type (import boundary: lib/ble cannot depend on lib/pble) and is asserted in
// pble_exception_table_test.dart — lib/ble only settles `disconnected` here.
//
// CURRENTLY RED: BleLinkState is still the S2 two-value enum, and BleBackoff /
// ReconnectingBleLink do not exist. HAND-OFF: `lib/ble/ble_link.dart` (+ barrel)
// → app-ble-engineer. If a different factoring is preferred, THIS is the
// coordination point.

import 'package:flutter_test/flutter_test.dart';

import 'package:pyble/ble/ble.dart';

import '../support/fake_ble.dart';

/// A near-instant backoff so the reattempt loop runs deterministically in tests.
const BleBackoff fastBackoff = BleBackoff(
  initial: Duration.zero,
  factor: 1.0,
  maxInterval: Duration.zero,
  maxAttempts: 3,
);

Future<void> settle() async {
  for (int i = 0; i < 8; i++) {
    await pumpEventQueue();
  }
}

void main() {
  group('A-03 BleLinkState — extended four-value enum (TDD §7.3)', () {
    test('carries disconnected/connecting/connected/reconnecting', () {
      expect(BleLinkState.values, <BleLinkState>[
        BleLinkState.disconnected,
        BleLinkState.connecting,
        BleLinkState.connected,
        BleLinkState.reconnecting,
      ]);
    });
  });

  group('A-03 BleBackoff — frozen bounded policy (TDD §7.3)', () {
    test('defaults: 0.5, 1, 2, 4, 8, 8 s over 6 attempts, no jitter', () {
      const BleBackoff b = BleBackoff();
      expect(b.initial, const Duration(milliseconds: 500));
      expect(b.factor, 2.0);
      expect(b.maxInterval, const Duration(seconds: 8));
      expect(b.maxAttempts, 6);
      expect(
        <Duration>[for (int n = 1; n <= 6; n++) b.delayFor(n)],
        <Duration>[
          const Duration(milliseconds: 500),
          const Duration(seconds: 1),
          const Duration(seconds: 2),
          const Duration(seconds: 4),
          const Duration(seconds: 8),
          const Duration(seconds: 8), // capped at maxInterval
        ],
      );
    });

    test('is injectable and caps each interval at maxInterval', () {
      const BleBackoff b = BleBackoff(
        initial: Duration(milliseconds: 10),
        factor: 3.0,
        maxInterval: Duration(milliseconds: 50),
        maxAttempts: 2,
      );
      expect(b.delayFor(1), const Duration(milliseconds: 10));
      expect(b.delayFor(2), const Duration(milliseconds: 30));
      expect(
        b.delayFor(3),
        const Duration(milliseconds: 50),
        reason: 'intervals never exceed maxInterval',
      );
    });
  });

  group('A-03 ReconnectingBleLink — auto-reattempt vs a mocked transport', () {
    late List<String> connectIds;
    late List<FakeBleLink> handedOut;
    late int connectCalls;

    Future<BleLink> okConnect(String id) async {
      connectCalls++;
      connectIds.add(id);
      final FakeBleLink link = FakeBleLink();
      handedOut.add(link);
      return link;
    }

    setUp(() {
      connectIds = <String>[];
      handedOut = <FakeBleLink>[];
      connectCalls = 0;
    });

    test('start() establishes the link and reports connected', () async {
      final ReconnectingBleLink r = ReconnectingBleLink(
        id: 'board-1',
        connect: okConnect,
        backoff: fastBackoff,
      );
      addTearDown(r.disconnect);

      await r.start();
      expect(
        r,
        isA<BleLink>(),
        reason: 'it IS the BleLink the layer above uses',
      );
      expect(r.linkState.value, BleLinkState.connected);
      expect(connectCalls, 1);
      expect(connectIds, <String>['board-1']);
    });

    test('an unexpected drop auto-reattempts to the remembered id', () async {
      final ReconnectingBleLink r = ReconnectingBleLink(
        id: 'board-1',
        connect: okConnect,
        backoff: fastBackoff,
      );
      addTearDown(r.disconnect);
      await r.start();

      final List<BleLinkState> seen = <BleLinkState>[];
      r.linkState.addListener(() => seen.add(r.linkState.value));

      // Inject an unexpected link loss on the current inner link.
      await handedOut.last.disconnect();
      await settle();

      expect(
        seen,
        containsAllInOrder(<BleLinkState>[
          BleLinkState.reconnecting,
          BleLinkState.connected,
        ]),
      );
      expect(connectCalls, 2, reason: 'one reattempt after the drop');
      expect(
        connectIds,
        <String>['board-1', 'board-1'],
        reason: 'reconnect reuses the remembered id — no re-scan (FR-BLE-4)',
      );
    });

    test('exhausting the backoff policy settles on disconnected', () async {
      int failingCalls = 0;
      Future<BleLink> flakyConnect(String id) async {
        connectCalls++;
        if (connectCalls == 1) {
          final FakeBleLink link = FakeBleLink();
          handedOut.add(link);
          return link; // initial connect succeeds
        }
        failingCalls++;
        throw StateError('cannot reach board'); // every reattempt fails
      }

      final ReconnectingBleLink r = ReconnectingBleLink(
        id: 'board-1',
        connect: flakyConnect,
        backoff: fastBackoff, // maxAttempts: 3
      );
      addTearDown(r.disconnect);
      await r.start();

      await handedOut.last.disconnect(); // trigger reattempts
      await settle();

      expect(r.linkState.value, BleLinkState.disconnected);
      expect(
        failingCalls,
        fastBackoff.maxAttempts,
        reason: 'it gives up after maxAttempts reattempts',
      );
    });

    test('a user-initiated disconnect() disables auto-reattempt', () async {
      final ReconnectingBleLink r = ReconnectingBleLink(
        id: 'board-1',
        connect: okConnect,
        backoff: fastBackoff,
      );
      await r.start();
      final int callsAtConnect = connectCalls;

      await r.disconnect(); // intentional teardown
      expect(r.linkState.value, BleLinkState.disconnected);

      // A subsequent inner drop must NOT trigger a reattempt.
      await handedOut.last.disconnect();
      await settle();
      expect(
        connectCalls,
        callsAtConnect,
        reason: 'no reconnect after disconnect()',
      );
    });
  });
}

// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.
//
// A-04 [red] — BLE permissions / adapter-off readiness, verified on a MOCKED
// platform seam (no radio). Frozen readiness contract: TDD §7.4.
//
//   • BleReadiness is the neutral four-value type {ready, adapterOff,
//     unauthorized, unsupported} and is reachable through lib/pble (widgets bind
//     to it there; NO widget imports lib/ble — CON-8, FR-BLE-8);
//   • the mockable readiness seam (BleReadinessSource) reports adapterOff /
//     unauthorized / ready as DISTINCT states, with `current` tracking the latest
//     — enough detail for a localized rationale LATER (FR-BLE-6, the rationale UI
//     + its ARB strings are A-22/S5, so S3 adds no user-facing strings).
//
// The type is imported from the lib/pble barrel to pin "reachable via lib/pble";
// the seam behaviour is driven via the FakeBleReadinessSource scaffold, which
// binds to the lib/ble source contract the production fbp-derived source honours.
//
// CURRENTLY RED: lib/ble defines no BleReadiness / BleReadinessSource, and the
// pble barrel does not re-export BleReadiness. HAND-OFF: `lib/ble/**` (readiness
// source) → app-ble-engineer; `lib/pble/pble.dart` re-export → app-protocol-
// engineer.

import 'package:flutter_test/flutter_test.dart';

// Reachable via lib/pble ONLY (FR-BLE-8): the widget-facing import path.
import 'package:pyble/pble/pble.dart' show BleReadiness;

import '../support/fake_readiness.dart';

void main() {
  group(
    'A-04 BleReadiness — neutral type reachable via lib/pble (FR-BLE-8)',
    () {
      test(
        'carries exactly ready / adapterOff / unauthorized / unsupported',
        () {
          expect(BleReadiness.values.toSet(), <BleReadiness>{
            BleReadiness.ready,
            BleReadiness.adapterOff,
            BleReadiness.unauthorized,
            BleReadiness.unsupported,
          });
          expect(BleReadiness.values, hasLength(4));
        },
      );
    },
  );

  group(
    'A-04 readiness seam — distinct states on a mocked platform (FR-BLE-6/7)',
    () {
      late FakeBleReadinessSource source;

      setUp(() => source = FakeBleReadinessSource());
      tearDown(() => source.dispose());

      test(
        'reports adapterOff, unauthorized, and ready as distinct transitions',
        () async {
          final List<BleReadiness> seen = <BleReadiness>[];
          source.readiness.listen(seen.add);

          source.emit(BleReadiness.adapterOff);
          source.emit(BleReadiness.unauthorized);
          source.emit(BleReadiness.ready);
          await pumpEventQueue();

          expect(seen, <BleReadiness>[
            BleReadiness.adapterOff,
            BleReadiness.unauthorized,
            BleReadiness.ready,
          ]);
        },
      );

      test(
        '`current` tracks the latest readiness for a fresh subscriber',
        () async {
          expect(source.current, BleReadiness.ready);
          source.emit(BleReadiness.adapterOff);
          expect(
            source.current,
            BleReadiness.adapterOff,
            reason:
                'adapter-off is surfaced upward, never swallowed (FR-BLE-7)',
          );
        },
      );
    },
  );
}

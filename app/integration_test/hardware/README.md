<!-- SPDX-License-Identifier: MIT -->

# Optional physical protocol central

`v070_run_status_real_test.dart` is an operator-selected Android BLE hardware
probe. It is separate from the single default Android smoke-test bundle in
`../android_smoke_test.dart` and is never imported by that bundle.

Build/run it explicitly with target
`integration_test/hardware/v070_run_status_real_test.dart`, a distinct local
application ID, `PYBLE_HIL_BOARD_ID` (or `PYBLE_HIL_BOARD_NAME`) and
`PYBLE_HIL_ATT_MTU=23` or `247` Dart defines. Reserve one backed-up candidate
board exclusively and disconnect all other clients first. The test refuses a
pre-existing active run. Its own source runs are finite and do not write board
files or configuration. Preserve the private receipt and any failed attempts.

The probe asserts the actual Android GATT MTU, HELLO MTU and tagged notification
fragment count. It exercises the production connection/link classes, but does
not establish a normal application UI row or complete firmware qualification.

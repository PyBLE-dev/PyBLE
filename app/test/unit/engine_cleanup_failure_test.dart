// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

import 'dart:async';
import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';
import 'package:pyble/pble/engine.dart';
import 'package:pyble/pble/frame.dart';
import 'package:pyble/pble/pble_constants.dart';
import 'package:pyble/pble/pble_exception.dart';

import '../support/fake_byte_transport.dart';

class _CancelFailureTransport extends FakeByteTransport {
  _CancelFailureTransport(Object failure)
    : input = StreamController<Uint8List>(onCancel: () async => throw failure);
  final StreamController<Uint8List> input;
  @override
  Stream<Uint8List> get inbound => input.stream;
}

void main() {
  test(
    'inbound cancellation failure still fails pending work and closes events',
    () async {
      final StateError failure = StateError('inbound cancellation failed');
      final _CancelFailureTransport transport = _CancelFailureTransport(
        failure,
      );
      final PbleEngine engine = PbleEngine(transport);
      bool eventsDone = false;
      Object? requestFailure;
      final StreamSubscription<PbleFrame> events = engine.events.listen(
        (_) {},
        onDone: () => eventsDone = true,
      );
      addTearDown(() async {
        await events.cancel();
        await transport.input.close();
        await transport.dispose();
      });
      unawaited(
        engine
            .request(
              PbleFrame(
                type: Pble.typeCmd,
                opcode: PbleOpcode.deviceInfo.code,
                id: engine.nextId(),
                payload: Uint8List(0),
              ),
              timeout: const Duration(milliseconds: 200),
            )
            .then<void>(
              (_) {},
              onError: (Object error) {
                requestFailure = error;
              },
            ),
      );
      await pumpEventQueue();
      await expectLater(engine.dispose(), throwsA(same(failure)));
      await pumpEventQueue();
      expect(requestFailure, isA<PbleTimeoutException>());
      expect(eventsDone, isTrue);
    },
  );
}

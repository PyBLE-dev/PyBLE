// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

import 'dart:async';
import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';
import 'package:pyble/pble/engine.dart';
import 'package:pyble/pble/frame.dart';
import 'package:pyble/pble/fragment.dart';
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

class _HeldTransport extends FakeByteTransport {
  _HeldTransport() : super(mtu: 23);
  final Completer<void> held = Completer<void>();
  int submissions = 0;
  @override
  Future<void> send(Uint8List packet, {required bool acknowledged}) async {
    submissions++;
    if (submissions == 1) await held.future;
    await super.send(packet, acknowledged: acknowledged);
  }
}

void main() {
  for (final bool fire in <bool>[false, true]) {
    test(
      'retired ${fire ? 'fire' : 'request'} never submits more held fragments',
      () async {
        final Completer<void> finished = Completer<void>();
        final List<Object> uncaught = <Object>[];
        Object? operationError;
        int before = 0;
        int after = 0;
        runZonedGuarded(() async {
          final _HeldTransport transport = _HeldTransport();
          final PbleEngine engine = PbleEngine(transport);
          final PbleFrame command = PbleFrame(
            type: Pble.typeCmd,
            opcode: (fire ? PbleOpcode.consoleInput : PbleOpcode.run).code,
            id: engine.nextId(),
            payload: Uint8List(100),
          );
          final Future<void> observed =
              (fire ? engine.fire(command) : engine.request(command))
                  .then<void>(
                    (_) {},
                    onError: (Object error) => operationError = error,
                  );
          await pumpEventQueue();
          before = transport.submissions;
          await engine.dispose();
          await pumpEventQueue();
          transport.held.complete();
          await observed;
          await pumpEventQueue();
          after = transport.submissions;
          await transport.dispose();
          finished.complete();
        }, (Object error, StackTrace _) => uncaught.add(error));
        await finished.future.timeout(const Duration(seconds: 2));
        expect(before, 1);
        expect(after, 1);
        expect(uncaught, isEmpty);
        expect(operationError, isA<PbleTimeoutException>());
      },
    );
  }

  test(
    'on-time response before retirement still wins over held write completion',
    () async {
      final _HeldTransport transport = _HeldTransport();
      final PbleEngine engine = PbleEngine(transport);
      final PbleFrame command = PbleFrame(
        type: Pble.typeCmd,
        opcode: PbleOpcode.deviceInfo.code,
        id: engine.nextId(),
        payload: Uint8List(0),
      );
      final Future<PbleFrame> result = engine.request(command);
      await pumpEventQueue();
      final PbleFrame response = PbleFrame(
        type: Pble.typeRsp,
        opcode: command.opcode,
        id: command.id,
        payload: Uint8List.fromList(<int>[0]),
      );
      for (final Uint8List packet in PbleFragmenter(
        mtu: 23,
      ).fragment(encodeFrame(response))) {
        transport.deliverRawPacket(packet);
      }
      await pumpEventQueue();
      await engine.dispose();
      transport.held.complete();
      expect((await result).payload, response.payload);
      expect(transport.submissions, 1);
      await transport.dispose();
    },
  );

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

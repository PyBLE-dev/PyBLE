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

/// Accept the packet before holding its acknowledged-write completion. This
/// reproduces the real ATT23 RUN FIRST / STATUS FIRST|LAST / RUN tail trace.
class _HeldPacketTransport extends FakeByteTransport {
  _HeldPacketTransport({this.holdFirst = true, this.respond = true})
    : super(mtu: 23);
  final bool holdFirst;
  final bool respond;
  final Completer<void> firstAccepted = Completer<void>();
  final Completer<void> releaseFirst = Completer<void>();
  int writesStarted = 0;

  @override
  Future<void> send(Uint8List packet, {required bool acknowledged}) async {
    final int submission = ++writesStarted;
    final int before = sentFrames.length;
    await super.send(packet, acknowledged: acknowledged);
    if (respond && sentFrames.length > before && acknowledged) {
      reply(sentFrames.last);
    }
    if (submission == 1) {
      firstAccepted.complete();
      if (holdFirst) await releaseFirst.future;
    }
  }

  void reply(PbleFrame command) => deliverFrame(
    PbleFrame(
      type: Pble.typeRsp,
      opcode: command.opcode,
      id: command.id,
      payload: Uint8List.fromList(<int>[PbleStatus.ok.code]),
    ),
  );
}

PbleFrame _command(int opcode, int id, [int bytes = 0]) => PbleFrame(
  type: Pble.typeCmd,
  opcode: opcode,
  id: id,
  payload: Uint8List.fromList(List<int>.filled(bytes, 0x78)),
);

Future<Object?> _observe(Future<Object?> future) =>
    future.then<Object?>((_) => null, onError: (Object error) => error);

void main() {
  for (final bool firstFire in <bool>[false, true]) {
    for (final bool nextFire in <bool>[false, true]) {
      test('whole frames stay contiguous: $firstFire then $nextFire', () async {
        final _HeldPacketTransport transport = _HeldPacketTransport();
        final PbleEngine engine = PbleEngine(transport);
        addTearDown(() async {
          await engine.dispose();
          await transport.dispose();
        });
        final PbleFrame first = _command(
          (firstFire ? PbleOpcode.consoleInput : PbleOpcode.run).code,
          8,
          42,
        );
        final PbleFrame next = _command(
          (nextFire ? PbleOpcode.consoleInput : PbleOpcode.runStatus).code,
          9,
        );
        final Future<Object?> a = _observe(
          firstFire ? engine.fire(first) : engine.request(first),
        );
        await transport.firstAccepted.future;
        final Future<Object?> b = _observe(
          nextFire ? engine.fire(next) : engine.request(next),
        );
        await pumpEventQueue();
        final int beforeRelease = transport.writesStarted;
        transport.releaseFirst.complete();
        expect(await a, isNull);
        expect(await b, isNull);
        expect(beforeRelease, 1, reason: 'STATUS must not replace RUN FIRST');
        expect(transport.sentFrames.map((PbleFrame f) => f.opcode), <int>[
          first.opcode,
          next.opcode,
        ]);
        expect(transport.sentFrames.first.payload, first.payload);
        expect(transport.sentFrames.last.id, 9);
      });

      test(
        'dispose retires active/queued frames: $firstFire/$nextFire',
        () async {
          final _HeldPacketTransport transport = _HeldPacketTransport();
          final PbleEngine engine = PbleEngine(transport);
          final Future<Object?> a = _observe(
            firstFire
                ? engine.fire(_command(PbleOpcode.consoleInput.code, 1, 100))
                : engine.request(_command(PbleOpcode.run.code, 1, 100)),
          );
          await transport.firstAccepted.future;
          final Future<Object?> b = _observe(
            nextFire
                ? engine.fire(_command(PbleOpcode.consoleInput.code, 2, 100))
                : engine.request(_command(PbleOpcode.runStatus.code, 2)),
          );
          await pumpEventQueue();
          await engine.dispose();
          final Object? queuedError = await b;
          transport.releaseFirst.complete();
          expect(await a, isA<PbleTimeoutException>());
          expect(queuedError, isA<PbleTimeoutException>());
          await pumpEventQueue();
          expect(transport.writesStarted, 1);
          await transport.dispose();
        },
      );
    }
  }

  test('writer releases before independent response waits complete', () async {
    final _HeldPacketTransport transport = _HeldPacketTransport(
      holdFirst: false,
      respond: false,
    );
    final PbleEngine engine = PbleEngine(transport);
    addTearDown(() async {
      await engine.dispose();
      await transport.dispose();
    });
    final PbleFrame first = _command(PbleOpcode.run.code, 1, 42);
    final PbleFrame second = _command(PbleOpcode.runStatus.code, 2);
    final Future<PbleFrame> a = engine.request(first);
    final Future<PbleFrame> b = engine.request(second);
    await pumpEventQueue();
    expect(transport.sentFrames, hasLength(2));
    transport.reply(second);
    expect((await b).id, 2);
    transport.reply(first);
    expect((await a).id, 1);
  });

  test('queued request deadline expires without a packet submission', () async {
    final _HeldPacketTransport transport = _HeldPacketTransport();
    final PbleEngine engine = PbleEngine(transport);
    final Future<Object?> a = _observe(
      engine.fire(_command(PbleOpcode.consoleInput.code, 1, 42)),
    );
    await transport.firstAccepted.future;
    final Stopwatch elapsed = Stopwatch()..start();
    final Object? error = await _observe(
      engine.request(
        _command(PbleOpcode.runStatus.code, 2),
        timeout: const Duration(milliseconds: 25),
      ),
    );
    expect(error, isA<PbleTimeoutException>());
    expect(elapsed.elapsed, lessThan(const Duration(milliseconds: 150)));
    expect(transport.writesStarted, 1);
    transport.releaseFirst.complete();
    expect(await a, isNull);
    expect(transport.sentFrames.map((PbleFrame f) => f.id), <int>[1]);
    await engine.dispose();
    await transport.dispose();
  });

  test(
    'timed-out send retains writer until physical completion settles',
    () async {
      final _HeldPacketTransport transport = _HeldPacketTransport();
      final PbleEngine engine = PbleEngine(transport);
      final Future<Object?> a = _observe(
        engine.request(
          _command(PbleOpcode.run.code, 1, 100),
          timeout: const Duration(milliseconds: 25),
        ),
      );
      await transport.firstAccepted.future;
      final Future<PbleFrame> b = engine.request(
        _command(PbleOpcode.runStatus.code, 2),
      );
      expect(await a, isA<PbleTimeoutException>());
      expect(transport.writesStarted, 1);
      transport.releaseFirst.complete();
      expect((await b).id, 2);
      expect(transport.sentFrames.map((PbleFrame f) => f.id), <int>[2]);
      expect(transport.writesStarted, 2, reason: 'expired RUN sends no tail');
      await engine.dispose();
      await transport.dispose();
    },
  );

  test('on-time response wins while final ACK holds later writers', () async {
    final _HeldPacketTransport transport = _HeldPacketTransport();
    final PbleEngine engine = PbleEngine(transport);
    final Future<PbleFrame> a = engine.request(
      _command(PbleOpcode.deviceInfo.code, 1),
      timeout: const Duration(milliseconds: 25),
    );
    await transport.firstAccepted.future;
    final Future<PbleFrame> b = engine.request(
      _command(PbleOpcode.runStatus.code, 2),
    );
    expect((await a).id, 1);
    expect(transport.writesStarted, 1);
    transport.releaseFirst.complete();
    expect((await b).id, 2);
    expect(transport.sentFrames.map((PbleFrame f) => f.id), <int>[1, 2]);
    await engine.dispose();
    await transport.dispose();
  });

  test(
    'disconnect rejects old work before a successor link can write',
    () async {
      final _HeldPacketTransport transport = _HeldPacketTransport();
      final PbleEngine engine = PbleEngine(transport);
      final Future<Object?> a = _observe(
        engine.request(_command(PbleOpcode.run.code, 1, 100)),
      );
      await transport.firstAccepted.future;
      final Future<Object?> b = _observe(
        engine.fire(_command(PbleOpcode.consoleInput.code, 2, 100)),
      );
      await pumpEventQueue();
      transport.setConnected(false);
      transport.setConnected(true);
      expect(await a, isA<BleLinkException>());
      expect(await b, isA<BleLinkException>());
      final Future<PbleFrame> successor = engine.request(
        _command(PbleOpcode.hello.code, 3),
      );
      await pumpEventQueue();
      expect(transport.writesStarted, 1);
      transport.releaseFirst.complete();
      expect((await successor).id, 3);
      expect(transport.sentFrames.map((PbleFrame f) => f.id), <int>[3]);
      expect(transport.writesStarted, 2);
      await engine.dispose();
      await transport.dispose();
    },
  );

  test(
    'live queue is bounded and its local refusal is not board EBUSY',
    () async {
      final _HeldPacketTransport transport = _HeldPacketTransport();
      final PbleEngine engine = PbleEngine(transport);
      final List<Future<Object?>> operations = <Future<Object?>>[];
      for (int i = 0; i < 256; i++) {
        operations.add(
          _observe(
            engine.fire(_command(PbleOpcode.consoleInput.code, i % 255 + 1)),
          ),
        );
      }
      await pumpEventQueue();
      transport.releaseFirst.complete();
      final List<Object?> outcomes = await Future.wait(operations);
      final List<Object> errors = outcomes.whereType<Object>().toList();
      expect(errors, hasLength(1));
      expect(errors.single, isA<PbleException>());
      expect(errors.single, isNot(isA<EBusy>()));
      expect(
        errors.single.runtimeType.toString(),
        'PbleTransportBusyException',
      );
      expect(transport.sentFrames, hasLength(255));
      await engine.dispose();
      await transport.dispose();
    },
  );

  test(
    'expired queued requests release bounded FIFO capacity immediately',
    () async {
      final _HeldPacketTransport transport = _HeldPacketTransport();
      final PbleEngine engine = PbleEngine(transport);
      final Future<Object?> first = _observe(
        engine.fire(_command(PbleOpcode.consoleInput.code, 1, 42)),
      );
      await transport.firstAccepted.future;
      final List<Future<Object?>> queued = <Future<Object?>>[
        for (int id = 2; id <= 255; id++)
          _observe(
            engine.request(
              _command(PbleOpcode.runStatus.code, id),
              timeout: const Duration(milliseconds: 25),
            ),
          ),
      ];
      expect(
        await Future.wait(queued),
        everyElement(isA<PbleTimeoutException>()),
      );
      final Future<Object?> replacement = _observe(
        engine.fire(_command(PbleOpcode.consoleInput.code, 2)),
      );
      await pumpEventQueue();
      expect(transport.writesStarted, 1);
      transport.releaseFirst.complete();
      expect(await first, isNull);
      expect(await replacement, isNull);
      expect(transport.sentFrames.map((PbleFrame f) => f.id), <int>[1, 2]);
      await engine.dispose();
      await transport.dispose();
    },
  );
}

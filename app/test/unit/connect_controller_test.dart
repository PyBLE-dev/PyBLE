// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

import 'dart:async';

import 'package:flutter_test/flutter_test.dart';

import 'package:pyble/connect/connect.dart';
import 'package:pyble/pble/pble.dart';

import '../support/fake_readiness_seam.dart';

class _DelayedInfoConnection extends FakeConnection {
  _DelayedInfoConnection() : super(initial: ConnState.ready);

  final Completer<DeviceInfo> _info = Completer<DeviceInfo>();
  int deviceInfoCalls = 0;

  @override
  Future<DeviceInfo> deviceInfo() {
    deviceInfoCalls += 1;
    return _info.future;
  }

  void completeInfo(DeviceInfo info) => _info.complete(info);
}

DeviceInfo _info(String deviceId, String agentVersion) => DeviceInfo(
  chip: 'esp32-s3',
  mpyVersion: '1.28.0',
  freeMem: 48000,
  fsRoot: '/',
  deviceId: deviceId,
  agentVersion: agentVersion,
);

void main() {
  test(
    'late DeviceInfo from a detached board cannot replace current identity',
    () async {
      final _DelayedInfoConnection first = _DelayedInfoConnection();
      final _DelayedInfoConnection second = _DelayedInfoConnection();
      final FakeSeamReadiness readiness = FakeSeamReadiness();
      final Map<String, _DelayedInfoConnection> boards =
          <String, _DelayedInfoConnection>{'board-a': first, 'board-b': second};
      final PbleConnectionManager manager = PbleConnectionManager(
        scanner: FakeScanner(),
        readiness: readiness,
        connectionFactory: (String id) async => boards[id]!,
      );
      final ConnectController controller = ConnectController(manager);
      addTearDown(() async {
        controller.dispose();
        await manager.dispose();
        await readiness.dispose();
      });
      final List<String> publishedIds = <String>[];
      controller.addListener(() {
        final String? id = controller.state.deviceInfo?.deviceId;
        if (id != null) publishedIds.add(id);
      });

      await manager.connect('board-a');
      await pumpEventQueue();
      expect(first.deviceInfoCalls, 1);

      await manager.disconnect();
      await manager.connect('board-b');
      await pumpEventQueue();
      expect(controller.state.deviceInfo, isNull);

      second.completeInfo(_info('BBBB', '0.7.0'));
      await pumpEventQueue();
      first.completeInfo(_info('AAAA', '0.6.0'));
      await pumpEventQueue();

      expect(
        second.deviceInfoCalls,
        1,
        reason: 'the replacement session must not wait for the old request',
      );
      expect(controller.state.deviceInfo?.deviceId, 'BBBB');
      expect(controller.state.deviceInfo?.agentVersion, '0.7.0');
      expect(
        publishedIds,
        isNot(contains('AAAA')),
        reason: 'prior-session identity must never flash in the live UI',
      );
    },
  );
}

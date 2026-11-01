// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

/// Operator-selected protocol HIL central, distinct from normal application UI.
/// Use an isolated application ID and an exclusively reserved, backed-up board:
/// --dart-define=PYBLE_HIL_BOARD_ID=`<platform-id>`
/// --dart-define=PYBLE_HIL_ATT_MTU=23 (or 247).
/// No board files, configuration, or autorun settings are changed.
library;

import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:flutter/foundation.dart';
import 'package:flutter_blue_plus/flutter_blue_plus.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';
import 'package:path_provider/path_provider.dart';
import 'package:pyble/ble/ble_link.dart';
import 'package:pyble/ble/fbp_ble_link.dart';
import 'package:pyble/pble/conn_state.dart';
import 'package:pyble/pble/fragment.dart';
import 'package:pyble/pble/frame.dart';
import 'package:pyble/pble/pble_connection.dart';
import 'package:pyble/pble/pble_constants.dart';
import 'package:pyble/pble/types.dart';

const _boardId = String.fromEnvironment('PYBLE_HIL_BOARD_ID');
const _boardName = String.fromEnvironment('PYBLE_HIL_BOARD_NAME');
const _requestedMtu = int.fromEnvironment(
  'PYBLE_HIL_ATT_MTU',
  defaultValue: 23,
);

void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();
  testWidgets(
    'physical run-status at ATT $_requestedMtu',
    (tester) async {
      await tester.runAsync(() async {
        expect(
          Platform.isAndroid,
          isTrue,
          reason: 'Explicit MTU HIL is Android.',
        );
        expect(<int>[23, 247], contains(_requestedMtu));
        final directory = await getApplicationSupportDirectory();
        final receipt = File(
          '${directory.path}/run-status-att-$_requestedMtu.json',
        );
        final result = <String, Object?>{
          'qualification': 'protocol-central; not normal UI',
          'requestedAttMtu': _requestedMtu,
          'startedUtc': DateTime.now().toUtc().toIso8601String(),
        };
        _Session? active;
        try {
          active = await _open();
          final info = await active.connection.deviceInfo();
          expect(info.hasRunStatus, isTrue);
          expect(info.mtu, _requestedMtu);
          expect(active.link.mtu, _requestedMtu);
          result['observedAttMtu'] = active.link.mtu;
          result['helloAttMtu'] = info.mtu;
          result['agentVersion'] = info.agentVersion;
          final initial = active.connection.runSnapshot.value!;
          expect(
            initial.state,
            isNot(RunState.running),
            reason: 'Never interrupt a pre-existing program.',
          );

          await active.connection.runSource(
            'import time\nprint("PBLE_ATT_HIL_RUNNING")\ntime.sleep(30)\n',
          );
          await _until(
            () =>
                active!.connection.runSnapshot.value?.state == RunState.running,
          );
          final running = active.connection.runSnapshot.value!;
          expect(running.origin, RunOrigin.source);
          expect(running.runId, isNot(initial.runId));
          result['beforeReconnect'] = _snapshot(running);
          final firstTrace = active.trace;
          await active.close();
          active = null;

          // Fresh production connection performs HELLO/status only. No RUN,
          // upload, STOP, or other board write is used to discover execution.
          active = await _open();
          final recovered = active.connection.runSnapshot.value!;
          expect(active.connection.state.value, ConnState.running);
          expect(recovered.state, RunState.running);
          expect(recovered.bootId, running.bootId);
          expect(recovered.runId, running.runId);
          expect(recovered.revision, greaterThanOrEqualTo(running.revision));
          expect(active.trace.commands, <int>[
            PbleOpcode.hello.code,
            PbleOpcode.runStatus.code,
          ]);
          result['afterReconnect'] = _snapshot(recovered);
          result['reconnectCommands'] = List<int>.of(active.trace.commands);

          await active.connection.stop();
          await _until(
            () =>
                active!.connection.runSnapshot.value?.terminalReason ==
                RunTerminalReason.stopped,
          );
          final stopped = await active.connection.refreshRunStatus();
          expect(stopped.runId, running.runId);
          expect(stopped.state, RunState.idle);
          expect(stopped.stopping, isFalse);
          result['stopped'] = _snapshot(stopped);

          await active.connection.runSource('print("PBLE_ATT_HIL_DONE")\n');
          await _until(
            () =>
                active!.connection.runSnapshot.value?.terminalReason ==
                RunTerminalReason.completed,
          );
          result['completed'] = _snapshot(active.connection.runSnapshot.value!);
          await active.connection.runSource(
            'raise RuntimeError("PBLE_ATT_HIL_ERROR")\n',
          );
          await _until(
            () =>
                active!.connection.runSnapshot.value?.terminalReason ==
                RunTerminalReason.exception,
          );
          result['exception'] = _snapshot(active.connection.runSnapshot.value!);

          final tagged = <Map<String, Object?>>[
            ...firstTrace.taggedEvents,
            ...active.trace.taggedEvents,
          ];
          expect(
            tagged,
            isNotEmpty,
            reason: 'Observe actual tagged notifications.',
          );
          for (final event in tagged) {
            expect(event['payloadBytes'], 25);
            expect(event['fragments'], _requestedMtu == 23 ? 2 : 1);
            expect(
              event['largestPacket'],
              lessThanOrEqualTo(_requestedMtu - 3),
            );
          }
          result['taggedEvents'] = tagged;
          result['passed'] = true;
        } catch (error) {
          result['passed'] = false;
          result['error'] = error.toString();
          rethrow;
        } finally {
          await active?.close();
          result['finishedUtc'] = DateTime.now().toUtc().toIso8601String();
          await receipt.writeAsString(
            const JsonEncoder.withIndent('  ').convert(result),
          );
        }
      });
    },
    skip: _boardId.isEmpty && _boardName.isEmpty,
  );
}

Future<void> _until(bool Function() condition) async {
  final deadline = DateTime.now().add(const Duration(seconds: 12));
  while (!condition()) {
    if (DateTime.now().isAfter(deadline)) {
      fail('Bounded physical state wait expired.');
    }
    await Future<void>.delayed(const Duration(milliseconds: 40));
  }
}

Map<String, Object?> _snapshot(RunSnapshot value) => <String, Object?>{
  'bootId': value.bootId,
  'runId': value.runId,
  'revision': value.revision,
  'state': value.state.name,
  'origin': value.origin.name,
  'reason': value.terminalReason.name,
  'queued': value.queued,
  'stopping': value.stopping,
};

Future<_Session> _open() async {
  await FlutterBluePlus.stopScan();
  final BluetoothDevice device;
  if (_boardId.isNotEmpty) {
    device = BluetoothDevice.fromId(_boardId);
  } else {
    final found = Completer<BluetoothDevice>();
    final subscription = FlutterBluePlus.scanResults.listen((hits) {
      for (final hit in hits) {
        if (hit.advertisementData.advName == _boardName && !found.isCompleted) {
          found.complete(hit.device);
        }
      }
    });
    try {
      await FlutterBluePlus.startScan(
        withServices: <Guid>[Guid(Pble.serviceUuid)],
      );
      device = await found.future.timeout(const Duration(seconds: 20));
    } finally {
      await FlutterBluePlus.stopScan();
      await subscription.cancel();
    }
  }
  await device.connect(mtu: null, timeout: const Duration(seconds: 20));
  try {
    final observed = await device.requestMtu(_requestedMtu);
    expect(observed, _requestedMtu);
    expect(
      device.mtuNow,
      _requestedMtu,
      reason: 'Command fragmentation alone does not prove ATT MTU.',
    );
    final services = await device.discoverServices();
    final service = services.singleWhere(
      (s) => s.uuid == Guid(Pble.serviceUuid),
    );
    final rx = service.characteristics.singleWhere(
      (c) => c.uuid == Guid(Pble.rxUuid),
    );
    final tx = service.characteristics.singleWhere(
      (c) => c.uuid == Guid(Pble.txUuid),
    );
    await tx.setNotifyValue(true);
    final trace = _Trace();
    final link = _ObservedLink(FbpBleLink(device, rx, tx), trace);
    final connection = PbleConnection.fromLink(
      link: link,
      appName: 'PyBLE protocol HIL',
      appVersion: '0.4.0',
    );
    final session = _Session(connection, link, trace);
    try {
      await _until(
        () =>
            connection.state.value == ConnState.ready ||
            connection.state.value == ConnState.running,
      );
      expect((await connection.deviceInfo()).mtu, _requestedMtu);
      return session;
    } catch (_) {
      await session.close();
      rethrow;
    }
  } catch (_) {
    await device.disconnect();
    rethrow;
  }
}

class _Session {
  _Session(this.connection, this.link, this.trace);
  final PbleConnection connection;
  final _ObservedLink link;
  final _Trace trace;
  Future<void> close() => connection.dispose();
}

/// A byte-transparent observer around the production GATT link. Both the
/// protocol engine and evidence decoder receive the same real notification.
class _ObservedLink implements BleLink {
  _ObservedLink(this.inner, this.trace);
  final FbpBleLink inner;
  final _Trace trace;
  @override
  Stream<List<int>> get inbound => inner.inbound.map((packet) {
    trace.offer(packet, inbound: true);
    return packet;
  });
  @override
  Future<void> write(List<int> bytes, {required bool withoutResponse}) {
    trace.offer(bytes, inbound: false);
    return inner.write(bytes, withoutResponse: withoutResponse);
  }

  @override
  int get mtu => inner.mtu;
  @override
  ValueListenable<BleLinkState> get linkState => inner.linkState;
  @override
  Future<void> disconnect() => inner.disconnect();
}

class _Trace {
  final commands = <int>[];
  final taggedEvents = <Map<String, Object?>>[];
  final _rx = PbleReassembler();
  final _tx = PbleReassembler();
  int _fragments = 0;
  int _largestPacket = 0;
  void offer(List<int> packet, {required bool inbound}) {
    if (inbound) {
      if (packet.first & Pble.fragFirst != 0) {
        _fragments = 0;
        _largestPacket = 0;
      }
      _fragments++;
      if (packet.length > _largestPacket) _largestPacket = packet.length;
    }
    final message = (inbound ? _rx : _tx).offer(Uint8List.fromList(packet));
    if (message == null) return;
    final frame = decodeFrame(message);
    if (!inbound && frame.type == Pble.typeCmd) commands.add(frame.opcode);
    if (inbound &&
        frame.type == Pble.typeEvt &&
        frame.opcode == PbleOpcode.runStatusChanged.code) {
      taggedEvents.add(<String, Object?>{
        'fragments': _fragments,
        'largestPacket': _largestPacket,
        'payloadBytes': frame.payload.length,
      });
    }
  }
}

// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

import 'dart:convert';
import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';

import 'package:pyble/pble/engine.dart';
import 'package:pyble/pble/frame.dart';
import 'package:pyble/pble/hello.dart';
import 'package:pyble/pble/pble_constants.dart';
import 'package:pyble/pble/types.dart';

import '../support/fake_byte_transport.dart';
import '../support/repo_paths.dart';

typedef JsonMap = Map<String, dynamic>;

const String _clientEmits = 'dart-client-emits';
const String _agentOnly = 'agent-only';

// Every shared semantic vector has an explicit Dart role. An added vector
// therefore fails this suite until its ownership is reviewed. Agent-only means
// that the valid app stack cannot originate the malformed/server-side input;
// it does not mean that Dart pretends to exercise the firmware admission path.
const Map<String, String> _helloRoles = <String, String>{
  'canonical_current_app': _clientEmits,
  'offer_order_unknown_key_and_trailing_lf': _agentOnly,
  'two_trailing_lf_are_not_canonical': _agentOnly,
  'well_formed_offer_without_v1': _clientEmits,
  'version_decimal_leading_zero_is_not_canonical': _agentOnly,
  'version_decimal_exceeds_uint8': _agentOnly,
  'more_than_eight_version_offers': _agentOnly,
  'missing_proto_versions': _agentOnly,
  'duplicate_required_key': _agentOnly,
  'duplicate_app_name': _agentOnly,
  'duplicate_app_version': _agentOnly,
  'empty_version_list_element': _agentOnly,
  'empty_interior_line': _agentOnly,
  'invalid_unknown_key_character': _agentOnly,
  'unknown_key_33_bytes': _agentOnly,
  'carriage_return_is_not_hello_ascii': _agentOnly,
  'non_ascii_app_name': _agentOnly,
  'app_name_33_bytes': _agentOnly,
  'empty_app_version': _agentOnly,
  'app_version_33_bytes': _agentOnly,
  'unknown_value_33_bytes': _agentOnly,
  'unknown_value_nonprintable': _agentOnly,
  'unknown_value_splits_at_first_equals': _agentOnly,
  'payload_193_bytes': _agentOnly,
};

const Map<String, String> _inboundRoles = <String, String>{
  'pre_hello_response_bearing_command': _agentOnly,
  'pre_hello_no_response_command_has_no_effect': _agentOnly,
  'post_hello_command_is_admitted': _clientEmits,
  'valid_crc_inbound_rsp_is_silent': _agentOnly,
  'valid_crc_inbound_evt_is_silent': _agentOnly,
  'valid_crc_command_id_zero_is_silent': _agentOnly,
  'bad_crc_command_precedes_session_gate': _agentOnly,
  'bad_crc_precedes_wrong_direction_gate': _agentOnly,
  'valid_crc_unsupported_frame_version': _agentOnly,
  'short_input_without_safe_correlation_is_silent': _agentOnly,
  'length_mismatch_with_safe_header_is_refused': _agentOnly,
  'length_mismatch_wrong_direction_is_silent': _agentOnly,
  'length_mismatch_zero_id_is_silent': _agentOnly,
  'length_mismatch_unsupported_version_is_silent': _agentOnly,
  'unknown_opcode_after_hello_is_not_a_violation': _agentOnly,
  'valid_crc_wrong_direction_precedes_unsupported_version': _agentOnly,
  'valid_crc_zero_id_precedes_unsupported_version': _agentOnly,
  'pre_hello_unknown_opcode_hits_session_gate_first': _agentOnly,
};

const Map<String, String> _sequenceRoles = <String, String>{
  'compatible_repeat_is_idempotent': _clientEmits,
  'failed_repeat_preserves_negotiated_state': _clientEmits,
  'malformed_repeat_preserves_negotiated_state': _agentOnly,
  'disconnect_and_reconnect_clear_negotiation': _agentOnly,
  'unpublished_hello_does_not_negotiate': _agentOnly,
};

const Map<String, String> _violationRoles = <String, String>{
  'eighth_pre_hello_command_terminates_once_without_reply': _agentOnly,
};

Set<String> _names(List<dynamic> cases) => cases
    .cast<JsonMap>()
    .map((JsonMap value) => value['name'] as String)
    .toSet();

void _expectExactRoles(List<dynamic> cases, Map<String, String> roles) {
  expect(roles.keys.toSet(), _names(cases));
  expect(roles.values.toSet(), <String>{_clientEmits, _agentOnly});
}

JsonMap _byName(List<dynamic> cases, String name) =>
    cases.cast<JsonMap>().singleWhere((JsonMap value) => value['name'] == name);

Uint8List _asciiPayload(JsonMap value) =>
    Uint8List.fromList(ascii.encode(value['payload_ascii'] as String));

Map<String, String> _helloFields(JsonMap value) => <String, String>{
  for (final String line in (value['payload_ascii'] as String).split('\n'))
    line.substring(0, line.indexOf('=')): line.substring(line.indexOf('=') + 1),
};

List<int> _helloOffer(JsonMap value) => _helloFields(
  value,
)['proto_versions']!.split(',').map(int.parse).toList(growable: false);

Uint8List _responsePayload(int status) {
  if (status != PbleStatus.ok.code) return Uint8List.fromList(<int>[status]);
  return Uint8List.fromList(<int>[
    status,
    ...utf8.encode(
      <String>[
        'proto=1',
        'agent=0.6.1',
        'chip=esp32',
        'mpy=1.28.0',
        'fs_root=/',
        'mtu=247',
        'window=8',
        'chunk=229',
        'free_mem=8192',
        'has_sd=0',
        'has_identify=0',
        'identify_led=255',
        'auto_run=0',
        'device_id=1234',
        'label=',
      ].join('\n'),
    ),
  ]);
}

Future<void> _answerHello({
  required FakeByteTransport transport,
  required Future<HelloResult> pending,
  required int status,
}) async {
  await pumpEventQueue();
  final PbleFrame command = transport.sentFrames.last;
  expect(command.type, Pble.typeCmd);
  expect(command.opcode, PbleOpcode.hello.code);
  expect(command.id, isNot(Pble.evtId));
  transport.deliverFrame(
    PbleFrame(
      type: Pble.typeRsp,
      opcode: command.opcode,
      id: command.id,
      payload: _responsePayload(status),
    ),
  );
  if (status == PbleStatus.ok.code) {
    await pending;
  } else {
    await expectLater(pending, throwsA(isA<EUnsupported>()));
  }
}

void main() {
  final JsonMap corpus =
      jsonDecode(v061SessionCorpus().readAsStringSync()) as JsonMap;
  final List<dynamic> helloCases = corpus['hello_cases'] as List<dynamic>;
  final List<dynamic> inboundCases = corpus['inbound_cases'] as List<dynamic>;
  final List<dynamic> sequences = corpus['session_sequences'] as List<dynamic>;

  group('v0.6.1 shared session corpus Dart ownership', () {
    test('assigns every vector to the client or the agent exactly once', () {
      _expectExactRoles(helloCases, _helloRoles);
      _expectExactRoles(inboundCases, _inboundRoles);
      _expectExactRoles(sequences, _sequenceRoles);
      expect(
        _violationRoles.keys.toSet(),
        _names(<dynamic>[corpus['violation_budget_case'] as JsonMap]),
      );
      // The violation budget is an agent receive/admission obligation. A
      // conforming app never emits the eight invalid pre-HELLO commands.
      expect(_violationRoles.values.single, _agentOnly);
    });

    test('emits every client-applicable HELLO case byte-for-byte', () async {
      for (final MapEntry<String, String> role in _helloRoles.entries) {
        if (role.value != _clientEmits) continue;
        final JsonMap vector = _byName(helloCases, role.key);
        final Map<String, String> fields = _helloFields(vector);
        final FakeByteTransport transport = FakeByteTransport();
        final PbleEngine engine = PbleEngine(transport);
        final HelloNegotiator negotiator = HelloNegotiator(
          engine: engine,
          appName: fields['app_name']!,
          appVersion: fields['app_version']!,
        );
        try {
          final Future<HelloResult> pending = negotiator.negotiate(
            offer: _helloOffer(vector),
          );
          await pumpEventQueue();
          expect(
            transport.sentFrames.single.payload,
            orderedEquals(_asciiPayload(vector)),
            reason: role.key,
          );
          await _answerHello(
            transport: transport,
            pending: pending,
            status: vector['expected_status'] as int,
          );
        } finally {
          await engine.dispose();
          await transport.dispose();
        }
      }
    });

    test('emits every client-applicable post-HELLO command vector', () async {
      final JsonMap vector = _byName(
        inboundCases,
        _inboundRoles.entries
            .singleWhere(
              (MapEntry<String, String> role) => role.value == _clientEmits,
            )
            .key,
      );
      final FakeByteTransport transport = FakeByteTransport();
      final PbleEngine engine = PbleEngine(transport);
      final HelloNegotiator negotiator = HelloNegotiator(
        engine: engine,
        appName: 'PyBLE',
        appVersion: '0.2.0',
      );
      try {
        await _answerHello(
          transport: transport,
          pending: negotiator.negotiate(),
          status: PbleStatus.ok.code,
        );
        final JsonMap frame = vector['frame'] as JsonMap;
        final Future<PbleFrame> pending = engine.request(
          PbleFrame(
            type: Pble.typeCmd,
            opcode: frame['opcode'] as int,
            id: engine.nextId(),
            payload: Uint8List(0),
          ),
        );
        await pumpEventQueue();
        final PbleFrame sent = transport.sentFrames.last;
        expect(sent.type, frame['type']);
        expect(sent.opcode, frame['opcode']);
        expect(sent.id, isNot(Pble.evtId));
        final JsonMap expected = vector['expected'] as JsonMap;
        transport.deliverFrame(
          PbleFrame(
            type: Pble.typeRsp,
            opcode: sent.opcode,
            id: sent.id,
            payload: Uint8List.fromList(<int>[expected['status'] as int]),
          ),
        );
        expect((await pending).payload.single, expected['status']);
      } finally {
        await engine.dispose();
        await transport.dispose();
      }
    });

    test('drives every client-applicable repeated-HELLO sequence', () async {
      for (final MapEntry<String, String> role in _sequenceRoles.entries) {
        if (role.value != _clientEmits) continue;
        final JsonMap sequence = _byName(sequences, role.key);
        final FakeByteTransport transport = FakeByteTransport();
        final PbleEngine engine = PbleEngine(transport);
        final HelloNegotiator negotiator = HelloNegotiator(
          engine: engine,
          appName: 'PyBLE',
          appVersion: '0.2.0',
        );
        try {
          for (final JsonMap step
              in (sequence['steps'] as List<dynamic>).cast<JsonMap>()) {
            final int status = step['status'] as int;
            if (step['action'] == 'hello') {
              final JsonMap vector = _byName(
                helloCases,
                step['case'] as String,
              );
              await _answerHello(
                transport: transport,
                pending: negotiator.negotiate(offer: _helloOffer(vector)),
                status: status,
              );
              continue;
            }

            expect(step['action'], 'command');
            final Future<PbleFrame> pending = engine.request(
              PbleFrame(
                type: Pble.typeCmd,
                opcode: step['opcode'] as int,
                id: engine.nextId(),
                payload: Uint8List(0),
              ),
            );
            await pumpEventQueue();
            final PbleFrame sent = transport.sentFrames.last;
            transport.deliverFrame(
              PbleFrame(
                type: Pble.typeRsp,
                opcode: sent.opcode,
                id: sent.id,
                payload: Uint8List.fromList(<int>[status]),
              ),
            );
            expect((await pending).payload.single, status, reason: role.key);
          }
        } finally {
          await engine.dispose();
          await transport.dispose();
        }
      }
    });
  });
}

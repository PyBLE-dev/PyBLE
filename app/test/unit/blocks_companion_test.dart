// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';

import 'package:pyble/blocks/blocks.dart';

void main() {
  const String sourcePath = '/blocks.py';
  const String source = "print('Hello, PyBLE!')\n";
  const Map<String, Object?> workspace = <String, Object?>{
    'variables': <Object?>[
      <String, Object?>{'name': 'message', 'id': 'variable-message'},
    ],
    'blocks': <String, Object?>{
      'languageVersion': 0,
      'blocks': <Object?>[
        <String, Object?>{
          'type': 'text_print',
          'id': 'print-message',
          'x': 48,
          'y': 48,
          'collapsed': true,
          'icons': <String, Object?>{
            'comment': <String, Object?>{
              'text': 'Preserve me.',
              'pinned': false,
              'height': 80,
              'width': 160,
            },
          },
        },
      ],
    },
  };

  group('versioned Blocks companion', () {
    test('derives one adjacent technical sidecar path', () {
      expect(
        blocksCompanionPathFor(sourcePath),
        '/blocks.py.pyble-blocks.json',
      );
      expect(
        blocksCompanionPathFor('/lib/blink.py'),
        '/lib/blink.py.pyble-blocks.json',
      );
      expect(
        () => blocksCompanionPathFor('relative.py'),
        throwsA(isA<ArgumentError>()),
      );
      for (final String invalid in <String>[
        '/notes.txt',
        '/../main.py',
        '/lib/../main.py',
        '/lib//main.py',
        r'/lib\main.py',
        '/main.py.pbltmp',
        '/pyble_agent.py',
        '/pble_config.py',
        '/_boot.py',
        '/boot.py',
      ]) {
        expect(
          () => blocksCompanionPathFor(invalid),
          throwsA(isA<ArgumentError>()),
          reason: invalid,
        );
      }
      expect(
        () => blocksCompanionPathFor('/${'x' * 108}.py'),
        throwsA(isA<ArgumentError>()),
        reason:
            'the adjacent sidecar must also fit PBLE/1\'s 128-byte path cap',
      );
    });

    test('round-trips every ordinary Blockly workspace field', () {
      final BlocksCompanion created = BlocksCompanion.create(
        pythonPath: sourcePath,
        pythonSource: source,
        workspaceJson: jsonEncode(workspace),
      );

      final BlocksCompanion parsed = BlocksCompanion.parse(created.encode());

      expect(parsed.format, kBlocksCompanionFormat);
      expect(parsed.version, kBlocksCompanionVersion);
      expect(parsed.pythonPath, sourcePath);
      expect(parsed.pythonEncoding, 'utf-8');
      expect(parsed.pythonByteLength, utf8.encode(source).length);
      expect(parsed.pythonCrc32, blocksCompanionCrc32(utf8.encode(source)));
      expect(parsed.pythonSource, source);
      expect(parsed.generatorId, kBlocksCompanionGeneratorId);
      expect(parsed.generatorVersion, kBlocksCompanionGeneratorVersion);
      expect(parsed.blocklyVersion, kBlocksCompanionBlocklyVersion);
      expect(
        jsonDecode(parsed.workspaceJson),
        jsonDecode(jsonEncode(workspace)),
      );
      expect(parsed.matchesPython(path: sourcePath, source: source), isTrue);
    });

    test('encoding is deterministic and schema keys are frozen', () {
      final BlocksCompanion first = BlocksCompanion.create(
        pythonPath: sourcePath,
        pythonSource: source,
        workspaceJson: jsonEncode(workspace),
      );
      final BlocksCompanion second = BlocksCompanion.create(
        pythonPath: sourcePath,
        pythonSource: source,
        workspaceJson: jsonEncode(workspace),
      );

      expect(first.encode(), second.encode());
      expect(
        (jsonDecode(first.encode())! as Map<String, dynamic>).keys,
        <String>['format', 'version', 'source', 'generator', 'workspace'],
      );
      final Map<String, dynamic> encoded =
          jsonDecode(first.encode())! as Map<String, dynamic>;
      expect(
        (encoded['source']! as Map<String, dynamic>)['crc32'],
        matches(RegExp(r'^[0-9a-f]{8}$')),
      );
    });

    test('one-byte source, path, length, or CRC mismatch rejects recovery', () {
      final BlocksCompanion companion = BlocksCompanion.create(
        pythonPath: sourcePath,
        pythonSource: source,
        workspaceJson: jsonEncode(workspace),
      );

      expect(
        companion.matchesPython(path: sourcePath, source: '$source '),
        isFalse,
      );
      expect(
        companion.matchesPython(path: '/other.py', source: source),
        isFalse,
      );

      final Map<String, dynamic> wrongLength =
          jsonDecode(companion.encode())! as Map<String, dynamic>;
      (wrongLength['source']! as Map<String, dynamic>)['byteLength'] = 1;
      expect(
        () => BlocksCompanion.parse(jsonEncode(wrongLength)),
        throwsA(isA<BlocksCompanionFormatException>()),
      );

      final Map<String, dynamic> wrongCrc =
          jsonDecode(companion.encode())! as Map<String, dynamic>;
      (wrongCrc['source']! as Map<String, dynamic>)['crc32'] = '00000000';
      expect(
        () => BlocksCompanion.parse(jsonEncode(wrongCrc)),
        throwsA(isA<BlocksCompanionFormatException>()),
      );

      final Map<String, dynamic> numericCrc =
          jsonDecode(companion.encode())! as Map<String, dynamic>;
      (numericCrc['source']! as Map<String, dynamic>)['crc32'] =
          companion.pythonCrc32;
      expect(
        () => BlocksCompanion.parse(jsonEncode(numericCrc)),
        throwsA(isA<BlocksCompanionFormatException>()),
      );

      final Map<String, dynamic> uppercaseCrc =
          jsonDecode(companion.encode())! as Map<String, dynamic>;
      (uppercaseCrc['source']! as Map<String, dynamic>)['crc32'] = 'ABCDEF12';
      expect(
        () => BlocksCompanion.parse(jsonEncode(uppercaseCrc)),
        throwsA(isA<BlocksCompanionFormatException>()),
      );
    });

    test(
      'rejects unsupported versions, generators, and malformed workspace',
      () {
        final BlocksCompanion companion = BlocksCompanion.create(
          pythonPath: sourcePath,
          pythonSource: source,
          workspaceJson: jsonEncode(workspace),
        );
        final Map<String, dynamic> envelope =
            jsonDecode(companion.encode())! as Map<String, dynamic>;

        for (final void Function(Map<String, dynamic>) mutate
            in <void Function(Map<String, dynamic>)>[
              (Map<String, dynamic> value) => value['format'] = 'other',
              (Map<String, dynamic> value) => value['version'] = 2,
              (Map<String, dynamic> value) =>
                  (value['source']! as Map<String, dynamic>)['encoding'] =
                      'latin-1',
              (Map<String, dynamic> value) =>
                  (value['generator']! as Map<String, dynamic>)['id'] = 'other',
              (Map<String, dynamic> value) =>
                  (value['generator']! as Map<String, dynamic>)['version'] = 2,
              (Map<String, dynamic> value) =>
                  (value['generator']! as Map<String, dynamic>)['blockly'] =
                      '0.0.0',
              (Map<String, dynamic> value) =>
                  value['workspace'] = <String, Object?>{},
            ]) {
          final Map<String, dynamic> changed =
              jsonDecode(jsonEncode(envelope))! as Map<String, dynamic>;
          mutate(changed);
          expect(
            () => BlocksCompanion.parse(jsonEncode(changed)),
            throwsA(isA<BlocksCompanionFormatException>()),
            reason: jsonEncode(changed),
          );
        }
      },
    );

    test('rejects non-object and oversized envelopes', () {
      expect(
        () => BlocksCompanion.parse('[]'),
        throwsA(isA<BlocksCompanionFormatException>()),
      );
      expect(
        () => BlocksCompanion.parse(
          '{"padding":"${'x' * kMaxBlocksCompanionBytes}"}',
        ),
        throwsA(isA<BlocksCompanionFormatException>()),
      );
      final Map<String, Object?> oversizedWorkspace =
          jsonDecode(jsonEncode(workspace))! as Map<String, Object?>;
      oversizedWorkspace['padding'] = 'x' * kMaxBlocksCompanionBytes;
      expect(
        () => BlocksCompanion.create(
          pythonPath: sourcePath,
          pythonSource: source,
          workspaceJson: jsonEncode(oversizedWorkspace),
        ),
        throwsA(isA<BlocksCompanionFormatException>()),
      );
    });
  });

  test('CRC-32 uses the standard check vector', () {
    expect(blocksCompanionCrc32(ascii.encode('123456789')), 0xcbf43926);
  });
}

// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

/// Versioned, source-bound persistence envelope for an exact Blockly workspace.
///
/// The companion is a commit record, not executable input. Blocks writes the
/// verified Python file first and this adjacent JSON file last. Recovery trusts
/// it only when every source identity field agrees with the Python bytes and
/// the production Blockly host independently restores and regenerates it.
library;

import 'dart:convert';

import 'package:flutter/foundation.dart' show immutable;

const String kBlocksCompanionFormat = 'pyble-blocks';
const int kBlocksCompanionVersion = 1;
const String kBlocksCompanionSuffix = '.pyble-blocks.json';
const int kMaxBlocksCompanionBytes = 1024 * 1024;
const int kMaxBlocksBoardPathBytes = 128;

const String kBlocksCompanionGeneratorId = 'pyble-blockly-python';
const int kBlocksCompanionGeneratorVersion = 1;
const String kBlocksCompanionBlocklyVersion = '13.1.0';

/// Derives the adjacent companion path for one absolute board Python path.
String blocksCompanionPathFor(String pythonPath) {
  final List<String> segments = pythonPath.split('/');
  final String topLevel = segments.length > 1 ? segments[1] : '';
  final bool hasControlCharacter = pythonPath.runes.any(
    (int value) => value < 0x20 || value == 0x7f,
  );
  final bool hasReservedSegment = segments.any(
    (String segment) => segment.toLowerCase().endsWith('.pbltmp'),
  );
  if (!pythonPath.startsWith('/') ||
      pythonPath.length < 4 ||
      !pythonPath.endsWith('.py') ||
      pythonPath.endsWith('/') ||
      pythonPath.contains(r'\') ||
      hasControlCharacter ||
      segments
          .skip(1)
          .any(
            (String segment) =>
                segment.isEmpty || segment == '.' || segment == '..',
          ) ||
      topLevel.startsWith('pyble') ||
      topLevel.startsWith('pble') ||
      topLevel == '_boot.py' ||
      topLevel == 'boot.py' ||
      hasReservedSegment) {
    throw ArgumentError.value(
      pythonPath,
      'pythonPath',
      'must be a canonical absolute Python workspace path',
    );
  }
  final String companionPath = '$pythonPath$kBlocksCompanionSuffix';
  if (utf8.encode(pythonPath).length > kMaxBlocksBoardPathBytes ||
      utf8.encode(companionPath).length > kMaxBlocksBoardPathBytes) {
    throw ArgumentError.value(
      pythonPath,
      'pythonPath',
      'source and companion paths must each fit 128 UTF-8 bytes',
    );
  }
  return companionPath;
}

/// CRC-32/ISO-HDLC used as an accidental-corruption check.
///
/// This is not an authenticity or security primitive. Exact source text,
/// byte-length, path, generator identity, workspace reserialization, and
/// production regeneration are independently checked before recovery.
int blocksCompanionCrc32(List<int> bytes) {
  int crc = 0xffffffff;
  for (final int byte in bytes) {
    crc ^= byte;
    for (int bit = 0; bit < 8; bit += 1) {
      crc = (crc & 1) != 0 ? (crc >>> 1) ^ 0xedb88320 : crc >>> 1;
    }
  }
  return (crc ^ 0xffffffff) & 0xffffffff;
}

class BlocksCompanionFormatException implements Exception {
  const BlocksCompanionFormatException(this.message);

  final String message;

  @override
  String toString() => 'BlocksCompanionFormatException($message)';
}

@immutable
class BlocksCompanion {
  const BlocksCompanion._({
    required this.pythonPath,
    required this.pythonByteLength,
    required this.pythonCrc32,
    required this.pythonSource,
    required this.workspaceJson,
  });

  final String pythonPath;
  final int pythonByteLength;
  final int pythonCrc32;
  final String pythonSource;
  final String workspaceJson;

  String get format => kBlocksCompanionFormat;
  int get version => kBlocksCompanionVersion;
  String get pythonEncoding => 'utf-8';
  String get generatorId => kBlocksCompanionGeneratorId;
  int get generatorVersion => kBlocksCompanionGeneratorVersion;
  String get blocklyVersion => kBlocksCompanionBlocklyVersion;

  factory BlocksCompanion.create({
    required String pythonPath,
    required String pythonSource,
    required String workspaceJson,
  }) {
    blocksCompanionPathFor(pythonPath);
    final Map<String, dynamic> workspace = _decodeWorkspace(workspaceJson);
    final List<int> sourceBytes = utf8.encode(pythonSource);
    final BlocksCompanion companion = BlocksCompanion._(
      pythonPath: pythonPath,
      pythonByteLength: sourceBytes.length,
      pythonCrc32: blocksCompanionCrc32(sourceBytes),
      pythonSource: pythonSource,
      workspaceJson: jsonEncode(workspace),
    );
    if (utf8.encode(companion.encode()).length > kMaxBlocksCompanionBytes) {
      throw const BlocksCompanionFormatException(
        'companion exceeds the 1 MiB admission limit',
      );
    }
    return companion;
  }

  factory BlocksCompanion.parse(String encoded) {
    if (utf8.encode(encoded).length > kMaxBlocksCompanionBytes) {
      throw const BlocksCompanionFormatException(
        'companion exceeds the 1 MiB admission limit',
      );
    }
    final Object? decoded;
    try {
      decoded = jsonDecode(encoded);
    } on FormatException catch (error) {
      throw BlocksCompanionFormatException(error.message);
    }
    if (decoded is! Map<String, dynamic>) {
      throw const BlocksCompanionFormatException(
        'companion must be a JSON object',
      );
    }
    if (decoded['format'] != kBlocksCompanionFormat ||
        decoded['version'] != kBlocksCompanionVersion) {
      throw const BlocksCompanionFormatException(
        'unsupported companion format or version',
      );
    }

    final Object? rawSource = decoded['source'];
    final Object? rawGenerator = decoded['generator'];
    final Object? rawWorkspace = decoded['workspace'];
    if (rawSource is! Map<String, dynamic> ||
        rawGenerator is! Map<String, dynamic> ||
        rawWorkspace is! Map<String, dynamic>) {
      throw const BlocksCompanionFormatException(
        'companion source, generator, and workspace must be objects',
      );
    }

    final Object? path = rawSource['path'];
    final Object? encoding = rawSource['encoding'];
    final Object? byteLength = rawSource['byteLength'];
    final Object? crc32 = rawSource['crc32'];
    final Object? text = rawSource['text'];
    if (path is! String ||
        encoding != 'utf-8' ||
        byteLength is! int ||
        byteLength < 0 ||
        crc32 is! String ||
        !RegExp(r'^[0-9a-f]{8}$').hasMatch(crc32) ||
        text is! String) {
      throw const BlocksCompanionFormatException(
        'companion source identity is malformed',
      );
    }
    try {
      blocksCompanionPathFor(path);
    } on ArgumentError {
      throw const BlocksCompanionFormatException(
        'companion source path is not absolute',
      );
    }
    if (rawGenerator['id'] != kBlocksCompanionGeneratorId ||
        rawGenerator['version'] != kBlocksCompanionGeneratorVersion ||
        rawGenerator['blockly'] != kBlocksCompanionBlocklyVersion) {
      throw const BlocksCompanionFormatException(
        'companion generator identity is unsupported',
      );
    }

    final List<int> bytes = utf8.encode(text);
    final int parsedCrc32 = int.parse(crc32, radix: 16);
    if (bytes.length != byteLength ||
        blocksCompanionCrc32(bytes) != parsedCrc32) {
      throw const BlocksCompanionFormatException(
        'companion source integrity fields do not match its text',
      );
    }
    final Map<String, dynamic> workspace = _validateWorkspace(rawWorkspace);
    return BlocksCompanion._(
      pythonPath: path,
      pythonByteLength: byteLength,
      pythonCrc32: parsedCrc32,
      pythonSource: text,
      workspaceJson: jsonEncode(workspace),
    );
  }

  /// Whether this commit record describes these exact Python bytes and path.
  bool matchesPython({required String path, required String source}) {
    if (path != pythonPath || source != pythonSource) return false;
    final List<int> bytes = utf8.encode(source);
    return bytes.length == pythonByteLength &&
        blocksCompanionCrc32(bytes) == pythonCrc32;
  }

  String encode() {
    final Object? workspace = jsonDecode(workspaceJson);
    return jsonEncode(<String, Object?>{
      'format': kBlocksCompanionFormat,
      'version': kBlocksCompanionVersion,
      'source': <String, Object?>{
        'path': pythonPath,
        'encoding': 'utf-8',
        'byteLength': pythonByteLength,
        'crc32': pythonCrc32.toRadixString(16).padLeft(8, '0'),
        'text': pythonSource,
      },
      'generator': <String, Object?>{
        'id': kBlocksCompanionGeneratorId,
        'version': kBlocksCompanionGeneratorVersion,
        'blockly': kBlocksCompanionBlocklyVersion,
      },
      'workspace': workspace,
    });
  }
}

Map<String, dynamic> _decodeWorkspace(String encoded) {
  final Object? decoded;
  try {
    decoded = jsonDecode(encoded);
  } on FormatException catch (error) {
    throw BlocksCompanionFormatException(error.message);
  }
  if (decoded is! Map<String, dynamic>) {
    throw const BlocksCompanionFormatException(
      'workspace must be a JSON object',
    );
  }
  return _validateWorkspace(decoded);
}

Map<String, dynamic> _validateWorkspace(Map<String, dynamic> workspace) {
  final Object? blocks = workspace['blocks'];
  if (blocks is! Map<String, dynamic> ||
      blocks['languageVersion'] != 0 ||
      blocks['blocks'] is! List<dynamic>) {
    throw const BlocksCompanionFormatException(
      'workspace is not ordinary Blockly serialization',
    );
  }
  return workspace;
}

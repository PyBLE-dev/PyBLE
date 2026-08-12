// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

/// A deliberately bounded, offline Python-to-Blockly importer.
///
/// This is not a general Python parser. It admits a frozen beginner subset,
/// reports a source-positioned diagnostic for everything else, and produces no
/// workspace at all on failure. The production Blockly host remains the oracle:
/// callers must restore, reserialize, and regenerate a candidate before asking
/// the user to commit it.
library;

import 'dart:convert';

import 'package:flutter/foundation.dart' show immutable;

const int kMaxPythonBlocksSourceBytes = 256 * 1024;
const int kMaxPythonBlocksLines = 4096;
const int kMaxPythonBlocksNodes = 20000;
const int kMaxPythonBlocksIndentationLevels = 32;
const int kMaxPythonBlocksFunctions = 16;
const int kMaxPythonBlocksParameters = 8;
const int kMaxBlocklySafeInteger = 9007199254740991;
const int _maxPythonBlocksExpressionDepth = 256;
const int _maxPythonBlocksExpressionTokens = kMaxPythonBlocksNodes * 4;

const Set<String> _pythonKeywords = <String>{
  'False',
  'None',
  'True',
  'and',
  'as',
  'assert',
  'async',
  'await',
  'break',
  'class',
  'continue',
  'def',
  'del',
  'elif',
  'else',
  'except',
  'finally',
  'for',
  'from',
  'global',
  'if',
  'import',
  'in',
  'is',
  'lambda',
  'nonlocal',
  'not',
  'or',
  'pass',
  'raise',
  'return',
  'try',
  'while',
  'with',
  'yield',
};

// Blockly's pinned Python generator renames every identifier in this set.
// Importing one as if its spelling were preserved would therefore be lossy.
const Set<String> _generatorReservedNames = <String>{
  ..._pythonKeywords,
  'Pin',
  'NeoPixel',
  'ST7789',
  'rgb565',
  'sleep_ms',
  'print',
  'NotImplemented',
  'Ellipsis',
  '__debug__',
  'quit',
  'exit',
  'copyright',
  'license',
  'credits',
  'ArithmeticError',
  'AssertionError',
  'AttributeError',
  'BaseException',
  'BlockingIOError',
  'BrokenPipeError',
  'BufferError',
  'BytesWarning',
  'ChildProcessError',
  'ConnectionAbortedError',
  'ConnectionError',
  'ConnectionRefusedError',
  'ConnectionResetError',
  'DeprecationWarning',
  'EOFError',
  'EnvironmentError',
  'Exception',
  'FileExistsError',
  'FileNotFoundError',
  'FloatingPointError',
  'FutureWarning',
  'GeneratorExit',
  'IOError',
  'ImportError',
  'ImportWarning',
  'IndentationError',
  'IndexError',
  'InterruptedError',
  'IsADirectoryError',
  'KeyError',
  'KeyboardInterrupt',
  'LookupError',
  'MemoryError',
  'ModuleNotFoundError',
  'NameError',
  'NotADirectoryError',
  'NotImplementedError',
  'OSError',
  'OverflowError',
  'PendingDeprecationWarning',
  'PermissionError',
  'ProcessLookupError',
  'RecursionError',
  'ReferenceError',
  'ResourceWarning',
  'RuntimeError',
  'RuntimeWarning',
  'StandardError',
  'StopAsyncIteration',
  'StopIteration',
  'SyntaxError',
  'SyntaxWarning',
  'SystemError',
  'SystemExit',
  'TabError',
  'TimeoutError',
  'TypeError',
  'UnboundLocalError',
  'UnicodeDecodeError',
  'UnicodeEncodeError',
  'UnicodeError',
  'UnicodeTranslateError',
  'UnicodeWarning',
  'UserWarning',
  'ValueError',
  'Warning',
  'ZeroDivisionError',
  '_',
  '__build_class__',
  '__doc__',
  '__import__',
  '__loader__',
  '__name__',
  '__package__',
  '__spec__',
  'abs',
  'all',
  'any',
  'apply',
  'ascii',
  'basestring',
  'bin',
  'bool',
  'buffer',
  'bytearray',
  'bytes',
  'callable',
  'chr',
  'classmethod',
  'cmp',
  'coerce',
  'compile',
  'complex',
  'delattr',
  'dict',
  'dir',
  'divmod',
  'enumerate',
  'eval',
  'exec',
  'execfile',
  'file',
  'filter',
  'float',
  'format',
  'frozenset',
  'getattr',
  'globals',
  'hasattr',
  'hash',
  'help',
  'hex',
  'id',
  'input',
  'int',
  'intern',
  'isinstance',
  'issubclass',
  'iter',
  'len',
  'list',
  'locals',
  'long',
  'map',
  'math',
  'max',
  'memoryview',
  'min',
  'next',
  'Number',
  'object',
  'oct',
  'open',
  'ord',
  'pow',
  'property',
  'random',
  'range',
  'raw_input',
  'reduce',
  'reload',
  'repr',
  'reversed',
  'round',
  'set',
  'setattr',
  'slice',
  'sorted',
  'staticmethod',
  'str',
  'sum',
  'super',
  'tuple',
  'type',
  'unichr',
  'unicode',
  'vars',
  'xrange',
  'zip',
};

@immutable
class PythonBlocksDiagnostic {
  const PythonBlocksDiagnostic({
    required this.code,
    required this.line,
    required this.column,
    required this.endLine,
    required this.endColumn,
    this.severity = 'error',
    this.messageKey = 'pythonBlocksDiagnostic',
    this.args = const <String, Object?>{},
  }) : assert(severity == 'error' || severity == 'warning'),
       assert(line >= 1),
       assert(column >= 1),
       assert(endLine >= line),
       assert(endColumn >= 1);

  /// Stable ASCII diagnostic identifier.
  final String code;

  /// `error` or `warning`; v1 parsing currently emits errors only.
  final String severity;

  /// Compatibility aliases retained for the first importer UI.
  final int line;
  final int column;
  final int endLine;
  final int endColumn;

  /// Frozen one-based, end-exclusive range names.
  int get startLine => line;
  int get startColumn => column;

  /// ARB lookup key and typed interpolation arguments.
  final String messageKey;
  final Map<String, Object?> args;

  Map<String, Object?> toJson() => <String, Object?>{
    'code': code,
    'severity': severity,
    'startLine': startLine,
    'startColumn': startColumn,
    'endLine': endLine,
    'endColumn': endColumn,
    'messageKey': messageKey,
    'args': args,
  };

  @override
  String toString() => '$code at $line:$column';

  @override
  bool operator ==(Object other) =>
      other is PythonBlocksDiagnostic &&
      other.code == code &&
      other.severity == severity &&
      other.line == line &&
      other.column == column &&
      other.endLine == endLine &&
      other.endColumn == endColumn &&
      other.messageKey == messageKey &&
      _diagnosticArgsEqual(other.args, args);

  @override
  int get hashCode => Object.hash(
    code,
    severity,
    line,
    column,
    endLine,
    endColumn,
    messageKey,
    Object.hashAll(
      args.entries.map(
        (MapEntry<String, Object?> value) =>
            Object.hash(value.key, value.value),
      ),
    ),
  );

  static bool _diagnosticArgsEqual(
    Map<String, Object?> left,
    Map<String, Object?> right,
  ) {
    if (left.length != right.length) return false;
    for (final MapEntry<String, Object?> entry in left.entries) {
      if (!right.containsKey(entry.key) || right[entry.key] != entry.value) {
        return false;
      }
    }
    return true;
  }
}

@immutable
class PythonBlocksConversion {
  const PythonBlocksConversion({
    required this.workspaceJson,
    required this.diagnostics,
    this.semanticFingerprint,
  });

  final String? workspaceJson;
  final List<PythonBlocksDiagnostic> diagnostics;

  /// Deterministic JSON for semantic equality with production-generated code.
  ///
  /// This is present only for a fully validated conversion. It contains no
  /// source text or visual Blockly state.
  final String? semanticFingerprint;

  bool get hasErrors => diagnostics.any(
    (PythonBlocksDiagnostic diagnostic) => diagnostic.severity == 'error',
  );
}

class PythonToBlocksConverter {
  const PythonToBlocksConverter();

  /// Converts user-authored [source], or production Blockly output when
  /// [productionGenerated] is true.
  ///
  /// The latter mode recognizes only the pinned generator's leading
  /// `name = None` workspace-variable preamble. Keeping that normalization
  /// explicit prevents a handwritten assignment from being guessed away.
  PythonBlocksConversion convert(
    String source, {
    bool productionGenerated = false,
  }) {
    if (utf8.encode(source).length > kMaxPythonBlocksSourceBytes) {
      return const PythonBlocksConversion(
        workspaceJson: null,
        diagnostics: <PythonBlocksDiagnostic>[
          PythonBlocksDiagnostic(
            code: 'source_too_large',
            line: 1,
            column: 1,
            endLine: 1,
            endColumn: 1,
          ),
        ],
      );
    }
    if (source.trim().isEmpty) {
      return const PythonBlocksConversion(
        workspaceJson: null,
        diagnostics: <PythonBlocksDiagnostic>[
          PythonBlocksDiagnostic(
            code: 'empty_source',
            line: 1,
            column: 1,
            endLine: 1,
            endColumn: 1,
          ),
        ],
      );
    }

    try {
      final _Program program = _PythonSubsetParser(source).parse();
      final _WorkspaceBuilder builder = _WorkspaceBuilder(
        program,
        normalizeGeneratorPreamble: productionGenerated,
      );
      final Map<String, Object?> workspace = builder.build();
      return PythonBlocksConversion(
        workspaceJson: jsonEncode(workspace),
        diagnostics: const <PythonBlocksDiagnostic>[],
        semanticFingerprint: _SemanticFingerprint(builder.statements).encode(),
      );
    } on _ImportFailure catch (failure) {
      return PythonBlocksConversion(
        workspaceJson: null,
        diagnostics: <PythonBlocksDiagnostic>[failure.diagnostic],
      );
    } on Object {
      // A malformed source must never escape as a raw parser exception into UI.
      return const PythonBlocksConversion(
        workspaceJson: null,
        diagnostics: <PythonBlocksDiagnostic>[
          PythonBlocksDiagnostic(
            code: 'invalid_syntax',
            line: 1,
            column: 1,
            endLine: 1,
            endColumn: 1,
          ),
        ],
      );
    }
  }
}

class _ImportFailure implements Exception {
  const _ImportFailure(this.diagnostic);

  final PythonBlocksDiagnostic diagnostic;
}

Never _fail(String code, int line, int column, {int? endColumn}) {
  throw _ImportFailure(
    PythonBlocksDiagnostic(
      code: code,
      line: line,
      column: column,
      endLine: line,
      endColumn: endColumn ?? column + 1,
      args: <String, Object?>{'code': code, 'line': line, 'column': column},
    ),
  );
}

// ---------------------------------------------------------------------------
// Line/suite parser
// ---------------------------------------------------------------------------

class _SourceLine {
  const _SourceLine({
    required this.number,
    required this.raw,
    required this.indent,
    required this.content,
  });

  final int number;
  final String raw;
  final int indent;
  final String content;
  int get contentColumn => indent + 1;
}

class _ParseBudget {
  int _nodes = 0;

  T node<T extends _Node>(T node) {
    _nodes += 1;
    if (_nodes > kMaxPythonBlocksNodes) {
      _fail('source_too_complex', node.line, node.column);
    }
    return node;
  }
}

class _PythonSubsetParser {
  _PythonSubsetParser(String source)
    : _lines = _prepareLines(
        source.replaceAll('\r\n', '\n').replaceAll('\r', '\n'),
      );

  final List<_SourceLine> _lines;
  final _ParseBudget _budget = _ParseBudget();
  int _index = 0;

  static List<_SourceLine> _prepareLines(String source) {
    final List<String> rawLines = source.split('\n');
    if (rawLines.length > kMaxPythonBlocksLines) {
      _fail('source_too_many_lines', kMaxPythonBlocksLines + 1, 1);
    }
    final List<_SourceLine> lines = <_SourceLine>[];
    for (int index = 0; index < rawLines.length; index += 1) {
      final String raw = rawLines[index];
      int indent = 0;
      while (indent < raw.length && raw.codeUnitAt(indent) == 0x20) {
        indent += 1;
      }
      if (indent < raw.length && raw.codeUnitAt(indent) == 0x09 ||
          raw.contains('\t')) {
        _fail('tabs_not_supported', index + 1, indent + 1);
      }
      final String content = raw.substring(indent);
      final int comment = _outsideStringIndex(content, '#');
      if (comment >= 0) {
        _fail(
          'comments_not_supported',
          index + 1,
          indent + content.substring(0, comment).runes.length + 1,
        );
      }
      final int semicolon = _outsideStringIndex(content, ';');
      if (semicolon >= 0) {
        _fail(
          'multiple_statements_not_supported',
          index + 1,
          indent + content.substring(0, semicolon).runes.length + 1,
        );
      }
      lines.add(
        _SourceLine(
          number: index + 1,
          raw: raw,
          indent: indent,
          content: content.trimRight(),
        ),
      );
    }
    return lines;
  }

  static int _outsideStringIndex(String value, String needle) {
    int quote = 0;
    bool escaped = false;
    for (int index = 0; index < value.length; index += 1) {
      final int char = value.codeUnitAt(index);
      if (quote != 0) {
        if (escaped) {
          escaped = false;
        } else if (char == 0x5c) {
          escaped = true;
        } else if (char == quote) {
          quote = 0;
        }
      } else if (char == 0x27 || char == 0x22) {
        quote = char;
      } else if (value[index] == needle) {
        return index;
      }
    }
    return -1;
  }

  _Program parse() {
    final List<_Stmt> statements = _parseSuite(0, topLevel: true, depth: 0);
    _skipBlank();
    if (_index != _lines.length) {
      final _SourceLine line = _lines[_index];
      _fail('unexpected_indentation', line.number, 1);
    }
    final _Program program = _Program(statements);
    _enforceNodeLimit(program);
    return program;
  }

  List<_Stmt> _parseSuite(
    int indent, {
    required bool topLevel,
    required int depth,
  }) {
    final List<_Stmt> result = <_Stmt>[];
    while (true) {
      _skipBlank();
      if (_index >= _lines.length) break;
      final _SourceLine line = _lines[_index];
      if (line.indent < indent) break;
      if (line.indent > indent) {
        _fail('unexpected_indentation', line.number, 1);
      }
      result.add(_parseStatement(line, topLevel: topLevel, depth: depth));
    }
    return result;
  }

  void _skipBlank() {
    while (_index < _lines.length && _lines[_index].content.trim().isEmpty) {
      _index += 1;
    }
  }

  _Stmt _parseStatement(
    _SourceLine line, {
    required bool topLevel,
    required int depth,
  }) {
    final String text = line.content;

    if (text == 'from machine import Pin') {
      _index += 1;
      return _budget.node(
        _ImportStmt(line.number, line.contentColumn, _ImportKind.pin),
      );
    }
    if (text == 'from neopixel import NeoPixel') {
      _index += 1;
      return _budget.node(
        _ImportStmt(line.number, line.contentColumn, _ImportKind.neoPixel),
      );
    }
    if (text == 'from pyble_st7789 import ST7789') {
      _index += 1;
      return _budget.node(
        _ImportStmt(line.number, line.contentColumn, _ImportKind.st7789),
      );
    }
    if (text == 'from pyble_st7789 import rgb565') {
      _index += 1;
      return _budget.node(
        _ImportStmt(line.number, line.contentColumn, _ImportKind.rgb565),
      );
    }
    if (text == 'from time import sleep_ms') {
      _index += 1;
      return _budget.node(
        _ImportStmt(line.number, line.contentColumn, _ImportKind.sleepMs),
      );
    }
    if (text.startsWith('import ') || text.startsWith('from ')) {
      _fail('unsupported_import', line.number, line.contentColumn);
    }
    if (text == 'pass') {
      _index += 1;
      return _budget.node(_PassStmt(line.number, line.contentColumn));
    }
    if (text == 'return' || text.startsWith('return ')) {
      if (text == 'return') {
        _fail('return_value_required', line.number, line.contentColumn);
      }
      final String value = text.substring('return '.length).trim();
      if (value.isEmpty) {
        _fail('return_value_required', line.number, line.contentColumn);
      }
      _index += 1;
      return _budget.node(
        _ReturnStmt(
          line.number,
          line.contentColumn,
          _parseExpression(line, value),
        ),
      );
    }
    if (text == 'else:' || text.startsWith('elif ')) {
      _fail('unexpected_clause', line.number, line.contentColumn);
    }

    final RegExpMatch? function = RegExp(
      r'^def ([A-Za-z_][A-Za-z0-9_]*)\(([^()]*)\):$',
    ).firstMatch(text);
    if (function != null) {
      if (!topLevel) {
        _fail('nested_function_not_supported', line.number, line.contentColumn);
      }
      final String name = function.group(1)!;
      final String parameterSource = function.group(2)!.trim();
      final List<String> parameters = parameterSource.isEmpty
          ? <String>[]
          : parameterSource
                .split(',')
                .map((String value) => value.trim())
                .toList();
      if (parameters.any(
            (String value) =>
                !RegExp(r'^[A-Za-z_][A-Za-z0-9_]*$').hasMatch(value),
          ) ||
          parameters.toSet().length != parameters.length) {
        _fail(
          'unsupported_function_signature',
          line.number,
          line.contentColumn,
        );
      }
      if (parameters.length > kMaxPythonBlocksParameters) {
        _fail('too_many_function_parameters', line.number, line.contentColumn);
      }
      _index += 1;
      final List<_Stmt> body = _requiredBody(
        line,
        topLevel: false,
        depth: depth,
      );
      return _budget.node(
        _FunctionStmt(line.number, line.contentColumn, name, parameters, body),
      );
    }
    if (text.startsWith('def ')) {
      _fail('unsupported_function_signature', line.number, line.contentColumn);
    }

    final RegExpMatch? ifMatch = RegExp(r'^if (.+):$').firstMatch(text);
    if (ifMatch != null) {
      final _Expr condition = _parseExpression(line, ifMatch.group(1)!);
      _index += 1;
      final List<_Stmt> body = _requiredBody(
        line,
        topLevel: false,
        depth: depth,
      );
      final List<_IfBranch> branches = <_IfBranch>[
        _budget.node(
          _IfBranch(line.number, line.contentColumn, condition, body),
        ),
      ];
      _skipBlank();
      List<_Stmt> otherwise = const <_Stmt>[];
      while (_index < _lines.length) {
        final _SourceLine clause = _lines[_index];
        final RegExpMatch? elifMatch = RegExp(
          r'^elif (.+):$',
        ).firstMatch(clause.content);
        if (clause.indent == line.indent && elifMatch != null) {
          final _Expr condition = _parseExpression(clause, elifMatch.group(1)!);
          _index += 1;
          branches.add(
            _budget.node(
              _IfBranch(
                clause.number,
                clause.contentColumn,
                condition,
                _requiredBody(clause, topLevel: false, depth: depth),
              ),
            ),
          );
          _skipBlank();
          continue;
        }
        if (clause.indent == line.indent && clause.content == 'else:') {
          _index += 1;
          otherwise = _requiredBody(clause, topLevel: false, depth: depth);
        }
        break;
      }
      return _budget.node(
        _IfStmt(line.number, line.contentColumn, branches, otherwise),
      );
    }
    if (text.startsWith('if ')) {
      _fail('invalid_syntax', line.number, line.contentColumn);
    }

    final RegExpMatch? whileMatch = RegExp(r'^while (.+):$').firstMatch(text);
    if (whileMatch != null) {
      final _Expr condition = _parseExpression(line, whileMatch.group(1)!);
      _index += 1;
      return _budget.node(
        _WhileStmt(
          line.number,
          line.contentColumn,
          condition,
          _requiredBody(line, topLevel: false, depth: depth),
        ),
      );
    }
    if (text.startsWith('while ')) {
      _fail('invalid_syntax', line.number, line.contentColumn);
    }

    final RegExpMatch? forMatch = RegExp(
      r'^for ([A-Za-z_][A-Za-z0-9_]*) in range\((.*)\):$',
    ).firstMatch(text);
    if (forMatch != null) {
      final String variable = forMatch.group(1)!;
      final List<_Expr> arguments = _parseExpressionList(
        line,
        forMatch.group(2)!,
      );
      _index += 1;
      return _budget.node(
        _ForStmt(
          line.number,
          line.contentColumn,
          variable,
          arguments,
          _requiredBody(line, topLevel: false, depth: depth),
        ),
      );
    }
    if (text.startsWith('for ')) {
      _fail('unsupported_for_loop', line.number, line.contentColumn);
    }

    final _AssignmentMatch? assignment = _assignment(text);
    if (assignment != null) {
      if (assignment.operator != '=' && assignment.operator != '+=') {
        _fail('unsupported_assignment', line.number, line.contentColumn);
      }
      final String target = text.substring(0, assignment.index).trim();
      final bool simpleTarget = RegExp(
        r'^[A-Za-z_][A-Za-z0-9_]*$',
      ).hasMatch(target);
      if (assignment.operator == '+=' && !simpleTarget) {
        _fail('unsupported_assignment', line.number, line.contentColumn);
      }
      final int valueStart = assignment.index + assignment.operator.length;
      if (_assignment(text.substring(valueStart)) != null) {
        _fail(
          'unsupported_assignment',
          line.number,
          line.contentColumn + valueStart,
        );
      }
      final String expression = text.substring(valueStart).trim();
      if (expression.isEmpty) {
        _fail('invalid_syntax', line.number, line.contentColumn + valueStart);
      }
      _index += 1;
      final _Expr value = _parseExpression(line, expression);
      if (assignment.operator == '+=') {
        return _budget.node(
          _ChangeStmt(line.number, line.contentColumn, target, value),
        );
      }
      if (simpleTarget) {
        return _budget.node(
          _AssignStmt(line.number, line.contentColumn, target, value),
        );
      }
      final _Expr parsedTarget = _parseExpression(line, target);
      if (parsedTarget is! _SubscriptExpr) {
        _fail('unsupported_assignment', line.number, line.contentColumn);
      }
      return _budget.node(
        _SubscriptAssignStmt(
          line.number,
          line.contentColumn,
          parsedTarget.target,
          parsedTarget.index,
          value,
        ),
      );
    }

    _index += 1;
    return _budget.node(
      _ExprStmt(line.number, line.contentColumn, _parseExpression(line, text)),
    );
  }

  List<_Stmt> _requiredBody(
    _SourceLine header, {
    required bool topLevel,
    required int depth,
  }) {
    _skipBlank();
    if (_index >= _lines.length || _lines[_index].indent <= header.indent) {
      _fail(
        'expected_indented_suite',
        header.number,
        header.content.length + header.contentColumn,
      );
    }
    final _SourceLine first = _lines[_index];
    final int childDepth = depth + 1;
    if (childDepth > kMaxPythonBlocksIndentationLevels) {
      _fail(
        'indentation_too_deep',
        first.number,
        1,
        endColumn: first.indent + 1,
      );
    }
    final List<_Stmt> body = _parseSuite(
      first.indent,
      topLevel: topLevel,
      depth: childDepth,
    );
    if (body.isEmpty) {
      _fail(
        'expected_indented_suite',
        header.number,
        header.content.length + header.contentColumn,
      );
    }
    return body;
  }

  _Expr _parseExpression(_SourceLine line, String source) {
    final int offset = line.content.indexOf(source);
    return _ExpressionParser(
      source,
      line.number,
      line.contentColumn +
          (offset < 0 ? 0 : line.content.substring(0, offset).runes.length),
      _budget,
    ).parse();
  }

  List<_Expr> _parseExpressionList(_SourceLine line, String source) {
    final int offset = line.content.indexOf(source);
    return _ExpressionParser(
      source,
      line.number,
      line.contentColumn +
          (offset < 0 ? 0 : line.content.substring(0, offset).runes.length),
      _budget,
    ).parseList();
  }

  static _AssignmentMatch? _assignment(String value) {
    int quote = 0;
    bool escaped = false;
    int depth = 0;
    for (int index = 0; index < value.length; index += 1) {
      final int char = value.codeUnitAt(index);
      if (quote != 0) {
        if (escaped) {
          escaped = false;
        } else if (char == 0x5c) {
          escaped = true;
        } else if (char == quote) {
          quote = 0;
        }
        continue;
      }
      if (char == 0x27 || char == 0x22) {
        quote = char;
      } else if (char == 0x28 || char == 0x5b) {
        depth += 1;
      } else if (char == 0x29 || char == 0x5d) {
        depth -= 1;
      } else if (char == 0x3d && depth == 0) {
        final int before = index == 0 ? 0 : value.codeUnitAt(index - 1);
        final int after = index + 1 >= value.length
            ? 0
            : value.codeUnitAt(index + 1);
        if (before != 0x3d &&
            before != 0x21 &&
            before != 0x3c &&
            before != 0x3e &&
            after != 0x3d) {
          if (before == 0x2b) {
            return _AssignmentMatch(index - 1, '+=');
          }
          if (<int>{0x2d, 0x2a, 0x2f, 0x25}.contains(before)) {
            return _AssignmentMatch(
              index - 1,
              value.substring(index - 1, index + 1),
            );
          }
          return _AssignmentMatch(index, '=');
        }
      }
    }
    return null;
  }
}

class _AssignmentMatch {
  const _AssignmentMatch(this.index, this.operator);

  final int index;
  final String operator;
}

// ---------------------------------------------------------------------------
// Expression lexer/parser
// ---------------------------------------------------------------------------

enum _TokenKind { identifier, number, string, symbol, eof }

class _Token {
  const _Token(this.kind, this.text, this.column, [this.value]);

  final _TokenKind kind;
  final String text;
  final int column;
  final Object? value;
}

class _NumberTokenValue {
  const _NumberTokenValue(this.value, {required this.isIntegerLiteral});

  final num value;
  final bool isIntegerLiteral;
}

class _ExpressionLexer {
  _ExpressionLexer(this.source, this.line, this.baseColumn);

  final String source;
  final int line;
  final int baseColumn;
  int index = 0;

  List<_Token> scan() {
    final List<_Token> tokens = <_Token>[];
    while (index < source.length) {
      final int code = source.codeUnitAt(index);
      if (code == 0x20) {
        index += 1;
        continue;
      }
      final int column = _columnAt(index);
      if (tokens.length >= _maxPythonBlocksExpressionTokens) {
        _fail('source_too_complex', line, column);
      }
      if (_isIdentifierStart(code)) {
        final int start = index++;
        while (index < source.length &&
            _isIdentifierPart(source.codeUnitAt(index))) {
          index += 1;
        }
        tokens.add(
          _Token(_TokenKind.identifier, source.substring(start, index), column),
        );
        continue;
      }
      if (_isDigit(code) ||
          code == 0x2e &&
              index + 1 < source.length &&
              _isDigit(source.codeUnitAt(index + 1))) {
        tokens.add(_number(column));
        continue;
      }
      if (code == 0x27 || code == 0x22) {
        tokens.add(_string(code, column));
        continue;
      }
      final String pair = index + 1 < source.length
          ? source.substring(index, index + 2)
          : '';
      if (<String>{'**', '==', '!=', '<=', '>=', '//'}.contains(pair)) {
        tokens.add(_Token(_TokenKind.symbol, pair, column));
        index += 2;
        continue;
      }
      final String char = source[index];
      if ('+-*/%(),.<>[]'.contains(char)) {
        tokens.add(_Token(_TokenKind.symbol, char, column));
        index += 1;
        continue;
      }
      _fail('invalid_token', line, column);
    }
    tokens.add(_Token(_TokenKind.eof, '', _columnAt(source.length)));
    return tokens;
  }

  int _columnAt(int codeUnitIndex) =>
      baseColumn + source.substring(0, codeUnitIndex).runes.length;

  _Token _number(int column) {
    final int start = index;
    bool hasDot = false;
    bool hasExponent = false;
    if (source.codeUnitAt(index) == 0x2e) {
      hasDot = true;
      index += 1;
      while (index < source.length && _isDigit(source.codeUnitAt(index))) {
        index += 1;
      }
    } else {
      while (index < source.length && _isDigit(source.codeUnitAt(index))) {
        index += 1;
      }
      if (index < source.length && source.codeUnitAt(index) == 0x2e) {
        hasDot = true;
        index += 1;
        while (index < source.length && _isDigit(source.codeUnitAt(index))) {
          index += 1;
        }
      }
    }
    if (index < source.length &&
        (source.codeUnitAt(index) == 0x65 ||
            source.codeUnitAt(index) == 0x45)) {
      hasExponent = true;
      index += 1;
      if (index < source.length &&
          (source.codeUnitAt(index) == 0x2b ||
              source.codeUnitAt(index) == 0x2d)) {
        index += 1;
      }
      if (index >= source.length || !_isDigit(source.codeUnitAt(index))) {
        _fail('invalid_number', line, column);
      }
      while (index < source.length && _isDigit(source.codeUnitAt(index))) {
        index += 1;
      }
    }
    final String text = source.substring(start, index);
    final bool isIntegerLiteral = !hasDot && !hasExponent;
    final int textColumns = text.runes.length;
    if (isIntegerLiteral && text.length > 1 && text.codeUnitAt(0) == 0x30) {
      _fail('invalid_number', line, column, endColumn: column + textColumns);
    }
    final num? value = isIntegerLiteral
        ? int.tryParse(text)
        : double.tryParse(text);
    if (value == null || !value.isFinite) {
      _fail('invalid_number', line, column, endColumn: column + textColumns);
    }
    if (value == value.round() &&
        (value > kMaxBlocklySafeInteger || value < -kMaxBlocklySafeInteger)) {
      _fail(
        'integer_out_of_range',
        line,
        column,
        endColumn: column + textColumns,
      );
    }
    return _Token(
      _TokenKind.number,
      text,
      column,
      _NumberTokenValue(value, isIntegerLiteral: isIntegerLiteral),
    );
  }

  _Token _string(int quote, int column) {
    final int start = index;
    index += 1;
    final StringBuffer value = StringBuffer();
    while (index < source.length) {
      final int code = source.codeUnitAt(index++);
      if (code == quote) {
        return _Token(
          _TokenKind.string,
          source.substring(start, index),
          column,
          value.toString(),
        );
      }
      if (code == 0x00) {
        _fail('nul_character_not_supported', line, _columnAt(index - 1));
      }
      if (code != 0x5c) {
        value.writeCharCode(code);
        continue;
      }
      if (index >= source.length) {
        _fail('unterminated_string', line, column);
      }
      final int escaped = source.codeUnitAt(index++);
      switch (escaped) {
        case 0x61:
          value.writeCharCode(0x07);
          break;
        case 0x62:
          value.write('\b');
          break;
        case 0x66:
          value.write('\f');
          break;
        case 0x6e:
          value.write('\n');
          break;
        case 0x72:
          value.write('\r');
          break;
        case 0x74:
          value.write('\t');
          break;
        case 0x76:
          value.writeCharCode(0x0b);
          break;
        case 0x5c:
        case 0x27:
        case 0x22:
          value.writeCharCode(escaped);
          break;
        default:
          _fail('unsupported_string_escape', line, column);
      }
    }
    _fail('unterminated_string', line, column);
  }

  static bool _isDigit(int code) => code >= 0x30 && code <= 0x39;
  static bool _isIdentifierStart(int code) =>
      code == 0x5f ||
      (code >= 0x41 && code <= 0x5a) ||
      (code >= 0x61 && code <= 0x7a);
  static bool _isIdentifierPart(int code) =>
      _isIdentifierStart(code) || _isDigit(code);
}

class _ExpressionParser {
  _ExpressionParser(String source, this.line, int baseColumn, this._budget)
    : _tokens = _ExpressionLexer(source, line, baseColumn).scan();

  final int line;
  final List<_Token> _tokens;
  final _ParseBudget _budget;
  int index = 0;
  int _depth = 0;

  _Token get current => _tokens[index];

  _Expr parse() {
    final _Expr expression = _parseOr();
    if (current.kind != _TokenKind.eof) {
      _fail('invalid_syntax', line, current.column);
    }
    return expression;
  }

  List<_Expr> parseList() {
    if (current.kind == _TokenKind.eof) return <_Expr>[];
    final List<_Expr> values = <_Expr>[_parseOr()];
    while (_take(',')) {
      if (current.kind == _TokenKind.eof) {
        _fail('invalid_syntax', line, current.column);
      }
      values.add(_parseOr());
    }
    if (current.kind != _TokenKind.eof) {
      _fail('invalid_syntax', line, current.column);
    }
    return values;
  }

  _Expr _parseOr() {
    _Expr left = _parseAnd();
    while (_takeKeyword('or')) {
      final _Token operator = _tokens[index - 1];
      left = _budget.node(
        _BinaryExpr(line, operator.column, 'or', left, _parseAnd()),
      );
    }
    return left;
  }

  _Expr _parseAnd() {
    _Expr left = _parseNot();
    while (_takeKeyword('and')) {
      final _Token operator = _tokens[index - 1];
      left = _budget.node(
        _BinaryExpr(line, operator.column, 'and', left, _parseNot()),
      );
    }
    return left;
  }

  _Expr _parseNot() {
    if (_takeKeyword('not')) {
      final _Token operator = _tokens[index - 1];
      return _budget.node(
        _UnaryExpr(line, operator.column, 'not', _descend(_parseNot)),
      );
    }
    return _parseComparison();
  }

  _Expr _parseComparison() {
    _Expr left = _parseAdditive();
    if (<String>{'==', '!=', '<', '<=', '>', '>='}.contains(current.text)) {
      final _Token operator = current;
      index += 1;
      left = _budget.node(
        _BinaryExpr(
          line,
          operator.column,
          operator.text,
          left,
          _parseAdditive(),
        ),
      );
      if (<String>{'==', '!=', '<', '<=', '>', '>='}.contains(current.text)) {
        _fail('chained_comparison_not_supported', line, current.column);
      }
    }
    return left;
  }

  _Expr _parseAdditive() {
    _Expr left = _parseMultiplicative();
    while (current.text == '+' || current.text == '-') {
      final _Token operator = current;
      index += 1;
      left = _budget.node(
        _BinaryExpr(
          line,
          operator.column,
          operator.text,
          left,
          _parseMultiplicative(),
        ),
      );
    }
    return left;
  }

  _Expr _parseMultiplicative() {
    _Expr left = _parseUnary();
    while (<String>{'*', '/', '%', '//'}.contains(current.text)) {
      final _Token operator = current;
      index += 1;
      if (operator.text == '//') {
        _fail('floor_division_not_supported', line, operator.column);
      }
      left = _budget.node(
        _BinaryExpr(line, operator.column, operator.text, left, _parseUnary()),
      );
    }
    return left;
  }

  _Expr _parseUnary() {
    if (current.text == '-' || current.text == '+') {
      final _Token operator = current;
      index += 1;
      return _budget.node(
        _UnaryExpr(line, operator.column, operator.text, _descend(_parseUnary)),
      );
    }
    return _parsePower();
  }

  _Expr _parsePower() {
    _Expr left = _parsePostfix();
    if (_take('**')) {
      final _Token operator = _tokens[index - 1];
      left = _budget.node(
        _BinaryExpr(line, operator.column, '**', left, _descend(_parseUnary)),
      );
    }
    return left;
  }

  _Expr _parsePostfix() {
    _Expr expression = _parsePrimary();
    while (true) {
      if (_take('(')) {
        final List<_Expr> arguments = _arguments();
        expression = _budget.node(
          _CallExpr(line, expression.column, expression, arguments),
        );
        continue;
      }
      if (_take('.')) {
        if (current.kind != _TokenKind.identifier) {
          _fail('invalid_syntax', line, current.column);
        }
        final _Token member = current;
        index += 1;
        expression = _budget.node(
          _AttributeExpr(line, member.column, expression, member.text),
        );
        continue;
      }
      if (_take('[')) {
        final _Expr indexExpression = _descend(_parseOr);
        _expect(']');
        expression = _budget.node(
          _SubscriptExpr(line, expression.column, expression, indexExpression),
        );
        continue;
      }
      break;
    }
    return expression;
  }

  List<_Expr> _arguments() {
    if (_take(')')) return <_Expr>[];
    final List<_Expr> result = <_Expr>[_descend(_parseOr)];
    while (_take(',')) {
      if (current.text == ')') break;
      result.add(_descend(_parseOr));
    }
    _expect(')');
    return result;
  }

  _Expr _parsePrimary() {
    final _Token token = current;
    if (token.kind == _TokenKind.number) {
      index += 1;
      final _NumberTokenValue number = token.value! as _NumberTokenValue;
      return _budget.node(
        _NumberExpr(
          line,
          token.column,
          number.value,
          isIntegerLiteral: number.isIntegerLiteral,
        ),
      );
    }
    if (token.kind == _TokenKind.string) {
      index += 1;
      return _budget.node(
        _StringExpr(line, token.column, token.value! as String),
      );
    }
    if (token.kind == _TokenKind.identifier) {
      index += 1;
      switch (token.text) {
        case 'True':
          return _budget.node(_BooleanExpr(line, token.column, true));
        case 'False':
          return _budget.node(_BooleanExpr(line, token.column, false));
        case 'None':
          return _budget.node(_NoneExpr(line, token.column));
        default:
          if (_pythonKeywords.contains(token.text)) {
            _fail('invalid_identifier', line, token.column);
          }
          return _budget.node(_NameExpr(line, token.column, token.text));
      }
    }
    if (_take('(')) {
      if (_take(')')) {
        return _budget.node(_TupleExpr(line, token.column, const <_Expr>[]));
      }
      final _Expr expression = _descend(_parseOr);
      if (!_take(',')) {
        _expect(')');
        return expression;
      }
      final List<_Expr> values = <_Expr>[expression];
      while (current.text != ')') {
        values.add(_descend(_parseOr));
        if (!_take(',')) break;
      }
      _expect(')');
      return _budget.node(_TupleExpr(line, token.column, values));
    }
    _fail('invalid_syntax', line, token.column);
  }

  bool _take(String text) {
    if (current.text != text) return false;
    index += 1;
    return true;
  }

  bool _takeKeyword(String text) =>
      current.kind == _TokenKind.identifier && _take(text);

  void _expect(String text) {
    if (!_take(text)) {
      _fail('invalid_syntax', line, current.column);
    }
  }

  _Expr _descend(_Expr Function() parse) {
    _depth += 1;
    if (_depth > _maxPythonBlocksExpressionDepth) {
      _fail('expression_too_deep', line, current.column);
    }
    try {
      return parse();
    } finally {
      _depth -= 1;
    }
  }
}

// ---------------------------------------------------------------------------
// AST
// ---------------------------------------------------------------------------

class _Program {
  const _Program(this.statements);
  final List<_Stmt> statements;
}

abstract class _Node {
  const _Node(this.line, this.column);
  final int line;
  final int column;
}

abstract class _Stmt extends _Node {
  const _Stmt(super.line, super.column);
}

enum _ImportKind { pin, neoPixel, st7789, rgb565, sleepMs }

class _ImportStmt extends _Stmt {
  const _ImportStmt(super.line, super.column, this.kind);
  final _ImportKind kind;
}

class _PassStmt extends _Stmt {
  const _PassStmt(super.line, super.column);
}

class _AssignStmt extends _Stmt {
  const _AssignStmt(super.line, super.column, this.target, this.value);
  final String target;
  final _Expr value;
}

class _SubscriptAssignStmt extends _Stmt {
  const _SubscriptAssignStmt(
    super.line,
    super.column,
    this.target,
    this.index,
    this.value,
  );

  final _Expr target;
  final _Expr index;
  final _Expr value;
}

class _ChangeStmt extends _Stmt {
  const _ChangeStmt(super.line, super.column, this.target, this.value);
  final String target;
  final _Expr value;
}

class _ReturnStmt extends _Stmt {
  const _ReturnStmt(super.line, super.column, this.value);
  final _Expr value;
}

class _ExprStmt extends _Stmt {
  const _ExprStmt(super.line, super.column, this.expression);
  final _Expr expression;
}

class _IfBranch extends _Node {
  const _IfBranch(super.line, super.column, this.condition, this.body);

  final _Expr condition;
  final List<_Stmt> body;
}

class _IfStmt extends _Stmt {
  const _IfStmt(super.line, super.column, this.branches, this.otherwise);

  final List<_IfBranch> branches;
  final List<_Stmt> otherwise;
}

class _WhileStmt extends _Stmt {
  const _WhileStmt(super.line, super.column, this.condition, this.body);
  final _Expr condition;
  final List<_Stmt> body;
}

class _ForStmt extends _Stmt {
  const _ForStmt(
    super.line,
    super.column,
    this.variable,
    this.arguments,
    this.body,
  );
  final String variable;
  final List<_Expr> arguments;
  final List<_Stmt> body;
}

class _FunctionStmt extends _Stmt {
  const _FunctionStmt(
    super.line,
    super.column,
    this.name,
    this.parameters,
    this.body,
  );
  final String name;
  final List<String> parameters;
  final List<_Stmt> body;
}

abstract class _Expr extends _Node {
  const _Expr(super.line, super.column);
}

class _NumberExpr extends _Expr {
  const _NumberExpr(
    super.line,
    super.column,
    this.value, {
    required this.isIntegerLiteral,
  });

  final num value;
  final bool isIntegerLiteral;
}

class _StringExpr extends _Expr {
  const _StringExpr(super.line, super.column, this.value);
  final String value;
}

class _BooleanExpr extends _Expr {
  const _BooleanExpr(super.line, super.column, this.value);
  final bool value;
}

class _NoneExpr extends _Expr {
  const _NoneExpr(super.line, super.column);
}

class _NameExpr extends _Expr {
  const _NameExpr(super.line, super.column, this.name);
  final String name;
}

class _UnaryExpr extends _Expr {
  const _UnaryExpr(super.line, super.column, this.operator, this.value);
  final String operator;
  final _Expr value;
}

class _BinaryExpr extends _Expr {
  const _BinaryExpr(
    super.line,
    super.column,
    this.operator,
    this.left,
    this.right,
  );
  final String operator;
  final _Expr left;
  final _Expr right;
}

class _CallExpr extends _Expr {
  const _CallExpr(super.line, super.column, this.target, this.arguments);
  final _Expr target;
  final List<_Expr> arguments;
}

class _AttributeExpr extends _Expr {
  const _AttributeExpr(super.line, super.column, this.target, this.member);
  final _Expr target;
  final String member;
}

class _TupleExpr extends _Expr {
  const _TupleExpr(super.line, super.column, this.values);
  final List<_Expr> values;
}

class _SubscriptExpr extends _Expr {
  const _SubscriptExpr(super.line, super.column, this.target, this.index);
  final _Expr target;
  final _Expr index;
}

void _enforceNodeLimit(_Program program) {
  final List<_Node> pending = <_Node>[...program.statements.reversed];
  int count = 0;
  while (pending.isNotEmpty) {
    final _Node node = pending.removeLast();
    count += 1;
    if (count > kMaxPythonBlocksNodes) {
      _fail('source_too_complex', node.line, node.column);
    }
    if (node is _AssignStmt) {
      pending.add(node.value);
    } else if (node is _SubscriptAssignStmt) {
      pending.add(node.value);
      pending.add(node.index);
      pending.add(node.target);
    } else if (node is _ChangeStmt) {
      pending.add(node.value);
    } else if (node is _ReturnStmt) {
      pending.add(node.value);
    } else if (node is _ExprStmt) {
      pending.add(node.expression);
    } else if (node is _IfStmt) {
      pending.addAll(node.otherwise.reversed);
      pending.addAll(node.branches.reversed);
    } else if (node is _IfBranch) {
      pending.addAll(node.body.reversed);
      pending.add(node.condition);
    } else if (node is _WhileStmt) {
      pending.addAll(node.body.reversed);
      pending.add(node.condition);
    } else if (node is _ForStmt) {
      pending.addAll(node.body.reversed);
      pending.addAll(node.arguments.reversed);
    } else if (node is _FunctionStmt) {
      pending.addAll(node.body.reversed);
    } else if (node is _UnaryExpr) {
      pending.add(node.value);
    } else if (node is _BinaryExpr) {
      pending.add(node.right);
      pending.add(node.left);
    } else if (node is _CallExpr) {
      pending.addAll(node.arguments.reversed);
      pending.add(node.target);
    } else if (node is _AttributeExpr) {
      pending.add(node.target);
    } else if (node is _TupleExpr) {
      pending.addAll(node.values.reversed);
    } else if (node is _SubscriptExpr) {
      pending.add(node.index);
      pending.add(node.target);
    }
  }
}

// ---------------------------------------------------------------------------
// Semantic validation + ordinary Blockly serialization
// ---------------------------------------------------------------------------

List<_Stmt> _normalizedModuleStatements(List<_Stmt> statements) {
  int index = 0;
  while (index < statements.length && statements[index] is _ImportStmt) {
    index += 1;
  }
  int preambleEnd = index;
  while (preambleEnd < statements.length) {
    final _Stmt statement = statements[preambleEnd];
    if (statement is! _AssignStmt || statement.value is! _NoneExpr) break;
    preambleEnd += 1;
  }
  final Map<String, List<int>> candidates = <String, List<int>>{};
  for (int candidate = index; candidate < preambleEnd; candidate += 1) {
    final String target = (statements[candidate] as _AssignStmt).target;
    candidates.putIfAbsent(target, () => <int>[]).add(candidate);
  }
  final Set<int> removable = <int>{};
  for (final MapEntry<String, List<int>> candidate in candidates.entries) {
    if (candidate.value.length > 1 ||
        _containsBinding(statements.sublist(preambleEnd), candidate.key)) {
      // The pinned generator emits exactly one initialization per workspace
      // variable. Preserve any following explicit `name = None` statement.
      removable.add(candidate.value.first);
    }
  }
  if (removable.isEmpty) return List<_Stmt>.unmodifiable(statements);
  return List<_Stmt>.unmodifiable(<_Stmt>[
    for (int current = 0; current < statements.length; current += 1)
      if (!removable.contains(current)) statements[current],
  ]);
}

bool _containsBinding(List<_Stmt> statements, String name) {
  for (final _Stmt statement in statements) {
    if (statement is _FunctionStmt) continue;
    if (statement is _AssignStmt && statement.target == name ||
        statement is _ChangeStmt && statement.target == name ||
        statement is _ForStmt && statement.variable == name) {
      return true;
    }
    if (statement is _IfStmt) {
      for (final _IfBranch branch in statement.branches) {
        if (_containsBinding(branch.body, name)) return true;
      }
      if (_containsBinding(statement.otherwise, name)) return true;
    } else if (statement is _WhileStmt &&
        _containsBinding(statement.body, name)) {
      return true;
    } else if (statement is _ForStmt &&
        _containsBinding(statement.body, name)) {
      return true;
    }
  }
  return false;
}

class _SemanticFingerprint {
  const _SemanticFingerprint(this.statements);

  final List<_Stmt> statements;

  String encode() {
    final List<_ImportStmt> imports =
        statements.whereType<_ImportStmt>().toList()..sort(
          (_ImportStmt left, _ImportStmt right) =>
              left.kind.index.compareTo(right.kind.index),
        );
    return jsonEncode(<String, Object?>{
      'version': 1,
      'statements': <Object?>[
        for (final _ImportStmt statement in imports) _statement(statement),
        for (final _Stmt statement in statements)
          if (statement is! _ImportStmt) _statement(statement),
      ],
    });
  }

  Object? _statement(_Stmt statement) {
    if (statement is _ImportStmt) {
      return <String, Object?>{'type': 'import', 'kind': statement.kind.name};
    }
    if (statement is _PassStmt) {
      return <String, Object?>{'type': 'pass'};
    }
    if (statement is _AssignStmt) {
      return <String, Object?>{
        'type': 'assign',
        'target': statement.target,
        'value': _expression(statement.value),
      };
    }
    if (statement is _SubscriptAssignStmt) {
      return <String, Object?>{
        'type': 'subscript_assign',
        'target': _expression(statement.target),
        'index': _expression(statement.index),
        'value': _expression(statement.value),
      };
    }
    if (statement is _ChangeStmt) {
      return <String, Object?>{
        'type': 'assign',
        'target': statement.target,
        'value': <String, Object?>{
          'type': 'binary',
          'operator': '+',
          'left': <String, Object?>{'type': 'name', 'name': statement.target},
          'right': _expression(statement.value),
        },
      };
    }
    if (statement is _ReturnStmt) {
      return <String, Object?>{
        'type': 'return',
        'value': _expression(statement.value),
      };
    }
    if (statement is _ExprStmt) {
      return <String, Object?>{
        'type': 'expression',
        'value': _expression(statement.expression),
      };
    }
    if (statement is _IfStmt) {
      return <String, Object?>{
        'type': 'if',
        'branches': <Object?>[
          for (final _IfBranch branch in statement.branches)
            <String, Object?>{
              'condition': _expression(branch.condition),
              'body': _suite(branch.body),
            },
        ],
        'else': _suite(statement.otherwise),
      };
    }
    if (statement is _WhileStmt) {
      return <String, Object?>{
        'type': 'while',
        'condition': _expression(statement.condition),
        'body': _suite(statement.body),
      };
    }
    if (statement is _ForStmt) {
      final ({int start, int stop, int step}) range = _range(
        statement.arguments,
      );
      return <String, Object?>{
        'type': 'for',
        'variable': statement.variable,
        'start': range.start,
        'stop': range.stop,
        'step': range.step,
        'body': _suite(statement.body),
      };
    }
    if (statement is _FunctionStmt) {
      return <String, Object?>{
        'type': 'function',
        'name': statement.name,
        'parameters': <Object?>[...statement.parameters],
        'body': _suite(statement.body),
      };
    }
    throw StateError('Validated Python subset contains an unknown statement');
  }

  List<Object?> _suite(List<_Stmt> suite) {
    if (suite.length == 1 && suite.single is _PassStmt) {
      return const <Object?>[];
    }
    return <Object?>[
      for (final _Stmt statement in suite) _statement(statement),
    ];
  }

  Object? _expression(_Expr expression) {
    if (expression is _NumberExpr) {
      final num value = expression.value;
      return <String, Object?>{
        'type': 'number',
        'value': value == value.round() ? value.toInt() : value,
      };
    }
    if (expression is _StringExpr) {
      return <String, Object?>{'type': 'string', 'value': expression.value};
    }
    if (expression is _BooleanExpr) {
      return <String, Object?>{'type': 'boolean', 'value': expression.value};
    }
    if (expression is _NoneExpr) {
      return <String, Object?>{'type': 'none'};
    }
    if (expression is _NameExpr) {
      return <String, Object?>{'type': 'name', 'name': expression.name};
    }
    if (expression is _UnaryExpr) {
      if (expression.operator == '+') return _expression(expression.value);
      return <String, Object?>{
        'type': 'unary',
        'operator': expression.operator,
        'value': _expression(expression.value),
      };
    }
    if (expression is _BinaryExpr) {
      return <String, Object?>{
        'type': 'binary',
        'operator': expression.operator,
        'left': _expression(expression.left),
        'right': _expression(expression.right),
      };
    }
    if (expression is _AttributeExpr) {
      return <String, Object?>{
        'type': 'attribute',
        'target': _expression(expression.target),
        'member': expression.member,
      };
    }
    if (expression is _TupleExpr) {
      return <String, Object?>{
        'type': 'tuple',
        'values': <Object?>[
          for (final _Expr value in expression.values) _expression(value),
        ],
      };
    }
    if (expression is _SubscriptExpr) {
      return <String, Object?>{
        'type': 'subscript',
        'target': _expression(expression.target),
        'index': _expression(expression.index),
      };
    }
    if (expression is _CallExpr) {
      final List<_Expr> arguments = <_Expr>[...expression.arguments];
      if (expression.target is _NameExpr &&
          (expression.target as _NameExpr).name == 'Pin' &&
          arguments.length == 2) {
        arguments.add(_NoneExpr(expression.line, expression.column));
      }
      return <String, Object?>{
        'type': 'call',
        'target': _expression(expression.target),
        'arguments': <Object?>[
          for (final _Expr argument in arguments) _expression(argument),
        ],
      };
    }
    throw StateError('Validated Python subset contains an unknown expression');
  }

  ({int start, int stop, int step}) _range(List<_Expr> arguments) {
    final List<int> values = arguments
        .map((_Expr expression) => _signedInteger(expression))
        .toList(growable: false);
    if (values.length == 1) {
      return (start: 0, stop: values[0], step: 1);
    }
    return (
      start: values[0],
      stop: values[1],
      step: values.length == 3 ? values[2] : 1,
    );
  }

  int _signedInteger(_Expr expression) {
    if (expression is _NumberExpr) return expression.value.toInt();
    if (expression is _UnaryExpr) {
      final int value = _signedInteger(expression.value);
      return expression.operator == '-' ? -value : value;
    }
    throw StateError('Validated range contains a non-literal');
  }
}

class _Procedure {
  const _Procedure({
    required this.statement,
    required this.parameterIds,
    required this.returnsValue,
  });

  final _FunctionStmt statement;
  final Map<String, String> parameterIds;
  final bool returnsValue;
}

class _BuildScope {
  _BuildScope({
    required this.variables,
    required this.insideFunction,
    Set<String>? definitelyAssigned,
    Set<String>? definitelyPins,
    Set<String>? definitelyNeoPixels,
    Set<String>? definitelyTfts,
  }) : definitelyAssigned = definitelyAssigned ?? <String>{},
       definitelyPins = definitelyPins ?? <String>{},
       definitelyNeoPixels = definitelyNeoPixels ?? <String>{},
       definitelyTfts = definitelyTfts ?? <String>{};

  final Map<String, String> variables;
  final bool insideFunction;
  final Set<String> definitelyAssigned;
  final Set<String> definitelyPins;
  final Set<String> definitelyNeoPixels;
  final Set<String> definitelyTfts;

  _BuildScope fork() => _BuildScope(
    variables: variables,
    insideFunction: insideFunction,
    definitelyAssigned: <String>{...definitelyAssigned},
    definitelyPins: <String>{...definitelyPins},
    definitelyNeoPixels: <String>{...definitelyNeoPixels},
    definitelyTfts: <String>{...definitelyTfts},
  );
}

class _WorkspaceBuilder {
  _WorkspaceBuilder(
    _Program program, {
    required bool normalizeGeneratorPreamble,
  }) : statements = normalizeGeneratorPreamble
           ? _normalizedModuleStatements(program.statements)
           : List<_Stmt>.unmodifiable(program.statements);

  final List<_Stmt> statements;
  int _nextBlock = 0;
  int _nextVariable = 0;
  int _nextParameter = 0;
  final Map<String, String> _globalVariables = <String, String>{};
  final Map<String, _Procedure> _procedures = <String, _Procedure>{};

  Map<String, Object?> build() {
    _validateModuleStructure();
    _indexSymbols();
    _validateProgram();
    final List<Map<String, Object?>> topBlocks = <Map<String, Object?>>[];
    int topIndex = 0;

    for (final _Stmt statement in statements) {
      if (statement is! _FunctionStmt) continue;
      final Map<String, Object?> definition = _functionBlock(statement);
      _place(definition, topIndex++);
      topBlocks.add(definition);
    }

    final List<_Stmt> executable = statements
        .where(
          (_Stmt value) => value is! _ImportStmt && value is! _FunctionStmt,
        )
        .toList(growable: false);
    final Map<String, Object?>? first = _statementChain(
      executable,
      _BuildScope(variables: _globalVariables, insideFunction: false),
    );
    if (first != null) {
      _place(first, topIndex);
      topBlocks.add(first);
    }
    if (topBlocks.isEmpty) {
      _fail('no_convertible_statements', 1, 1);
    }

    return <String, Object?>{
      if (_globalVariables.isNotEmpty)
        'variables': <Object?>[
          for (final MapEntry<String, String> variable
              in _globalVariables.entries)
            <String, Object?>{'name': variable.key, 'id': variable.value},
        ],
      'blocks': <String, Object?>{'languageVersion': 0, 'blocks': topBlocks},
    };
  }

  void _validateModuleStructure() {
    bool sawNonImport = false;
    bool sawExecutable = false;
    final Set<_ImportKind> imports = <_ImportKind>{};
    int functions = 0;
    for (final _Stmt statement in statements) {
      if (statement is _ImportStmt) {
        if (sawNonImport) {
          _fail('imports_must_be_leading', statement.line, statement.column);
        }
        if (!imports.add(statement.kind)) {
          _fail('duplicate_import', statement.line, statement.column);
        }
        continue;
      }
      sawNonImport = true;
      if (statement is _FunctionStmt) {
        if (sawExecutable) {
          _fail(
            'function_definitions_must_be_first',
            statement.line,
            statement.column,
          );
        }
        functions += 1;
        if (functions > kMaxPythonBlocksFunctions) {
          _fail('too_many_functions', statement.line, statement.column);
        }
      } else {
        sawExecutable = true;
      }
    }
  }

  void _indexSymbols() {
    for (final _Stmt statement in statements) {
      if (statement is _FunctionStmt) {
        if (_generatorReservedNames.contains(statement.name)) {
          _fail('reserved_name', statement.line, statement.column);
        }
        if (_procedures.containsKey(statement.name)) {
          _fail('duplicate_name', statement.line, statement.column);
        }
        final Map<String, String> parameters = <String, String>{};
        for (final String parameter in statement.parameters) {
          if (_generatorReservedNames.contains(parameter)) {
            _fail('reserved_name', statement.line, statement.column);
          }
          parameters[parameter] = _parameterId();
        }
        _procedures[statement.name] = _Procedure(
          statement: statement,
          parameterIds: parameters,
          returnsValue:
              statement.body.isNotEmpty && statement.body.last is _ReturnStmt,
        );
      }
    }
    for (final _Stmt statement in statements) {
      if (statement is _FunctionStmt || statement is _ImportStmt) continue;
      _collectGlobalVariables(statement);
    }
    for (final String name in _globalVariables.keys) {
      final _Stmt statement = _firstBinding(statements, name)!;
      if (_procedures.containsKey(name)) {
        _fail('duplicate_name', statement.line, statement.column);
      }
      if (_generatorReservedNames.contains(name)) {
        _fail('reserved_name', statement.line, statement.column);
      }
    }
  }

  void _collectGlobalVariables(_Stmt statement) {
    if (statement is _AssignStmt) {
      _globalVariables.putIfAbsent(statement.target, _variableId);
    } else if (statement is _ChangeStmt) {
      _globalVariables.putIfAbsent(statement.target, _variableId);
    } else if (statement is _ForStmt) {
      _globalVariables.putIfAbsent(statement.variable, _variableId);
      for (final _Stmt child in statement.body) {
        _collectGlobalVariables(child);
      }
    } else if (statement is _IfStmt) {
      for (final _IfBranch branch in statement.branches) {
        for (final _Stmt child in branch.body) {
          _collectGlobalVariables(child);
        }
      }
      for (final _Stmt child in statement.otherwise) {
        _collectGlobalVariables(child);
      }
    } else if (statement is _WhileStmt) {
      for (final _Stmt child in statement.body) {
        _collectGlobalVariables(child);
      }
    }
  }

  _Stmt? _firstBinding(List<_Stmt> statements, String name) {
    for (final _Stmt statement in statements) {
      if (statement is _AssignStmt && statement.target == name ||
          statement is _ChangeStmt && statement.target == name ||
          statement is _ForStmt && statement.variable == name) {
        return statement;
      }
      final List<List<_Stmt>> children = <List<_Stmt>>[
        if (statement is _IfStmt)
          for (final _IfBranch branch in statement.branches) branch.body,
        if (statement is _IfStmt) statement.otherwise,
        if (statement is _WhileStmt) statement.body,
        if (statement is _ForStmt) statement.body,
      ];
      for (final List<_Stmt> suite in children) {
        final _Stmt? found = _firstBinding(suite, name);
        if (found != null) return found;
      }
    }
    return null;
  }

  void _validateProgram() {
    for (final _Procedure procedure in _procedures.values) {
      _validateFunction(procedure);
    }
    _validateSuite(
      statements
          .where(
            (_Stmt statement) =>
                statement is! _ImportStmt && statement is! _FunctionStmt,
          )
          .toList(growable: false),
      _BuildScope(variables: _globalVariables, insideFunction: false),
      moduleSuite: true,
      allowEmpty: true,
    );
    _validateImports();
    _validateNoRecursiveCalls();
  }

  void _validateFunction(_Procedure procedure) {
    final _FunctionStmt function = procedure.statement;
    final List<_Stmt> body = function.body;
    final _PassStmt? pass = body.whereType<_PassStmt>().firstOrNull;
    if (pass != null && body.length != 1) {
      _fail('pass_must_be_sole_statement', pass.line, pass.column);
    }
    if (body.whereType<_ReturnStmt>().length > 1 ||
        body.indexed.any(
          ((int, _Stmt) entry) =>
              entry.$2 is _ReturnStmt && entry.$1 != body.length - 1,
        )) {
      _fail('return_must_be_final', function.line, function.column);
    }
    final _BuildScope scope = _BuildScope(
      variables: procedure.parameterIds,
      insideFunction: true,
      definitelyAssigned: <String>{...procedure.parameterIds.keys},
    );
    final int bodyLength = procedure.returnsValue
        ? body.length - 1
        : body.length;
    _validateSuite(
      body.sublist(0, bodyLength),
      scope,
      moduleSuite: false,
      allowEmpty: procedure.returnsValue,
    );
    if (procedure.returnsValue) {
      _validateExpression((body.last as _ReturnStmt).value, scope);
    }
  }

  void _validateSuite(
    List<_Stmt> statements,
    _BuildScope scope, {
    required bool moduleSuite,
    bool allowEmpty = false,
  }) {
    if (statements.isEmpty) {
      if (!allowEmpty) {
        _fail('expected_indented_suite', 1, 1);
      }
      return;
    }
    final _PassStmt? pass = statements.whereType<_PassStmt>().firstOrNull;
    if (pass != null) {
      if (moduleSuite || statements.length != 1) {
        _fail('pass_must_be_sole_statement', pass.line, pass.column);
      }
      return;
    }
    for (final _Stmt statement in statements) {
      _validateStatement(statement, scope);
    }
  }

  void _validateStatement(_Stmt statement, _BuildScope scope) {
    if (statement is _ReturnStmt) {
      _fail('return_must_be_final', statement.line, statement.column);
    }
    if (statement is _ImportStmt) {
      _fail('imports_must_be_leading', statement.line, statement.column);
    }
    if (statement is _FunctionStmt) {
      _fail('nested_function_not_supported', statement.line, statement.column);
    }
    if (statement is _AssignStmt) {
      if (scope.insideFunction) {
        _fail(
          'function_local_assignment_not_supported',
          statement.line,
          statement.column,
        );
      }
      _validateExpression(statement.value, scope);
      scope.definitelyAssigned.add(statement.target);
      if (_isPinConstructor(statement.value)) {
        scope.definitelyPins.add(statement.target);
      } else {
        scope.definitelyPins.remove(statement.target);
      }
      if (_isNeoPixelConstructor(statement.value)) {
        scope.definitelyNeoPixels.add(statement.target);
      } else {
        scope.definitelyNeoPixels.remove(statement.target);
      }
      if (_isTftConstructor(statement.value)) {
        scope.definitelyTfts.add(statement.target);
      } else {
        scope.definitelyTfts.remove(statement.target);
      }
      return;
    }
    if (statement is _SubscriptAssignStmt) {
      if (!_isDefinitelyBoundNeoPixel(statement.target, scope)) {
        _fail(
          'invalid_neopixel_receiver',
          statement.target.line,
          statement.target.column,
        );
      }
      _validateNeoPixelIndex(statement.index, scope);
      _validateNeoPixelColor(statement.value, scope);
      return;
    }
    if (statement is _ChangeStmt) {
      if (scope.insideFunction) {
        _fail(
          'function_local_assignment_not_supported',
          statement.line,
          statement.column,
        );
      }
      if (!scope.definitelyAssigned.contains(statement.target) ||
          scope.definitelyPins.contains(statement.target) ||
          scope.definitelyNeoPixels.contains(statement.target) ||
          scope.definitelyTfts.contains(statement.target) ||
          !_isNumericExpression(statement.value)) {
        _fail('invalid_numeric_change', statement.line, statement.column);
      }
      _validateExpression(statement.value, scope);
      scope.definitelyPins.remove(statement.target);
      scope.definitelyNeoPixels.remove(statement.target);
      scope.definitelyTfts.remove(statement.target);
      return;
    }
    if (statement is _ExprStmt) {
      _validateExpressionStatement(statement, scope);
      return;
    }
    if (statement is _IfStmt) {
      final List<_BuildScope> paths = <_BuildScope>[];
      for (final _IfBranch branch in statement.branches) {
        _validateExpression(branch.condition, scope);
        final _BuildScope branchScope = scope.fork();
        _validateSuite(branch.body, branchScope, moduleSuite: false);
        paths.add(branchScope);
      }
      if (statement.otherwise.isNotEmpty) {
        final _BuildScope elseScope = scope.fork();
        _validateSuite(statement.otherwise, elseScope, moduleSuite: false);
        paths.add(elseScope);
      } else {
        paths.add(scope.fork());
      }
      _retainDefiniteIntersection(scope, paths);
      return;
    }
    if (statement is _WhileStmt) {
      final _BuildScope loopEntry = scope.fork();
      _BuildScope loopHeader = loopEntry.fork();
      // A while may execute zero or many times. Meet its entry facts with the
      // backedge until the facts guaranteed at every condition check settle.
      while (true) {
        _validateExpression(statement.condition, loopHeader);
        final _BuildScope bodyExit = loopHeader.fork();
        _validateSuite(statement.body, bodyExit, moduleSuite: false);
        final _BuildScope nextHeader = loopEntry.fork();
        _retainDefiniteIntersection(nextHeader, <_BuildScope>[
          loopEntry,
          bodyExit,
        ]);
        if (_hasSameDefiniteFacts(loopHeader, nextHeader)) {
          _replaceDefiniteFacts(scope, nextHeader);
          return;
        }
        loopHeader = nextHeader;
      }
    }
    if (statement is _ForStmt) {
      if (scope.insideFunction) {
        _fail(
          'function_local_loop_not_supported',
          statement.line,
          statement.column,
        );
      }
      final ({int start, int stop, int step}) bounds = _rangeBounds(statement);
      final _BuildScope firstHeader = scope.fork();
      _applyForLoopVariable(firstHeader, statement.variable);
      _BuildScope loopHeader = firstHeader;
      _BuildScope bodyExit = loopHeader.fork();
      _validateSuite(statement.body, bodyExit, moduleSuite: false);
      // Accepted ranges are non-empty. A one-element range has no backedge;
      // longer ranges must be safe after every preceding body execution.
      if (!_rangeHasMultipleIterations(bounds)) {
        _replaceDefiniteFacts(scope, bodyExit);
        return;
      }
      while (true) {
        final _BuildScope backedge = bodyExit.fork();
        _applyForLoopVariable(backedge, statement.variable);
        final _BuildScope nextHeader = firstHeader.fork();
        _retainDefiniteIntersection(nextHeader, <_BuildScope>[
          firstHeader,
          backedge,
        ]);
        if (_hasSameDefiniteFacts(loopHeader, nextHeader)) {
          _replaceDefiniteFacts(scope, bodyExit);
          return;
        }
        loopHeader = nextHeader;
        bodyExit = loopHeader.fork();
        _validateSuite(statement.body, bodyExit, moduleSuite: false);
      }
    }
    if (statement is _PassStmt) return;
    _fail('unsupported_statement', statement.line, statement.column);
  }

  void _applyForLoopVariable(_BuildScope scope, String variable) {
    scope.definitelyAssigned.add(variable);
    scope.definitelyPins.remove(variable);
    scope.definitelyNeoPixels.remove(variable);
    scope.definitelyTfts.remove(variable);
  }

  bool _rangeHasMultipleIterations(({int start, int stop, int step}) bounds) {
    // BigInt keeps the distance exact even when subtracting opposite safe
    // integer endpoints produces a value outside JavaScript's safe range.
    final BigInt distance = bounds.step > 0
        ? BigInt.from(bounds.stop) - BigInt.from(bounds.start)
        : BigInt.from(bounds.start) - BigInt.from(bounds.stop);
    return distance > BigInt.from(bounds.step.abs());
  }

  bool _hasSameDefiniteFacts(_BuildScope left, _BuildScope right) =>
      _setsEqual(left.definitelyAssigned, right.definitelyAssigned) &&
      _setsEqual(left.definitelyPins, right.definitelyPins) &&
      _setsEqual(left.definitelyNeoPixels, right.definitelyNeoPixels) &&
      _setsEqual(left.definitelyTfts, right.definitelyTfts);

  bool _setsEqual(Set<String> left, Set<String> right) =>
      left.length == right.length && left.containsAll(right);

  void _replaceDefiniteFacts(_BuildScope target, _BuildScope source) {
    target.definitelyAssigned
      ..clear()
      ..addAll(source.definitelyAssigned);
    target.definitelyPins
      ..clear()
      ..addAll(source.definitelyPins);
    target.definitelyNeoPixels
      ..clear()
      ..addAll(source.definitelyNeoPixels);
    target.definitelyTfts
      ..clear()
      ..addAll(source.definitelyTfts);
  }

  void _retainDefiniteIntersection(
    _BuildScope target,
    List<_BuildScope> paths,
  ) {
    final Set<String> assigned = <String>{...paths.first.definitelyAssigned};
    final Set<String> pins = <String>{...paths.first.definitelyPins};
    final Set<String> neoPixels = <String>{...paths.first.definitelyNeoPixels};
    final Set<String> tfts = <String>{...paths.first.definitelyTfts};
    for (final _BuildScope path in paths.skip(1)) {
      assigned.retainAll(path.definitelyAssigned);
      pins.retainAll(path.definitelyPins);
      neoPixels.retainAll(path.definitelyNeoPixels);
      tfts.retainAll(path.definitelyTfts);
    }
    target.definitelyAssigned
      ..clear()
      ..addAll(assigned);
    target.definitelyPins
      ..clear()
      ..addAll(pins);
    target.definitelyNeoPixels
      ..clear()
      ..addAll(neoPixels);
    target.definitelyTfts
      ..clear()
      ..addAll(tfts);
  }

  void _validateExpressionStatement(_ExprStmt statement, _BuildScope scope) {
    final _Expr expression = statement.expression;
    if (expression is! _CallExpr) {
      _fail(
        'unsupported_expression_statement',
        expression.line,
        expression.column,
      );
    }
    if (expression.target case final _NameExpr target) {
      if (target.name == 'print') {
        if (expression.arguments.length != 1) {
          _fail('invalid_print', expression.line, expression.column);
        }
        _validateExpression(expression.arguments.single, scope);
        return;
      }
      if (target.name == 'sleep_ms') {
        if (expression.arguments.length != 1) {
          _fail('invalid_sleep', expression.line, expression.column);
        }
        final int? value = _integerLiteral(
          expression.arguments.single,
          requireIntegerSyntax: true,
        );
        if (value == null || value < 0) {
          _fail('invalid_sleep', expression.line, expression.column);
        }
        return;
      }
      final _Procedure? procedure = _procedures[target.name];
      if (procedure == null) {
        _fail('unsupported_call', expression.line, expression.column);
      }
      if (procedure.returnsValue) {
        _fail(
          'function_call_kind_mismatch',
          expression.line,
          expression.column,
        );
      }
      _validateCallArguments(expression, procedure, scope);
      return;
    }
    if (expression.target case final _AttributeExpr attribute) {
      if (attribute.member == 'value') {
        if (expression.arguments.length != 1 ||
            !_isDefinitelyBoundPin(attribute.target, scope)) {
          _fail('unsupported_call', expression.line, expression.column);
        }
        final int? level = _integerLiteral(
          expression.arguments.single,
          requireIntegerSyntax: true,
        );
        if (level != 0 && level != 1) {
          _fail('invalid_gpio', expression.line, expression.column);
        }
        return;
      }
      if (_isDefinitelyBoundTft(attribute.target, scope)) {
        _validateTftMethodCall(expression, attribute.member, scope);
        return;
      }
      if (!_isDefinitelyBoundNeoPixel(attribute.target, scope)) {
        _fail(
          'invalid_neopixel_receiver',
          attribute.target.line,
          attribute.target.column,
        );
      }
      if (attribute.member == 'fill') {
        if (expression.arguments.length != 1) {
          _fail('invalid_neopixel_fill', expression.line, expression.column);
        }
        _validateNeoPixelColor(expression.arguments.single, scope);
        return;
      }
      if (attribute.member == 'write') {
        if (expression.arguments.isNotEmpty) {
          _fail('invalid_neopixel_write', expression.line, expression.column);
        }
        return;
      }
      _fail('unsupported_call', expression.line, expression.column);
    }
    _fail('unsupported_call', expression.line, expression.column);
  }

  void _validateExpression(_Expr expression, _BuildScope scope) {
    if (expression is _NumberExpr) {
      _validateNumber(expression);
      return;
    }
    if (expression is _StringExpr ||
        expression is _BooleanExpr ||
        expression is _NoneExpr) {
      return;
    }
    if (expression is _NameExpr) {
      if (!scope.variables.containsKey(expression.name) ||
          !scope.definitelyAssigned.contains(expression.name)) {
        _fail('unknown_variable', expression.line, expression.column);
      }
      return;
    }
    if (expression is _UnaryExpr) {
      _validateExpression(expression.value, scope);
      return;
    }
    if (expression is _BinaryExpr) {
      _validateExpression(expression.left, scope);
      _validateExpression(expression.right, scope);
      return;
    }
    if (expression is _TupleExpr) {
      _fail('unsupported_tuple', expression.line, expression.column);
    }
    if (expression is _SubscriptExpr) {
      _fail('unsupported_subscript', expression.line, expression.column);
    }
    if (expression is _CallExpr) {
      if (expression.target case final _NameExpr target) {
        if (target.name == 'Pin') {
          _validatePinCall(expression);
          return;
        }
        if (target.name == 'NeoPixel') {
          _validateNeoPixelCall(expression);
          return;
        }
        if (target.name == 'ST7789') {
          _validateTftConstructorCall(expression, scope);
          return;
        }
        if (target.name == 'rgb565') {
          _validateTftColorCall(expression, scope);
          return;
        }
        final _Procedure? procedure = _procedures[target.name];
        if (procedure == null) {
          _fail('unsupported_call', expression.line, expression.column);
        }
        if (!procedure.returnsValue) {
          _fail(
            'function_call_kind_mismatch',
            expression.line,
            expression.column,
          );
        }
        _validateCallArguments(expression, procedure, scope);
        return;
      }
      if (expression.target case final _AttributeExpr attribute) {
        if (attribute.member != 'value' ||
            expression.arguments.isNotEmpty ||
            !_isDefinitelyBoundPin(attribute.target, scope)) {
          _fail('unsupported_call', expression.line, expression.column);
        }
        return;
      }
      _fail('unsupported_call', expression.line, expression.column);
    }
    if (expression is _AttributeExpr) {
      _fail('unsupported_attribute', expression.line, expression.column);
    }
    _fail('unsupported_expression', expression.line, expression.column);
  }

  void _validateCallArguments(
    _CallExpr expression,
    _Procedure procedure,
    _BuildScope scope,
  ) {
    if (expression.arguments.length != procedure.statement.parameters.length) {
      _fail('invalid_function_call', expression.line, expression.column);
    }
    for (final _Expr argument in expression.arguments) {
      _validateExpression(argument, scope);
    }
  }

  void _validateNumber(_NumberExpr expression) {
    if (!expression.value.isFinite) {
      _fail('invalid_number', expression.line, expression.column);
    }
    if (!expression.isIntegerLiteral &&
        expression.value == expression.value.round()) {
      _fail('integral_float_not_preserved', expression.line, expression.column);
    }
    if (expression.value == expression.value.round() &&
        (expression.value > kMaxBlocklySafeInteger ||
            expression.value < -kMaxBlocklySafeInteger)) {
      _fail('integer_out_of_range', expression.line, expression.column);
    }
  }

  bool _isNumericExpression(_Expr expression) {
    if (expression is _NumberExpr || expression is _NameExpr) return true;
    if (expression is _UnaryExpr) {
      return expression.operator != 'not' &&
          _isNumericExpression(expression.value);
    }
    if (expression is _BinaryExpr) {
      return <String>{
            '+',
            '-',
            '*',
            '/',
            '%',
            '**',
          }.contains(expression.operator) &&
          _isNumericExpression(expression.left) &&
          _isNumericExpression(expression.right);
    }
    if (expression is _CallExpr) {
      if (expression.target case final _AttributeExpr attribute) {
        return attribute.member == 'value' && expression.arguments.isEmpty;
      }
      if (expression.target case final _NameExpr target) {
        if (target.name == 'rgb565') return true;
        return _procedures[target.name]?.returnsValue ?? false;
      }
    }
    return false;
  }

  void _validatePinCall(_CallExpr expression) {
    if (expression.arguments.length < 2 || expression.arguments.length > 3) {
      _fail('invalid_gpio', expression.line, expression.column);
    }
    if (_pinIdentity(expression.arguments[0]) == null) {
      _fail('invalid_gpio', expression.line, expression.column);
    }
    final String? mode = _pinConstant(expression.arguments[1]);
    if (mode != 'IN' && mode != 'OUT') {
      _fail('invalid_gpio', expression.line, expression.column);
    }
    if (expression.arguments.length == 3) {
      final _Expr pull = expression.arguments[2];
      if (pull is! _NoneExpr &&
          !<String>{'PULL_UP', 'PULL_DOWN'}.contains(_pinConstant(pull))) {
        _fail('invalid_gpio', pull.line, pull.column);
      }
    }
  }

  void _validateNeoPixelCall(_CallExpr expression) {
    if (expression.arguments.length != 2) {
      _fail('invalid_neopixel', expression.line, expression.column);
    }
    final _Expr pin = expression.arguments[0];
    if (pin is! _CallExpr ||
        pin.target is! _NameExpr ||
        (pin.target as _NameExpr).name != 'Pin') {
      _fail('invalid_neopixel', pin.line, pin.column);
    }
    _validatePinCall(pin);
    final int? pixels = _integerLiteral(
      expression.arguments[1],
      requireIntegerSyntax: true,
    );
    if (pixels == null || pixels <= 0) {
      _fail(
        'invalid_neopixel',
        expression.arguments[1].line,
        expression.arguments[1].column,
      );
    }
  }

  void _validateNeoPixelColor(_Expr expression, _BuildScope scope) {
    if (expression is! _TupleExpr || expression.values.length != 3) {
      _fail('invalid_neopixel_color', expression.line, expression.column);
    }
    for (final _Expr channel in expression.values) {
      _validateExpression(channel, scope);
      if (!_isNumericExpression(channel)) {
        _fail('invalid_neopixel_color', channel.line, channel.column);
      }
    }
  }

  void _validateTftConstructorCall(_CallExpr expression, _BuildScope scope) {
    if (expression.arguments.length != 16) {
      _fail('invalid_tft_constructor', expression.line, expression.column);
    }

    final List<int> literalIndexes = <int>[0, 1, 2, 3, 10, 11, 12, 13];
    final List<int> values = <int>[];
    for (final int index in literalIndexes) {
      final _Expr argument = expression.arguments[index];
      final int? value = _integerLiteral(argument, requireIntegerSyntax: true);
      if (value == null) {
        _fail('invalid_tft_constructor', argument.line, argument.column);
      }
      values.add(value);
    }
    final int spiId = values[0];
    final int baudrate = values[1];
    final int polarity = values[2];
    final int phase = values[3];
    final int width = values[4];
    final int height = values[5];
    final int xOffset = values[6];
    final int yOffset = values[7];
    if (spiId < 0 ||
        baudrate <= 0 ||
        (polarity != 0 && polarity != 1) ||
        (phase != 0 && phase != 1) ||
        width <= 0 ||
        height <= 0 ||
        xOffset < 0 ||
        yOffset < 0) {
      _fail('invalid_tft_constructor', expression.line, expression.column);
    }

    for (int index = 4; index <= 9; index += 1) {
      final _Expr pin = expression.arguments[index];
      if (pin is! _CallExpr ||
          pin.target is! _NameExpr ||
          (pin.target as _NameExpr).name != 'Pin') {
        _fail('invalid_tft_pin', pin.line, pin.column);
      }
      _validatePinCall(pin);
    }

    for (final int index in <int>[14, 15]) {
      final _Expr flag = expression.arguments[index];
      _validateExpression(flag, scope);
      if (!_isBooleanExpression(flag, scope)) {
        _fail('invalid_tft_boolean', flag.line, flag.column);
      }
    }
  }

  void _validateTftColorCall(_CallExpr expression, _BuildScope scope) {
    if (expression.arguments.length != 3) {
      _fail('invalid_tft_color', expression.line, expression.column);
    }
    for (final _Expr channel in expression.arguments) {
      _validateExpression(channel, scope);
      if (!_isNumericExpression(channel)) {
        _fail('invalid_tft_color', channel.line, channel.column);
      }
    }
  }

  void _validateTftColor(_Expr expression, _BuildScope scope) {
    if (expression is! _CallExpr ||
        expression.target is! _NameExpr ||
        (expression.target as _NameExpr).name != 'rgb565') {
      _fail('invalid_tft_color', expression.line, expression.column);
    }
    _validateTftColorCall(expression, scope);
  }

  void _validateTftMethodCall(
    _CallExpr expression,
    String member,
    _BuildScope scope,
  ) {
    final List<_Expr> arguments = expression.arguments;
    if (member == 'fill') {
      if (arguments.length != 1) {
        _fail('invalid_tft_fill', expression.line, expression.column);
      }
      _validateTftColor(arguments[0], scope);
      return;
    }
    if (member == 'pixel') {
      if (arguments.length != 3) {
        _fail('invalid_tft_pixel', expression.line, expression.column);
      }
      _validateNumericTftArguments(arguments.take(2), scope);
      _validateTftColor(arguments[2], scope);
      return;
    }
    if (member == 'rect' || member == 'fill_rect') {
      if (arguments.length != 5) {
        _fail('invalid_tft_rect', expression.line, expression.column);
      }
      _validateNumericTftArguments(arguments.take(4), scope);
      _validateTftColor(arguments[4], scope);
      return;
    }
    if (member == 'text') {
      if (arguments.length != 4) {
        _fail('invalid_tft_text', expression.line, expression.column);
      }
      _validateExpression(arguments[0], scope);
      if (!_isTextExpression(arguments[0], scope)) {
        _fail('invalid_tft_text', arguments[0].line, arguments[0].column);
      }
      _validateNumericTftArguments(arguments.skip(1).take(2), scope);
      _validateTftColor(arguments[3], scope);
      return;
    }
    if (member == 'show') {
      if (arguments.isNotEmpty) {
        _fail('invalid_tft_show', expression.line, expression.column);
      }
      return;
    }
    if (member == 'backlight') {
      if (arguments.length != 1) {
        _fail('invalid_tft_backlight', expression.line, expression.column);
      }
      _validateExpression(arguments[0], scope);
      if (!_isBooleanExpression(arguments[0], scope)) {
        _fail('invalid_tft_backlight', arguments[0].line, arguments[0].column);
      }
      return;
    }
    _fail('unsupported_call', expression.line, expression.column);
  }

  void _validateNumericTftArguments(
    Iterable<_Expr> arguments,
    _BuildScope scope,
  ) {
    for (final _Expr argument in arguments) {
      _validateExpression(argument, scope);
      if (!_isNumericExpression(argument)) {
        _fail('invalid_tft_numeric', argument.line, argument.column);
      }
    }
  }

  bool _isBooleanExpression(_Expr expression, _BuildScope scope) {
    if (expression is _BooleanExpr) return true;
    if (expression is _NameExpr) {
      return scope.variables.containsKey(expression.name) &&
          scope.definitelyAssigned.contains(expression.name);
    }
    if (expression is _UnaryExpr) return expression.operator == 'not';
    if (expression is _BinaryExpr) {
      return <String>{
        'and',
        'or',
        '==',
        '!=',
        '<',
        '<=',
        '>',
        '>=',
      }.contains(expression.operator);
    }
    if (expression is _CallExpr && expression.target is _NameExpr) {
      return _procedures[(expression.target as _NameExpr).name]?.returnsValue ??
          false;
    }
    return false;
  }

  bool _isTextExpression(_Expr expression, _BuildScope scope) {
    if (expression is _StringExpr) return true;
    if (expression is _NameExpr) {
      return scope.variables.containsKey(expression.name) &&
          scope.definitelyAssigned.contains(expression.name);
    }
    if (expression is _CallExpr && expression.target is _NameExpr) {
      return _procedures[(expression.target as _NameExpr).name]?.returnsValue ??
          false;
    }
    return false;
  }

  void _validateNeoPixelIndex(_Expr expression, _BuildScope scope) {
    _validateExpression(expression, scope);
    if (!_isNumericExpression(expression)) {
      _fail('invalid_neopixel_index', expression.line, expression.column);
    }
  }

  bool _isDefinitelyBoundPin(_Expr expression, _BuildScope scope) =>
      expression is _NameExpr &&
      !scope.insideFunction &&
      scope.variables.containsKey(expression.name) &&
      scope.definitelyAssigned.contains(expression.name) &&
      scope.definitelyPins.contains(expression.name);

  bool _isBoundPinName(_Expr expression, _BuildScope scope) =>
      expression is _NameExpr &&
      !scope.insideFunction &&
      scope.variables.containsKey(expression.name);

  bool _isDefinitelyBoundNeoPixel(_Expr expression, _BuildScope scope) =>
      expression is _NameExpr &&
      !scope.insideFunction &&
      scope.variables.containsKey(expression.name) &&
      scope.definitelyAssigned.contains(expression.name) &&
      scope.definitelyNeoPixels.contains(expression.name);

  bool _isDefinitelyBoundTft(_Expr expression, _BuildScope scope) =>
      expression is _NameExpr &&
      !scope.insideFunction &&
      scope.variables.containsKey(expression.name) &&
      scope.definitelyAssigned.contains(expression.name) &&
      scope.definitelyTfts.contains(expression.name);

  bool _isBoundNeoPixelName(_Expr expression, _BuildScope scope) =>
      expression is _NameExpr &&
      !scope.insideFunction &&
      scope.variables.containsKey(expression.name);

  bool _isBoundTftName(_Expr expression, _BuildScope scope) =>
      expression is _NameExpr &&
      !scope.insideFunction &&
      scope.variables.containsKey(expression.name);

  bool _isPinConstructor(_Expr expression) =>
      expression is _CallExpr &&
      expression.target is _NameExpr &&
      (expression.target as _NameExpr).name == 'Pin';

  bool _isNeoPixelConstructor(_Expr expression) =>
      expression is _CallExpr &&
      expression.target is _NameExpr &&
      (expression.target as _NameExpr).name == 'NeoPixel';

  bool _isTftConstructor(_Expr expression) =>
      expression is _CallExpr &&
      expression.target is _NameExpr &&
      (expression.target as _NameExpr).name == 'ST7789';

  void _validateImports() {
    final Set<_ImportKind> actual = statements
        .whereType<_ImportStmt>()
        .map((_ImportStmt value) => value.kind)
        .toSet();
    bool usesPin = false;
    bool usesNeoPixel = false;
    bool usesSt7789 = false;
    bool usesRgb565 = false;
    bool usesSleep = false;
    for (final _Node node in _allNodes(statements)) {
      if (node is _CallExpr && node.target is _NameExpr) {
        final String name = (node.target as _NameExpr).name;
        usesPin |= name == 'Pin';
        usesNeoPixel |= name == 'NeoPixel';
        usesSt7789 |= name == 'ST7789';
        usesRgb565 |= name == 'rgb565';
        usesSleep |= name == 'sleep_ms';
      }
    }
    _requireImport(
      _ImportKind.pin,
      used: usesPin,
      present: actual.contains(_ImportKind.pin),
    );
    _requireImport(
      _ImportKind.neoPixel,
      used: usesNeoPixel,
      present: actual.contains(_ImportKind.neoPixel),
    );
    _requireImport(
      _ImportKind.st7789,
      used: usesSt7789,
      present: actual.contains(_ImportKind.st7789),
    );
    _requireImport(
      _ImportKind.rgb565,
      used: usesRgb565,
      present: actual.contains(_ImportKind.rgb565),
    );
    _requireImport(
      _ImportKind.sleepMs,
      used: usesSleep,
      present: actual.contains(_ImportKind.sleepMs),
    );
  }

  void _requireImport(
    _ImportKind kind, {
    required bool used,
    required bool present,
  }) {
    if (used == present) return;
    final _ImportStmt? statement = statements
        .whereType<_ImportStmt>()
        .where((_ImportStmt value) => value.kind == kind)
        .firstOrNull;
    final _Node location =
        statement ??
        _allNodes(statements).firstWhere(
          (_Node node) =>
              node is _CallExpr &&
              node.target is _NameExpr &&
              (node.target as _NameExpr).name == _importName(kind),
        );
    _fail(
      used ? 'missing_required_import' : 'unused_import',
      location.line,
      location.column,
    );
  }

  String _importName(_ImportKind kind) => switch (kind) {
    _ImportKind.pin => 'Pin',
    _ImportKind.neoPixel => 'NeoPixel',
    _ImportKind.st7789 => 'ST7789',
    _ImportKind.rgb565 => 'rgb565',
    _ImportKind.sleepMs => 'sleep_ms',
  };

  Iterable<_Node> _allNodes(List<_Stmt> statements) sync* {
    final List<_Node> pending = <_Node>[...statements.reversed];
    while (pending.isNotEmpty) {
      final _Node node = pending.removeLast();
      yield node;
      if (node is _AssignStmt) {
        pending.add(node.value);
      } else if (node is _SubscriptAssignStmt) {
        pending.add(node.value);
        pending.add(node.index);
        pending.add(node.target);
      } else if (node is _ChangeStmt) {
        pending.add(node.value);
      } else if (node is _ReturnStmt) {
        pending.add(node.value);
      } else if (node is _ExprStmt) {
        pending.add(node.expression);
      } else if (node is _IfStmt) {
        pending.addAll(node.otherwise.reversed);
        pending.addAll(node.branches.reversed);
      } else if (node is _IfBranch) {
        pending.addAll(node.body.reversed);
        pending.add(node.condition);
      } else if (node is _WhileStmt) {
        pending.addAll(node.body.reversed);
        pending.add(node.condition);
      } else if (node is _ForStmt) {
        pending.addAll(node.body.reversed);
        pending.addAll(node.arguments.reversed);
      } else if (node is _FunctionStmt) {
        pending.addAll(node.body.reversed);
      } else if (node is _UnaryExpr) {
        pending.add(node.value);
      } else if (node is _BinaryExpr) {
        pending.add(node.right);
        pending.add(node.left);
      } else if (node is _CallExpr) {
        pending.addAll(node.arguments.reversed);
        pending.add(node.target);
      } else if (node is _AttributeExpr) {
        pending.add(node.target);
      } else if (node is _TupleExpr) {
        pending.addAll(node.values.reversed);
      } else if (node is _SubscriptExpr) {
        pending.add(node.index);
        pending.add(node.target);
      }
    }
  }

  void _validateNoRecursiveCalls() {
    final Map<String, Set<String>> graph = <String, Set<String>>{
      for (final String name in _procedures.keys) name: <String>{},
    };
    for (final MapEntry<String, _Procedure> entry in _procedures.entries) {
      for (final _Node node in _allNodes(entry.value.statement.body)) {
        if (node is _CallExpr && node.target is _NameExpr) {
          final String called = (node.target as _NameExpr).name;
          if (_procedures.containsKey(called)) {
            graph[entry.key]!.add(called);
          }
        }
      }
    }
    final Map<String, int> state = <String, int>{};

    void visit(String name) {
      if (state[name] == 1) {
        final _FunctionStmt function = _procedures[name]!.statement;
        _fail('recursive_function', function.line, function.column);
      }
      if (state[name] == 2) return;
      state[name] = 1;
      for (final String called in graph[name]!) {
        visit(called);
      }
      state[name] = 2;
    }

    for (final String name in graph.keys) {
      visit(name);
    }
  }

  String _variableId() =>
      'py-import-v${(++_nextVariable).toString().padLeft(4, '0')}';
  String _parameterId() =>
      'py-import-p${(++_nextParameter).toString().padLeft(4, '0')}';
  String _blockId() =>
      'py-import-b${(++_nextBlock).toString().padLeft(4, '0')}';

  void _place(Map<String, Object?> block, int index) {
    block['x'] = 48;
    block['y'] = 48 + index * 192;
  }

  Map<String, Object?> _block(
    String type, {
    Map<String, Object?>? fields,
    Map<String, Object?>? inputs,
    Map<String, Object?>? extraState,
  }) => <String, Object?>{
    'type': type,
    'id': _blockId(),
    if (fields != null && fields.isNotEmpty) 'fields': fields,
    if (extraState != null && extraState.isNotEmpty) 'extraState': extraState,
    if (inputs != null && inputs.isNotEmpty) 'inputs': inputs,
  };

  Map<String, Object?> _input(Map<String, Object?> block) => <String, Object?>{
    'block': block,
  };

  Map<String, Object?>? _statementChain(
    List<_Stmt> statements,
    _BuildScope scope,
  ) {
    Map<String, Object?>? first;
    Map<String, Object?>? previous;
    for (final _Stmt statement in statements) {
      final Map<String, Object?>? current = _statementBlock(statement, scope);
      if (current == null) continue;
      first ??= current;
      if (previous != null) {
        previous['next'] = _input(current);
      }
      previous = current;
    }
    return first;
  }

  Map<String, Object?>? _statementBlock(_Stmt statement, _BuildScope scope) {
    if (statement is _PassStmt || statement is _ImportStmt) return null;
    if (statement is _FunctionStmt) {
      _fail('nested_function_not_supported', statement.line, statement.column);
    }
    if (statement is _AssignStmt) {
      if (scope.insideFunction) {
        _fail(
          'function_local_assignment_not_supported',
          statement.line,
          statement.column,
        );
      }
      final String? variableId = scope.variables[statement.target];
      if (variableId == null) {
        _fail('unknown_variable', statement.line, statement.column);
      }
      return _block(
        'variables_set',
        fields: <String, Object?>{
          'VAR': <String, Object?>{'id': variableId},
        },
        inputs: <String, Object?>{
          'VALUE': _input(_expressionBlock(statement.value, scope)),
        },
      );
    }
    if (statement is _SubscriptAssignStmt) {
      if (!_isBoundNeoPixelName(statement.target, scope)) {
        _fail(
          'invalid_neopixel_receiver',
          statement.target.line,
          statement.target.column,
        );
      }
      return _block(
        'pyble_neopixel_set_pixel',
        inputs: <String, Object?>{
          'STRIP': _input(_expressionBlock(statement.target, scope)),
          'INDEX': _input(_expressionBlock(statement.index, scope)),
          'COLOR': _input(_neoPixelColorBlock(statement.value, scope)),
        },
      );
    }
    if (statement is _ChangeStmt) {
      final String variableId = scope.variables[statement.target]!;
      return _block(
        'variables_set',
        fields: <String, Object?>{
          'VAR': <String, Object?>{'id': variableId},
        },
        inputs: <String, Object?>{
          'VALUE': _input(
            _block(
              'math_arithmetic',
              fields: <String, Object?>{'OP': 'ADD'},
              inputs: <String, Object?>{
                'A': _input(
                  _block(
                    'variables_get',
                    fields: <String, Object?>{
                      'VAR': <String, Object?>{'id': variableId},
                    },
                  ),
                ),
                'B': _input(_expressionBlock(statement.value, scope)),
              },
            ),
          ),
        },
      );
    }
    if (statement is _ReturnStmt) {
      _fail('return_must_be_final', statement.line, statement.column);
    }
    if (statement is _ExprStmt) {
      return _expressionStatementBlock(statement, scope);
    }
    if (statement is _IfStmt) {
      final Map<String, Object?> inputs = <String, Object?>{};
      for (int index = 0; index < statement.branches.length; index += 1) {
        final _IfBranch branch = statement.branches[index];
        inputs['IF$index'] = _input(_expressionBlock(branch.condition, scope));
        final Map<String, Object?>? body = _statementChain(branch.body, scope);
        if (body != null) inputs['DO$index'] = _input(body);
      }
      final Map<String, Object?>? otherwise = _statementChain(
        statement.otherwise,
        scope,
      );
      if (otherwise != null) inputs['ELSE'] = _input(otherwise);
      return _block(
        'controls_if',
        extraState:
            statement.branches.length == 1 && statement.otherwise.isEmpty
            ? null
            : <String, Object?>{
                if (statement.branches.length > 1)
                  'elseIfCount': statement.branches.length - 1,
                if (statement.otherwise.isNotEmpty) 'hasElse': true,
              },
        inputs: inputs,
      );
    }
    if (statement is _WhileStmt) {
      final Map<String, Object?> inputs = <String, Object?>{
        'BOOL': _input(_expressionBlock(statement.condition, scope)),
      };
      final Map<String, Object?>? body = _statementChain(statement.body, scope);
      if (body != null) inputs['DO'] = _input(body);
      return _block(
        'controls_whileUntil',
        fields: <String, Object?>{'MODE': 'WHILE'},
        inputs: inputs,
      );
    }
    if (statement is _ForStmt) {
      if (scope.insideFunction) {
        _fail(
          'function_local_loop_not_supported',
          statement.line,
          statement.column,
        );
      }
      final ({int start, int stop, int step}) bounds = _rangeBounds(statement);
      final String? variableId = scope.variables[statement.variable];
      if (variableId == null) {
        _fail('unknown_variable', statement.line, statement.column);
      }
      final Map<String, Object?> inputs = <String, Object?>{
        'FROM': _input(_numberBlock(bounds.start)),
        'TO': _input(
          _numberBlock(bounds.step > 0 ? bounds.stop - 1 : bounds.stop + 1),
        ),
        'BY': _input(_numberBlock(bounds.step.abs())),
      };
      final Map<String, Object?>? body = _statementChain(statement.body, scope);
      if (body != null) inputs['DO'] = _input(body);
      return _block(
        'controls_for',
        fields: <String, Object?>{
          'VAR': <String, Object?>{'id': variableId},
        },
        inputs: inputs,
      );
    }
    _fail('unsupported_statement', statement.line, statement.column);
  }

  ({int start, int stop, int step}) _rangeBounds(_ForStmt statement) {
    if (statement.arguments.isEmpty || statement.arguments.length > 3) {
      _fail('invalid_range', statement.line, statement.column);
    }
    final List<int> values = statement.arguments.map((_Expr expression) {
      final int? value = _integerLiteral(
        expression,
        requireIntegerSyntax: true,
      );
      if (value == null) {
        _fail('invalid_range', expression.line, expression.column);
      }
      return value;
    }).toList();
    final int start;
    final int stop;
    final int step;
    if (values.length == 1) {
      start = 0;
      stop = values[0];
      step = 1;
    } else {
      start = values[0];
      stop = values[1];
      step = values.length == 3 ? values[2] : 1;
    }
    if (step == 0 || step > 0 && start >= stop || step < 0 && start <= stop) {
      _fail('invalid_range', statement.line, statement.column);
    }
    final int inclusiveStop = step > 0 ? stop - 1 : stop + 1;
    if (!_isSafeInteger(start) ||
        !_isSafeInteger(stop) ||
        !_isSafeInteger(step) ||
        !_isSafeInteger(inclusiveStop)) {
      _fail('invalid_range', statement.line, statement.column);
    }
    return (start: start, stop: stop, step: step);
  }

  Map<String, Object?> _expressionStatementBlock(
    _ExprStmt statement,
    _BuildScope scope,
  ) {
    final _Expr expression = statement.expression;
    if (expression is! _CallExpr) {
      _fail(
        'unsupported_expression_statement',
        expression.line,
        expression.column,
      );
    }
    if (expression.target is _NameExpr) {
      final String name = (expression.target as _NameExpr).name;
      if (name == 'print') {
        if (expression.arguments.length != 1) {
          _fail('invalid_print', expression.line, expression.column);
        }
        return _block(
          'text_print',
          inputs: <String, Object?>{
            'TEXT': _input(
              _expressionBlock(expression.arguments.single, scope),
            ),
          },
        );
      }
      if (name == 'sleep_ms') {
        if (expression.arguments.length != 1) {
          _fail('invalid_sleep', expression.line, expression.column);
        }
        final int? duration = _integerLiteral(
          expression.arguments.single,
          requireIntegerSyntax: true,
        );
        if (duration == null || duration < 0) {
          _fail('invalid_sleep', expression.line, expression.column);
        }
        return _block(
          'pyble_time_sleep_ms',
          inputs: <String, Object?>{
            'MILLISECONDS': _input(_numberBlock(duration)),
          },
        );
      }
      final _Procedure? procedure = _procedures[name];
      if (procedure == null) {
        _fail('unsupported_call', expression.line, expression.column);
      }
      if (expression.arguments.length !=
          procedure.statement.parameters.length) {
        _fail('invalid_function_call', expression.line, expression.column);
      }
      if (procedure.returnsValue) {
        _fail(
          'function_call_kind_mismatch',
          expression.line,
          expression.column,
        );
      }
      return _block(
        'procedures_callnoreturn',
        extraState: <String, Object?>{
          'name': name,
          'params': <Object?>[...procedure.statement.parameters],
        },
        inputs: <String, Object?>{
          for (int index = 0; index < expression.arguments.length; index += 1)
            'ARG$index': _input(
              _expressionBlock(expression.arguments[index], scope),
            ),
        },
      );
    }
    if (expression.target is _AttributeExpr) {
      final _AttributeExpr attribute = expression.target as _AttributeExpr;
      if (attribute.member == 'value') {
        if (expression.arguments.length != 1 ||
            !_isBoundPinName(attribute.target, scope)) {
          _fail('unsupported_call', expression.line, expression.column);
        }
        final int? level = _integerLiteral(
          expression.arguments.single,
          requireIntegerSyntax: true,
        );
        if (level != 0 && level != 1) {
          _fail('invalid_gpio', expression.line, expression.column);
        }
        return _block(
          'pyble_gpio_write',
          fields: <String, Object?>{'LEVEL': level == 0 ? 'LOW' : 'HIGH'},
          inputs: <String, Object?>{
            'PIN': _input(_expressionBlock(attribute.target, scope)),
          },
        );
      }
      if (<String>{
            'pixel',
            'rect',
            'fill_rect',
            'text',
            'show',
            'backlight',
          }.contains(attribute.member) ||
          attribute.member == 'fill' &&
              expression.arguments.length == 1 &&
              _isTftColorCall(expression.arguments.single)) {
        if (!_isBoundTftName(attribute.target, scope)) {
          _fail(
            'invalid_tft_receiver',
            attribute.target.line,
            attribute.target.column,
          );
        }
        return _tftStatementBlock(expression, attribute, scope);
      }
      if (!_isBoundNeoPixelName(attribute.target, scope)) {
        _fail(
          'invalid_neopixel_receiver',
          attribute.target.line,
          attribute.target.column,
        );
      }
      if (attribute.member == 'fill' && expression.arguments.length == 1) {
        return _block(
          'pyble_neopixel_fill',
          inputs: <String, Object?>{
            'STRIP': _input(_expressionBlock(attribute.target, scope)),
            'COLOR': _input(
              _neoPixelColorBlock(expression.arguments.single, scope),
            ),
          },
        );
      }
      if (attribute.member == 'write' && expression.arguments.isEmpty) {
        return _block(
          'pyble_neopixel_write',
          inputs: <String, Object?>{
            'STRIP': _input(_expressionBlock(attribute.target, scope)),
          },
        );
      }
      _fail('unsupported_call', expression.line, expression.column);
    }
    _fail('unsupported_call', expression.line, expression.column);
  }

  Map<String, Object?> _functionBlock(_FunctionStmt statement) {
    final _Procedure procedure = _procedures[statement.name]!;
    final Map<String, String> variables = <String, String>{
      ...procedure.parameterIds,
    };
    final Map<String, Object?> inputs = <String, Object?>{};
    final List<_Stmt> bodyStatements = procedure.returnsValue
        ? statement.body.sublist(0, statement.body.length - 1)
        : statement.body;
    final Map<String, Object?>? body = _statementChain(
      bodyStatements,
      _BuildScope(variables: variables, insideFunction: true),
    );
    if (body != null) inputs['STACK'] = _input(body);
    if (procedure.returnsValue) {
      inputs['RETURN'] = _input(
        _expressionBlock(
          (statement.body.last as _ReturnStmt).value,
          _BuildScope(variables: variables, insideFunction: true),
        ),
      );
    }
    return _block(
      procedure.returnsValue
          ? 'procedures_defreturn'
          : 'procedures_defnoreturn',
      fields: <String, Object?>{'NAME': statement.name},
      extraState: <String, Object?>{
        'name': statement.name,
        'params': <Object?>[
          for (final String parameter in statement.parameters)
            <String, Object?>{
              'name': parameter,
              'id': procedure.parameterIds[parameter],
            },
        ],
      },
      inputs: inputs,
    );
  }

  Map<String, Object?> _expressionBlock(_Expr expression, _BuildScope scope) {
    if (expression is _NumberExpr) return _numberBlock(expression.value);
    if (expression is _StringExpr) {
      return _block(
        'text',
        fields: <String, Object?>{'TEXT': expression.value},
      );
    }
    if (expression is _BooleanExpr) {
      return _block(
        'logic_boolean',
        fields: <String, Object?>{'BOOL': expression.value ? 'TRUE' : 'FALSE'},
      );
    }
    if (expression is _NoneExpr) return _block('logic_null');
    if (expression is _NameExpr) {
      final String? id = scope.variables[expression.name];
      if (id == null) {
        _fail('unknown_variable', expression.line, expression.column);
      }
      return _block(
        'variables_get',
        fields: <String, Object?>{
          'VAR': <String, Object?>{'id': id},
        },
      );
    }
    if (expression is _UnaryExpr) {
      if (expression.operator == 'not') {
        return _block(
          'logic_negate',
          inputs: <String, Object?>{
            'BOOL': _input(_expressionBlock(expression.value, scope)),
          },
        );
      }
      if (expression.operator == '-') {
        return _block(
          'math_single',
          fields: <String, Object?>{'OP': 'NEG'},
          inputs: <String, Object?>{
            'NUM': _input(_expressionBlock(expression.value, scope)),
          },
        );
      }
      if (expression.operator == '+') {
        return _expressionBlock(expression.value, scope);
      }
    }
    if (expression is _BinaryExpr) {
      const Map<String, String> arithmetic = <String, String>{
        '+': 'ADD',
        '-': 'MINUS',
        '*': 'MULTIPLY',
        '/': 'DIVIDE',
        '**': 'POWER',
      };
      const Map<String, String> comparisons = <String, String>{
        '==': 'EQ',
        '!=': 'NEQ',
        '<': 'LT',
        '<=': 'LTE',
        '>': 'GT',
        '>=': 'GTE',
      };
      if (arithmetic.containsKey(expression.operator)) {
        return _block(
          'math_arithmetic',
          fields: <String, Object?>{'OP': arithmetic[expression.operator]},
          inputs: <String, Object?>{
            'A': _input(_expressionBlock(expression.left, scope)),
            'B': _input(_expressionBlock(expression.right, scope)),
          },
        );
      }
      if (expression.operator == '%') {
        return _block(
          'math_modulo',
          inputs: <String, Object?>{
            'DIVIDEND': _input(_expressionBlock(expression.left, scope)),
            'DIVISOR': _input(_expressionBlock(expression.right, scope)),
          },
        );
      }
      if (comparisons.containsKey(expression.operator)) {
        return _block(
          'logic_compare',
          fields: <String, Object?>{'OP': comparisons[expression.operator]},
          inputs: <String, Object?>{
            'A': _input(_expressionBlock(expression.left, scope)),
            'B': _input(_expressionBlock(expression.right, scope)),
          },
        );
      }
      if (expression.operator == 'and' || expression.operator == 'or') {
        return _block(
          'logic_operation',
          fields: <String, Object?>{
            'OP': expression.operator == 'and' ? 'AND' : 'OR',
          },
          inputs: <String, Object?>{
            'A': _input(_expressionBlock(expression.left, scope)),
            'B': _input(_expressionBlock(expression.right, scope)),
          },
        );
      }
    }
    if (expression is _CallExpr) {
      if (expression.target is _NameExpr &&
          (expression.target as _NameExpr).name == 'Pin') {
        return _pinBlock(expression);
      }
      if (expression.target is _NameExpr &&
          (expression.target as _NameExpr).name == 'NeoPixel') {
        return _neoPixelCreateBlock(expression);
      }
      if (expression.target is _NameExpr &&
          (expression.target as _NameExpr).name == 'ST7789') {
        return _tftCreateBlock(expression, scope);
      }
      if (expression.target is _NameExpr &&
          (expression.target as _NameExpr).name == 'rgb565') {
        return _tftColorBlock(expression, scope);
      }
      if (expression.target is _AttributeExpr) {
        final _AttributeExpr attribute = expression.target as _AttributeExpr;
        if (attribute.member == 'value' &&
            expression.arguments.isEmpty &&
            _isBoundPinName(attribute.target, scope)) {
          return _block(
            'pyble_gpio_read',
            inputs: <String, Object?>{
              'PIN': _input(_expressionBlock(attribute.target, scope)),
            },
          );
        }
      }
      if (expression.target is _NameExpr) {
        final String name = (expression.target as _NameExpr).name;
        final _Procedure? procedure = _procedures[name];
        if (procedure != null && procedure.returnsValue) {
          return _block(
            'procedures_callreturn',
            extraState: <String, Object?>{
              'name': name,
              'params': <Object?>[...procedure.statement.parameters],
            },
            inputs: <String, Object?>{
              for (
                int index = 0;
                index < expression.arguments.length;
                index += 1
              )
                'ARG$index': _input(
                  _expressionBlock(expression.arguments[index], scope),
                ),
            },
          );
        }
      }
      _fail('unsupported_call', expression.line, expression.column);
    }
    if (expression is _AttributeExpr) {
      _fail('unsupported_attribute', expression.line, expression.column);
    }
    if (expression is _TupleExpr) {
      _fail('unsupported_tuple', expression.line, expression.column);
    }
    if (expression is _SubscriptExpr) {
      _fail('unsupported_subscript', expression.line, expression.column);
    }
    _fail('unsupported_expression', expression.line, expression.column);
  }

  Map<String, Object?> _neoPixelCreateBlock(_CallExpr expression) {
    _validateNeoPixelCall(expression);
    final int pixels = _integerLiteral(
      expression.arguments[1],
      requireIntegerSyntax: true,
    )!;
    return _block(
      'pyble_neopixel_create',
      inputs: <String, Object?>{
        'PIN': _input(_pinBlock(expression.arguments[0] as _CallExpr)),
        'PIXELS': _input(_numberBlock(pixels)),
      },
    );
  }

  Map<String, Object?> _tftCreateBlock(
    _CallExpr expression,
    _BuildScope scope,
  ) {
    _validateTftConstructorCall(expression, scope);
    const List<String> numericNames = <String>[
      'SPI_ID',
      'BAUDRATE',
      'POLARITY',
      'PHASE',
    ];
    const List<String> pinNames = <String>[
      'SCK',
      'MOSI',
      'CS',
      'DC',
      'RESET',
      'BACKLIGHT',
    ];
    const List<String> geometryNames = <String>[
      'WIDTH',
      'HEIGHT',
      'X_OFFSET',
      'Y_OFFSET',
    ];
    final Map<String, Object?> inputs = <String, Object?>{};
    for (int index = 0; index < numericNames.length; index += 1) {
      inputs[numericNames[index]] = _input(
        _numberBlock(
          _integerLiteral(
            expression.arguments[index],
            requireIntegerSyntax: true,
          )!,
        ),
      );
    }
    for (int index = 0; index < pinNames.length; index += 1) {
      inputs[pinNames[index]] = _input(
        _pinBlock(expression.arguments[index + 4] as _CallExpr),
      );
    }
    for (int index = 0; index < geometryNames.length; index += 1) {
      inputs[geometryNames[index]] = _input(
        _numberBlock(
          _integerLiteral(
            expression.arguments[index + 10],
            requireIntegerSyntax: true,
          )!,
        ),
      );
    }
    inputs['BGR'] = _input(_expressionBlock(expression.arguments[14], scope));
    inputs['INVERSION'] = _input(
      _expressionBlock(expression.arguments[15], scope),
    );
    return _block('pyble_tft_create', inputs: inputs);
  }

  Map<String, Object?> _tftColorBlock(_CallExpr expression, _BuildScope scope) {
    _validateTftColorCall(expression, scope);
    return _block(
      'pyble_tft_rgb565',
      inputs: <String, Object?>{
        'RED': _input(_expressionBlock(expression.arguments[0], scope)),
        'GREEN': _input(_expressionBlock(expression.arguments[1], scope)),
        'BLUE': _input(_expressionBlock(expression.arguments[2], scope)),
      },
    );
  }

  Map<String, Object?> _tftStatementBlock(
    _CallExpr expression,
    _AttributeExpr attribute,
    _BuildScope scope,
  ) {
    final Map<String, Object?> display = _input(
      _expressionBlock(attribute.target, scope),
    );
    final List<_Expr> arguments = expression.arguments;
    if (attribute.member == 'fill') {
      return _block(
        'pyble_tft_fill',
        inputs: <String, Object?>{
          'DISPLAY': display,
          'COLOR': _input(_tftColorBlock(arguments[0] as _CallExpr, scope)),
        },
      );
    }
    if (attribute.member == 'pixel') {
      return _block(
        'pyble_tft_pixel',
        inputs: <String, Object?>{
          'DISPLAY': display,
          'X': _input(_expressionBlock(arguments[0], scope)),
          'Y': _input(_expressionBlock(arguments[1], scope)),
          'COLOR': _input(_tftColorBlock(arguments[2] as _CallExpr, scope)),
        },
      );
    }
    if (attribute.member == 'rect' || attribute.member == 'fill_rect') {
      return _block(
        'pyble_tft_rect',
        fields: <String, Object?>{
          'STYLE': attribute.member == 'fill_rect' ? 'FILLED' : 'OUTLINE',
        },
        inputs: <String, Object?>{
          'DISPLAY': display,
          'X': _input(_expressionBlock(arguments[0], scope)),
          'Y': _input(_expressionBlock(arguments[1], scope)),
          'WIDTH': _input(_expressionBlock(arguments[2], scope)),
          'HEIGHT': _input(_expressionBlock(arguments[3], scope)),
          'COLOR': _input(_tftColorBlock(arguments[4] as _CallExpr, scope)),
        },
      );
    }
    if (attribute.member == 'text') {
      return _block(
        'pyble_tft_text',
        inputs: <String, Object?>{
          'DISPLAY': display,
          'TEXT': _input(_expressionBlock(arguments[0], scope)),
          'X': _input(_expressionBlock(arguments[1], scope)),
          'Y': _input(_expressionBlock(arguments[2], scope)),
          'COLOR': _input(_tftColorBlock(arguments[3] as _CallExpr, scope)),
        },
      );
    }
    if (attribute.member == 'show') {
      return _block(
        'pyble_tft_show',
        inputs: <String, Object?>{'DISPLAY': display},
      );
    }
    if (attribute.member == 'backlight') {
      return _block(
        'pyble_tft_backlight',
        inputs: <String, Object?>{
          'DISPLAY': display,
          'ON': _input(_expressionBlock(arguments[0], scope)),
        },
      );
    }
    _fail('unsupported_call', expression.line, expression.column);
  }

  bool _isTftColorCall(_Expr expression) =>
      expression is _CallExpr &&
      expression.target is _NameExpr &&
      (expression.target as _NameExpr).name == 'rgb565';

  Map<String, Object?> _neoPixelColorBlock(
    _Expr expression,
    _BuildScope scope,
  ) {
    if (expression is! _TupleExpr || expression.values.length != 3) {
      _fail('invalid_neopixel_color', expression.line, expression.column);
    }
    return _block(
      'pyble_neopixel_rgb',
      inputs: <String, Object?>{
        'RED': _input(_expressionBlock(expression.values[0], scope)),
        'GREEN': _input(_expressionBlock(expression.values[1], scope)),
        'BLUE': _input(_expressionBlock(expression.values[2], scope)),
      },
    );
  }

  Map<String, Object?> _pinBlock(_CallExpr expression) {
    _validatePinCall(expression);
    final Object gpio = _pinIdentity(expression.arguments[0])!;
    final String? mode = _pinConstant(expression.arguments[1]);
    if (mode != 'IN' && mode != 'OUT') {
      _fail('invalid_gpio', expression.line, expression.column);
    }
    String pull = 'NONE';
    if (expression.arguments.length == 3) {
      final _Expr pullExpression = expression.arguments[2];
      if (pullExpression is _NoneExpr) {
        pull = 'NONE';
      } else {
        final String? value = _pinConstant(pullExpression);
        if (value == 'PULL_UP') {
          pull = 'UP';
        } else if (value == 'PULL_DOWN') {
          pull = 'DOWN';
        } else {
          _fail('invalid_gpio', pullExpression.line, pullExpression.column);
        }
      }
    }
    return _block(
      'pyble_gpio_pin',
      fields: <String, Object?>{'MODE': mode, 'PULL': pull},
      inputs: <String, Object?>{
        'GPIO': _input(
          gpio is String
              ? _block('text', fields: <String, Object?>{'TEXT': gpio})
              : _numberBlock(gpio as int),
        ),
      },
    );
  }

  /// FR-BLOCKS-1B pin identity: a non-negative integer literal (`int`), a
  /// quoted `machine.Pin` name under the frozen grammar (`String`), or
  /// `null` for anything else (the existing invalid-pin path).
  Object? _pinIdentity(_Expr expression) {
    if (expression is _StringExpr) {
      return _pinNamePattern.hasMatch(expression.value)
          ? expression.value
          : null;
    }
    final int? gpio = _integerLiteral(expression, requireIntegerSyntax: true);
    if (gpio == null || gpio < 0) return null;
    return gpio;
  }

  static final RegExp _pinNamePattern = RegExp(r'^[A-Za-z][A-Za-z0-9_]{0,15}$');

  String? _pinConstant(_Expr expression) {
    if (expression is! _AttributeExpr ||
        expression.target is! _NameExpr ||
        (expression.target as _NameExpr).name != 'Pin') {
      return null;
    }
    return expression.member;
  }

  int? _integerLiteral(_Expr expression, {required bool requireIntegerSyntax}) {
    if (expression is _NumberExpr &&
        expression.value.isFinite &&
        (!requireIntegerSyntax || expression.isIntegerLiteral) &&
        expression.value == expression.value.round()) {
      final int value = expression.value.toInt();
      return _isSafeInteger(value) ? value : null;
    }
    if (expression is _UnaryExpr &&
        (expression.operator == '-' || expression.operator == '+')) {
      final int? value = _integerLiteral(
        expression.value,
        requireIntegerSyntax: requireIntegerSyntax,
      );
      if (value == null) return null;
      return expression.operator == '-' ? -value : value;
    }
    return null;
  }

  bool _isSafeInteger(int value) =>
      value >= -kMaxBlocklySafeInteger && value <= kMaxBlocklySafeInteger;

  Map<String, Object?> _numberBlock(num value) {
    if (!value.isFinite ||
        value == value.round() &&
            (value > kMaxBlocklySafeInteger ||
                value < -kMaxBlocklySafeInteger)) {
      _fail('integer_out_of_range', 1, 1);
    }
    return _block('math_number', fields: <String, Object?>{'NUM': value});
  }
}

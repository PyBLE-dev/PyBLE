// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';

import 'package:pyble/blocks/blocks.dart';

Map<String, dynamic> _workspaceOf(String source) {
  final PythonBlocksConversion result = const PythonToBlocksConverter().convert(
    source,
  );
  expect(result.diagnostics, isEmpty, reason: result.diagnostics.toString());
  expect(result.workspaceJson, isNotNull);
  return jsonDecode(result.workspaceJson!)! as Map<String, dynamic>;
}

Iterable<Map<String, dynamic>> _objects(Object? value) sync* {
  if (value is Map<String, dynamic>) {
    yield value;
    for (final Object? child in value.values) {
      yield* _objects(child);
    }
  } else if (value is List<dynamic>) {
    for (final Object? child in value) {
      yield* _objects(child);
    }
  }
}

Map<String, dynamic> _onlyType(Map<String, dynamic> workspace, String type) =>
    _objects(
      workspace,
    ).singleWhere((Map<String, dynamic> value) => value['type'] == type);

void main() {
  group('bounded Python to ordinary Blockly conversion', () {
    test(
      'converts print, literals, variables, and precedence deterministically',
      () {
        const String source = '''
x = 1 + 2 * 3
print(x)
print("hello")
print(True)
print(None)
''';
        final PythonBlocksConversion first = const PythonToBlocksConverter()
            .convert(source);
        final PythonBlocksConversion second = const PythonToBlocksConverter()
            .convert(source);

        expect(first.diagnostics, isEmpty);
        expect(first.workspaceJson, second.workspaceJson);
        final Map<String, dynamic> workspace =
            jsonDecode(first.workspaceJson!)! as Map<String, dynamic>;
        final List<dynamic> variables =
            workspace['variables']! as List<dynamic>;
        expect(variables, <Object?>[
          <String, Object?>{'name': 'x', 'id': 'py-import-v0001'},
        ]);
        final Map<String, dynamic> set = _onlyType(workspace, 'variables_set');
        final Map<String, dynamic> add = _objects(set).firstWhere(
          (Map<String, dynamic> value) =>
              value['type'] == 'math_arithmetic' &&
              (value['fields']! as Map<String, dynamic>)['OP'] == 'ADD',
        );
        final Map<String, dynamic> multiply = _objects(add).firstWhere(
          (Map<String, dynamic> value) =>
              value['type'] == 'math_arithmetic' &&
              (value['fields']! as Map<String, dynamic>)['OP'] == 'MULTIPLY',
        );
        expect((multiply['inputs']! as Map<String, dynamic>).keys, <String>[
          'A',
          'B',
        ]);
        expect(
          _objects(workspace)
              .where(
                (Map<String, dynamic> value) => value['type'] == 'text_print',
              )
              .length,
          4,
        );
        final List<String> blockIds = _objects(workspace)
            .where((Map<String, dynamic> value) => value['type'] is String)
            .map((Map<String, dynamic> value) => value['id'])
            .whereType<String>()
            .toList();
        expect(blockIds.toSet().length, blockIds.length);
      },
    );

    test('converts nested if/else, boolean logic, comparisons, and while', () {
      final Map<String, dynamic> workspace = _workspaceOf('''
done = False
x = 2
while x < 10:
    if x >= 2 and not done:
        print(x)
    else:
        print("no")
''');
      final Map<String, dynamic> whileBlock = _onlyType(
        workspace,
        'controls_whileUntil',
      );
      expect((whileBlock['fields']! as Map<String, dynamic>)['MODE'], 'WHILE');
      final Map<String, dynamic> ifBlock = _onlyType(workspace, 'controls_if');
      expect(ifBlock['extraState'], <String, Object?>{'hasElse': true});
      final Map<String, dynamic> operation = _onlyType(
        workspace,
        'logic_operation',
      );
      expect((operation['fields']! as Map<String, dynamic>)['OP'], 'AND');
      expect(_onlyType(workspace, 'logic_negate'), isNotEmpty);
      expect(
        _objects(workspace)
            .where(
              (Map<String, dynamic> value) => value['type'] == 'logic_compare',
            )
            .map(
              (Map<String, dynamic> value) =>
                  (value['fields']! as Map<String, dynamic>)['OP'],
            ),
        containsAll(<String>['LT', 'GTE']),
      );
    });

    test('maps Python range stop-exclusive bounds to Blockly inclusive TO', () {
      final Map<String, dynamic> workspace = _workspaceOf('''
for i in range(5):
    print(i)
for j in range(1, 6, 2):
    print(j)
''');
      final List<Map<String, dynamic>> loops = _objects(workspace)
          .where(
            (Map<String, dynamic> value) => value['type'] == 'controls_for',
          )
          .toList();
      expect(loops, hasLength(2));

      int numberInput(Map<String, dynamic> block, String name) {
        final Map<String, dynamic> input =
            (block['inputs']! as Map<String, dynamic>)[name]!
                as Map<String, dynamic>;
        final Map<String, dynamic> number =
            (input['block'] ?? input['shadow'])! as Map<String, dynamic>;
        return (number['fields']! as Map<String, dynamic>)['NUM']! as int;
      }

      expect(
        <int>[
          numberInput(loops[0], 'FROM'),
          numberInput(loops[0], 'TO'),
          numberInput(loops[0], 'BY'),
        ],
        <int>[0, 4, 1],
      );
      expect(
        <int>[
          numberInput(loops[1], 'FROM'),
          numberInput(loops[1], 'TO'),
          numberInput(loops[1], 'BY'),
        ],
        <int>[1, 5, 2],
      );
    });

    test('converts no-return functions, parameters, and calls', () {
      final Map<String, dynamic> workspace = _workspaceOf('''
def greet(name):
    print(name)

greet("Ada")
''');
      final Map<String, dynamic> definition = _onlyType(
        workspace,
        'procedures_defnoreturn',
      );
      expect(definition['extraState'], <String, Object?>{
        'name': 'greet',
        'params': <Object?>[
          <String, Object?>{'name': 'name', 'id': 'py-import-p0001'},
        ],
      });
      final Map<String, dynamic> call = _onlyType(
        workspace,
        'procedures_callnoreturn',
      );
      expect(call['extraState'], <String, Object?>{
        'name': 'greet',
        'params': <Object?>['name'],
      });
    });

    test('consumes supported imports and creates generic GPIO/time blocks', () {
      final Map<String, dynamic> workspace = _workspaceOf('''
from machine import Pin
from time import sleep_ms

led = Pin(17, Pin.OUT)
button = Pin(23, Pin.IN, Pin.PULL_UP)
led.value(1)
print(button.value())
sleep_ms(500)
''');
      final List<Map<String, dynamic>> pins = _objects(workspace)
          .where(
            (Map<String, dynamic> value) => value['type'] == 'pyble_gpio_pin',
          )
          .toList();
      expect(pins, hasLength(2));
      expect(
        pins.map((Map<String, dynamic> value) => value['fields']),
        containsAll(<Map<String, Object?>>[
          <String, Object?>{'MODE': 'OUT', 'PULL': 'NONE'},
          <String, Object?>{'MODE': 'IN', 'PULL': 'UP'},
        ]),
      );
      expect(
        (_onlyType(workspace, 'pyble_gpio_write')['fields']!
            as Map<String, dynamic>)['LEVEL'],
        'HIGH',
      );
      expect(_onlyType(workspace, 'pyble_gpio_read'), isNotEmpty);
      expect(_onlyType(workspace, 'pyble_time_sleep_ms'), isNotEmpty);
      expect(
        _objects(workspace)
            .where(
              (Map<String, dynamic> value) => value['type'] == 'math_number',
            )
            .map(
              (Map<String, dynamic> value) =>
                  (value['fields']! as Map<String, dynamic>)['NUM'],
            ),
        containsAll(<int>[17, 23, 500]),
      );
    });

    test('maps the bounded standard NeoPixel subset to ordinary blocks', () {
      final Map<String, dynamic> workspace = _workspaceOf('''
from machine import Pin
from neopixel import NeoPixel

red = 8
pixel = 0
strip = NeoPixel(Pin(48, Pin.OUT), 1)
strip[pixel + 0] = (red, 16 + 1, 24)
strip.fill((0, 0, 0))
strip.write()
''');

      final Map<String, dynamic> create = _onlyType(
        workspace,
        'pyble_neopixel_create',
      );
      expect(
        (create['inputs']! as Map<String, dynamic>).keys,
        containsAll(<String>['PIN', 'PIXELS']),
      );
      expect(
        _objects(create).any(
          (Map<String, dynamic> value) => value['type'] == 'pyble_gpio_pin',
        ),
        isTrue,
      );

      final Map<String, dynamic> setPixel = _onlyType(
        workspace,
        'pyble_neopixel_set_pixel',
      );
      expect(
        (setPixel['inputs']! as Map<String, dynamic>).keys,
        containsAll(<String>['STRIP', 'INDEX', 'COLOR']),
      );
      expect(
        _objects(setPixel).any(
          (Map<String, dynamic> value) => value['type'] == 'math_arithmetic',
        ),
        isTrue,
      );

      final Map<String, dynamic> fill = _onlyType(
        workspace,
        'pyble_neopixel_fill',
      );
      expect(
        (fill['inputs']! as Map<String, dynamic>).keys,
        containsAll(<String>['STRIP', 'COLOR']),
      );
      expect(_onlyType(workspace, 'pyble_neopixel_write'), isNotEmpty);

      final List<Map<String, dynamic>> colors = _objects(workspace)
          .where(
            (Map<String, dynamic> value) =>
                value['type'] == 'pyble_neopixel_rgb',
          )
          .toList(growable: false);
      expect(colors, hasLength(2));
      for (final Map<String, dynamic> color in colors) {
        expect(
          (color['inputs']! as Map<String, dynamic>).keys,
          containsAll(<String>['RED', 'GREEN', 'BLUE']),
        );
      }
    });

    test('accepts CRLF, a missing final newline, and Unicode string data', () {
      final PythonBlocksConversion result = const PythonToBlocksConverter()
          .convert('print("สวัสดี")\r\nprint("done")');
      expect(result.diagnostics, isEmpty);
      expect(result.workspaceJson, isNotNull);
      expect(result.workspaceJson, contains('สวัสดี'));
    });
  });

  group('bounded importer diagnostics are all-or-nothing', () {
    final Map<String, String> rejected = <String, String>{
      'unsupported_import': 'import machine\n',
      'comment': '# not silently discarded\nprint("hello")\n',
      'tabs': 'if True:\n\tprint("hello")\n',
      'indentation': 'if True:\n  print("hello")\n    print("misaligned")\n',
      'unsupported_statement': 'return 1\n',
      'unsupported_call': 'open("file.txt")\n',
      'invalid_range': 'for i in range(0):\n    print(i)\n',
      'invalid_gpio': 'led = Pin(-1, Pin.OUT)\n',
      'invalid_sleep': 'sleep_ms(1 + 2)\n',
      'multiple_statements': 'x = 1; print(x)\n',
      'chained_comparison': 'if 1 < x < 3:\n    print(x)\n',
      'unterminated_string': 'print("hello)\n',
    };

    for (final MapEntry<String, String> entry in rejected.entries) {
      test('rejects ${entry.key} without producing a workspace', () {
        final PythonBlocksConversion result = const PythonToBlocksConverter()
            .convert(entry.value);

        expect(result.workspaceJson, isNull);
        expect(result.hasErrors, isTrue);
        expect(result.diagnostics, isNotEmpty);
        final PythonBlocksDiagnostic diagnostic = result.diagnostics.first;
        expect(diagnostic.code, isNotEmpty);
        expect(diagnostic.line, greaterThanOrEqualTo(1));
        expect(diagnostic.column, greaterThanOrEqualTo(1));
        expect(diagnostic.endLine, greaterThanOrEqualTo(diagnostic.line));
        expect(diagnostic.endColumn, greaterThanOrEqualTo(1));
      });
    }

    test('empty source has one stable source-positioned diagnostic', () {
      final PythonBlocksConversion result = const PythonToBlocksConverter()
          .convert(' \r\n');
      expect(result.workspaceJson, isNull);
      expect(result.diagnostics, hasLength(1));
      expect(result.diagnostics.single.code, 'empty_source');
      expect(result.diagnostics.single.line, 1);
      expect(result.diagnostics.single.column, 1);
    });

    test('same invalid source produces byte-stable diagnostics', () {
      final PythonBlocksConversion first = const PythonToBlocksConverter()
          .convert('if True\n    pass\n');
      final PythonBlocksConversion second = const PythonToBlocksConverter()
          .convert('if True\n    pass\n');
      expect(
        first.diagnostics.map((PythonBlocksDiagnostic value) => value.toJson()),
        second.diagnostics.map(
          (PythonBlocksDiagnostic value) => value.toJson(),
        ),
      );
    });
  });

  group('ADR-0017 resource and diagnostic contract', () {
    test('publishes the exact frozen resource ceilings', () {
      expect(kMaxPythonBlocksSourceBytes, 256 * 1024);
      expect(kMaxPythonBlocksLines, 4096);
      expect(kMaxPythonBlocksNodes, 20000);
      expect(kMaxPythonBlocksIndentationLevels, 32);
      expect(kMaxBlocklySafeInteger, 9007199254740991);
    });

    test('accepts 4096 physical lines and rejects line 4097', () {
      final String atLimit = <String>[
        ...List<String>.filled(kMaxPythonBlocksLines - 1, ''),
        'print(1)',
      ].join('\n');
      final String overLimit = <String>[
        ...List<String>.filled(kMaxPythonBlocksLines, ''),
        'print(1)',
      ].join('\n');

      expect(
        const PythonToBlocksConverter().convert(atLimit).diagnostics,
        isEmpty,
      );
      expect(
        const PythonToBlocksConverter()
            .convert(overLimit)
            .diagnostics
            .single
            .code,
        'source_too_many_lines',
      );
    });

    test('accepts 32 indentation levels and rejects level 33', () {
      String nested(int levels) {
        final StringBuffer source = StringBuffer();
        for (int level = 0; level < levels; level += 1) {
          source.writeln(
            '${List<String>.filled(level, '    ').join()}if True:',
          );
        }
        source.writeln('${List<String>.filled(levels, '    ').join()}pass');
        return source.toString();
      }

      expect(
        const PythonToBlocksConverter().convert(nested(32)).diagnostics,
        isEmpty,
      );
      expect(
        const PythonToBlocksConverter()
            .convert(nested(33))
            .diagnostics
            .single
            .code,
        'indentation_too_deep',
      );
    });

    test('rejects more than 20000 syntax nodes during parsing', () {
      final String source =
          'print(${List<String>.filled(10001, '1').join(' + ')})\n';
      final PythonBlocksConversion result = const PythonToBlocksConverter()
          .convert(source);

      expect(result.workspaceJson, isNull);
      expect(result.diagnostics.single.code, 'source_too_complex');
    });

    test('hostile recursive expression depth fails without escaping', () {
      final String source = 'print(${List<String>.filled(300, '+').join()}1)\n';
      final PythonBlocksConversion result = const PythonToBlocksConverter()
          .convert(source);

      expect(result.workspaceJson, isNull);
      expect(result.diagnostics.single.code, 'expression_too_deep');
    });

    test('hostile redundant-parenthesis depth fails as a resource error', () {
      final String source =
          'print(${List<String>.filled(300, '(').join()}1'
          '${List<String>.filled(300, ')').join()})\n';
      final PythonBlocksConversion result = const PythonToBlocksConverter()
          .convert(source);

      expect(result.workspaceJson, isNull);
      expect(result.diagnostics.single.code, 'expression_too_deep');
    });

    test('uses Unicode-scalar columns and frozen diagnostic JSON shape', () {
      final PythonBlocksDiagnostic diagnostic = const PythonToBlocksConverter()
          .convert('print("😀") @\n')
          .diagnostics
          .single;

      expect(diagnostic.code, 'invalid_token');
      expect(diagnostic.startLine, 1);
      expect(diagnostic.startColumn, 12);
      expect(diagnostic.endColumn, 13);
      expect(diagnostic.severity, 'error');
      expect(diagnostic.messageKey, 'pythonBlocksDiagnostic');
      expect(diagnostic.toJson().keys, <String>[
        'code',
        'severity',
        'startLine',
        'startColumn',
        'endLine',
        'endColumn',
        'messageKey',
        'args',
      ]);
      expect(diagnostic.args['code'], 'invalid_token');
    });

    test('warning-only conversions do not report hasErrors', () {
      const PythonBlocksConversion conversion = PythonBlocksConversion(
        workspaceJson: '{}',
        diagnostics: <PythonBlocksDiagnostic>[
          PythonBlocksDiagnostic(
            code: 'normalized_layout',
            severity: 'warning',
            line: 1,
            column: 1,
            endLine: 1,
            endColumn: 1,
          ),
        ],
      );
      expect(conversion.hasErrors, isFalse);
    });

    test('checks UTF-8 byte size before empty-source classification', () {
      final String source = List<String>.filled(
        kMaxPythonBlocksSourceBytes + 1,
        ' ',
      ).join();
      final PythonBlocksConversion result = const PythonToBlocksConverter()
          .convert(source);
      expect(result.diagnostics.single.code, 'source_too_large');
    });
  });

  group('ADR-0017 names, numbers, imports, and GPIO bindings', () {
    test('accepts safe integer boundaries, finite floats, and unary plus', () {
      final PythonBlocksConversion result = const PythonToBlocksConverter()
          .convert('''
print(9007199254740991)
print(-9007199254740991)
print(+1.5)
''');
      expect(result.diagnostics, isEmpty);
    });

    test('rejects unsafe integral numeric literals', () {
      for (final String literal in <String>[
        '9007199254740992',
        '-9007199254740992',
        '9.007199254740992e15',
      ]) {
        final PythonBlocksConversion result = const PythonToBlocksConverter()
            .convert('print($literal)\n');
        expect(result.workspaceJson, isNull);
        expect(result.diagnostics.single.code, 'integer_out_of_range');
      }
    });

    test('rejects integral float syntax that Blockly would emit as int', () {
      for (final String literal in <String>[
        '1.0',
        '1.',
        '.0',
        '1e3',
        '1.00e+2',
      ]) {
        final PythonBlocksConversion result = const PythonToBlocksConverter()
            .convert('print($literal)\n');
        expect(result.workspaceJson, isNull, reason: literal);
        expect(
          result.diagnostics.single.code,
          'integral_float_not_preserved',
          reason: literal,
        );
      }
    });

    test('integer-only constructs require decimal integer syntax', () {
      final Map<String, String> failures = <String, String>{
        'invalid_sleep':
            'from time import sleep_ms\n'
            'sleep_ms(1.0)\n',
        'invalid_gpio':
            'from machine import Pin\n'
            'p = Pin(1.0, Pin.OUT)\n',
        'invalid_range': 'for i in range(0.0, 2):\n    pass\n',
      };
      for (final MapEntry<String, String> failure in failures.entries) {
        final PythonBlocksConversion result = const PythonToBlocksConverter()
            .convert(failure.value);
        expect(result.workspaceJson, isNull, reason: failure.key);
        expect(result.diagnostics.single.code, failure.key);
      }
    });

    test('rejects Python keywords and pinned-generator reserved names', () {
      for (final String name in <String>['class', 'len', 'range', 'Pin']) {
        final PythonBlocksConversion result = const PythonToBlocksConverter()
            .convert('$name = 1\n');
        expect(result.workspaceJson, isNull, reason: name);
        expect(result.diagnostics.single.code, 'reserved_name', reason: name);
      }
    });

    test('requires exact, unique, leading, use-dependent imports', () {
      final Map<String, String> failures = <String, String>{
        'missing_required_import': 'p = Pin(1, Pin.OUT)\n',
        'unused_import': 'from machine import Pin\nprint(1)\n',
        'duplicate_import':
            'from machine import Pin\nfrom machine import Pin\n'
            'p = Pin(1, Pin.OUT)\n',
        'imports_must_be_leading':
            'print(1)\nfrom time import sleep_ms\nsleep_ms(1)\n',
        'unsupported_import':
            'from machine import Pin as Gpio\n'
            'p = Pin(1, Pin.OUT)\n',
      };
      for (final MapEntry<String, String> failure in failures.entries) {
        final PythonBlocksConversion result = const PythonToBlocksConverter()
            .convert(failure.value);
        expect(result.workspaceJson, isNull, reason: failure.key);
        expect(
          result.diagnostics.single.code,
          failure.key,
          reason: failure.value,
        );
      }
    });

    test('requires value calls to use a simple Pin-bound identifier', () {
      const String source = '''
from machine import Pin
x = 1
print(x.value())
''';
      final PythonBlocksConversion result = const PythonToBlocksConverter()
          .convert(source);
      expect(result.workspaceJson, isNull);
      expect(result.diagnostics.single.code, 'unsupported_call');
    });

    test('requires every read and change to follow a definite binding', () {
      final Map<String, String> failures = <String, String>{
        'forward_read': 'print(x)\nx = 1\n',
        'conditional_only_read':
            'if False:\n'
            '    x = 1\n'
            'print(x)\n',
        'change_before_bind': 'x += 1\nx = 0\n',
        'pin_use_before_bind':
            'from machine import Pin\n'
            'p.value(1)\n'
            'p = Pin(1, Pin.OUT)\n',
      };
      for (final MapEntry<String, String> failure in failures.entries) {
        final PythonBlocksConversion result = const PythonToBlocksConverter()
            .convert(failure.value);
        expect(result.workspaceJson, isNull, reason: failure.key);
        expect(result.hasErrors, isTrue, reason: failure.key);
      }
    });

    test('retains bindings established on every conditional path', () {
      final PythonBlocksConversion result = const PythonToBlocksConverter()
          .convert('''
if True:
    x = 1
else:
    x = 2
print(x)
''');
      expect(result.diagnostics, isEmpty);
    });

    test('does not retain a Pin binding invalidated by a while body', () {
      final PythonBlocksConversion result = const PythonToBlocksConverter()
          .convert('''
from machine import Pin

iteration = 0
pin = Pin(48, Pin.OUT)
while iteration < 1:
    pin = 0
    iteration += 1
pin.value(1)
''');

      expect(result.workspaceJson, isNull);
      expect(result.hasErrors, isTrue);
    });

    test('validates a Pin-bound while condition across the backedge', () {
      final PythonBlocksConversion result = const PythonToBlocksConverter()
          .convert('''
from machine import Pin

pin = Pin(48, Pin.IN)
while pin.value() == 1:
    pin = 0
''');

      expect(result.workspaceJson, isNull);
      expect(result.hasErrors, isTrue);
    });

    test('rejects raw NUL in a string with a scalar-positioned diagnostic', () {
      final PythonBlocksConversion result = const PythonToBlocksConverter()
          .convert('print("a\u0000b")\n');

      expect(result.workspaceJson, isNull);
      expect(result.diagnostics.single.code, 'nul_character_not_supported');
      expect(result.diagnostics.single.startLine, 1);
      expect(result.diagnostics.single.startColumn, 9);
      expect(result.diagnostics.single.endColumn, 10);
    });
  });

  group('ADR-0018 bounded NeoPixel imports and bindings', () {
    const String imports = '''
from machine import Pin
from neopixel import NeoPixel
''';

    test('requires an exact, unique, leading, use-dependent import', () {
      final Map<String, String> failures = <String, String>{
        'missing_required_import':
            'from machine import Pin\n'
            'strip = NeoPixel(Pin(48, Pin.OUT), 1)\n',
        'unused_import':
            'from neopixel import NeoPixel\n'
            'print(1)\n',
        'duplicate_import':
            'from machine import Pin\n'
            'from neopixel import NeoPixel\n'
            'from neopixel import NeoPixel\n'
            'strip = NeoPixel(Pin(48, Pin.OUT), 1)\n',
        'unsupported_import':
            'from machine import Pin\n'
            'from neopixel import NeoPixel as Pixels\n'
            'strip = NeoPixel(Pin(48, Pin.OUT), 1)\n',
        'imports_must_be_leading':
            'from machine import Pin\n'
            'print(1)\n'
            'from neopixel import NeoPixel\n'
            'strip = NeoPixel(Pin(48, Pin.OUT), 1)\n',
      };

      for (final MapEntry<String, String> failure in failures.entries) {
        final PythonBlocksConversion result = const PythonToBlocksConverter()
            .convert(failure.value);
        expect(result.workspaceJson, isNull, reason: failure.key);
        expect(result.diagnostics.single.code, failure.key);
      }
    });

    test('admits only an inline Pin and positive literal pixel count', () {
      final List<String> invalidConstructors = <String>[
        'strip = NeoPixel(Pin(48, Pin.OUT))',
        'strip = NeoPixel(Pin(48, Pin.OUT), 1, 3)',
        'strip = NeoPixel(Pin(48, Pin.OUT), 1, timing=1)',
        'strip = NeoPixel(pin=Pin(48, Pin.OUT), n=1)',
        'pin = Pin(48, Pin.OUT)\nstrip = NeoPixel(pin, 1)',
        'strip = NeoPixel(Pin(48, Pin.OUT), 0)',
        'strip = NeoPixel(Pin(48, Pin.OUT), -1)',
        'strip = NeoPixel(Pin(48, Pin.OUT), 1.0)',
        'strip = NeoPixel(Pin(48, Pin.OUT), 1 + 1)',
      ];

      for (final String constructor in invalidConstructors) {
        final PythonBlocksConversion result = const PythonToBlocksConverter()
            .convert('$imports$constructor\n');
        expect(result.workspaceJson, isNull, reason: constructor);
        expect(result.hasErrors, isTrue, reason: constructor);
      }
    });

    test('accepts a receiver established on every branch', () {
      final PythonBlocksConversion result = const PythonToBlocksConverter()
          .convert('''
$imports
if True:
    strip = NeoPixel(Pin(47, Pin.OUT), 1)
else:
    strip = NeoPixel(Pin(48, Pin.OUT), 1)
strip.write()
''');
      expect(result.diagnostics, isEmpty);
      expect(result.workspaceJson, isNotNull);
    });

    test('requires each NeoPixel operation to follow a definite binding', () {
      final Map<String, String> failures = <String, String>{
        'before_bind':
            '''
$imports
strip.write()
strip = NeoPixel(Pin(48, Pin.OUT), 1)
''',
        'conditional_only':
            '''
$imports
if True:
    strip = NeoPixel(Pin(48, Pin.OUT), 1)
strip.write()
''',
        'reassigned':
            '''
$imports
strip = NeoPixel(Pin(48, Pin.OUT), 1)
strip = 1
strip.write()
''',
        'ordinary_receiver':
            '''
$imports
strip = 1
strip.fill((1, 2, 3))
''',
      };

      for (final MapEntry<String, String> failure in failures.entries) {
        final PythonBlocksConversion result = const PythonToBlocksConverter()
            .convert(failure.value);
        expect(result.workspaceJson, isNull, reason: failure.key);
        expect(result.hasErrors, isTrue, reason: failure.key);
      }
    });

    test('admits RGB tuples only in bounded NeoPixel color positions', () {
      final List<String> invalidPrograms = <String>[
        'color = (1, 2, 3)',
        'strip = NeoPixel(Pin(48, Pin.OUT), 1)\n'
            'strip[0] = (1, 2, 3, 4)',
        'strip = NeoPixel(Pin(48, Pin.OUT), 1)\n'
            'strip.fill((1, 2))',
        'strip = NeoPixel(Pin(48, Pin.OUT), 1)\n'
            'strip.fill((1, "green", 3))',
        'strip = NeoPixel(Pin(48, Pin.OUT), 1)\n'
            'strip["first"] = (1, 2, 3)',
        'strip = NeoPixel(Pin(48, Pin.OUT), 1)\n'
            'strip.fill((1, 2, 3), 4)',
        'strip = NeoPixel(Pin(48, Pin.OUT), 1)\n'
            'strip.write(1)',
        'strip = NeoPixel(Pin(48, Pin.OUT), 1)\n'
            'strip.show()',
      ];

      for (final String program in invalidPrograms) {
        final PythonBlocksConversion result = const PythonToBlocksConverter()
            .convert('$imports$program\n');
        expect(result.workspaceJson, isNull, reason: program);
        expect(result.hasErrors, isTrue, reason: program);
      }
    });

    test('an invalid NeoPixel tail produces no partial workspace', () {
      final PythonBlocksConversion result = const PythonToBlocksConverter()
          .convert('''
$imports
strip = NeoPixel(Pin(48, Pin.OUT), 1)
strip[0] = (8, 16, 24)
strip.fill((1, 2, 3, 4))
''');

      expect(result.workspaceJson, isNull);
      expect(result.diagnostics, hasLength(1));
    });

    test('does not retain a receiver invalidated by a while body', () {
      final PythonBlocksConversion result = const PythonToBlocksConverter()
          .convert('''
$imports
iteration = 0
strip = NeoPixel(Pin(48, Pin.OUT), 1)
while iteration < 1:
    strip = 0
    iteration += 1
strip.write()
''');

      expect(result.workspaceJson, isNull);
      expect(result.hasErrors, isTrue);
    });

    test('validates a NeoPixel receiver across the for-loop backedge', () {
      for (final String range in <String>['range(2)', 'range(2, 0, -1)']) {
        final PythonBlocksConversion result = const PythonToBlocksConverter()
            .convert('''
$imports
strip = NeoPixel(Pin(48, Pin.OUT), 1)
for iteration in $range:
    strip.write()
    strip = 0
''');

        expect(result.workspaceJson, isNull, reason: range);
        expect(result.hasErrors, isTrue, reason: range);
      }
    });

    test('does not invent a backedge for a one-iteration range', () {
      for (final String range in <String>['range(1)', 'range(1, 0, -1)']) {
        final PythonBlocksConversion result = const PythonToBlocksConverter()
            .convert('''
$imports
strip = NeoPixel(Pin(48, Pin.OUT), 1)
for iteration in $range:
    strip.write()
    strip = 0
''');

        expect(result.diagnostics, isEmpty, reason: range);
        expect(result.workspaceJson, isNotNull, reason: range);
      }
    });

    test('preserves a receiver re-established before every loop use', () {
      final PythonBlocksConversion result = const PythonToBlocksConverter()
          .convert('''
$imports
strip = NeoPixel(Pin(48, Pin.OUT), 1)
for iteration in range(2):
    strip = NeoPixel(Pin(48, Pin.OUT), 1)
    strip.write()
    strip = 0
''');

      expect(result.diagnostics, isEmpty);
      expect(result.workspaceJson, isNotNull);
    });
  });

  group('ADR-0023 bounded ST7789 imports and bindings', () {
    const String imports = '''
from machine import Pin
from pyble_st7789 import ST7789
from pyble_st7789 import rgb565
''';

    test('maps the complete generated TFT subset to ordinary blocks', () {
      final Map<String, dynamic> workspace = _workspaceOf('''
$imports
display = ST7789(2, 40000000, 0, 0, Pin(40, Pin.OUT), Pin(45, Pin.OUT), Pin(42, Pin.OUT), Pin(41, Pin.OUT), Pin(39, Pin.OUT), Pin(46, Pin.OUT), 172, 320, 34, 0, True, True)
display.fill(rgb565(8, 18, 40))
display.pixel(0, 0, rgb565(255, 0, 0))
display.rect(8, 8, 156, 304, rgb565(0, 180, 216))
display.fill_rect(12, 12, 8, 8, rgb565(0, 255, 0))
display.text("Hello PyBLE", 24, 150, rgb565(255, 255, 255))
display.show()
display.backlight(True)
''');

      for (final String type in <String>[
        'pyble_tft_create',
        'pyble_tft_fill',
        'pyble_tft_pixel',
        'pyble_tft_text',
        'pyble_tft_show',
        'pyble_tft_backlight',
      ]) {
        expect(_onlyType(workspace, type), isNotEmpty, reason: type);
      }
      final List<Map<String, dynamic>> rectangles = _objects(workspace)
          .where(
            (Map<String, dynamic> value) => value['type'] == 'pyble_tft_rect',
          )
          .toList(growable: false);
      expect(rectangles, hasLength(2));
      expect(
        rectangles.map(
          (Map<String, dynamic> value) =>
              (value['fields']! as Map<String, dynamic>)['STYLE'],
        ),
        containsAll(<String>['OUTLINE', 'FILLED']),
      );
      expect(
        _objects(workspace)
            .where(
              (Map<String, dynamic> value) =>
                  value['type'] == 'pyble_tft_rgb565',
            )
            .length,
        5,
      );
      expect(
        _objects(workspace)
            .where(
              (Map<String, dynamic> value) => value['type'] == 'pyble_gpio_pin',
            )
            .length,
        6,
      );
    });

    test('accepts a display definitely constructed on every branch', () {
      final PythonBlocksConversion result = const PythonToBlocksConverter()
          .convert('''
from machine import Pin
from pyble_st7789 import ST7789

if True:
    display = ST7789(2, 40000000, 0, 0, Pin(40, Pin.OUT), Pin(45, Pin.OUT), Pin(42, Pin.OUT), Pin(41, Pin.OUT), Pin(39, Pin.OUT), Pin(46, Pin.OUT), 172, 320, 34, 0, True, True)
else:
    display = ST7789(2, 20000000, 0, 0, Pin(1, Pin.OUT), Pin(2, Pin.OUT), Pin(3, Pin.OUT), Pin(4, Pin.OUT), Pin(5, Pin.OUT), Pin(6, Pin.OUT), 128, 128, 0, 0, False, False)
display.show()
''');
      expect(result.diagnostics, isEmpty);
      expect(result.workspaceJson, isNotNull);
    });

    test('rejects malformed constructors and uncertain display receivers', () {
      for (final String source in <String>[
        '$imports\ndisplay = ST7789(2, 40000000)\n',
        '$imports\ndisplay = ST7789(spi_id=2)\n',
        '$imports\ndisplay.show()\n',
        '$imports\nif True:\n    display = ST7789(2, 40000000, 0, 0, Pin(40, Pin.OUT), Pin(45, Pin.OUT), Pin(42, Pin.OUT), Pin(41, Pin.OUT), Pin(39, Pin.OUT), Pin(46, Pin.OUT), 172, 320, 34, 0, True, True)\ndisplay.show()\n',
      ]) {
        final PythonBlocksConversion result = const PythonToBlocksConverter()
            .convert(source);
        expect(result.workspaceJson, isNull, reason: source);
        expect(result.hasErrors, isTrue, reason: source);
      }
    });
  });

  group('ADR-0017 normalized statements and control flow', () {
    test('accepts the pinned generator two-space suite indentation', () {
      final PythonBlocksConversion result = const PythonToBlocksConverter()
          .convert('''
if True:
  print("two spaces")
else:
  print("still consistent")
''');
      expect(result.diagnostics, isEmpty);
    });

    test('normalizes numeric += to an ordinary set/add/get graph', () {
      final Map<String, dynamic> workspace = _workspaceOf('''
x = 1
x += 2
''');
      final List<Map<String, dynamic>> sets = _objects(workspace)
          .where(
            (Map<String, dynamic> block) => block['type'] == 'variables_set',
          )
          .toList();
      expect(sets, hasLength(2));
      expect(
        _objects(sets.last).any(
          (Map<String, dynamic> block) =>
              block['type'] == 'math_arithmetic' &&
              (block['fields']! as Map<String, dynamic>)['OP'] == 'ADD',
        ),
        isTrue,
      );
      expect(
        _objects(
          sets.last,
        ).any((Map<String, dynamic> block) => block['type'] == 'variables_get'),
        isTrue,
      );
    });

    test('maps all elif branches into one controls_if mutation', () {
      final Map<String, dynamic> workspace = _workspaceOf('''
x = 2
if x == 0:
    print("zero")
elif x == 1:
    print("one")
elif x == 2:
    print("two")
else:
    print("other")
''');
      final Map<String, dynamic> block = _onlyType(workspace, 'controls_if');
      expect(block['extraState'], <String, Object?>{
        'elseIfCount': 2,
        'hasElse': true,
      });
      expect(
        (block['inputs']! as Map<String, dynamic>).keys,
        containsAll(<String>['IF0', 'DO0', 'IF1', 'DO1', 'IF2', 'DO2', 'ELSE']),
      );
    });

    test('maps descending ranges with adjusted endpoint and absolute BY', () {
      final Map<String, dynamic> workspace = _workspaceOf('''
for i in range(5, 0, -2):
    print(i)
''');
      final Map<String, dynamic> loop = _onlyType(workspace, 'controls_for');

      int inputNumber(String name) {
        final Map<String, dynamic> input =
            (loop['inputs']! as Map<String, dynamic>)[name]!
                as Map<String, dynamic>;
        final Map<String, dynamic> number =
            input['block']! as Map<String, dynamic>;
        return (number['fields']! as Map<String, dynamic>)['NUM']! as int;
      }

      expect(inputNumber('FROM'), 5);
      expect(inputNumber('TO'), 1);
      expect(inputNumber('BY'), 2);
    });

    test('rejects empty, zero-step, and direction-inconsistent ranges', () {
      for (final String args in <String>[
        '0',
        '0, 0',
        '0, 5, 0',
        '0, 5, -1',
        '5, 0, 1',
        '0.0, 5',
      ]) {
        final PythonBlocksConversion result = const PythonToBlocksConverter()
            .convert('for i in range($args):\n    pass\n');
        expect(result.workspaceJson, isNull, reason: args);
        expect(result.diagnostics.single.code, 'invalid_range', reason: args);
      }
    });

    test('admits pass only as a sole representable nested suite', () {
      final Map<String, dynamic> workspace = _workspaceOf('''
if True:
    pass
''');
      final Map<String, dynamic> block = _onlyType(workspace, 'controls_if');
      expect(
        (block['inputs']! as Map<String, dynamic>).containsKey('DO0'),
        isFalse,
      );

      for (final String source in <String>[
        'pass\n',
        'if True:\n    pass\n    print(1)\n',
      ]) {
        final PythonBlocksConversion result = const PythonToBlocksConverter()
            .convert(source);
        expect(result.workspaceJson, isNull);
        expect(result.diagnostics.single.code, 'pass_must_be_sole_statement');
      }
    });
  });

  group('ADR-0017 bounded procedures', () {
    test('converts a final value return and matching expression call', () {
      final Map<String, dynamic> workspace = _workspaceOf('''
def twice(value):
    return value * 2

print(twice(3))
''');
      expect(_onlyType(workspace, 'procedures_defreturn'), isNotEmpty);
      expect(_onlyType(workspace, 'procedures_callreturn'), isNotEmpty);
    });

    test('enforces function and parameter count bounds', () {
      final String sixteen = List<String>.generate(
        16,
        (int index) => 'def f$index():\n    pass\n',
      ).join();
      expect(
        const PythonToBlocksConverter().convert(sixteen).diagnostics,
        isEmpty,
      );
      expect(
        const PythonToBlocksConverter()
            .convert('${sixteen}def overflow():\n    pass\n')
            .diagnostics
            .single
            .code,
        'too_many_functions',
      );
      expect(
        const PythonToBlocksConverter()
            .convert('def f(a, b, c, d, e, f, g, h, i):\n    pass\n')
            .diagnostics
            .single
            .code,
        'too_many_function_parameters',
      );
    });

    test(
      'definitions precede module execution and return is exactly final',
      () {
        final Map<String, String> failures = <String, String>{
          'function_definitions_must_be_first':
              'print(1)\ndef later():\n    pass\n',
          'return_must_be_final':
              'def f():\n    return 1\n    print(2)\nprint(f())\n',
          'pass_must_be_sole_statement':
              'def f():\n    pass\n    return 1\nprint(f())\n',
        };
        for (final MapEntry<String, String> failure in failures.entries) {
          final PythonBlocksConversion result = const PythonToBlocksConverter()
              .convert(failure.value);
          expect(result.workspaceJson, isNull);
          expect(result.diagnostics.single.code, failure.key);
        }
      },
    );

    test('enforces exact arity and expression/statement call kind', () {
      final Map<String, String> failures = <String, String>{
        'invalid_function_call': 'def f(value):\n    print(value)\nf()\n',
        'returning_as_statement': 'def f():\n    return 1\nf()\n',
        'no_return_as_expression': 'def f():\n    pass\nprint(f())\n',
      };
      for (final MapEntry<String, String> failure in failures.entries) {
        final PythonBlocksConversion result = const PythonToBlocksConverter()
            .convert(failure.value);
        expect(result.workspaceJson, isNull, reason: failure.key);
        expect(
          result.diagnostics.single.code,
          failure.key == 'invalid_function_call'
              ? 'invalid_function_call'
              : 'function_call_kind_mismatch',
        );
      }
    });

    test('rejects local/free variables and recursive call cycles', () {
      final Map<String, String> failures = <String, String>{
        'function_local_assignment_not_supported': 'def f():\n    x = 1\nf()\n',
        'unknown_variable': 'def f():\n    print(x)\nx = 1\nf()\n',
        'recursive_function': 'def a():\n    b()\ndef b():\n    a()\na()\n',
      };
      for (final MapEntry<String, String> failure in failures.entries) {
        final PythonBlocksConversion result = const PythonToBlocksConverter()
            .convert(failure.value);
        expect(result.workspaceJson, isNull, reason: failure.key);
        expect(result.diagnostics.single.code, failure.key);
      }
    });
  });

  test('semantic fingerprints normalize production generator spellings', () {
    const String original = '''
from machine import Pin

led = Pin(17, Pin.OUT)
for i in range(3):
    print(led.value())
''';
    const String generated = '''
from machine import Pin

led = None
i = None

led = Pin(17, Pin.OUT, None)
for i in range(0, 3, 1):
    print(led.value())
''';
    final PythonBlocksConversion input = const PythonToBlocksConverter()
        .convert(original);
    final PythonBlocksConversion output = const PythonToBlocksConverter()
        .convert(generated, productionGenerated: true);

    expect(input.diagnostics, isEmpty);
    expect(output.diagnostics, isEmpty);
    expect(input.semanticFingerprint, isNotNull);
    expect(output.semanticFingerprint, input.semanticFingerprint);
  });

  test('generated-only preamble normalization preserves explicit None', () {
    const String original = '''
x = None
print(x)
''';
    const String generated = '''
x = None

x = None
print(x)
''';
    final PythonBlocksConversion input = const PythonToBlocksConverter()
        .convert(original);
    final PythonBlocksConversion output = const PythonToBlocksConverter()
        .convert(generated, productionGenerated: true);

    expect(input.diagnostics, isEmpty);
    expect(output.diagnostics, isEmpty);
    expect(output.semanticFingerprint, input.semanticFingerprint);
  });

  test('semantic fingerprint canonicalizes legal leading import order', () {
    const String timeFirst = '''
from time import sleep_ms
from machine import Pin

led = Pin(17, Pin.OUT)
sleep_ms(1)
''';
    const String pinFirst = '''
from machine import Pin
from time import sleep_ms

led = Pin(17, Pin.OUT, None)
sleep_ms(1)
''';
    final PythonBlocksConversion first = const PythonToBlocksConverter()
        .convert(timeFirst);
    final PythonBlocksConversion second = const PythonToBlocksConverter()
        .convert(pinFirst);

    expect(first.diagnostics, isEmpty);
    expect(second.diagnostics, isEmpty);
    expect(first.semanticFingerprint, second.semanticFingerprint);
  });

  test('semantic fingerprint preserves canonical NeoPixel round trips', () {
    const String original = '''
from neopixel import NeoPixel
from machine import Pin

strip = NeoPixel(Pin(48, Pin.OUT), 1)
strip[0] = (8, 16, 24)
strip.fill((0, 0, 0))
strip.write()
''';
    const String generated = '''
from machine import Pin
from neopixel import NeoPixel

strip = None

strip = NeoPixel(Pin(48, Pin.OUT, None), 1)
strip[0] = (8, 16, 24)
strip.fill((0, 0, 0))
strip.write()
''';

    final PythonBlocksConversion input = const PythonToBlocksConverter()
        .convert(original);
    final PythonBlocksConversion output = const PythonToBlocksConverter()
        .convert(generated, productionGenerated: true);

    expect(input.diagnostics, isEmpty);
    expect(output.diagnostics, isEmpty);
    expect(input.semanticFingerprint, isNotNull);
    expect(output.semanticFingerprint, input.semanticFingerprint);
  });

  group('A-38 named pins in the bounded importer', () {
    test('imports double- and single-quoted pin names as quoted-name '
        'blocks', () {
      final Map<String, dynamic> workspace = _workspaceOf('''
from machine import Pin

led = Pin("LED", Pin.OUT)
sensor = Pin('WL_GPIO0', Pin.IN)
led.value(1)
print(sensor.value())
''');
      final List<Map<String, dynamic>> pins = _objects(workspace)
          .where(
            (Map<String, dynamic> value) => value['type'] == 'pyble_gpio_pin',
          )
          .toList(growable: false);
      expect(pins, hasLength(2));
      expect(
        pins.map((Map<String, dynamic> value) => value['fields']),
        containsAll(<Map<String, Object?>>[
          <String, Object?>{'MODE': 'OUT', 'PULL': 'NONE'},
          <String, Object?>{'MODE': 'IN', 'PULL': 'NONE'},
        ]),
      );
      final List<Object?> names = pins
          .map((Map<String, dynamic> pin) {
            final Map<String, dynamic> gpio =
                ((pin['inputs']! as Map<String, dynamic>)['GPIO']!
                        as Map<String, dynamic>)['block']!
                    as Map<String, dynamic>;
            expect(
              gpio['type'],
              'text',
              reason:
                  'a named pin imports as the stock Blockly string literal '
                  'block, exactly the shape example materialization produces',
            );
            return (gpio['fields']! as Map<String, dynamic>)['TEXT'];
          })
          .toList(growable: false);
      expect(names, containsAll(<String>['LED', 'WL_GPIO0']));
    });

    const Map<String, String> rejectedNamedPins = <String, String>{
      'a space inside the name':
          'from machine import Pin\n\nled = Pin("led led", Pin.OUT)\n',
      'a leading digit':
          "from machine import Pin\n\nled = Pin('2x', Pin.OUT)\n",
      'an empty name': 'from machine import Pin\n\nled = Pin("", Pin.OUT)\n',
      'a seventeen-character name':
          'from machine import Pin\n\n'
          'led = Pin("ABCDEFGHIJKLMNOPQ", Pin.OUT)\n',
      'a digits-only string':
          'from machine import Pin\n\nled = Pin("2", Pin.OUT)\n',
      'a variable pin identity':
          'from machine import Pin\n\nx = 1\nled = Pin(x, Pin.OUT)\n',
      'a valid name next to an invalid one (all-or-nothing)':
          'from machine import Pin\n\n'
          'led = Pin("LED", Pin.OUT)\nbad = Pin("led led", Pin.OUT)\n',
    };
    for (final MapEntry<String, String> entry in rejectedNamedPins.entries) {
      test('rejects ${entry.key} without producing a workspace', () {
        final PythonBlocksConversion result = const PythonToBlocksConverter()
            .convert(entry.value);

        expect(result.workspaceJson, isNull);
        expect(result.hasErrors, isTrue);
        expect(result.diagnostics.first.code, 'invalid_gpio');
      });
    }

    test('semantic fingerprint preserves canonical named-pin round trips', () {
      const String original = '''
from machine import Pin

led = Pin("LED", Pin.OUT)
button = Pin(23, Pin.IN)
led.value(1)
print(button.value())
''';
      const String generated = '''
from machine import Pin

led = None
button = None

led = Pin('LED', Pin.OUT, None)
button = Pin(23, Pin.IN, None)
led.value(1)
print(button.value())
''';
      final PythonBlocksConversion input = const PythonToBlocksConverter()
          .convert(original);
      final PythonBlocksConversion output = const PythonToBlocksConverter()
          .convert(generated, productionGenerated: true);

      expect(input.diagnostics, isEmpty);
      expect(output.diagnostics, isEmpty);
      expect(input.semanticFingerprint, isNotNull);
      expect(output.semanticFingerprint, input.semanticFingerprint);
    });
  });
}

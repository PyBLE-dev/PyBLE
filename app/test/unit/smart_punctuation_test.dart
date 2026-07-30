// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.
//
// A-25 — typographic-substitution guard (specs.md FR-ERR, FR-EDIT).
//
// Regression cover for a failure reproduced on real hardware: a board file
// containing
//     b'print(\xe2\x80\x9cHello world\xe2\x80\x9d)'
// (U+201C / U+201D instead of ASCII ") makes MicroPython answer
//     File "<stdin>", line 1
//     SyntaxError: invalid syntax
// identically over USB serial and over BLE — the transport is irrelevant, the
// SOURCE TEXT is invalid. iPadOS Smart Punctuation produces this while typing,
// and PASTED code carries it in regardless of keyboard settings.

import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:pyble/editor/editor.dart';

void main() {
  group('A-25 findSmartPunctuation — makes the invisible visible', () {
    test('plain ASCII code reports nothing', () {
      expect(hasSmartPunctuation('print("Hello world!!")\n'), isFalse);
      expect(findSmartPunctuation('x = 5 - 2\n'), isEmpty);
    });

    test('detects the exact curly quotes that broke the bench board', () {
      const String broken = 'print(“Hello world!!”)';
      final List<SmartPunctuationHit> hits = findSmartPunctuation(broken);
      expect(hits.length, 2);
      expect(hits.first.offset, 6);
      expect(hits.first.codepoint, 'U+201C');
      expect(hits.last.codepoint, 'U+201D');
      expect(
        hits.every((SmartPunctuationHit h) => h.replacement == '"'),
        isTrue,
      );
    });

    test('detects curly single quotes, en/em dashes and minus sign', () {
      expect(findSmartPunctuation('a = ‘x’').length, 2);
      expect(findSmartPunctuation('x = 5 – 2').single.replacement, '-');
      expect(findSmartPunctuation('x = 5 — 2').single.replacement, '-');
      expect(findSmartPunctuation('x = 5 − 2').single.replacement, '-');
    });

    test('detects the INVISIBLE non-breaking space', () {
      const String sneaky = 'x = 1';
      expect(
        hasSmartPunctuation(sneaky),
        isTrue,
        reason: 'a non-breaking space is unreadable on screen but fatal',
      );
      expect(findSmartPunctuation(sneaky).single.codepoint, 'U+00A0');
    });
  });

  group('A-25 normalizeSmartPunctuation — converts to what the user meant', () {
    test('the bench-board failure becomes valid Python', () {
      expect(
        normalizeSmartPunctuation('print(“Hello world!!”)'),
        'print("Hello world!!")',
      );
    });

    test('a non-breaking space becomes a real space', () {
      expect(normalizeSmartPunctuation('x = 1'), 'x = 1');
    });

    test('ASCII source is returned untouched (identical instance)', () {
      const String clean = 'for i in range(3):\n    print(i)\n';
      expect(normalizeSmartPunctuation(clean), same(clean));
    });

    test('legitimate non-ASCII in strings and comments is PRESERVED', () {
      // Accents, non-Latin scripts and emoji are perfectly valid inside a
      // string literal — the guard must not touch them.
      const String src = 'print("café ไทย 🎉")  # naïve\n';
      expect(normalizeSmartPunctuation(src), src);
      expect(hasSmartPunctuation(src), isFalse);
    });

    test('mixed content converts only the offenders', () {
      // The curly quotes are the delimiters (code) -> fixed. The em dash is
      // inside a COMMENT -> the user's text, left alone.
      expect(
        normalizeSmartPunctuation('print(“café”)  # smart — dash'),
        'print("café")  # smart — dash',
      );
    });
  });

  // The distinction that separates "fixes your syntax" from "corrupts your
  // data". A general user must never have their printed output silently
  // rewritten to repair a problem that did not exist.
  group('A-25 code position vs data position', () {
    test('curly quotes used AS delimiters are fixed — both of them', () {
      expect(normalizeSmartPunctuation('print(“Hello”)'), 'print("Hello")');
      expect(normalizeSmartPunctuation('x = ‘abc’'), "x = 'abc'");
    });

    test('an em dash INSIDE a proper string literal is PRESERVED', () {
      const String src = 'print("a — b")';
      expect(
        normalizeSmartPunctuation(src),
        src,
        reason: 'it compiles and prints an em dash — it is the user data',
      );
      expect(
        hasSmartPunctuation(src),
        isFalse,
        reason: 'and it must not raise a warning banner either',
      );
    });

    test('a curly apostrophe inside a string is intentional text', () {
      const String src = 'print("it\'s fine")';
      expect(normalizeSmartPunctuation(src), src);
      const String curly = 'print("it’s fine")';
      expect(normalizeSmartPunctuation(curly), curly);
    });

    test('typography inside a COMMENT is left alone', () {
      const String src = '# cost — “high”\nx = 1\n';
      expect(normalizeSmartPunctuation(src), src);
      expect(hasSmartPunctuation(src), isFalse);
    });

    test('a dash in CODE position is still fixed', () {
      expect(normalizeSmartPunctuation('x = 5 – 2'), 'x = 5 - 2');
      expect(normalizeSmartPunctuation('x = 1'), 'x = 1');
    });

    test(
      'curly delimiters wrapping an em dash keep the dash, fix the quotes',
      () {
        expect(
          normalizeSmartPunctuation('print(“a — b”)'),
          'print("a — b")',
          reason: 'fix the syntax, keep the message exactly as written',
        );
      },
    );

    test('triple-quoted strings protect their contents', () {
      const String src = 'DOC = """\nuse — dashes “freely” here\n"""\n';
      expect(normalizeSmartPunctuation(src), src);
    });

    test('escaped quotes inside a string do not end it early', () {
      const String src = r'print("she said \"hi\" — loudly")';
      expect(normalizeSmartPunctuation(src), src);
    });

    test('the bench-board line is still fixed end to end', () {
      expect(
        normalizeSmartPunctuation('print(“Hello world!!”)\n'),
        'print("Hello world!!")\n',
      );
    });
  });

  group(
    'A-25 SmartPunctuationFormatter — the platform-independent guarantee',
    () {
      // smartQuotesType/smartDashesType are documented by Flutter as "This flag
      // only affects iOS", so they cannot be the guarantee. The formatter runs in
      // the editing pipeline on every platform and every input route.
      const SmartPunctuationFormatter fmt = SmartPunctuationFormatter();

      TextEditingValue typed(String text, {int? caret}) => TextEditingValue(
        text: text,
        selection: TextSelection.collapsed(offset: caret ?? text.length),
      );

      test('a typed curly quote is rewritten to ASCII immediately', () {
        final TextEditingValue out = fmt.formatEditUpdate(
          typed('print('),
          typed('print(“'),
        );
        expect(out.text, 'print("');
      });

      test('the caret does not move (every mapping is 1:1)', () {
        // Caret sits right after the offending character, mid-buffer.
        final TextEditingValue out = fmt.formatEditUpdate(
          typed('print()', caret: 6),
          typed('print(“)', caret: 7),
        );
        expect(out.text, 'print(")');
        expect(
          out.selection.baseOffset,
          7,
          reason: 'a moving caret while typing would be worse than the bug',
        );
      });

      test(
        'PASTED code is cleaned — the case no keyboard setting can cover',
        () {
          final TextEditingValue out = fmt.formatEditUpdate(
            typed(''),
            typed('print(“Hello world!!”)'),
          );
          expect(out.text, 'print("Hello world!!")');
          expect(hasSmartPunctuation(out.text), isFalse);
        },
      );

      test('an invisible non-breaking space is scrubbed', () {
        final TextEditingValue out = fmt.formatEditUpdate(
          typed(''),
          typed('x = 1'),
        );
        expect(out.text, 'x = 1');
        expect(out.text.codeUnits.contains(0x00A0), isFalse);
      });

      test('clean ASCII passes through untouched, same instance', () {
        final TextEditingValue v = typed('for i in range(3):\n    print(i)\n');
        expect(
          fmt.formatEditUpdate(typed(''), v),
          same(v),
          reason: 'no needless value churn on the common path',
        );
      });

      test('legitimate non-ASCII in a string literal survives', () {
        final TextEditingValue v = typed('print("café ไทย 🎉")');
        expect(fmt.formatEditUpdate(typed(''), v).text, 'print("café ไทย 🎉")');
      });

      test(
        'the exact bytes recovered from the bench board become valid Python',
        () {
          // /test.py read back over serial as:
          //   b'print(\xe2\x80\x9cHello world\xe2\x80\x9d)'
          const String fromBoard = 'print(“Hello world”)';
          expect(
            fmt.formatEditUpdate(typed(''), typed(fromBoard)).text,
            'print("Hello world")',
          );
        },
      );
    },
  );
}

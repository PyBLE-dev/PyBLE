// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

/// A-25 — typographic-substitution guard (specs.md FR-ERR, FR-EDIT).
///
/// On a tablet-first MicroPython IDE the single most common way to end up with
/// code that cannot compile is text that LOOKS right but is not ASCII:
///
///   * iPadOS/macOS **Smart Punctuation** rewrites `"` to `“ ”` and `--` to `—`
///     while typing (suppressed on our own fields, but a system-wide setting we
///     do not control on other surfaces);
///   * **pasted** code — from Notes, a web page, a chat message, a PDF — carries
///     the substitutions with it, and no keyboard setting can prevent that;
///   * a non-breaking space (`U+00A0`) is completely INVISIBLE and still makes
///     MicroPython answer `SyntaxError`.
///
/// The board's answer in every case is the same unhelpful line:
///
///     File "<stdin>", line 1
///     SyntaxError: invalid syntax
///
/// which points at a line the user can see nothing wrong with. This module makes
/// the invisible visible: [findSmartPunctuation] reports what is there, and
/// [normalizeSmartPunctuation] rewrites it to the ASCII a Python tokenizer
/// accepts. Detection is offered to the user as an explicit, reversible action —
/// user code is never silently rewritten (FR-ERR "annotate, never hide").
library;

import 'package:flutter/services.dart'
    show TextInputFormatter, TextEditingValue, TextSelection;

/// Typographic characters that break a Python tokenizer, mapped to the ASCII the
/// user meant. Deliberately conservative: only characters with an unambiguous
/// ASCII source that a text-substitution feature or a copy-paste actually
/// produces. Accented letters and non-Latin scripts are NOT here — they are
/// perfectly legal inside string literals and comments.
const Map<String, String> kSmartPunctuationMap = <String, String>{
  '“': '"', // “ left double quotation mark
  '”': '"', // ” right double quotation mark
  '„': '"', // „ double low-9 quotation mark
  '‘': "'", // ‘ left single quotation mark
  '’': "'", // ’ right single quotation mark (also the "apostrophe")
  '‚': "'", // ‚ single low-9 quotation mark
  '–': '-', // – en dash
  '—': '-', // — em dash
  '−': '-', // − minus sign
  ' ': ' ', // non-breaking space (INVISIBLE)
  ' ': ' ', // en space
  ' ': ' ', // em space
  '　': ' ', // ideographic space
};

/// One offending character found in a buffer.
class SmartPunctuationHit {
  const SmartPunctuationHit({
    required this.offset,
    required this.character,
    required this.replacement,
  });

  /// Index of the character within the buffer.
  final int offset;

  /// The offending character as it appears in the buffer.
  final String character;

  /// The ASCII this character should be.
  final String replacement;

  /// `U+201C` style codepoint label — a technical identifier, never localized
  /// (FR-I18N-4).
  String get codepoint =>
      'U+${character.runes.first.toRadixString(16).toUpperCase().padLeft(4, '0')}';
}

/// The result of scanning [source]: the corrected text plus what was corrected.
class SmartPunctuationScan {
  const SmartPunctuationScan({required this.text, required this.hits});

  /// [text] with only the CODE-BREAKING characters rewritten.
  final String text;

  /// The characters that were rewritten, in order.
  final List<SmartPunctuationHit> hits;

  /// Whether anything needed correcting.
  bool get isClean => hits.isEmpty;
}

/// Scans Python [source] and rewrites ONLY the typographic characters that
/// actually break the tokenizer.
///
/// The distinction matters, and getting it wrong corrupts user data:
///
///   * `print(“hi”)`  — the curly quotes ARE meant to be the delimiters. There
///     is no string here at all, so this cannot compile → rewrite to `"`.
///   * `print("a — b")` — the em dash is INSIDE a proper string literal. It is
///     the user's data, it compiles perfectly, and it prints an em dash →
///     leave it alone. A blunt rewrite would silently change their output.
///   * `# cost — high` — inside a comment nothing is parsed → leave it alone.
///   * `print("it’s")` — a curly apostrophe inside a string is intentional text.
///
/// So the rule is: correct what is in CODE position, preserve what is DATA.
///
/// When a curly quote is used as a delimiter, its partner is corrected too —
/// otherwise rewriting only the opener would leave the string unterminated and
/// produce a *different* SyntaxError, which would be worse than the original.
SmartPunctuationScan scanSmartPunctuation(String source) {
  final StringBuffer out = StringBuffer();
  final List<SmartPunctuationHit> hits = <SmartPunctuationHit>[];

  // Delimiter of the string literal we are inside, or null in code position.
  String? delim; // '"' | "'" | '"""' | "'''"
  // True when the enclosing string was OPENED by a curly quote, so its closing
  // partner is also a curly quote that must be corrected.
  bool curlyDelimited = false;
  bool inComment = false;

  void fix(int i, String ch) {
    final String ascii = kSmartPunctuationMap[ch]!;
    hits.add(SmartPunctuationHit(offset: i, character: ch, replacement: ascii));
    out.write(ascii);
  }

  int i = 0;
  while (i < source.length) {
    final String ch = source[i];

    if (inComment) {
      if (ch == '\n') inComment = false;
      out.write(ch);
      i++;
      continue;
    }

    if (delim != null) {
      // Inside a string literal: everything is the user's DATA…
      if (ch == r'\') {
        out.write(ch);
        if (i + 1 < source.length) out.write(source[i + 1]);
        i += 2;
        continue;
      }
      // …except the closing delimiter, which may be a curly partner.
      if (curlyDelimited &&
          (ch == '“' || ch == '”' || ch == '‘' || ch == '’')) {
        final bool doubleQ = ch == '“' || ch == '”';
        if ((doubleQ && delim == '"') || (!doubleQ && delim == "'")) {
          fix(i, ch);
          delim = null;
          curlyDelimited = false;
          i++;
          continue;
        }
      }
      if (source.startsWith(delim, i)) {
        out.write(delim);
        i += delim.length;
        delim = null;
        curlyDelimited = false;
        continue;
      }
      out.write(ch);
      i++;
      continue;
    }

    // --- code position -------------------------------------------------------
    if (ch == '#') {
      inComment = true;
      out.write(ch);
      i++;
      continue;
    }
    if (ch == '"' || ch == "'") {
      final String triple = ch * 3;
      if (source.startsWith(triple, i)) {
        delim = triple;
        out.write(triple);
        i += 3;
      } else {
        delim = ch;
        out.write(ch);
        i++;
      }
      continue;
    }
    if (ch == '“' || ch == '”' || ch == '„') {
      fix(i, ch); // becomes an ASCII " and OPENS a string
      delim = '"';
      curlyDelimited = true;
      i++;
      continue;
    }
    if (ch == '‘' || ch == '’' || ch == '‚') {
      fix(i, ch);
      delim = "'";
      curlyDelimited = true;
      i++;
      continue;
    }
    if (kSmartPunctuationMap.containsKey(ch)) {
      fix(i, ch); // a dash or an invisible space sitting in code
      i++;
      continue;
    }
    out.write(ch);
    i++;
  }

  return SmartPunctuationScan(text: out.toString(), hits: hits);
}

/// Every CODE-BREAKING typographic character in [source], in order.
///
/// Characters inside string literals and comments are the user's data and are
/// deliberately NOT reported — the warning must not nag about a legitimate em
/// dash in a printed message.
List<SmartPunctuationHit> findSmartPunctuation(String source) =>
    scanSmartPunctuation(source).hits;

/// Whether [source] contains a character that would break the tokenizer.
bool hasSmartPunctuation(String source) {
  // Cheap reject first: most buffers are pure ASCII and never need the scan.
  bool candidate = false;
  for (int i = 0; i < source.length; i++) {
    if (kSmartPunctuationMap.containsKey(source[i])) {
      candidate = true;
      break;
    }
  }
  return candidate && scanSmartPunctuation(source).hits.isNotEmpty;
}

/// [source] with only the code-breaking typographic characters rewritten.
///
/// Data is preserved: accents, emoji, non-Latin text, and typographic
/// punctuation INSIDE string literals or comments are all left untouched.
String normalizeSmartPunctuation(String source) {
  bool candidate = false;
  for (int i = 0; i < source.length; i++) {
    if (kSmartPunctuationMap.containsKey(source[i])) {
      candidate = true;
      break;
    }
  }
  if (!candidate) return source;
  final SmartPunctuationScan scan = scanSmartPunctuation(source);
  return scan.isClean ? source : scan.text;
}

/// Rewrites typographic substitutions to ASCII **as the user types or pastes**.
///
/// Why this exists rather than relying on `smartQuotesType`/`smartDashesType`:
/// Flutter documents those as *"This flag only affects iOS."* They are a HINT to
/// one platform's text-input traits, so they do nothing on Android, macOS,
/// Windows, Linux or web, and they never apply to text that arrives by PASTE,
/// dictation, or an external keyboard's own substitution. Relying on them makes
/// correctness a platform accident.
///
/// A formatter runs inside the editing pipeline on EVERY value change, on every
/// platform, for every input route — so the buffer simply cannot hold a
/// character the MicroPython tokenizer would reject. Enforce the invariant;
/// don't ask the OS nicely.
///
/// Offsets are preserved exactly: every entry in [kSmartPunctuationMap] is a
/// one-character-to-one-character mapping, so the cursor never jumps while
/// typing. The guard below keeps that true even if the table is extended later.
class SmartPunctuationFormatter extends TextInputFormatter {
  const SmartPunctuationFormatter();

  @override
  TextEditingValue formatEditUpdate(
    TextEditingValue oldValue,
    TextEditingValue newValue,
  ) {
    final String fixed = normalizeSmartPunctuation(newValue.text);
    if (fixed == newValue.text) return newValue;

    if (fixed.length == newValue.text.length) {
      // Length-invariant: selection AND the IME composing region stay valid, so
      // neither the caret nor an in-flight composition is disturbed.
      return TextEditingValue(
        text: fixed,
        selection: newValue.selection,
        composing: newValue.composing,
      );
    }

    // Defensive: a future non-1:1 mapping would invalidate the offsets, so fall
    // back to a collapsed caret at the end rather than corrupting the selection.
    return TextEditingValue(
      text: fixed,
      selection: TextSelection.collapsed(offset: fixed.length),
    );
  }
}

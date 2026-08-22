#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
#
# X-12 — LOCALE-PARITY gate (BLD-5, CON-9, FR-I18N-1..4, NFR-A11Y-1/2).
#
# en ships day-one and every locale ships at parity (no partial translation).
# This merge-blocking gate mechanically enforces the localization framework's
# three invariants over the app package:
#
#   1. KEY PARITY — every non-en `lib/localization/arb/app_*.arb` MUST carry
#      EXACTLY en's key set. FAIL on any MISSING key (an incomplete locale must
#      not ship, NFR-A11Y-2) OR any ORPHAN key (a key absent from en). The
#      comparison ignores `@@locale` and `@key` description/placeholder metadata.
#
#   2. TECHNICAL IDENTIFIER — technical identifiers (esp32 / esp32-s3 /
#      esp32-c3, filesystem paths, PBLE/1 opcode / capability / status names)
#      stay ASCII and are NEVER localized (FR-I18N-4 / NFR-A11Y-4). A reserved
#      token present in an en VALUE MUST appear verbatim in every other locale's
#      value for that key.
#
#   3. HARD-CODED TEXT — a display-string literal in `lib/**` (a `Text()`
#      positional string, or a `tooltip:` / `title:` / `label:` / `content:`
#      string literal) that is NOT sourced from `AppLocalizations` is a FAIL
#      (FR-I18N-3). Bare technical identifiers (esp32*, `/paths`) and
#      `{placeholder}`-only strings are allowlisted so they do not false-positive.
#
# En keys referenced by no widget (dead keys) are REPORTED (never fatal), and
# only once the shell has begun sourcing text from AppLocalizations — before the
# migration lands every key is trivially unreferenced, so the note is suppressed.
#
#   Usage:  locale_parity.sh [APP_DIR]     (APP_DIR defaults to <repo>/app)
#   Exit:   non-zero (and names each offender) on any violation; 0 if the tree
#           is clean. Fails closed (exit 2) if python3 is unavailable.
#
# The ARB analysis is done in python3 (robust JSON: nested @key metadata and ICU
# `{chip}` placeholders parse correctly where a line/brace scanner would not).
# python3 is already a repo build dependency (ESP-IDF, the firmware host tests,
# and the shared conformance corpus all require it).

set -u

HERE="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
REPO_ROOT="$(cd "$HERE/../.." && pwd)"
APP_DIR="${1:-$REPO_ROOT/app}"

if ! command -v python3 >/dev/null 2>&1; then
  echo "locale-parity gate: python3 is required but was not found on PATH" >&2
  exit 2
fi

python3 - "$APP_DIR" <<'PY'
import glob
import json
import os
import re
import sys

app_dir = sys.argv[1]
arb_dir = os.path.join(app_dir, "lib", "localization", "arb")
lib_dir = os.path.join(app_dir, "lib")

# Reserved ASCII technical tokens that must render verbatim (FR-I18N-4). Longer
# chip variants come first so the specific form is detected before its prefix.
RESERVED_TOKENS = ["esp32-s3", "esp32-c3", "esp32", "PBLE/1"]

violations = []  # fatal — each drives a non-zero exit
notes = []       # informational — never affects the exit code


def load_arb(path):
    """Top-level user keys->values; drops @@locale and @-prefixed metadata."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return {
        k: v
        for k, v in data.items()
        if k != "@@locale" and not k.startswith("@")
    }


# --- Collect the ARB bundles (locale is the app_<locale>.arb infix). ---
arbs = {}
for path in sorted(glob.glob(os.path.join(arb_dir, "app_*.arb"))):
    locale = os.path.basename(path)[len("app_"):-len(".arb")]
    try:
        arbs[locale] = load_arb(path)
    except (OSError, ValueError) as exc:
        violations.append("ARB PARSE: %s is not valid ARB/JSON (%s)" % (path, exc))

en = arbs.get("en", {})
en_keys = set(en.keys())

# --- Rule 1: KEY PARITY (every non-en locale == en's key set). ---
for locale in sorted(arbs):
    if locale == "en":
        continue
    keys = set(arbs[locale].keys())
    for k in sorted(en_keys - keys):
        violations.append(
            "KEY PARITY: locale '%s' is MISSING key '%s' (present in en) — a "
            "partial translation must not ship (NFR-A11Y-2)" % (locale, k)
        )
    for k in sorted(keys - en_keys):
        violations.append(
            "KEY PARITY: locale '%s' has ORPHAN key '%s' (absent from en) — "
            "FR-I18N-2" % (locale, k)
        )


def reserved_in(value):
    if not isinstance(value, str):
        return []
    return [tok for tok in RESERVED_TOKENS if tok in value]


# --- Rule 2: TECHNICAL IDENTIFIER (reserved tokens survive into every locale). ---
for key, en_val in en.items():
    tokens = reserved_in(en_val)
    if not tokens:
        continue
    for locale in sorted(arbs):
        if locale == "en" or key not in arbs[locale]:
            continue  # a missing key is already a KEY PARITY violation
        other = arbs[locale][key]
        for tok in tokens:
            if not isinstance(other, str) or tok not in other:
                violations.append(
                    "TECHNICAL IDENTIFIER: locale '%s' key '%s' drops the "
                    "reserved token '%s' — technical identifiers stay ASCII and "
                    "are rendered verbatim (FR-I18N-4)" % (locale, key, tok)
                )

# --- Rule 3: HARD-CODED TEXT over lib/** (display literal not from ARB). ---
# Matches a Text() positional string, or a tooltip/title/label/content string
# literal, and captures the literal body so the technical-identifier allowlist
# can spare bare identifiers. A variable/AppLocalizations argument has no leading
# quote and therefore never matches (that is the sanctioned path, FR-I18N-3).
LITERAL = re.compile(
    r"""(?:Text\(\s*|(?:tooltip|title|label|content)\s*:\s*)"""
    r"""r?(?P<q>['"])(?P<body>(?:\\.|(?!(?P=q)).)*)(?P=q)"""
)


def is_allowlisted(body):
    s = body.strip()
    if s == "":
        return True  # an empty string is never display copy
    if s.startswith("/"):
        return True  # a filesystem path (technical identifier)
    if s in RESERVED_TOKENS or re.fullmatch(r"esp32(-s3|-c3)?", s):
        return True  # a bare chip / protocol identifier
    if re.fullmatch(r"\{[A-Za-z_][A-Za-z0-9_]*\}", s):
        return True  # a lone ICU placeholder, not literal copy
    if re.fullmatch(r"%[0-9]+", s):
        return True  # a Blockly message placeholder, not display copy
    if re.fullmatch(
        r"(?:\$[A-Za-z_][A-Za-z0-9_]*|\$\{[^}]+\}|[\s.,:;!?()\-/–—])+",
        s,
    ):
        return True  # localized/interpolated values joined only by punctuation
    return False


if os.path.isdir(lib_dir):
    for root, dirs, files in os.walk(lib_dir):
        dirs[:] = [d for d in dirs if os.path.join(root, d) !=
                   os.path.join(lib_dir, "localization", "gen")]
        for name in sorted(files):
            if not name.endswith(".dart"):
                continue
            fpath = os.path.join(root, name)
            rel = os.path.relpath(fpath, app_dir)
            with open(fpath, encoding="utf-8", errors="replace") as f:
                for lineno, raw in enumerate(f, start=1):
                    line = raw.rstrip("\n")
                    if line.lstrip().startswith("//"):
                        continue  # skip full-line comments (incl. the SPDX header)
                    for m in LITERAL.finditer(line):
                        if is_allowlisted(m.group("body")):
                            continue
                        violations.append(
                            "HARD-CODED TEXT: %s:%d has a display literal "
                            "\"%s\" not sourced from AppLocalizations (FR-I18N-3)"
                            % (rel, lineno, m.group("body"))
                        )

# --- Dead-key report (non-fatal; only after the shell starts using ARB). ---
if os.path.isdir(lib_dir) and en_keys:
    used = set()
    migration_started = False
    for root, dirs, files in os.walk(lib_dir):
        dirs[:] = [d for d in dirs if os.path.join(root, d) !=
                   os.path.join(lib_dir, "localization", "gen")]
        for name in files:
            if not name.endswith(".dart"):
                continue
            with open(os.path.join(root, name), encoding="utf-8",
                      errors="replace") as f:
                src = f.read()
            if "AppLocalizations" in src:
                migration_started = True
            for k in en_keys:
                if re.search(r"\.%s\b" % re.escape(k), src):
                    used.add(k)
    if migration_started:
        for k in sorted(en_keys - used):
            notes.append(
                "note: en key '%s' is referenced by no widget in lib/** "
                "(dead key?)" % k
            )

for n in notes:
    print(n)

if violations:
    for v in violations:
        print(v, file=sys.stderr)
    print(
        "locale-parity gate: %d violation(s) — fix: keep every non-en ARB at en "
        "key parity (no missing/orphan keys), keep technical identifiers "
        "ASCII/verbatim (FR-I18N-4), and source lib/** display text from "
        "AppLocalizations (FR-I18N-3)." % len(violations),
        file=sys.stderr,
    )
    sys.exit(1)

print("locale-parity gate: clean (ARB key parity + technical-identifier + "
      "hard-coded-text over lib/**)")
sys.exit(0)
PY

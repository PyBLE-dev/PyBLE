#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
#
# X-02 — No-leak CI gate (CON-6, PRD 1A.2/16.3). The canonical AGENTS.md gate:
# a push is rejected if a forbidden proprietary identifier appears in shippable
# source. Scans <ROOT>/{app,firmware,protocol,examples,tests,tools} for the
# forbidden regex in .dart/.c/.h/.py files, plus PyBLE-authored Blockly and
# public-site source. Governance docs that quote the tokens to forbid them
# (.md and this .sh), pinned upstream/vendor trees, web dependencies, and
# generated web output are exempt.
#
#   Usage:  no_leak.sh [ROOT]     (ROOT defaults to the repo root)
#   Exit:   non-zero if any forbidden token is found; 0 if clean.
#
# CLEAN-ROOM: the forbidden regex is ASSEMBLED from harmless fragments so this
# gate file itself contains no contiguous forbidden literal (the AGENTS.md gate
# only scans code extensions, but we keep every tracked file literal-free).

set -u

HERE="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
ROOT="${1:-$(cd "$HERE/../.." && pwd)}"

# Adjacent quoted fragments concatenate at runtime; no contiguous prohibited
# identifier is committed in this source.
FORBIDDEN='slp''/1|slp_[a-z]|titra''lab|micro''pad'

SCAN_DIRS="app firmware protocol examples tests tools"

scan_dirs=()
for d in $SCAN_DIRS; do
  [ -d "$ROOT/$d" ] && scan_dirs+=("$ROOT/$d")
done

# Nothing to scan -> vacuously clean.
if [ "${#scan_dirs[@]}" -eq 0 ]; then
  exit 0
fi

# Reads a NUL-delimited file list from stdin, prints every matching
# file:line:text record, and returns non-zero when at least one hit exists.
scan_forbidden_files() {
  local file line
  local found=0
  while IFS= read -r -d '' file; do
    if grep -qiE "$FORBIDDEN" -- "$file" 2>/dev/null; then
      while IFS= read -r line; do
        printf '%s:%s\n' "$file" "$line" >&2
      done < <(grep -niE "$FORBIDDEN" -- "$file" 2>/dev/null)
      found=1
    fi
  done
  return "$found"
}

# Prune only reviewed third-party/generated paths. In particular, the Blockly
# exception is the exact bundled asset subtree; a different directory merely
# named "vendor" remains authored source and MUST stay in scope.
if ! scan_forbidden_files < <(
  find "${scan_dirs[@]}" \
    \( -path '*/upstream' \
       -o -path '*/.esp-idf' \
       -o -path "$ROOT/firmware/.arm-gnu" \
       -o -path '*/build' \
       -o -path '*/__pycache__' \
       -o -path '*/managed_components' \
       -o -path '*/.git' \
       -o -path "$ROOT/tools/web/node_modules" \
       -o -path "$ROOT/tools/web/.next" \
       -o -path "$ROOT/tools/web/out" \
       -o -path "$ROOT/tools/web/.open-next" \
       -o -path "$ROOT/tools/web/.wrangler" \
       -o -path "$ROOT/tools/web/.vercel" \
       -o -path "$ROOT/tools/web/.turbo" \
       -o -path "$ROOT/tools/web/coverage" \
       -o -path "$ROOT/tools/web/dist" \
       -o -path "$ROOT/tools/web/playwright-report" \
       -o -path "$ROOT/tools/web/test-results" \
       -o -path "$ROOT/app/assets/blockly/vendor" \) -prune \
    -o -type f \
       \( -name '*.dart' -o -name '*.c' -o -name '*.h' -o -name '*.py' \) \
       -print0
); then
  echo "no-leak gate: forbidden proprietary token found in shippable source" >&2
  exit 1
fi

BLOCKLY_ASSETS="$ROOT/app/assets/blockly"
if [ -d "$BLOCKLY_ASSETS" ]; then
  if ! scan_forbidden_files < <(
    find "$BLOCKLY_ASSETS" \
      \( -path "$BLOCKLY_ASSETS/vendor" \
         -o -path "$BLOCKLY_ASSETS/upstream" \
         -o -path '*/.git' \) -prune \
      -o -type f \
         \( -name '*.js' -o -name '*.html' -o -name '*.css' \
            -o -name '*.json' \) \
         -print0
  ); then
    echo "no-leak gate: forbidden proprietary token found in authored Blockly assets" >&2
    exit 1
  fi
fi

WEB_SOURCE="$ROOT/tools/web"
if [ -d "$WEB_SOURCE" ]; then
  if ! scan_forbidden_files < <(
    find "$WEB_SOURCE" \
      \( -path "$WEB_SOURCE/node_modules" \
         -o -path "$WEB_SOURCE/.next" \
         -o -path "$WEB_SOURCE/out" \
         -o -path "$WEB_SOURCE/.open-next" \
         -o -path "$WEB_SOURCE/.wrangler" \
         -o -path "$WEB_SOURCE/.vercel" \
         -o -path "$WEB_SOURCE/.turbo" \
         -o -path "$WEB_SOURCE/coverage" \
         -o -path "$WEB_SOURCE/dist" \
         -o -path "$WEB_SOURCE/playwright-report" \
         -o -path "$WEB_SOURCE/test-results" \
         -o -path '*/.git' \) -prune \
      -o -type f \
         \( -name '*.ts' -o -name '*.tsx' -o -name '*.js' \
            -o -name '*.jsx' -o -name '*.mjs' -o -name '*.cjs' \
            -o -name '*.css' -o -name '*.html' -o -name '*.json' \
            -o -name '*.svg' -o -name '*.mdx' \) \
         ! -name 'package-lock.json' \
         ! -name 'next-env.d.ts' \
         -print0
  ); then
    echo "no-leak gate: forbidden proprietary token found in authored website source" >&2
    exit 1
  fi
fi

echo "no-leak gate: clean (no forbidden proprietary identifiers in authored source)"
exit 0

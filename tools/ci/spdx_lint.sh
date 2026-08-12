#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
#
# X-01 / NFR-MAINT-4 — SPDX-MIT header lint. Every PyBLE source file must carry
# an `SPDX-License-Identifier: MIT` header. Scans .py/.c/.h/.dart/.sh under ROOT
# plus comment-capable PyBLE-authored Blockly and public-site source (default
# repo root), skipping vendored/dependency/generated trees. Names every
# offender.
#
#   Usage:  spdx_lint.sh [ROOT]
#   Exit:   0 iff every scanned source file carries the header; non-zero (and
#           prints each offender) otherwise.

set -u

HERE="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
ROOT="${1:-$(cd "$HERE/../.." && pwd)}"

# When ROOT is a git work tree, skip files git would not track. This drops
# generated/gitignored artifacts that are NOT authored source (e.g. Flutter's
# GeneratedPluginRegistrant.*, ios/Flutter/flutter_export_environment.sh, the
# ios ephemeral tree) so a local working-tree run matches CI, which checks out
# tracked files only. Tracked source with no header still fails (not weakened).
GIT_WORKTREE=0
git -C "$ROOT" rev-parse --is-inside-work-tree >/dev/null 2>&1 && GIT_WORKTREE=1

miss=0
while IFS= read -r f; do
  if [ "$GIT_WORKTREE" -eq 1 ] && git -C "$ROOT" check-ignore -q -- "$f"; then
    continue
  fi
  if ! grep -q 'SPDX-License-Identifier: MIT' "$f"; then
    printf 'spdx_lint: missing SPDX-License-Identifier: MIT — %s\n' "$f" >&2
    miss=1
  fi
done < <(find "$ROOT" \
            \( -path '*/.git' \
               -o -path '*/build' \
               -o -path '*/upstream' \
               -o -path '*/app/assets/blockly/vendor' \
               -o -path '*/firmware/.esp-idf' \
               -o -path '*/.esp-idf' \
               -o -path "$ROOT/firmware/.arm-gnu" \
               -o -path '*/.idf_tools' \
               -o -path '*/.claude' \
               -o -path '*/docs' \
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
            \) -prune -o \
            -type f \( -name '*.py' -o -name '*.c' -o -name '*.h' \
                       -o -name '*.dart' -o -name '*.sh' \) -print)

BLOCKLY_ASSETS="$ROOT/app/assets/blockly"
if [ -d "$BLOCKLY_ASSETS" ]; then
  while IFS= read -r f; do
    if [ "$GIT_WORKTREE" -eq 1 ] && git -C "$ROOT" check-ignore -q -- "$f"; then
      continue
    fi
    if ! grep -q 'SPDX-License-Identifier: MIT' "$f"; then
      printf 'spdx_lint: missing SPDX-License-Identifier: MIT — %s\n' "$f" >&2
      miss=1
    fi
  done < <(find "$BLOCKLY_ASSETS" \
              \( -path "$BLOCKLY_ASSETS/vendor" \
                 -o -path "$BLOCKLY_ASSETS/upstream" \
                 -o -path '*/.git' \
              \) -prune -o \
              -type f \( -name '*.js' -o -name '*.html' -o -name '*.css' \
                         -o -name '*.json' \) -print)
fi

WEB_SOURCE="$ROOT/tools/web"
if [ -d "$WEB_SOURCE" ]; then
  while IFS= read -r f; do
    if [ "$GIT_WORKTREE" -eq 1 ] && git -C "$ROOT" check-ignore -q -- "$f"; then
      continue
    fi
    if ! grep -q 'SPDX-License-Identifier: MIT' "$f"; then
      printf 'spdx_lint: missing SPDX-License-Identifier: MIT — %s\n' "$f" >&2
      miss=1
    fi
  done < <(find "$WEB_SOURCE" \
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
                 -o -path '*/.git' \
              \) -prune -o \
              -type f \( -name '*.ts' -o -name '*.tsx' -o -name '*.js' \
                         -o -name '*.jsx' -o -name '*.mjs' -o -name '*.cjs' \
                         -o -name '*.css' -o -name '*.html' \
                         -o -name '*.svg' -o -name '*.mdx' \) \
              ! -name 'next-env.d.ts' \
              -print)
fi

if [ "$miss" -ne 0 ]; then
  echo "spdx_lint: one or more source files are missing the SPDX-MIT header" >&2
  exit 1
fi

echo "spdx_lint: all scanned source files carry SPDX-License-Identifier: MIT"
exit 0

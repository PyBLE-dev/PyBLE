#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
#
# X-03 — Build all three chips (BLD-3, CON-11) from the single pin. Thin driver
# over build.sh for esp32 / esp32-s3 / esp32-c3.
#
#   build_all.sh            real build of all three targets (stops on first fail).
#   build_all.sh --plan     dry-run plan for all three (no ESP-IDF required).

set -eu

HERE="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
REPO_ROOT="$(cd "$HERE/../.." && pwd)"
BUILD="$HERE/build.sh"
FW="$REPO_ROOT/firmware"

TARGETS="esp32 esp32-s3 esp32-c3"
BUILD_ROOT="${PYBLE_BUILD_ROOT:-$FW/build}"
CANONICAL_UPSTREAM="${PYBLE_CANONICAL_UPSTREAM_DIR:-$FW/upstream/micropython}"
LOCK="${PYBLE_LOCK_FILE:-$FW/versions.lock}"

PLAN=""
if [ "${1:-}" = "--plan" ]; then
  PLAN="--plan"
fi

PYBLE_SOURCE_COMMIT="$(git -C "$REPO_ROOT" rev-parse HEAD 2>/dev/null || true)"
case "$PYBLE_SOURCE_COMMIT" in
  *[!0-9a-f]*) echo "build_all: cannot resolve one full PyBLE source commit" >&2; exit 1 ;;
esac
[ "${#PYBLE_SOURCE_COMMIT}" -eq 40 ] || {
  echo "build_all: cannot resolve one full PyBLE source commit" >&2
  exit 1
}
SOURCE_DATE_EPOCH="$(git -C "$REPO_ROOT" show -s --format=%ct "$PYBLE_SOURCE_COMMIT" 2>/dev/null || true)"
case "$SOURCE_DATE_EPOCH" in
  ""|*[!0-9]*) echo "build_all: cannot resolve source commit time" >&2; exit 1 ;;
esac
export PYBLE_SOURCE_COMMIT SOURCE_DATE_EPOCH

lock_value() {
  section="$1"
  key="$2"
  awk -F'"' -v wanted="[$section]" -v wanted_key="$key" '
    /^\[/ { active = ($0 == wanted) }
    active {
      line = $0
      sub(/^[[:space:]]*/, "", line)
      if (index(line, wanted_key) == 1 &&
          substr(line, length(wanted_key) + 1) ~ /^[[:space:]]*=/) {
        print $2
        exit
      }
    }
  ' "$LOCK"
}

assert_source_state() {
  current="$(git -C "$REPO_ROOT" rev-parse HEAD 2>/dev/null || true)"
  if [ "$current" != "$PYBLE_SOURCE_COMMIT" ]; then
    echo "build_all: PyBLE HEAD changed during the build matrix" >&2
    return 1
  fi
  status="$(git -C "$REPO_ROOT" status --porcelain \
    --untracked-files=normal --ignore-submodules=untracked 2>/dev/null || true)"
  if [ -n "$status" ]; then
    echo "build_all: PyBLE source tree is not clean:" >&2
    printf '%s\n' "$status" >&2
    return 1
  fi
}

assert_git_identity() {
  checkout="$1"
  label="$2"

  if [ -L "$checkout" ] || [ ! -d "$checkout" ] || [ ! -e "$checkout/.git" ]; then
    echo "build_all: $label checkout is missing, symlinked, or not Git: $checkout" >&2
    return 1
  fi
  checkout_head="$(git -C "$checkout" rev-parse HEAD 2>/dev/null || true)"
  if [ "$checkout_head" != "$MICROPYTHON_COMMIT" ]; then
    echo "build_all: $label checkout HEAD differs from versions.lock" >&2
    return 1
  fi
  checkout_origin="$(git -C "$checkout" remote get-url origin 2>/dev/null || true)"
  if [ "$checkout_origin" != "$MICROPYTHON_REPO" ]; then
    echo "build_all: $label checkout origin differs from versions.lock" >&2
    return 1
  fi
  if ! tracked_status="$(git -C "$checkout" status --porcelain \
    --untracked-files=no --ignore-submodules=untracked 2>/dev/null)"
  then
    echo "build_all: cannot inspect tracked state for $label checkout" >&2
    return 1
  fi
  if [ -n "$tracked_status" ]; then
    echo "build_all: $label checkout has tracked source changes:" >&2
    printf '%s\n' "$tracked_status" >&2
    return 1
  fi
}

initialize_local_submodule() {
  checkout="$1"
  submodule_path="$2"

  # A minimal test or future upstream may not declare one of today's library
  # submodules. Only initialize paths that are actual gitlinks in this pin.
  gitlink="$(git -C "$CANONICAL_UPSTREAM" ls-files --stage -- "$submodule_path" \
    2>/dev/null | awk '$1 == "160000" { print $2; exit }')"
  [ -n "$gitlink" ] || return 0

  submodule_name="$(git -C "$CANONICAL_UPSTREAM" config -f .gitmodules \
    --get-regexp '^submodule\..*\.path$' 2>/dev/null |
    awk -v wanted="$submodule_path" '
      $2 == wanted {
        name = $1
        sub(/^submodule\./, "", name)
        sub(/\.path$/, "", name)
        print name
        exit
      }
    ')"
  if [ -z "$submodule_name" ]; then
    echo "build_all: $submodule_path is a gitlink without .gitmodules ownership" >&2
    return 1
  fi

  canonical_submodule="$CANONICAL_UPSTREAM/$submodule_path"
  if [ -L "$canonical_submodule" ] || [ ! -e "$canonical_submodule/.git" ]; then
    echo "build_all: canonical $submodule_path submodule is not initialized" >&2
    return 1
  fi
  canonical_submodule_head="$(
    git -C "$canonical_submodule" rev-parse HEAD 2>/dev/null || true
  )"
  if [ "$canonical_submodule_head" != "$gitlink" ]; then
    echo "build_all: canonical $submodule_path submodule differs from its gitlink" >&2
    return 1
  fi

  if ! git -C "$checkout" \
    -c protocol.file.allow=always \
    -c "submodule.$submodule_name.url=$canonical_submodule" \
    submodule update --quiet --init --no-fetch -- "$submodule_path"
  then
    echo "build_all: could not initialize local $submodule_path for $checkout" >&2
    return 1
  fi
}

provision_target_checkout() {
  target="$1"
  checkout="$SOURCES_ROOT/$target/micropython"

  # Never reuse potentially mutated build input, even when it looks valid.
  if [ -e "$checkout" ] || [ -L "$checkout" ]; then
    echo "build_all: refusing pre-existing target source checkout: $checkout" >&2
    return 1
  fi
  mkdir -p "$SOURCES_ROOT/$target"
  if ! git clone --quiet --no-hardlinks --no-checkout \
    "$CANONICAL_UPSTREAM" "$checkout"
  then
    echo "build_all: local MicroPython clone failed for $target" >&2
    return 1
  fi
  if ! git -C "$checkout" checkout --quiet --detach "$MICROPYTHON_COMMIT"; then
    echo "build_all: pinned MicroPython checkout failed for $target" >&2
    return 1
  fi
  git -C "$checkout" remote set-url origin "$MICROPYTHON_REPO"

  initialize_local_submodule "$checkout" "lib/berkeley-db-1.xx" || return 1
  initialize_local_submodule "$checkout" "lib/micropython-lib" || return 1
  assert_git_identity "$checkout" "$target retained" || return 1
}

assert_retained_checkouts() {
  for retained_target in $PROVISIONED_TARGETS; do
    retained="$SOURCES_ROOT/$retained_target/micropython"
    assert_git_identity "$retained" "$retained_target retained" || return 1
  done
}

# A plan is diagnostic and remains usable from a development worktree. A real
# all-profile build is release input and therefore starts from one clean state.
if [ -z "$PLAN" ]; then
  assert_source_state

  [ -f "$LOCK" ] || {
    echo "build_all: versions.lock not found at $LOCK" >&2
    exit 1
  }
  MICROPYTHON_COMMIT="$(lock_value micropython commit)"
  MICROPYTHON_REPO="$(lock_value micropython repo)"
  case "$MICROPYTHON_COMMIT" in
    *[!0-9a-f]*) echo "build_all: invalid MicroPython commit pin" >&2; exit 1 ;;
  esac
  [ "${#MICROPYTHON_COMMIT}" -eq 40 ] || {
    echo "build_all: invalid MicroPython commit pin" >&2
    exit 1
  }
  [ -n "$MICROPYTHON_REPO" ] || {
    echo "build_all: missing MicroPython repository pin" >&2
    exit 1
  }
  assert_git_identity "$CANONICAL_UPSTREAM" "canonical MicroPython" || exit 1

  # Resolve the retained root once to the physical spelling CMake and the
  # compiler will record (important when the host aliases /var to /private/var).
  mkdir -p "$BUILD_ROOT"
  BUILD_ROOT="$(cd "$BUILD_ROOT" && pwd -P)"
  SOURCES_ROOT="$BUILD_ROOT/.sources"
  for t in $TARGETS; do
    destination="$SOURCES_ROOT/$t/micropython"
    if [ -e "$destination" ] || [ -L "$destination" ]; then
      echo "build_all: refusing pre-existing target source checkout: $destination" >&2
      exit 1
    fi
  done
  PROVISIONED_TARGETS=""
  for t in $TARGETS; do
    provision_target_checkout "$t" || exit 1
    PROVISIONED_TARGETS="$PROVISIONED_TARGETS $t"
  done
  assert_retained_checkouts || exit 1
fi

rc=0
for t in $TARGETS; do
  echo "== build_all: $t =="
  if [ -n "$PLAN" ]; then
    "$BUILD" --plan "$t" || rc=1
  else
    target_upstream="$SOURCES_ROOT/$t/micropython"
    PYBLE_BUILD_ROOT="$BUILD_ROOT" \
      PYBLE_UPSTREAM_DIR="$target_upstream" \
      "$BUILD" "$t" ||
      { rc=1; echo "build_all: $t FAILED" >&2; break; }
    assert_source_state || { rc=1; echo "build_all: source changed while building $t" >&2; break; }
    assert_git_identity "$CANONICAL_UPSTREAM" "canonical MicroPython" ||
      { rc=1; echo "build_all: canonical source changed while building $t" >&2; break; }
    assert_retained_checkouts ||
      { rc=1; echo "build_all: retained source changed while building $t" >&2; break; }
  fi
done

if [ "$rc" -ne 0 ]; then
  echo "build_all: one or more targets did not complete" >&2
  exit 1
fi
echo "build_all: all three targets ($TARGETS) completed"
exit 0

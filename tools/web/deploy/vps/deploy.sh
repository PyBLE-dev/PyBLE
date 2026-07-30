#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.

set -Eeuo pipefail

if [[ $# -ne 1 ]]; then
    printf 'Usage: %s <ssh-target>\n' "$0" >&2
    printf 'Example: %s root@vps.example\n' "$0" >&2
    exit 64
fi

readonly deploy_target=$1
readonly script_directory=$(
    cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
    pwd
)
readonly web_directory=$(
    cd -- "${script_directory}/../.."
    pwd
)
readonly repository_root=$(git -C "${web_directory}" rev-parse --show-toplevel)
staged_firmware_root=
firmware_evidence_root=
upload_evidence_root=
firmware_version=
firmware_tag=
firmware_provenance_commit=
local_firmware_tag_object_before_build=

cleanup_firmware_evidence() {
    if [[ -n "${firmware_evidence_root}" && -d "${firmware_evidence_root}" ]]; then
        chmod -R u+w -- "${firmware_evidence_root}" 2>/dev/null || true
        rm -rf -- "${firmware_evidence_root}"
    fi
    firmware_evidence_root=
}
cleanup_upload_evidence() {
    if [[ -n "${upload_evidence_root}" && -d "${upload_evidence_root}" ]]; then
        chmod -R u+w -- "${upload_evidence_root}" 2>/dev/null || true
        rm -rf -- "${upload_evidence_root}"
    fi
    upload_evidence_root=
}
cleanup_deployment_evidence() {
    cleanup_firmware_evidence
    cleanup_upload_evidence
}
trap cleanup_deployment_evidence EXIT

if [[ -n $(find "${web_directory}" \
    -mindepth 1 \
    -maxdepth 1 \
    -name '.env*' \
    -print \
    -quit) ]]; then
    printf 'Refusing deployment: tools/web/.env* nodes can inject unreviewed Next build inputs.\n' >&2
    exit 65
fi

if [[ -n ${PYBLE_FLASH_SELECTION_FILE:-} ]]; then
    printf 'Refusing deployment: PYBLE_FLASH_SELECTION_FILE is derived only from verified staging.\n' >&2
    exit 65
fi
unset PYBLE_FLASH_SELECTION_FILE

if [[ -n $(git -C "${repository_root}" status --porcelain --untracked-files=all --ignore-submodules=untracked) ]]; then
    printf 'Refusing to deploy: the complete source tree has uncommitted changes.\n' >&2
    exit 65
fi
readonly commit=$(git -C "${repository_root}" rev-parse HEAD)

verify_firmware_tree_parity() {
    local expected_tree=$1
    local actual_tree=$2
    local parity_label=$3

    if ! diff --recursive --brief --no-dereference \
        "${expected_tree}" "${actual_tree}" >/dev/null; then
        printf 'Refusing deployment: %s differs from trusted firmware staging.\n' \
            "${parity_label}" >&2
        exit 65
    fi
}

verify_local_firmware_tag() {
    local expected_tag_object=${1:-}
    local tag_ref="refs/tags/${firmware_tag}"
    local tag_object=
    local tag_type=
    local tag_name=
    local peeled_commit=

    if ! tag_object=$(
        git -C "${repository_root}" show-ref --verify --hash "${tag_ref}"
    ); then
        printf 'Refusing public firmware activation: local annotated tag %s is missing.\n' \
            "${firmware_tag}" >&2
        return 65
    fi
    if [[ ! "${tag_object}" =~ ^[0-9a-f]{40}$ ]]; then
        printf 'Refusing public firmware activation: local tag object is invalid.\n' >&2
        return 65
    fi
    tag_type=$(git -C "${repository_root}" cat-file -t "${tag_object}")
    if [[ "${tag_type}" != "tag" ]]; then
        printf 'Refusing public firmware activation: %s must be an annotated tag.\n' \
            "${firmware_tag}" >&2
        return 65
    fi
    tag_name=$(
        git -C "${repository_root}" for-each-ref \
            --format='%(tag)' "${tag_ref}"
    )
    if [[ "${tag_name}" != "${firmware_tag}" ]]; then
        printf 'Refusing public firmware activation: annotated tag name mismatch.\n' >&2
        return 65
    fi
    peeled_commit=$(
        git -C "${repository_root}" rev-parse --verify "${tag_object}^{commit}"
    )
    if [[ "${peeled_commit}" != "${firmware_provenance_commit}" ]]; then
        printf 'Refusing public firmware activation: release provenance and annotated tag differ.\n' >&2
        return 65
    fi
    if [[ -n "${expected_tag_object}" &&
        "${tag_object}" != "${expected_tag_object}" ]]; then
        printf 'Refusing public firmware activation: local annotated tag changed during deployment.\n' >&2
        return 65
    fi
    printf '%s\n' "${tag_object}"
}

if [[ -n ${PYBLE_FIRMWARE_STAGED_ROOT:-} ]]; then
    if [[ -z ${PYBLE_FIRMWARE_LICENSE_EVIDENCE_DIR:-} ]]; then
        printf 'Refusing public firmware activation: PYBLE_FIRMWARE_LICENSE_EVIDENCE_DIR is required.\n' >&2
        exit 65
    fi
    if [[ -z ${PYBLE_FIRMWARE_LICENSE_BUILD_ROOT:-} ]]; then
        printf 'Refusing public firmware activation: PYBLE_FIRMWARE_LICENSE_BUILD_ROOT is required.\n' >&2
        exit 65
    fi

    staged_firmware_root=$(
        cd -- "${PYBLE_FIRMWARE_STAGED_ROOT}"
        pwd -P
    )
    staged_selection="${staged_firmware_root}/.pyble-firmware-release-selection.json"
    test -f "${staged_selection}"
    test -d "${staged_firmware_root}/firmware"
    PYBLE_FIRMWARE_STAGED_ROOT="${staged_firmware_root}" \
        node "${web_directory}/scripts/stage-firmware-release.js" \
        --verify-staged
    node -e '
      const { readFileSync } = require("node:fs");
      const descriptor = JSON.parse(readFileSync(process.argv[1], "utf8"));
      if (descriptor.deployment !== "public" || descriptor.hilStatus !== "passed") {
        throw new Error("The public VPS accepts only an all-HIL-passed public release");
      }
    ' "${staged_selection}"

    firmware_version=$(
        node -e '
          const { readFileSync } = require("node:fs");
          const descriptor = JSON.parse(readFileSync(process.argv[1], "utf8"));
          process.stdout.write(descriptor.version);
        ' "${staged_selection}"
    )
    firmware_tag="firmware-v${firmware_version}"
    staged_release_bundle="${staged_firmware_root}/firmware/v${firmware_version}"
    firmware_provenance_commit=$(
        node -e '
          const { readFileSync } = require("node:fs");
          const release = JSON.parse(readFileSync(process.argv[1], "utf8"));
          const commit = release?.provenance?.pyble?.commit;
          if (typeof commit !== "string" || !/^[0-9a-f]{40}$/.test(commit)) {
            throw new Error("release.json provenance.pyble.commit is invalid");
          }
          process.stdout.write(commit);
        ' "${staged_release_bundle}/release.json"
    )
    local_firmware_tag_object_before_build=$(verify_local_firmware_tag)

    firmware_evidence_root=$(mktemp -d)
    chmod 0700 "${firmware_evidence_root}"
    trusted_firmware_snapshot="${firmware_evidence_root}/trusted-staged"
    mkdir -m 0700 -- "${trusted_firmware_snapshot}"
    cp -a -- "${staged_firmware_root}/." "${trusted_firmware_snapshot}/"
    verify_firmware_tree_parity \
        "${staged_firmware_root}" \
        "${trusted_firmware_snapshot}" \
        "trusted local firmware snapshot"
    PYBLE_FIRMWARE_STAGED_ROOT="${trusted_firmware_snapshot}" \
        node "${web_directory}/scripts/stage-firmware-release.js" \
        --verify-staged

    staged_firmware_root="${trusted_firmware_snapshot}"
    staged_selection="${staged_firmware_root}/.pyble-firmware-release-selection.json"
    export PYBLE_FIRMWARE_STAGED_ROOT="${staged_firmware_root}"
    export PYBLE_FLASH_SELECTION_FILE="${staged_selection}"
fi
readonly release_timestamp=$(date -u +%Y%m%dT%H%M%SZ)
readonly release_name="${release_timestamp}-${commit:0:12}"
readonly release_root=/srv/pyble/releases
readonly incoming_release="${release_root}/.${release_name}.incoming"
readonly final_release="${release_root}/${release_name}"
readonly current_release=/srv/pyble/current
readonly firmware_root=/srv/pyble/firmware
readonly firmware_publish_lock=/srv/pyble/.firmware-publish.lock
readonly activation_watchdog_unit="pyble-activation-${release_name}"
readonly activation_confirmation="/srv/pyble/.${release_name}.confirmed"

cd -- "${web_directory}"
if [[ -z "${staged_firmware_root}" ]]; then
    rm -rf -- out/firmware
fi
npm ci
NEXT_TELEMETRY_DISABLED=1 npm run check

readonly commit_after_build=$(git -C "${repository_root}" rev-parse HEAD)
if [[ "${commit_after_build}" != "${commit}" ]]; then
    printf 'Refusing deployment: source HEAD changed during the website build.\n' >&2
    exit 65
fi
if [[ -n $(git -C "${repository_root}" status --porcelain --untracked-files=all --ignore-submodules=untracked) ]]; then
    printf 'Refusing deployment: the source tree changed during the website build.\n' >&2
    exit 65
fi

test ! -e out/firmware
if [[ -n "${staged_firmware_root}" ]]; then
    cp -R "${staged_firmware_root}/firmware" out/
    PYBLE_FIRMWARE_STAGED_ROOT="${staged_firmware_root}" \
        node "${web_directory}/scripts/stage-firmware-release.js" \
        --verify-staged
    verify_firmware_tree_parity \
        "${staged_firmware_root}/firmware" \
        "${web_directory}/out/firmware" \
        "packaged website firmware"
    readonly local_firmware_tag_object_after_build=$(
        verify_local_firmware_tag "${local_firmware_tag_object_before_build}"
    )
fi
for firmware_release in out/firmware/v*; do
    if [[ ! -d "${firmware_release}" ]]; then
        continue
    fi
    test -f "${firmware_release}/release.json"
    test -f "${firmware_release}/SHA256SUMS"
    (
        cd -- "${firmware_release}"
        shasum --algorithm 256 --check SHA256SUMS
    )
done

readonly final_source_commit=$(git -C "${repository_root}" rev-parse HEAD)
if [[ "${final_source_commit}" != "${commit}" ]]; then
    printf 'Refusing deployment: source HEAD changed before upload.\n' >&2
    exit 65
fi
if [[ -n $(git -C "${repository_root}" status --porcelain --untracked-files=all --ignore-submodules=untracked) ]]; then
    printf 'Refusing deployment: the source tree changed before upload.\n' >&2
    exit 65
fi
readonly source_commit_marker=.pyble-source-commit
test ! -e "out/${source_commit_marker}"
install -m 0644 /dev/null "out/${source_commit_marker}"
printf '%s\n' "${commit}" > "out/${source_commit_marker}"

if [[ -n "${staged_firmware_root}" ]]; then
    PYBLE_FIRMWARE_STAGED_ROOT="${staged_firmware_root}" \
        node "${web_directory}/scripts/stage-firmware-release.js" \
        --verify-staged
    verify_firmware_tree_parity \
        "${staged_firmware_root}/firmware" \
        "${web_directory}/out/firmware" \
        "final packaged website firmware"
    readonly local_firmware_tag_object_before_upload=$(
        verify_local_firmware_tag "${local_firmware_tag_object_after_build}"
    )
fi
upload_evidence_root=$(mktemp -d)
chmod 0700 "${upload_evidence_root}"
readonly upload_snapshot_candidate="${upload_evidence_root}/site"
mkdir -m 0700 -- "${upload_snapshot_candidate}"
cp -a -- out/. "${upload_snapshot_candidate}/"
readonly trusted_upload_snapshot="${upload_snapshot_candidate}"
if ! diff --recursive --brief --no-dereference \
    out "${trusted_upload_snapshot}" >/dev/null; then
    printf 'Refusing deployment: private upload snapshot differs from final verified output.\n' >&2
    exit 65
fi
if [[ -n "${staged_firmware_root}" ]]; then
    verify_firmware_tree_parity \
        "${staged_firmware_root}/firmware" \
        "${trusted_upload_snapshot}/firmware" \
        "trusted upload snapshot firmware"
fi
readonly trusted_site_inventory_name=.pyble-site-inventory.sha256
readonly trusted_site_inventory="${trusted_upload_snapshot}/${trusted_site_inventory_name}"
python3 - \
    "${trusted_upload_snapshot}" \
    "${trusted_site_inventory}" <<'PYTHON'
from __future__ import annotations

import hashlib
from pathlib import Path
import re
import stat
import sys

root = Path(sys.argv[1])
inventory = Path(sys.argv[2])
safe_path = re.compile(r"[A-Za-z0-9._/-]+")
records: list[tuple[str, str]] = []

for candidate in sorted(root.rglob("*"), key=lambda path: path.as_posix()):
    metadata = candidate.lstat()
    relative = candidate.relative_to(root).as_posix()
    if not safe_path.fullmatch(relative):
        raise SystemExit(f"unsafe upload snapshot path: {relative!r}")
    if stat.S_ISDIR(metadata.st_mode):
        continue
    if not stat.S_ISREG(metadata.st_mode):
        raise SystemExit(f"upload snapshot contains a non-regular node: {relative}")
    if candidate == inventory:
        raise SystemExit("trusted inventory already exists in upload snapshot")
    digest = hashlib.sha256()
    with candidate.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    records.append((relative, digest.hexdigest()))

if not records:
    raise SystemExit("upload snapshot is empty")
with inventory.open("x", encoding="ascii", newline="\n") as output:
    for relative, digest in records:
        output.write(f"{digest}  ./{relative}\n")
PYTHON
readonly trusted_site_inventory_digest=$(
    shasum --algorithm 256 -- "${trusted_site_inventory}" |
        awk '{ print $1 }'
)
if [[ ! "${trusted_site_inventory_digest}" =~ ^[0-9a-f]{64}$ ]]; then
    printf 'Refusing deployment: trusted site inventory digest is invalid.\n' >&2
    exit 65
fi
(
    cd -- "${trusted_upload_snapshot}"
    shasum --algorithm 256 --check "${trusted_site_inventory_name}" >/dev/null
)
find "${trusted_upload_snapshot}" -type d -exec chmod 0500 {} +
find "${trusted_upload_snapshot}" -type f -exec chmod 0400 {} +

ssh -o BatchMode=yes "${deploy_target}" \
    "install -d -m 0755 '${release_root}' '${firmware_root}' && install -d -m 0755 '${incoming_release}'"

rsync \
    --archive \
    --delete \
    --no-owner \
    --no-group \
    -- \
    "${trusted_upload_snapshot}/" \
    "${deploy_target}:${incoming_release}/"

previous_release=$(
ssh -o BatchMode=yes "${deploy_target}" bash -s -- \
    "${incoming_release}" \
    "${final_release}" \
    "${current_release}" \
    "${firmware_root}" \
    "${firmware_publish_lock}" \
    "${release_name}" \
    "${activation_watchdog_unit}" \
    "${activation_confirmation}" \
    "${commit}" \
    "${trusted_site_inventory_name}" \
    "${trusted_site_inventory_digest}" <<'REMOTE'
set -Eeuo pipefail

readonly incoming_release=$1
readonly final_release=$2
readonly current_release=$3
readonly firmware_root=$4
readonly firmware_publish_lock=$5
readonly release_name=$6
readonly activation_watchdog_unit=$7
readonly activation_confirmation=$8
readonly expected_source_commit=$9
readonly trusted_site_inventory_name=${10}
readonly expected_trusted_site_inventory_digest=${11}
readonly trusted_site_inventory="${incoming_release}/${trusted_site_inventory_name}"
readonly next_link="${current_release}.next"
readonly release_root=$(dirname -- "${final_release}")

test -L "${current_release}"
previous_release=$(readlink -f -- "${current_release}")
if [[ "${previous_release}" != "${release_root}/"* ]]; then
    printf 'Current release is outside the managed release root: %s\n' \
        "${previous_release}" >&2
    exit 68
fi
test -d "${previous_release}"

activation_started=0
watchdog_armed=0
disarm_activation_watchdog() {
    systemctl stop "${activation_watchdog_unit}.timer" >/dev/null 2>&1 || true
    systemctl stop "${activation_watchdog_unit}.service" >/dev/null 2>&1 || true
    systemctl reset-failed "${activation_watchdog_unit}.service" \
        >/dev/null 2>&1 || true
    rm -f -- "${activation_confirmation}"
    watchdog_armed=0
}
rollback_activation() {
    local activation_status=$?
    if [[ "${activation_status}" -eq 0 ]]; then
        activation_status=70
    fi
    trap - ERR HUP INT TERM
    if [[ "${activation_started}" -eq 1 ]]; then
        printf 'Activation failed; restoring %s.\n' "${previous_release}" >&2
        local restore_link="${current_release}.restore"
        rm -f -- "${restore_link}"
        ln -s -- "${previous_release}" "${restore_link}"
        mv -Tf -- "${restore_link}" "${current_release}"
        if ! systemctl reload nginx; then
            printf 'CRITICAL: Nginx reload failed while restoring %s.\n' \
                "${previous_release}" >&2
        fi
    fi
    if [[ "${watchdog_armed}" -eq 1 ]]; then
        disarm_activation_watchdog
    fi
    exit "${activation_status}"
}
trap rollback_activation ERR HUP INT TERM

if [[ -n $(find "${incoming_release}" \
    -mindepth 1 \
    ! -type d \
    ! -type f \
    -print \
    -quit) ]]; then
    printf 'Incoming website contains a non-regular filesystem node.\n' >&2
    exit 69
fi
test -f "${trusted_site_inventory}"
actual_trusted_site_inventory_digest=$(
    sha256sum "${trusted_site_inventory}" |
        awk '{ print $1 }'
)
if [[ "${actual_trusted_site_inventory_digest}" != \
    "${expected_trusted_site_inventory_digest}" ]]; then
    printf 'Trusted site inventory digest mismatch before activation.\n' >&2
    exit 69
fi

remote_inventory_check_root=$(mktemp -d)
cleanup_remote_inventory_check() {
    rm -rf -- "${remote_inventory_check_root}"
}
trap cleanup_remote_inventory_check EXIT
readonly actual_site_file_list="${remote_inventory_check_root}/actual"
readonly expected_site_file_list="${remote_inventory_check_root}/expected"
(
    cd -- "${incoming_release}"
    find . -type f -print |
        LC_ALL=C sort > "${actual_site_file_list}"
    sed -E 's/^[0-9a-f]{64}  //' \
        "${trusted_site_inventory_name}" > "${expected_site_file_list}"
    printf './%s\n' "${trusted_site_inventory_name}" >> \
        "${expected_site_file_list}"
    LC_ALL=C sort -o "${expected_site_file_list}" \
        "${expected_site_file_list}"
    diff --unified "${expected_site_file_list}" "${actual_site_file_list}"
    sha256sum --check "${trusted_site_inventory_name}" >/dev/null
)
cleanup_remote_inventory_check
trap - EXIT

chown -R root:root "${incoming_release}"
find "${incoming_release}" -type d -exec chmod 0755 {} +
find "${incoming_release}" -type f -exec chmod 0644 {} +

for required_file in \
    index.html \
    404.html \
    privacy.html \
    support.html \
    flash.html \
    robots.txt \
    sitemap.xml \
    manifest.webmanifest \
    .pyble-source-commit \
    WEBSITE_THIRD_PARTY_LICENSES.txt; do
    test -f "${incoming_release}/${required_file}"
done
test "$(cat "${incoming_release}/.pyble-source-commit")" = \
    "${expected_source_commit}"

for firmware_release in "${incoming_release}"/firmware/v*; do
    if [[ ! -d "${firmware_release}" ]]; then
        continue
    fi
    test -f "${firmware_release}/release.json"
    test -f "${firmware_release}/SHA256SUMS"
    (
        cd -- "${firmware_release}"
        sha256sum --check SHA256SUMS >/dev/null
    )
done

exec 9>"${firmware_publish_lock}"
flock --exclusive 9
for firmware_release in "${incoming_release}"/firmware/v*; do
    if [[ ! -d "${firmware_release}" ]]; then
        continue
    fi
    if [[ -n $(find "${firmware_release}" -type l -print -quit) ]]; then
        printf 'Firmware release contains a symbolic link: %s\n' \
            "${firmware_release}" >&2
        exit 69
    fi
    firmware_name=$(basename -- "${firmware_release}")
    if [[ ! "${firmware_name}" =~ ^v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(-(0|[1-9][0-9]*|[0-9]*[A-Za-z-][0-9A-Za-z-]*)(\.(0|[1-9][0-9]*|[0-9]*[A-Za-z-][0-9A-Za-z-]*))*)?(\+[0-9A-Za-z-]+(\.[0-9A-Za-z-]+)*)?$ ]]; then
        printf 'Invalid immutable firmware version directory: %s\n' \
            "${firmware_name}" >&2
        exit 69
    fi
    published_firmware_release="${firmware_root}/${firmware_name}"
    if [[ -e "${published_firmware_release}" ]]; then
        if [[ -L "${published_firmware_release}" || ! -d "${published_firmware_release}" ]]; then
            printf 'Immutable firmware path is not an ordinary directory: %s\n' \
                "${published_firmware_release}" >&2
            exit 69
        fi
        (
            cd -- "${published_firmware_release}"
            sha256sum --check SHA256SUMS >/dev/null
        )
        if ! diff --recursive --brief --no-dereference \
            "${firmware_release}" "${published_firmware_release}" >/dev/null; then
            printf 'Refusing divergent reuse of immutable firmware %s.\n' \
                "${firmware_name}" >&2
            exit 69
        fi
        continue
    fi

    firmware_publish_incoming="/srv/pyble/.${firmware_name}.${release_name}.incoming"
    test ! -e "${firmware_publish_incoming}"
    if ! cp -a -- "${firmware_release}" "${firmware_publish_incoming}"; then
        rm -rf -- "${firmware_publish_incoming}"
        exit 69
    fi
    if ! diff --recursive --brief --no-dereference \
        "${firmware_release}" "${firmware_publish_incoming}" >/dev/null; then
        rm -rf -- "${firmware_publish_incoming}"
        printf 'Immutable firmware copy changed before publication: %s\n' \
            "${firmware_name}" >&2
        exit 69
    fi
    mv -- "${firmware_publish_incoming}" "${published_firmware_release}"
done

test ! -e "${final_release}"
nginx -t

mv -- "${incoming_release}" "${final_release}"
rm -f -- "${next_link}"
ln -s -- "${final_release}" "${next_link}"

# Arm a transport-independent rollback before switching current. The transient
# timer remains live after this SSH process exits and restores the prior release
# unless the caller records successful production smoke and cancels it.
rm -f -- "${activation_confirmation}"
watchdog_armed=1
systemd-run --quiet --collect --expand-environment=no \
    --unit="${activation_watchdog_unit}" \
    --on-active=15min \
    /bin/bash -c '
set -Eeuo pipefail

readonly confirmation=$1
readonly previous_release=$2
readonly expected_release=$3
readonly current_release=$4

for ((guard_attempt = 0; guard_attempt < 60; guard_attempt += 1)); do
    if [[ ! -e "${confirmation}" ]]; then
        break
    fi
    sleep 1
done
test -d "${previous_release}"
if [[ ! -L "${current_release}" ]]; then
    exit 0
fi
current_target=$(readlink -f -- "${current_release}")
if [[ "${current_target}" != "${expected_release}" ]]; then
    exit 0
fi

printf "Activation watchdog restoring %s after missing confirmation.\n" \
    "${previous_release}" >&2
readonly restore_link="${current_release}.watchdog-restore"
rm -f -- "${restore_link}"
ln -s -- "${previous_release}" "${restore_link}"
mv -Tf -- "${restore_link}" "${current_release}"
nginx -t
systemctl reload nginx
' pyble-activation-watchdog \
    "${activation_confirmation}" \
    "${previous_release}" \
    "${final_release}" \
    "${current_release}"

activation_started=1
mv -Tf -- "${next_link}" "${current_release}"

systemctl reload nginx
printf '%s\n' "${previous_release}"
activation_started=0
trap - ERR HUP INT TERM
REMOTE
)
readonly previous_release

if [[ -n "${staged_firmware_root}" ]]; then
    cleanup_firmware_evidence
fi

rollback_release() {
    ssh -o BatchMode=yes "${deploy_target}" bash -s -- \
        "${previous_release}" \
        "${final_release}" \
        "${current_release}" \
        "${activation_watchdog_unit}" \
        "${activation_confirmation}" <<'REMOTE'
set -euo pipefail

readonly previous_release=$1
readonly final_release=$2
readonly current_release=$3
readonly activation_watchdog_unit=$4
readonly activation_confirmation=$5
readonly restore_link="${current_release}.restore"

test -d "${previous_release}"
test -L "${current_release}"
current_target=$(readlink -f -- "${current_release}")
if [[ "${current_target}" != "${final_release}" && "${current_target}" != "${previous_release}" ]]; then
    printf 'Refusing rollback over a different current release: %s\n' \
        "${current_target}" >&2
    exit 71
fi
if [[ "${current_target}" == "${final_release}" ]]; then
    rm -f -- "${restore_link}"
    ln -s -- "${previous_release}" "${restore_link}"
    mv -Tf -- "${restore_link}" "${current_release}"
fi
nginx -t
systemctl reload nginx
systemctl stop "${activation_watchdog_unit}.timer" >/dev/null 2>&1 || true
systemctl stop "${activation_watchdog_unit}.service" >/dev/null 2>&1 || true
systemctl reset-failed "${activation_watchdog_unit}.service" \
    >/dev/null 2>&1 || true
rm -f -- "${activation_confirmation}"
REMOTE
}

confirm_activation() {
    ssh -o BatchMode=yes "${deploy_target}" bash -s -- \
        "${final_release}" \
        "${current_release}" \
        "${previous_release}" \
        "${activation_watchdog_unit}" \
        "${activation_confirmation}" <<'REMOTE'
set -Eeuo pipefail

readonly final_release=$1
readonly current_release=$2
readonly previous_release=$3
readonly activation_watchdog_unit=$4
readonly activation_confirmation=$5
readonly activation_confirmation_unit="${activation_watchdog_unit}-confirmation"

# The confirmation transaction is owned by systemd, so loss of this SSH
# transport cannot interrupt watchdog cancellation halfway through.
systemd-run --quiet --wait --collect --expand-environment=no \
    --unit="${activation_confirmation_unit}" \
    /bin/bash -c '
set -Eeuo pipefail

readonly final_release=$1
readonly current_release=$2
readonly previous_release=$3
readonly activation_watchdog_unit=$4
readonly activation_confirmation=$5

trap "rm -f -- \"\${activation_confirmation}\"" ERR
trap "rm -f -- \"\${activation_confirmation}\"; exit 73" HUP INT TERM
test -d "${previous_release}"
test -L "${current_release}"
test "$(readlink -f -- "${current_release}")" = "${final_release}"
install -m 0600 /dev/null "${activation_confirmation}"
systemctl stop "${activation_watchdog_unit}.service"
systemctl stop "${activation_watchdog_unit}.timer"
watchdog_timer_state=$(
    systemctl show --property=ActiveState --value "${activation_watchdog_unit}.timer"
)
watchdog_service_state=$(
    systemctl show --property=ActiveState --value "${activation_watchdog_unit}.service"
)
test "${watchdog_timer_state}" = inactive
test "${watchdog_service_state}" = inactive
test "$(readlink -f -- "${current_release}")" = "${final_release}"
rm -f -- "${activation_confirmation}"
trap - ERR HUP INT TERM
' pyble-activation-confirmation \
    "${final_release}" \
    "${current_release}" \
    "${previous_release}" \
    "${activation_watchdog_unit}" \
    "${activation_confirmation}"

test "$(readlink -f -- "${current_release}")" = "${final_release}"
printf 'Activation confirmed after production smoke.\n'
REMOTE
}

rollback_on_smoke_error() {
    readonly smoke_status=$?
    trap - ERR
    printf 'Post-activation smoke failed; restoring %s.\n' \
        "${previous_release}" >&2
    if ! rollback_release; then
        printf 'CRITICAL: automatic rollback failed; inspect %s immediately.\n' \
            "${current_release}" >&2
    fi
    exit "${smoke_status}"
}
trap rollback_on_smoke_error ERR

smoke_root=$(mktemp -d)
cleanup_smoke() {
    rm -rf -- "${smoke_root}"
    cleanup_deployment_evidence
}
trap cleanup_smoke EXIT

for route in / /privacy /support /flash; do
    case "${route}" in
        /) route_file=index.html ;;
        /privacy) route_file=privacy.html ;;
        /support) route_file=support.html ;;
        /flash) route_file=flash.html ;;
    esac
    route_body="${smoke_root}/${route_file}"
    route_headers="${smoke_root}/${route_file}.headers"
    curl --fail --silent --show-error --max-time 30 \
        --location --max-redirs 0 --proto '=https' \
        --dump-header "${route_headers}" \
        --output "${route_body}" \
        "https://pyble.dev${route}"
    cmp -- "out/${route_file}" "${route_body}"
    grep -Fq 'id="main-content"' "${route_body}"
    normalized_headers="${route_headers}.normalized"
    tr -d '\r' < "${route_headers}" > "${normalized_headers}"
    grep -Eiq "^Content-Security-Policy: .*default-src 'self'" \
        "${normalized_headers}"
    grep -Eiq '^Cache-Control: *no-cache, *no-transform *$' \
        "${normalized_headers}"
done

for firmware_release in out/firmware/v*; do
    if [[ ! -d "${firmware_release}" ]]; then
        continue
    fi
    firmware_version=${firmware_release#out/firmware/v}
    public_release="${smoke_root}/v${firmware_version}"
    mkdir -p -- "${public_release}"

    curl --fail --silent --show-error --max-time 30 \
        --location --max-redirs 0 --proto '=https' \
        "https://pyble.dev/firmware/v${firmware_version}/SHA256SUMS" \
        --output "${public_release}/SHA256SUMS"
    cmp -- \
        "${firmware_release}/SHA256SUMS" \
        "${public_release}/SHA256SUMS"

    while IFS= read -r checksum_line; do
        if [[ -z "${checksum_line}" ]]; then
            continue
        fi
        firmware_path=${checksum_line#*  }
        if [[ "${firmware_path}" == "${checksum_line}" ]]; then
            printf 'Invalid firmware checksum entry: %s\n' \
                "${checksum_line}" >&2
            exit 67
        fi
        case "${firmware_path}" in
            ""|/*|*\\*|*..*)
                printf 'Unsafe firmware checksum path: %s\n' \
                    "${firmware_path}" >&2
                exit 67
                ;;
        esac
        mkdir -p -- "$(dirname -- "${public_release}/${firmware_path}")"
        curl --fail --silent --show-error --max-time 30 \
            --location --max-redirs 0 --proto '=https' \
            "https://pyble.dev/firmware/v${firmware_version}/${firmware_path}" \
            --output "${public_release}/${firmware_path}"
    done < "${firmware_release}/SHA256SUMS"

    (
        cd -- "${public_release}"
        shasum --algorithm 256 --check SHA256SUMS
    )
done

readonly not_found_status=$(
    curl --silent --show-error --max-time 30 \
        --output /dev/null \
        --write-out '%{http_code}' \
        https://pyble.dev/not-found-smoke
)

if [[ "${not_found_status}" != 404 ]]; then
    printf 'Public 404 smoke failed: expected 404, received %s.\n' \
        "${not_found_status}" >&2
    exit 66
fi

confirm_activation
trap - ERR
printf 'Deployed %s (%s) to %s.\n' \
    "${release_name}" \
    "${commit}" \
    "${deploy_target}"

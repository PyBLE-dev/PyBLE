#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.

set -euo pipefail

validation_output=
if ! validation_output=$(nginx -t 2>&1); then
    printf '%s\n' "${validation_output}" >&2
    exit 1
fi

systemctl reload nginx

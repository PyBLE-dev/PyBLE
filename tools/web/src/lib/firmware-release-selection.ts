// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import {
  hasExactFirmwareProfileDescriptors,
  type FirmwareReleaseDescriptor,
} from "@/lib/firmware-release";

// The public source tree deliberately selects no release. A qualified public
// descriptor is reviewed and added only after both final-byte HIL rows
// pass. Protected candidates are supplied explicitly at build time by the
// external staging workflow; they are never selected by browser state.
export const selectedFirmwareRelease: FirmwareReleaseDescriptor | null = null;

export function firmwareReleaseSelectedAtBuild(): FirmwareReleaseDescriptor | null {
  const selectionFile = process.env.PYBLE_FLASH_SELECTION_FILE;
  if (!selectionFile) {
    return selectedFirmwareRelease;
  }

  const parsed: unknown = JSON.parse(
    readFileSync(resolve(selectionFile), "utf8"),
  );
  if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
    throw new Error("Build-selected firmware descriptor must be an object");
  }
  const descriptor = parsed as FirmwareReleaseDescriptor;
  if (
    descriptor.deployment !== "public" &&
    descriptor.deployment !== "candidate"
  ) {
    throw new Error(
      "Build-selected firmware descriptor has an invalid deployment mode",
    );
  }
  if (
    typeof descriptor.version !== "string" ||
    !hasExactFirmwareProfileDescriptors(descriptor.version, descriptor.profiles)
  ) {
    throw new Error(
      "Build-selected firmware descriptor must contain exactly the two current release profiles",
    );
  }
  if (
    descriptor.deployment === "candidate" &&
    descriptor.accessControlled !== true
  ) {
    throw new Error(
      "Build-selected candidate firmware must be access-controlled",
    );
  }
  if (descriptor.deployment === "public" && descriptor.hilStatus !== "passed") {
    throw new Error(
      "Build-selected public firmware must have passed all hardware validation",
    );
  }
  return descriptor;
}

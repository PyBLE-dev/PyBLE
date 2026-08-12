// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

import { lstatSync, readFileSync, realpathSync } from "node:fs";
import { dirname, join, resolve } from "node:path";

import {
  hasExactFirmwareProfileDescriptors,
  hasExactHistoricalFirmwareProfileDescriptors,
  isExactPublicBetaFirmwareRelease,
  releaseIncludesWaveshareLcd147b,
  type FirmwareReleaseDescriptor,
} from "@/lib/firmware-release";
import {
  isLocalFirmwarePreviewDescriptor,
  type LocalFirmwarePreviewDescriptor,
} from "@/lib/local-firmware-preview";

// The public source tree deliberately selects no release. A qualified public
// descriptor is reviewed and added only after all three final-byte HIL rows
// pass. Protected candidates are supplied explicitly at build time by the
// external staging workflow; they are never selected by browser state.
export const selectedFirmwareRelease: FirmwareReleaseDescriptor | null = null;

export function localFirmwarePreviewSelectedAtBuild(
  packageRoot = process.cwd(),
): LocalFirmwarePreviewDescriptor | null {
  const previewFlag = process.env.PYBLE_LOCAL_FLASH_PREVIEW;
  const previewFile = process.env.PYBLE_LOCAL_FLASH_PREVIEW_FILE;
  if (!previewFlag && !previewFile) {
    return null;
  }
  if (process.env.NODE_ENV !== "development") {
    throw new Error(
      "Local firmware preview is forbidden outside a development server",
    );
  }
  if (previewFlag !== "1" || !previewFile) {
    throw new Error(
      "Local firmware preview requires PYBLE_LOCAL_FLASH_PREVIEW=1 and PYBLE_LOCAL_FLASH_PREVIEW_FILE",
    );
  }
  if (process.env.PYBLE_FLASH_SELECTION_FILE) {
    throw new Error(
      "Local firmware preview cannot coexist with a release selector",
    );
  }
  const canonicalPackageRoot = realpathSync(packageRoot);
  const expectedFile = join(
    canonicalPackageRoot,
    "public",
    ".pyble-local-preview",
    "descriptor.json",
  );
  const requestedFile = resolve(previewFile);
  const requestedMetadata = lstatSync(requestedFile);
  if (!requestedMetadata.isFile() || requestedMetadata.isSymbolicLink()) {
    throw new Error("Local firmware preview descriptor must be a regular file");
  }
  const selectedFile = realpathSync(requestedFile);
  if (selectedFile !== expectedFile) {
    throw new Error(
      "Local firmware preview requires the exact staged descriptor path",
    );
  }
  if (realpathSync(dirname(selectedFile)) !== dirname(selectedFile)) {
    throw new Error("Local firmware preview descriptor must not use symlinks");
  }
  const parsed: unknown = JSON.parse(readFileSync(selectedFile, "utf8"));
  if (!isLocalFirmwarePreviewDescriptor(parsed)) {
    throw new Error("Local firmware preview descriptor is invalid");
  }
  return parsed;
}

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
    descriptor.deployment !== "candidate" &&
    descriptor.deployment !== "public-beta"
  ) {
    throw new Error(
      "Build-selected firmware descriptor has an invalid deployment mode",
    );
  }
  if (
    typeof descriptor.version !== "string" ||
    !(descriptor.deployment === "public-beta"
      ? hasExactHistoricalFirmwareProfileDescriptors(
          descriptor.version,
          descriptor.profiles,
        )
      : hasExactFirmwareProfileDescriptors(
          descriptor.version,
          descriptor.profiles,
        ))
  ) {
    throw new Error(
      "Build-selected firmware descriptor must contain the exact version-appropriate release profiles",
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
  if (
    descriptor.deployment === "public" &&
    !releaseIncludesWaveshareLcd147b(descriptor)
  ) {
    throw new Error(
      "Build-selected public firmware must be an unrestricted qualified v0.5.1-or-newer release",
    );
  }
  if (
    descriptor.deployment === "public-beta" &&
    !isExactPublicBetaFirmwareRelease(descriptor)
  ) {
    throw new Error(
      "Build-selected public beta does not match the exact audited v0.4.2 release",
    );
  }
  return descriptor;
}

// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

export const historicalFirmwareProfileTable = [
  {
    id: "esp32-4mb",
    label: "ESP32 · 4 MiB flash",
    target: "esp32",
    chipFamily: "ESP32",
    offset: 4096,
    flashSizeBytes: 4 * 1024 * 1024,
    flashFrequencyHz: 40_000_000,
    siliconRevision: { minimumFull: 0, maximumFull: 399 },
    psram: { required: false, sizeBytes: 0, type: "not-required" },
  },
  {
    id: "esp32-s3-n16r8",
    label: "ESP32-S3 · N16R8",
    target: "esp32-s3",
    chipFamily: "ESP32-S3",
    offset: 0,
    flashSizeBytes: 16 * 1024 * 1024,
    flashFrequencyHz: 80_000_000,
    siliconRevision: { minimumFull: 0, maximumFull: 99 },
    psram: { required: true, sizeBytes: 8 * 1024 * 1024, type: "octal" },
  },
] as const;

const sourceFirmwareProfileTable = [
  historicalFirmwareProfileTable[0],
  {
    ...historicalFirmwareProfileTable[1],
    label: "ESP32-S3 · N16R8 · lean generic",
  },
  {
    id: "waveshare-esp32-s3-lcd-147b",
    label: "Waveshare ESP32-S3-LCD-1.47B · N16R8",
    target: "waveshare-esp32-s3-lcd-147b",
    chipFamily: "ESP32-S3",
    offset: 0,
    flashSizeBytes: 16 * 1024 * 1024,
    flashFrequencyHz: 80_000_000,
    siliconRevision: { minimumFull: 0, maximumFull: 99 },
    psram: { required: true, sizeBytes: 8 * 1024 * 1024, type: "octal" },
  },
] as const;

export const firmwareProfileTable = [
  ...sourceFirmwareProfileTable,
  {
    id: "esp32-c3-4mb",
    label: "ESP32-C3 revision v0.3+ · 4 MiB flash",
    target: "esp32-c3",
    chipFamily: "ESP32-C3",
    offset: 0,
    flashSizeBytes: 4 * 1024 * 1024,
    flashFrequencyHz: 80_000_000,
    siliconRevision: { minimumFull: 3, maximumFull: 199 },
    psram: { required: false, sizeBytes: 0, type: "not-required" },
  },
  {
    id: "rpi-pico2-w",
    label: "Raspberry Pi Pico 2 W",
    target: "rpi-pico2-w",
  },
] as const;

// Retained for source compatibility with the pre-v0.6 website. The C3 is no
// longer merely planned; it is the fourth profile in the v0.6 release set.
export const plannedFirmwareProfileTable = [firmwareProfileTable[3]] as const;

export type FirmwareProfileId = (typeof firmwareProfileTable)[number]["id"];
export type HistoricalFirmwareProfileId =
  (typeof historicalFirmwareProfileTable)[number]["id"];
export type PlannedFirmwareProfileId =
  (typeof plannedFirmwareProfileTable)[number]["id"];
export type FirmwareDeployment = "public" | "candidate" | "public-beta";
export type FirmwareHilStatus = "pending" | "passed";
export type FirmwareProvisioningKind =
  "esp-web-serial" | "verified-uf2-bootsel";

export const publicBetaFirmwareVersion = "0.4.2";
export const publicBetaReleaseJsonSha256 =
  "5d1b0db8c4b90cccf054cd244530afb3b9112d489aa02f7c5da650e92161acde";

interface EspDescriptorFields {
  readonly chipFamily: string;
  readonly manifestPath: string;
  readonly offset: number;
  readonly siliconRevision: {
    readonly minimumFull: number;
    readonly maximumFull: number;
  };
  readonly flashSizeBytes: number;
  readonly psram: {
    readonly required: boolean;
    readonly sizeBytes: number;
    readonly type: string;
  };
}

export interface LegacyFirmwareProfileDescriptor extends EspDescriptorFields {
  readonly id: Exclude<FirmwareProfileId, "esp32-c3-4mb" | "rpi-pico2-w">;
  readonly label: string;
  readonly firmwarePath: string;
  readonly provisioningKind?: never;
  readonly target?: never;
}

export interface EspFirmwareProfileDescriptor extends EspDescriptorFields {
  readonly id: Exclude<FirmwareProfileId, "rpi-pico2-w">;
  readonly label: string;
  readonly target: string;
  readonly provisioningKind: "esp-web-serial";
  readonly firmwarePath: string;
}

export interface PicoFirmwareProfileDescriptor {
  readonly id: "rpi-pico2-w";
  readonly label: string;
  readonly target: "rpi-pico2-w";
  readonly provisioningKind: "verified-uf2-bootsel";
  readonly firmwarePath: string;
}

// The long-standing public type retains the ESP fields as required so source
// consumers compiled against the immutable v0.4/v0.5 descriptor do not need a
// migration. Schema-4 Pico descriptors deliberately omit those fields at
// runtime and are discriminated by provisioningKind.
export interface FirmwareProfileDescriptor extends EspDescriptorFields {
  readonly id: FirmwareProfileId;
  readonly label: string;
  readonly target?: string;
  readonly provisioningKind?: FirmwareProvisioningKind;
  readonly firmwarePath: string;
}

export interface FirmwareReleaseDescriptor {
  readonly deployment: FirmwareDeployment;
  readonly accessControlled: boolean;
  readonly version: string;
  readonly builtAt: string;
  readonly hilStatus: FirmwareHilStatus;
  readonly releaseJson: {
    readonly path: string;
    readonly sha256: string;
  };
  readonly schemaPath: string;
  readonly recoveryPath: string;
  readonly profiles: readonly FirmwareProfileDescriptor[];
}

export interface VerifiedFirmwareProfile {
  readonly profileId: FirmwareProfileId;
  readonly provisioningKind?: FirmwareProvisioningKind;
  readonly chipFamily: string;
  readonly manifestPath: string;
  readonly manifestBuildCount: 1;
  readonly firmwarePath: string;
  readonly version: string;
  readonly downloadUrl?: string;
  readonly verifiedFirmwareBytes?: ArrayBuffer;
}

export type VerifiedEspFirmwareProfile = VerifiedFirmwareProfile;
export type VerifiedPicoFirmwareProfile = VerifiedFirmwareProfile;

function coreVersion(
  version: string,
): readonly [number, number, number] | null {
  const match =
    /^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:-(?:0|[1-9][0-9]*|[0-9]*[A-Za-z-][0-9A-Za-z-]*)(?:\.(?:0|[1-9][0-9]*|[0-9]*[A-Za-z-][0-9A-Za-z-]*))*)?(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$/.exec(
      version,
    );
  return match ? [Number(match[1]), Number(match[2]), Number(match[3])] : null;
}

export function firmwareVersionUsesFiveProfiles(version: string): boolean {
  const core = coreVersion(version);
  return Boolean(
    core && (core[0] > 0 || core[1] > 6 || (core[1] === 6 && core[2] >= 0)),
  );
}

function firmwareVersionIncludesWaveshareLcd147b(version: string): boolean {
  const core = coreVersion(version);
  return Boolean(
    core && (core[0] > 0 || core[1] > 5 || (core[1] === 5 && core[2] >= 1)),
  );
}

interface EspProfileTableEntry {
  readonly id: Exclude<FirmwareProfileId, "esp32-c3-4mb" | "rpi-pico2-w">;
  readonly label: string;
  readonly target: string;
  readonly chipFamily: string;
  readonly offset: number;
  readonly flashSizeBytes: number;
  readonly flashFrequencyHz: number;
  readonly siliconRevision: {
    readonly minimumFull: number;
    readonly maximumFull: number;
  };
  readonly psram: {
    readonly required: boolean;
    readonly sizeBytes: number;
    readonly type: string;
  };
}

function legacyDescriptor(
  version: string,
  profile: EspProfileTableEntry,
): LegacyFirmwareProfileDescriptor {
  const root = `/firmware/v${version}/${profile.id}`;
  return {
    id: profile.id,
    label: profile.label,
    chipFamily: profile.chipFamily,
    manifestPath: `${root}/manifest.json`,
    firmwarePath: `${root}/firmware.bin`,
    offset: profile.offset,
    siliconRevision: profile.siliconRevision,
    flashSizeBytes: profile.flashSizeBytes,
    psram: profile.psram,
  };
}

export function profileDescriptor(
  version: string,
  profileId: FirmwareProfileId,
): FirmwareProfileDescriptor {
  if (!firmwareVersionUsesFiveProfiles(version)) {
    const legacy = sourceFirmwareProfileTable.find(
      (candidate) => candidate.id === profileId,
    );
    if (!legacy) {
      throw new Error(`Unsupported firmware profile: ${profileId}`);
    }
    return legacyDescriptor(version, legacy);
  }

  const profile = firmwareProfileTable.find(
    (candidate) => candidate.id === profileId,
  );
  if (!profile) {
    throw new Error(`Unsupported firmware profile: ${profileId}`);
  }
  const root = `/firmware/v${version}/${profileId}`;
  if (profile.id === "rpi-pico2-w") {
    return {
      id: profile.id,
      label: profile.label,
      target: profile.target,
      provisioningKind: "verified-uf2-bootsel",
      firmwarePath: `${root}/firmware.uf2`,
    } as unknown as FirmwareProfileDescriptor;
  }
  return {
    id: profile.id,
    label: profile.label,
    target: profile.target,
    provisioningKind: "esp-web-serial",
    chipFamily: profile.chipFamily,
    manifestPath: `${root}/manifest.json`,
    firmwarePath: `${root}/firmware.bin`,
    offset: profile.offset,
    siliconRevision: profile.siliconRevision,
    flashSizeBytes: profile.flashSizeBytes,
    psram: profile.psram,
  };
}

export function firmwareProfileDescriptors(
  version: string,
): readonly FirmwareProfileDescriptor[] {
  const profiles = firmwareVersionUsesFiveProfiles(version)
    ? firmwareProfileTable
    : sourceFirmwareProfileTable;
  return profiles.map(({ id }) => profileDescriptor(version, id));
}

export function historicalFirmwareProfileDescriptors(
  version: string,
): readonly LegacyFirmwareProfileDescriptor[] {
  return historicalFirmwareProfileTable.map((profile) =>
    legacyDescriptor(version, profile),
  );
}

export function isFirmwareProfileId(value: string): value is FirmwareProfileId {
  return firmwareProfileTable.some(({ id }) => id === value);
}

function exactObjectKeys(value: object, expected: readonly string[]): boolean {
  const actual = Object.keys(value).sort();
  const wanted = [...expected].sort();
  return (
    actual.length === wanted.length &&
    actual.every((key, index) => key === wanted[index])
  );
}

function isExactProfileDescriptor(
  value: unknown,
  expected: FirmwareProfileDescriptor,
): value is FirmwareProfileDescriptor {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return false;
  }
  const actual = value as Partial<FirmwareProfileDescriptor>;
  const base =
    actual.id === expected.id &&
    actual.label === expected.label &&
    actual.firmwarePath === expected.firmwarePath;
  if (!base) {
    return false;
  }
  if (expected.provisioningKind === "verified-uf2-bootsel") {
    return (
      exactObjectKeys(value, [
        "firmwarePath",
        "id",
        "label",
        "provisioningKind",
        "target",
      ]) &&
      actual.provisioningKind === expected.provisioningKind &&
      actual.target === expected.target
    );
  }

  const expectedEsp = expected as FirmwareProfileDescriptor;
  const actualEsp = actual as Partial<typeof expectedEsp>;
  const qualified = expectedEsp.provisioningKind === "esp-web-serial";
  const expectedKeys = [
    "chipFamily",
    "firmwarePath",
    "flashSizeBytes",
    "id",
    "label",
    "manifestPath",
    "offset",
    "psram",
    "siliconRevision",
    ...(qualified ? ["provisioningKind", "target"] : []),
  ];
  return (
    exactObjectKeys(value, expectedKeys) &&
    actualEsp.chipFamily === expectedEsp.chipFamily &&
    actualEsp.manifestPath === expectedEsp.manifestPath &&
    actualEsp.offset === expectedEsp.offset &&
    actualEsp.siliconRevision?.minimumFull ===
      expectedEsp.siliconRevision.minimumFull &&
    actualEsp.siliconRevision?.maximumFull ===
      expectedEsp.siliconRevision.maximumFull &&
    actualEsp.flashSizeBytes === expectedEsp.flashSizeBytes &&
    actualEsp.psram?.required === expectedEsp.psram.required &&
    actualEsp.psram?.sizeBytes === expectedEsp.psram.sizeBytes &&
    actualEsp.psram?.type === expectedEsp.psram.type &&
    (!qualified ||
      (actual.provisioningKind === "esp-web-serial" &&
        actual.target === expectedEsp.target))
  );
}

export function hasExactFirmwareProfileDescriptors(
  version: string,
  value: unknown,
): value is readonly FirmwareProfileDescriptor[] {
  if (!Array.isArray(value)) {
    return false;
  }
  const expected = firmwareProfileDescriptors(version);
  return (
    value.length === expected.length &&
    value.every((profile, index) => {
      const expectedProfile = expected[index];
      return Boolean(
        expectedProfile && isExactProfileDescriptor(profile, expectedProfile),
      );
    })
  );
}

export function hasExactHistoricalFirmwareProfileDescriptors(
  version: string,
  value: unknown,
): value is readonly LegacyFirmwareProfileDescriptor[] {
  if (!Array.isArray(value)) {
    return false;
  }
  const expected = historicalFirmwareProfileDescriptors(version);
  return (
    value.length === expected.length &&
    value.every((profile, index) => {
      const expectedProfile = expected[index];
      return Boolean(
        expectedProfile && isExactProfileDescriptor(profile, expectedProfile),
      );
    })
  );
}

export function isExactPublicBetaFirmwareRelease(
  value: unknown,
): value is FirmwareReleaseDescriptor {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return false;
  }
  const descriptor = value as Partial<FirmwareReleaseDescriptor>;
  const version = publicBetaFirmwareVersion;
  return (
    descriptor.deployment === "public-beta" &&
    descriptor.accessControlled === false &&
    descriptor.version === version &&
    descriptor.hilStatus === "pending" &&
    descriptor.releaseJson?.path === `/firmware/v${version}/release.json` &&
    descriptor.releaseJson?.sha256 === publicBetaReleaseJsonSha256 &&
    descriptor.schemaPath === `/firmware/v${version}/release.schema.json` &&
    descriptor.recoveryPath === `/firmware/v${version}/RECOVERY.md` &&
    hasExactHistoricalFirmwareProfileDescriptors(version, descriptor.profiles)
  );
}

export function releaseIncludesWaveshareLcd147b(
  release: FirmwareReleaseDescriptor | null | undefined,
): boolean {
  return Boolean(
    release?.deployment === "public" &&
    release.accessControlled === false &&
    release.hilStatus === "passed" &&
    firmwareVersionIncludesWaveshareLcd147b(release.version) &&
    hasExactFirmwareProfileDescriptors(release.version, release.profiles) &&
    release.profiles[2]?.id === "waveshare-esp32-s3-lcd-147b",
  );
}

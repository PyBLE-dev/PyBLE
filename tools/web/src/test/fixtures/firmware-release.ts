// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

import { createHash } from "node:crypto";

export const firmwareVersion = "0.4.1";
export const firmwareOrigin = "https://pyble.dev";

export const firmwareProfiles = [
  {
    id: "esp32-4mb",
    label: "ESP32 · 4 MiB flash",
    chipFamily: "ESP32",
    manifestPath: "/firmware/v0.4.1/esp32-4mb/manifest.json",
    firmwarePath: "/firmware/v0.4.1/esp32-4mb/firmware.bin",
    offset: 4096,
    siliconRevision: {
      minimumFull: 0,
      maximumFull: 399,
    },
    flashSizeBytes: 4 * 1024 * 1024,
    psram: {
      required: false,
      sizeBytes: 0,
      type: "not-required",
    },
  },
  {
    id: "esp32-s3-n16r8",
    label: "ESP32-S3 · N16R8",
    chipFamily: "ESP32-S3",
    manifestPath: "/firmware/v0.4.1/esp32-s3-n16r8/manifest.json",
    firmwarePath: "/firmware/v0.4.1/esp32-s3-n16r8/firmware.bin",
    offset: 0,
    siliconRevision: {
      minimumFull: 0,
      maximumFull: 99,
    },
    flashSizeBytes: 16 * 1024 * 1024,
    psram: {
      required: true,
      sizeBytes: 8 * 1024 * 1024,
      type: "octal",
    },
  },
] as const;

export type FirmwareProfileId = (typeof firmwareProfiles)[number]["id"];
export type FirmwareDeployment = "public" | "candidate";
export type HilStatus = "pending" | "passed";

interface TestArtifact {
  path: string;
  size: number;
  sha256: string;
}

interface TestOffsetArtifact extends TestArtifact {
  offset: number;
}

interface TestComponentArtifact extends TestOffsetArtifact {
  role: "bootloader" | "partition-table" | "application";
}

export interface TestManifest {
  name: string;
  version: string;
  new_install_prompt_erase: boolean;
  new_install_improv_wait_time: number;
  builds: Array<{
    chipFamily: string;
    parts: Array<{ path: string; offset: number }>;
  }>;
}

export interface TestReleaseProfile {
  id: FirmwareProfileId;
  chip_family: string;
  requirements: {
    flash_size_bytes: number;
    psram: {
      required: boolean;
      size_bytes: number;
      type: string;
    };
  };
  flash: {
    mode: string;
    frequency_hz: number;
  };
  silicon_revision: {
    minimum_full: number;
    maximum_full: number;
  };
  hil_status: HilStatus;
  manifest: TestArtifact;
  install: TestOffsetArtifact;
  components: TestComponentArtifact[];
}

export interface TestRelease {
  schema_version: number;
  identity: {
    version: string;
    tag: string;
    agent_version: string;
    protocol_version: string;
    built_at: string;
  };
  provenance: {
    pyble: { commit: string; clean: boolean };
    micropython: { ref: string; commit: string };
    esp_idf: { ref: string; commit: string };
    patch_count: number;
    runner: { os: string; architecture: string };
    tools: Array<{ name: string; version: string }>;
  };
  installer: {
    package: string;
    version: string;
  };
  profiles: TestReleaseProfile[];
  documents: {
    third_party_licenses: TestArtifact;
    release_notes: TestArtifact;
    recovery: TestArtifact;
    hil_report: TestArtifact;
  };
  unexpected?: unknown;
}

export interface FirmwareReleaseDescriptor {
  deployment: FirmwareDeployment;
  accessControlled: boolean;
  version: string;
  builtAt: string;
  hilStatus: HilStatus;
  releaseJson: {
    path: string;
    sha256: string;
  };
  schemaPath: string;
  recoveryPath: string;
  profiles: typeof firmwareProfiles;
}

interface FixtureOptions {
  deployment?: FirmwareDeployment;
  accessControlled?: boolean;
  hilStatus?: HilStatus;
  profileHilStatus?: Partial<Record<FirmwareProfileId, HilStatus>>;
  profileId?: FirmwareProfileId;
  mutateDescriptor?: (descriptor: FirmwareReleaseDescriptor) => void;
  mutateManifest?: (manifest: TestManifest) => void;
  mutateRelease?: (release: TestRelease) => void;
  servedFirmware?: (declaredBytes: Uint8Array) => Uint8Array;
  servedManifest?: (declaredBytes: Uint8Array) => Uint8Array;
}

export interface FirmwareReleaseFixture {
  descriptor: FirmwareReleaseDescriptor;
  files: Map<string, Uint8Array>;
  manifest: TestManifest;
  manifestBytes: Uint8Array;
  firmwareBytes: Uint8Array;
  profileId: FirmwareProfileId;
  release: TestRelease;
  releaseBytes: Uint8Array;
}

const encoder = new TextEncoder();

function textBytes(value: string) {
  return encoder.encode(value);
}

export function jsonBytes(value: unknown) {
  return textBytes(`${JSON.stringify(value)}\n`);
}

export function sha256(bytes: Uint8Array) {
  return createHash("sha256").update(bytes).digest("hex");
}

function artifact(path: string, bytes: Uint8Array): TestArtifact {
  return {
    path,
    size: bytes.byteLength,
    sha256: sha256(bytes),
  };
}

function exactManifest(profileId: FirmwareProfileId): TestManifest {
  const profile = firmwareProfiles.find(
    (candidate) => candidate.id === profileId,
  );
  if (!profile) {
    throw new Error(`Unknown test profile: ${profileId}`);
  }

  return {
    name: "PyBLE",
    version: firmwareVersion,
    new_install_prompt_erase: false,
    new_install_improv_wait_time: 0,
    builds: [
      {
        chipFamily: profile.chipFamily,
        parts: [{ path: "firmware.bin", offset: profile.offset }],
      },
    ],
  };
}

export function exactReleaseSchema() {
  const sha = {
    type: "string",
    pattern: "^[0-9a-f]{64}$",
  };
  const commit = {
    type: "string",
    pattern: "^[0-9a-f]{40}$",
  };
  const relativePath = {
    type: "string",
    minLength: 1,
    pattern: "^(?!/)(?!.*(?:^|/)\\.\\.?(?:/|$))(?!.*[\\\\?#])(?!.*://).+$",
  };
  const artifactSchema = {
    type: "object",
    additionalProperties: false,
    required: ["path", "size", "sha256"],
    properties: {
      path: relativePath,
      size: { type: "integer", minimum: 1 },
      sha256: sha,
    },
  };
  const offsetArtifact = {
    ...artifactSchema,
    required: [...artifactSchema.required, "offset"],
    properties: {
      ...artifactSchema.properties,
      offset: { type: "integer", minimum: 0 },
    },
  };
  const component = {
    ...offsetArtifact,
    required: ["role", ...offsetArtifact.required],
    properties: {
      ...offsetArtifact.properties,
      role: {
        enum: ["bootloader", "partition-table", "application"],
      },
    },
  };
  const profileSchema = {
    type: "object",
    additionalProperties: false,
    required: [
      "id",
      "chip_family",
      "requirements",
      "flash",
      "silicon_revision",
      "hil_status",
      "manifest",
      "install",
      "components",
    ],
    properties: {
      id: {
        enum: ["esp32-4mb", "esp32-s3-n16r8"],
      },
      chip_family: {
        enum: ["ESP32", "ESP32-S3"],
      },
      silicon_revision: {
        type: "object",
        additionalProperties: false,
        required: ["minimum_full", "maximum_full"],
        properties: {
          minimum_full: { type: "integer", minimum: 0 },
          maximum_full: { type: "integer", minimum: 0 },
        },
      },
      requirements: {
        type: "object",
        additionalProperties: false,
        required: ["flash_size_bytes", "psram"],
        properties: {
          flash_size_bytes: { type: "integer", minimum: 1 },
          psram: {
            type: "object",
            additionalProperties: false,
            required: ["required", "size_bytes", "type"],
            properties: {
              required: { type: "boolean" },
              size_bytes: { type: "integer", minimum: 0 },
              type: { enum: ["not-required", "octal"] },
            },
          },
        },
      },
      flash: {
        type: "object",
        additionalProperties: false,
        required: ["mode", "frequency_hz"],
        properties: {
          mode: { const: "dio" },
          frequency_hz: { type: "integer", minimum: 1 },
        },
      },
      hil_status: { enum: ["pending", "passed"] },
      manifest: artifactSchema,
      install: offsetArtifact,
      components: {
        type: "array",
        minItems: 3,
        maxItems: 3,
        items: component,
      },
    },
  };
  const tool = {
    type: "object",
    additionalProperties: false,
    required: ["name", "version"],
    properties: {
      name: { type: "string", minLength: 1 },
      version: { type: "string", minLength: 1 },
    },
  };

  return {
    $schema: "https://json-schema.org/draft/2020-12/schema",
    $id: "https://pyble.dev/firmware/release.schema.json",
    title: "PyBLE firmware release metadata v2",
    type: "object",
    additionalProperties: false,
    required: [
      "schema_version",
      "identity",
      "provenance",
      "installer",
      "profiles",
      "documents",
    ],
    properties: {
      schema_version: { const: 2 },
      identity: {
        type: "object",
        additionalProperties: false,
        required: [
          "version",
          "tag",
          "agent_version",
          "protocol_version",
          "built_at",
        ],
        properties: {
          version: {
            type: "string",
            pattern:
              "^(?:0|[1-9][0-9]*)\\.(?:0|[1-9][0-9]*)\\.(?:0|[1-9][0-9]*)(?:-(?:0|[1-9][0-9]*|[0-9]*[A-Za-z-][0-9A-Za-z-]*)(?:\\.(?:0|[1-9][0-9]*|[0-9]*[A-Za-z-][0-9A-Za-z-]*))*)?(?:\\+[0-9A-Za-z-]+(?:\\.[0-9A-Za-z-]+)*)?$",
          },
          tag: { type: "string", pattern: "^firmware-v.+$" },
          agent_version: { type: "string", minLength: 1 },
          protocol_version: { const: "PBLE/1" },
          built_at: {
            type: "string",
            pattern: "^\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}Z$",
          },
        },
      },
      provenance: {
        type: "object",
        additionalProperties: false,
        required: [
          "pyble",
          "micropython",
          "esp_idf",
          "patch_count",
          "runner",
          "tools",
        ],
        properties: {
          pyble: {
            type: "object",
            additionalProperties: false,
            required: ["commit", "clean"],
            properties: {
              commit,
              clean: { const: true },
            },
          },
          micropython: {
            type: "object",
            additionalProperties: false,
            required: ["ref", "commit"],
            properties: {
              ref: { type: "string", minLength: 1 },
              commit,
            },
          },
          esp_idf: {
            type: "object",
            additionalProperties: false,
            required: ["ref", "commit"],
            properties: {
              ref: { type: "string", minLength: 1 },
              commit,
            },
          },
          patch_count: { type: "integer", minimum: 0 },
          runner: {
            type: "object",
            additionalProperties: false,
            required: ["os", "architecture"],
            properties: {
              os: { type: "string", minLength: 1 },
              architecture: { type: "string", minLength: 1 },
            },
          },
          tools: {
            type: "array",
            minItems: 1,
            items: tool,
          },
        },
      },
      installer: {
        type: "object",
        additionalProperties: false,
        required: ["package", "version"],
        properties: {
          package: { const: "esp-web-tools" },
          version: { const: "10.4.0" },
        },
      },
      profiles: {
        type: "array",
        minItems: 2,
        maxItems: 2,
        items: profileSchema,
      },
      documents: {
        type: "object",
        additionalProperties: false,
        required: [
          "third_party_licenses",
          "release_notes",
          "recovery",
          "hil_report",
        ],
        properties: {
          third_party_licenses: artifactSchema,
          release_notes: artifactSchema,
          recovery: artifactSchema,
          hil_report: artifactSchema,
        },
      },
    },
  };
}

export function createFirmwareReleaseFixture(
  options: FixtureOptions = {},
): FirmwareReleaseFixture {
  const selectedProfileId = options.profileId ?? "esp32-s3-n16r8";
  const selectedManifest = exactManifest(selectedProfileId);
  options.mutateManifest?.(selectedManifest);

  const files = new Map<string, Uint8Array>();
  const profileArtifacts = new Map<
    FirmwareProfileId,
    {
      manifest: TestArtifact;
      install: TestOffsetArtifact;
      components: TestComponentArtifact[];
    }
  >();

  for (const [profileIndex, profile] of firmwareProfiles.entries()) {
    const manifest =
      profile.id === selectedProfileId
        ? selectedManifest
        : exactManifest(profile.id);
    const manifestBytes = jsonBytes(manifest);
    const firmwareBytes = new Uint8Array([
      0xe9,
      profileIndex,
      0x50,
      0x79,
      0x42,
      0x4c,
      0x45,
    ]);
    const componentDefinitions = [
      {
        role: "bootloader" as const,
        filename: "bootloader.bin",
        offset: profile.offset,
      },
      {
        role: "partition-table" as const,
        filename: "partition-table.bin",
        offset: 0x8000,
      },
      {
        role: "application" as const,
        filename: "application.bin",
        offset: 0x10000,
      },
    ];

    files.set(`${profile.id}/manifest.json`, manifestBytes);
    files.set(`${profile.id}/firmware.bin`, firmwareBytes);

    const components = componentDefinitions.map(
      ({ role, filename, offset }, componentIndex) => {
        const bytes = new Uint8Array([
          0xe9,
          profileIndex,
          componentIndex,
          0x50,
          0x79,
        ]);
        files.set(`${profile.id}/${filename}`, bytes);
        return {
          ...artifact(`${profile.id}/${filename}`, bytes),
          role,
          offset,
        };
      },
    );

    profileArtifacts.set(profile.id, {
      manifest: artifact(`${profile.id}/manifest.json`, manifestBytes),
      install: {
        ...artifact(`${profile.id}/firmware.bin`, firmwareBytes),
        offset: profile.offset,
      },
      components,
    });
  }

  const documentDefinitions = {
    third_party_licenses: {
      path: "THIRD_PARTY_LICENSES.txt",
      bytes: textBytes("Test-only third-party notices\n"),
    },
    release_notes: {
      path: "RELEASE_NOTES.md",
      bytes: textBytes("# Test-only release notes\n"),
    },
    recovery: {
      path: "RECOVERY.md",
      bytes: textBytes("# Test-only recovery\n"),
    },
    hil_report: {
      path: "HIL_REPORT.md",
      bytes: textBytes("# Test-only HIL report\n"),
    },
  };

  for (const { path, bytes } of Object.values(documentDefinitions)) {
    files.set(path, bytes);
  }

  const defaultHilStatus = options.hilStatus ?? "passed";
  const release: TestRelease = {
    schema_version: 2,
    identity: {
      version: firmwareVersion,
      tag: `firmware-v${firmwareVersion}`,
      agent_version: firmwareVersion,
      protocol_version: "PBLE/1",
      built_at: "2026-07-30T12:00:00Z",
    },
    provenance: {
      pyble: { commit: "1".repeat(40), clean: true },
      micropython: { ref: "v1.28.0", commit: "2".repeat(40) },
      esp_idf: { ref: "v5.5.1", commit: "3".repeat(40) },
      patch_count: 0,
      runner: { os: "FixtureOS 1", architecture: "fixture64" },
      tools: [
        { name: "cmake", version: "4.0.1" },
        { name: "esp-idf", version: "5.5.1" },
      ],
    },
    installer: {
      package: "esp-web-tools",
      version: "10.4.0",
    },
    profiles: firmwareProfiles.map((profile) => {
      const artifacts = profileArtifacts.get(profile.id);
      if (!artifacts) {
        throw new Error(`Missing test artifacts for ${profile.id}`);
      }
      return {
        id: profile.id,
        chip_family: profile.chipFamily,
        requirements: {
          flash_size_bytes: profile.flashSizeBytes,
          psram: {
            required: profile.psram.required,
            size_bytes: profile.psram.sizeBytes,
            type: profile.psram.type,
          },
        },
        flash: {
          mode: "dio",
          frequency_hz: profile.id === "esp32-4mb" ? 40_000_000 : 80_000_000,
        },
        silicon_revision: {
          minimum_full: profile.siliconRevision.minimumFull,
          maximum_full: profile.siliconRevision.maximumFull,
        },
        hil_status: options.profileHilStatus?.[profile.id] ?? defaultHilStatus,
        ...artifacts,
      };
    }),
    documents: {
      third_party_licenses: artifact(
        documentDefinitions.third_party_licenses.path,
        documentDefinitions.third_party_licenses.bytes,
      ),
      release_notes: artifact(
        documentDefinitions.release_notes.path,
        documentDefinitions.release_notes.bytes,
      ),
      recovery: artifact(
        documentDefinitions.recovery.path,
        documentDefinitions.recovery.bytes,
      ),
      hil_report: artifact(
        documentDefinitions.hil_report.path,
        documentDefinitions.hil_report.bytes,
      ),
    },
  };

  options.mutateRelease?.(release);
  const releaseBytes = jsonBytes(release);
  const descriptor: FirmwareReleaseDescriptor = {
    deployment: options.deployment ?? "public",
    accessControlled: options.accessControlled ?? false,
    version: firmwareVersion,
    builtAt: release.identity.built_at,
    hilStatus: defaultHilStatus,
    releaseJson: {
      path: `/firmware/v${firmwareVersion}/release.json`,
      sha256: sha256(releaseBytes),
    },
    schemaPath: `/firmware/v${firmwareVersion}/release.schema.json`,
    recoveryPath: `/firmware/v${firmwareVersion}/RECOVERY.md`,
    profiles: firmwareProfiles,
  };
  options.mutateDescriptor?.(descriptor);

  files.set("release.json", releaseBytes);
  const schemaBytes = jsonBytes(exactReleaseSchema());
  files.set("release.schema.json", schemaBytes);

  const selectedRelativeManifest = `${selectedProfileId}/manifest.json`;
  const selectedRelativeFirmware = `${selectedProfileId}/firmware.bin`;
  const declaredManifestBytes = files.get(selectedRelativeManifest);
  const declaredFirmwareBytes = files.get(selectedRelativeFirmware);
  if (!declaredManifestBytes || !declaredFirmwareBytes) {
    throw new Error("Selected test profile artifacts are missing");
  }

  files.set(
    selectedRelativeManifest,
    options.servedManifest?.(declaredManifestBytes) ?? declaredManifestBytes,
  );
  files.set(
    selectedRelativeFirmware,
    options.servedFirmware?.(declaredFirmwareBytes) ?? declaredFirmwareBytes,
  );

  return {
    descriptor,
    files,
    manifest: selectedManifest,
    manifestBytes: declaredManifestBytes,
    firmwareBytes: declaredFirmwareBytes,
    profileId: selectedProfileId,
    release,
    releaseBytes,
  };
}

export function bundleFiles(fixture: FirmwareReleaseFixture) {
  const files = new Map(fixture.files);
  const sums = [...files.entries()]
    .sort(([left], [right]) => left.localeCompare(right))
    .map(([path, bytes]) => `${sha256(bytes)}  ${path}`)
    .join("\n");
  files.set("SHA256SUMS", textBytes(`${sums}\n`));
  return files;
}

export const passedPublicFirmwareRelease =
  createFirmwareReleaseFixture().descriptor;
export const pendingPublicFirmwareRelease = createFirmwareReleaseFixture({
  hilStatus: "pending",
}).descriptor;
export const pendingCandidateFirmwareRelease = createFirmwareReleaseFixture({
  deployment: "candidate",
  accessControlled: true,
  hilStatus: "pending",
}).descriptor;
export const uncontrolledCandidateFirmwareRelease =
  createFirmwareReleaseFixture({
    deployment: "candidate",
    accessControlled: false,
    hilStatus: "pending",
  }).descriptor;

export const installerConsents = [
  /module matches the selected chip, silicon revision, flash, and psram profile/i,
  /backed up the board files and previous firmware/i,
  /installation erases the device/i,
  /data-capable usb cable and stable power/i,
  /closed serial monitors and other apps using this port/i,
] as const;

export function verifiedProfile(profileId: FirmwareProfileId) {
  const profile = firmwareProfiles.find(
    (candidate) => candidate.id === profileId,
  );
  if (!profile) {
    throw new Error(`Unknown test profile: ${profileId}`);
  }

  return {
    profileId,
    chipFamily: profile.chipFamily,
    manifestPath: profile.manifestPath,
    manifestBuildCount: 1 as const,
    firmwarePath: profile.firmwarePath,
    version: firmwareVersion,
  };
}

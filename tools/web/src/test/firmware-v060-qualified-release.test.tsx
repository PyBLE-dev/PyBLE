// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

import { createHash } from "node:crypto";
import { mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import type { ComponentType } from "react";

import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { FlashStatus } from "@/components/flash-status";
import {
  firmwareProfileDescriptors,
  historicalFirmwareProfileDescriptors,
  isFirmwareProfileId,
} from "@/lib/firmware-release";
import { firmwareReleaseSelectedAtBuild } from "@/lib/firmware-release-selection";
import {
  createCurrentFirmwareReleaseFixture,
  createFirmwareReleaseFixture,
} from "@/test/fixtures/firmware-release";
import { stageFirmwareRelease } from "../../scripts/stage-firmware-release";

const version = "0.6.0";
const profileOrder = [
  "esp32-4mb",
  "esp32-s3-n16r8",
  "waveshare-esp32-s3-lcd-147b",
  "esp32-c3-4mb",
  "rpi-pico2-w",
] as const;
const temporaryDirectories: string[] = [];
const encoder = new TextEncoder();

type HilStatus = "pending" | "passed";
type ProvisioningKind = "esp-web-serial" | "verified-uf2-bootsel";
type EspProfileId = Exclude<(typeof profileOrder)[number], "rpi-pico2-w">;

interface QualifiedProfileDescriptor {
  id: (typeof profileOrder)[number];
  label: string;
  target: string;
  provisioningKind: ProvisioningKind;
  firmwarePath: string;
  chipFamily?: string;
  manifestPath?: string;
  offset?: number;
  siliconRevision?: { minimumFull: number; maximumFull: number };
  flashSizeBytes?: number;
  psram?: { required: boolean; sizeBytes: number; type: string };
}

interface QualifiedReleaseDescriptor {
  deployment: "public" | "candidate";
  accessControlled: boolean;
  version: string;
  builtAt: string;
  hilStatus: HilStatus;
  releaseJson: { path: string; sha256: string };
  schemaPath: string;
  recoveryPath: string;
  profiles: QualifiedProfileDescriptor[];
}

interface VerifiedEspProfile {
  profileId: EspProfileId;
  provisioningKind: "esp-web-serial";
  chipFamily: string;
  manifestPath: string;
  manifestBuildCount: 1;
  firmwarePath: string;
  version: string;
}

interface VerifiedPicoProfile {
  profileId: "rpi-pico2-w";
  provisioningKind: "verified-uf2-bootsel";
  firmwarePath: string;
  version: string;
  downloadUrl: string;
  verifiedFirmwareBytes: ArrayBuffer;
}

type VerifiedProfile = VerifiedEspProfile | VerifiedPicoProfile;

interface QualifiedFlashProps {
  capabilities: {
    secureContext: boolean;
    webSerial: boolean;
    webCrypto: boolean;
  };
  installArtifactFetch?: (
    profile: VerifiedEspProfile,
    releaseKey: string,
  ) => () => void;
  loadInstaller?: () => Promise<void>;
  release: QualifiedReleaseDescriptor;
  verifyProfile?: (
    release: QualifiedReleaseDescriptor,
    profileId: (typeof profileOrder)[number],
  ) => Promise<VerifiedProfile>;
}

const QualifiedFlashStatus = FlashStatus as ComponentType<QualifiedFlashProps>;

function qualifiedProfiles(): QualifiedProfileDescriptor[] {
  const esp = [
    {
      id: "esp32-4mb" as const,
      label: "ESP32 · 4 MiB flash",
      target: "esp32",
      chipFamily: "ESP32",
      offset: 4096,
      flashSizeBytes: 4 * 1024 * 1024,
      siliconRevision: { minimumFull: 0, maximumFull: 399 },
      psram: { required: false, sizeBytes: 0, type: "not-required" },
    },
    {
      id: "esp32-s3-n16r8" as const,
      label: "ESP32-S3 · N16R8 · lean generic",
      target: "esp32-s3",
      chipFamily: "ESP32-S3",
      offset: 0,
      flashSizeBytes: 16 * 1024 * 1024,
      siliconRevision: { minimumFull: 0, maximumFull: 99 },
      psram: { required: true, sizeBytes: 8 * 1024 * 1024, type: "octal" },
    },
    {
      id: "waveshare-esp32-s3-lcd-147b" as const,
      label: "Waveshare ESP32-S3-LCD-1.47B · N16R8",
      target: "waveshare-esp32-s3-lcd-147b",
      chipFamily: "ESP32-S3",
      offset: 0,
      flashSizeBytes: 16 * 1024 * 1024,
      siliconRevision: { minimumFull: 0, maximumFull: 99 },
      psram: { required: true, sizeBytes: 8 * 1024 * 1024, type: "octal" },
    },
    {
      id: "esp32-c3-4mb" as const,
      label: "ESP32-C3 revision v0.3+ · 4 MiB flash",
      target: "esp32-c3",
      chipFamily: "ESP32-C3",
      offset: 0,
      flashSizeBytes: 4 * 1024 * 1024,
      siliconRevision: { minimumFull: 3, maximumFull: 199 },
      psram: { required: false, sizeBytes: 0, type: "not-required" },
    },
  ].map((profile) => ({
    ...profile,
    provisioningKind: "esp-web-serial" as const,
    manifestPath: `/firmware/v${version}/${profile.id}/manifest.json`,
    firmwarePath: `/firmware/v${version}/${profile.id}/firmware.bin`,
  }));

  return [
    ...esp,
    {
      id: "rpi-pico2-w",
      label: "Raspberry Pi Pico 2 W",
      target: "rpi-pico2-w",
      provisioningKind: "verified-uf2-bootsel",
      firmwarePath: `/firmware/v${version}/rpi-pico2-w/firmware.uf2`,
    },
  ];
}

function qualifiedRelease(
  hilStatus: HilStatus = "passed",
): QualifiedReleaseDescriptor {
  return {
    deployment: "public",
    accessControlled: false,
    version,
    builtAt: "2026-08-12T00:00:00Z",
    hilStatus,
    releaseJson: {
      path: `/firmware/v${version}/release.json`,
      sha256: "a".repeat(64),
    },
    schemaPath: `/firmware/v${version}/release.schema.json`,
    recoveryPath: `/firmware/v${version}/RECOVERY.md`,
    profiles: qualifiedProfiles(),
  };
}

function candidateRelease(): QualifiedReleaseDescriptor {
  return {
    ...qualifiedRelease("pending"),
    deployment: "candidate",
    accessControlled: true,
  };
}

function textBytes(value: string) {
  return encoder.encode(value);
}

function jsonBytes(value: unknown) {
  return textBytes(`${JSON.stringify(value)}\n`);
}

function sha256(bytes: Uint8Array) {
  return createHash("sha256").update(bytes).digest("hex");
}

function artifact(path: string, bytes: Uint8Array) {
  return { path, size: bytes.byteLength, sha256: sha256(bytes) };
}

function validPicoArtifacts() {
  const rawImage = new Uint8Array(256);
  rawImage.set([0x50, 0x42, 0x4c, 0x45]);
  const uf2 = new Uint8Array(1024);
  const view = new DataView(uf2.buffer);

  function writeBlock(
    blockOffset: number,
    flags: number,
    address: number,
    blockNumber: number,
    totalBlocks: number,
    family: number,
    payload: Uint8Array,
  ) {
    view.setUint32(blockOffset, 0x0a324655, true);
    view.setUint32(blockOffset + 4, 0x9e5d5157, true);
    view.setUint32(blockOffset + 8, flags, true);
    view.setUint32(blockOffset + 12, address, true);
    view.setUint32(blockOffset + 16, payload.byteLength, true);
    view.setUint32(blockOffset + 20, blockNumber, true);
    view.setUint32(blockOffset + 24, totalBlocks, true);
    view.setUint32(blockOffset + 28, family, true);
    uf2.set(payload, blockOffset + 32);
    view.setUint32(blockOffset + 508, 0x0ab16f30, true);
  }

  writeBlock(0, 0x00002000, 0x10000000, 0, 1, 0xe48bff59, rawImage);
  writeBlock(
    512,
    0x0000a000,
    0x10ffff00,
    0,
    2,
    0xe48bff57,
    new Uint8Array(256),
  );
  return { rawImage, uf2 };
}

async function temporaryDirectory(label: string) {
  const directory = await mkdtemp(join(tmpdir(), `pyble-${label}-`));
  temporaryDirectories.push(directory);
  return directory;
}

async function writeSelection(descriptor: QualifiedReleaseDescriptor) {
  const root = await temporaryDirectory("v060-selection");
  const path = join(root, "selection.json");
  await writeFile(path, `${JSON.stringify(descriptor, null, 2)}\n`);
  process.env.PYBLE_FLASH_SELECTION_FILE = path;
}

async function writeQualifiedBundle(root: string) {
  const files = new Map<string, Uint8Array>();
  const profileMetadata: Array<Record<string, unknown>> = [];
  const espProfiles = qualifiedProfiles().slice(0, 4);

  for (const [profileIndex, profile] of espProfiles.entries()) {
    const manifest = jsonBytes({
      name: "PyBLE",
      version,
      new_install_prompt_erase: false,
      new_install_improv_wait_time: 0,
      builds: [
        {
          chipFamily: profile.chipFamily,
          parts: [{ path: "firmware.bin", offset: profile.offset }],
        },
      ],
    });
    const install = new Uint8Array([
      0xe9,
      profileIndex,
      0x50,
      0x42,
      0x4c,
      0x45,
    ]);
    files.set(`${profile.id}/manifest.json`, manifest);
    files.set(`${profile.id}/firmware.bin`, install);
    const componentSpecs = [
      ["bootloader", "bootloader.bin", profile.offset],
      ["partition-table", "partition-table.bin", 0x8000],
      ["application", "application.bin", 0x10000],
    ] as const;
    const components = componentSpecs.map(([role, name, offset], index) => {
      const bytes = new Uint8Array([0xe9, profileIndex, index, 0x60]);
      const path = `${profile.id}/${name}`;
      files.set(path, bytes);
      return { role, ...artifact(path, bytes), offset };
    });
    profileMetadata.push({
      id: profile.id,
      target: profile.target,
      provisioning_kind: profile.provisioningKind,
      chip_family: profile.chipFamily,
      requirements: {
        flash_size_bytes: profile.flashSizeBytes,
        psram: {
          required: profile.psram?.required,
          size_bytes: profile.psram?.sizeBytes,
          type: profile.psram?.type,
        },
      },
      flash: {
        mode: "dio",
        frequency_hz: profile.id === "esp32-4mb" ? 40_000_000 : 80_000_000,
      },
      silicon_revision: {
        minimum_full: profile.siliconRevision?.minimumFull,
        maximum_full: profile.siliconRevision?.maximumFull,
      },
      hil_status: "passed",
      manifest: artifact(`${profile.id}/manifest.json`, manifest),
      install: {
        ...artifact(`${profile.id}/firmware.bin`, install),
        offset: profile.offset,
      },
      components,
    });
  }

  const { rawImage, uf2 } = validPicoArtifacts();
  files.set("rpi-pico2-w/firmware.uf2", uf2);
  files.set("rpi-pico2-w/firmware.bin", rawImage);
  profileMetadata.push({
    id: "rpi-pico2-w",
    target: "rpi-pico2-w",
    provisioning_kind: "verified-uf2-bootsel",
    hil_status: "passed",
    board: "RPI_PICO2_W",
    install: {
      ...artifact("rpi-pico2-w/firmware.uf2", uf2),
      format: "uf2",
    },
    resource_image: {
      ...artifact("rpi-pico2-w/firmware.bin", rawImage),
      image_limit_bytes: 1_572_864,
    },
  });

  const documentSpecs = {
    third_party_licenses: ["THIRD_PARTY_LICENSES.txt", "MIT\n"],
    release_notes: ["RELEASE_NOTES.md", "# PyBLE 0.6.0\n"],
    recovery: ["RECOVERY.md", "# Recovery\n"],
    hil_report: ["HIL_REPORT.md", "# Passed HIL\n"],
  } as const;
  const documents: Record<string, ReturnType<typeof artifact>> = {};
  for (const [key, [path, contents]] of Object.entries(documentSpecs)) {
    const bytes = textBytes(contents);
    files.set(path, bytes);
    documents[key] = artifact(path, bytes);
  }

  const release = {
    schema_version: 4,
    identity: {
      version,
      tag: `firmware-v${version}`,
      agent_version: version,
      protocol_version: "PBLE/1",
      built_at: "2026-08-12T00:00:00Z",
    },
    provenance: {
      pyble: { commit: "1".repeat(40), clean: true },
      micropython: { ref: "v1.28.0", commit: "2".repeat(40) },
      esp_idf: { ref: "v5.5.2", commit: "3".repeat(40) },
      patch_count: 0,
      runner: { os: "macOS", architecture: "arm64" },
      tools: [{ name: "xtensa-esp-elf-gcc", version: "14.2.0" }],
    },
    installer: { package: "esp-web-tools", version: "10.4.0" },
    profiles: profileMetadata,
    documents,
  };
  files.set("release.json", jsonBytes(release));
  files.set(
    "release.schema.json",
    new Uint8Array(
      await readFile(
        join(process.cwd(), "src/lib/firmware-release-schema.json"),
      ),
    ),
  );
  const sums = [...files.entries()]
    .sort(([left], [right]) => left.localeCompare(right))
    .map(([path, bytes]) => `${sha256(bytes)}  ${path}`)
    .join("\n");
  files.set("SHA256SUMS", textBytes(`${sums}\n`));

  for (const [relativePath, bytes] of files) {
    const path = join(root, relativePath);
    await mkdir(dirname(path), { recursive: true });
    await writeFile(path, bytes);
  }
}

afterEach(async () => {
  delete process.env.PYBLE_FLASH_SELECTION_FILE;
  vi.restoreAllMocks();
  await Promise.all(
    temporaryDirectories
      .splice(0)
      .map((directory) => rm(directory, { recursive: true, force: true })),
  );
});

describe("qualified v0.6.0 firmware descriptor", () => {
  it("uses the exact heterogeneous five-profile order and provisioning methods", () => {
    const v060 = firmwareProfileDescriptors(
      version,
    ) as readonly QualifiedProfileDescriptor[];
    expect(v060.map(({ id }) => id)).toEqual(profileOrder);
    expect(
      v060.slice(0, 4).map(({ provisioningKind }) => provisioningKind),
    ).toEqual([
      "esp-web-serial",
      "esp-web-serial",
      "esp-web-serial",
      "esp-web-serial",
    ]);
    for (const profile of v060.slice(0, 4)) {
      expect(profile.manifestPath).toBe(
        `/firmware/v${version}/${profile.id}/manifest.json`,
      );
      expect(profile.firmwarePath).toBe(
        `/firmware/v${version}/${profile.id}/firmware.bin`,
      );
    }
    expect(v060[4]).toMatchObject({
      id: "rpi-pico2-w",
      provisioningKind: "verified-uf2-bootsel",
      firmwarePath: `/firmware/v${version}/rpi-pico2-w/firmware.uf2`,
    });
    expect(v060[4]).not.toHaveProperty("manifestPath");
    expect(v060[4]).not.toHaveProperty("offset");
    expect(v060[4]).not.toHaveProperty("chipFamily");
    expect(profileOrder.every((id) => isFirmwareProfileId(id))).toBe(true);
  });

  it("preserves the immutable v0.4.2 and source-era v0.5.1 fixture shapes", () => {
    expect(
      historicalFirmwareProfileDescriptors("0.4.2").map(({ id }) => id),
    ).toEqual(profileOrder.slice(0, 2));
    expect(firmwareProfileDescriptors("0.5.1").map(({ id }) => id)).toEqual(
      profileOrder.slice(0, 3),
    );

    const historical = createFirmwareReleaseFixture();
    const sourceV051 = createCurrentFirmwareReleaseFixture();
    expect(historical.release.schema_version).toBe(2);
    expect(historical.release.profiles.map(({ id }) => id)).toEqual(
      profileOrder.slice(0, 2),
    );
    expect(sourceV051.release.schema_version).toBe(3);
    expect(sourceV051.release.identity.version).toBe("0.5.1");
    expect(sourceV051.release.profiles.map(({ id }) => id)).toEqual(
      profileOrder.slice(0, 3),
    );
  });

  it("publishes the canonical release schema 4 discriminator", async () => {
    const schema = JSON.parse(
      await readFile(
        join(process.cwd(), "src/lib/firmware-release-schema.json"),
        "utf8",
      ),
    ) as {
      title: string;
      properties: {
        schema_version: { const: number };
        profiles: { minItems: number; maxItems: number };
      };
    };
    const serialized = JSON.stringify(schema);

    expect(schema.title).toMatch(/v4$/i);
    expect(schema.properties.schema_version.const).toBe(4);
    expect(schema.properties.profiles).toMatchObject({
      minItems: 5,
      maxItems: 5,
    });
    expect(serialized).toContain("esp-web-serial");
    expect(serialized).toContain("verified-uf2-bootsel");
    expect(serialized).toContain("RPI_PICO2_W");
    expect(serialized).toContain("image_limit_bytes");
  });

  it("accepts only the exact unrestricted all-passed five-profile public selector", async () => {
    const exact = qualifiedRelease();
    await writeSelection(exact);
    expect(firmwareReleaseSelectedAtBuild()).toEqual(exact);

    const pending = qualifiedRelease("pending");
    await writeSelection(pending);
    expect(() => firmwareReleaseSelectedAtBuild()).toThrow(
      /qualified|hardware validation|passed/i,
    );

    const reordered = qualifiedRelease();
    [reordered.profiles[3], reordered.profiles[4]] = [
      reordered.profiles[4]!,
      reordered.profiles[3]!,
    ];
    await writeSelection(reordered);
    expect(() => firmwareReleaseSelectedAtBuild()).toThrow(
      /exact|profile|order/i,
    );
  });

  it("stages schema-4 ESP manifests and Pico UF2 without inventing a Pico manifest", async () => {
    const bundleDirectory = await temporaryDirectory("v060-bundle");
    const outputDirectory = await temporaryDirectory("v060-staged");
    await writeQualifiedBundle(bundleDirectory);

    const descriptor = (await stageFirmwareRelease({
      accessControlled: false,
      bundleDirectory,
      deployment: "public",
      outputDirectory,
      releaseValidator: async () => undefined,
    })) as QualifiedReleaseDescriptor;

    expect(descriptor.version).toBe(version);
    expect(descriptor.hilStatus).toBe("passed");
    expect(descriptor.profiles.map(({ id }) => id)).toEqual(profileOrder);
    expect(descriptor.profiles.slice(0, 4)).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          id: "esp32-c3-4mb",
          provisioningKind: "esp-web-serial",
          manifestPath: `/firmware/v${version}/esp32-c3-4mb/manifest.json`,
          firmwarePath: `/firmware/v${version}/esp32-c3-4mb/firmware.bin`,
        }),
      ]),
    );
    const pico = descriptor.profiles[4];
    expect(pico).toMatchObject({
      id: "rpi-pico2-w",
      provisioningKind: "verified-uf2-bootsel",
      firmwarePath: `/firmware/v${version}/rpi-pico2-w/firmware.uf2`,
    });
    expect(pico).not.toHaveProperty("manifestPath");
    expect(pico).not.toHaveProperty("chipFamily");
    expect(pico).not.toHaveProperty("offset");
  });
});

function acceptAcknowledgements() {
  const group = screen.getByRole("group", {
    name: /installation acknowledgements/i,
  });
  for (const checkbox of within(group).getAllByRole("checkbox")) {
    fireEvent.click(checkbox);
  }
}

function selectProfile(profileId: (typeof profileOrder)[number]) {
  fireEvent.change(
    screen.getByRole("combobox", { name: /choose a firmware target/i }),
    { target: { value: profileId } },
  );
}

describe("qualified v0.6.0 production installer", () => {
  it("starts with an unselected five-target dropdown in exact release order", () => {
    render(
      <QualifiedFlashStatus
        capabilities={{ secureContext: true, webSerial: true, webCrypto: true }}
        release={qualifiedRelease()}
      />,
    );

    expect(
      screen.getByRole("heading", { name: /qualified release/i }),
    ).toBeVisible();
    const selector = screen.getByRole("combobox", {
      name: /choose a firmware target/i,
    });
    expect(selector).toHaveValue("");
    expect(
      within(selector)
        .getAllByRole("option")
        .map((option) => (option as HTMLOptionElement).value)
        .filter(Boolean),
    ).toEqual(profileOrder);
    expect(
      screen.queryByRole("group", { name: /installation acknowledgements/i }),
    ).not.toBeInTheDocument();
  });

  it("verifies only the selected ESP artifacts before exposing Web Serial install", async () => {
    const release = qualifiedRelease();
    const loadInstaller = vi.fn(async () => undefined);
    const installArtifactFetch = vi.fn(() => () => undefined);
    const verifyProfile = vi.fn(async (): Promise<VerifiedEspProfile> => ({
      profileId: "esp32-c3-4mb",
      provisioningKind: "esp-web-serial",
      chipFamily: "ESP32-C3",
      manifestPath: `/firmware/v${version}/esp32-c3-4mb/manifest.json`,
      manifestBuildCount: 1,
      firmwarePath: `/firmware/v${version}/esp32-c3-4mb/firmware.bin`,
      version,
    }));
    render(
      <QualifiedFlashStatus
        capabilities={{ secureContext: true, webSerial: true, webCrypto: true }}
        installArtifactFetch={installArtifactFetch}
        loadInstaller={loadInstaller}
        release={release}
        verifyProfile={verifyProfile}
      />,
    );

    selectProfile("esp32-c3-4mb");
    acceptAcknowledgements();
    fireEvent.click(screen.getByRole("button", { name: /verify firmware/i }));

    await waitFor(() => expect(loadInstaller).toHaveBeenCalledOnce());
    expect(verifyProfile).toHaveBeenCalledWith(release, "esp32-c3-4mb");
    expect(installArtifactFetch).toHaveBeenCalledOnce();
    expect(document.querySelector("esp-web-install-button")).toHaveAttribute(
      "manifest",
      `/firmware/v${version}/esp32-c3-4mb/manifest.json`,
    );
    expect(screen.queryByRole("link", { name: /download.*uf2/i })).toBeNull();
  });

  it("downloads selected verified in-memory Pico UF2 without Web Serial or ESP Web Tools", async () => {
    const release = qualifiedRelease();
    const loadInstaller = vi.fn(async () => undefined);
    const verifyProfile = vi.fn(async (): Promise<VerifiedPicoProfile> => ({
      profileId: "rpi-pico2-w",
      provisioningKind: "verified-uf2-bootsel",
      firmwarePath: `/firmware/v${version}/rpi-pico2-w/firmware.uf2`,
      version,
      downloadUrl: "blob:pyble-qualified-rpi-pico2-w",
      verifiedFirmwareBytes: new Uint8Array([0x55, 0x46, 0x32]).buffer,
    }));
    render(
      <QualifiedFlashStatus
        capabilities={{
          secureContext: true,
          webSerial: false,
          webCrypto: true,
        }}
        loadInstaller={loadInstaller}
        release={release}
        verifyProfile={verifyProfile}
      />,
    );

    selectProfile("rpi-pico2-w");
    acceptAcknowledgements();
    fireEvent.click(screen.getByRole("button", { name: /verify firmware/i }));

    const download = await screen.findByRole("link", {
      name: /download.*uf2/i,
    });
    expect(download).toHaveAttribute(
      "href",
      "blob:pyble-qualified-rpi-pico2-w",
    );
    expect(download).not.toHaveAttribute(
      "href",
      `/firmware/v${version}/rpi-pico2-w/firmware.uf2`,
    );
    expect(download).toHaveAttribute(
      "download",
      `pyble-${version}-rpi-pico2-w.uf2`,
    );
    expect(screen.getByText(/BOOTSEL/i)).toBeVisible();
    expect(loadInstaller).not.toHaveBeenCalled();
    expect(document.querySelector("esp-web-install-button")).toBeNull();
  });

  it("keeps the exact-board Waveshare warning visible whenever its profile is selectable", () => {
    const candidate = render(
      <QualifiedFlashStatus
        capabilities={{ secureContext: true, webSerial: true, webCrypto: true }}
        release={candidateRelease()}
      />,
    );

    expect(
      screen.getByRole("heading", { name: /protected release candidate/i }),
    ).toBeVisible();
    expect(
      screen.getByText(/image is only for the exact ESP32-S3-LCD-1\.47B/i),
    ).toBeVisible();
    candidate.unmount();

    render(
      <QualifiedFlashStatus
        capabilities={{ secureContext: true, webSerial: true, webCrypto: true }}
        release={qualifiedRelease()}
      />,
    );
    expect(
      screen.getByText(/image is only for the exact ESP32-S3-LCD-1\.47B/i),
    ).toBeVisible();
  });

  it("asks for Pico-appropriate acknowledgements in the verified-UF2 flow", () => {
    render(
      <QualifiedFlashStatus
        capabilities={{
          secureContext: true,
          webSerial: false,
          webCrypto: true,
        }}
        release={qualifiedRelease()}
      />,
    );

    selectProfile("rpi-pico2-w");

    const group = screen.getByRole("group", {
      name: /installation acknowledgements/i,
    });
    expect(
      within(group).getByText("Installation acknowledgements", {
        selector: "legend",
      }),
    ).toBeInTheDocument();
    // The board affirmation names the actual Pico 2 W hardware contract, not
    // the ESP chip/silicon-revision/flash/PSRAM fields the schema-4 Pico
    // profile deliberately omits.
    expect(
      within(group).getByRole("checkbox", {
        name: /raspberry pi pico 2 w \(rp2350 \+ cyw43439\)/i,
      }),
    ).toBeInTheDocument();
    expect(
      within(group).queryByRole("checkbox", {
        name: /chip, silicon revision, flash, and psram/i,
      }),
    ).toBeNull();
    expect(
      within(group).queryByRole("checkbox", {
        name: /closed serial monitors/i,
      }),
    ).toBeNull();
  });

  it("keeps a pending public five-profile release fail-closed", () => {
    render(
      <QualifiedFlashStatus
        capabilities={{ secureContext: true, webSerial: true, webCrypto: true }}
        release={qualifiedRelease("pending")}
      />,
    );

    expect(
      screen.getByRole("heading", { name: /public installer unavailable/i }),
    ).toBeVisible();
    expect(
      screen.getByText(/hardware validation.*pending.*fail-closed/i),
    ).toBeVisible();
    expect(
      screen.queryByRole("combobox", { name: /choose a firmware target/i }),
    ).toBeNull();
    expect(document.querySelector("esp-web-install-button")).toBeNull();
    expect(screen.queryByRole("link", { name: /download.*uf2/i })).toBeNull();
  });
});

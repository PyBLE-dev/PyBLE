// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

import { execFile as execFileCallback } from "node:child_process";
import { createHash } from "node:crypto";
import {
  mkdir,
  mkdtemp,
  readFile,
  readdir,
  rm,
  symlink,
  writeFile,
} from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { promisify } from "node:util";

import { afterEach, describe, expect, it, vi } from "vitest";

import { prepareSitesOutput } from "../../scripts/prepare-sites-output";
import {
  stageLocalFirmwarePreview,
  validateRp2350Uf2,
} from "../../scripts/stage-local-firmware-preview";
import {
  firmwareReleaseSelectedAtBuild,
  localFirmwarePreviewSelectedAtBuild,
} from "@/lib/firmware-release-selection";
import {
  verifyLocalFirmwarePreviewProfile,
  type LocalFirmwarePreviewDescriptor,
} from "@/lib/local-firmware-preview";

const execFile = promisify(execFileCallback);
const temporaryDirectories: string[] = [];
const initialNodeEnvironment = process.env.NODE_ENV;
const initialFirmwareSelection = process.env.PYBLE_FLASH_SELECTION_FILE;
const mutableEnvironment = process.env as Record<string, string | undefined>;

const espProfiles = [
  {
    buildTarget: "esp32",
    chipFamily: "ESP32",
    flashFrequency: "40m",
    flashSize: "4MB",
    id: "esp32-4mb",
    label: "ESP32 · 4 MiB flash",
    offset: 0x1000,
  },
  {
    buildTarget: "esp32-s3",
    chipFamily: "ESP32-S3",
    flashFrequency: "80m",
    flashSize: "16MB",
    id: "esp32-s3-n16r8",
    label: "ESP32-S3 · N16R8 · lean generic",
    offset: 0,
  },
  {
    buildTarget: "waveshare-esp32-s3-lcd-147b",
    chipFamily: "ESP32-S3",
    flashFrequency: "80m",
    flashSize: "16MB",
    id: "waveshare-esp32-s3-lcd-147b",
    label: "Waveshare ESP32-S3-LCD-1.47B · N16R8",
    offset: 0,
  },
  {
    buildTarget: "esp32-c3",
    chipFamily: "ESP32-C3",
    flashFrequency: "80m",
    flashSize: "4MB",
    id: "esp32-c3-4mb",
    label: "ESP32-C3 revision v0.3+ · 4 MiB flash",
    offset: 0,
  },
] as const;

interface PreviewFixture {
  readonly repositoryRoot: string;
  readonly espBuildRoot: string;
  readonly rp2BuildRoot: string;
  readonly sourceCommit: string;
  readonly sourceDateEpoch: number;
  readonly espFirmware: ReadonlyMap<string, Uint8Array>;
  readonly picoFirmware: Uint8Array;
}

afterEach(async () => {
  delete process.env.PYBLE_LOCAL_FLASH_PREVIEW;
  delete process.env.PYBLE_LOCAL_FLASH_PREVIEW_FILE;
  if (initialFirmwareSelection === undefined) {
    delete process.env.PYBLE_FLASH_SELECTION_FILE;
  } else {
    process.env.PYBLE_FLASH_SELECTION_FILE = initialFirmwareSelection;
  }
  if (initialNodeEnvironment === undefined) {
    delete mutableEnvironment.NODE_ENV;
  } else {
    mutableEnvironment.NODE_ENV = initialNodeEnvironment;
  }
  vi.restoreAllMocks();
  await Promise.all(
    temporaryDirectories
      .splice(0)
      .map((directory) => rm(directory, { recursive: true, force: true })),
  );
});

async function temporaryDirectory(label: string) {
  const directory = await mkdtemp(join(tmpdir(), `pyble-${label}-`));
  temporaryDirectories.push(directory);
  return directory;
}

async function writeJson(path: string, value: unknown) {
  await mkdir(dirname(path), { recursive: true });
  await writeFile(path, `${JSON.stringify(value, null, 2)}\n`, "utf8");
}

function sha256(bytes: Uint8Array) {
  return createHash("sha256").update(bytes).digest("hex");
}

function rp2350Uf2Fixture() {
  const firmwareBin = Buffer.alloc(300);
  firmwareBin.forEach((_, index) => {
    firmwareBin[index] = index & 0xff;
  });
  const extension = Buffer.alloc(512);
  extension.writeUInt32LE(0x0a324655, 0);
  extension.writeUInt32LE(0x9e5d5157, 4);
  extension.writeUInt32LE(0x0000a000, 8);
  extension.writeUInt32LE(0x10ffff00, 12);
  extension.writeUInt32LE(256, 16);
  extension.writeUInt32LE(0, 20);
  extension.writeUInt32LE(2, 24);
  extension.writeUInt32LE(0xe48bff57, 28);
  extension.fill(0xef, 32, 288);
  extension.writeUInt32LE(0x0ab16f30, 508);
  const mainBlocks = [0, 1].map((blockNumber) => {
    const block = Buffer.alloc(512);
    block.writeUInt32LE(0x0a324655, 0);
    block.writeUInt32LE(0x9e5d5157, 4);
    block.writeUInt32LE(0x00002000, 8);
    block.writeUInt32LE(0x10000000 + blockNumber * 256, 12);
    block.writeUInt32LE(256, 16);
    block.writeUInt32LE(blockNumber, 20);
    block.writeUInt32LE(2, 24);
    block.writeUInt32LE(0xe48bff59, 28);
    firmwareBin
      .subarray(blockNumber * 256, (blockNumber + 1) * 256)
      .copy(block, 32);
    block.writeUInt32LE(0x0ab16f30, 508);
    return block;
  });
  return {
    firmwareBin,
    firmwareUf2: Buffer.concat([extension, ...mainBlocks]),
  };
}

async function initialiseRepository(root: string) {
  await mkdir(join(root, "firmware"), { recursive: true });
  await writeFile(
    join(root, "firmware", "versions.lock"),
    '[micropython]\ncommit = "1111111111111111111111111111111111111111"\n\n[esp_idf]\ncommit = "2222222222222222222222222222222222222222"\n\n[pyble]\nagent_version = "0.6.0"\nprotocol_version = "PBLE/1"\n\n[arm_gnu_toolchain]\nrelease = "14.2.Rel1"\ngcc_version = "14.2.1 20241119"\n',
    "utf8",
  );
  await writeFile(
    join(root, "firmware", "source-contract.txt"),
    "preview fixture\n",
    "utf8",
  );
  await execFile("git", ["init", "--quiet"], { cwd: root });
  await execFile("git", ["config", "user.name", "PyBLE tests"], {
    cwd: root,
  });
  await execFile("git", ["config", "user.email", "tests@pyble.dev"], {
    cwd: root,
  });
  await execFile("git", ["add", "firmware"], { cwd: root });
  await execFile("git", ["commit", "--quiet", "-m", "firmware source"], {
    cwd: root,
    env: {
      ...process.env,
      GIT_AUTHOR_DATE: "2026-08-12T00:00:00Z",
      GIT_COMMITTER_DATE: "2026-08-12T00:00:00Z",
    },
  });
  const [{ stdout: commit }, { stdout: epoch }] = await Promise.all([
    execFile("git", ["rev-parse", "HEAD"], { cwd: root }),
    execFile("git", ["show", "-s", "--format=%ct", "HEAD"], { cwd: root }),
  ]);
  return {
    sourceCommit: commit.trim(),
    sourceDateEpoch: Number(epoch.trim()),
  };
}

function espProvenance(
  buildTarget: string,
  sourceCommit: string,
  sourceDateEpoch: number,
) {
  return {
    schema_version: 1,
    target: buildTarget,
    source_date_epoch: sourceDateEpoch,
    pyble: { commit: sourceCommit, clean: true },
    micropython: { commit: "1".repeat(40) },
    esp_idf: { commit: "2".repeat(40) },
  };
}

async function createPreviewFixture(): Promise<PreviewFixture> {
  const repositoryRoot = await temporaryDirectory("preview-source");
  const espBuildRoot = await temporaryDirectory("preview-esp-builds");
  const rp2BuildRoot = await temporaryDirectory("preview-rp2-builds");
  const { sourceCommit, sourceDateEpoch } =
    await initialiseRepository(repositoryRoot);
  const espFirmware = new Map<string, Uint8Array>();

  for (const [index, profile] of espProfiles.entries()) {
    const targetRoot = join(espBuildRoot, profile.buildTarget);
    const firmware = new Uint8Array([0xe9, index, 0x50, 0x42, 0x4c, 0x45]);
    espFirmware.set(profile.id, firmware);
    await mkdir(targetRoot, { recursive: true });
    await writeFile(join(targetRoot, "firmware.bin"), firmware);
    await writeJson(join(targetRoot, "flasher_args.json"), {
      write_flash_args: [
        "--flash_mode",
        "dio",
        "--flash_size",
        profile.flashSize,
        "--flash_freq",
        profile.flashFrequency,
      ],
      flash_settings: {
        flash_mode: "dio",
        flash_size: profile.flashSize,
        flash_freq: profile.flashFrequency,
      },
      flash_files: {
        [`0x${profile.offset.toString(16)}`]: "bootloader/bootloader.bin",
        "0x10000": "micropython.bin",
        "0x8000": "partition_table/partition-table.bin",
      },
      extra_esptool_args: {
        after: "hard_reset",
        before: "default_reset",
        stub: true,
        chip:
          profile.buildTarget === "esp32"
            ? "esp32"
            : profile.buildTarget === "esp32-c3"
              ? "esp32c3"
              : "esp32s3",
      },
    });
    await writeJson(
      join(targetRoot, "pyble-build-provenance.json"),
      espProvenance(profile.buildTarget, sourceCommit, sourceDateEpoch),
    );
  }

  const picoRoot = join(rp2BuildRoot, "rpi-pico2-w");
  const { firmwareBin: picoBin, firmwareUf2: picoFirmware } =
    rp2350Uf2Fixture();
  await mkdir(picoRoot, { recursive: true });
  await writeFile(join(picoRoot, "firmware.uf2"), picoFirmware);
  await writeFile(join(picoRoot, "firmware.bin"), picoBin);
  await writeFile(join(picoRoot, "firmware.elf"), "ELF fixture");
  await writeJson(join(picoRoot, "pyble-build-provenance.json"), {
    schema_version: 1,
    target: "rpi-pico2-w",
    port: "rp2",
    board: "PYBLE_RPI_PICO2_W",
    source_date_epoch: sourceDateEpoch,
    pyble: { commit: sourceCommit, clean: true },
    micropython: { commit: "1".repeat(40) },
    arm_gnu_toolchain: {
      release: "14.2.Rel1",
      gcc: "arm-none-eabi-gcc 14.2.1 20241119",
    },
    picotool: "picotool v2.3.0",
    firmware_bin_bytes: picoBin.byteLength,
  });

  return {
    repositoryRoot,
    espBuildRoot,
    rp2BuildRoot,
    sourceCommit,
    sourceDateEpoch,
    espFirmware,
    picoFirmware,
  };
}

async function commitNonFirmwareChange(fixture: PreviewFixture) {
  await mkdir(join(fixture.repositoryRoot, "docs"));
  await writeFile(
    join(fixture.repositoryRoot, "docs", "preview.md"),
    "Local preview only.\n",
  );
  await execFile("git", ["add", "docs/preview.md"], {
    cwd: fixture.repositoryRoot,
  });
  await execFile("git", ["commit", "--quiet", "-m", "website preview"], {
    cwd: fixture.repositoryRoot,
  });
}

describe("local firmware engineering-preview staging", () => {
  it("rejects incomplete RP2350 Arm UF2 streams", async () => {
    const directory = await temporaryDirectory("preview-truncated-uf2");
    const { firmwareUf2 } = rp2350Uf2Fixture();
    const path = join(directory, "firmware.uf2");
    await writeFile(path, firmwareUf2.subarray(0, -512));

    await expect(validateRp2350Uf2(path)).rejects.toThrow(
      /incomplete|RP2350 Arm/i,
    );
  });

  it("rejects fake ESP bytes through the canonical build validator", async () => {
    const fixture = await createPreviewFixture();

    await expect(
      stageLocalFirmwarePreview({
        repositoryRoot: fixture.repositoryRoot,
        espBuildRoot: fixture.espBuildRoot,
        rp2BuildRoot: fixture.rp2BuildRoot,
      }),
    ).rejects.toThrow(/canonical|release_bundle\.py/i);
  });

  it("stages five isolated, hash-bound v0.6.0 profiles from one unchanged firmware source", async () => {
    const fixture = await createPreviewFixture();
    await commitNonFirmwareChange(fixture);
    const validateUf2 = vi.fn(async () => undefined);

    const descriptor = await stageLocalFirmwarePreview({
      repositoryRoot: fixture.repositoryRoot,
      espBuildRoot: fixture.espBuildRoot,
      rp2BuildRoot: fixture.rp2BuildRoot,
      espBuildValidator: async () => undefined,
      uf2Validator: validateUf2,
    });
    const outputRoot = join(
      fixture.repositoryRoot,
      "tools",
      "web",
      "public",
      ".pyble-local-preview",
    );

    expect(validateUf2).toHaveBeenCalledOnce();
    expect(validateUf2).toHaveBeenCalledWith(
      join(fixture.rp2BuildRoot, "rpi-pico2-w", "firmware.uf2"),
    );
    expect(descriptor).toMatchObject({
      schemaVersion: 1,
      deployment: "local-preview",
      localOnly: true,
      qualified: false,
      version: "0.6.0",
      sourceCommit: fixture.sourceCommit,
      builtAt: new Date(fixture.sourceDateEpoch * 1000).toISOString(),
    });
    expect(descriptor.profiles).toHaveLength(5);
    expect(await readdir(outputRoot)).toEqual([
      "descriptor.json",
      "esp32-4mb",
      "esp32-c3-4mb",
      "esp32-s3-n16r8",
      "rpi-pico2-w",
      "waveshare-esp32-s3-lcd-147b",
    ]);

    for (const expected of espProfiles) {
      const profile = descriptor.profiles.find(
        (candidate) => candidate.id === expected.id,
      );
      const sourceFirmware = fixture.espFirmware.get(expected.id);
      expect(sourceFirmware).toBeDefined();
      expect(profile).toEqual({
        id: expected.id,
        label: expected.label,
        chipFamily: expected.chipFamily,
        buildTarget: expected.buildTarget,
        method: "esp-web-tools",
        qualified: false,
        status: "engineering-preview",
        offset: expected.offset,
        manifest: {
          path: `/.pyble-local-preview/${expected.id}/manifest.json`,
          size: expect.any(Number),
          sha256: expect.stringMatching(/^[0-9a-f]{64}$/),
        },
        firmware: {
          path: `/.pyble-local-preview/${expected.id}/firmware.bin`,
          size: sourceFirmware?.byteLength,
          sha256: sha256(sourceFirmware ?? new Uint8Array()),
        },
      });
      const profileRoot = join(outputRoot, expected.id);
      expect(await readdir(profileRoot)).toEqual([
        "firmware.bin",
        "manifest.json",
      ]);
      const manifestBytes = await readFile(join(profileRoot, "manifest.json"));
      expect(profile?.manifest).toEqual({
        path: `/.pyble-local-preview/${expected.id}/manifest.json`,
        size: manifestBytes.byteLength,
        sha256: sha256(manifestBytes),
      });
      expect(JSON.parse(manifestBytes.toString("utf8"))).toEqual({
        name: "PyBLE",
        version: "0.6.0",
        new_install_prompt_erase: false,
        new_install_improv_wait_time: 0,
        builds: [
          {
            chipFamily: expected.chipFamily,
            parts: [{ path: "firmware.bin", offset: expected.offset }],
          },
        ],
      });
      await expect(
        readFile(join(profileRoot, "firmware.bin")),
      ).resolves.toEqual(Buffer.from(sourceFirmware ?? new Uint8Array()));
    }

    expect(descriptor.profiles.at(-1)).toEqual({
      id: "rpi-pico2-w",
      label: "Raspberry Pi Pico 2 W",
      chipFamily: "RP2350",
      buildTarget: "rpi-pico2-w",
      method: "uf2-download",
      qualified: false,
      status: "engineering-preview",
      firmware: {
        path: "/.pyble-local-preview/rpi-pico2-w/firmware.uf2",
        size: fixture.picoFirmware.byteLength,
        sha256: sha256(fixture.picoFirmware),
      },
    });
    await expect(
      readFile(join(outputRoot, "rpi-pico2-w", "firmware.uf2")),
    ).resolves.toEqual(fixture.picoFirmware);
    await expect(
      readFile(join(outputRoot, "descriptor.json"), "utf8").then(JSON.parse),
    ).resolves.toEqual(descriptor);

    const origin = "http://127.0.0.1:3000";
    const verified = await verifyLocalFirmwarePreviewProfile({
      descriptor: descriptor as unknown as LocalFirmwarePreviewDescriptor,
      origin,
      profileId: "esp32-4mb",
      subtle: globalThis.crypto.subtle,
      fetcher: async (input) => {
        const url = new URL(input.toString());
        const bytes = await readFile(
          join(outputRoot, url.pathname.replace("/.pyble-local-preview/", "")),
        );
        const response = new Response(bytes, { status: 200 });
        Object.defineProperty(response, "url", { value: url.href });
        return response;
      },
    });
    expect(verified).toMatchObject({
      profileId: "esp32-4mb",
      manifestPath: "/.pyble-local-preview/esp32-4mb/manifest.json",
      firmwarePath: "/.pyble-local-preview/esp32-4mb/firmware.bin",
    });

    mutableEnvironment.NODE_ENV = "development";
    delete process.env.PYBLE_FLASH_SELECTION_FILE;
    process.env.PYBLE_LOCAL_FLASH_PREVIEW = "1";
    process.env.PYBLE_LOCAL_FLASH_PREVIEW_FILE = join(
      outputRoot,
      "descriptor.json",
    );
    expect(
      localFirmwarePreviewSelectedAtBuild(
        join(fixture.repositoryRoot, "tools", "web"),
      ),
    ).toEqual(descriptor);
  });

  it("rejects non-regular inputs and firmware changes after the attested build commit", async () => {
    const symlinkFixture = await createPreviewFixture();
    const linkedFirmware = join(symlinkFixture.espBuildRoot, "linked.bin");
    await writeFile(linkedFirmware, new Uint8Array([0xe9]));
    const esp32Firmware = join(
      symlinkFixture.espBuildRoot,
      "esp32",
      "firmware.bin",
    );
    await rm(esp32Firmware);
    await symlink(linkedFirmware, esp32Firmware);
    await expect(
      stageLocalFirmwarePreview({
        repositoryRoot: symlinkFixture.repositoryRoot,
        espBuildRoot: symlinkFixture.espBuildRoot,
        rp2BuildRoot: symlinkFixture.rp2BuildRoot,
        espBuildValidator: async () => undefined,
        uf2Validator: async () => undefined,
      }),
    ).rejects.toThrow(/ordinary|regular|symbolic link/i);

    const driftFixture = await createPreviewFixture();
    await writeFile(
      join(driftFixture.repositoryRoot, "firmware", "source-contract.txt"),
      "changed after build\n",
    );
    await execFile("git", ["add", "firmware/source-contract.txt"], {
      cwd: driftFixture.repositoryRoot,
    });
    await execFile("git", ["commit", "--quiet", "-m", "firmware drift"], {
      cwd: driftFixture.repositoryRoot,
    });
    await expect(
      stageLocalFirmwarePreview({
        repositoryRoot: driftFixture.repositoryRoot,
        espBuildRoot: driftFixture.espBuildRoot,
        rp2BuildRoot: driftFixture.rp2BuildRoot,
        espBuildValidator: async () => undefined,
        uf2Validator: async () => undefined,
      }),
    ).rejects.toThrow(/firmware.*(?:changed|drift)|source.*firmware/i);
  });
});

describe("local preview remains outside every production publication path", () => {
  it("requires both an explicit selector and the development environment", async () => {
    const fixture = await createPreviewFixture();
    const descriptor = await stageLocalFirmwarePreview({
      repositoryRoot: fixture.repositoryRoot,
      espBuildRoot: fixture.espBuildRoot,
      rp2BuildRoot: fixture.rp2BuildRoot,
      espBuildValidator: async () => undefined,
      uf2Validator: async () => undefined,
    });
    const selectionFile = join(
      fixture.repositoryRoot,
      "tools",
      "web",
      "public",
      ".pyble-local-preview",
      "descriptor.json",
    );

    mutableEnvironment.NODE_ENV = "development";
    delete process.env.PYBLE_FLASH_SELECTION_FILE;
    delete process.env.PYBLE_LOCAL_FLASH_PREVIEW;
    delete process.env.PYBLE_LOCAL_FLASH_PREVIEW_FILE;
    const packageRoot = join(fixture.repositoryRoot, "tools", "web");
    expect(localFirmwarePreviewSelectedAtBuild(packageRoot)).toBeNull();

    process.env.PYBLE_LOCAL_FLASH_PREVIEW_FILE = selectionFile;
    expect(() => localFirmwarePreviewSelectedAtBuild(packageRoot)).toThrow(
      /PYBLE_LOCAL_FLASH_PREVIEW=1|explicit/i,
    );
    process.env.PYBLE_LOCAL_FLASH_PREVIEW = "1";
    expect(localFirmwarePreviewSelectedAtBuild(packageRoot)).toEqual(
      descriptor,
    );
    process.env.PYBLE_FLASH_SELECTION_FILE = "/tmp/public-release.json";
    expect(() => localFirmwarePreviewSelectedAtBuild(packageRoot)).toThrow(
      /cannot coexist|release selector/i,
    );
    delete process.env.PYBLE_FLASH_SELECTION_FILE;

    mutableEnvironment.NODE_ENV = "production";
    expect(() => localFirmwarePreviewSelectedAtBuild(packageRoot)).toThrow(
      /development|local preview/i,
    );
    expect(firmwareReleaseSelectedAtBuild()).toBeNull();
    await expect(
      prepareSitesOutput(await temporaryDirectory("preview-sites")),
    ).rejects.toThrow(/local preview|PYBLE_LOCAL_FLASH_PREVIEW_FILE/i);
  });

  it("keeps generated preview bytes ignored and untracked", async () => {
    const repositoryRoot = join(process.cwd(), "..", "..");
    const previewPath = "tools/web/public/.pyble-local-preview/descriptor.json";
    const [{ stdout: tracked }, ignoreProbe] = await Promise.all([
      execFile("git", ["ls-files", "--", previewPath], {
        cwd: repositoryRoot,
      }),
      execFile("git", ["check-ignore", "--quiet", previewPath], {
        cwd: repositoryRoot,
      }).then(
        () => true,
        () => false,
      ),
    ]);

    expect(tracked.trim()).toBe("");
    expect(ignoreProbe).toBe(true);
  });
});

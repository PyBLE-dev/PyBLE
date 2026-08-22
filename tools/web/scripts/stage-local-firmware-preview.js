// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

import { execFile as execFileCallback } from "node:child_process";
import { createHash } from "node:crypto";
import {
  lstat,
  mkdir,
  mkdtemp,
  readFile,
  realpath,
  rename,
  rm,
  writeFile,
} from "node:fs/promises";
import { dirname, isAbsolute, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { promisify } from "node:util";

const execFile = promisify(execFileCallback);

const espProfiles = [
  {
    id: "esp32-4mb",
    label: "ESP32 · 4 MiB flash",
    buildTarget: "esp32",
    chipFamily: "ESP32",
    flashFrequency: "40m",
    flashSize: "4MB",
    offset: 0x1000,
  },
  {
    id: "esp32-s3-n16r8",
    label: "ESP32-S3 · N16R8 · lean generic",
    buildTarget: "esp32-s3",
    chipFamily: "ESP32-S3",
    flashFrequency: "80m",
    flashSize: "16MB",
    offset: 0,
  },
  {
    id: "waveshare-esp32-s3-lcd-147b",
    label: "Waveshare ESP32-S3-LCD-1.47B · N16R8",
    buildTarget: "waveshare-esp32-s3-lcd-147b",
    chipFamily: "ESP32-S3",
    flashFrequency: "80m",
    flashSize: "16MB",
    offset: 0,
  },
  {
    id: "esp32-c3-4mb",
    label: "ESP32-C3 revision v0.3+ · 4 MiB flash",
    buildTarget: "esp32-c3",
    chipFamily: "ESP32-C3",
    flashFrequency: "80m",
    flashSize: "4MB",
    offset: 0,
  },
];

/**
 * @param {string} message
 * @returns {never}
 */
function failure(message) {
  throw new Error(`Local firmware preview staging failed: ${message}`);
}

/** @param {string | Uint8Array} bytes */
function sha256(bytes) {
  return createHash("sha256").update(bytes).digest("hex");
}

/** @param {unknown} value @param {string[]} expected */
function hasExactKeys(value, expected) {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return false;
  }
  const actual = Object.keys(value).sort();
  const wanted = [...expected].sort();
  return (
    actual.length === wanted.length &&
    actual.every((key, index) => key === wanted[index])
  );
}

/**
 * @param {string} path
 * @param {string} root
 */
async function ordinaryFile(path, root) {
  const metadata = await lstat(path).catch(() => null);
  if (!metadata?.isFile() || metadata.isSymbolicLink()) {
    failure(`${path} must be an ordinary regular file, not a symbolic link`);
  }
  const [resolvedFile, resolvedRoot] = await Promise.all([
    realpath(path),
    realpath(root),
  ]);
  const child = relative(resolvedRoot, resolvedFile);
  if (!child || child.startsWith("..") || isAbsolute(child)) {
    failure(`${path} escapes its build root`);
  }
}

/**
 * @param {string} path
 * @param {string} root
 * @returns {Promise<any>}
 */
async function jsonFile(path, root) {
  await ordinaryFile(path, root);
  return JSON.parse(await readFile(path, "utf8"));
}

/**
 * @param {string} repositoryRoot
 * @param {string[]} arguments_
 */
async function git(repositoryRoot, arguments_) {
  return execFile("git", arguments_, { cwd: repositoryRoot }).then(
    ({ stdout }) => stdout.trim(),
    (error) =>
      failure(
        `Git source validation failed: ${error instanceof Error ? error.message : String(error)}`,
      ),
  );
}

/** @param {string} lock */
function versionFromLock(lock) {
  const match =
    /^\[pyble\]$(?:\r?\n(?!\[)[^\r\n]*)*?\r?\nagent_version\s*=\s*"([^"]+)"/m.exec(
      lock,
    );
  if (!match) {
    failure("firmware/versions.lock has no [pyble] agent_version");
  }
  const version = match[1];
  if (
    !version ||
    !/^(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)$/.test(version)
  ) {
    failure("firmware/versions.lock has no canonical [pyble] agent_version");
  }
  return version;
}

/** @param {string} lock @param {string} section @param {string} key */
function valueFromLock(lock, section, key) {
  let active = "";
  for (const rawLine of lock.split(/\r?\n/)) {
    const line = rawLine.trim();
    const heading = /^\[([^\]]+)\]$/.exec(line);
    if (heading) {
      active = heading[1] ?? "";
      continue;
    }
    if (active !== section) {
      continue;
    }
    const assignment = /^([a-z_]+)\s*=\s*"([^"]+)"$/.exec(line);
    if (assignment?.[1] === key) {
      return assignment[2];
    }
  }
  failure(`firmware/versions.lock has no [${section}] ${key}`);
}

/**
 * @param {any} provenance
 * @param {string} expectedTarget
 * @param {{commit: string | null, epoch: number | null}} sourceIdentity
 * @param {string} label
 * @param {string} expectedMicropython
 * @param {string} expectedEspIdf
 */
function validateProvenance(
  provenance,
  expectedTarget,
  sourceIdentity,
  label,
  expectedMicropython,
  expectedEspIdf,
) {
  if (
    !hasExactKeys(provenance, [
      "esp_idf",
      "micropython",
      "pyble",
      "schema_version",
      "source_date_epoch",
      "target",
    ]) ||
    provenance?.schema_version !== 1 ||
    provenance?.target !== expectedTarget ||
    provenance?.pyble?.clean !== true ||
    typeof provenance?.pyble?.commit !== "string" ||
    !/^[0-9a-f]{40}$/.test(provenance.pyble.commit) ||
    !Number.isInteger(provenance?.source_date_epoch) ||
    provenance.source_date_epoch <= 0 ||
    !hasExactKeys(provenance.pyble, ["clean", "commit"]) ||
    !hasExactKeys(provenance.micropython, ["commit"]) ||
    !hasExactKeys(provenance.esp_idf, ["commit"]) ||
    provenance.micropython.commit !== expectedMicropython ||
    provenance.esp_idf.commit !== expectedEspIdf
  ) {
    failure(`${label} provenance is invalid or not clean`);
  }
  if (sourceIdentity.commit === null) {
    sourceIdentity.commit = provenance.pyble.commit;
    sourceIdentity.epoch = provenance.source_date_epoch;
  } else if (
    sourceIdentity.commit !== provenance.pyble.commit ||
    sourceIdentity.epoch !== provenance.source_date_epoch
  ) {
    failure("build provenance mixes source commits or source epochs");
  }
}

/**
 * @param {string} repositoryRoot
 * @param {string} target
 * @param {string} buildRoot
 */
async function canonicalEspBuildValidator(repositoryRoot, target, buildRoot) {
  const validator = join(
    repositoryRoot,
    "firmware",
    "scripts",
    "release_bundle.py",
  );
  await ordinaryFile(validator, repositoryRoot);
  await execFile("python3", [validator, "validate-build", target, buildRoot], {
    cwd: repositoryRoot,
  }).catch((error) =>
    failure(
      `${target} failed canonical build validation: ${error instanceof Error ? error.message : String(error)}`,
    ),
  );
}

/**
 * @param {any} value
 * @param {(typeof espProfiles)[number]} profile
 */
function validateFlasherArguments(value, profile) {
  const settings = value?.flash_settings;
  const files = value?.flash_files;
  if (
    settings?.flash_mode !== "dio" ||
    settings?.flash_size !== profile.flashSize ||
    settings?.flash_freq !== profile.flashFrequency ||
    typeof files !== "object" ||
    files === null ||
    !(profile.offset === 0
      ? Object.hasOwn(files, "0x0")
      : Object.hasOwn(files, "0x1000")) ||
    files["0x8000"] !== "partition_table/partition-table.bin" ||
    files["0x10000"] !== "micropython.bin"
  ) {
    failure(
      `${profile.buildTarget} flasher arguments do not match its exact profile`,
    );
  }
}

/**
 * @param {(typeof espProfiles)[number]} profile
 * @param {string} version
 */
function manifest(profile, version) {
  return {
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
  };
}

/** @param {string} path */
export async function validateRp2350Uf2(path) {
  const bytes = await readFile(path);
  if (!bytes.length || bytes.length % 512 !== 0) {
    failure("Pico 2 W firmware is not a complete UF2 stream");
  }
  const armBlocks = [];
  let extensionBlocks = 0;
  for (let offset = 0; offset < bytes.length; offset += 512) {
    if (
      bytes.readUInt32LE(offset) !== 0x0a324655 ||
      bytes.readUInt32LE(offset + 4) !== 0x9e5d5157 ||
      bytes.readUInt32LE(offset + 508) !== 0x0ab16f30
    ) {
      failure("Pico 2 W UF2 block magic is invalid");
    }
    const payloadBytes = bytes.readUInt32LE(offset + 16);
    if (payloadBytes === 0 || payloadBytes > 476) {
      failure("Pico 2 W UF2 payload length is invalid");
    }
    const flags = bytes.readUInt32LE(offset + 8);
    const family = bytes.readUInt32LE(offset + 28);
    if (flags === 0x00002000 && family === 0xe48bff59) {
      armBlocks.push({
        address: bytes.readUInt32LE(offset + 12),
        blockNumber: bytes.readUInt32LE(offset + 20),
        payload: bytes.subarray(offset + 32, offset + 32 + payloadBytes),
        payloadBytes,
        totalBlocks: bytes.readUInt32LE(offset + 24),
      });
    } else if (
      flags === 0x0000a000 &&
      family === 0xe48bff57 &&
      bytes.readUInt32LE(offset + 12) === 0x10ffff00 &&
      payloadBytes === 256 &&
      bytes.readUInt32LE(offset + 20) === 0 &&
      bytes.readUInt32LE(offset + 24) === 2
    ) {
      extensionBlocks += 1;
    } else {
      failure("Pico 2 W UF2 contains an unexpected family or flag block");
    }
  }
  if (armBlocks.length === 0 || extensionBlocks !== 1) {
    failure("Pico 2 W UF2 does not contain RP2350 Arm image blocks");
  }
  const totalBlocks = armBlocks[0].totalBlocks;
  const payloadBytes = armBlocks[0].payloadBytes;
  const baseAddress = armBlocks[0].address;
  if (
    totalBlocks !== armBlocks.length ||
    payloadBytes !== 256 ||
    baseAddress !== 0x10000000 ||
    armBlocks.some(
      (block, index) =>
        block.totalBlocks !== totalBlocks ||
        block.payloadBytes !== payloadBytes ||
        block.blockNumber !== index ||
        block.address !== baseAddress + index * payloadBytes,
    )
  ) {
    failure("Pico 2 W UF2 RP2350 Arm block sequence is incomplete");
  }
  return Buffer.concat(armBlocks.map(({ payload }) => payload));
}

/**
 * @param {{repositoryRoot: string, espBuildRoot: string, rp2BuildRoot: string,
 * espBuildValidator?: (repositoryRoot: string, target: string, buildRoot: string) => Promise<void>,
 * uf2Validator?: (path: string) => Promise<void>}} options
 */
export async function stageLocalFirmwarePreview({
  repositoryRoot,
  espBuildRoot,
  rp2BuildRoot,
  espBuildValidator = canonicalEspBuildValidator,
  uf2Validator = async () => undefined,
}) {
  for (const [label, path] of Object.entries({
    repositoryRoot,
    espBuildRoot,
    rp2BuildRoot,
  })) {
    if (typeof path !== "string" || !isAbsolute(path)) {
      failure(`${label} must be an explicit path`);
    }
  }

  const canonicalRepositoryRoot = await realpath(repositoryRoot);
  const checkoutRoot = await git(canonicalRepositoryRoot, [
    "rev-parse",
    "--show-toplevel",
  ]);
  if ((await realpath(checkoutRoot)) !== canonicalRepositoryRoot) {
    failure("repositoryRoot must be the exact Git checkout root");
  }
  const outputDirectory = join(
    canonicalRepositoryRoot,
    "tools",
    "web",
    "public",
    ".pyble-local-preview",
  );

  const lockPath = join(canonicalRepositoryRoot, "firmware", "versions.lock");
  await ordinaryFile(lockPath, canonicalRepositoryRoot);
  const lock = await readFile(lockPath, "utf8");
  const version = versionFromLock(lock);
  const expectedMicropython = valueFromLock(lock, "micropython", "commit");
  const expectedEspIdf = valueFromLock(lock, "esp_idf", "commit");
  /** @type {{commit: string | null, epoch: number | null}} */
  const sourceIdentity = { commit: null, epoch: null };
  const stagedEsp = [];

  for (const profile of espProfiles) {
    const buildRoot = join(espBuildRoot, profile.buildTarget);
    await espBuildValidator(
      canonicalRepositoryRoot,
      profile.buildTarget,
      buildRoot,
    );
    const firmwarePath = join(buildRoot, "firmware.bin");
    const flasherPath = join(buildRoot, "flasher_args.json");
    const provenancePath = join(buildRoot, "pyble-build-provenance.json");
    await ordinaryFile(firmwarePath, buildRoot);
    const [flasherArguments, provenance, firmwareBytes] = await Promise.all([
      jsonFile(flasherPath, buildRoot),
      jsonFile(provenancePath, buildRoot),
      readFile(firmwarePath),
    ]);
    validateFlasherArguments(flasherArguments, profile);
    validateProvenance(
      provenance,
      profile.buildTarget,
      sourceIdentity,
      profile.buildTarget,
      expectedMicropython,
      expectedEspIdf,
    );
    stagedEsp.push({ profile, firmwareBytes });
  }

  const picoRoot = join(rp2BuildRoot, "rpi-pico2-w");
  const picoFirmwarePath = join(picoRoot, "firmware.uf2");
  const picoBinPath = join(picoRoot, "firmware.bin");
  const picoElfPath = join(picoRoot, "firmware.elf");
  const picoProvenancePath = join(picoRoot, "pyble-build-provenance.json");
  await Promise.all([
    ordinaryFile(picoFirmwarePath, picoRoot),
    ordinaryFile(picoBinPath, picoRoot),
    ordinaryFile(picoElfPath, picoRoot),
  ]);
  const [picoProvenance, picoFirmwareBytes, picoBinBytes, reconstructedBin] =
    await Promise.all([
      jsonFile(picoProvenancePath, picoRoot),
      readFile(picoFirmwarePath),
      readFile(picoBinPath),
      validateRp2350Uf2(picoFirmwarePath),
      uf2Validator(picoFirmwarePath),
    ]);
  if (
    !hasExactKeys(picoProvenance, [
      "arm_gnu_toolchain",
      "board",
      "firmware_bin_bytes",
      "micropython",
      "picotool",
      "port",
      "pyble",
      "schema_version",
      "source_date_epoch",
      "target",
    ]) ||
    picoProvenance.schema_version !== 1 ||
    picoProvenance.target !== "rpi-pico2-w" ||
    picoProvenance.port !== "rp2" ||
    picoProvenance.board !== "PYBLE_RPI_PICO2_W" ||
    !hasExactKeys(picoProvenance.pyble, ["clean", "commit"]) ||
    picoProvenance.pyble.clean !== true ||
    !/^[0-9a-f]{40}$/.test(picoProvenance.pyble.commit) ||
    !hasExactKeys(picoProvenance.micropython, ["commit"]) ||
    picoProvenance.micropython.commit !== expectedMicropython ||
    !hasExactKeys(picoProvenance.arm_gnu_toolchain, ["gcc", "release"]) ||
    picoProvenance.arm_gnu_toolchain.release !==
      valueFromLock(lock, "arm_gnu_toolchain", "release") ||
    !String(picoProvenance.arm_gnu_toolchain.gcc).includes(
      valueFromLock(lock, "arm_gnu_toolchain", "gcc_version"),
    ) ||
    !/^picotool v2\.3\.0\b/.test(picoProvenance.picotool) ||
    picoProvenance.firmware_bin_bytes !== picoBinBytes.byteLength ||
    picoBinBytes.byteLength > 1_572_864 ||
    picoProvenance.source_date_epoch <= 0
  ) {
    failure("rpi-pico2-w provenance or sibling artifacts are invalid");
  }
  if (
    reconstructedBin
      .subarray(0, picoBinBytes.byteLength)
      .compare(picoBinBytes) !== 0 ||
    reconstructedBin
      .subarray(picoBinBytes.byteLength)
      .some((value) => value !== 0)
  ) {
    failure("Pico 2 W UF2 does not reconstruct its sibling firmware.bin");
  }
  if (sourceIdentity.commit === null) {
    sourceIdentity.commit = picoProvenance.pyble.commit;
    sourceIdentity.epoch = picoProvenance.source_date_epoch;
  } else if (
    sourceIdentity.commit !== picoProvenance.pyble.commit ||
    sourceIdentity.epoch !== picoProvenance.source_date_epoch
  ) {
    failure("build provenance mixes source commits or source epochs");
  }

  if (sourceIdentity.commit === null || sourceIdentity.epoch === null) {
    failure("build provenance did not select a source identity");
  }
  const sourceCommit = sourceIdentity.commit;
  const sourceEpoch = sourceIdentity.epoch;
  const head = await git(canonicalRepositoryRoot, ["rev-parse", "HEAD"]);
  await git(canonicalRepositoryRoot, [
    "merge-base",
    "--is-ancestor",
    sourceCommit,
    head,
  ]);
  const firmwareDiff = await git(canonicalRepositoryRoot, [
    "diff",
    "--name-only",
    sourceCommit,
    head,
    "--",
    "firmware",
  ]);
  const firmwareWorktree = await git(canonicalRepositoryRoot, [
    "status",
    "--porcelain",
    "--untracked-files=no",
    "--ignore-submodules=untracked",
    "--",
    "firmware",
  ]);
  if (firmwareDiff || firmwareWorktree) {
    failure("source firmware changed after the attested build commit");
  }

  const parent = dirname(outputDirectory);
  await mkdir(parent, { recursive: true });
  if ((await realpath(parent)) !== parent) {
    failure("local preview parent must not contain a symbolic link");
  }
  const existingOutput = await lstat(outputDirectory).catch((error) => {
    if (error?.code === "ENOENT") {
      return null;
    }
    throw error;
  });
  if (
    existingOutput?.isSymbolicLink() ||
    (existingOutput && !existingOutput.isDirectory())
  ) {
    failure("local preview output must be an ordinary directory");
  }
  const stagingRoot = await mkdtemp(join(parent, ".pyble-preview-stage-"));
  try {
    const profiles = [];
    for (const { profile, firmwareBytes } of stagedEsp) {
      const profileRoot = join(stagingRoot, profile.id);
      await mkdir(profileRoot, { recursive: true });
      const manifestBytes = Buffer.from(
        `${JSON.stringify(manifest(profile, version), null, 2)}\n`,
        "utf8",
      );
      await Promise.all([
        writeFile(join(profileRoot, "manifest.json"), manifestBytes),
        writeFile(join(profileRoot, "firmware.bin"), firmwareBytes),
      ]);
      profiles.push({
        id: profile.id,
        label: profile.label,
        chipFamily: profile.chipFamily,
        buildTarget: profile.buildTarget,
        method: "esp-web-tools",
        qualified: false,
        status: "engineering-preview",
        offset: profile.offset,
        manifest: {
          path: `/.pyble-local-preview/${profile.id}/manifest.json`,
          size: manifestBytes.byteLength,
          sha256: sha256(manifestBytes),
        },
        firmware: {
          path: `/.pyble-local-preview/${profile.id}/firmware.bin`,
          size: firmwareBytes.byteLength,
          sha256: sha256(firmwareBytes),
        },
      });
    }

    const picoOutput = join(stagingRoot, "rpi-pico2-w");
    await mkdir(picoOutput, { recursive: true });
    await writeFile(join(picoOutput, "firmware.uf2"), picoFirmwareBytes);
    profiles.push({
      id: "rpi-pico2-w",
      label: "Raspberry Pi Pico 2 W",
      chipFamily: "RP2350",
      buildTarget: "rpi-pico2-w",
      method: "uf2-download",
      qualified: false,
      status: "engineering-preview",
      firmware: {
        path: "/.pyble-local-preview/rpi-pico2-w/firmware.uf2",
        size: picoFirmwareBytes.byteLength,
        sha256: sha256(picoFirmwareBytes),
      },
    });

    const descriptor = {
      schemaVersion: 1,
      deployment: "local-preview",
      localOnly: true,
      qualified: false,
      version,
      sourceCommit,
      builtAt: new Date(sourceEpoch * 1000).toISOString(),
      profiles,
    };
    await writeFile(
      join(stagingRoot, "descriptor.json"),
      `${JSON.stringify(descriptor, null, 2)}\n`,
      "utf8",
    );
    await rm(outputDirectory, { recursive: true, force: true });
    await rename(stagingRoot, outputDirectory);
    return descriptor;
  } catch (error) {
    await rm(stagingRoot, { recursive: true, force: true });
    throw error;
  }
}

async function main() {
  const packageRoot = fileURLToPath(new URL("..", import.meta.url));
  const repositoryRoot = resolve(packageRoot, "..", "..");
  const espBuildRoot = process.env.PYBLE_LOCAL_ESP_BUILD_ROOT;
  const rp2BuildRoot = process.env.PYBLE_LOCAL_RP2_BUILD_ROOT;
  if (!espBuildRoot || !rp2BuildRoot) {
    failure(
      "PYBLE_LOCAL_ESP_BUILD_ROOT and PYBLE_LOCAL_RP2_BUILD_ROOT are required",
    );
  }
  const descriptor = await stageLocalFirmwarePreview({
    repositoryRoot,
    espBuildRoot: resolve(espBuildRoot),
    rp2BuildRoot: resolve(rp2BuildRoot),
  });
  process.stdout.write(
    `Local engineering preview staged: v${descriptor.version}, ${descriptor.profiles.length} profiles\n`,
  );
}

if (
  process.argv[1] &&
  resolve(process.argv[1]) === fileURLToPath(import.meta.url)
) {
  main().catch((error) => {
    process.stderr.write(
      `${error instanceof Error ? error.message : String(error)}\n`,
    );
    process.exitCode = 1;
  });
}

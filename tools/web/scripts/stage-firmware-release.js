// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

import {
  cp,
  lstat,
  mkdir,
  mkdtemp,
  readFile,
  readdir,
  rename,
  rm,
  rmdir,
  writeFile,
} from "node:fs/promises";
import { execFile as execFileCallback } from "node:child_process";
import { createHash } from "node:crypto";
import {
  basename,
  dirname,
  isAbsolute,
  join,
  relative,
  resolve,
} from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { isDeepStrictEqual, promisify } from "node:util";

const execFile = promisify(execFileCallback);
const canonicalSemverPattern =
  /^(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)(?:-(?:0|[1-9][0-9]*|[0-9]*[A-Za-z-][0-9A-Za-z-]*)(?:\.(?:0|[1-9][0-9]*|[0-9]*[A-Za-z-][0-9A-Za-z-]*))*)?(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$/;
const publicBetaVersion = "0.4.1";
const publicBetaReleaseJsonSha256 =
  "8b84fbb65a0463d20369e1d86dac566ca7a2039ebc30f9186f55c05421962445";

function packageDirectory() {
  try {
    return fileURLToPath(new URL("..", import.meta.url));
  } catch {
    // Vite gives imported test modules a virtual URL. Tests execute from the
    // package root; the production CLI always takes the file-URL branch.
    return process.cwd();
  }
}

const profileTable = [
  {
    id: "esp32-4mb",
    label: "ESP32 · 4 MiB flash",
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
    chipFamily: "ESP32-S3",
    offset: 0,
    flashSizeBytes: 16 * 1024 * 1024,
    flashFrequencyHz: 80_000_000,
    siliconRevision: { minimumFull: 0, maximumFull: 99 },
    psram: { required: true, sizeBytes: 8 * 1024 * 1024, type: "octal" },
  },
];

/**
 * @param {string} message
 * @returns {never}
 */
function failure(message) {
  throw new Error(`Firmware staging failed: ${message}`);
}

/**
 * @param {unknown} value
 * @returns {value is Record<string, unknown>}
 */
function isObject(value) {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/**
 * @param {unknown} value
 * @param {string} label
 * @returns {Record<string, any>}
 */
function asObject(value, label) {
  if (!isObject(value)) {
    failure(`${label} must be an object`);
  }
  return value;
}

/**
 * @param {Record<string, any>} value
 * @param {string[]} keys
 * @param {string} label
 */
function exactKeys(value, keys, label) {
  const actual = Object.keys(value).sort();
  const expected = [...keys].sort();
  if (
    actual.length !== expected.length ||
    actual.some((key, index) => key !== expected[index])
  ) {
    failure(`${label} has an invalid shape`);
  }
}

/**
 * @param {unknown} value
 * @param {string} label
 * @returns {string}
 */
function asString(value, label) {
  if (typeof value !== "string" || !value) {
    failure(`${label} must be a non-empty string`);
  }
  return value;
}

/**
 * @param {unknown} value
 * @param {string} label
 * @param {number} [minimum]
 * @returns {number}
 */
function asInteger(value, label, minimum = 0) {
  if (
    typeof value !== "number" ||
    !Number.isInteger(value) ||
    value < minimum
  ) {
    failure(`${label} must be an integer of at least ${minimum}`);
  }
  return value;
}

/**
 * @param {unknown} actual
 * @param {unknown} expected
 * @param {string} label
 */
function equal(actual, expected, label) {
  if (actual !== expected) {
    failure(`${label} does not match the frozen profile`);
  }
}

/**
 * @param {unknown} value
 * @param {string} label
 * @returns {string}
 */
function safePath(value, label) {
  const path = asString(value, label);
  if (
    path.startsWith("/") ||
    path.includes("\\") ||
    path.includes("?") ||
    path.includes("#") ||
    path.includes("://") ||
    path.split("/").some((part) => part === "." || part === "..")
  ) {
    failure(`${label} is unsafe`);
  }
  return path;
}

/**
 * @param {string | Uint8Array} bytes
 * @returns {string}
 */
function sha256(bytes) {
  return createHash("sha256").update(bytes).digest("hex");
}

/**
 * Run the canonical firmware release validator. This is deliberately not
 * configurable through the environment: production staging must execute the
 * reviewed repository tool, not an arbitrary substitute.
 *
 * @param {string} bundleDirectory
 * @param {"public" | "candidate"} deployment
 */
export async function validateWithCanonicalReleaseTool(
  bundleDirectory,
  deployment,
) {
  const repositoryRoot = resolve(packageDirectory(), "..", "..");
  const canonicalReleaseTool = join(
    repositoryRoot,
    "firmware",
    "scripts",
    "release_bundle.py",
  );
  const arguments_ = [
    canonicalReleaseTool,
    "validate",
    resolve(bundleDirectory),
  ];
  const mode =
    deployment === "public"
      ? "--public"
      : deployment === "candidate"
        ? "--audited-candidate"
        : failure("canonical validation deployment is invalid");
  const licenseEvidenceDirectory =
    process.env.PYBLE_FIRMWARE_LICENSE_EVIDENCE_DIR;
  const licenseBuildRoot = process.env.PYBLE_FIRMWARE_LICENSE_BUILD_ROOT;
  if (!licenseEvidenceDirectory) {
    failure(
      `PYBLE_FIRMWARE_LICENSE_EVIDENCE_DIR is required for ${deployment} validation`,
    );
  }
  if (!licenseBuildRoot) {
    failure(
      `PYBLE_FIRMWARE_LICENSE_BUILD_ROOT is required for ${deployment} validation`,
    );
  }
  arguments_.push(
    mode,
    "--license-evidence-dir",
    resolve(licenseEvidenceDirectory),
    "--license-build-root",
    resolve(licenseBuildRoot),
    "--repo-root",
    repositoryRoot,
  );
  try {
    await execFile("python3", arguments_, {
      cwd: repositoryRoot,
      maxBuffer: 16 * 1024 * 1024,
    });
  } catch (error) {
    const detail =
      error instanceof Error && "stderr" in error && error.stderr
        ? `: ${String(error.stderr).trim()}`
        : "";
    failure(
      `canonical release_bundle.py validation rejected the bundle${detail}`,
    );
  }
}

/**
 * Validate the identity root for the one retained public-beta bundle. The
 * structural, schema, path, size, checksum, and profile checks still run in
 * validateReleaseBundle; this function prevents any other self-consistent
 * pending bundle from entering the exceptional deployment mode.
 *
 * @param {string} bundleDirectory
 * @param {"public" | "candidate" | "public-beta"} deployment
 */
export async function validateAttestedPublicBetaBundle(
  bundleDirectory,
  deployment,
) {
  if (deployment !== "public-beta") {
    failure("attested public-beta validation has an invalid deployment");
  }
  const releaseBytes = await readFile(
    join(resolve(bundleDirectory), "release.json"),
  );
  if (sha256(releaseBytes) !== publicBetaReleaseJsonSha256) {
    failure("bundle is not the exact attested v0.4.1 public beta");
  }
}

/**
 * @param {string} bundleDirectory
 * @param {"public" | "candidate" | "public-beta"} deployment
 */
export async function validateFreshDeploymentBundle(
  bundleDirectory,
  deployment,
) {
  if (deployment === "public-beta") {
    return validateAttestedPublicBetaBundle(bundleDirectory, deployment);
  }
  return validateWithCanonicalReleaseTool(bundleDirectory, deployment);
}

/**
 * @param {string} bundleDirectory
 * @param {"public" | "candidate" | "public-beta"} deployment
 */
async function validatePreservedDeploymentBundle(bundleDirectory, deployment) {
  if (deployment === "public-beta") {
    return validateAttestedPublicBetaBundle(bundleDirectory, deployment);
  }
  return validatePreviouslyActivatedPublicWithCanonicalReleaseTool(
    bundleDirectory,
    deployment,
  );
}

/**
 * Re-run every self-contained public-release check for bytes that were already
 * activated through the fresh license-evidence gate. The deployment wrapper
 * permits this mode only for an exact selector recovered from its current
 * managed release.
 *
 * @param {string} bundleDirectory
 * @param {"public" | "candidate"} deployment
 */
export async function validatePreviouslyActivatedPublicWithCanonicalReleaseTool(
  bundleDirectory,
  deployment,
) {
  if (deployment !== "public") {
    failure("preserved activation accepts only a public release");
  }
  const repositoryRoot = resolve(packageDirectory(), "..", "..");
  const canonicalReleaseTool = join(
    repositoryRoot,
    "firmware",
    "scripts",
    "release_bundle.py",
  );
  try {
    await execFile(
      "python3",
      [
        canonicalReleaseTool,
        "validate",
        resolve(bundleDirectory),
        "--previously-activated-public",
        "--qualification-repo-root",
        repositoryRoot,
      ],
      {
        cwd: repositoryRoot,
        maxBuffer: 16 * 1024 * 1024,
      },
    );
  } catch (error) {
    const detail =
      error instanceof Error && "stderr" in error && error.stderr
        ? `: ${String(error.stderr).trim()}`
        : "";
    failure(
      `canonical preserved-public validation rejected the bundle${detail}`,
    );
  }
}

/**
 * @param {unknown} value
 * @param {string} label
 */
function validateCommit(value, label) {
  const commit = asString(value, label);
  if (!/^[0-9a-f]{40}$/.test(commit)) {
    failure(`${label} must be a full lowercase commit`);
  }
}

/** @param {unknown} value */
function validateProvenance(value) {
  const provenance = asObject(value, "release provenance");
  exactKeys(
    provenance,
    ["pyble", "micropython", "esp_idf", "patch_count", "runner", "tools"],
    "release provenance",
  );

  const pyble = asObject(provenance.pyble, "release provenance.pyble");
  exactKeys(pyble, ["commit", "clean"], "release provenance.pyble");
  validateCommit(pyble.commit, "release provenance.pyble.commit");
  equal(pyble.clean, true, "release provenance clean state");

  for (const key of ["micropython", "esp_idf"]) {
    const upstream = asObject(provenance[key], `release provenance.${key}`);
    exactKeys(upstream, ["ref", "commit"], `release provenance.${key}`);
    asString(upstream.ref, `release provenance.${key}.ref`);
    validateCommit(upstream.commit, `release provenance.${key}.commit`);
  }

  asInteger(provenance.patch_count, "release provenance.patch_count");
  const runner = asObject(provenance.runner, "release provenance.runner");
  exactKeys(runner, ["os", "architecture"], "release provenance.runner");
  asString(runner.os, "release provenance.runner.os");
  asString(runner.architecture, "release provenance.runner.architecture");

  if (!Array.isArray(provenance.tools) || provenance.tools.length === 0) {
    failure("release provenance.tools must contain at least one tool");
  }
  provenance.tools.forEach((value, index) => {
    const tool = asObject(value, `release provenance.tools[${index}]`);
    exactKeys(tool, ["name", "version"], `release provenance.tools[${index}]`);
    asString(tool.name, `release provenance.tools[${index}].name`);
    asString(tool.version, `release provenance.tools[${index}].version`);
  });
}

/** @param {string} bundleDirectory */
async function validateCanonicalSchema(bundleDirectory) {
  const canonicalSchemaPath = join(
    packageDirectory(),
    "src",
    "lib",
    "firmware-release-schema.json",
  );
  let actual;
  let expected;
  try {
    [actual, expected] = await Promise.all([
      readFile(join(bundleDirectory, "release.schema.json"), "utf8").then(
        JSON.parse,
      ),
      readFile(canonicalSchemaPath, "utf8").then(JSON.parse),
    ]);
  } catch (error) {
    throw new Error("Firmware staging failed: release schema is invalid", {
      cause: error,
    });
  }
  if (!isDeepStrictEqual(actual, expected)) {
    failure("release schema does not equal the canonical frozen schema");
  }
}

/**
 * @param {string} root
 * @returns {Promise<string[]>}
 */
async function allFiles(root) {
  /** @type {string[]} */
  const found = [];
  /** @param {string} directory */
  async function visit(directory) {
    const entries = await readdir(directory, { withFileTypes: true });
    entries.sort((left, right) => left.name.localeCompare(right.name));
    for (const entry of entries) {
      const path = join(directory, entry.name);
      const metadata = await lstat(path);
      if (metadata.isSymbolicLink()) {
        failure("bundle must not contain symbolic links");
      }
      if (metadata.isDirectory()) {
        await visit(path);
      } else if (metadata.isFile()) {
        found.push(relative(root, path).split("\\").join("/"));
      } else {
        failure(`unsupported bundle entry: ${entry.name}`);
      }
    }
  }
  await visit(root);
  return found.sort();
}

/** @param {string} bundleDirectory */
async function verifySums(bundleDirectory) {
  const sumsText = await readFile(join(bundleDirectory, "SHA256SUMS"), "utf8");
  const declared = new Map();
  for (const line of sumsText.split("\n")) {
    if (!line) {
      continue;
    }
    const match = /^([0-9a-f]{64}) {2}(.+)$/.exec(line);
    if (!match) {
      failure("SHA256SUMS has a non-conventional entry");
    }
    const path = safePath(match[2], "SHA256SUMS path");
    if (path === "SHA256SUMS" || declared.has(path)) {
      failure("SHA256SUMS contains a duplicate or self entry");
    }
    declared.set(path, match[1]);
  }

  const actual = (await allFiles(bundleDirectory)).filter(
    (path) => path !== "SHA256SUMS",
  );
  if (
    actual.length !== declared.size ||
    actual.some((path) => !declared.has(path))
  ) {
    failure("SHA256SUMS does not cover the exact bundle");
  }
  for (const path of actual) {
    const bytes = await readFile(join(bundleDirectory, path));
    if (sha256(bytes) !== declared.get(path)) {
      failure(`checksum mismatch for ${path}`);
    }
  }
}

/**
 * @param {string} bundleDirectory
 * @param {unknown} value
 * @param {string} expectedPath
 * @param {string} label
 */
async function verifyArtifact(bundleDirectory, value, expectedPath, label) {
  const record = asObject(value, label);
  exactKeys(record, ["path", "size", "sha256"], label);
  const path = safePath(record.path, `${label}.path`);
  equal(path, expectedPath, `${label}.path`);
  const size = asInteger(record.size, `${label}.size`, 1);
  const hash = asString(record.sha256, `${label}.sha256`);
  if (!/^[0-9a-f]{64}$/.test(hash)) {
    failure(`${label}.sha256 is invalid`);
  }
  const bytes = await readFile(join(bundleDirectory, path));
  equal(bytes.byteLength, size, `${label}.size`);
  equal(sha256(bytes), hash, `${label}.sha256`);
  return { path, size, sha256: hash };
}

/**
 * @param {string} bundleDirectory
 * @param {unknown} value
 * @param {string} expectedPath
 * @param {number} expectedOffset
 * @param {string} label
 */
async function verifyInstall(
  bundleDirectory,
  value,
  expectedPath,
  expectedOffset,
  label,
) {
  const record = asObject(value, label);
  exactKeys(record, ["path", "size", "sha256", "offset"], label);
  const artifact = await verifyArtifact(
    bundleDirectory,
    {
      path: record.path,
      size: record.size,
      sha256: record.sha256,
    },
    expectedPath,
    label,
  );
  equal(
    asInteger(record.offset, `${label}.offset`),
    expectedOffset,
    `${label}.offset`,
  );
  return { ...artifact, offset: expectedOffset };
}

/**
 * @param {string} bundleDirectory
 * @param {string} version
 * @param {(typeof profileTable)[number]} profile
 * @param {{ path: string }} artifact
 */
async function verifyManifest(bundleDirectory, version, profile, artifact) {
  const value = JSON.parse(
    await readFile(join(bundleDirectory, artifact.path), "utf8"),
  );
  const manifest = asObject(value, `${profile.id} manifest`);
  exactKeys(
    manifest,
    [
      "name",
      "version",
      "new_install_prompt_erase",
      "new_install_improv_wait_time",
      "builds",
    ],
    `${profile.id} manifest`,
  );
  equal(manifest.name, "PyBLE", `${profile.id} manifest name`);
  equal(manifest.version, version, `${profile.id} manifest version`);
  equal(
    manifest.new_install_prompt_erase,
    false,
    `${profile.id} erase behavior`,
  );
  equal(manifest.new_install_improv_wait_time, 0, `${profile.id} Improv wait`);
  if (!Array.isArray(manifest.builds) || manifest.builds.length !== 1) {
    failure(`${profile.id} manifest must contain one build`);
  }
  const build = asObject(manifest.builds[0], `${profile.id} build`);
  exactKeys(build, ["chipFamily", "parts"], `${profile.id} build`);
  equal(build.chipFamily, profile.chipFamily, `${profile.id} family`);
  if (!Array.isArray(build.parts) || build.parts.length !== 1) {
    failure(`${profile.id} manifest must contain one part`);
  }
  const part = asObject(build.parts[0], `${profile.id} part`);
  exactKeys(part, ["path", "offset"], `${profile.id} part`);
  equal(
    safePath(part.path, `${profile.id} part path`),
    "firmware.bin",
    `${profile.id} part path`,
  );
  equal(
    asInteger(part.offset, `${profile.id} part offset`),
    profile.offset,
    `${profile.id} part offset`,
  );
}

/**
 * @param {string} bundleDirectory
 * @param {"public" | "candidate" | "public-beta"} deployment
 * @param {boolean} accessControlled
 * @param {(bundleDirectory: string, deployment: "public" | "candidate" | "public-beta") => Promise<void>} releaseValidator
 */
async function validateReleaseBundle(
  bundleDirectory,
  deployment,
  accessControlled,
  releaseValidator,
) {
  if (typeof releaseValidator !== "function") {
    failure("an explicit canonical release validator is required");
  }
  await releaseValidator(bundleDirectory, deployment);
  await verifySums(bundleDirectory);
  await validateCanonicalSchema(bundleDirectory);
  const releaseBytes = await readFile(join(bundleDirectory, "release.json"));
  const release = asObject(
    JSON.parse(releaseBytes.toString("utf8")),
    "release",
  );
  const releaseFilesKey = ["docu", "ments"].join("");
  exactKeys(
    release,
    [
      "schema_version",
      "identity",
      "provenance",
      "installer",
      "profiles",
      releaseFilesKey,
    ],
    "release",
  );
  equal(release.schema_version, 2, "schema version");

  const identity = asObject(release.identity, "release identity");
  exactKeys(
    identity,
    ["version", "tag", "agent_version", "protocol_version", "built_at"],
    "release identity",
  );
  const version = asString(identity.version, "release version");
  if (!canonicalSemverPattern.test(version)) {
    failure("release version is not canonical SemVer");
  }
  equal(identity.tag, `firmware-v${version}`, "release tag");
  equal(identity.agent_version, version, "agent version");
  equal(identity.protocol_version, "PBLE/1", "protocol version");
  const builtAt = asString(identity.built_at, "build time");
  if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/.test(builtAt)) {
    failure("build time is invalid");
  }

  validateProvenance(release.provenance);
  const installer = asObject(release.installer, "installer");
  exactKeys(installer, ["package", "version"], "installer");
  equal(installer.package, "esp-web-tools", "installer package");
  equal(installer.version, "10.4.0", "installer version");

  if (
    !Array.isArray(release.profiles) ||
    release.profiles.length !== profileTable.length
  ) {
    failure("release must contain exactly the two current release profiles");
  }
  const statuses = [];
  for (const [index, profile] of profileTable.entries()) {
    const value = asObject(release.profiles[index], `${profile.id} profile`);
    exactKeys(
      value,
      [
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
      `${profile.id} profile`,
    );
    equal(value.id, profile.id, `${profile.id} ID`);
    equal(value.chip_family, profile.chipFamily, `${profile.id} family`);

    const requirements = asObject(
      value.requirements,
      `${profile.id} requirements`,
    );
    exactKeys(
      requirements,
      ["flash_size_bytes", "psram"],
      `${profile.id} requirements`,
    );
    equal(
      requirements.flash_size_bytes,
      profile.flashSizeBytes,
      `${profile.id} flash size`,
    );
    const psram = asObject(requirements.psram, `${profile.id} PSRAM`);
    exactKeys(psram, ["required", "size_bytes", "type"], `${profile.id} PSRAM`);
    equal(psram.required, profile.psram.required, `${profile.id} PSRAM`);
    equal(
      psram.size_bytes,
      profile.psram.sizeBytes,
      `${profile.id} PSRAM size`,
    );
    equal(psram.type, profile.psram.type, `${profile.id} PSRAM type`);

    const flash = asObject(value.flash, `${profile.id} flash`);
    exactKeys(flash, ["mode", "frequency_hz"], `${profile.id} flash`);
    equal(flash.mode, "dio", `${profile.id} flash mode`);
    equal(
      flash.frequency_hz,
      profile.flashFrequencyHz,
      `${profile.id} flash frequency`,
    );
    const revision = asObject(
      value.silicon_revision,
      `${profile.id} silicon revision`,
    );
    exactKeys(
      revision,
      ["minimum_full", "maximum_full"],
      `${profile.id} silicon revision`,
    );
    equal(
      revision.minimum_full,
      profile.siliconRevision.minimumFull,
      `${profile.id} minimum silicon revision`,
    );
    equal(
      revision.maximum_full,
      profile.siliconRevision.maximumFull,
      `${profile.id} maximum silicon revision`,
    );

    const status = asString(value.hil_status, `${profile.id} HIL status`);
    if (status !== "pending" && status !== "passed") {
      failure(`${profile.id} HIL status is invalid`);
    }
    statuses.push(status);
    const manifest = await verifyArtifact(
      bundleDirectory,
      value.manifest,
      `${profile.id}/manifest.json`,
      `${profile.id} manifest`,
    );
    await verifyManifest(bundleDirectory, version, profile, manifest);
    await verifyInstall(
      bundleDirectory,
      value.install,
      `${profile.id}/firmware.bin`,
      profile.offset,
      `${profile.id} install image`,
    );

    if (!Array.isArray(value.components) || value.components.length !== 3) {
      failure(`${profile.id} must contain exactly three components`);
    }
    const expectedComponents = [
      {
        role: "bootloader",
        path: `${profile.id}/bootloader.bin`,
        offset: profile.offset,
      },
      {
        role: "partition-table",
        path: `${profile.id}/partition-table.bin`,
        offset: 0x8000,
      },
      {
        role: "application",
        path: `${profile.id}/application.bin`,
        offset: 0x10000,
      },
    ];
    for (const [componentIndex, expected] of expectedComponents.entries()) {
      const label = `${profile.id} ${expected.role} component`;
      const component = asObject(value.components[componentIndex], label);
      exactKeys(component, ["role", "path", "size", "sha256", "offset"], label);
      equal(component.role, expected.role, `${label}.role`);
      await verifyInstall(
        bundleDirectory,
        {
          path: component.path,
          size: component.size,
          sha256: component.sha256,
          offset: component.offset,
        },
        expected.path,
        expected.offset,
        label,
      );
    }
  }

  if (
    deployment === "public" &&
    statuses.some((status) => status !== "passed")
  ) {
    failure("public bundles require passed HIL on every exact profile");
  }
  if (deployment === "candidate" && !accessControlled) {
    failure("candidate bundles require explicit access control");
  }
  if (deployment === "public-beta") {
    if (version !== publicBetaVersion) {
      failure("public beta must be the exact v0.4.1 version");
    }
    if (accessControlled) {
      failure("public beta must be unrestricted, not access-controlled");
    }
    if (statuses.some((status) => status !== "pending")) {
      failure("public beta HIL status must remain pending on both profiles");
    }
  }
  const hilStatus = statuses.every((status) => status === "passed")
    ? "passed"
    : "pending";

  const documents = asObject(release[releaseFilesKey], "release documents");
  const expectedDocuments = {
    third_party_licenses: "THIRD_PARTY_LICENSES.txt",
    release_notes: "RELEASE_NOTES.md",
    recovery: "RECOVERY.md",
    hil_report: "HIL_REPORT.md",
  };
  exactKeys(documents, Object.keys(expectedDocuments), "release documents");
  for (const [key, path] of Object.entries(expectedDocuments)) {
    await verifyArtifact(
      bundleDirectory,
      documents[key],
      path,
      `release document ${key}`,
    );
  }

  return {
    deployment,
    accessControlled,
    version,
    builtAt,
    hilStatus,
    releaseJson: {
      path: `/firmware/v${version}/release.json`,
      sha256: sha256(releaseBytes),
    },
    schemaPath: `/firmware/v${version}/release.schema.json`,
    recoveryPath: `/firmware/v${version}/RECOVERY.md`,
    profiles: profileTable.map((profile) => {
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
    }),
  };
}

/**
 * @param {{
 *   accessControlled: boolean;
 *   bundleDirectory: string;
 *   deployment: "public" | "candidate" | "public-beta";
 *   outputDirectory: string;
 *   releaseValidator: (bundleDirectory: string, deployment: "public" | "candidate" | "public-beta") => Promise<void>;
 * }} options
 */
export async function stageFirmwareRelease({
  accessControlled,
  bundleDirectory,
  deployment,
  outputDirectory,
  releaseValidator,
}) {
  if (
    deployment !== "public" &&
    deployment !== "candidate" &&
    deployment !== "public-beta"
  ) {
    failure("deployment must be public, candidate, or public-beta");
  }
  if (typeof releaseValidator !== "function") {
    failure("an explicit canonical release validator is required");
  }
  const source = resolve(bundleDirectory);
  const output = resolve(outputDirectory);
  const outputFromSource = relative(source, output);
  const sourceFromOutput = relative(output, source);
  if (
    outputFromSource === "" ||
    (!outputFromSource.startsWith("..") && !isAbsolute(outputFromSource)) ||
    (!sourceFromOutput.startsWith("..") && !isAbsolute(sourceFromOutput))
  ) {
    failure("input bundle and output directory must be disjoint");
  }
  const sourceMetadata = await lstat(source);
  if (sourceMetadata.isSymbolicLink() || !sourceMetadata.isDirectory()) {
    failure("bundle input must be an ordinary directory");
  }

  let outputPlaceholder = false;
  try {
    const outputMetadata = await lstat(output);
    if (outputMetadata.isSymbolicLink() || !outputMetadata.isDirectory()) {
      failure("output must be absent or an ordinary empty directory");
    }
    if ((await readdir(output)).length !== 0) {
      failure("output directory must be empty");
    }
    outputPlaceholder = true;
  } catch (error) {
    if (
      !(error instanceof Error) ||
      !("code" in error) ||
      error.code !== "ENOENT"
    ) {
      throw error;
    }
  }

  await mkdir(dirname(output), { recursive: true });
  const transactionRoot = await mkdtemp(
    join(dirname(output), `.${basename(output)}.incoming-`),
  );
  const copiedBundle = join(transactionRoot, ".bundle");
  let removedPlaceholder = false;
  try {
    await cp(source, copiedBundle, {
      recursive: true,
      errorOnExist: true,
      force: false,
    });
    const descriptor = await validateReleaseBundle(
      copiedBundle,
      deployment,
      accessControlled,
      releaseValidator,
    );
    const firmwareRoot = join(transactionRoot, "firmware");
    await mkdir(firmwareRoot);
    await rename(copiedBundle, join(firmwareRoot, `v${descriptor.version}`));

    await writeFile(
      join(transactionRoot, ".pyble-firmware-release-selection.json"),
      `${JSON.stringify(descriptor, null, 2)}\n`,
      { encoding: "utf8", flag: "wx" },
    );
    const revalidated = await validateStagedFirmwareRelease(transactionRoot, {
      releaseValidator,
    });

    if (outputPlaceholder) {
      await rmdir(output);
      removedPlaceholder = true;
    }
    await rename(transactionRoot, output);
    return revalidated;
  } catch (error) {
    await rm(transactionRoot, { recursive: true, force: true });
    if (removedPlaceholder) {
      await mkdir(output);
    }
    throw error;
  }
}

/**
 * Revalidate a previously staged tree immediately before a deployment build.
 * The descriptor is derived again from the copied immutable bytes; it is never
 * trusted merely because an earlier staging process wrote it.
 *
 * @param {string} stagedRoot
 * @param {{
 *   releaseValidator: (bundleDirectory: string, deployment: "public" | "candidate" | "public-beta") => Promise<void>;
 * }} options
 */
export async function validateStagedFirmwareRelease(
  stagedRoot,
  { releaseValidator },
) {
  if (typeof releaseValidator !== "function") {
    failure("an explicit canonical release validator is required");
  }
  const root = resolve(stagedRoot);
  const rootMetadata = await lstat(root);
  if (rootMetadata.isSymbolicLink() || !rootMetadata.isDirectory()) {
    failure("staged root must be an ordinary directory");
  }

  const rootEntries = await readdir(root, { withFileTypes: true });
  const rootEntryMap = new Map(rootEntries.map((entry) => [entry.name, entry]));
  if (
    rootEntries.length !== 2 ||
    !rootEntryMap.get(".pyble-firmware-release-selection.json")?.isFile() ||
    !rootEntryMap.get("firmware")?.isDirectory()
  ) {
    failure("staged root must contain only its selection and firmware tree");
  }
  for (const entry of rootEntries) {
    const metadata = await lstat(join(root, entry.name));
    if (metadata.isSymbolicLink()) {
      failure("staged root must not contain symbolic links");
    }
  }

  const selectionPath = join(root, ".pyble-firmware-release-selection.json");
  const selected = asObject(
    JSON.parse(await readFile(selectionPath, "utf8")),
    "staged selection",
  );
  const version = asString(selected.version, "staged selection version");
  if (!canonicalSemverPattern.test(version)) {
    failure("staged selection version is not canonical SemVer");
  }
  const deployment = selected.deployment;
  if (
    deployment !== "public" &&
    deployment !== "candidate" &&
    deployment !== "public-beta"
  ) {
    failure("staged selection deployment is invalid");
  }
  if (typeof selected.accessControlled !== "boolean") {
    failure("staged selection access control must be boolean");
  }

  const firmwareRoot = join(root, "firmware");
  const firmwareEntries = await readdir(firmwareRoot, {
    withFileTypes: true,
  });
  if (
    firmwareEntries.length !== 1 ||
    firmwareEntries[0]?.name !== `v${version}` ||
    !firmwareEntries[0].isDirectory()
  ) {
    failure("staged firmware tree must contain exactly the selected version");
  }
  const versionRoot = join(firmwareRoot, `v${version}`);
  const versionMetadata = await lstat(versionRoot);
  if (versionMetadata.isSymbolicLink() || !versionMetadata.isDirectory()) {
    failure("staged firmware version must be an ordinary directory");
  }

  const derived = await validateReleaseBundle(
    versionRoot,
    deployment,
    selected.accessControlled,
    releaseValidator,
  );
  if (!isDeepStrictEqual(selected, derived)) {
    failure("staged selection no longer matches the immutable firmware bytes");
  }
  return derived;
}

/**
 * Revalidate an exact staged tree recovered from the current managed website
 * release. Its original activation already supplied the fresh source/build
 * license evidence; this path accepts only the same all-HIL-passed public
 * bytes or the same exact digest-bound transitional public beta.
 *
 * @param {string} stagedRoot
 * @param {{
 *   releaseValidator: (bundleDirectory: string, deployment: "public" | "candidate" | "public-beta") => Promise<void>;
 * }} options
 */
export async function validatePreservedPublicFirmwareRelease(
  stagedRoot,
  { releaseValidator },
) {
  const descriptor = await validateStagedFirmwareRelease(stagedRoot, {
    releaseValidator,
  });
  const qualifiedPublic =
    descriptor.deployment === "public" &&
    descriptor.hilStatus === "passed" &&
    !descriptor.accessControlled;
  const publicBeta =
    descriptor.deployment === "public-beta" &&
    descriptor.version === publicBetaVersion &&
    descriptor.releaseJson.sha256 === publicBetaReleaseJsonSha256 &&
    descriptor.hilStatus === "pending" &&
    !descriptor.accessControlled;
  if (!qualifiedPublic && !publicBeta) {
    failure(
      "previously activated firmware must remain an unrestricted qualified public release or the exact public beta",
    );
  }
  return descriptor;
}

/**
 * Revalidate an all-HIL-passed public staged release and prove that a freshly
 * downloaded GitHub Release bundle contains exactly the same files and bytes.
 * The caller owns retrieval and must supply a new download/extraction directory;
 * this function deliberately has no network dependency so the equality boundary
 * remains deterministic and unit-testable.
 *
 * @param {string} stagedRoot
 * @param {{
 *   publishedBundleDirectory: string;
 *   packagedRoot?: string;
 *   releaseValidator: (bundleDirectory: string, deployment: "public" | "candidate" | "public-beta") => Promise<void>;
 * }} options
 */
export async function validatePublishedFirmwareRelease(
  stagedRoot,
  { publishedBundleDirectory, packagedRoot, releaseValidator },
) {
  if (typeof releaseValidator !== "function") {
    failure("an explicit canonical release validator is required");
  }
  const staged = await validateStagedFirmwareRelease(stagedRoot, {
    releaseValidator,
  });
  if (staged.deployment !== "public" || staged.hilStatus !== "passed") {
    failure(
      "published GitHub evidence is accepted only for an all-HIL-passed public release",
    );
  }

  const publishedRoot = resolve(publishedBundleDirectory);
  let publishedMetadata;
  try {
    publishedMetadata = await lstat(publishedRoot);
  } catch (error) {
    if (error instanceof Error && "code" in error && error.code === "ENOENT") {
      failure("published GitHub evidence directory is missing");
    }
    throw error;
  }
  if (publishedMetadata.isSymbolicLink() || !publishedMetadata.isDirectory()) {
    failure("published GitHub evidence must be an ordinary directory");
  }

  const published = await validateReleaseBundle(
    publishedRoot,
    "public",
    staged.accessControlled,
    releaseValidator,
  );
  if (!isDeepStrictEqual(staged, published)) {
    failure(
      "published GitHub release identity differs from the staged public release",
    );
  }

  const stagedBundle = join(
    resolve(stagedRoot),
    "firmware",
    `v${staged.version}`,
  );
  const [stagedFiles, publishedFiles] = await Promise.all([
    allFiles(stagedBundle),
    allFiles(publishedRoot),
  ]);
  if (!isDeepStrictEqual(stagedFiles, publishedFiles)) {
    failure("published GitHub release file set differs from the staged bundle");
  }
  for (const path of stagedFiles) {
    const [stagedBytes, publishedBytes] = await Promise.all([
      readFile(join(stagedBundle, path)),
      readFile(join(publishedRoot, path)),
    ]);
    if (!stagedBytes.equals(publishedBytes)) {
      failure(`published GitHub byte mismatch for ${path}`);
    }
  }

  if (packagedRoot !== undefined) {
    const packagedOutput = resolve(packagedRoot);
    const packagedMetadata = await lstat(packagedOutput);
    if (packagedMetadata.isSymbolicLink() || !packagedMetadata.isDirectory()) {
      failure("packaged website output must be an ordinary directory");
    }
    const packagedFirmwareRoot = join(packagedOutput, "firmware");
    const packagedFirmwareMetadata = await lstat(packagedFirmwareRoot);
    if (
      packagedFirmwareMetadata.isSymbolicLink() ||
      !packagedFirmwareMetadata.isDirectory()
    ) {
      failure("packaged firmware root must be an ordinary directory");
    }
    const packagedEntries = await readdir(packagedFirmwareRoot, {
      withFileTypes: true,
    });
    if (
      packagedEntries.length !== 1 ||
      packagedEntries[0]?.name !== `v${staged.version}` ||
      !packagedEntries[0].isDirectory()
    ) {
      failure(
        "packaged firmware root must contain exactly the selected version",
      );
    }

    const packagedBundle = join(packagedFirmwareRoot, `v${staged.version}`);
    const packagedFiles = await allFiles(packagedBundle);
    if (!isDeepStrictEqual(stagedFiles, packagedFiles)) {
      failure("packaged firmware file set differs from the staged bundle");
    }
    for (const path of stagedFiles) {
      const [stagedBytes, packagedBytes] = await Promise.all([
        readFile(join(stagedBundle, path)),
        readFile(join(packagedBundle, path)),
      ]);
      if (!stagedBytes.equals(packagedBytes)) {
        failure(`packaged firmware byte mismatch for ${path}`);
      }
    }
  }
  return staged;
}

async function run() {
  if (process.argv.includes("--verify-published")) {
    const stagedRoot = process.env.PYBLE_FIRMWARE_STAGED_ROOT;
    if (!stagedRoot) {
      failure("PYBLE_FIRMWARE_STAGED_ROOT is required");
    }
    const publishedBundleDirectory =
      process.env.PYBLE_GITHUB_RELEASE_BUNDLE_DIR;
    if (!publishedBundleDirectory) {
      failure("PYBLE_GITHUB_RELEASE_BUNDLE_DIR is required");
    }
    const descriptor = await validatePublishedFirmwareRelease(stagedRoot, {
      publishedBundleDirectory,
      packagedRoot: process.env.PYBLE_FIRMWARE_PACKAGED_ROOT,
      releaseValidator: validateFreshDeploymentBundle,
    });
    process.stdout.write(
      `Verified published GitHub bytes for PyBLE firmware v${descriptor.version}.\n`,
    );
    return;
  }
  if (process.argv.includes("--verify-staged")) {
    const stagedRoot = process.env.PYBLE_FIRMWARE_STAGED_ROOT;
    if (!stagedRoot) {
      failure("PYBLE_FIRMWARE_STAGED_ROOT is required");
    }
    const descriptor = await validateStagedFirmwareRelease(stagedRoot, {
      releaseValidator: validateFreshDeploymentBundle,
    });
    process.stdout.write(
      `Verified staged PyBLE firmware v${descriptor.version} for ${descriptor.deployment}.\n`,
    );
    return;
  }
  if (process.argv.includes("--verify-preserved-staged")) {
    const stagedRoot = process.env.PYBLE_FIRMWARE_STAGED_ROOT;
    if (!stagedRoot) {
      failure("PYBLE_FIRMWARE_STAGED_ROOT is required");
    }
    const descriptor = await validatePreservedPublicFirmwareRelease(
      stagedRoot,
      {
        releaseValidator: validatePreservedDeploymentBundle,
      },
    );
    process.stdout.write(
      `Verified preserved public PyBLE firmware v${descriptor.version}.\n`,
    );
    return;
  }
  const deployment = process.env.PYBLE_FLASH_DEPLOYMENT ?? "disabled";
  if (deployment === "disabled" || deployment === "unavailable") {
    process.stdout.write(
      "Firmware staging disabled; public selection remains unavailable.\n",
    );
    return;
  }
  if (
    deployment !== "public" &&
    deployment !== "candidate" &&
    deployment !== "public-beta"
  ) {
    failure(
      "PYBLE_FLASH_DEPLOYMENT must be public, candidate, public-beta, or disabled",
    );
  }
  const bundleDirectory = process.env.PYBLE_FIRMWARE_BUNDLE_DIR;
  if (!bundleDirectory) {
    failure("PYBLE_FIRMWARE_BUNDLE_DIR is required");
  }
  const outputDirectory = process.env.PYBLE_FIRMWARE_OUTPUT_DIR;
  if (!outputDirectory) {
    failure("PYBLE_FIRMWARE_OUTPUT_DIR is required");
  }
  const accessControlled = process.env.PYBLE_FLASH_ACCESS_CONTROLLED === "1";
  const descriptor = await stageFirmwareRelease({
    accessControlled,
    bundleDirectory,
    deployment,
    outputDirectory,
    releaseValidator: validateFreshDeploymentBundle,
  });
  process.stdout.write(
    `Staged PyBLE firmware v${descriptor.version} for ${descriptor.deployment}.\n`,
  );
}

const invokedPath = process.argv[1];
if (
  invokedPath &&
  import.meta.url === pathToFileURL(resolve(invokedPath)).href
) {
  run().catch((error) => {
    console.error(error instanceof Error ? error.message : error);
    process.exitCode = 1;
  });
}

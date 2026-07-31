// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

import {
  firmwareProfileDescriptors,
  firmwareProfileTable,
  isExactPublicBetaFirmwareRelease,
  type FirmwareProfileDescriptor,
  type FirmwareProfileId,
  type FirmwareReleaseDescriptor,
  type VerifiedFirmwareProfile,
} from "@/lib/firmware-release";
import canonicalReleaseSchema from "@/lib/firmware-release-schema.json";

type JsonObject = Record<string, unknown>;
type Fetcher = (
  input: RequestInfo | URL,
  init?: RequestInit,
) => Promise<Response>;

interface VerifyFirmwareProfileOptions {
  readonly descriptor: FirmwareReleaseDescriptor;
  readonly fetcher?: Fetcher;
  readonly origin?: string;
  readonly profileId: FirmwareProfileId;
  readonly subtle?: SubtleCrypto;
}

interface ArtifactRecord {
  path: string;
  size: number;
  sha256: string;
}

interface InstallRecord extends ArtifactRecord {
  offset: number;
}

interface ValidatedProfile {
  chipFamily: string;
  hilStatus: "pending" | "passed";
  install: InstallRecord;
  manifest: ArtifactRecord;
}

interface ValidatedRelease {
  builtAt: string;
  profiles: Map<FirmwareProfileId, ValidatedProfile>;
  version: string;
}

export class FirmwareIntegrityError extends Error {
  constructor(message: string, options?: ErrorOptions) {
    super(message, options);
    this.name = "FirmwareIntegrityError";
  }
}

function fail(message: string): never {
  throw new FirmwareIntegrityError(message);
}

function isObject(value: unknown): value is JsonObject {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function object(value: unknown, label: string): JsonObject {
  if (!isObject(value)) {
    fail(`${label} must be an object`);
  }
  return value;
}

function exactKeys(
  value: JsonObject,
  expected: readonly string[],
  label: string,
) {
  const actual = Object.keys(value).sort();
  const wanted = [...expected].sort();
  if (
    actual.length !== wanted.length ||
    actual.some((key, index) => key !== wanted[index])
  ) {
    fail(`${label} has an invalid shape`);
  }
}

function sameJsonValue(left: unknown, right: unknown): boolean {
  if (Object.is(left, right)) {
    return true;
  }
  if (Array.isArray(left) || Array.isArray(right)) {
    return (
      Array.isArray(left) &&
      Array.isArray(right) &&
      left.length === right.length &&
      left.every((value, index) => sameJsonValue(value, right[index]))
    );
  }
  if (!isObject(left) || !isObject(right)) {
    return false;
  }
  const leftKeys = Object.keys(left).sort();
  const rightKeys = Object.keys(right).sort();
  return (
    leftKeys.length === rightKeys.length &&
    leftKeys.every(
      (key, index) =>
        key === rightKeys[index] && sameJsonValue(left[key], right[key]),
    )
  );
}

function validateReleaseSchema(value: unknown) {
  if (!sameJsonValue(value, canonicalReleaseSchema)) {
    fail("Release schema does not match the canonical PyBLE release schema");
  }
}

function string(value: unknown, label: string): string {
  if (typeof value !== "string" || value.length === 0) {
    fail(`${label} must be a non-empty string`);
  }
  return value;
}

function integer(value: unknown, label: string, minimum = 0): number {
  if (!Number.isInteger(value) || (value as number) < minimum) {
    fail(`${label} must be an integer of at least ${minimum}`);
  }
  return value as number;
}

function boolean(value: unknown, label: string): boolean {
  if (typeof value !== "boolean") {
    fail(`${label} must be a boolean`);
  }
  return value;
}

function array(value: unknown, label: string): unknown[] {
  if (!Array.isArray(value)) {
    fail(`${label} must be an array`);
  }
  return value;
}

function equal(actual: unknown, expected: unknown, label: string) {
  if (actual !== expected) {
    fail(`${label} does not match the selected release`);
  }
}

function isSha256(value: string) {
  return /^[0-9a-f]{64}$/.test(value);
}

function isCommit(value: string) {
  return /^[0-9a-f]{40}$/.test(value);
}

function isSemver(value: string) {
  return /^(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)(?:-(?:0|[1-9][0-9]*|[0-9]*[A-Za-z-][0-9A-Za-z-]*)(?:\.(?:0|[1-9][0-9]*|[0-9]*[A-Za-z-][0-9A-Za-z-]*))*)?(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$/.test(
    value,
  );
}

function isUtcTimestamp(value: string) {
  return /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/.test(value);
}

function safeRelativePath(value: unknown, label: string): string {
  const path = string(value, label);
  if (
    path.startsWith("/") ||
    path.includes("\\") ||
    path.includes("?") ||
    path.includes("#") ||
    path.includes("://") ||
    path.split("/").some((segment) => segment === "." || segment === "..")
  ) {
    fail(`${label} is not a safe relative path`);
  }
  return path;
}

function artifactRecord(value: unknown, label: string): ArtifactRecord {
  const record = object(value, label);
  exactKeys(record, ["path", "size", "sha256"], label);
  const sha256 = string(record.sha256, `${label}.sha256`);
  if (!isSha256(sha256)) {
    fail(`${label}.sha256 must be lowercase SHA-256`);
  }
  return {
    path: safeRelativePath(record.path, `${label}.path`),
    size: integer(record.size, `${label}.size`, 1),
    sha256,
  };
}

function installRecord(value: unknown, label: string): InstallRecord {
  const record = object(value, label);
  exactKeys(record, ["path", "size", "sha256", "offset"], label);
  const base = artifactRecord(
    {
      path: record.path,
      size: record.size,
      sha256: record.sha256,
    },
    label,
  );
  return {
    ...base,
    offset: integer(record.offset, `${label}.offset`),
  };
}

function validateDescriptorProfile(
  actual: FirmwareProfileDescriptor,
  expected: FirmwareProfileDescriptor,
) {
  equal(actual.id, expected.id, `${expected.id} descriptor ID`);
  equal(actual.label, expected.label, `${expected.id} descriptor label`);
  equal(
    actual.chipFamily,
    expected.chipFamily,
    `${expected.id} descriptor family`,
  );
  equal(
    actual.manifestPath,
    expected.manifestPath,
    `${expected.id} descriptor manifest`,
  );
  equal(
    actual.firmwarePath,
    expected.firmwarePath,
    `${expected.id} descriptor firmware`,
  );
  equal(actual.offset, expected.offset, `${expected.id} descriptor offset`);
  equal(
    actual.flashSizeBytes,
    expected.flashSizeBytes,
    `${expected.id} descriptor flash size`,
  );
  equal(
    actual.siliconRevision.minimumFull,
    expected.siliconRevision.minimumFull,
    `${expected.id} descriptor minimum silicon revision`,
  );
  equal(
    actual.siliconRevision.maximumFull,
    expected.siliconRevision.maximumFull,
    `${expected.id} descriptor maximum silicon revision`,
  );
  equal(
    actual.psram.required,
    expected.psram.required,
    `${expected.id} descriptor PSRAM requirement`,
  );
  equal(
    actual.psram.sizeBytes,
    expected.psram.sizeBytes,
    `${expected.id} descriptor PSRAM size`,
  );
  equal(
    actual.psram.type,
    expected.psram.type,
    `${expected.id} descriptor PSRAM type`,
  );
}

function validateDescriptor(
  descriptor: FirmwareReleaseDescriptor,
  origin: string,
) {
  if (
    descriptor.deployment !== "public" &&
    descriptor.deployment !== "candidate" &&
    descriptor.deployment !== "public-beta"
  ) {
    fail("Selected firmware deployment mode is invalid");
  }
  if (!isSemver(descriptor.version)) {
    fail("Selected firmware version is not canonical SemVer");
  }
  if (!isUtcTimestamp(descriptor.builtAt)) {
    fail("Selected firmware build time is invalid");
  }
  if (!isSha256(descriptor.releaseJson.sha256)) {
    fail("Selected release root SHA-256 is invalid");
  }
  if (descriptor.deployment === "candidate" && !descriptor.accessControlled) {
    fail("Candidate firmware requires an access-controlled build");
  }
  if (descriptor.deployment === "public" && descriptor.hilStatus !== "passed") {
    fail("Public firmware requires passed hardware validation");
  }
  if (
    descriptor.deployment === "public-beta" &&
    !isExactPublicBetaFirmwareRelease(descriptor)
  ) {
    fail("Public beta does not match the exact attested v0.4.1 release");
  }

  const releasePath = `/firmware/v${descriptor.version}/release.json`;
  const schemaPath = `/firmware/v${descriptor.version}/release.schema.json`;
  const recoveryPath = `/firmware/v${descriptor.version}/RECOVERY.md`;
  equal(descriptor.releaseJson.path, releasePath, "Release metadata path");
  equal(descriptor.schemaPath, schemaPath, "Release schema path");
  equal(descriptor.recoveryPath, recoveryPath, "Recovery path");
  const releaseUrl = new URL(descriptor.releaseJson.path, origin);
  if (
    releaseUrl.origin !== origin ||
    releaseUrl.pathname !== releasePath ||
    releaseUrl.search ||
    releaseUrl.hash
  ) {
    fail("Release metadata must use the selected same-origin version path");
  }

  const expectedProfiles = firmwareProfileDescriptors(descriptor.version);
  if (descriptor.profiles.length !== expectedProfiles.length) {
    fail(
      "Selected release descriptor must contain exactly the two current release profiles",
    );
  }
  descriptor.profiles.forEach((profile, index) => {
    const expected = expectedProfiles[index];
    if (!expected) {
      fail("Unexpected selected firmware profile");
    }
    validateDescriptorProfile(profile, expected);
  });
}

function validateTool(value: unknown, index: number) {
  const tool = object(value, `provenance.tools[${index}]`);
  exactKeys(tool, ["name", "version"], `provenance.tools[${index}]`);
  string(tool.name, `provenance.tools[${index}].name`);
  string(tool.version, `provenance.tools[${index}].version`);
}

function validateProvenance(value: unknown) {
  const provenance = object(value, "release.provenance");
  exactKeys(
    provenance,
    ["pyble", "micropython", "esp_idf", "patch_count", "runner", "tools"],
    "release.provenance",
  );

  const pyble = object(provenance.pyble, "release.provenance.pyble");
  exactKeys(pyble, ["commit", "clean"], "release.provenance.pyble");
  if (!isCommit(string(pyble.commit, "release.provenance.pyble.commit"))) {
    fail("PyBLE source commit must be full lowercase hexadecimal");
  }
  equal(
    boolean(pyble.clean, "release.provenance.pyble.clean"),
    true,
    "PyBLE clean state",
  );

  for (const key of ["micropython", "esp_idf"] as const) {
    const upstream = object(provenance[key], `release.provenance.${key}`);
    exactKeys(upstream, ["ref", "commit"], `release.provenance.${key}`);
    string(upstream.ref, `release.provenance.${key}.ref`);
    if (
      !isCommit(string(upstream.commit, `release.provenance.${key}.commit`))
    ) {
      fail(`${key} commit must be full lowercase hexadecimal`);
    }
  }

  integer(provenance.patch_count, "release.provenance.patch_count");
  const runner = object(provenance.runner, "release.provenance.runner");
  exactKeys(runner, ["os", "architecture"], "release.provenance.runner");
  string(runner.os, "release.provenance.runner.os");
  string(runner.architecture, "release.provenance.runner.architecture");
  const tools = array(provenance.tools, "release.provenance.tools");
  if (tools.length < 1) {
    fail("Release provenance must include compiler and build tools");
  }
  tools.forEach(validateTool);
}

function validateComponents(
  value: unknown,
  profileIndex: number,
  profileId: FirmwareProfileId,
  baseOffset: number,
) {
  const components = array(value, `${profileId}.components`);
  if (components.length !== 3) {
    fail(`${profileId} must declare exactly three components`);
  }
  const expected = [
    {
      role: "bootloader",
      path: `${profileId}/bootloader.bin`,
      offset: baseOffset,
    },
    {
      role: "partition-table",
      path: `${profileId}/partition-table.bin`,
      offset: 0x8000,
    },
    {
      role: "application",
      path: `${profileId}/application.bin`,
      offset: 0x10000,
    },
  ] as const;

  components.forEach((value, componentIndex) => {
    const label = `release.profiles[${profileIndex}].components[${componentIndex}]`;
    const component = object(value, label);
    exactKeys(component, ["role", "path", "offset", "size", "sha256"], label);
    const artifact = installRecord(
      {
        path: component.path,
        size: component.size,
        sha256: component.sha256,
        offset: component.offset,
      },
      label,
    );
    const wanted = expected[componentIndex];
    if (!wanted) {
      fail(`${profileId} contains an extra component`);
    }
    equal(component.role, wanted.role, `${label}.role`);
    equal(artifact.path, wanted.path, `${label}.path`);
    equal(artifact.offset, wanted.offset, `${label}.offset`);
  });
}

function validateProfile(
  value: unknown,
  index: number,
): [FirmwareProfileId, ValidatedProfile] {
  const expected = firmwareProfileTable[index];
  if (!expected) {
    fail("Release contains an unexpected profile");
  }
  const label = `release.profiles[${index}]`;
  const profile = object(value, label);
  exactKeys(
    profile,
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
    label,
  );
  equal(profile.id, expected.id, `${label}.id`);
  equal(profile.chip_family, expected.chipFamily, `${label}.chip_family`);

  const requirements = object(profile.requirements, `${label}.requirements`);
  exactKeys(
    requirements,
    ["flash_size_bytes", "psram"],
    `${label}.requirements`,
  );
  equal(
    integer(
      requirements.flash_size_bytes,
      `${label}.requirements.flash_size_bytes`,
      1,
    ),
    expected.flashSizeBytes,
    `${label}.requirements.flash_size_bytes`,
  );
  const psram = object(requirements.psram, `${label}.requirements.psram`);
  exactKeys(
    psram,
    ["required", "size_bytes", "type"],
    `${label}.requirements.psram`,
  );
  equal(
    boolean(psram.required, `${label}.requirements.psram.required`),
    expected.psram.required,
    `${label}.requirements.psram.required`,
  );
  equal(
    integer(psram.size_bytes, `${label}.requirements.psram.size_bytes`),
    expected.psram.sizeBytes,
    `${label}.requirements.psram.size_bytes`,
  );
  equal(
    string(psram.type, `${label}.requirements.psram.type`),
    expected.psram.type,
    `${label}.requirements.psram.type`,
  );

  const flash = object(profile.flash, `${label}.flash`);
  exactKeys(flash, ["mode", "frequency_hz"], `${label}.flash`);
  equal(flash.mode, "dio", `${label}.flash.mode`);
  equal(
    integer(flash.frequency_hz, `${label}.flash.frequency_hz`, 1),
    expected.flashFrequencyHz,
    `${label}.flash.frequency_hz`,
  );

  const revision = object(
    profile.silicon_revision,
    `${label}.silicon_revision`,
  );
  exactKeys(
    revision,
    ["minimum_full", "maximum_full"],
    `${label}.silicon_revision`,
  );
  equal(
    integer(revision.minimum_full, `${label}.silicon_revision.minimum_full`),
    expected.siliconRevision.minimumFull,
    `${label}.silicon_revision.minimum_full`,
  );
  equal(
    integer(revision.maximum_full, `${label}.silicon_revision.maximum_full`),
    expected.siliconRevision.maximumFull,
    `${label}.silicon_revision.maximum_full`,
  );

  const hilStatus = string(profile.hil_status, `${label}.hil_status`);
  if (hilStatus !== "pending" && hilStatus !== "passed") {
    fail(`${label}.hil_status must be pending or passed`);
  }
  const manifest = artifactRecord(profile.manifest, `${label}.manifest`);
  const install = installRecord(profile.install, `${label}.install`);
  equal(
    manifest.path,
    `${expected.id}/manifest.json`,
    `${label}.manifest.path`,
  );
  equal(install.path, `${expected.id}/firmware.bin`, `${label}.install.path`);
  equal(install.offset, expected.offset, `${label}.install.offset`);
  validateComponents(profile.components, index, expected.id, expected.offset);

  return [
    expected.id,
    {
      chipFamily: expected.chipFamily,
      hilStatus,
      install,
      manifest,
    },
  ];
}

function validateDocuments(value: unknown) {
  const documents = object(value, "release.documents");
  const expected = {
    third_party_licenses: "THIRD_PARTY_LICENSES.txt",
    release_notes: "RELEASE_NOTES.md",
    recovery: "RECOVERY.md",
    hil_report: "HIL_REPORT.md",
  } as const;
  exactKeys(documents, Object.keys(expected), "release.documents");
  for (const [key, path] of Object.entries(expected)) {
    const record = artifactRecord(documents[key], `release.documents.${key}`);
    equal(record.path, path, `release.documents.${key}.path`);
  }
}

function validateRelease(
  value: unknown,
  descriptor: FirmwareReleaseDescriptor,
): ValidatedRelease {
  const release = object(value, "release");
  exactKeys(
    release,
    [
      "schema_version",
      "identity",
      "provenance",
      "installer",
      "profiles",
      "documents",
    ],
    "release",
  );
  equal(release.schema_version, 2, "Release schema version");

  const identity = object(release.identity, "release.identity");
  exactKeys(
    identity,
    ["version", "tag", "agent_version", "protocol_version", "built_at"],
    "release.identity",
  );
  const version = string(identity.version, "release.identity.version");
  if (!isSemver(version)) {
    fail("Release identity version is not canonical SemVer");
  }
  equal(version, descriptor.version, "Release identity version");
  equal(identity.tag, `firmware-v${version}`, "Release tag");
  equal(identity.agent_version, version, "Firmware agent version");
  equal(identity.protocol_version, "PBLE/1", "Protocol version");
  const builtAt = string(identity.built_at, "release.identity.built_at");
  if (!isUtcTimestamp(builtAt)) {
    fail("Release build time is not a UTC timestamp");
  }
  equal(builtAt, descriptor.builtAt, "Release build time");

  validateProvenance(release.provenance);
  const installer = object(release.installer, "release.installer");
  exactKeys(installer, ["package", "version"], "release.installer");
  equal(installer.package, "esp-web-tools", "Installer package");
  equal(installer.version, "10.4.0", "Installer package version");

  const profileValues = array(release.profiles, "release.profiles");
  if (profileValues.length !== firmwareProfileTable.length) {
    fail("Release must contain exactly the two current release profiles");
  }
  const profiles = new Map(
    profileValues.map((profile, index) => validateProfile(profile, index)),
  );
  const statuses = [...profiles.values()].map(({ hilStatus }) => hilStatus);
  if (
    descriptor.deployment === "public" &&
    statuses.some((status) => status !== "passed")
  ) {
    fail("Public release hardware validation is incomplete");
  }
  if (descriptor.deployment === "candidate" && !descriptor.accessControlled) {
    fail("Pending candidate release is not access-controlled");
  }
  if (
    descriptor.deployment === "public-beta" &&
    statuses.some((status) => status !== "pending")
  ) {
    fail("Public beta hardware validation must remain pending");
  }
  const aggregateStatus = statuses.every((status) => status === "passed")
    ? "passed"
    : "pending";
  equal(
    descriptor.hilStatus,
    aggregateStatus,
    "Selected hardware-validation status",
  );

  validateDocuments(release.documents);
  return { builtAt, profiles, version };
}

function parseJson(bytes: Uint8Array, label: string): unknown {
  let text;
  try {
    text = new TextDecoder("utf-8", { fatal: true }).decode(bytes);
  } catch (error) {
    throw new FirmwareIntegrityError(`${label} is not valid UTF-8`, {
      cause: error,
    });
  }
  try {
    return JSON.parse(text);
  } catch (error) {
    throw new FirmwareIntegrityError(`${label} is not valid JSON`, {
      cause: error,
    });
  }
}

function toHex(bytes: Uint8Array) {
  return [...bytes]
    .map((value) => value.toString(16).padStart(2, "0"))
    .join("");
}

async function digest(subtle: SubtleCrypto, bytes: Uint8Array) {
  const input = bytes.slice().buffer;
  return toHex(new Uint8Array(await subtle.digest("SHA-256", input)));
}

async function fetchExactBytes(
  fetcher: Fetcher,
  origin: string,
  path: string,
  label: string,
  releaseKey: string,
) {
  const canonical = new URL(path, origin);
  if (
    canonical.origin !== origin ||
    canonical.pathname !== path ||
    canonical.search ||
    canonical.hash
  ) {
    fail(`${label} URL is not an exact same-origin path`);
  }
  if (!/^[0-9a-f]{64}$/.test(releaseKey)) {
    fail(`${label} release cache key is invalid`);
  }
  const expected = new URL(canonical);
  expected.searchParams.set("pyble_release", releaseKey);

  let response;
  try {
    response = await fetcher(`${path}${expected.search}`, {
      cache: "reload",
      credentials: "same-origin",
      redirect: "error",
    });
  } catch (error) {
    throw new FirmwareIntegrityError(`${label} request failed`, {
      cause: error,
    });
  }
  if (!response.ok) {
    fail(`${label} request failed with HTTP ${response.status}`);
  }
  if (response.redirected) {
    fail(`${label} redirect rejected`);
  }
  if (response.url !== expected.href) {
    fail(`${label} response URL does not match the selected origin`);
  }
  return new Uint8Array(await response.arrayBuffer());
}

async function verifyArtifact(
  bytes: Uint8Array,
  record: ArtifactRecord,
  subtle: SubtleCrypto,
  label: string,
) {
  if (bytes.byteLength !== record.size) {
    fail(`${label} size mismatch`);
  }
  if ((await digest(subtle, bytes)) !== record.sha256) {
    fail(`${label} digest mismatch`);
  }
}

function validateManifest(
  value: unknown,
  release: ValidatedRelease,
  profileId: FirmwareProfileId,
) {
  const manifest = object(value, "manifest");
  exactKeys(
    manifest,
    [
      "name",
      "version",
      "new_install_prompt_erase",
      "new_install_improv_wait_time",
      "builds",
    ],
    "manifest",
  );
  equal(manifest.name, "PyBLE", "Manifest name");
  equal(manifest.version, release.version, "Manifest version");
  equal(manifest.new_install_prompt_erase, false, "Manifest erase behavior");
  equal(manifest.new_install_improv_wait_time, 0, "Manifest Improv wait");
  const builds = array(manifest.builds, "manifest.builds");
  if (builds.length !== 1) {
    fail("Manifest must contain exactly one selected-profile build");
  }
  const build = object(builds[0], "manifest.builds[0]");
  exactKeys(build, ["chipFamily", "parts"], "manifest.builds[0]");
  const selected = release.profiles.get(profileId);
  if (!selected) {
    fail("Selected profile is absent from release metadata");
  }
  equal(build.chipFamily, selected.chipFamily, "Manifest chip family");
  const parts = array(build.parts, "manifest.builds[0].parts");
  if (parts.length !== 1) {
    fail("Manifest must contain exactly one merged-image part");
  }
  const part = object(parts[0], "manifest.builds[0].parts[0]");
  exactKeys(part, ["path", "offset"], "manifest.builds[0].parts[0]");
  equal(
    safeRelativePath(part.path, "manifest.builds[0].parts[0].path"),
    "firmware.bin",
    "Manifest merged-image path",
  );
  equal(
    integer(part.offset, "manifest.builds[0].parts[0].offset"),
    selected.install.offset,
    "Manifest merged-image offset",
  );
}

export async function verifyFirmwareProfile({
  descriptor,
  fetcher = globalThis.fetch.bind(globalThis),
  origin = globalThis.location?.origin ?? "https://pyble.dev",
  profileId,
  subtle = globalThis.crypto.subtle,
}: VerifyFirmwareProfileOptions): Promise<VerifiedFirmwareProfile> {
  validateDescriptor(descriptor, origin);
  const descriptorProfile = descriptor.profiles.find(
    ({ id }) => id === profileId,
  );
  if (!descriptorProfile) {
    fail("Selected profile is not present in the build descriptor");
  }

  const releaseBytes = await fetchExactBytes(
    fetcher,
    origin,
    descriptor.releaseJson.path,
    "Release metadata",
    descriptor.releaseJson.sha256,
  );
  if ((await digest(subtle, releaseBytes)) !== descriptor.releaseJson.sha256) {
    fail("Release metadata digest mismatch");
  }
  const schemaBytes = await fetchExactBytes(
    fetcher,
    origin,
    descriptor.schemaPath,
    "Release schema",
    descriptor.releaseJson.sha256,
  );
  validateReleaseSchema(parseJson(schemaBytes, "Release schema"));
  const release = validateRelease(
    parseJson(releaseBytes, "Release metadata"),
    descriptor,
  );
  const selected = release.profiles.get(profileId);
  if (!selected) {
    fail("Selected profile is absent from verified release metadata");
  }

  const releaseRoot = `/firmware/v${release.version}/`;
  const manifestPath = `${releaseRoot}${selected.manifest.path}`;
  equal(manifestPath, descriptorProfile.manifestPath, "Selected manifest path");
  const manifestBytes = await fetchExactBytes(
    fetcher,
    origin,
    manifestPath,
    "Selected manifest",
    descriptor.releaseJson.sha256,
  );
  await verifyArtifact(
    manifestBytes,
    selected.manifest,
    subtle,
    "Selected manifest",
  );
  validateManifest(
    parseJson(manifestBytes, "Selected manifest"),
    release,
    profileId,
  );

  const firmwarePath = `${releaseRoot}${selected.install.path}`;
  equal(firmwarePath, descriptorProfile.firmwarePath, "Selected firmware path");
  const firmwareBytes = await fetchExactBytes(
    fetcher,
    origin,
    firmwarePath,
    "Selected firmware",
    descriptor.releaseJson.sha256,
  );
  await verifyArtifact(
    firmwareBytes,
    selected.install,
    subtle,
    "Selected firmware",
  );

  return {
    profileId,
    chipFamily: selected.chipFamily,
    manifestPath,
    manifestBuildCount: 1,
    firmwarePath,
    version: release.version,
  };
}

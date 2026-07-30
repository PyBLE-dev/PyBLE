// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

import { execFile as execFileCallback } from "node:child_process";
import {
  access,
  mkdir,
  mkdtemp,
  readFile,
  readdir,
  rm,
  writeFile,
} from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, relative } from "node:path";
import { promisify } from "node:util";

import { afterEach, describe, expect, it } from "vitest";

import {
  bundleFiles,
  createFirmwareReleaseFixture,
} from "@/test/fixtures/firmware-release";

const execFile = promisify(execFileCallback);
const temporaryDirectories: string[] = [];
const archiveHelper = join(
  process.cwd(),
  "scripts",
  "verify-firmware-release-archive.py",
);

const archiveBuilder = String.raw`
import io
import pathlib
import sys
import tarfile

expected = pathlib.Path(sys.argv[1])
archive = pathlib.Path(sys.argv[2])
variant = sys.argv[3]
directories = sorted(
    (path for path in expected.rglob("*") if path.is_dir()),
    key=lambda path: path.relative_to(expected).as_posix(),
)
files = sorted(
    (path for path in expected.rglob("*") if path.is_file()),
    key=lambda path: path.relative_to(expected).as_posix(),
)

def regular(archive_file, name, data):
    info = tarfile.TarInfo(name)
    info.mode = 0o644
    info.mtime = 0
    info.size = len(data)
    archive_file.addfile(info, io.BytesIO(data))

with tarfile.open(archive, "w:gz", format=tarfile.PAX_FORMAT) as archive_file:
    for path in directories:
        name = path.relative_to(expected).as_posix() + "/"
        info = tarfile.TarInfo(name)
        info.type = tarfile.DIRTYPE
        info.mode = 0o755
        info.mtime = 0
        archive_file.addfile(info)

    for path in files:
        name = path.relative_to(expected).as_posix()
        data = path.read_bytes()
        if variant == "size" and name == "release.json":
            regular(archive_file, name, data + b"x")
        elif variant == "symlink" and name == "release.json":
            info = tarfile.TarInfo(name)
            info.type = tarfile.SYMTYPE
            info.linkname = "../outside"
            info.mode = 0o777
            info.mtime = 0
            archive_file.addfile(info)
        elif variant == "special" and name == "release.json":
            info = tarfile.TarInfo(name)
            info.type = tarfile.FIFOTYPE
            info.mode = 0o644
            info.mtime = 0
            archive_file.addfile(info)
        else:
            regular(archive_file, name, data)

    release_bytes = (expected / "release.json").read_bytes()
    if variant == "duplicate":
        regular(archive_file, "release.json", release_bytes)
    elif variant == "extra":
        regular(archive_file, "unexpected.bin", b"unexpected")
    elif variant == "dot":
        regular(archive_file, "./release.json", release_bytes)
    elif variant == "dotdot":
        regular(archive_file, "../escape.bin", b"escape")
`;

afterEach(async () => {
  await Promise.all(
    temporaryDirectories
      .splice(0)
      .map((directory) => rm(directory, { recursive: true, force: true })),
  );
});

async function writeExpectedBundle(root: string) {
  const fixture = createFirmwareReleaseFixture();
  for (const [relativePath, bytes] of bundleFiles(fixture)) {
    const path = join(root, relativePath);
    await mkdir(join(path, ".."), { recursive: true });
    await writeFile(path, bytes);
  }
}

async function buildArchive(
  expectedBundle: string,
  archive: string,
  variant: string,
) {
  await execFile(
    "python3",
    ["-c", archiveBuilder, expectedBundle, archive, variant],
    { maxBuffer: 16 * 1024 * 1024 },
  );
}

async function filesBelow(root: string) {
  const files: string[] = [];
  async function visit(directory: string) {
    const entries = await readdir(directory, { withFileTypes: true });
    for (const entry of entries) {
      const path = join(directory, entry.name);
      if (entry.isDirectory()) {
        await visit(path);
      } else if (entry.isFile()) {
        files.push(relative(root, path).split("\\").join("/"));
      }
    }
  }
  await visit(root);
  return files.sort();
}

async function verifyArchive(
  archive: string,
  expectedBundle: string,
  outputDirectory: string,
) {
  return execFile(
    "python3",
    [
      archiveHelper,
      "--archive",
      archive,
      "--expected-bundle",
      expectedBundle,
      "--output-dir",
      outputDirectory,
    ],
    { maxBuffer: 16 * 1024 * 1024 },
  );
}

describe("GitHub firmware release archive safety", () => {
  it("extracts only an exact bounded archive and publishes no invalid output", async () => {
    try {
      await access(archiveHelper);
    } catch {
      expect.fail(
        "scripts/verify-firmware-release-archive.py must own safe archive inspection and extraction",
      );
      return;
    }

    const root = await mkdtemp(join(tmpdir(), "pyble-firmware-archive-"));
    const expectedBundle = join(root, "expected");
    temporaryDirectories.push(root);
    await mkdir(expectedBundle);
    await writeExpectedBundle(expectedBundle);

    const validArchive = join(root, "valid.tar.gz");
    const validOutput = join(root, "valid-output");
    await buildArchive(expectedBundle, validArchive, "valid");
    await expect(
      verifyArchive(validArchive, expectedBundle, validOutput),
    ).resolves.toBeDefined();

    const expectedFiles = await filesBelow(expectedBundle);
    expect(await filesBelow(validOutput)).toEqual(expectedFiles);
    for (const path of expectedFiles) {
      await expect(readFile(join(validOutput, path))).resolves.toEqual(
        await readFile(join(expectedBundle, path)),
      );
    }

    const invalidVariants = [
      "duplicate",
      "extra",
      "size",
      "symlink",
      "special",
      "dot",
      "dotdot",
    ];
    for (const variant of invalidVariants) {
      const caseRoot = join(root, variant);
      const archive = join(caseRoot, "bundle.tar.gz");
      const output = join(caseRoot, "published");
      await mkdir(caseRoot);
      await buildArchive(expectedBundle, archive, variant);

      let rejected = false;
      try {
        await verifyArchive(archive, expectedBundle, output);
      } catch {
        rejected = true;
      }
      expect.soft(rejected, `${variant} archive must be rejected`).toBe(true);
      await expect.soft(access(output)).rejects.toThrow();
      await expect.soft(access(join(caseRoot, "escape.bin"))).rejects.toThrow();
    }
  });
});

// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

import { readFile, writeFile } from "node:fs/promises";
import { basename, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const packageRoot = fileURLToPath(new URL("..", import.meta.url));
const lockPath = join(packageRoot, "package-lock.json");
const noticePath = join(
  packageRoot,
  "public",
  "WEBSITE_THIRD_PARTY_LICENSES.txt",
);
const licenseNames = [
  "LICENSE",
  "LICENSE.md",
  "LICENSE.txt",
  "LICENSE.MIT",
  "LICENSE-MIT.txt",
  "LICENCE",
  "LICENCE.md",
  "LICENCE.txt",
];
const supplementalLicenseSources = {
  "node_modules/esptool-js/node_modules/pako": ["lib/zlib/README"],
};

function mitLicense(copyright, heading = "MIT License") {
  return `${heading}

${copyright}

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.`;
}

const reviewedLicenseFallbacks = {
  "node_modules/@next/env": {
    version: "16.2.12",
    text: mitLicense(
      "Copyright (c) 2025 Vercel, Inc.",
      "The MIT License (MIT)",
    ),
  },
  "node_modules/@unpic/core": {
    version: "1.0.3",
    text: mitLicense("Copyright (c) 2023 Matt Kane"),
  },
  "node_modules/client-only": {
    version: "0.0.1",
    text: mitLicense("Copyright (c) Meta Platforms, Inc. and affiliates."),
  },
  "node_modules/css-box-shadow": {
    version: "1.0.0-3",
    text: mitLicense("Copyright (c) Brent Jackson"),
  },
  "node_modules/unpic": {
    version: "4.2.2",
    text: mitLicense("Copyright (c) 2023 Matt Kane"),
  },
  "node_modules/yoga-layout": {
    version: "3.2.1",
    text: mitLicense("Copyright (c) Facebook, Inc. and its affiliates."),
  },
};
const reviewedLicenseSources = {
  "node_modules/@lit-labs/ssr-dom-shim": {
    version: "1.6.0",
    path: "node_modules/lit/LICENSE",
  },
  "node_modules/@resvg/resvg-wasm": {
    version: "2.4.0",
    path: "node_modules/lightningcss/LICENSE",
  },
};

function packageNameFromPath(packagePath) {
  const marker = "node_modules/";
  const lastMarker = packagePath.lastIndexOf(marker);
  if (lastMarker < 0) {
    throw new Error(`Cannot derive package name from ${packagePath}`);
  }
  const tail = packagePath.slice(lastMarker + marker.length);
  if (tail.startsWith("@")) {
    return tail.split("/").slice(0, 2).join("/");
  }
  return tail.split("/")[0];
}

function resolveDependencyPath(packages, ownerPath, dependencyName) {
  let searchRoot = ownerPath;
  while (true) {
    const candidate = searchRoot
      ? `${searchRoot}/node_modules/${dependencyName}`
      : `node_modules/${dependencyName}`;
    if (packages[candidate]) {
      return candidate;
    }
    const marker = searchRoot.lastIndexOf("/node_modules/");
    if (marker < 0) {
      if (searchRoot) {
        searchRoot = "";
        continue;
      }
      break;
    }
    searchRoot = searchRoot.slice(0, marker);
  }
  return undefined;
}

function dependencyNames(entry) {
  return Object.keys(entry.dependencies ?? {}).sort();
}

function normalizeLicenseText(text) {
  return text
    .replace(/\r\n?/g, "\n")
    .split("\n")
    .map((line) => line.trimEnd())
    .join("\n")
    .trimEnd();
}

function productionClosure(lock) {
  const packages = lock.packages;
  const root = packages[""];
  if (!packages || !root) {
    throw new Error("package-lock.json does not contain a packages root");
  }

  const pending = Object.keys(root.dependencies ?? {})
    .sort()
    .map((name) => {
      const path = resolveDependencyPath(packages, "", name);
      if (!path) {
        throw new Error(`Production dependency is missing from lock: ${name}`);
      }
      return path;
    });
  const visited = new Set();

  while (pending.length > 0) {
    const packagePath = pending.shift();
    if (!packagePath || visited.has(packagePath)) {
      continue;
    }
    const entry = packages[packagePath];
    if (!entry) {
      throw new Error(`Locked package entry is missing: ${packagePath}`);
    }
    visited.add(packagePath);

    for (const name of dependencyNames(entry)) {
      const dependencyPath = resolveDependencyPath(packages, packagePath, name);
      if (dependencyPath && !visited.has(dependencyPath)) {
        pending.push(dependencyPath);
      }
    }
    pending.sort();
  }

  return [...visited].sort((left, right) => {
    const leftEntry = packages[left];
    const rightEntry = packages[right];
    const leftKey = `${packageNameFromPath(left)}@${leftEntry.version}:${left}`;
    const rightKey = `${packageNameFromPath(right)}@${rightEntry.version}:${right}`;
    return leftKey.localeCompare(rightKey);
  });
}

async function readLicense(packagePath, packageVersion) {
  const directory = join(packageRoot, packagePath);
  let primary;
  for (const name of licenseNames) {
    try {
      const text = await readFile(join(directory, name), "utf8");
      primary = { name, text: normalizeLicenseText(text) };
      break;
    } catch (error) {
      if (
        !(error instanceof Error) ||
        !("code" in error) ||
        error.code !== "ENOENT"
      ) {
        throw error;
      }
    }
  }
  if (!primary) {
    const fallback = reviewedLicenseFallbacks[packagePath];
    const reviewedSource = reviewedLicenseSources[packagePath];
    if (fallback) {
      if (fallback.version !== packageVersion) {
        throw new Error(
          `Reviewed license fallback is stale for ${packagePath}@${packageVersion}`,
        );
      }
      primary = {
        name: `reviewed fallback for ${packagePath}@${packageVersion}`,
        text: fallback.text,
      };
    } else if (reviewedSource) {
      if (reviewedSource.version !== packageVersion) {
        throw new Error(
          `Reviewed license source is stale for ${packagePath}@${packageVersion}`,
        );
      }
      primary = {
        name: `reviewed upstream text from ${reviewedSource.path}`,
        text: normalizeLicenseText(
          await readFile(join(packageRoot, reviewedSource.path), "utf8"),
        ),
      };
    } else {
      throw new Error(`No complete license text found for ${packagePath}`);
    }
  }

  const supplements = [];
  for (const relativePath of supplementalLicenseSources[packagePath] ?? []) {
    supplements.push({
      name: relativePath,
      text: normalizeLicenseText(
        await readFile(join(directory, relativePath), "utf8"),
      ),
    });
  }
  return {
    name: [primary.name, ...supplements.map(({ name }) => name)].join(" + "),
    text: [
      primary.text,
      ...supplements.map(
        ({ name, text }) =>
          `Supplemental license and notice text from ${name}\n\n${text}`,
      ),
    ].join("\n\n"),
  };
}

function sourceUrl(entry) {
  if (typeof entry.resolved === "string") {
    return entry.resolved;
  }
  return "bundled from the exact package-lock.json entry";
}

export async function generateWebsiteThirdPartyLicenses() {
  const lock = JSON.parse(await readFile(lockPath, "utf8"));
  const packagePaths = productionClosure(lock);
  const records = [];

  for (const packagePath of packagePaths) {
    const entry = lock.packages[packagePath];
    const name = packageNameFromPath(packagePath);
    if (
      typeof entry.version !== "string" ||
      typeof entry.license !== "string"
    ) {
      throw new Error(`Incomplete package metadata for ${packagePath}`);
    }
    const license = await readLicense(packagePath, entry.version);
    records.push(
      [
        "================================================================================",
        `${name} ${entry.version}`,
        `Installed path: ${packagePath}`,
        `SPDX license: ${entry.license}`,
        `Source: ${sourceUrl(entry)}`,
        `License file: ${license.name}`,
        "",
        license.text,
        "",
      ].join("\n"),
    );
  }

  return [
    "PyBLE website third-party notices",
    "====================================",
    "",
    "This deterministic file covers the production npm dependency closure",
    "bundled into the PyBLE website. It is separate from the firmware image",
    "and from the firmware release licensing evidence.",
    "",
    `Packages: ${records.length}`,
    "",
    ...records,
  ].join("\n");
}

async function run() {
  const generated = await generateWebsiteThirdPartyLicenses();
  const check = process.argv.includes("--check");
  if (check) {
    let current;
    try {
      current = await readFile(noticePath, "utf8");
    } catch (error) {
      throw new Error(
        `Website notice is missing; run ${basename(process.argv[1])} without --check`,
        { cause: error },
      );
    }
    if (current !== generated) {
      throw new Error(
        "WEBSITE_THIRD_PARTY_LICENSES.txt is stale; regenerate it from package-lock.json",
      );
    }
    return;
  }
  await writeFile(noticePath, generated, "utf8");
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

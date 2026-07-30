// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

import { readFile } from "node:fs/promises";
import { join } from "node:path";

import { beforeAll, describe, expect, it } from "vitest";

const deployScript = join(process.cwd(), "deploy", "vps", "deploy.sh");
let script = "";

beforeAll(async () => {
  script = await readFile(deployScript, "utf8");
});

describe("self-hosted firmware activation", () => {
  it("accepts only a canonically validated all-HIL-passed public staged release", () => {
    const stagedBranch = script.indexOf(
      "if [[ -n ${PYBLE_FIRMWARE_STAGED_ROOT:-} ]]; then",
    );
    const canonicalValidation = script.indexOf("--verify-staged", stagedBranch);
    const publicGate = script.indexOf(
      'descriptor.deployment !== "public"',
      stagedBranch,
    );
    const hilGate = script.indexOf(
      'descriptor.hilStatus !== "passed"',
      stagedBranch,
    );
    const build = script.indexOf("NEXT_TELEMETRY_DISABLED=1 npm run check");

    expect(stagedBranch).toBeGreaterThan(-1);
    expect(canonicalValidation).toBeGreaterThan(stagedBranch);
    expect(publicGate).toBeGreaterThan(canonicalValidation);
    expect(hilGate).toBeGreaterThan(canonicalValidation);
    expect(hilGate).toBeLessThan(build);
    expect(script).not.toContain("PYBLE_GITHUB_REPOSITORY");
    expect(script).not.toMatch(/\bgh\s+(?:api|repo|release)\b/);
    expect(script).not.toContain("--verify-published");
  });

  it("binds release provenance to an unchanged local annotated tag before and after the build", () => {
    const build = script.indexOf("NEXT_TELEMETRY_DISABLED=1 npm run check");
    const verifier = /verify_local_firmware_tag\(\)\s*\{([\s\S]*?)^\}/m.exec(
      script,
    )?.[1];
    const before = script.indexOf("local_firmware_tag_object_before_build");
    const after = script.indexOf(
      "local_firmware_tag_object_after_build",
      build,
    );

    expect(verifier).toBeDefined();
    expect.soft(verifier).toContain("refs/tags/${firmware_tag}");
    expect.soft(verifier).toMatch(/git[\s\S]*cat-file[\s\S]*-t/);
    expect.soft(verifier).toMatch(/(?:object_type|tag_type)[\s\S]*"tag"/);
    expect.soft(verifier).toMatch(/\^\{commit\}/);
    expect.soft(verifier).toContain("firmware_provenance_commit");
    expect.soft(verifier).toContain("expected_tag_object");
    expect(before).toBeGreaterThan(-1);
    expect(before).toBeLessThan(build);
    expect(after).toBeGreaterThan(build);
    expect(script.slice(after, after + 800)).toContain(
      "local_firmware_tag_object_before_build",
    );
  });

  it("copies verified staging into a mode-0700 trusted local snapshot", () => {
    const snapshot = script.indexOf("trusted_firmware_snapshot");
    const snapshotParity = script.indexOf(
      '"trusted local firmware snapshot"',
      snapshot,
    );
    const snapshotValidation = script.indexOf("--verify-staged", snapshot);

    expect(script).toMatch(
      /firmware_evidence_root=\$\(mktemp -d\)[\s\S]{0,200}chmod 0700/,
    );
    expect(script).toMatch(
      /mkdir -m 0700 -- "\$\{trusted_firmware_snapshot\}"/,
    );
    expect(script).toMatch(
      /cp -a -- "\$\{staged_firmware_root\}\/\." "\$\{trusted_firmware_snapshot\}\/"/,
    );
    expect(snapshotParity).toBeGreaterThan(snapshot);
    expect(script.slice(snapshotParity - 300, snapshotParity)).toContain(
      '"${staged_firmware_root}"',
    );
    expect(script.slice(snapshotParity - 300, snapshotParity)).toContain(
      '"${trusted_firmware_snapshot}"',
    );
    expect(snapshotValidation).toBeGreaterThan(snapshot);
    expect(script).toContain(
      'staged_firmware_root="${trusted_firmware_snapshot}"',
    );
  });

  it("proves exact staged-to-output-to-upload firmware parity before rsync", () => {
    const packageCopy = script.indexOf(
      'cp -R "${staged_firmware_root}/firmware" out/',
    );
    const outputParity = script.indexOf(
      '"packaged website firmware"',
      packageCopy,
    );
    const uploadSnapshot = script.indexOf("readonly trusted_upload_snapshot");
    const uploadParity = script.indexOf(
      '"trusted upload snapshot firmware"',
      uploadSnapshot,
    );
    const upload = script.search(/\brsync\b/);

    expect(script).toMatch(
      /verify_firmware_tree_parity\(\)[\s\S]{0,500}diff --recursive --brief --no-dereference/,
    );
    expect(packageCopy).toBeGreaterThan(-1);
    expect(outputParity).toBeGreaterThan(packageCopy);
    expect(script.slice(outputParity - 300, outputParity)).toContain(
      '"${staged_firmware_root}/firmware"',
    );
    expect(script.slice(outputParity - 300, outputParity)).toContain(
      '"${web_directory}/out/firmware"',
    );
    expect(uploadParity).toBeGreaterThan(uploadSnapshot);
    expect(script.slice(uploadParity - 300, uploadParity)).toContain(
      '"${trusted_upload_snapshot}/firmware"',
    );
    expect(uploadParity).toBeLessThan(upload);
  });

  it("retains private firmware evidence until the exact upload snapshot is frozen", () => {
    const cleanup = /cleanup_firmware_evidence\(\)\s*\{([\s\S]*?)^\}/m.exec(
      script,
    )?.[1];
    const parity = script.indexOf('"trusted upload snapshot firmware"');
    const cleanupCall = script.lastIndexOf("cleanup_firmware_evidence");

    expect(cleanup).toBeDefined();
    expect.soft(cleanup).toMatch(/chmod -R u\+w/);
    expect.soft(cleanup).toMatch(/rm -rf/);
    expect(cleanupCall).toBeGreaterThan(parity);
  });
});

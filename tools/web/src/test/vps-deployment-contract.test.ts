// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

import { execFile as execFileCallback } from "node:child_process";
import { access, readFile } from "node:fs/promises";
import { constants } from "node:fs";
import { join } from "node:path";
import { promisify } from "node:util";

import { describe, expect, it } from "vitest";

const deploymentRoot = join(process.cwd(), "deploy");
const execFile = promisify(execFileCallback);

describe("Cloudflare-fronted VPS deployment", () => {
  it("serves the portable export with canonical routes and a true static 404", async () => {
    const config = await readFile(
      join(deploymentRoot, "nginx", "10-pyble-dev-https.conf"),
      "utf8",
    );

    expect(config).toContain("root /srv/pyble/current;");
    expect(config).toMatch(/server_name\s+pyble\.dev;/);
    expect(config).toMatch(
      /location = \/(privacy|support|flash)\s*\{[\s\S]*?\.html/,
    );
    expect(config).toMatch(/location = \/(privacy|support|flash)\/\s*\{/);
    expect(config).toContain("error_page 404 /404.html;");
    expect(config).toMatch(/location = \/404\.html\s*\{[\s\S]*?internal;/);
    expect(config).not.toContain("proxy_pass");
  });

  it("defines TLS, cache, MIME, and security-header boundaries", async () => {
    const [config, headers] = await Promise.all([
      readFile(
        join(deploymentRoot, "nginx", "10-pyble-dev-https.conf"),
        "utf8",
      ),
      readFile(
        join(deploymentRoot, "nginx", "pyble-security-headers.conf"),
        "utf8",
      ),
    ]);

    expect(config).toContain("ssl_certificate ");
    expect(config).toContain("ssl_certificate_key ");
    expect(config).toContain("ssl_protocols TLSv1.2 TLSv1.3;");
    expect(config).toContain("ssl_session_tickets off;");
    expect(config).not.toContain("options-ssl-nginx.conf");
    expect(config).toMatch(/location \^~ \/_next\/static\/[\s\S]*?immutable/);
    expect(config).toMatch(
      /location = \/manifest\.webmanifest[\s\S]*?application\/manifest\+json/,
    );
    expect(config).toMatch(
      /location \^~ \/firmware\/[\s\S]*?\$pyble_firmware_cache_control/,
    );
    expect(config).toMatch(
      /map \$status \$pyble_firmware_cache_control[\s\S]*?2\[0-9\]\[0-9\][\s\S]*?304[\s\S]*?max-age=31536000, immutable[\s\S]*?default "no-store"/,
    );
    expect(config).toMatch(
      /location \^~ \/firmware\/[\s\S]*?add_header Cache-Control \$pyble_firmware_cache_control always/,
    );
    expect(config).not.toMatch(
      /location \^~ \/firmware\/[\s\S]*?add_header Cache-Control "public, max-age=31536000, immutable" always/,
    );
    expect(config).toMatch(
      /location \^~ \/firmware\/[\s\S]*?application\/json[\s\S]*?json/,
    );
    expect(config).toMatch(
      /location \^~ \/firmware\/[\s\S]*?application\/octet-stream[\s\S]*?bin/,
    );
    expect(config).toContain('Cache-Control "no-cache, no-transform"');
    expect(config).not.toContain('add_header Cache-Control "no-cache" always;');
    for (const route of ["/", "/privacy", "/support", "/flash"]) {
      const locationStart = config.indexOf(`location = ${route} {`);
      const locationEnd = config.indexOf("\n    }", locationStart);
      const locationBlock = config.slice(locationStart, locationEnd);

      expect
        .soft(locationStart, `${route} location must exist`)
        .toBeGreaterThan(-1);
      expect
        .soft(locationBlock, `${route} must prohibit edge transformations`)
        .toContain('add_header Cache-Control "no-cache, no-transform" always;');
    }
    expect(headers).toContain("X-Content-Type-Options");
    expect(headers).toContain("Content-Security-Policy");
    expect(headers).toContain("serial=(self)");
    expect(headers).toContain("Strict-Transport-Security");
  });

  it("refuses deployment when active Nginx contracts differ from source", async () => {
    const script = await readFile(
      join(deploymentRoot, "vps", "deploy.sh"),
      "utf8",
    );
    const parityIndex = script.indexOf("verify_remote_runtime_config");
    const buildIndex = script.indexOf(
      "NEXT_TELEMETRY_DISABLED=1 npm run check",
    );
    const uploadIndex = script.search(/\brsync\b/);

    expect(parityIndex).toBeGreaterThan(-1);
    expect(parityIndex).toBeLessThan(buildIndex);
    expect(parityIndex).toBeLessThan(uploadIndex);
    expect(script).toContain(
      "/etc/nginx/sites-available/10-pyble-dev-https.conf",
    );
    expect(script).toContain("/etc/nginx/snippets/pyble-security-headers.conf");
    expect(script).toMatch(
      /verify_remote_runtime_config\(\)[\s\S]*?shasum[\s\S]*?ssh[\s\S]*?sha256sum[\s\S]*?(?:mismatch|differs)/i,
    );
  });

  it("keeps firmware 404 responses non-cacheable through the shared error page", async () => {
    const config = await readFile(
      join(deploymentRoot, "nginx", "10-pyble-dev-https.conf"),
      "utf8",
    );

    expect(config).toMatch(
      /map \$request_uri \$pyble_not_found_cache_control\s*\{[\s\S]*?~\^\/firmware\/ "no-store";[\s\S]*?default "no-cache, no-transform";[\s\S]*?\}/,
    );
    expect(config).toMatch(
      /location = \/404\.html\s*\{[\s\S]*?add_header Cache-Control \$pyble_not_found_cache_control always;/,
    );
  });

  it("keeps retired unversioned social-card 404 responses out of caches", async () => {
    const [config, script] = await Promise.all([
      readFile(
        join(deploymentRoot, "nginx", "10-pyble-dev-https.conf"),
        "utf8",
      ),
      readFile(join(deploymentRoot, "vps", "deploy.sh"), "utf8"),
    ]);

    for (const extension of ["png", "svg"]) {
      const path = `/social/pyble-beta-og-1200x630.${extension}`;
      expect(config).toContain(`"${path}" "no-store";`);
      expect(config).toContain(`~^${path.replace(".", "\\.")}\\? "no-store";`);
    }
    expect(script).toContain("retired_public_asset_paths=(");
    expect(script).toContain("/social/pyble-beta-og-1200x630.png");
    expect(script).toContain("/social/pyble-beta-og-1200x630.svg");
    expect(script).toContain("retired_public_asset_methods=( GET HEAD )");
    expect(script).toContain('--request "${retired_public_asset_method}"');
    expect(script).not.toContain("retired_public_asset_curl_mode");
    expect(script).toMatch(/retired_public_asset_status[\s\S]*?!= 404/);
    expect(script).toContain("Cache-Control: *no-store");
  });

  it("routes the exact v0.4.2 public beta through the immutable firmware boundary", async () => {
    const config = await readFile(
      join(deploymentRoot, "nginx", "10-pyble-dev-https.conf"),
      "utf8",
    );
    expect(config).not.toContain("location ^~ /firmware/v0.4.2/");
    expect(config).not.toContain("@burned_firmware_candidate");
    expect(config).toMatch(
      /location \^~ \/firmware\/\s*\{[\s\S]*?alias \/srv\/pyble\/firmware\//,
    );
  });

  it("preserves path and query while canonicalizing every alternate host", async () => {
    const [httpConfig, devConfig, orgConfig] = await Promise.all([
      readFile(join(deploymentRoot, "nginx", "00-pyble-http.conf"), "utf8"),
      readFile(
        join(deploymentRoot, "nginx", "10-pyble-dev-https.conf"),
        "utf8",
      ),
      readFile(
        join(deploymentRoot, "nginx", "20-pyble-org-https.conf"),
        "utf8",
      ),
    ]);

    expect(httpConfig).toContain(
      "server_name pyble.dev www.pyble.dev pyble.org www.pyble.org;",
    );
    expect(httpConfig).toContain("return 308 https://pyble.dev$request_uri;");
    expect(devConfig).toMatch(/server_name\s+www\.pyble\.dev;/);
    expect(devConfig).toContain("return 308 https://pyble.dev$request_uri;");
    expect(orgConfig).toContain("server_name pyble.org www.pyble.org;");
    expect(orgConfig).toContain("return 308 https://pyble.dev$request_uri;");
  });

  it("deploys a checked commit as an atomic, reversible release", async () => {
    const scriptPath = join(deploymentRoot, "vps", "deploy.sh");
    const script = await readFile(scriptPath, "utf8");

    await expect(access(scriptPath, constants.X_OK)).resolves.toBeUndefined();
    expect(script).toContain("NEXT_TELEMETRY_DISABLED=1 npm run check");
    expect(script).toContain("/srv/pyble/releases");
    expect(script).toContain("/srv/pyble/current");
    expect(script).toMatch(/git(?: -C [^\n]+)? rev-parse HEAD/);
    expect(script).toContain("nginx -t");
    expect(script).toContain("systemctl reload nginx");
    expect(script).toContain("-type d -exec chmod 0755");
    expect(script).toContain("-type f -exec chmod 0644");
    expect(script).toContain("firmware/v");
    expect(script).toContain("release.json");
    expect(script).toContain("SHA256SUMS");
    expect(script).toContain("WEBSITE_THIRD_PARTY_LICENSES.txt");
    expect(script).toMatch(/sha256sum\s+--check/);
    expect(script).toMatch(
      /curl[\s\S]*?--location[\s\S]*?--max-redirs\s+0[\s\S]*?firmware\/v/,
    );
    expect(script).toMatch(
      /cmp[\s\S]*?SHA256SUMS[\s\S]*?shasum[\s\S]*?--check/,
    );
    expect(script).not.toContain("--chmod=");
    expect(script).not.toMatch(/\b(?:\d{1,3}\.){3}\d{1,3}\b/);
    expect(script).not.toMatch(/BEGIN (?:RSA |OPENSSH )?PRIVATE KEY/);
  });

  it("accepts only the exact unrestricted pending public beta in the activation path", async () => {
    const [script, staging] = await Promise.all([
      readFile(join(deploymentRoot, "vps", "deploy.sh"), "utf8"),
      readFile(
        join(process.cwd(), "scripts", "stage-firmware-release.js"),
        "utf8",
      ),
    ]);

    expect(script).toContain('descriptor.deployment === "public-beta"');
    expect(script).toContain('descriptor.hilStatus === "pending"');
    expect(script).toContain("descriptor.accessControlled === false");
    expect(script).toContain(
      "5d1b0db8c4b90cccf054cd244530afb3b9112d489aa02f7c5da650e92161acde",
    );
    expect(staging).toMatch(
      /public-beta[\s\S]*?--audited-candidate[\s\S]*?--license-evidence-dir[\s\S]*?--license-build-root/,
    );
    expect(script).toContain("PYBLE_FIRMWARE_LICENSE_EVIDENCE_DIR");
    expect(script).toContain("PYBLE_FIRMWARE_LICENSE_BUILD_ROOT");
    expect(script).toContain("PYBLE_FIRMWARE_SOURCE_ROOT");
    expect(script).toMatch(
      /if \[\[ "\$\{firmware_deployment\}" == public-beta \]\]; then\s+require_firmware_release_inputs\s+fi/,
    );
    expect(script).toContain("local_firmware_tag_object_before_build");
    expect(script).not.toMatch(
      /public-beta[\s\S]{0,180}(?:skip|does not require)[\s\S]{0,180}annotated tag/i,
    );
  });

  it("retains deployment-evidence cleanup after installing the smoke-test EXIT trap", async () => {
    const script = await readFile(
      join(deploymentRoot, "vps", "deploy.sh"),
      "utf8",
    );
    const smokeCleanupBody = /cleanup_smoke\(\)\s*\{([\s\S]*?)^\}/m.exec(
      script,
    )?.[1];

    expect(script).toContain("trap cleanup_smoke EXIT");
    expect(smokeCleanupBody).toBeDefined();
    expect(smokeCleanupBody).toMatch(/\bcleanup_deployment_evidence\b/);
  });

  it("restores the previous current-release target if a post-activation smoke test fails", async () => {
    const script = await readFile(
      join(deploymentRoot, "vps", "deploy.sh"),
      "utf8",
    );

    expect
      .soft(script)
      .toMatch(
        /(?:(?:previous|prior|old|rollback)_(?:release|target|current)[\s\S]{0,400}readlink|readlink[\s\S]{0,400}(?:previous|prior|old|rollback)_(?:release|target|current))/i,
      );
    expect.soft(script).toMatch(/rollback|restore/i);
    expect
      .soft(script)
      .toMatch(
        /(?:trap[^\n]*(?:rollback|restore)|if\s+![\s\S]{0,1200}(?:rollback|restore))/i,
      );
    expect
      .soft(script)
      .toMatch(
        /(?:rollback|restore)[\s\S]{0,1600}(?:ln\s+-s|mv\s+-Tf)[\s\S]{0,500}(?:current_release|\/srv\/pyble\/current)/i,
      );
  });

  it("routes explicit post-activation smoke rejections through rollback", async () => {
    const script = await readFile(
      join(deploymentRoot, "vps", "deploy.sh"),
      "utf8",
    );
    const smokeStart = script.indexOf("trap rollback_on_smoke_error ERR");
    const smokeEnd = script.indexOf("trap - ERR", smokeStart + 1);
    const smokeRegion = script.slice(smokeStart, smokeEnd);

    expect(smokeStart).toBeGreaterThan(-1);
    expect(smokeEnd).toBeGreaterThan(smokeStart);
    expect(script).toMatch(
      /reject_post_activation_smoke\(\)[\s\S]*?return\s+"\$\{smoke_status\}"/,
    );
    expect(smokeRegion).not.toMatch(/\bexit\s+(?:66|67)\b/);
    expect(smokeRegion).toMatch(/\breject_post_activation_smoke\s+(?:66|67)\b/);
  });

  it("arms rollback before the current symlink can switch or the activation SSH can fail", async () => {
    const script = await readFile(
      join(deploymentRoot, "vps", "deploy.sh"),
      "utf8",
    );
    const switchIndex = script.indexOf(
      'mv -Tf -- "${next_link}" "${current_release}"',
    );
    const reloadIndex = script.indexOf("systemctl reload nginx", switchIndex);
    const rollbackTrapIndices = [
      ...script.matchAll(/trap[^\n]*(?:rollback|restore)/gi),
    ].map(({ index }) => index ?? -1);

    expect(switchIndex).toBeGreaterThan(-1);
    expect(reloadIndex).toBeGreaterThan(switchIndex);
    expect(
      rollbackTrapIndices.some(
        (trapIndex) => trapIndex >= 0 && trapIndex < switchIndex,
      ),
      "rollback must already be armed when activation switches current, reloads Nginx, or loses SSH",
    ).toBe(true);
    expect(
      script,
      "a transport-independent rollback watchdog must survive loss of the activation SSH session",
    ).toMatch(
      /systemd-run[\s\S]{0,2400}(?:rollback|restore)[\s\S]{0,1600}(?:current_release|\/srv\/pyble\/current)/i,
    );
    expect(
      script,
      "the rollback watchdog may be cancelled only after production smoke succeeds",
    ).toMatch(
      /(?:systemctl\s+(?:stop|cancel|reset-failed)|rm\s+-f)[^\n]*(?:watchdog|rollback|activation)[\s\S]{0,1200}(?:smoke|deployed|confirmed)/i,
    );
  });

  it("serves firmware from persistent immutable storage and rejects divergent version reuse", async () => {
    const [script, config] = await Promise.all([
      readFile(join(deploymentRoot, "vps", "deploy.sh"), "utf8"),
      readFile(
        join(deploymentRoot, "nginx", "10-pyble-dev-https.conf"),
        "utf8",
      ),
    ]);
    const firmwareLocation =
      /location \^~ \/firmware\/\s*\{([\s\S]*?)\n\s*\}/.exec(config)?.[1];

    expect(firmwareLocation).toBeDefined();
    expect.soft(firmwareLocation).toMatch(/alias\s+\/srv\/pyble\/firmware\//);
    expect.soft(script).toContain("/srv/pyble/firmware");
    expect
      .soft(script)
      .toMatch(
        /if\s+\[\[\s+-[ed]\s+[^\n]*(?:firmware|version)[^\n]*\]\][\s\S]{0,1600}(?:cmp|diff|sha256sum)[\s\S]{0,600}(?:exit|return)/i,
      );
    expect
      .soft(script)
      .not.toMatch(
        /(?:rm\s+-[^\n]*|rsync[\s\S]{0,200}--delete)[^\n]*\/srv\/pyble\/firmware/,
      );
  });

  it("retains a trusted upload inventory and verifies every remote byte before activation", async () => {
    const script = await readFile(
      join(deploymentRoot, "vps", "deploy.sh"),
      "utf8",
    );
    const finalFirmwareParity = script.lastIndexOf(
      '"trusted upload snapshot firmware"',
    );
    const uploadIndex = script.search(/\brsync\b/);
    const remoteActivationIndex = script.indexOf("previous_release=$(");
    const switchIndex = script.indexOf(
      'mv -Tf -- "${next_link}" "${current_release}"',
    );
    const trustedRecordPattern =
      /(?:trusted|deployment|upload|site)[_-](?:file[_-])?(?:inventory|snapshot|checksums?)/gi;
    const trustedRecordIndices = [...script.matchAll(trustedRecordPattern)].map(
      ({ index }) => index ?? -1,
    );
    const trustedRecordBeforeUpload =
      trustedRecordIndices.find(
        (index) => index > finalFirmwareParity && index < uploadIndex,
      ) ?? -1;
    const trustedRecordAfterUpload =
      trustedRecordIndices.find((index) => index > remoteActivationIndex) ?? -1;
    const remoteActivation = script.slice(remoteActivationIndex, switchIndex);

    expect.soft(finalFirmwareParity).toBeGreaterThan(-1);
    expect
      .soft(
        trustedRecordBeforeUpload,
        "a trusted whole-site inventory or immutable snapshot must be frozen after final validation",
      )
      .toBeGreaterThan(finalFirmwareParity);
    expect.soft(trustedRecordBeforeUpload).toBeLessThan(uploadIndex);
    expect
      .soft(
        trustedRecordAfterUpload,
        "the trusted record must survive upload and enter remote verification",
      )
      .toBeGreaterThan(remoteActivationIndex);
    expect
      .soft(
        remoteActivation,
        "remote verification must cover the exact file set",
      )
      .toMatch(
        /find[\s\S]{0,1200}(?:diff|cmp)[\s\S]{0,600}(?:inventory|checksums?|file[_-]list)/i,
      );
    expect
      .soft(
        remoteActivation,
        "remote verification must cover every file digest",
      )
      .toMatch(
        /(?:sha256sum\s+--check|shasum[\s\S]{0,160}--check)[^\n]*(?:inventory|checksums?)/i,
      );
    expect
      .soft(
        remoteActivation,
        "the remote must authenticate the retained inventory itself",
      )
      .toMatch(
        /(?:inventory|checksums?)[\s\S]{0,800}(?:sha256sum|shasum|digest)[\s\S]{0,800}(?:expected|mismatch|!=|cmp)/i,
      );
  });

  it("confirms activation only after watchdog cancellation is proven", async () => {
    const script = await readFile(
      join(deploymentRoot, "vps", "deploy.sh"),
      "utf8",
    );
    const confirmationFunction =
      /confirm_activation\(\)\s*\{([\s\S]*?)\n\}/.exec(script)?.[1];

    expect(confirmationFunction).toBeDefined();
    if (!confirmationFunction) {
      return;
    }

    const markerCreateIndex = confirmationFunction.indexOf(
      'install -m 0600 /dev/null "${activation_confirmation}"',
    );
    const watchdogStopIndex = confirmationFunction.search(
      /systemctl\s+stop\s+"?\$\{activation_watchdog_unit\}\.timer"?/,
    );
    const inactiveProofIndex = confirmationFunction.search(
      /systemctl\s+(?:is-active|show)[^\n]*(?:activation_watchdog_unit|watchdog)/,
    );
    const markerRemovalIndex = confirmationFunction.lastIndexOf(
      'rm -f -- "${activation_confirmation}"',
    );

    expect.soft(markerCreateIndex).toBeGreaterThan(-1);
    expect.soft(watchdogStopIndex).toBeGreaterThan(markerCreateIndex);
    expect
      .soft(confirmationFunction)
      .not.toMatch(
        /systemctl\s+stop\s+[^\n]*(?:activation_watchdog_unit|watchdog)[^\n]*\|\|\s*true/,
      );
    expect.soft(inactiveProofIndex).toBeGreaterThan(watchdogStopIndex);
    expect.soft(markerRemovalIndex).toBeGreaterThan(inactiveProofIndex);
  });

  it("passes transient activation programs verbatim to systemd", async () => {
    const script = await readFile(
      join(deploymentRoot, "vps", "deploy.sh"),
      "utf8",
    );
    const transientShellRuns = [
      ...script.matchAll(/systemd-run[\s\S]*?\/bin\/bash -c '/g),
    ].map((match) => match[0]);

    expect(transientShellRuns).toHaveLength(2);
    for (const invocation of transientShellRuns) {
      expect(invocation).toContain("--expand-environment=no");
    }
  });

  it("checks the byte-stable cache policy during public route smoke", async () => {
    const script = await readFile(
      join(deploymentRoot, "vps", "deploy.sh"),
      "utf8",
    );
    const publicRouteSmoke =
      /for route in \/ \/privacy \/support \/flash; do([\s\S]*?)\ndone/.exec(
        script,
      )?.[1];

    expect(publicRouteSmoke).toBeDefined();
    expect(publicRouteSmoke).toContain(
      "Cache-Control: *no-cache, *no-transform",
    );
  });

  it("requires missing firmware and deferred C3 smoke responses to be 404 no-store", async () => {
    const script = await readFile(
      join(deploymentRoot, "vps", "deploy.sh"),
      "utf8",
    );
    const smokeStart = script.indexOf("firmware_not_found_paths=(");
    const smokeEnd = script.indexOf("confirm_activation", smokeStart);
    const firmwareNotFoundSmoke = script.slice(smokeStart, smokeEnd);

    expect(smokeStart).toBeGreaterThan(-1);
    expect(smokeEnd).toBeGreaterThan(smokeStart);
    expect(firmwareNotFoundSmoke).toContain("/firmware/not-found-smoke");
    expect(firmwareNotFoundSmoke).toContain("/firmware/v0.4.1/release.json");
    expect(firmwareNotFoundSmoke).toContain(
      "/firmware/v0.4.1/esp32-4mb/manifest.json",
    );
    expect(firmwareNotFoundSmoke).toContain(
      "firmware_not_found_methods=( GET HEAD )",
    );
    expect(firmwareNotFoundSmoke).toContain(
      '--request "${firmware_not_found_method}"',
    );
    expect(firmwareNotFoundSmoke).not.toContain("firmware_not_found_curl_mode");
    expect(firmwareNotFoundSmoke).toContain("esp32-c3-4mb/manifest.json");
    expect(firmwareNotFoundSmoke).toContain("--dump-header");
    expect(firmwareNotFoundSmoke).toContain("--write-out '%{http_code}'");
    expect(firmwareNotFoundSmoke).toMatch(
      /firmware_not_found_status[\s\S]*?!= 404/,
    );
    expect(firmwareNotFoundSmoke).toContain("Cache-Control: *no-store");
  });

  it("freezes one clean full source commit through the completed website build", async () => {
    const script = await readFile(
      join(deploymentRoot, "vps", "deploy.sh"),
      "utf8",
    );
    const buildIndex = script.indexOf(
      "NEXT_TELEMETRY_DISABLED=1 npm run check",
    );
    const headChecks = [
      ...script.matchAll(/git(?:\s+-C\s+[^\n]+)?\s+rev-parse\s+HEAD/g),
    ].map(({ index }) => index ?? -1);
    const statusChecks = [
      ...script.matchAll(/git(?:\s+-C\s+[^\n]+)?\s+status\b/g),
    ].map(({ index }) => index ?? -1);

    expect.soft(script).not.toMatch(/git[^\n]*status[^\n]*--\s+tools\/web/);
    expect
      .soft(headChecks.some((index) => index >= 0 && index < buildIndex))
      .toBe(true);
    expect.soft(headChecks.some((index) => index > buildIndex)).toBe(true);
    expect.soft(statusChecks.some((index) => index > buildIndex)).toBe(true);
    expect
      .soft(script)
      .toMatch(
        /(?:\.pyble-source-commit|source[-_]commit|commit[-_]sha)[\s\S]{0,500}(?:out\/|incoming_release|final_release)[\s\S]{0,500}\$\{?commit\}?/i,
      );
  });

  it("cannot inherit an installer selection or stale firmware during a site-only deploy", async () => {
    const script = await readFile(
      join(deploymentRoot, "vps", "deploy.sh"),
      "utf8",
    );
    const externalSelectionGuard = script.search(
      /if\s+\[\[\s+-n\s+\$\{PYBLE_FLASH_SELECTION_FILE:-\}\s+\]\]/,
    );
    const stagedRootBranch = script.search(
      /if\s+\[\[\s+-n\s+\$\{PYBLE_FIRMWARE_STAGED_ROOT:-\}\s+\]\]/,
    );
    const buildIndex = script.indexOf(
      "NEXT_TELEMETRY_DISABLED=1 npm run check",
    );
    const staleRemovalIndex = script.indexOf("rm -rf -- out/firmware");
    const cleanOutputAssertionIndex = script.indexOf(
      "test ! -e out/firmware",
      buildIndex,
    );

    expect(
      externalSelectionGuard,
      "the deploy wrapper must reject a caller-supplied build selector",
    ).toBeGreaterThan(-1);
    expect(externalSelectionGuard).toBeLessThan(stagedRootBranch);
    expect(script).toMatch(
      /PYBLE_FLASH_SELECTION_FILE[\s\S]{0,400}(?:Refusing|exit\s+65)/,
    );
    expect(script).toContain("unset PYBLE_FLASH_SELECTION_FILE");
    expect(staleRemovalIndex).toBeGreaterThan(-1);
    expect(staleRemovalIndex).toBeLessThan(buildIndex);
    expect(cleanOutputAssertionIndex).toBeGreaterThan(buildIndex);
  });

  it("cannot silently replace an active installer with the unavailable page", async () => {
    const script = await readFile(
      join(deploymentRoot, "vps", "deploy.sh"),
      "utf8",
    );
    const marker = ".pyble-firmware-release-selection.json";
    const buildIndex = script.indexOf(
      "NEXT_TELEMETRY_DISABLED=1 npm run check",
    );
    const markerLookup = script.indexOf(marker);
    const explicitDisable = script.indexOf(
      "PYBLE_EXPLICITLY_DISABLE_PUBLIC_INSTALLER",
    );

    expect(markerLookup).toBeGreaterThan(-1);
    expect(markerLookup).toBeLessThan(buildIndex);
    expect(explicitDisable).toBeGreaterThan(-1);
    expect(explicitDisable).toBeLessThan(buildIndex);
    expect
      .soft(script.slice(Math.min(markerLookup, explicitDisable), buildIndex))
      .toMatch(
        /(?:preserv|carry|current)[\s\S]{0,2400}(?:Refusing|exit\s+65|--verify-staged)/i,
      );
  });

  it("rejects every Next production dotenv input before a nominal website-only build", async () => {
    const script = await readFile(
      join(deploymentRoot, "vps", "deploy.sh"),
      "utf8",
    );
    const inheritedSelectionGuard = script.search(
      /if\s+\[\[\s+-n\s+\$\{PYBLE_FLASH_SELECTION_FILE:-\}\s+\]\]/,
    );
    const stagedRootBranch = script.search(
      /if\s+\[\[\s+-n\s+\$\{PYBLE_FIRMWARE_STAGED_ROOT:-\}\s+\]\]/,
    );
    const buildIndex = script.indexOf(
      "NEXT_TELEMETRY_DISABLED=1 npm run check",
    );
    const dotenvGlobIndex = script.search(/\.env\\?\*/);
    const explicitDotenvIndices = [
      ".env.production.local",
      ".env.local",
      ".env.production",
      ".env",
    ].map((name) => script.indexOf(name));
    const hasExhaustiveDotenvGuard =
      dotenvGlobIndex >= 0 ||
      explicitDotenvIndices.every((index) => index >= 0);
    const dotenvGuardIndex =
      dotenvGlobIndex >= 0
        ? dotenvGlobIndex
        : Math.min(
            ...explicitDotenvIndices.filter((index) => index >= 0),
            Number.MAX_SAFE_INTEGER,
          );

    expect
      .soft(
        inheritedSelectionGuard,
        "an inherited selector must be rejected before deployment mode is chosen",
      )
      .toBeGreaterThan(-1);
    expect.soft(inheritedSelectionGuard).toBeLessThan(stagedRootBranch);
    expect
      .soft(
        hasExhaustiveDotenvGuard,
        "Next can inject a selector from .env.production.local, .env.local, .env.production, or .env",
      )
      .toBe(true);
    expect.soft(dotenvGuardIndex).toBeLessThan(stagedRootBranch);
    expect.soft(dotenvGuardIndex).toBeLessThan(buildIndex);
    expect
      .soft(script.slice(dotenvGuardIndex, buildIndex))
      .toMatch(/(?:Refusing|reject|exit\s+65)/i);
  });

  it("uses canonical SemVer for immutable VPS firmware directories", async () => {
    const script = await readFile(
      join(deploymentRoot, "vps", "deploy.sh"),
      "utf8",
    );
    const versionPattern =
      /if\s+\[\[\s+!\s+"\$\{firmware_name\}"\s+=~\s+(\^[^\n]+?)\s+\]\];\s+then/.exec(
        script,
      )?.[1];

    expect(versionPattern).toBeDefined();
    if (!versionPattern) {
      return;
    }
    const matchesVersion = async (value: string) => {
      await execFile(
        "bash",
        [
          "-c",
          `if [[ "$1" =~ ${versionPattern} ]]; then exit 0; else exit 1; fi`,
          "pyble-semver-test",
          value,
        ],
        { cwd: process.cwd() },
      );
    };

    for (const version of [
      "v0.0.0",
      "v1.2.3-alpha.1+build.01",
      "v10.20.30-0.3.7",
    ]) {
      await expect(
        matchesVersion(version),
        `${version} is canonical SemVer`,
      ).resolves.toBeUndefined();
    }
    for (const version of [
      "v1.2.3-01",
      "v1.2.3-a..b",
      "v1.2.3-a.",
      "v1.2.3-.a",
      "v1.2.3+build..1",
    ]) {
      await expect(
        matchesVersion(version),
        `${version} is not canonical SemVer`,
      ).rejects.toBeDefined();
    }
  });

  it("checks the deployed CSP header and rendered route content instead of accepting any 2xx body", async () => {
    const script = await readFile(
      join(deploymentRoot, "vps", "deploy.sh"),
      "utf8",
    );
    const routeSmoke =
      /for route in \/ \/privacy \/support \/flash; do([\s\S]*?)\ndone/.exec(
        script,
      )?.[1];

    expect(routeSmoke).toBeDefined();
    expect.soft(routeSmoke).not.toContain(">/dev/null");
    expect.soft(routeSmoke).toMatch(/--output|=\$\(\s*curl/);
    expect.soft(script).toMatch(/Content-Security-Policy:/i);
    expect
      .soft(script)
      .toMatch(
        /(?:--dump-header|-D\b|--include|-I\b|--head)[\s\S]{0,1200}Content-Security-Policy:/i,
      );
    expect
      .soft(script)
      .toMatch(
        /(?:(?:grep|fgrep)[^\n]*(?:main-content|<!doctype|<main)|cmp[^\n]*(?:index|privacy|support|flash)\.html)/i,
      );
  });

  it("reloads Nginx only after a renewed certificate passes validation", async () => {
    const hookPath = join(
      deploymentRoot,
      "vps",
      "reload-nginx-after-renewal.sh",
    );
    const hook = await readFile(hookPath, "utf8");

    await expect(access(hookPath, constants.X_OK)).resolves.toBeUndefined();
    expect(hook).toContain("nginx -t");
    expect(hook).toContain("systemctl reload nginx");
  });
});

// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import FlashPage from "@/app/flash/page";
import {
  firmwareProfileDescriptors,
  type FirmwareReleaseDescriptor,
} from "@/lib/firmware-release";
import * as firmwareSelection from "@/lib/firmware-release-selection";
import type { LocalFirmwarePreviewDescriptor } from "@/lib/local-firmware-preview";
import {
  hypotheticalPassedPublicFirmwareRelease,
  publicBetaFirmwareRelease,
} from "@/test/fixtures/firmware-release";

function hypotheticalQualifiedReleaseAtVersion(
  version: string,
): FirmwareReleaseDescriptor {
  const release = structuredClone(
    hypotheticalPassedPublicFirmwareRelease,
  ) as unknown as {
    version: string;
    builtAt: string;
    releaseJson: { path: string };
    schemaPath: string;
    recoveryPath: string;
    profiles: Array<{ manifestPath: string; firmwarePath: string }>;
  };
  release.version = version;
  release.builtAt = "2026-08-02T00:00:00Z";
  release.releaseJson.path = `/firmware/v${version}/release.json`;
  release.schemaPath = `/firmware/v${version}/release.schema.json`;
  release.recoveryPath = `/firmware/v${version}/RECOVERY.md`;
  for (const profile of release.profiles) {
    profile.manifestPath = profile.manifestPath.replace(
      "/firmware/v0.5.1/",
      `/firmware/v${version}/`,
    );
    profile.firmwarePath = profile.firmwarePath.replace(
      "/firmware/v0.5.1/",
      `/firmware/v${version}/`,
    );
  }
  return release as unknown as FirmwareReleaseDescriptor;
}

function fiveProfileV060Release(
  deployment: "candidate" | "public",
): FirmwareReleaseDescriptor {
  const version = "0.6.0";
  return {
    deployment,
    accessControlled: deployment === "candidate",
    version,
    builtAt: "2026-08-21T00:00:00Z",
    hilStatus: deployment === "public" ? "passed" : "pending",
    releaseJson: {
      path: `/firmware/v${version}/release.json`,
      sha256: "a".repeat(64),
    },
    schemaPath: `/firmware/v${version}/release.schema.json`,
    recoveryPath: `/firmware/v${version}/RECOVERY.md`,
    profiles: firmwareProfileDescriptors(version),
  } as FirmwareReleaseDescriptor;
}

async function withSelectedRelease(
  release: FirmwareReleaseDescriptor,
  run: () => Promise<void> | void,
) {
  const selectionRoot = await mkdtemp(
    join(tmpdir(), "pyble-flash-five-profile-selection-"),
  );
  const selectionFile = join(selectionRoot, "selection.json");
  const previousSelection = process.env.PYBLE_FLASH_SELECTION_FILE;
  process.env.PYBLE_FLASH_SELECTION_FILE = selectionFile;
  try {
    await writeFile(selectionFile, JSON.stringify(release), "utf8");
    await run();
  } finally {
    if (previousSelection === undefined) {
      delete process.env.PYBLE_FLASH_SELECTION_FILE;
    } else {
      process.env.PYBLE_FLASH_SELECTION_FILE = previousSelection;
    }
    await rm(selectionRoot, { recursive: true, force: true });
  }
}

function expectFiveProfileFlashPageCopy() {
  // The stale planned/unavailable cards must never render beside a
  // five-profile installer that offers those same targets.
  expect(
    screen.queryByRole("heading", { name: /planned profiles/i }),
  ).toBeNull();
  expect(
    screen.queryByText(
      /no installer selection, firmware image, or recovery command is offered yet/i,
    ),
  ).toBeNull();
  expect(screen.queryByText(/pre-GP2/i)).toBeNull();
  expect(
    screen.queryByText(/no public UF2 download or installer action/i),
  ).toBeNull();

  // Accurate five-target provisioning summary instead.
  const methods = screen
    .getByRole("heading", { name: /two provisioning methods/i })
    .closest("section");
  expect(methods).toBeDefined();
  expect(methods).toHaveTextContent(
    /ESP Web Tools.*Web Serial.*four exact ESP profiles/i,
  );
  expect(methods).toHaveTextContent(
    /esp32-4mb.*esp32-s3-n16r8.*waveshare-esp32-s3-lcd-147b.*esp32-c3-4mb/i,
  );
  expect(methods).toHaveTextContent(/Pico 2 W.*BOOTSEL.*UF2/i);

  // The profile explainer covers all five profiles with exact requirements.
  const profileSection = screen
    .getByRole("heading", { name: /choose the exact module profile/i })
    .closest("section");
  expect(profileSection).toBeDefined();
  const classicProfile = within(profileSection as HTMLElement)
    .getByText("esp32-4mb")
    .closest("li");
  expect(classicProfile).toHaveTextContent(/Classic ESP32 module/);
  const c3Profile = within(profileSection as HTMLElement)
    .getByText("esp32-c3-4mb")
    .closest("li");
  expect(c3Profile).toHaveTextContent(/revision v0\.3 or newer.*4 MiB flash/i);
  const waveshareProfile = within(profileSection as HTMLElement)
    .getByText("waveshare-esp32-s3-lcd-147b")
    .closest("li");
  expect(waveshareProfile).toHaveTextContent(
    /B version.*16 MiB flash.*8 MiB Octal PSRAM/i,
  );
  const picoProfile = within(profileSection as HTMLElement)
    .getByText("rpi-pico2-w")
    .closest("li");
  expect(picoProfile).toHaveTextContent(/RP2350.*CYW43439/i);
  expect(picoProfile).toHaveTextContent(/BOOTSEL/i);
  expect(picoProfile).toHaveTextContent(/not a Web Serial flow/i);

  // The real-hardware exact-board photo spotlight stays visible whenever the
  // Waveshare profile is offered by the selected release; the photograph is
  // deliberately the historical v0.5.0 shot of the actual board.
  const boardSection = screen
    .getByRole("heading", { name: "Waveshare ESP32-S3-LCD-1.47B" })
    .closest("section");
  expect(boardSection).toBeDefined();
  expect(boardSection).toHaveTextContent(/real hardware.*not a render/i);
  const boardPhoto = screen.getByRole("img", {
    name: "Actual Waveshare ESP32-S3-LCD-1.47B displaying the PyBLE v0.5.0 boot splash and app QR",
  });
  expect(boardSection).toContainElement(boardPhoto);
  expect(boardPhoto).toHaveAttribute(
    "src",
    "/boards/esp32-s3-lcd-1.47b-pyble-v0.5.0.jpg",
  );
  expect(boardPhoto.closest("figure")).toHaveTextContent(
    /Actual board.*PyBLE firmware v0\.5\.0/i,
  );

  // "Before you connect" must not claim Web Serial or desktop Chromium as a
  // requirement of the Pico flow.
  const beforeConnect = screen
    .getByRole("heading", { name: /before you connect/i })
    .closest("section");
  expect(beforeConnect).toBeDefined();
  expect(beforeConnect).toHaveTextContent(
    /ESP.*Web Serial.*desktop Chromium|desktop Chromium.*Web Serial/i,
  );
  expect(beforeConnect).toHaveTextContent(/Pico 2 W does not use Web Serial/i);
  expect(beforeConnect).toHaveTextContent(/secure context.*Web Crypto/i);
  expect(beforeConnect).not.toHaveTextContent(
    /The installer uses Web Serial and Web Crypto/i,
  );

  // The visible recovery section carries all four ESP merged-image commands.
  const recoverySection = screen
    .getByRole("heading", { name: /recover an interrupted flash/i })
    .closest("section");
  expect(recoverySection).toBeDefined();
  const recoveryCommands = [
    "python -m esptool --chip esp32 write_flash 0x1000 esp32-4mb/firmware.bin",
    "python -m esptool --chip esp32s3 write_flash 0x0 esp32-s3-n16r8/firmware.bin",
    "python -m esptool --chip esp32s3 write_flash 0x0 waveshare-esp32-s3-lcd-147b/firmware.bin",
    "python -m esptool --chip esp32c3 write_flash 0x0 esp32-c3-4mb/firmware.bin",
  ];
  for (const command of recoveryCommands) {
    expect(
      screen.getByText(
        (_content, element) =>
          element?.tagName === "CODE" &&
          element.textContent?.replace(/\s+/g, " ").trim() === command,
      ),
    ).toBeInTheDocument();
  }

  // Component offsets name the C3 beside the S3.
  expect(recoverySection).toHaveTextContent(
    /bootloader at 0x1000 for classic ESP32 or 0x0 for ESP32-S3 and ESP32-C3/i,
  );

  // Separate Pico BOOTSEL re-copy recovery with no esptool/offset/Web Serial
  // fallback inside it.
  const picoRecovery = within(recoverySection as HTMLElement)
    .getByText(/Pico 2 W recovery/i)
    .closest("p");
  expect(picoRecovery).toBeDefined();
  expect(picoRecovery).toHaveTextContent(
    /hold BOOTSEL while reconnecting USB/i,
  );
  expect(picoRecovery).toHaveTextContent(/RP2350 volume/i);
  expect(picoRecovery).toHaveTextContent(/same versioned UF2/i);
  expect(picoRecovery).toHaveTextContent(/automatic reboot/i);
  expect(picoRecovery).toHaveTextContent(/PyBLE-XXXX/i);
  expect(picoRecovery).toHaveTextContent(
    /does not use Web Serial or the ESP ROM recovery controls/i,
  );
  expect(picoRecovery?.textContent).not.toMatch(/esptool|write_flash|0x[0-9]/i);
}

function localPreviewArtifact(
  path: string,
  digestCharacter: string,
  size = 1_024,
) {
  return { path, size, sha256: digestCharacter.repeat(64) };
}

function localFiveBoardPreview(): LocalFirmwarePreviewDescriptor {
  const root = "/.pyble-local-preview";
  return {
    schemaVersion: 1,
    deployment: "local-preview",
    localOnly: true,
    qualified: false,
    version: "0.6.0",
    sourceCommit: "e895a33642627401dbae5c8bd8110802ab143900",
    builtAt: "2026-08-12T00:00:00Z",
    profiles: [
      {
        id: "esp32-4mb",
        label: "ESP32 · 4 MiB flash",
        chipFamily: "ESP32",
        buildTarget: "esp32",
        method: "esp-web-tools",
        qualified: false,
        status: "engineering-preview",
        offset: 4096,
        manifest: localPreviewArtifact(`${root}/esp32-4mb/manifest.json`, "1"),
        firmware: localPreviewArtifact(`${root}/esp32-4mb/firmware.bin`, "2"),
      },
      {
        id: "esp32-s3-n16r8",
        label: "ESP32-S3 · N16R8 · lean generic",
        chipFamily: "ESP32-S3",
        buildTarget: "esp32-s3",
        method: "esp-web-tools",
        qualified: false,
        status: "engineering-preview",
        offset: 0,
        manifest: localPreviewArtifact(
          `${root}/esp32-s3-n16r8/manifest.json`,
          "3",
        ),
        firmware: localPreviewArtifact(
          `${root}/esp32-s3-n16r8/firmware.bin`,
          "4",
        ),
      },
      {
        id: "waveshare-esp32-s3-lcd-147b",
        label: "Waveshare ESP32-S3-LCD-1.47B · N16R8",
        chipFamily: "ESP32-S3",
        buildTarget: "waveshare-esp32-s3-lcd-147b",
        method: "esp-web-tools",
        qualified: false,
        status: "engineering-preview",
        offset: 0,
        manifest: localPreviewArtifact(
          `${root}/waveshare-esp32-s3-lcd-147b/manifest.json`,
          "5",
        ),
        firmware: localPreviewArtifact(
          `${root}/waveshare-esp32-s3-lcd-147b/firmware.bin`,
          "6",
        ),
      },
      {
        id: "esp32-c3-4mb",
        label: "ESP32-C3 revision v0.3+ · 4 MiB flash",
        chipFamily: "ESP32-C3",
        buildTarget: "esp32-c3",
        method: "esp-web-tools",
        qualified: false,
        status: "engineering-preview",
        offset: 0,
        manifest: localPreviewArtifact(
          `${root}/esp32-c3-4mb/manifest.json`,
          "7",
        ),
        firmware: localPreviewArtifact(
          `${root}/esp32-c3-4mb/firmware.bin`,
          "8",
        ),
      },
      {
        id: "rpi-pico2-w",
        label: "Raspberry Pi Pico 2 W",
        chipFamily: "RP2350",
        buildTarget: "rpi-pico2-w",
        method: "uf2-download",
        qualified: false,
        status: "engineering-preview",
        firmware: localPreviewArtifact(`${root}/rpi-pico2-w/firmware.uf2`, "9"),
      },
    ],
  };
}

describe("firmware installer release copy", () => {
  it("wires an explicit local five-board preview into /flash without changing the public default", async () => {
    const preview = localFiveBoardPreview();
    const previewSelection = vi
      .spyOn(firmwareSelection, "localFirmwarePreviewSelectedAtBuild")
      .mockReturnValue(preview);

    try {
      render(<FlashPage />);

      expect(screen.getByRole("main")).toHaveTextContent(
        /local engineering preview.*v?0\.6\.0.*unqualified.*not a public release/i,
      );
      const selector = screen.getByRole("combobox", {
        name: /choose a firmware target/i,
      });
      expect(
        within(selector)
          .getAllByRole("option")
          .filter((option) => (option as HTMLOptionElement).value !== "")
          .map((option) => (option as HTMLOptionElement).value),
      ).toEqual([
        "esp32-4mb",
        "esp32-s3-n16r8",
        "waveshare-esp32-s3-lcd-147b",
        "esp32-c3-4mb",
        "rpi-pico2-w",
      ]);
      expect(screen.getByRole("main")).toHaveTextContent(
        /ESP Web Tools.*Web Serial.*Pico 2 W.*BOOTSEL.*UF2/i,
      );
      expect(
        screen.queryByText(/ESP32-C3.*unavailable/i),
      ).not.toBeInTheDocument();

      const boardSection = screen
        .getByRole("heading", {
          name: "Waveshare ESP32-S3-LCD-1.47B",
        })
        .closest("section");
      expect(boardSection).toBeDefined();
      expect(boardSection?.parentElement).toHaveClass("flash-explainer");
      expect(boardSection?.parentElement?.firstElementChild).toBe(boardSection);
      expect(boardSection).toHaveTextContent(/Exact-board reference/i);
      expect(boardSection).toHaveTextContent(/real PyBLE board.*not a render/i);
      expect(boardSection).toHaveTextContent(
        /historical identification reference/i,
      );
      expect(boardSection).toHaveTextContent(
        /does not qualify.*local v0\.6\.0.*firmware bytes/i,
      );
      expect(boardSection).not.toHaveTextContent(/Validated display board/i);
      const boardPhoto = screen.getByRole("img", {
        name: "Actual Waveshare ESP32-S3-LCD-1.47B displaying the PyBLE v0.5.0 boot splash and app QR",
      });
      expect(boardSection).toContainElement(boardPhoto);
      expect(boardPhoto).toHaveAttribute(
        "src",
        "/boards/esp32-s3-lcd-1.47b-pyble-v0.5.0.jpg",
      );
      expect(boardPhoto).toHaveAttribute("loading", "eager");
      expect(boardPhoto).toHaveAttribute("fetchpriority", "high");
      expect(boardPhoto.closest("figure")).toHaveTextContent(
        /Actual board.*PyBLE firmware v0\.5\.0/i,
      );
    } finally {
      previewSelection.mockRestore();
    }
  });

  it("describes the staged five-profile candidate accurately with pending-qualification framing", async () => {
    await withSelectedRelease(fiveProfileV060Release("candidate"), () => {
      render(<FlashPage />);

      expectFiveProfileFlashPageCopy();

      // Candidate mode alone carries the visibly pending candidate framing.
      expect(
        screen.getByText(/access-controlled.*release candidate/i),
      ).toBeInTheDocument();
      const methods = screen
        .getByRole("heading", { name: /two provisioning methods/i })
        .closest("section");
      expect(methods).toHaveTextContent(/visibly pending candidate/i);
      expect(methods).toHaveTextContent(/hardware qualification.*pending/i);

      // The real-hardware photo stays, but the spotlight eyebrow must not
      // claim a validated board while qualification is pending.
      const spotlight = screen
        .getByRole("heading", { name: "Waveshare ESP32-S3-LCD-1.47B" })
        .closest("section");
      expect(spotlight).toHaveTextContent(/hardware qualification pending/i);
      expect(spotlight).not.toHaveTextContent(/Validated display board/i);
    });
  });

  it("covers all five targets in the qualified v0.6.0 release copy", async () => {
    await withSelectedRelease(fiveProfileV060Release("public"), () => {
      render(<FlashPage />);

      expect(
        screen.getByText(
          /qualified v0\.6\.0 firmware is available for all five exact release profiles/i,
        ),
      ).toBeInTheDocument();

      expectFiveProfileFlashPageCopy();

      // Qualified-public mode never claims a pending candidate.
      const methods = screen
        .getByRole("heading", { name: /two provisioning methods/i })
        .closest("section");
      expect(methods).not.toHaveTextContent(/visibly pending candidate/i);

      // Once qualified, the spotlight keeps its validated framing.
      const spotlight = screen
        .getByRole("heading", { name: "Waveshare ESP32-S3-LCD-1.47B" })
        .closest("section");
      expect(spotlight).toHaveTextContent(/Validated display board/i);
      expect(spotlight).not.toHaveTextContent(/qualification pending/i);
    });
  });

  it("keeps the historical public beta available without a current exact-board claim", async () => {
    const selectionRoot = await mkdtemp(
      join(tmpdir(), "pyble-flash-qualified-selection-"),
    );
    const selectionFile = join(selectionRoot, "selection.json");
    const previousSelection = process.env.PYBLE_FLASH_SELECTION_FILE;
    process.env.PYBLE_FLASH_SELECTION_FILE = selectionFile;

    try {
      await writeFile(
        selectionFile,
        JSON.stringify(publicBetaFirmwareRelease),
        "utf8",
      );
      render(<FlashPage />);

      expect(
        screen.getByText(
          /current v0\.4\.2 installer.*hardware-tested firmware beta/i,
        ),
      ).toBeInTheDocument();
      expect(
        screen.queryByText(/all three exact current release profiles/i),
      ).toBeNull();
      expect(screen.queryByText(/ESP32-S3-LCD-1\.47B/i)).toBeNull();
      expect(
        screen.queryByRole("img", {
          name: /actual waveshare esp32-s3-lcd-1\.47b/i,
        }),
      ).toBeNull();
    } finally {
      if (previousSelection === undefined) {
        delete process.env.PYBLE_FLASH_SELECTION_FILE;
      } else {
        process.env.PYBLE_FLASH_SELECTION_FILE = previousSelection;
      }
      await rm(selectionRoot, { recursive: true, force: true });
    }
  });

  it("defines the future qualified v0.5.1 Waveshare presentation without claiming it is current", async () => {
    const selectionRoot = await mkdtemp(
      join(tmpdir(), "pyble-flash-waveshare-selection-"),
    );
    const selectionFile = join(selectionRoot, "selection.json");
    const previousSelection = process.env.PYBLE_FLASH_SELECTION_FILE;
    process.env.PYBLE_FLASH_SELECTION_FILE = selectionFile;

    try {
      await writeFile(
        selectionFile,
        JSON.stringify(hypotheticalQualifiedReleaseAtVersion("0.5.1")),
        "utf8",
      );
      render(<FlashPage />);

      expect(
        screen.getByText(
          /qualified v0\.5\.1 firmware is available for all three exact release profiles/i,
        ),
      ).toBeInTheDocument();

      const profileSection = screen
        .getByRole("heading", { name: /choose the exact module profile/i })
        .closest("section");
      expect(profileSection).toBeDefined();
      const genericProfile = within(profileSection as HTMLElement)
        .getByText("esp32-s3-n16r8")
        .closest("li");
      expect(genericProfile).toHaveTextContent(/lean.*board-neutral/i);
      expect(genericProfile).toHaveTextContent(
        /does not bundle.*pyble_st7789.*pyble_waveshare_lcd147b.*splash/i,
      );
      expect(genericProfile).not.toHaveTextContent(
        /validated Waveshare ESP32-S3-LCD-1\.47B/i,
      );

      const exactProfile = within(profileSection as HTMLElement)
        .getByText("waveshare-esp32-s3-lcd-147b")
        .closest("li");
      expect(exactProfile).toBeDefined();
      expect(exactProfile).toHaveTextContent(
        /exact ESP32-S3-LCD-1\.47B B version/i,
      );
      expect(exactProfile).toHaveTextContent(
        /16 MiB flash.*8 MiB Octal PSRAM/i,
      );

      const boardSection = screen
        .getByRole("heading", {
          name: "Waveshare ESP32-S3-LCD-1.47B",
        })
        .closest("section");
      expect(boardSection).toBeDefined();
      expect(boardSection?.parentElement).toHaveClass("flash-explainer");
      expect(boardSection?.parentElement?.firstElementChild).toBe(boardSection);
      expect(boardSection).toHaveTextContent(
        /PyBLE on real hardware.*not a render/i,
      );
      expect(boardSection).toHaveTextContent(
        /separate.*waveshare-esp32-s3-lcd-147b.*image/i,
      );
      expect(boardSection).toHaveTextContent(
        /lean.*esp32-s3-n16r8.*does not bundle/i,
      );
      expect(boardSection).toHaveTextContent(
        /16 MiB flash.*8 MiB Octal PSRAM/i,
      );
      expect(boardSection).toHaveTextContent(/172.*320.*ST7789V3/i);
      expect(boardSection).toHaveTextContent(/pyble_st7789/i);
      expect(boardSection).toHaveTextContent(/pyble_waveshare_lcd147b/i);
      expect(boardSection).toHaveTextContent(/Blockly TFT programs/);
      expect(boardSection).not.toHaveTextContent(/Blocky TFT/);
      expect(boardSection).toHaveTextContent(
        /fresh erased installation.*boot splash.*shown by default.*persistently disable/i,
      );
      expect(boardSection).toHaveTextContent(/B version/i);
      expect(boardSection).toHaveTextContent(/non-B.*wiring differs/i);
      expect(boardSection).toHaveTextContent(
        /select.*waveshare-esp32-s3-lcd-147b/i,
      );
      const boardPhoto = screen.getByRole("img", {
        name: "Actual Waveshare ESP32-S3-LCD-1.47B displaying the PyBLE v0.5.0 boot splash and app QR",
      });
      expect(boardSection).toContainElement(boardPhoto);
      expect(boardPhoto).toHaveAttribute(
        "src",
        "/boards/esp32-s3-lcd-1.47b-pyble-v0.5.0.jpg",
      );
      expect(boardPhoto).toHaveAttribute("loading", "eager");
      expect(boardPhoto).toHaveAttribute("fetchpriority", "high");
      expect(boardPhoto.closest("figure")).toHaveTextContent(
        /Actual board.*PyBLE firmware v0\.5\.0/i,
      );
      expect(
        screen.getAllByText(/ESP32-S3-LCD-1\.47B/i).length,
      ).toBeGreaterThan(1);
      expect(
        screen.getByText(
          (_content, element) =>
            element?.tagName === "CODE" &&
            element.textContent?.replace(/\s+/g, " ").trim() ===
              "python -m esptool --chip esp32s3 write_flash 0x0 waveshare-esp32-s3-lcd-147b/firmware.bin",
        ),
      ).toBeInTheDocument();
    } finally {
      if (previousSelection === undefined) {
        delete process.env.PYBLE_FLASH_SELECTION_FILE;
      } else {
        process.env.PYBLE_FLASH_SELECTION_FILE = previousSelection;
      }
      await rm(selectionRoot, { recursive: true, force: true });
    }
  });
});

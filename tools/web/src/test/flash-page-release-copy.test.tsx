// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import FlashPage from "@/app/flash/page";
import type { FirmwareReleaseDescriptor } from "@/lib/firmware-release";
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

function localPreviewArtifact(
  path: string,
  digestCharacter: string,
  size = 1_024,
) {
  return { path, size, sha256: digestCharacter.repeat(64) };
}

function localFiveBoardPreview() {
  const root = "/.pyble-preview-firmware";
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
        label: "Classical ESP32 · 4 MiB",
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
        label: "ESP32-S3 N16R8 · lean generic",
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
        label: "Waveshare ESP32-S3-LCD-1.47B · exact B version",
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
        label: "ESP32-C3 · 4 MiB",
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
    const previewRoot = await mkdtemp(
      join(tmpdir(), "pyble-flash-local-preview-"),
    );
    const previewFile = join(previewRoot, "preview.json");
    const mutableEnvironment = process.env as Record<
      string,
      string | undefined
    >;
    const previousPreview = process.env.PYBLE_LOCAL_FLASH_PREVIEW_FILE;
    const previousPreviewFlag = process.env.PYBLE_LOCAL_FLASH_PREVIEW;
    const previousSelection = process.env.PYBLE_FLASH_SELECTION_FILE;
    const previousNodeEnvironment = process.env.NODE_ENV;
    process.env.PYBLE_LOCAL_FLASH_PREVIEW = "1";
    process.env.PYBLE_LOCAL_FLASH_PREVIEW_FILE = previewFile;
    mutableEnvironment.NODE_ENV = "development";
    delete process.env.PYBLE_FLASH_SELECTION_FILE;

    try {
      await writeFile(
        previewFile,
        JSON.stringify(localFiveBoardPreview()),
        "utf8",
      );
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
    } finally {
      if (previousPreview === undefined) {
        delete process.env.PYBLE_LOCAL_FLASH_PREVIEW_FILE;
      } else {
        process.env.PYBLE_LOCAL_FLASH_PREVIEW_FILE = previousPreview;
      }
      if (previousPreviewFlag === undefined) {
        delete process.env.PYBLE_LOCAL_FLASH_PREVIEW;
      } else {
        process.env.PYBLE_LOCAL_FLASH_PREVIEW = previousPreviewFlag;
      }
      if (previousSelection === undefined) {
        delete process.env.PYBLE_FLASH_SELECTION_FILE;
      } else {
        process.env.PYBLE_FLASH_SELECTION_FILE = previousSelection;
      }
      if (previousNodeEnvironment === undefined) {
        delete mutableEnvironment.NODE_ENV;
      } else {
        mutableEnvironment.NODE_ENV = previousNodeEnvironment;
      }
      await rm(previewRoot, { recursive: true, force: true });
    }
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

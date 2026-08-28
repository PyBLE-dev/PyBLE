// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

import type { ComponentType } from "react";

import { cleanup, render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import BlocksTutorial from "@/app/learn/blocks/page";
import ConfiguredHardwareTutorial from "@/app/learn/configured-hardware/page";
import ExamplesTutorial from "@/app/learn/examples/page";
import FilesTutorial from "@/app/learn/files/page";
import FirstProgramTutorial from "@/app/learn/first-program/page";
import GitHubImportTutorial from "@/app/learn/github-import/page";
import HardwareTutorial from "@/app/learn/hardware/page";
import Pico2WTutorial from "@/app/learn/pico-2-w/page";
import SetupTutorial from "@/app/learn/setup/page";
import WaveshareTutorial from "@/app/learn/waveshare-lcd-147b/page";
import { tutorialBoardIdentities } from "@/components/tutorial-board-identity-gallery";
import {
  compatibilityLabels,
  examplesSnapshot,
  firmwareProfiles,
  tutorials,
} from "@/lib/tutorials";

const examplesCommit = "8f4529b3cd0d62e8d53d7deb4f37e5cd2a171fd1";

const profileOrder = [
  "esp32-4mb",
  "esp32-s3-n16r8",
  "waveshare-esp32-s3-lcd-147b",
  "esp32-c3-4mb",
  "rpi-pico2-w",
] as const;

const expectedTutorials = [
  ["setup", "/learn/setup", "Setup"],
  ["first-program", "/learn/first-program", "First program"],
  ["files", "/learn/files", "Files"],
  ["github-import", "/learn/github-import", "GitHub import"],
  ["blocks", "/learn/blocks", "Blocks"],
  ["examples", "/learn/examples", "Examples catalog"],
  ["hardware", "/learn/hardware", "Hardware safety"],
  ["configured-hardware", "/learn/configured-hardware", "Configured hardware"],
  ["pico-2-w", "/learn/pico-2-w", "Pico 2 W"],
  ["waveshare-lcd-147b", "/learn/waveshare-lcd-147b", "Waveshare LCD 1.47B"],
] as const;

const expectedExampleIds = [
  "portable-hello-console",
  "portable-paced-counter",
  "portable-runtime-info",
  "portable-file-round-trip",
  "gpio-blink-external-led",
  "neopixel-single-pixel",
  "pico2w-onboard-led",
  "waveshare-lcd147b-hello",
  "portable-data-decisions",
  "portable-reusable-functions",
  "portable-error-handling",
  "portable-console-input",
  "portable-json-data",
  "portable-async-cooperation",
  "portable-binary-data",
  "workflow-stop-a-program",
  "workflow-expected-error",
  "filesystem-list-directory",
  "gpio-read-external-button",
  "gpio-button-controls-led",
  "gpio-pwm-fade",
  "gpio-adc-sampling",
  "bus-i2c-scan",
  "bus-spi-loopback",
  "neopixel-strip-chase",
  "pico2w-onboard-led-patterns",
  "waveshare-lcd147b-shapes",
  "waveshare-lcd147b-onboard-pixel",
  "project-button-press-counter",
  "project-adc-data-logger",
  "project-button-neopixel",
  "project-waveshare-lcd147b-dashboard",
] as const;

const lessonPages: Array<{
  Page: ComponentType;
  href: string;
  position: number;
  title: string;
}> = [
  {
    Page: SetupTutorial,
    href: "/learn/setup",
    position: 1,
    title: "Setup",
  },
  {
    Page: FirstProgramTutorial,
    href: "/learn/first-program",
    position: 2,
    title: "First program",
  },
  { Page: FilesTutorial, href: "/learn/files", position: 3, title: "Files" },
  {
    Page: GitHubImportTutorial,
    href: "/learn/github-import",
    position: 4,
    title: "GitHub import",
  },
  {
    Page: BlocksTutorial,
    href: "/learn/blocks",
    position: 5,
    title: "Blocks",
  },
  {
    Page: ExamplesTutorial,
    href: "/learn/examples",
    position: 6,
    title: "Examples catalog",
  },
  {
    Page: HardwareTutorial,
    href: "/learn/hardware",
    position: 7,
    title: "Hardware safety",
  },
  {
    Page: ConfiguredHardwareTutorial,
    href: "/learn/configured-hardware",
    position: 8,
    title: "Configured hardware",
  },
  {
    Page: Pico2WTutorial,
    href: "/learn/pico-2-w",
    position: 9,
    title: "Pico 2 W",
  },
  {
    Page: WaveshareTutorial,
    href: "/learn/waveshare-lcd-147b",
    position: 10,
    title: "Waveshare LCD 1.47B",
  },
];

const physicalTabletLessonPages = lessonPages;

function mainText(Page: ComponentType): string {
  cleanup();
  render(<Page />);
  return screen.getByRole("main").textContent ?? "";
}

describe("learning catalog contract", () => {
  it("keeps the ten lessons in the specified beginner progression", () => {
    expect(
      tutorials.map(({ slug, href, title }) => [slug, href, title]),
    ).toEqual(expectedTutorials);
    expect(tutorials.map(({ position }) => position)).toEqual([
      1, 2, 3, 4, 5, 6, 7, 8, 9, 10,
    ]);

    for (const tutorial of tutorials) {
      expect(tutorial.difficulty).toBeTruthy();
      expect(tutorial.minutes).toBeGreaterThan(0);
      expect(tutorial.prerequisites.length).toBeGreaterThan(0);
      expect(tutorial.outcomes.length).toBeGreaterThan(0);
    }
  });

  it("keeps compatibility language precise and the five profiles ordered", () => {
    expect(compatibilityLabels).toEqual({
      qualifiedFirmware: "Qualified firmware",
      designed: "Designed for this profile",
      exactBoardOnly: "Exact board only",
      developmentUnvalidated:
        "Development example — physical validation not recorded",
      notApplicable: "Not applicable",
    });
    expect(firmwareProfiles.map(({ id }) => id)).toEqual(profileOrder);
    expect(firmwareProfiles.map(({ scope }) => scope)).toEqual([
      "generic-profile",
      "generic-profile",
      "exact-board",
      "generic-profile",
      "exact-board",
    ]);
  });

  it("publishes the complete development snapshot without inventing evidence", () => {
    expect(examplesSnapshot).toMatchObject({
      repositoryUrl: "https://github.com/PyBLE-dev/examples",
      commit: examplesCommit,
      status: "development",
      releaseTag: null,
      firmwareBaseline: "0.6.0",
      protocol: "PBLE/1",
    });
    expect(examplesSnapshot.examples).toHaveLength(32);
    expect(examplesSnapshot.examples.map(({ id }) => id)).toEqual(
      expectedExampleIds,
    );
    expect(
      Object.fromEntries(
        ["0.1.0", "0.2.0", "0.3.0"].map((release) => [
          release,
          examplesSnapshot.examples.filter(
            ({ plannedRelease }) => plannedRelease === release,
          ).length,
        ]),
      ),
    ).toEqual({ "0.1.0": 8, "0.2.0": 17, "0.3.0": 7 });

    for (const example of examplesSnapshot.examples) {
      expect(example.validationStatus).toBe("planned");
      expect(example.validatedProfiles).toEqual([]);
      expect(example.designedProfiles.length).toBeGreaterThan(0);
      expect(example.sourceUrl).toBe(
        `https://github.com/PyBLE-dev/examples/blob/${examplesCommit}/${example.path}/${example.entrypoint}`,
      );
      expect(example.sourceUrl).not.toContain("/blob/main/");
    }
  });

  it("does not blur generic, ESP NeoPixel, or exact-board boundaries", () => {
    const exactBoardExamples = examplesSnapshot.examples.filter(
      ({ classification }) => classification === "exact-hardware",
    );
    expect(exactBoardExamples).toHaveLength(6);
    expect(
      exactBoardExamples.every(
        ({ designedProfiles }) =>
          designedProfiles.length === 1 &&
          ["waveshare-esp32-s3-lcd-147b", "rpi-pico2-w"].includes(
            designedProfiles[0] ?? "",
          ),
      ),
    ).toBe(true);

    const fourEspExamples = examplesSnapshot.examples.filter(
      ({ designedProfiles }) => designedProfiles.length === 4,
    );
    expect(fourEspExamples.map(({ id }) => id)).toEqual([
      "neopixel-single-pixel",
      "neopixel-strip-chase",
      "project-button-neopixel",
    ]);
    for (const example of fourEspExamples) {
      expect(example.designedProfiles).toEqual(profileOrder.slice(0, 4));
      expect(example.designedProfiles).not.toContain("rpi-pico2-w");
    }
  });
});

describe("shared tutorial structure", () => {
  it.each(lessonPages)(
    "$href has usable static lesson structure",
    ({ Page, position, title }) => {
      render(<Page />);
      const main = screen.getByRole("main");

      expect(
        within(main).getByRole("heading", { level: 1, name: title }),
      ).toBeVisible();
      expect(main).toHaveTextContent(`Tutorial ${position} of 10`);
      expect(main).toHaveTextContent(/Difficulty/i);
      expect(main).toHaveTextContent(/\d+ min/i);
      expect(
        within(main).getByRole("heading", { name: /Prerequisites/i }),
      ).toBeVisible();
      expect(
        within(main).getByRole("heading", { name: /Outcomes/i }),
      ).toBeVisible();

      const steps = within(main).getByRole("list", { name: /Tutorial steps/i });
      const numberedSteps = within(steps).getAllByRole("listitem");
      expect(steps.tagName).toBe("OL");
      expect(numberedSteps.length).toBeGreaterThan(0);
      for (const step of numberedSteps) {
        expect(step).toHaveTextContent(/Expected:|Stop if:/i);
      }

      expect(
        within(main).getByRole("link", { name: /current firmware|flash/i }),
      ).toHaveAttribute("href", "/flash");
      expect(
        within(main).getByRole("link", { name: /support|recovery/i }),
      ).toHaveAttribute("href", "/support");

      const progress = within(main).getByRole("navigation", {
        name: /Tutorial navigation/i,
      });
      expect(
        within(progress).getByRole("link", { name: /all tutorials/i }),
      ).toHaveAttribute("href", "/learn");
      if (position > 1) {
        expect(
          within(progress).getByRole("link", { name: /previous/i }),
        ).toHaveAttribute("href", lessonPages[position - 2]?.href);
      }
      if (position < lessonPages.length) {
        expect(
          within(progress).getByRole("link", { name: /next/i }),
        ).toHaveAttribute("href", lessonPages[position]?.href);
      }
    },
  );
});

describe("instructional visual contract", () => {
  it.each(lessonPages)(
    "$href includes a purposeful, accessible visual",
    ({ Page }) => {
      render(<Page />);
      const main = screen.getByRole("main");
      const figures = [...main.querySelectorAll("figure")];

      expect(figures.length).toBeGreaterThan(0);
      for (const figure of figures) {
        expect(figure.querySelector("figcaption")).not.toBeNull();
        const images = [...figure.querySelectorAll("img")];
        for (const image of images) {
          expect(image).toHaveAttribute("alt");
          expect(image.getAttribute("alt")?.trim().length).toBeGreaterThan(20);
          expect(Number(image.getAttribute("width"))).toBeGreaterThan(0);
          expect(Number(image.getAttribute("height"))).toBeGreaterThan(0);
          expect(image).toHaveAttribute("loading", "lazy");
        }
      }
    },
  );

  it.each(physicalTabletLessonPages)(
    "$href includes truthful physical Lenovo app evidence",
    ({ Page }) => {
      render(<Page />);
      const main = screen.getByRole("main");
      const physicalFigures = [...main.querySelectorAll("figure")].filter(
        (figure) =>
          figure
            .querySelector("figcaption")
            ?.textContent?.includes("Actual Android tablet · Lenovo TB-J616X"),
      );

      expect(physicalFigures.length).toBeGreaterThan(0);
      for (const figure of physicalFigures) {
        const images = within(figure).getAllByRole("img");
        expect(images.length).toBeGreaterThan(0);
        for (const image of images) {
          expect(image.getAttribute("src")).toMatch(
            /^\/learn\/app\/[a-z0-9.-]+\.png$/,
          );
          expect(image.getAttribute("alt")).toMatch(/PyBLE 0\.2\.0 beta/i);
        }
        expect(figure).not.toHaveTextContent(/integration test|debug|golden/i);
      }
      expect(main).not.toHaveTextContent(/PyBLE Integration Test/i);
    },
  );

  it.each([SetupTutorial, HardwareTutorial])(
    "renders the complete five-board observed identity set",
    (Page) => {
      render(<Page />);
      const main = screen.getByRole("main");
      const text = main.textContent ?? "";

      for (const [boardId, runtimeChip] of [
        ["5646", "esp32-s3"],
        ["8C9E", "esp32"],
        ["C81A", "esp32-c3"],
        ["DA86", "esp32-s3"],
        ["3DCB", "rpi-pico2-w"],
      ] as const) {
        expect(text).toContain(boardId);
        expect(text).toContain(runtimeChip);
      }
    },
  );

  it("keeps 5646 associated with the generic ESP32-S3 session", () => {
    expect(tutorialBoardIdentities.genericS3).toMatchObject({
      boardId: "5646",
      context: "Generic ESP32-S3 · N16R8",
      runtimeChip: "esp32-s3",
    });
    expect(tutorialBoardIdentities.waveshareLcd147b).toMatchObject({
      boardId: "DA86",
      context: "Waveshare ESP32-S3-LCD-1.47B",
      runtimeChip: "esp32-s3",
    });
  });

  it("uses identity subsets as hardware boundaries, not profile proof", () => {
    const configuredText = mainText(ConfiguredHardwareTutorial);
    expect(configuredText).toMatch(/C81A.*esp32-c3/is);

    const picoText = mainText(Pico2WTutorial);
    expect(picoText).toMatch(/3DCB.*rpi-pico2-w/is);

    const waveshareText = mainText(WaveshareTutorial);
    expect(waveshareText).toMatch(/5646.*DA86/is);
    expect(waveshareText).toMatch(
      /esp32-s3.*(?:cannot|does not).*distinguish.*profile/is,
    );
  });
});

describe("tutorial truth and safety content", () => {
  it("teaches exact provisioning boundaries before BLE use", () => {
    const text = mainText(SetupTutorial);

    expect(text).toMatch(/backup.*flash.*erase/is);
    expect(text).toMatch(/ESP32.*4 MiB.*Web Serial/is);
    expect(text).toMatch(/ESP32-S3.*N16R8.*Web Serial/is);
    expect(text).toMatch(/Waveshare.*1\.47B.*B-version.*Web Serial/is);
    expect(text).toMatch(/ESP32-C3.*revision (?:v)?0\.3\+.*4 MiB/is);
    expect(text).toMatch(/Pico 2 W.*UF2.*BOOTSEL/is);
    expect(text).toMatch(/iPad.*cannot.*wired.*provision/is);
    expect(text).toMatch(/PyBLE-.*scan.*connect/is);
    expect(text).toMatch(/verify.*board.*firmware.*chip.*MicroPython/is);
  });

  it("teaches the first program as an explicit, hardware-free workflow", () => {
    const text = mainText(FirstProgramTutorial);

    expect(text).toContain('print("Hello from PyBLE!")');
    expect(text).toMatch(/hardware-free/i);
    expect(text).toMatch(/In Files.*New file.*hello\.py.*open.*Editor/is);
    expect(text).not.toMatch(/New file in the Editor.*name.*hello\.py/is);
    expect(text).toMatch(/hello\.py.*Save.*Run.*Console/is);
    expect(text).toMatch(/Stop.*soft reboot.*reconnect/is);
  });

  it("warns that Files deletion is bounded, permanent, and non-atomic", () => {
    const text = mainText(FilesTutorial);

    expect(text).toContain("/examples");
    expect(text).toMatch(/visible.*direct.*regular files/is);
    expect(text).toMatch(/folders.*excluded|does not.*folders/is);
    expect(text).toMatch(/no recursive|not recursive/is);
    expect(text).toMatch(/permanent.*no trash.*no rollback/is);
    expect(text).toMatch(/sequential.*fail-fast.*not atomic/is);
    expect(text).toMatch(/board root.*boot\.py.*_boot\.py/is);
    expect(text).toMatch(/board root.*pyble.*pble.*\.pbltmp/is);
  });

  it("teaches reproducible public GitHub import without elevated trust", () => {
    const text = mainText(GitHubImportTutorial);

    expect(text).toContain("https://github.com/PyBLE-dev/examples");
    expect(text).toContain(examplesCommit);
    expect(text).toContain("examples/portable/basics/hello_console");
    expect(text).toContain("/examples/pyble_hello_console.py");
    expect(text).toMatch(/editable.*repository URL/is);
    expect(text).toMatch(/branch.*only branches/is);
    expect(text).toMatch(/main.*branch discovery/is);
    expect(text).toMatch(/Use a tag or commit.*40-character commit/is);
    expect(text).not.toMatch(/Open Advanced/i);
    expect(text).toMatch(/public.*no.*account.*token/is);
    expect(text).toMatch(/rate limit/is);
    expect(text).toMatch(/lowercase \.py.*direct.*one folder/is);
    expect(text).toMatch(/flattened.*current.*directory/is);
    expect(text).toMatch(/create.*destination.*before.*import/is);
    expect(text).toMatch(/sequential.*not.*atomic/is);
    expect(text).toMatch(/does not automatically.*open.*run/is);
    expect(text).toMatch(/official.*does not.*trusted|no elevated trust/is);
    expect(text).toMatch(/blob URL.*not.*repository URL/is);
  });

  it("keeps Blocks generation explicit and exact-board starters bounded", () => {
    const text = mainText(BlocksTutorial);

    for (const starter of [
      "Hello PyBLE",
      "Count repeatedly",
      "Blink LED",
      "Blink NeoPixel",
      "Read button",
      "Button controls LED",
      "Reusable function",
      "ESP32-S3-LCD-1.47B TFT pattern",
    ]) {
      expect(text).toContain(starter);
    }
    expect(text).toMatch(/Preview.*Generated Python.*Create copy/is);
    expect(text).toMatch(/Save.*Run.*explicit/is);
    expect(text).toMatch(/sidecar/is);
    expect(text).toMatch(/Python-to-Blocks.*all-or-nothing/is);
    expect(text).toMatch(/NeoPixel.*four ESP.*not.*Pico/is);
    expect(text).toMatch(/TFT.*exact.*B-version.*not.*lean.*S3/is);
  });

  it("shows every example with an immutable, unvalidated development label", () => {
    const text = mainText(ExamplesTutorial);

    expect(text).toContain(
      "Development example — physical validation not recorded",
    );
    expect(text).toMatch(/development-only.*unreleased.*not HIL-validated/is);
    expect(text).not.toMatch(/examples-v\d/);
    for (const example of examplesSnapshot.examples) {
      expect(text).toContain(example.title);
      expect(text).toContain(example.plannedRelease);
    }
  });

  it("requires electrical review instead of supplying generic pin defaults", () => {
    const text = mainText(HardwareTutorial);

    expect(text).toMatch(/generic.*no.*pin map|no.*generic.*pin assumption/is);
    expect(text).toMatch(/exact carrier.*documentation/is);
    expect(text).toMatch(/voltage.*current/is);
    expect(text).toMatch(/boot.*strapping/is);
    expect(text).toMatch(/shared ground/is);
    expect(text).toMatch(/resistor|protection/is);
    expect(text).toMatch(/bounded.*effect.*Stop.*cleanup/is);
    expect(text).toMatch(/two S3.*same.*esp32-s3.*not.*infer/is);
  });

  it("keeps configured hardware pins explicit and cleanup visible", () => {
    const text = mainText(ConfiguredHardwareTutorial);

    for (const capability of ["GPIO", "ADC", "PWM", "I2C", "SPI", "NeoPixel"]) {
      expect(text).toContain(capability);
    }
    expect(text).toMatch(/set|configure/i);
    expect(text).toMatch(/pin.*exact.*board.*documentation/is);
    expect(text).toMatch(/no default pins|does not choose.*pin/is);
    expect(text).toMatch(/bounded.*cleanup/is);
  });

  it("keeps the Pico lesson on its exact named LED surface", () => {
    const text = mainText(Pico2WTutorial);

    expect(text).toContain('Pin("LED")');
    expect(text).toMatch(/exact.*Raspberry Pi Pico 2 W/is);
    expect(text).toMatch(/does not.*NeoPixel|no NeoPixel/is);
    expect(text).toMatch(/UF2.*BOOTSEL/is);
  });

  it("keeps display and onboard-pixel claims on the exact Waveshare B image", () => {
    const text = mainText(WaveshareTutorial);

    expect(text).toMatch(/exact.*Waveshare ESP32-S3-LCD-1\.47B.*B-version/is);
    expect(text).toContain("pyble_st7789");
    expect(text).toContain("pyble_waveshare_lcd147b");
    expect(text).toMatch(/fixed.*display wiring/is);
    expect(text).toMatch(/onboard.*pixel.*GPIO38/is);
    expect(text).toMatch(/lean.*ESP32-S3.*does not|not.*lean.*ESP32-S3/is);
  });
});

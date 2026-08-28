// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

import { TutorialCallout } from "@/components/tutorial-callout";
import { TutorialPage, type TutorialStep } from "@/components/tutorial-page";
import { examplesSnapshot } from "@/lib/tutorials";
import { pageMetadata } from "@/lib/site";

export const metadata = pageMetadata({
  title: "Waveshare LCD 1.47B tutorial",
  description:
    "Use the exact Waveshare ESP32-S3-LCD-1.47B B-version firmware, fixed ST7789 display wiring, bounded frames, and GPIO38 onboard pixel.",
  path: "/learn/waveshare-lcd-147b",
});

const waveshareExamples = examplesSnapshot.examples.filter(
  (example) =>
    example.designedProfiles.length === 1 &&
    example.designedProfiles[0] === "waveshare-esp32-s3-lcd-147b",
);

const steps: readonly TutorialStep[] = [
  {
    title: "Verify the complete B-version identity",
    body: (
      <p>
        Read the physical product marking and confirm the exact Waveshare
        ESP32-S3-LCD-1.47B B-version with 16 MiB flash and 8 MiB Octal PSRAM.
        Confirm your own installer record names
        <code> waveshare-esp32-s3-lcd-147b</code>, then verify board ID, agent
        firmware, chip, and MicroPython are consistent. DeviceInfo does not
        report the provisioning profile, and ESP32-S3 identity cannot
        distinguish this exact carrier from the lean generic S3 target.
      </p>
    ),
    stopIf:
      "the label omits the B suffix, the memory topology or installer record differs, or any reported identity field is inconsistent with the recorded installation.",
  },
  {
    title: "Confirm the exact runtime before touching display pins",
    body: (
      <p>
        The exact image bundles <code>pyble_st7789</code> and the named
        <code> pyble_waveshare_lcd147b</code> companion. The example checks the
        companion before configuring GPIO. An import failure is an identity or
        firmware problem, not a reason to paste the modules onto another image.
      </p>
    ),
    expected:
      "the exact profile exposes both modules before the reviewed example performs any display setup.",
  },
  {
    title: "Review the fixed display wiring",
    body: (
      <p>
        The built-in panel uses fixed display wiring: SPI1 at 40 MHz with SCLK
        GPIO40, MOSI GPIO45, CS GPIO42, D/C GPIO41, reset GPIO39, and
        active-high backlight GPIO46. Its visible ST7789V3 surface is 172 × 320
        with X offset 34. Do not edit these GPIO values or connect external
        hardware to them.
      </p>
    ),
    stopIf:
      "your schematic, exact board label, or selected firmware disagrees with any fixed role.",
  },
  {
    title: "Import and inspect Waveshare LCD Hello",
    body: (
      <p>
        Pin the examples repository to the reviewed commit, browse the exact
        Waveshare LCD Hello folder, and import its Python file into a disposable
        child directory. Read the exact-board guard, fixed setup, hold-time
        bound, draw function, and cleanup before Run.
      </p>
    ),
    expected:
      "the imported file remains closed until you open it and the review shows a finite three-second frame with backlight-off cleanup.",
  },
  {
    title: "Run one bounded display frame",
    body: (
      <p>
        Verify identity again, choose Run explicitly, and watch both display and
        Console. The backlight should turn on only after the frame is ready. At
        completion or Stop, the example turns the backlight off and
        deinitializes the display.
      </p>
    ),
    expected:
      "a bounded PyBLE hello frame appears on the exact panel, then the backlight turns off and display resources are released.",
  },
  {
    title: "Change one safe visual value",
    body: (
      <p>
        Try the documented hold-time change or alter one word or color inside
        the draw function. Do not change fixed GPIO, geometry, offset, SPI mode,
        or cleanup. Save and Run explicitly, then confirm the screen finishes
        dark.
      </p>
    ),
    stopIf:
      "the edit changes fixed board setup, removes duration validation, retains the framebuffer, or leaves the backlight on.",
  },
  {
    title: "Treat the onboard pixel as a separate exact surface",
    body: (
      <p>
        The board&apos;s onboard WS2812-compatible pixel uses GPIO38; the
        display runtime does not initialize it. Review the Onboard Pixel
        example, verify its exact-board confirmation remains required, keep each
        channel dim and its sequence finite, then ensure cleanup writes off and
        leaves GPIO38 low.
      </p>
    ),
    expected:
      "the onboard pixel shows only the bounded dim sequence and finishes off without changing display wiring.",
  },
];

export default function WaveshareTutorial() {
  return (
    <TutorialPage
      slug="waveshare-lcd-147b"
      steps={steps}
      compatibility={{
        "esp32-4mb": "notApplicable",
        "esp32-s3-n16r8": "notApplicable",
        "waveshare-esp32-s3-lcd-147b": "exactBoardOnly",
        "esp32-c3-4mb": "notApplicable",
        "rpi-pico2-w": "notApplicable",
      }}
      compatibilityNote={
        <p>
          This is an exact-board-only lesson. The lean ESP32-S3 N16R8 image does
          not include the display runtime, companion, fixed carrier wiring, or
          onboard-pixel claim.
        </p>
      }
    >
      <section aria-labelledby="waveshare-before">
        <h2 id="waveshare-before">Before you begin</h2>
        <p>
          Remove external wiring, complete Hardware safety, and inspect the
          exact board label and schematic. The non-B LCD-1.47 and other ESP32-S3
          carriers use different wiring; a shared MCU family does not make them
          compatible with this lesson.
        </p>
        <TutorialCallout title="Exact B-version only" tone="warning">
          <p>
            Run display and onboard-pixel code only on the exact Waveshare
            ESP32-S3-LCD-1.47B B-version with its matching exact firmware image.
            It is not for the lean ESP32-S3 profile, the non-B board, or another
            N16R8 carrier.
          </p>
        </TutorialCallout>
      </section>

      <section aria-labelledby="waveshare-source">
        <h2 id="waveshare-source">Exact immutable sources</h2>
        <p>
          These four entries are development-only and not HIL-validated. Their
          immutable source remains in the examples repository.
        </p>
        <div className="tutorial-source-links">
          {waveshareExamples.map((example) => (
            <a
              href={example.sourceUrl}
              target="_blank"
              rel="noopener noreferrer"
              key={example.id}
            >
              {example.title} · planned {example.plannedRelease}
            </a>
          ))}
        </div>
      </section>
    </TutorialPage>
  );
}

// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

import { TutorialCallout } from "@/components/tutorial-callout";
import { TutorialPage, type TutorialStep } from "@/components/tutorial-page";
import { examplesSnapshot } from "@/lib/tutorials";
import { pageMetadata } from "@/lib/site";

export const metadata = pageMetadata({
  title: "Raspberry Pi Pico 2 W tutorial",
  description:
    "Provision the exact Raspberry Pi Pico 2 W UF2 profile and run finite examples on its documented named onboard LED without ESP NeoPixel assumptions.",
  path: "/learn/pico-2-w",
});

const picoExamples = examplesSnapshot.examples.filter(
  (example) =>
    example.designedProfiles.length === 1 &&
    example.designedProfiles[0] === "rpi-pico2-w",
);

const steps: readonly TutorialStep[] = [
  {
    title: "Confirm the exact board and firmware profile",
    body: (
      <p>
        Read the physical board label and confirm it is an exact Raspberry Pi
        Pico 2 W, not Pico W or another RP2350 carrier. Confirm your own
        installer record names <code>rpi-pico2-w</code>, then verify the
        connected board ID, agent firmware, chip, and MicroPython are consistent
        with that board. DeviceInfo does not report the provisioning profile,
        and an RP2350 chip identity cannot distinguish an exact carrier.
      </p>
    ),
    stopIf:
      "the physical product or installer record is uncertain, or any reported identity field is inconsistent with the recorded Pico 2 W installation.",
  },
  {
    title: "Know the recovery path before changing code",
    body: (
      <p>
        Pico 2 W provisioning uses an exact UF2: hold BOOTSEL while connecting
        USB, copy the selected UF2 to the mounted volume, and let the board
        restart. This is different from ESP Web Serial and requires a computer.
      </p>
    ),
    expected:
      "you can identify BOOTSEL and explain where the exact Pico 2 W UF2 comes from before continuing over BLE.",
  },
  {
    title: "Review the named LED surface",
    body: (
      <p>
        The exact-board examples use <code>Pin(&quot;LED&quot;)</code>, the
        documented MicroPython name for the Pico 2 W onboard LED. Do not replace
        it with a numeric GPIO copied from another Pico family board. No
        external wiring is required.
      </p>
    ),
    expected:
      "the source names LED and has a finite duration plus a final off state; it contains no guessed numeric LED pin.",
  },
  {
    title: "Import the finite onboard LED example",
    body: (
      <p>
        In a disposable child folder, pin the examples repository to the
        reviewed commit, browse to the Pico 2 W onboard LED folder, select its
        ordinary Python file, and verify the exact source and board target.
      </p>
    ),
    expected:
      "the terminal import result reports one exact file and Files refreshes without opening or running it.",
  },
  {
    title: "Read, run, and observe the bounded blink",
    body: (
      <p>
        Open the imported source, check the blink count and timing bounds, then
        choose Run explicitly. Keep Console visible and be ready to press Stop.
        The source&apos;s cleanup leaves the LED off after completion or
        interruption.
      </p>
    ),
    expected:
      "the exact onboard LED blinks the documented finite count, Console reports completion, and the LED finishes off.",
  },
  {
    title: "Try only a bounded pattern change",
    body: (
      <p>
        Open the separate Pico 2 W LED Patterns source or reduce the first
        example&apos;s documented count. Keep its total duration within the
        source limits, Save, Run explicitly, then Stop and verify the LED is
        off.
      </p>
    ),
    stopIf:
      "a proposed edit removes validation, cleanup, the finite duration, or the exact named LED surface.",
  },
];

export default function Pico2WTutorial() {
  return (
    <TutorialPage
      slug="pico-2-w"
      steps={steps}
      compatibility={{
        "esp32-4mb": "notApplicable",
        "esp32-s3-n16r8": "notApplicable",
        "waveshare-esp32-s3-lcd-147b": "notApplicable",
        "esp32-c3-4mb": "notApplicable",
        "rpi-pico2-w": "exactBoardOnly",
      }}
      compatibilityNote={
        <p>
          This exact-board lesson is only for Raspberry Pi Pico 2 W. Firmware
          0.6.0 exposes its named onboard LED surface; it does not claim
          NeoPixel support for this profile.
        </p>
      }
    >
      <section aria-labelledby="pico-before">
        <h2 id="pico-before">Before you begin</h2>
        <p>
          Complete Setup and Hardware safety, then remove any external circuit.
          The exact onboard LED needs no wiring, resistor choice, or numeric
          pin. A board with a similar name is outside this lesson.
        </p>
        <TutorialCallout title="Pico is not an ESP profile" tone="warning">
          <p>
            The reviewed examples snapshot has no NeoPixel design claim for Pico
            2 W. Do not carry ESP-only NeoPixel imports, GPIO assumptions, or
            Web Serial instructions into this UF2/BOOTSEL profile.
          </p>
        </TutorialCallout>
      </section>

      <section aria-labelledby="pico-source">
        <h2 id="pico-source">Exact immutable sources</h2>
        <p>
          Both entries below are development-only and not HIL-validated. Read
          each complete file at the reviewed commit before importing it.
        </p>
        <div className="tutorial-source-links">
          {picoExamples.map((example) => (
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

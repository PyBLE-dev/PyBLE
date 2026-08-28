// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

import { TutorialCallout } from "@/components/tutorial-callout";
import { TutorialPage, type TutorialStep } from "@/components/tutorial-page";
import { pageMetadata } from "@/lib/site";

export const metadata = pageMetadata({
  title: "Hardware safety tutorial",
  description:
    "Review exact carrier documentation, electrical limits, pins, protection, bounded effects, Stop behavior, and cleanup before running PyBLE hardware code.",
  path: "/learn/hardware",
});

const steps: readonly TutorialStep[] = [
  {
    title: "Power off and identify every exact part",
    body: (
      <p>
        Disconnect board and peripheral power. Record the full board/carrier
        name and revision, component part number, supply voltage, signal
        voltage, and intended connection. Open the exact carrier documentation
        and each component datasheet—not a pinout for a similar board.
      </p>
    ),
    stopIf:
      "a suffix, board revision, component marking, voltage domain, or pin label is unknown.",
  },
  {
    title: "Classify the code before choosing pins",
    body: (
      <p>
        Decide whether the example is portable, capability-configured, or
        exact-board-only. Portable code assumes no physical peripheral.
        Capability code requires your explicit pins and circuit. Exact-board
        code applies only to the named carrier revision.
      </p>
    ),
    expected:
      "you can name the example class and explain why your exact hardware is or is not in its designed scope.",
  },
  {
    title: "Build a pin and conflict worksheet",
    body: (
      <p>
        For each signal, copy the physical header location, GPIO or exact
        MicroPython pin name, mode, pull state, voltage capability, and shared
        peripheral use from the exact documentation. Check input-only pins,
        boot/strapping pins, flash or PSRAM connections, and pins already used
        by displays, USB, radio, or another device.
      </p>
    ),
    stopIf:
      "a selected pin is reserved, input-only for an output role, a boot/strapping risk, or shared in an incompatible way.",
  },
  {
    title: "Review the electrical path",
    body: (
      <p>
        Confirm supply and logic voltage, maximum source/sink current, polarity,
        component power demand, shared ground, current-limiting resistor or
        other required protection, and any level shifting or separate supply.
        Account for startup states before user code configures a pin.
      </p>
    ),
    stopIf:
      "a voltage or current limit is exceeded, grounds cannot be shared safely, or required resistor, protection, or level conversion is missing.",
  },
  {
    title: "Bound the program before execution",
    body: (
      <p>
        Read the complete source. Identify its maximum loop count or duration,
        highest output level, expected physical effect, Console progress, Stop
        behavior, exception behavior, and final cleanup state. Replace an
        unbounded effect with a finite test before first power-up.
      </p>
    ),
    expected:
      "you can state the bounded effect, when to press Stop, and the exact cleanup that returns outputs and power to a safe state.",
  },
  {
    title: "Wire cold, inspect, then power",
    body: (
      <p>
        With all power removed, make the reviewed connections. Trace every wire
        from source to destination against the worksheet, check polarity and
        protection again, remove loose conductors, then apply power while ready
        to disconnect it.
      </p>
    ),
    stopIf:
      "the powered board resets, heats, smells unusual, draws unexpected current, or a component behaves before Run.",
  },
  {
    title: "Run once, observe, Stop, and clean up",
    body: (
      <p>
        Verify connected identity, choose Run explicitly, and compare the
        bounded physical and Console observations with the plan. Press Stop on
        any mismatch. When the test ends, drive outputs to their safe state when
        possible, disconnect peripheral power, then remove wiring.
      </p>
    ),
    expected:
      "the finite effect matches the plan and the circuit finishes powered down in the documented cleanup state.",
  },
];

export default function HardwareTutorial() {
  return (
    <TutorialPage
      slug="hardware"
      steps={steps}
      compatibilityNote={
        <p>
          This review method is designed for every profile. It intentionally
          provides no pin selection: generic-profile firmware and exact-board
          hardware identity are different claims.
        </p>
      }
    >
      <section aria-labelledby="hardware-before">
        <h2 id="hardware-before">Before you begin</h2>
        <p>
          A generic ESP profile has no carrier pin map, so there is no safe
          generic pin assumption. Use exact carrier documentation and component
          datasheets. The exact Pico 2 W and Waveshare B-version profiles expose
          only the documented onboard surfaces named in their own lessons.
        </p>
        <TutorialCallout
          title="Matching chip names are not a pinout"
          tone="warning"
        >
          <p>
            Two S3 boards can report the same <code>esp32-s3</code> runtime chip
            and still route every peripheral differently. Do not infer the
            Waveshare display or onboard pixel from the lean generic S3 image,
            memory size, or chip token.
          </p>
        </TutorialCallout>
      </section>

      <section aria-labelledby="hardware-classes">
        <h2 id="hardware-classes">Three compatibility classes</h2>
        <dl className="tutorial-definition-list">
          <div>
            <dt>Portable</dt>
            <dd>
              Console, language, data, workflow, or filesystem code with no pin
              or external-peripheral assumption.
            </dd>
          </div>
          <div>
            <dt>Configured capability</dt>
            <dd>
              GPIO, ADC, PWM, I2C, SPI, or NeoPixel behavior whose pins and
              circuit must be supplied from exact documentation.
            </dd>
          </div>
          <div>
            <dt>Exact board</dt>
            <dd>
              A named carrier surface such as Pico 2 W <code>Pin("LED")</code>{" "}
              or Waveshare LCD wiring; another carrier with the same MCU is
              outside that claim.
            </dd>
          </div>
        </dl>
      </section>

      <section aria-labelledby="hardware-never-assume">
        <h2 id="hardware-never-assume">What PyBLE does not decide for you</h2>
        <p>
          Firmware qualification does not prove your circuit, chosen pin,
          peripheral voltage, power source, component current, resistor value,
          pull configuration, or bus wiring. Example design metadata is also not
          HIL evidence. The safe path is documentation, calculation, cold
          wiring, inspection, a bounded first effect, Stop, and cleanup.
        </p>
      </section>
    </TutorialPage>
  );
}

// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

import { TutorialCallout } from "@/components/tutorial-callout";
import { TutorialBoardIdentityGallery } from "@/components/tutorial-board-identity-gallery";
import { TutorialConceptFigure } from "@/components/tutorial-concept-figure";
import { TutorialPage, type TutorialStep } from "@/components/tutorial-page";
import { pageMetadata } from "@/lib/site";

export const metadata = pageMetadata({
  title: "Configured hardware tutorial",
  description:
    "Configure explicit reviewed pins for bounded GPIO, ADC, PWM, I2C, SPI, and ESP NeoPixel examples, then Stop and restore safe hardware state.",
  path: "/learn/configured-hardware",
});

const steps: readonly TutorialStep[] = [
  {
    title: "Create an explicit configuration worksheet",
    body: (
      <p>
        Choose one capability and write down every role it needs. Set each GPIO
        number or exact pin name from your exact board documentation, plus mode,
        pull, voltage, current, shared peripheral, and cleanup. PyBLE does not
        choose a pin for you.
      </p>
    ),
    stopIf:
      "any role lacks an exact documented pin, electrical limit, wiring path, or safe cleanup state.",
  },
  {
    title: "Start with bounded digital GPIO",
    body: (
      <p>
        For an external LED, use the reviewed output pin, polarity, and
        current-limiting resistor. For a button, use the reviewed input and the
        example&apos;s documented pull/active level. For Button Controls LED,
        configure two distinct compatible pins.
      </p>
    ),
    expected:
      "a finite LED sequence or bounded button-transition report matches the circuit, then the output returns to its safe state.",
  },
  {
    title: "Add PWM only to a suitable output",
    body: (
      <p>
        Confirm the chosen output supports PWM and the load is electrically
        appropriate. Use the example&apos;s bounded low-duty fade rather than
        driving an unknown load directly from a GPIO.
      </p>
    ),
    expected:
      "the protected LED changes smoothly for the finite sequence and PWM is deinitialized or the output is left safe.",
  },
  {
    title: "Sample ADC within its input range",
    body: (
      <p>
        Verify the ADC-capable pin and the board&apos;s permitted analog input
        voltage. Connect only a source that stays inside that range and shares
        the intended ground; never use ADC sampling as a way to discover safe
        voltage.
      </p>
    ),
    stopIf:
      "the source can exceed the documented ADC range, floats unpredictably, or lacks a reviewed common reference.",
  },
  {
    title: "Configure I2C signal and power roles",
    body: (
      <p>
        Set explicit SDA and SCL pins, a conservative frequency, peripheral
        supply voltage, common ground, address expectations, and appropriate
        pull-ups. Run only a bounded I2C scan on the reviewed bus.
      </p>
    ),
    expected:
      "Console reports a finite address list or a truthful empty result without changing peripheral state.",
  },
  {
    title: "Wire the finite SPI loopback deliberately",
    body: (
      <p>
        Configure explicit SCK, MOSI, and MISO pins from exact documentation.
        For the loopback exercise, connect only the documented loopback path
        with power off; do not attach an unknown SPI peripheral as a substitute.
      </p>
    ),
    expected:
      "the received finite payload matches the transmitted bytes and the software SPI object is deinitialized.",
  },
  {
    title: "Use NeoPixel only inside the ESP design boundary",
    body: (
      <p>
        On one of the four ESP profiles, configure the exact data GPIO, pixel
        count, low brightness, supply, logic-level requirements, and shared
        ground for a WS2812-compatible pixel or strip. This capability is not
        designed for the Pico 2 W profile in the reviewed snapshot.
      </p>
    ),
    stopIf:
      "the profile is Pico 2 W, the pixel supply or logic level is uncertain, or the strip current exceeds the reviewed power plan.",
  },
  {
    title: "Stop and perform visible cleanup",
    body: (
      <p>
        Compare the effect and Console output with the bounded plan. Press Stop
        on any mismatch. Finish the example&apos;s <code>finally</code> cleanup
        where provided, set outputs and pixels off, deinitialize buses or PWM,
        remove peripheral power, and only then alter wiring.
      </p>
    ),
    expected:
      "the bounded test is complete, outputs are safe, buses are released, pixels are dark, and the circuit is unpowered before rewiring.",
  },
];

export default function ConfiguredHardwareTutorial() {
  return (
    <TutorialPage
      slug="configured-hardware"
      steps={steps}
      compatibilityNote={
        <p>
          GPIO, ADC, PWM, I2C, and SPI examples are designed across the five
          profiles only after configuration review. NeoPixel examples are
          designed for the four ESP profiles and are not applicable to Pico 2 W
          in this development snapshot.
        </p>
      }
    >
      <section aria-labelledby="configured-before">
        <h2 id="configured-before">Before you begin</h2>
        <p>
          Complete Hardware safety first. This lesson supplies no default pins
          and does not choose a pin from the connected chip. Set every role from
          your exact board documentation, inspect the complete example at its
          immutable source link, and keep the circuit powered off while wiring.
        </p>
        <TutorialCallout title="Designed is not validated" tone="warning">
          <p>
            The linked capability examples are development source with empty HIL
            evidence. A designed profile means the code was authored for that
            MicroPython capability; it does not validate your carrier, pins,
            components, or circuit.
          </p>
        </TutorialCallout>
        <TutorialBoardIdentityGallery
          boards={["esp32C3"]}
          title="One observed ESP32-C3 configuration context"
          introduction="Board C81A reported the esp32-c3 runtime token in this maintained physical session. That observation helps confirm the connected runtime, but exact carrier documentation must still supply every pin and electrical choice."
          caption="C81A session · connection and runtime evidence before explicit pin review"
        />
        <TutorialConceptFigure
          eyebrow="One bounded experiment"
          title="Review, observe, restore"
          items={[
            {
              label: "Review",
              detail:
                "Confirm pin roles, voltage, current, boot conflicts, protection, and shared ground.",
            },
            {
              label: "Observe",
              detail:
                "Run one finite effect with Console visible and Stop immediately available.",
            },
            {
              label: "Restore",
              detail:
                "Leave outputs safe, deinitialize buses, power down, and remove temporary wiring.",
            },
          ]}
          caption="A configured-hardware lesson is complete only after the circuit returns to a documented safe state."
        />
      </section>

      <section aria-labelledby="configured-progression">
        <h2 id="configured-progression">Capability progression</h2>
        <div className="tutorial-capability-grid">
          <article>
            <h3>GPIO</h3>
            <p>External LED, button input, and a two-pin combined exercise.</p>
          </article>
          <article>
            <h3>PWM</h3>
            <p>A protected external LED with a finite low-duty fade.</p>
          </article>
          <article>
            <h3>ADC</h3>
            <p>
              A capped set of raw and scaled readings inside the input range.
            </p>
          </article>
          <article>
            <h3>I2C</h3>
            <p>
              An explicitly configured software bus and finite address scan.
            </p>
          </article>
          <article>
            <h3>SPI</h3>
            <p>An explicitly configured software bus and finite loopback.</p>
          </article>
          <article>
            <h3>NeoPixel</h3>
            <p>
              A dim finite pixel sequence on reviewed ESP hardware and power.
            </p>
          </article>
        </div>
      </section>

      <section aria-labelledby="configured-one-change">
        <h2 id="configured-one-change">Change one variable at a time</h2>
        <p>
          Begin with one component and the shortest bounded example. Record the
          exact configuration and observation before adding another capability.
          A traceback or unexpected physical effect is a Stop condition, not a
          prompt to try random pin numbers.
        </p>
      </section>
    </TutorialPage>
  );
}

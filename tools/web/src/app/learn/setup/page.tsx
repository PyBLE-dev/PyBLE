// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

import Link from "next/link";

import { TutorialCallout } from "@/components/tutorial-callout";
import { TutorialPage, type TutorialStep } from "@/components/tutorial-page";
import { pageMetadata } from "@/lib/site";

export const metadata = pageMetadata({
  title: "Setup tutorial",
  description:
    "Install the PyBLE beta, provision one exact firmware profile with the correct wired method, connect over BLE, and verify board identity.",
  path: "/learn/setup",
});

const steps: readonly TutorialStep[] = [
  {
    title: "Back up the board and identify the exact profile",
    body: (
      <p>
        Copy off anything you need before flashing because installation can
        erase the board. Read the module marking, flash and PSRAM capacity,
        carrier model, and hardware revision; then match all of them to one
        profile on the installer. Similar names are not enough.
      </p>
    ),
    stopIf:
      "the memory size, PSRAM type, carrier suffix, or revision does not match one exact profile.",
  },
  {
    title: "Provision with the profile's wired method",
    body: (
      <p>
        On a compatible desktop browser, open the current firmware page. Select
        the exact profile, review the active release and erase warning, connect
        a data-capable cable, and start the enabled action. For Pico 2 W, use
        its UF2 file and BOOTSEL flow instead of Web Serial.
      </p>
    ),
    expected:
      "the installer reports completion for the selected profile, or the Pico volume accepts the exact UF2 and restarts.",
  },
  {
    title: "Move from the cable to Bluetooth",
    body: (
      <p>
        Disconnect the provisioning cable if desired, power-cycle the board, and
        wait for its agent to start. Open PyBLE on the tablet, allow Bluetooth
        access, scan for a nearby name beginning with PyBLE-, and tap that board
        to connect.
      </p>
    ),
    expected:
      "the scan shows one PyBLE-… advertisement and the app reaches its connected workspace.",
  },
  {
    title: "Verify identity before writing code",
    body: (
      <p>
        Compare your recorded installer selection and physical board with the
        connected board ID, agent firmware version, chip family, and MicroPython
        version. DeviceInfo does not report or authorize a provisioning profile,
        and a chip name cannot distinguish an exact carrier. Keep both the
        installer record and reported identity with any later problem report.
      </p>
    ),
    stopIf:
      "a reported field is absent or inconsistent with the physical board and your recorded installer selection.",
  },
];

export default function SetupTutorial() {
  return (
    <TutorialPage
      slug="setup"
      steps={steps}
      compatibilityNote={
        <p>
          The five profile identities are stable, but availability comes from
          the active release. The generic ESP profiles describe memory and
          runtime constraints, not a carrier-board pin map.
        </p>
      }
    >
      <section aria-labelledby="setup-equipment">
        <h2 id="setup-equipment">Before you begin</h2>
        <p>
          Have the exact board, a reliable data-capable USB cable, a desktop or
          laptop that can perform the wired install, stable power, and an iPad
          or invited Android test device with PyBLE installed. Stock MicroPython
          alone does not provide PBLE/1.
        </p>
        <TutorialCallout title="Flashing is destructive" tone="warning">
          <p>
            Make a backup of every file you need before you flash. Installation
            can erase board storage. Do not continue on an uncertain profile,
            and do not disconnect power during an erase or write.
          </p>
        </TutorialCallout>
      </section>

      <section aria-labelledby="setup-profile-methods">
        <h2 id="setup-profile-methods">
          Match profile and provisioning method
        </h2>
        <dl className="tutorial-definition-list">
          <div>
            <dt>ESP32 · 4 MiB</dt>
            <dd>
              Select <code>esp32-4mb</code> only for a classic ESP32 with 4 MiB
              external SPI flash and no assumed PSRAM; install with ESP Web
              Serial.
            </dd>
          </div>
          <div>
            <dt>ESP32-S3 · N16R8</dt>
            <dd>
              Select <code>esp32-s3-n16r8</code> only for 16 MiB flash and 8 MiB
              Octal PSRAM; install the lean generic image with ESP Web Serial.
            </dd>
          </div>
          <div>
            <dt>Waveshare ESP32-S3-LCD-1.47B</dt>
            <dd>
              Confirm the exact B-version with 16 MiB flash and 8 MiB Octal
              PSRAM, then select its separate profile and use ESP Web Serial.
              The shared ESP32-S3 chip token does not make the lean image
              interchangeable.
            </dd>
          </div>
          <div>
            <dt>ESP32-C3 · revision v0.3+</dt>
            <dd>
              Select <code>esp32-c3-4mb</code> only for revision v0.3+ with 4
              MiB external SPI flash; install with ESP Web Serial.
            </dd>
          </div>
          <div>
            <dt>Raspberry Pi Pico 2 W</dt>
            <dd>
              Hold BOOTSEL while connecting USB, copy the exact Pico 2 W UF2 to
              the mounted volume, and let the board restart.
            </dd>
          </div>
        </dl>
        <TutorialCallout title="Provision on a computer" tone="note">
          <p>
            An iPad cannot perform the wired provisioning step. Use a compatible
            desktop or laptop once; the everyday editor, Files, Blocks, Run, and
            Console workflow then uses BLE on the tablet.
          </p>
        </TutorialCallout>
      </section>

      <section aria-labelledby="setup-troubleshooting">
        <h2 id="setup-troubleshooting">If discovery or identity fails</h2>
        <p>
          Power-cycle once, keep the board near the tablet, release any other
          BLE connection, and scan again. A boot loop, implausible storage,
          missing PSRAM, absent PyBLE- advertisement, or wrong identity is a
          reason to stop—not a reason to try random profiles. Return to the{" "}
          <Link href="/flash">firmware selector</Link> and re-check the physical
          markings before using the <Link href="/support">issue checklist</Link>
          .
        </p>
      </section>
    </TutorialPage>
  );
}

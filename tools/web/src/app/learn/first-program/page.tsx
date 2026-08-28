// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

import { TutorialCallout } from "@/components/tutorial-callout";
import { TutorialPage, type TutorialStep } from "@/components/tutorial-page";
import { pageMetadata } from "@/lib/site";

export const metadata = pageMetadata({
  title: "First PyBLE program tutorial",
  description:
    "Create hello.py, save it to a connected MicroPython board, run it explicitly, read Console output, and practice Stop and reconnect recovery.",
  path: "/learn/first-program",
});

const helloProgram = 'print("Hello from PyBLE!")';

const steps: readonly TutorialStep[] = [
  {
    title: "Create a new board-backed file",
    body: (
      <p>
        With the correct board connected, choose New file in the Editor and name
        it <code>hello.py</code>. Enter exactly the one hardware-free line
        below. It uses no GPIO and is designed for all five profiles.
      </p>
    ),
    code: helloProgram,
    expected:
      "the editor shows hello.py as the current document and marks the unsaved edit clearly.",
  },
  {
    title: "Save one reviewed snapshot",
    body: (
      <p>
        Read the line once more, then choose Save. Wait for the transfer to
        finish before editing again so the saved snapshot and the visible
        document are easy to compare.
      </p>
    ),
    expected:
      "Save completes and hello.py remains the current board-backed file without an unsaved-change indicator.",
  },
  {
    title: "Run explicitly and read Console",
    body: (
      <p>
        Choose Run only after Save succeeds, then open Console. The full loop is
        <code> hello.py → Save → Run → Console</code>; creating or saving the
        file alone never executes it.
      </p>
    ),
    expected: (
      <>
        Console prints <code>Hello from PyBLE!</code> once and the finite
        program ends.
      </>
    ),
  },
  {
    title: "Edit and prove the cycle again",
    body: (
      <p>
        Change the message, Save the new snapshot, and Run it again. Confirm
        that Console shows the changed text, not the earlier copy.
      </p>
    ),
    expected:
      "the new Console line matches the exact text currently saved in the editor.",
  },
  {
    title: "Practice Stop and recovery",
    body: (
      <p>
        Choose Stop while work is active. Stop requests interruption; a soft
        reboot may close the BLE session. If that happens, wait for the agent,
        scan, reconnect, verify identity again, and reopen the file from Files.
      </p>
    ),
    expected:
      "bounded work stops, or the board returns after soft reboot and reconnect with the same verified identity.",
  },
];

export default function FirstProgramTutorial() {
  return (
    <TutorialPage
      slug="first-program"
      steps={steps}
      compatibilityNote={
        <p>
          This hardware-free program is designed for all five profiles because
          it only prints to the PBLE/1 Console. No pin, carrier, sensor, or
          display behavior is assumed.
        </p>
      }
    >
      <section aria-labelledby="first-program-before">
        <h2 id="first-program-before">Before you begin</h2>
        <p>
          Keep the board powered and verify that PyBLE still shows the identity
          checked in Setup. This lesson deliberately starts with a one-line,
          hardware-free program so an editor, transfer, runner, or Console
          problem cannot be confused with wiring.
        </p>
        <TutorialCallout title="Execution stays explicit" tone="safety">
          <p>
            New and Save do not run code. Inspect the file and choose Run
            yourself. Use Stop before disconnecting if a later program is still
            active.
          </p>
        </TutorialCallout>
      </section>

      <section aria-labelledby="first-program-recovery">
        <h2 id="first-program-recovery">What each observation proves</h2>
        <p>
          A successful Save proves the selected source reached the current board
          session. The one Console line proves explicit Run executed that saved
          file. Neither result validates hardware pins, and a reconnect should
          always be followed by another identity check.
        </p>
      </section>
    </TutorialPage>
  );
}

// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

import { TutorialCallout } from "@/components/tutorial-callout";
import { TutorialPage, type TutorialStep } from "@/components/tutorial-page";
import { pageMetadata } from "@/lib/site";

export const metadata = pageMetadata({
  title: "Blocks tutorial",
  description:
    "Open a bundled offline PyBLE Blocks starter, preview generated Python, create an editable copy, and save or run only through explicit actions.",
  path: "/learn/blocks",
});

const steps: readonly TutorialStep[] = [
  {
    title: "Open the bundled examples",
    body: (
      <p>
        Switch to Blocks and choose Examples. Select Hello PyBLE. The chooser is
        bundled with the app and works offline; selecting a row only presents
        its description and available actions.
      </p>
    ),
    expected:
      "the chooser shows Hello PyBLE, its concepts, no-external-wiring note, and an idle generated-source area.",
  },
  {
    title: "Preview before changing the workspace",
    body: (
      <p>
        Choose Preview and read the Generated Python panel. Preview is
        non-mutating: it does not replace the active workspace, write a board
        file, hand source to the Editor, or run anything.
      </p>
    ),
    expected:
      "a read-only Python preview appears while the Blocks canvas and connected board remain unchanged.",
  },
  {
    title: "Create an independent editable copy",
    body: (
      <p>
        With an empty workspace, choose Create copy. If your workspace is not
        empty, the app instead offers Replace workspace and requires a separate
        confirmation. A created copy is independent; edits never alter the
        bundled starter.
      </p>
    ),
    expected:
      "the Blocks canvas contains an editable Hello PyBLE copy and nothing has been saved or run.",
  },
  {
    title: "Edit and preview a fresh snapshot",
    body: (
      <p>
        Change the greeting block, then use Preview or Open in editor to inspect
        newly generated Python. Generation uses the current acknowledged
        workspace; returning from the Editor does not create two-way live sync.
      </p>
    ),
    expected:
      "the Python text reflects the edited block while the board still has not executed it.",
  },
  {
    title: "Save and Run only when ready",
    body: (
      <p>
        Connect and verify the intended board, review the target path, then
        choose Save. Choose Run as a second explicit action. PyBLE writes the
        Python source first and its matching sidecar last; neither a starter nor
        a preview triggers these actions.
      </p>
    ),
    expected:
      "Save reports a complete source-and-sidecar pair, and only explicit Run produces the changed greeting in Console.",
  },
  {
    title: "Reopen a saved workspace carefully",
    body: (
      <p>
        In Files, use Open as Blocks on the saved <code>.py</code> source. An
        exact, integrity-checked sidecar can restore the saved workspace only
        when it still describes the adjacent Python bytes. A stale, malformed,
        or missing companion is not silently trusted.
      </p>
    ),
    expected:
      "PyBLE presents a review before restoring exact blocks or before offering a bounded Python conversion.",
  },
  {
    title: "Treat Python conversion as a strict boundary",
    body: (
      <p>
        When you choose Convert Python to Blocks or Open as Blocks without an
        exact companion, PyBLE accepts only its supported beginner subset. The
        Python-to-Blocks conversion is all-or-nothing: any unsupported construct
        yields diagnostics and leaves the live workspace unchanged.
      </p>
    ),
    stopIf:
      "the review reports an unsupported construct, stale source, invalid target, or source change; fix the Python and start a fresh conversion.",
  },
];

export default function BlocksTutorial() {
  return (
    <TutorialPage
      slug="blocks"
      steps={steps}
      compatibilityNote={
        <p>
          The language-only starters are designed for all five profiles.
          Hardware starters become appropriate only after explicit pin and
          wiring review. Their inclusion in the app is not physical-board
          validation.
        </p>
      }
    >
      <section aria-labelledby="blocks-before">
        <h2 id="blocks-before">Before you begin</h2>
        <p>
          Blocks-to-Python is the primary visual workflow. Preview, Create copy,
          Replace workspace, Open in editor, Save, and Run are distinct actions;
          loading or generating never means execution.
        </p>
        <TutorialCallout title="Loading is never execution" tone="safety">
          <p>
            Read generated Python before Save, verify the current board and
            target, then choose Run explicitly. Stop any ongoing program before
            changing wiring or disconnecting power.
          </p>
        </TutorialCallout>
      </section>

      <section aria-labelledby="blocks-starters">
        <h2 id="blocks-starters">Eight bundled offline starters</h2>
        <div className="tutorial-starter-grid">
          <article>
            <h3>Hello PyBLE</h3>
            <p>Print one greeting; no external wiring.</p>
          </article>
          <article>
            <h3>Count repeatedly</h3>
            <p>Combine a variable, loop, and paced Console output.</p>
          </article>
          <article>
            <h3>Blink LED</h3>
            <p>Requires an explicit GPIO and an external, protected LED.</p>
          </article>
          <article>
            <h3>Blink NeoPixel</h3>
            <p>Requires an explicit data GPIO, pixel power review, and Stop.</p>
          </article>
          <article>
            <h3>Read button</h3>
            <p>Requires an explicit input pin and reviewed pull-up wiring.</p>
          </article>
          <article>
            <h3>Button controls LED</h3>
            <p>Requires two distinct explicit pins and reviewed components.</p>
          </article>
          <article>
            <h3>Reusable function</h3>
            <p>Shows parameters and calls without external hardware.</p>
          </article>
          <article>
            <h3>ESP32-S3-LCD-1.47B TFT pattern</h3>
            <p>
              Only for the exact B-version display profile and documented pins.
            </p>
          </article>
        </div>
      </section>

      <section aria-labelledby="blocks-hardware-boundaries">
        <h2 id="blocks-hardware-boundaries">Hardware starter boundaries</h2>
        <p>
          Blink LED, Read button, and Button controls LED require user-entered
          pins from exact carrier documentation; PyBLE supplies no default pins
          and assumes no generic onboard LED. Blink NeoPixel is designed for the
          four ESP profiles, not Pico 2 W. It still assumes neither a built-in
          pixel nor a safe power circuit.
        </p>
        <p>
          The TFT starter is exact-board-only: use it on the Waveshare
          ESP32-S3-LCD-1.47B B-version after checking its fixed wiring. It is
          not for the lean ESP32-S3 N16R8 image, even though both report
          ESP32-S3.
        </p>
        <TutorialCallout title="Enter every hardware role" tone="warning">
          <p>
            A hardware preview stays unavailable until every required GPIO or
            exact pin name is valid. Validate voltage, current, polarity, shared
            ground, boot/strapping conflicts, and protection outside the app
            before generating or running the copy.
          </p>
        </TutorialCallout>
      </section>
    </TutorialPage>
  );
}

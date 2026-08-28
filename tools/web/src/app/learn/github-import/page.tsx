// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

import { TutorialCallout } from "@/components/tutorial-callout";
import { TutorialPage, type TutorialStep } from "@/components/tutorial-page";
import { examplesSnapshot } from "@/lib/tutorials";
import { pageMetadata } from "@/lib/site";

export const metadata = pageMetadata({
  title: "Public GitHub import tutorial",
  description:
    "Review and import a lowercase Python example from a public GitHub repository using an immutable commit and an exact child-folder destination.",
  path: "/learn/github-import",
});

const exampleFolder = "examples/portable/basics/hello_console";
const boardFolder = "/examples/portable/basics";

const steps: readonly TutorialStep[] = [
  {
    title: "Create the destination before opening import",
    body: (
      <p>
        In Files, create and enter <code>{boardFolder}</code>, one child folder
        at a time if necessary. GitHub import does not create board directories.
        Keep this current destination visible before opening Import examples.
      </p>
    ),
    expected: (
      <>
        the Files breadcrumb shows exactly <code>{boardFolder}</code>.
      </>
    ),
  },
  {
    title: "Review the editable repository URL",
    body: (
      <p>
        Open Import examples from GitHub. The repository URL starts as the
        editable official default <code>{examplesSnapshot.repositoryUrl}</code>.
        Keep that canonical repository URL for this exercise; a GitHub blob URL
        is not a repository URL and must not be pasted into the field.
      </p>
    ),
    expected:
      "the importer shows the canonical public repository and does not ask for a GitHub account or token.",
  },
  {
    title: "Distinguish discovery from provenance",
    body: (
      <p>
        In Branch mode, load the chooser and observe that it lists only
        branches. Select <code>main</code> to understand branch discovery, but
        do not use that moving name as this lesson&apos;s reproducibility
        identity. Open Advanced, choose tag or commit, and enter the full
        40-character commit below.
      </p>
    ),
    code: examplesSnapshot.commit,
    expected:
      "the importer resolves and displays the same full immutable commit before browsing files.",
  },
  {
    title: "Browse one source folder and select the file",
    body: (
      <p>
        Browse to <code>{exampleFolder}</code>. Select the displayed ordinary
        lowercase <code>.py</code> entry <code>pyble_hello_console.py</code>.
        The bounded importer accepts selected direct regular Python files from
        one shown GitHub folder, not a recursive tree.
      </p>
    ),
    expected:
      "the review contains one pinned source path and one derived board target, with no hidden descendants.",
  },
  {
    title: "Verify exact source, target, and overwrite state",
    body: (
      <p>
        Confirm the source names the full commit and the folder above. Confirm
        that the basename is flattened into the current board directory as{" "}
        <code>{boardFolder}/pyble_hello_console.py</code>. If the target exists,
        inspect it and grant the separate overwrite consent only when replacing
        it is intentional.
      </p>
    ),
    stopIf:
      "the source commit, source folder, current directory, filename, or overwrite state differs from your review.",
  },
  {
    title: "Import and interpret the terminal result",
    body: (
      <p>
        Choose Download to board once, or choose Overwrite and download only
        after reviewing every existing target. PyBLE fetches and validates the
        selected content before board writes, then writes targets sequentially.
        A multi-file import is not atomic: after a first failure or session
        change, completed writes remain and later targets are reported
        unattempted.
      </p>
    ),
    expected:
      "the terminal result names the exact written target, and the refreshed Files list agrees with that result.",
  },
  {
    title: "Open, review, and run as separate choices",
    body: (
      <p>
        Close the import result, find the imported file in Files, open it, read
        all source, and only then choose Run if its behavior is acceptable. The
        importer does not automatically open, save, or run imported code.
      </p>
    ),
    expected:
      "nothing executes until you explicitly open, review, and choose Run in the connected workspace.",
  },
];

export default function GitHubImportTutorial() {
  return (
    <TutorialPage
      slug="github-import"
      steps={steps}
      compatibility={{
        "esp32-4mb": "developmentUnvalidated",
        "esp32-s3-n16r8": "developmentUnvalidated",
        "waveshare-esp32-s3-lcd-147b": "developmentUnvalidated",
        "esp32-c3-4mb": "developmentUnvalidated",
        "rpi-pico2-w": "developmentUnvalidated",
      }}
      compatibilityNote={
        <p>
          This source snapshot is designed for stated profiles but remains
          development-only, unreleased, and not HIL-validated. Its official
          repository name grants no elevated trust; review every target and
          every source file before Run.
        </p>
      }
    >
      <section aria-labelledby="github-before">
        <h2 id="github-before">Before you begin</h2>
        <p>
          This lesson uses public source at immutable commit{" "}
          <code>{examplesSnapshot.commit}</code>. The mutable <code>main</code>
          branch is useful for branch discovery, while the full pinned commit is
          the reproducible review point.
        </p>
        <TutorialCallout title="Public GitHub request" tone="privacy">
          <p>
            This is PyBLE&apos;s sole optional Internet workflow. Only after you
            start it, PyBLE sends HTTPS requests to <code>api.github.com</code>
            for the public repository owner/name, ref, branch discovery, paths,
            selected public source, and a PyBLE version user agent. It uses no
            account or token and does not send board identity, board files, or
            private project source. GitHub independently receives ordinary
            request metadata such as the client IP address.
          </p>
        </TutorialCallout>
      </section>

      <section aria-labelledby="github-boundaries">
        <h2 id="github-boundaries">Import boundaries</h2>
        <p>
          Only ordinary lowercase <code>.py</code> direct files from one folder
          can be selected. Chosen basenames are flattened into the current board
          directory; the GitHub directory tree is not recreated. Create the
          destination before import, and remember that import has no automatic
          open or Run step.
        </p>
        <TutorialCallout title="Rate limits are normal" tone="note">
          <p>
            Public unauthenticated GitHub requests have a rate limit. If GitHub
            reports that the public request limit was reached, stop retrying and
            wait for the reset shown by the app. Editing, BLE, Files, Blocks,
            and Run remain available offline and do not depend on this importer.
          </p>
        </TutorialCallout>
      </section>

      <section aria-labelledby="github-provenance">
        <h2 id="github-provenance">Immutable source for this lesson</h2>
        <p>
          The complete runnable source remains in the examples repository. Open
          the exact reviewed snapshot in a browser if you want an independent
          comparison.
        </p>
        <a
          href={
            examplesSnapshot.repositoryUrl +
            "/tree/" +
            examplesSnapshot.commit +
            "/" +
            exampleFolder
          }
          target="_blank"
          rel="noopener noreferrer"
        >
          View Hello Console at commit {examplesSnapshot.commit.slice(0, 12)}…
        </a>
      </section>
    </TutorialPage>
  );
}

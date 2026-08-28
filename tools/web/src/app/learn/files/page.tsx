// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

import { TutorialAppCapture } from "@/components/tutorial-app-capture";
import { TutorialCallout } from "@/components/tutorial-callout";
import { TutorialPage, type TutorialStep } from "@/components/tutorial-page";
import { pageMetadata } from "@/lib/site";

export const metadata = pageMetadata({
  title: "Board Files tutorial",
  description:
    "Create and edit files in a child folder, understand protected board-root paths, and review PyBLE's permanent non-atomic multi-file deletion.",
  path: "/learn/files",
});

const steps: readonly TutorialStep[] = [
  {
    title: "Work below the board root",
    body: (
      <p>
        Open Files and create or enter a disposable child folder such as{" "}
        <code>/tutorial-capture</code>. You may instead work below{" "}
        <code>/examples</code> when that folder contains no valuable work. Keep
        the breadcrumb visible and confirm the exact current path before every
        mutation.
      </p>
    ),
    expected:
      "Files shows /tutorial-capture, or the disposable child you chose, as the current board folder.",
  },
  {
    title: "Create, open, edit, save, and refresh",
    body: (
      <p>
        Create <code>delete_me_one.py</code> and <code>delete_me_two.py</code>.
        Leave them empty for this deletion exercise, return to Files, and choose
        Refresh. Use only files you are prepared to lose.
      </p>
    ),
    expected:
      "both disposable regular files appear directly in the current folder after Refresh.",
  },
  {
    title: "Enter the bounded selection mode",
    body: (
      <p>
        Choose Select files, or long-press one eligible regular-file row. Toggle
        the two disposable files. Selection is bound to the current folder and
        board session; normal navigation and mutation actions remain unavailable
        until you Cancel or leave selection mode.
      </p>
    ),
    expected:
      "the contextual bar reports exactly two selected files and leaves folders or locked entries unavailable.",
  },
  {
    title: "Read the confirmation, then cancel once",
    body: (
      <p>
        Choose Delete selected files. Read the exact current folder and ordered
        filenames in the confirmation, then choose Cancel for this first pass.
        Confirm in Files that neither disposable file was removed.
      </p>
    ),
    visual: <TutorialAppCapture capture="filesMultiDeleteReview" />,
    expected:
      "the dialog closes and both files remain; cancellation issues no deletion.",
  },
  {
    title: "Confirm a permanent batch",
    body: (
      <p>
        Re-enter selection, select only the two disposable files, review the
        same exact targets, and confirm Delete. Keep the board connected until
        the terminal result and refreshed listing appear.
      </p>
    ),
    stopIf:
      "the confirmation names a different folder, an unselected file, or anything you have not backed up.",
  },
  {
    title: "Interpret the result literally",
    body: (
      <p>
        Compare the reported succeeded, failed/current, and unattempted paths
        with the refreshed list. A partial result means earlier removals stay
        removed; resolve the connection or path problem before deciding whether
        to retry an unresolved file.
      </p>
    ),
    expected:
      "a complete result removes both files, while a partial result identifies exactly what changed without claiming rollback.",
  },
];

export default function FilesTutorial() {
  return (
    <TutorialPage
      slug="files"
      steps={steps}
      compatibilityNote={
        <p>
          Files uses the PBLE/1 filesystem surface on every profile. Protection
          is path-based and case-sensitive; lesson compatibility does not make
          every board-root entry user-editable.
        </p>
      }
    >
      <section aria-labelledby="files-before">
        <h2 id="files-before">Before you begin</h2>
        <p>
          Practice only with disposable files in <code>/tutorial-capture</code>,{" "}
          <code>/examples</code>, or a child folder. Files can create, open,
          edit, save, refresh, and remove board content, but this lesson does
          not promise direct export to tablet storage.
        </p>
        <TutorialCallout title="Deletion is permanent" tone="warning">
          <p>
            Multi-file deletion is permanent: there is no trash and no rollback.
            It runs sequentially, is fail-fast, and is not atomic. If a later
            deletion fails or the session changes, files already deleted remain
            deleted and later targets are unattempted.
          </p>
        </TutorialCallout>
      </section>

      <section aria-labelledby="files-selection-boundary">
        <h2 id="files-selection-boundary">What can be selected</h2>
        <p>
          Selection includes only eligible, visible, direct regular files in the
          currently shown folder. Folders are excluded, omitted or truncated
          entries are excluded, and selection does not include descendants. It
          is not recursive. A folder still uses its separate one-at-a-time,
          empty-directory delete behavior.
        </p>
        <p>
          At the board root, exact <code>boot.py</code> and{" "}
          <code>_boot.py</code>, lowercase names beginning with{" "}
          <code>pyble</code> or <code>pble</code>, and any path component ending
          in <code>.pbltmp</code> are protected. Ordinary nested{" "}
          <code>pyble*</code> basenames are not root control files, but{" "}
          <code>.pbltmp</code> remains locked anywhere.
        </p>
      </section>

      <section aria-labelledby="files-safe-review">
        <h2 id="files-safe-review">Review before every mutation</h2>
        <p>
          The breadcrumb, selected count, exact filenames, connection state, and
          confirmation form one safety check. If any of them changes or looks
          unfamiliar, Cancel. Never use a deletion exercise to test whether a
          protected path is truly protected.
        </p>
      </section>
    </TutorialPage>
  );
}

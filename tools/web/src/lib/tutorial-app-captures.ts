// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

export type TutorialCaptureReview =
  | {
      status: "pending-derivative";
      sha256: null;
    }
  | {
      status: "reviewed";
      sha256: string;
    };

export type TutorialAppCaptureRecord = {
  src: `/learn/app/${string}.png`;
  alt: string;
  caption: string;
  width: number;
  height: number;
  provenance: {
    device: "Lenovo TB-J616X";
    operatingSystem: "Android 12 (API 31)";
    appVersion: "0.2.0 beta";
    appBuild: 5;
    capturedOn: "2026-08-28";
    sourceRevision: string;
    rawCapture: string;
    depictedState: string;
    processing: string;
    privacyReview: string;
    review: TutorialCaptureReview;
  };
};

const sharedProvenance = {
  device: "Lenovo TB-J616X",
  operatingSystem: "Android 12 (API 31)",
  appVersion: "0.2.0 beta",
  appBuild: 5,
  capturedOn: "2026-08-28",
  sourceRevision: "4df378fc76c919f0e2481eb5b668f14115d38587",
  processing:
    "Crop the Android status and navigation bars, then strip metadata; do not retouch app pixels.",
  privacyReview:
    "No account, token, private repository, notification, or unrelated board file is visible. Some captures retain the Lenovo stylus edge control as truthful device chrome rather than retouching app pixels.",
} as const;

function captureRecord(
  capture: Omit<TutorialAppCaptureRecord, "provenance"> & {
    rawCapture: string;
    depictedState: string;
    sha256: string | null;
  },
): TutorialAppCaptureRecord {
  const { depictedState, rawCapture, sha256, ...record } = capture;
  const review: TutorialCaptureReview =
    sha256 === null
      ? { status: "pending-derivative", sha256: null }
      : { status: "reviewed", sha256 };

  return {
    ...record,
    provenance: {
      ...sharedProvenance,
      rawCapture,
      depictedState,
      review,
    },
  };
}

export const tutorialAppCaptures = {
  setupScanResults: captureRecord({
    src: "/learn/app/pyble-app-0.2.0-build-5-setup-scan-results-3558cadbe501.png",
    alt: "PyBLE 0.2.0 beta on a Lenovo Android tablet showing the nearby Bluetooth scan result for board PyBLE-5646.",
    caption: "Bluetooth discovery · one nearby PyBLE board",
    width: 2000,
    height: 1092,
    rawCapture: "06-setup-scan-results-production-release.raw.png",
    depictedState:
      "Nearby-board scan showing one PyBLE-5646 advertisement before connection.",
    sha256: "3558cadbe501d1865aafbacf4fe5dd9624ae969a2fb0ff7bbd457029bcf2c41c",
  }),
  setupConnectedIdentity: captureRecord({
    src: "/learn/app/pyble-app-0.2.0-build-5-setup-connected-identity-58f65b64a966.png",
    alt: "PyBLE 0.2.0 beta connected workspace on a Lenovo Android tablet showing board, firmware, and ESP32-S3 identity details.",
    caption: "Connected workspace · identity checked before writing",
    width: 2000,
    height: 1092,
    rawCapture: "07-setup-connected-identity-production-release.raw.png",
    depictedState:
      "Connected workspace showing board 5646, agent firmware 0.6.0, and ESP32-S3 context.",
    sha256: "58f65b64a966d4ef2dcd0148442bf07dbe6b2008eda502f9d1e14cda4b7b36ce",
  }),
  firstProgramEditorConsole: captureRecord({
    src: "/learn/app/pyble-app-0.2.0-build-5-first-program-editor-console-86552d68afaa.png",
    alt: "PyBLE 0.2.0 beta on a Lenovo Android tablet showing saved hello.py source and the exact Hello from PyBLE Console output.",
    caption: "hello.py · saved source and explicit Run result",
    width: 2000,
    height: 1092,
    rawCapture: "08-first-program-editor-console-production-release.raw.png",
    depictedState:
      "Saved hello.py source beside its completed explicit-Run Console output.",
    sha256: "86552d68afaa7f9ea8b1151e0ffc812685815f3009bb64b7a3c823090ef42152",
  }),
  filesMultiDeleteReview: captureRecord({
    src: "/learn/app/pyble-app-0.2.0-build-5-files-multi-delete-review-b1df22dfa70a.png",
    alt: "PyBLE 0.2.0 beta on a Lenovo Android tablet showing the confirmation for two selected disposable files before deletion.",
    caption: "Files · exact two-file deletion review before Cancel",
    width: 2000,
    height: 1092,
    rawCapture: "09-files-multi-delete-review-production-release.raw.png",
    depictedState:
      "Permanent deletion confirmation naming two selected disposable files before Cancel.",
    sha256: "b1df22dfa70a449356c05f34189ff897decdfbd418bf4630ae251365b6ed6b86",
  }),
  githubBranchChooser: captureRecord({
    src: "/learn/app/pyble-app-0.2.0-build-5-github-import-branch-chooser-4514d2f0522b.png",
    alt: "PyBLE 0.2.0 beta on a Lenovo Android tablet showing the editable official GitHub URL and branches-only chooser with main selected.",
    caption: "GitHub import · editable URL and branches-only discovery",
    width: 2000,
    height: 1092,
    rawCapture: "10-github-import-branch-chooser-production-release.raw.png",
    depictedState:
      "Editable official repository URL with the branches-only chooser open on main.",
    sha256: "4514d2f0522bb3600ba38a75d9ed581255877d1949a8c153341af2d720da8ba7",
  }),
  githubPrewriteReview: captureRecord({
    src: "/learn/app/pyble-app-0.2.0-build-5-github-import-prewrite-review-faa68602fcd0.png",
    alt: "PyBLE 0.2.0 beta on a Lenovo Android tablet showing the immutable GitHub source and exact board target before download.",
    caption: "GitHub import · immutable source and target review",
    width: 2000,
    height: 1092,
    rawCapture: "11-github-prewrite-review-production-release.raw.png",
    depictedState:
      "Pre-write review showing one immutable GitHub source and its exact board target.",
    sha256: "faa68602fcd0ef2761573e726c490fcbbfd3d953eecaff60d246511cfa0cb047",
  }),
  examplesImportComplete: captureRecord({
    src: "/learn/app/pyble-app-0.2.0-build-5-examples-import-complete-ab466a044a11.png",
    alt: "PyBLE 0.2.0 beta on a Lenovo Android tablet showing the completed one-file example import without opening or running it.",
    caption: "Examples · completed import with execution still explicit",
    width: 2000,
    height: 1092,
    rawCapture: "12-examples-import-complete-production-release.raw.png",
    depictedState:
      "Completed one-file example import before any explicit open or Run action.",
    sha256: "ab466a044a115a20bef8b1bf355d49867a5a6d439333e51ff3b8deb11d3c9317",
  }),
  blocksHelloWorkspace: captureRecord({
    src: "/learn/app/pyble-app-0.2.0-build-5-blocks-hello-workspace-c37bd12f3102.png",
    alt: "PyBLE 0.2.0 beta on a Lenovo Android tablet showing an editable Hello PyBLE Blocks workspace and its generated Python.",
    caption: "Blocks · Hello PyBLE workspace and generated Python",
    width: 2000,
    height: 1092,
    rawCapture: "20-blocks-hello-workspace-production-release.raw.png",
    depictedState:
      "Editable Hello PyBLE Blocks copy with its generated Python visible.",
    sha256: "c37bd12f31021c0a8dfcf1ecd8f592c1d8083c081a5d1d74582dbc8cf9998ee4",
  }),
} satisfies Record<string, TutorialAppCaptureRecord>;

export type TutorialAppCaptureId = keyof typeof tutorialAppCaptures;

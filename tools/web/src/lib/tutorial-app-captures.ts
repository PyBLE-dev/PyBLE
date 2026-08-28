// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

export type TutorialCaptureReview =
  | { status: "pending-derivative"; sha256: null }
  | { status: "reviewed"; sha256: string };

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
  privacyReview:
    "No account, token, private repository, notification, or unrelated user file is visible. The Lenovo stylus overlay was stopped before every selected frame.",
} as const;

const fullFrameProcessing =
  "Crop the Android status and navigation bars to 2000×1092+0+36, strip metadata, and do not retouch app pixels.";
const readyProcessing =
  "Crop the exact 400×84+0+36 Ready status, strip metadata, and do not retouch app pixels.";
const chipProcessing =
  "Crop the exact 512×390+1488+330 read-only runtime-chip panel, strip metadata, and do not retouch app pixels.";

function captureRecord(
  capture: Omit<TutorialAppCaptureRecord, "provenance"> & {
    rawCapture: string;
    depictedState: string;
    processing: string;
    sha256: string | null;
  },
): TutorialAppCaptureRecord {
  const { depictedState, processing, rawCapture, sha256, ...record } = capture;
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
      processing,
      review,
    },
  };
}

export const tutorialAppCaptures = {
  setupFiveBoardScan: captureRecord({
    src: "/learn/app/pyble-app-0.2.0-build-5-setup-five-board-scan-a89dedab7efc.png",
    alt: "PyBLE 0.2.0 beta on a Lenovo Android tablet showing five stopped Bluetooth scan results from nearby PyBLE agents.",
    caption: "Bluetooth discovery · five nearby agents · scan stopped",
    width: 2000,
    height: 1092,
    rawCapture: "07-five-board-scan-stopped.raw.png",
    depictedState:
      "Stable stopped scan showing five distinct PyBLE advertisements, Boards seen: 5, and Scan: Idle.",
    processing: fullFrameProcessing,
    sha256: "a89dedab7efc472332e4280ba145400edf0be2cf2f68acb50d26dca1d2023bcf",
  }),
  identity5646Ready: captureRecord({
    src: "/learn/app/pyble-app-0.2.0-build-5-identity-5646-ready-6b8ef886ea40.png",
    alt: "PyBLE 0.2.0 beta Ready status on a Lenovo Android tablet for board 5646 running agent firmware 0.6.0.",
    caption: "Board 5646 · Ready · agent 0.6.0",
    width: 400,
    height: 84,
    rawCapture: "02-connected-5646.raw.png",
    depictedState: "Ready board 5646 on PyBLE firmware 0.6.0.",
    processing: readyProcessing,
    sha256: "6b8ef886ea4039288e7af1c18921ac41b1b22a10f336a59f96cbf28a74cdb4d2",
  }),
  identity5646Chip: captureRecord({
    src: "/learn/app/pyble-app-0.2.0-build-5-identity-5646-chip-03edb94bcf73.png",
    alt: "PyBLE 0.2.0 beta read-only pin reference on a Lenovo Android tablet showing the esp32-s3 runtime token for board 5646.",
    caption: "Observed runtime token · esp32-s3",
    width: 512,
    height: 390,
    rawCapture: "02-connected-5646.raw.png",
    depictedState:
      "Observed esp32-s3 runtime token; it is not provisioning-profile proof.",
    processing: chipProcessing,
    sha256: "03edb94bcf730b72028952962893a3ac26959a3d7c4bf948fbc252757a86e452",
  }),
  identity8c9eReady: captureRecord({
    src: "/learn/app/pyble-app-0.2.0-build-5-identity-8c9e-ready-3b64e4b0b84c.png",
    alt: "PyBLE 0.2.0 beta Ready status on a Lenovo Android tablet for board 8C9E running agent firmware 0.6.0.",
    caption: "Board 8C9E · Ready · agent 0.6.0",
    width: 400,
    height: 84,
    rawCapture: "03-connected-8c9e.raw.png",
    depictedState: "Ready board 8C9E on PyBLE firmware 0.6.0.",
    processing: readyProcessing,
    sha256: "3b64e4b0b84c2d1a81c32b190bfc45d0f294758998bdef1d3c1776d0a1879045",
  }),
  identity8c9eChip: captureRecord({
    src: "/learn/app/pyble-app-0.2.0-build-5-identity-8c9e-chip-0aa751bf86a3.png",
    alt: "PyBLE 0.2.0 beta read-only pin reference on a Lenovo Android tablet showing the esp32 runtime token for board 8C9E.",
    caption: "Observed runtime token · esp32",
    width: 512,
    height: 390,
    rawCapture: "03-connected-8c9e.raw.png",
    depictedState:
      "Observed esp32 runtime token; it is not provisioning-profile proof.",
    processing: chipProcessing,
    sha256: "0aa751bf86a3e7f247a731ecc9ac65b7b2fcb61188201e79c327ba0ca561a3a8",
  }),
  identityc81aReady: captureRecord({
    src: "/learn/app/pyble-app-0.2.0-build-5-identity-c81a-ready-8dea0554c432.png",
    alt: "PyBLE 0.2.0 beta Ready status on a Lenovo Android tablet for board C81A running agent firmware 0.6.0.",
    caption: "Board C81A · Ready · agent 0.6.0",
    width: 400,
    height: 84,
    rawCapture: "04-connected-c81a.raw.png",
    depictedState: "Ready board C81A on PyBLE firmware 0.6.0.",
    processing: readyProcessing,
    sha256: "8dea0554c432558f5f411a67a2175a5ff762e96c055fd9117ee3fb97906a1fd1",
  }),
  identityc81aChip: captureRecord({
    src: "/learn/app/pyble-app-0.2.0-build-5-identity-c81a-chip-1c4d40085693.png",
    alt: "PyBLE 0.2.0 beta read-only pin reference on a Lenovo Android tablet showing the esp32-c3 runtime token for board C81A.",
    caption: "Observed runtime token · esp32-c3",
    width: 512,
    height: 390,
    rawCapture: "04-connected-c81a.raw.png",
    depictedState:
      "Observed esp32-c3 runtime token; it is not provisioning-profile proof.",
    processing: chipProcessing,
    sha256: "1c4d400856933184a8d37548240469c46850cafc9a76207f17d7b4f9b424c468",
  }),
  identityda86Ready: captureRecord({
    src: "/learn/app/pyble-app-0.2.0-build-5-identity-da86-ready-49595991ba1f.png",
    alt: "PyBLE 0.2.0 beta Ready status on a Lenovo Android tablet for board DA86 running agent firmware 0.6.0.",
    caption: "Board DA86 · Ready · agent 0.6.0",
    width: 400,
    height: 84,
    rawCapture: "05-connected-da86.raw.png",
    depictedState: "Ready board DA86 on PyBLE firmware 0.6.0.",
    processing: readyProcessing,
    sha256: "49595991ba1f422ca8e840594b198953d00e3938c1d13d6c9c5e2586d50a0972",
  }),
  identityda86Chip: captureRecord({
    src: "/learn/app/pyble-app-0.2.0-build-5-identity-da86-chip-03edb94bcf73.png",
    alt: "PyBLE 0.2.0 beta read-only pin reference on a Lenovo Android tablet showing the esp32-s3 runtime token for board DA86.",
    caption: "Observed runtime token · esp32-s3",
    width: 512,
    height: 390,
    rawCapture: "05-connected-da86.raw.png",
    depictedState:
      "Observed esp32-s3 runtime token; it is not provisioning-profile proof.",
    processing: chipProcessing,
    sha256: "03edb94bcf730b72028952962893a3ac26959a3d7c4bf948fbc252757a86e452",
  }),
  identity3dcbReady: captureRecord({
    src: "/learn/app/pyble-app-0.2.0-build-5-identity-3dcb-ready-613559d187f3.png",
    alt: "PyBLE 0.2.0 beta Ready status on a Lenovo Android tablet for board 3DCB running agent firmware 0.6.0.",
    caption: "Board 3DCB · Ready · agent 0.6.0",
    width: 400,
    height: 84,
    rawCapture: "06-connected-3dcb.raw.png",
    depictedState: "Ready board 3DCB on PyBLE firmware 0.6.0.",
    processing: readyProcessing,
    sha256: "613559d187f330e7c7ba3375f86123dbfc4a7ea51b7cb703d34659d9972463e2",
  }),
  identity3dcbChip: captureRecord({
    src: "/learn/app/pyble-app-0.2.0-build-5-identity-3dcb-chip-2b80ef41db8f.png",
    alt: "PyBLE 0.2.0 beta read-only pin reference on a Lenovo Android tablet showing the rpi-pico2-w runtime token for board 3DCB.",
    caption: "Observed runtime token · rpi-pico2-w",
    width: 512,
    height: 390,
    rawCapture: "06-connected-3dcb.raw.png",
    depictedState:
      "Observed rpi-pico2-w runtime token; it is not provisioning-profile proof.",
    processing: chipProcessing,
    sha256: "2b80ef41db8f86d5d0d1b79aebf97041fffbba2178817a2a4598ed038c717d96",
  }),
  firstProgramEditorConsole: captureRecord({
    src: "/learn/app/pyble-app-0.2.0-build-5-first-program-editor-console-f6928eea293b.png",
    alt: "PyBLE 0.2.0 beta on a Lenovo Android tablet showing saved hello.py source and one completed Hello from PyBLE Console line on board 8C9E.",
    caption: "hello.py · saved source and explicit Run result",
    width: 2000,
    height: 1092,
    rawCapture: "08-first-program-classic-esp32.raw.png",
    depictedState:
      "Ready board 8C9E with saved hello.py, Finished status, and exactly one Hello from PyBLE Console line.",
    processing: fullFrameProcessing,
    sha256: "f6928eea293bd20bcddab94e3e56034033b74a6470cab0f9b018b6a31b969203",
  }),
  filesMultiDeleteReview: captureRecord({
    src: "/learn/app/pyble-app-0.2.0-build-5-files-multi-delete-review-42cfacddd965.png",
    alt: "PyBLE 0.2.0 beta on a Lenovo Android tablet showing the exact permanent-delete review for two empty disposable files on board 8C9E.",
    caption: "Files · exact two-file deletion review before Cancel",
    width: 2000,
    height: 1092,
    rawCapture: "17-files-multi-delete-classic-esp32-idle.raw.png",
    depictedState:
      "Idle connected session with a permanent-delete confirmation naming only delete_me_one.py and delete_me_two.py in /tutorial-capture.",
    processing: fullFrameProcessing,
    sha256: "42cfacddd9657146ba0edfb20273e87e56b5cf8ed9d646c6fd5878f77a728e31",
  }),
  githubBranchChooser: captureRecord({
    src: "/learn/app/pyble-app-0.2.0-build-5-github-branch-chooser-f0c52c24bc5b.png",
    alt: "PyBLE 0.2.0 beta on a Lenovo Android tablet showing the editable official GitHub URL and branches-only main chooser without the keyboard.",
    caption: "GitHub import · editable URL and branches-only discovery",
    width: 2000,
    height: 1092,
    rawCapture: "16-github-branch-chooser-generic-s3-clean.raw.png",
    depictedState:
      "Official public repository URL, open main-default branch chooser, /examples board folder, and no software keyboard.",
    processing: fullFrameProcessing,
    sha256: "f0c52c24bc5be7412d5e62e2cdbd2708037ed538949c543d121d31aaae5810d7",
  }),
  githubPinnedSource: captureRecord({
    src: "/learn/app/pyble-app-0.2.0-build-5-github-pinned-source-68a784c12ada.png",
    alt: "PyBLE 0.2.0 beta on a Lenovo Android tablet showing the full immutable examples commit and selected Hello Console source.",
    caption: "GitHub import · full pinned commit and selected source",
    width: 2000,
    height: 1092,
    rawCapture: "12-github-pinned-source-generic-s3.raw.png",
    depictedState:
      "Full 40-character commit shown in the ref field and pinned-commit line with one selected public Python source.",
    processing: fullFrameProcessing,
    sha256: "68a784c12ada7ae3690e7268cf8b724268ecd81e024c0d92e20ad7870329e372",
  }),
  githubTargetReview: captureRecord({
    src: "/learn/app/pyble-app-0.2.0-build-5-github-target-review-16aafa28be77.png",
    alt: "PyBLE 0.2.0 beta on a Lenovo Android tablet showing the exact public source and /examples board target before download.",
    caption: "GitHub import · exact source and target before write",
    width: 2000,
    height: 1092,
    rawCapture: "11-github-target-review-generic-s3.raw.png",
    depictedState:
      "Pre-write review mapping pyble_hello_console.py to /examples/pyble_hello_console.py and stating that downloads are not opened or run automatically.",
    processing: fullFrameProcessing,
    sha256: "16aafa28be77af34696eb61882610a02aa3f8943f5c130de40801b8112b26118",
  }),
  examplesImportComplete: captureRecord({
    src: "/learn/app/pyble-app-0.2.0-build-5-examples-import-complete-65fc3f839336.png",
    alt: "PyBLE 0.2.0 beta on a Lenovo Android tablet showing one completed Hello Console import to board DA86 without opening or running it.",
    caption: "Examples · one completed import with execution still explicit",
    width: 2000,
    height: 1092,
    rawCapture: "14-examples-import-waveshare.raw.png",
    depictedState:
      "One file downloaded to /examples/pyble_hello_console.py on board DA86; the result explicitly says it was not opened or run automatically.",
    processing: fullFrameProcessing,
    sha256: "65fc3f8393366948ee56d183b5ecfdbaf5550a6339e6519c31d0bb6d0ebc8b32",
  }),
  blocksHelloWorkspace: captureRecord({
    src: "/learn/app/pyble-app-0.2.0-build-5-blocks-hello-workspace-adc069d73fba.png",
    alt: "PyBLE 0.2.0 beta on a Lenovo Android tablet showing the Hello PyBLE Blocks workspace and generated Python while board C81A is Ready and Idle.",
    caption: "Blocks · editable Hello workspace · not saved or run",
    width: 2000,
    height: 1092,
    rawCapture: "13-blocks-hello-c3-idle.raw.png",
    depictedState:
      "Ready board C81A, editable Hello PyBLE block, generated Python, and Idle Console before Save or Run.",
    processing: fullFrameProcessing,
    sha256: "adc069d73fbaab648f2e6b55dc536b38dade609c31aa03f18eb528a634a02f76",
  }),
} satisfies Record<string, TutorialAppCaptureRecord>;

export type TutorialAppCaptureId = keyof typeof tutorialAppCaptures;

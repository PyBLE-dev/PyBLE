// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

import Image from "next/image";

import { tutorialAppCaptures } from "@/lib/tutorial-app-captures";

type BoardIdentityCaptureId =
  | "identity5646Ready"
  | "identity5646Chip"
  | "identity8c9eReady"
  | "identity8c9eChip"
  | "identityc81aReady"
  | "identityc81aChip"
  | "identityda86Ready"
  | "identityda86Chip"
  | "identity3dcbReady"
  | "identity3dcbChip";

export type TutorialBoardIdentityKey =
  "genericS3" | "classicEsp32" | "esp32C3" | "waveshareLcd147b" | "pico2W";

type TutorialBoardIdentity = {
  boardId: string;
  context: string;
  runtimeChip: string;
  readyCapture: BoardIdentityCaptureId;
  chipCapture: BoardIdentityCaptureId;
  boundary: string;
};

export const tutorialBoardIdentities = {
  genericS3: {
    boardId: "5646",
    context: "Generic ESP32-S3 · N16R8",
    runtimeChip: "esp32-s3",
    readyCapture: "identity5646Ready",
    chipCapture: "identity5646Chip",
    boundary:
      "Maintained physical-session record: generic ESP32-S3. The shared runtime token does not identify a carrier or provisioning profile.",
  },
  classicEsp32: {
    boardId: "8C9E",
    context: "Generic ESP32 · 4 MiB",
    runtimeChip: "esp32",
    readyCapture: "identity8c9eReady",
    chipCapture: "identity8c9eChip",
    boundary:
      "Maintained physical-session record: classic ESP32. The app observation does not prove flash capacity or a carrier pinout.",
  },
  esp32C3: {
    boardId: "C81A",
    context: "Generic ESP32-C3 · 4 MiB",
    runtimeChip: "esp32-c3",
    readyCapture: "identityc81aReady",
    chipCapture: "identityc81aChip",
    boundary:
      "Maintained physical-session record: ESP32-C3. Revision, flash capacity, and pin choices still come from the physical board record and exact documentation.",
  },
  waveshareLcd147b: {
    boardId: "DA86",
    context: "Waveshare ESP32-S3-LCD-1.47B",
    runtimeChip: "esp32-s3",
    readyCapture: "identityda86Ready",
    chipCapture: "identityda86Chip",
    boundary:
      "Maintained physical-session record: exact Waveshare B-version. Its esp32-s3 token alone does not prove this carrier or its firmware profile.",
  },
  pico2W: {
    boardId: "3DCB",
    context: "Raspberry Pi Pico 2 W",
    runtimeChip: "rpi-pico2-w",
    readyCapture: "identity3dcbReady",
    chipCapture: "identity3dcbChip",
    boundary:
      "Maintained physical-session record: exact Pico 2 W. Keep the physical marking and UF2 installer record as the profile evidence.",
  },
} as const satisfies Record<TutorialBoardIdentityKey, TutorialBoardIdentity>;

export const allTutorialBoardIdentityKeys = [
  "genericS3",
  "classicEsp32",
  "esp32C3",
  "waveshareLcd147b",
  "pico2W",
] as const satisfies readonly TutorialBoardIdentityKey[];

function captureRecord(capture: BoardIdentityCaptureId) {
  return tutorialAppCaptures[capture];
}

export function TutorialBoardIdentityGallery({
  boards,
  title,
  introduction,
  caption,
}: {
  boards: readonly TutorialBoardIdentityKey[];
  title: string;
  introduction: string;
  caption: string;
}) {
  return (
    <figure className="tutorial-identity-gallery">
      <header className="tutorial-identity-gallery__heading">
        <span>Observed BLE identity</span>
        <h3>{title}</h3>
        <p>{introduction}</p>
      </header>
      <ul
        className="tutorial-identity-gallery__grid"
        data-board-count={boards.length}
      >
        {boards.map((board) => {
          const identity = tutorialBoardIdentities[board];
          const readyCapture = captureRecord(identity.readyCapture);
          const chipCapture = captureRecord(identity.chipCapture);

          return (
            <li key={identity.boardId}>
              <article className="tutorial-identity-card">
                <header>
                  <span className="tutorial-identity-card__id">
                    PyBLE-{identity.boardId}
                  </span>
                  <h4>{identity.context}</h4>
                </header>
                <div className="tutorial-identity-card__capture tutorial-identity-card__capture--ready">
                  <span>Ready observation</span>
                  <Image
                    src={readyCapture.src}
                    alt={readyCapture.alt}
                    width={readyCapture.width}
                    height={readyCapture.height}
                    sizes="(max-width: 680px) calc(100vw - 92px), 400px"
                    loading="lazy"
                    unoptimized
                  />
                </div>
                <div className="tutorial-identity-card__capture tutorial-identity-card__capture--chip">
                  <span>
                    Runtime token · <code>{identity.runtimeChip}</code>
                  </span>
                  <Image
                    src={chipCapture.src}
                    alt={chipCapture.alt}
                    width={chipCapture.width}
                    height={chipCapture.height}
                    sizes="(max-width: 680px) calc(100vw - 92px), 360px"
                    loading="lazy"
                    unoptimized
                  />
                </div>
                <p>{identity.boundary}</p>
              </article>
            </li>
          );
        })}
      </ul>
      <figcaption>
        <span className="tutorial-identity-gallery__evidence">
          <i aria-hidden="true" />
          Actual Android tablet · Lenovo TB-J616X
        </span>
        <span>{caption}</span>
      </figcaption>
    </figure>
  );
}

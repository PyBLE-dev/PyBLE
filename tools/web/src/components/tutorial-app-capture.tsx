// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

import Image from "next/image";

import {
  tutorialAppCaptures,
  type TutorialAppCaptureId,
} from "@/lib/tutorial-app-captures";

export function TutorialAppCapture({
  capture,
}: {
  capture: TutorialAppCaptureId;
}) {
  const record = tutorialAppCaptures[capture];

  return (
    <figure className="tutorial-app-capture">
      <div className="tutorial-app-capture__frame">
        <Image
          className="tutorial-app-capture__image"
          src={record.src}
          alt={record.alt}
          width={record.width}
          height={record.height}
          sizes="(max-width: 640px) calc(100vw - 76px), (max-width: 880px) calc(100vw - 146px), 720px"
          loading="lazy"
          unoptimized
        />
      </div>
      <figcaption>
        <span className="tutorial-app-capture__evidence">
          <i aria-hidden="true" />
          Actual Android tablet · Lenovo TB-J616X
        </span>
        <span>{record.caption}</span>
      </figcaption>
    </figure>
  );
}

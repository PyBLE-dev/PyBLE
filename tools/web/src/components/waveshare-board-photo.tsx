// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

import Image from "next/image";
import Link from "next/link";

import { ArrowIcon } from "@/components/icons";

const photoAlt =
  "Actual Waveshare ESP32-S3-LCD-1.47B displaying the PyBLE v0.5.0 boot splash and app QR";

interface WaveshareBoardPhotoProps {
  showInstallerLink?: boolean;
}

export function WaveshareBoardPhoto({
  showInstallerLink = false,
}: WaveshareBoardPhotoProps) {
  return (
    <figure className="waveshare-board-photo">
      <div className="waveshare-board-photo__media">
        <Image
          className="waveshare-board-photo__image"
          src="/boards/esp32-s3-lcd-1.47b-pyble-v0.5.0.jpg"
          alt={photoAlt}
          width={1600}
          height={1116}
          sizes="(max-width: 680px) calc(100vw - 28px), (max-width: 880px) calc(100vw - 36px), 920px"
          unoptimized
        />
        <span className="waveshare-board-photo__badge">
          <i aria-hidden="true" />
          Real hardware
        </span>
      </div>
      <figcaption>
        <span className="waveshare-board-photo__copy">
          <strong>Actual board · PyBLE firmware v0.5.0</strong>
          <span>
            Opt-in boot splash and app QR on the B-version 172 × 320 display.
          </span>
        </span>
        {showInstallerLink ? (
          <Link className="text-link" href="/flash">
            Open this board&apos;s installer
            <ArrowIcon />
          </Link>
        ) : null}
      </figcaption>
    </figure>
  );
}

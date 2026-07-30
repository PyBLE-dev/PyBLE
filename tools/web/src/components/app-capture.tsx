// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

import Image from "next/image";

const captureAlt =
  "Actual PyBLE app showing a GPIO 48 NeoPixel Blocks program beside its generated Python";

export function AppCapture() {
  return (
    <figure className="app-capture">
      <div className="app-capture__frame">
        <div className="app-capture__screen">
          <Image
            className="app-capture__image"
            src="/app/pyble-neopixel-gpio48-ipad-raw.png"
            alt={captureAlt}
            width={2048}
            height={2732}
            sizes="(max-width: 880px) calc(100vw - 36px), (max-width: 1200px) 52vw, 625px"
            preload
            unoptimized
          />
        </div>
      </div>
      <figcaption>
        <span className="app-capture__live">
          <i aria-hidden="true" />
          Actual PyBLE app
        </span>
        <span>NeoPixel Blocks · GPIO 48 · Generated Python</span>
      </figcaption>
    </figure>
  );
}

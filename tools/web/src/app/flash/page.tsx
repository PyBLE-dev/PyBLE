// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

import { ExternalIcon } from "@/components/icons";
import { FlashStatus } from "@/components/flash-status";
import { PageIntro } from "@/components/page-intro";
import { WaveshareBoardPhoto } from "@/components/waveshare-board-photo";
import { releaseIncludesWaveshareLcd147b } from "@/lib/firmware-release";
import {
  firmwareReleaseSelectedAtBuild,
  localFirmwarePreviewSelectedAtBuild,
} from "@/lib/firmware-release-selection";
import { pageMetadata } from "@/lib/site";

export const metadata = pageMetadata({
  title: "Firmware installer",
  description:
    "Release status and provisioning requirements for five PyBLE firmware targets across ESP32 and Raspberry Pi Pico 2 W.",
  path: "/flash",
});

export default function FlashPage() {
  const preview = localFirmwarePreviewSelectedAtBuild();
  const release = preview ? null : firmwareReleaseSelectedAtBuild();
  const publicBeta = release?.deployment === "public-beta";
  const waveshareLcd147b = releaseIncludesWaveshareLcd147b(release);
  const showWaveshareBoard =
    waveshareLcd147b ||
    preview?.profiles.some(
      (profile) => profile.id === "waveshare-esp32-s3-lcd-147b",
    );
  const qualifiedPublic = release !== null && waveshareLcd147b;

  return (
    <main id="main-content">
      <PageIntro eyebrow="One-time provisioning" title="Firmware installer">
        <p>
          One-time wired provisioning installs PyBLE-enabled MicroPython. Then
          develop over Bluetooth Low Energy from the tablet-first PyBLE app.
          {preview
            ? ` LOCAL ENGINEERING PREVIEW v${preview.version} — UNQUALIFIED. This is not a public release.`
            : publicBeta
              ? " The current v0.4.2 installer is a hardware-tested firmware beta. Production Chrome erase/install and deliberately interrupted-flash recovery passed on both exact profiles. Complete release qualification is still pending; this is not a qualified release."
              : qualifiedPublic
                ? ` Qualified v${release.version} firmware is available for all three exact release profiles.`
                : " The public install action remains unavailable until the final v0.6.0-derived bytes pass hardware validation on every included profile."}
        </p>
      </PageIntro>

      <section className="section">
        <div className="container flash-layout">
          <FlashStatus preview={preview} release={release} />

          <div className="flash-explainer">
            <section aria-labelledby="why-wired">
              <p className="eyebrow">Why a cable here?</p>
              <h2 id="why-wired">Provision over USB. Develop over BLE.</h2>
              <p>
                A board needs the PyBLE-enabled MicroPython firmware before it
                can advertise PBLE/1. The wired step establishes that
                foundation. Afterward, the PyBLE app connects, transfers files,
                runs code, and streams the console over Bluetooth Low Energy.
              </p>
            </section>

            <section aria-labelledby="requirements">
              <h2 id="requirements">Choose the exact module profile</h2>
              <ul className="requirement-list">
                <li>
                  <strong>esp32-4mb</strong>
                  <span>
                    Classical ESP32 module with 4 MiB flash; no PSRAM required.
                  </span>
                </li>
                <li>
                  <strong>esp32-s3-n16r8</strong>
                  <span>
                    ESP32-S3 module with 16 MiB flash and 8 MiB Octal PSRAM.
                    This lean, board-neutral image is not for every ESP32-S3
                    board. It does not bundle <code>pyble_st7789</code>,{" "}
                    <code>pyble_waveshare_lcd147b</code>, exact-board pins, or
                    the display boot splash.
                  </span>
                </li>
                {showWaveshareBoard ? (
                  <li>
                    <strong>waveshare-esp32-s3-lcd-147b</strong>
                    <span>
                      Exact ESP32-S3-LCD-1.47B B version with 16 MiB flash and 8
                      MiB Octal PSRAM. This separate image bundles its display
                      runtime and fresh-install splash support.
                    </span>
                  </li>
                ) : null}
              </ul>
            </section>

            {showWaveshareBoard ? (
              <section aria-labelledby="waveshare-lcd147b">
                <p className="eyebrow">
                  {preview
                    ? "Exact-board reference"
                    : "Validated display board"}
                </p>
                <h2 id="waveshare-lcd147b">Waveshare ESP32-S3-LCD-1.47B</h2>
                {preview ? (
                  <>
                    <p>
                      This reviewed photograph shows the exact B-version board
                      as recorded with PyBLE firmware v0.5.0. Use it to
                      distinguish the Waveshare profile from the lean generic
                      ESP32-S3 profile.
                    </p>
                    <p>
                      This is a historical identification reference. It does not
                      qualify the local v{preview.version} firmware bytes or
                      turn this engineering preview into a supported release.
                    </p>
                    <p>
                      Select <strong>waveshare-esp32-s3-lcd-147b</strong> only
                      for the exact B-version board with 16 MiB flash and 8 MiB
                      Octal PSRAM. Non-B display wiring differs.
                    </p>
                  </>
                ) : (
                  <>
                    <p>
                      This board uses the separate{" "}
                      <strong>waveshare-esp32-s3-lcd-147b</strong> image. Its
                      own manifest and immutable firmware bytes are never
                      aliased to the lean generic S3 image. It requires the
                      exact B-version board with 16 MiB flash and 8 MiB Octal
                      PSRAM.
                    </p>
                    <p>
                      The lean <strong>esp32-s3-n16r8</strong> image does not
                      bundle this board&apos;s display driver, companion module,
                      pin constants, boot hook, or splash machinery.
                    </p>
                    <p>
                      Use the <strong>B version</strong> shown here. Non-B
                      display wiring differs and is not covered by this
                      installer claim.
                    </p>
                  </>
                )}
                <WaveshareBoardPhoto />
                {!preview ? (
                  <>
                    <ul className="requirement-list">
                      <li>
                        <strong>Integrated display</strong>
                        <span>
                          172 × 320 ST7789V3 TFT with the board&apos;s published
                          SPI wiring.
                        </span>
                      </li>
                      <li>
                        <strong>Explicit MicroPython runtime</strong>
                        <span>
                          Firmware includes the inert <code>pyble_st7789</code>{" "}
                          user library and <code>pyble_waveshare_lcd147b</code>{" "}
                          companion for ordinary Python and Blocky TFT programs.
                        </span>
                      </li>
                      <li>
                        <strong>Fresh-install boot splash</strong>
                        <span>
                          After a fresh erased installation, the PyBLE/app-QR
                          boot splash is shown by default. You can persistently
                          disable or re-enable it; it never detects or selects
                          the board automatically.
                        </span>
                      </li>
                    </ul>
                    <p>
                      In the installer, select{" "}
                      <strong>waveshare-esp32-s3-lcd-147b</strong>, confirm the
                      exact B-version board and N16R8 memory topology, and
                      verify that profile&apos;s own release bytes. Use the same
                      BOOT/RESET recovery sequence documented below if automatic
                      reset does not enter the ROM loader.
                    </p>
                  </>
                ) : null}
              </section>
            ) : null}

            {preview ? (
              <section aria-labelledby="preview-methods">
                <h2 id="preview-methods">Two provisioning methods</h2>
                <ul className="requirement-list">
                  <li>
                    <strong>ESP Web Tools · Web Serial</strong>
                    <span>
                      Direct local browser installation for the four exact ESP
                      profiles after manifest and firmware verification.
                    </span>
                  </li>
                  <li>
                    <strong>Pico 2 W · BOOTSEL / UF2</strong>
                    <span>
                      Verify and download the UF2, then copy it to the mounted
                      RP2350 BOOTSEL volume. This is not an ESP Web Tools flow.
                    </span>
                  </li>
                </ul>
              </section>
            ) : (
              <section aria-labelledby="planned-profile">
                <h2 id="planned-profile">Planned profiles</h2>
                <ul className="requirement-list planned-profile-list">
                  <li className="planned-profile-card" aria-disabled="true">
                    <strong>esp32-c3-4mb</strong>
                    <span>
                      <b>Unavailable.</b> Exact-profile real-hardware validation
                      is pending for ESP32-C3 revision v0.3 or newer with 4 MiB
                      flash. No installer selection, firmware image, or recovery
                      command is offered yet.
                    </span>
                  </li>
                  <li className="planned-profile-card" aria-disabled="true">
                    <strong>rpi-pico2-w</strong>
                    <span>
                      <b>Unavailable.</b> The Pico 2 W port remains pre-GP2; no
                      public UF2 download or installer action is offered yet.
                    </span>
                  </li>
                </ul>
              </section>
            )}

            <section aria-labelledby="installer-requirements">
              <h2 id="installer-requirements">Before you connect</h2>
              {preview ? (
                <ul className="requirement-list">
                  <li>
                    <strong>Loopback Chromium + Web Crypto</strong>
                    <span>
                      Open this approval harness only at localhost. Every
                      artifact is size- and SHA-256-verified before an action is
                      shown.
                    </span>
                  </li>
                  <li>
                    <strong>ESP targets use Web Serial</strong>
                    <span>
                      Use a data-capable cable, stable power, and close every
                      serial monitor before installing one of the four ESP
                      profiles.
                    </span>
                  </li>
                  <li>
                    <strong>Pico 2 W does not use Web Serial</strong>
                    <span>
                      Its action downloads verified in-memory UF2 bytes for a
                      manual BOOTSEL-volume copy. Back up board files first.
                    </span>
                  </li>
                </ul>
              ) : (
                <ul className="requirement-list">
                  <li>
                    <strong>Desktop Chromium over HTTPS</strong>
                    <span>
                      The installer uses Web Serial and Web Crypto. iPadOS
                      cannot perform this wired provisioning step.
                    </span>
                  </li>
                  <li>
                    <strong>Data-capable USB and stable power</strong>
                    <span>
                      Back up board files, close other serial tools, and expect
                      the installation to erase the device.
                    </span>
                  </li>
                </ul>
              )}
            </section>

            <div className="installer-links">
              {publicBeta ? (
                <a
                  className="text-link"
                  href="https://github.com/PyBLE-dev/PyBLE/releases/tag/firmware-v0.4.2"
                  target="_blank"
                  rel="noreferrer"
                >
                  Release evidence and exact hashes
                  <ExternalIcon />
                </a>
              ) : null}
              <a
                className="text-link"
                href="https://esphome.github.io/esp-web-tools/"
                target="_blank"
                rel="noreferrer"
              >
                Learn about ESP Web Tools
                <ExternalIcon />
              </a>
              <a className="text-link" href="/WEBSITE_THIRD_PARTY_LICENSES.txt">
                Website third-party notices
              </a>
            </div>
            <p className="fine-print">
              ESP Web Tools is licensed under Apache-2.0 and is loaded from the
              exact package bundled with this website—never from a runtime CDN.
            </p>
          </div>
        </div>
      </section>

      <section className="section section--tint">
        <div className="container safety-note">
          <div>
            <p className="eyebrow">Recovery</p>
            <h2>Recover an interrupted flash</h2>
          </div>
          {preview ? (
            <div className="flash-explainer">
              <p>
                <strong>ESP recovery:</strong> reconnect the exact selected ESP
                board, close serial monitors, enter its ROM bootloader with the
                board-specific BOOT/RESET sequence if automatic reset fails,
                then verify and retry that same profile.
              </p>
              <p>
                <strong>Pico 2 W recovery:</strong> reconnect while holding
                BOOTSEL, wait for the RP2350 volume, then copy the same verified
                UF2 again. Pico provisioning does not use Web Serial or ESP ROM
                recovery controls.
              </p>
              <p>
                After either method, wait for reboot and confirm the expected
                PyBLE BLE advertisement. A successful local operation remains
                engineering evidence, not public qualification.
              </p>
            </div>
          ) : (
            <div className="flash-explainer">
              <p>
                Installing PyBLE erases the board&apos;s existing firmware and
                user workspace. Back up user files before installing. Use a
                normal USB connection with a data-capable cable and stable
                power, close every serial monitor or application holding the
                port, and select the correct serial port.
              </p>
              <p>
                Try automatic reset first. If it fails, use the manual
                BOOT/RESET sequence: hold BOOT, tap RESET, then release BOOT.
                Button labels vary by board.
              </p>
              <p>
                It is safe to retry after permission denial, disconnect,
                timeout, interrupted erase, interrupted write, verification
                failure, or when a board no longer boots. Close serial monitors,
                reconnect USB, manually enter the ROM bootloader, reload this
                page, and retry the same verified profile. The installer
                rechecks the reviewed SHA-256 metadata root and selected
                artifacts before it exposes the install action.
              </p>
              <p>
                For advanced merged-image recovery with the same version-matched
                bundle bytes, run the command for the exact selected profile:
              </p>
              <ul className="readiness-list">
                <li>
                  <code>
                    python -m esptool --chip esp32 write_flash 0x1000{" "}
                    <span>esp32-</span>
                    <span>4mb/firmware.bin</span>
                  </code>
                </li>
                <li>
                  <code>
                    python -m esptool --chip esp32s3 write_flash 0x0{" "}
                    <span>esp32-s3-</span>
                    <span>n16r8/firmware.bin</span>
                  </code>
                </li>
                {waveshareLcd147b ? (
                  <li>
                    <code>
                      python -m esptool --chip esp32s3 write_flash 0x0{" "}
                      <span>waveshare-esp32-s3-lcd-147b/</span>
                      <span>firmware.bin</span>
                    </code>
                  </li>
                ) : null}
              </ul>
              <p>
                As an advanced diagnostic or recovery alternative, the component
                offsets are: bootloader at 0x1000 for classic ESP32 or 0x0 for
                ESP32-S3, partition table at 0x8000, and application at 0x10000.
                Use only the component files from that same bundle.
              </p>
              <p>
                After flashing, perform a hard reset or power cycle. Expect the
                board to advertise as <code>PyBLE-XXXX</code>, then make the
                first connection from the PyBLE app.
              </p>
              <p>
                Repeated resets, flash-size or PSRAM startup errors, or no BLE
                advertisement can indicate a wrong memory profile. Stop instead
                of trying random images, then use the{" "}
                <a className="text-link" href="/support">
                  support route
                </a>
                . Safe diagnostic fields to share are the release version,
                profile ID, board model or module marking, browser/OS versions,
                failed stage, and redacted error text. Do not share secrets or
                personal device labels.
              </p>
            </div>
          )}
        </div>
      </section>
    </main>
  );
}

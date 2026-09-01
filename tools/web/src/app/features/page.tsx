// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

import Image from "next/image";
import Link from "next/link";

import { ArrowIcon, ExternalIcon } from "@/components/icons";
import { PageIntro } from "@/components/page-intro";
import { pageMetadata } from "@/lib/site";

export const metadata = pageMetadata({
  title: "PyBLE Firmware Architecture",
  description:
    "Explore the PBLE/1 functional architecture, complete operation surface, exact profiles, and operating limits of qualified PyBLE firmware 0.6.0.",
  path: "/features",
});

const diagramPath =
  "/features/pyble-firmware-v0.6.0-functional-block-diagram-473a85d475aa.svg";

const featureReference = [
  {
    title: "BLE transport",
    body: "One PyBLE-owned GATT service. RX accepts Write and Write Without Response; TX notifies; INFO is readable. The app prefers ATT MTU 247, while fragmentation and reassembly keep the transport valid down to MTU 23.",
  },
  {
    title: "Identity and capabilities",
    body: "HELLO comes first. DEVICE_INFO and INFO expose 15 emitted keys: proto, agent, chip, mpy, fs_root, mtu, window, chunk, free_mem, has_sd, has_identify, identify_led, auto_run, device_id, and label. Labels are at most 24 UTF-8 bytes.",
  },
  {
    title: "Safe boot and persistence",
    body: "The embedded agent starts independently of the editable workspace, advertises and waits by default, and runs /main.py only after autorun is enabled. A broken user file cannot prevent the agent from advertising at boot.",
  },
  {
    title: "Security and privacy",
    body: "PBLE/1 has no application-layer authentication: a connected client is trusted. Device identity and labels are display-only, an advertised label is public, and the PyBLE agent sends no telemetry or code to a cloud service.",
  },
  {
    title: "PBLE/1 protocol",
    body: "Version 1 frames carry a command, response, or event, a request ID, and CRC-32. The dispatcher returns explicit status values and keeps transport framing separate from filesystem, runner, console, and identity services.",
  },
  {
    title: "Files",
    body: "List, stat, offset download, CRC-verified windowed upload, cumulative acknowledgement, reconnect resume, delete files or empty directories, mkdir, and rename. One transfer is active at a time; paths are limited to 128 bytes; .mpy and .pyc transfers are rejected.",
  },
  {
    title: "Run and control",
    body: "Run one workspace path of at most 128 bytes or inline UTF-8 source of at most 2,048 bytes. Observe idle, running, done, or error state; Stop is idempotent; soft reboot responds before its side effect; /main.py autorun is opt-in.",
  },
  {
    title: "Live console",
    body: "Tagged stdout and stderr travel to the app, while stdin supports input() and sys.stdin. Output chunks are at most 200 bytes and input staging is 256 bytes. Congestion can drop output, so the console is live feedback rather than a lossless log.",
  },
  {
    title: "Lifecycle and reliability",
    body: "BLE remains serviceable while user code runs. Bounded queues plus connection-generation and virtual-machine-epoch binding prevent stale work from crossing disconnects or resets. Pico 2 W returns EBUSY for file transfer while a program runs.",
  },
  {
    title: "MicroPython runtime",
    body: "Upstream MicroPython 1.28.0 runs with zero PyBLE upstream patches. ESP uses FAT and includes upstream NeoPixel; Pico uses LFS2. Programs keep ordinary filesystem, machine, VFS, and asyncio APIs with explicit pins and buses—there is no automatic board or pin detection.",
  },
] as const;

const operationGroups = [
  {
    title: "Identity",
    operations: ["HELLO", "DEVICE_INFO"],
  },
  {
    title: "Files",
    operations: [
      "FILE_LIST",
      "FILE_STAT",
      "FILE_GET_BEGIN",
      "FILE_GET_DATA",
      "FILE_GET_END",
      "FILE_PUT_BEGIN",
      "FILE_PUT_DATA",
      "FILE_PUT_END",
      "FILE_DELETE",
      "MKDIR",
      "FILE_RENAME",
      "FILE_PUT_ACK",
    ],
  },
  {
    title: "Execution",
    operations: ["RUN", "STOP", "SOFT_REBOOT", "SET_AUTORUN", "RUN_STATE"],
  },
  {
    title: "Console",
    operations: ["CONSOLE_DATA", "CONSOLE_INPUT"],
  },
  {
    title: "Device controls",
    operations: ["SET_LABEL", "SET_IDENTIFY_LED", "IDENTIFY"],
  },
] as const;

const firmwareProfiles = [
  {
    id: "esp32-4mb",
    hardware: "Classic ESP32; exactly 4 MiB flash; no PSRAM required.",
    runtime: "Native C agent, NimBLE, FAT, upstream NeoPixel, upload window 8.",
    provisioning:
      "ESP Web Serial. HIL reference: ESP32 DevKitC / ESP32-WROOM-32.",
  },
  {
    id: "esp32-s3-n16r8",
    hardware: "ESP32-S3; exactly 16 MiB flash and 8 MiB Octal PSRAM.",
    runtime:
      "Lean, board-neutral N16R8 image; native C agent, NimBLE, FAT, upload window 8; no TFT or boot splash.",
    provisioning:
      "ESP Web Serial. HIL reference: ESP32-S3-DevKitC-1 / WROOM-1 N16R8.",
  },
  {
    id: "waveshare-esp32-s3-lcd-147b",
    hardware:
      "Exact ESP32-S3-LCD-1.47B B-version; 16 MiB flash and 8 MiB Octal PSRAM.",
    runtime:
      "Native C agent, NimBLE, FAT, upload window 8; pyble_st7789 runtime and fresh-install splash.",
    provisioning: "ESP Web Serial. HIL uses the exact Waveshare B-version.",
  },
  {
    id: "esp32-c3-4mb",
    hardware: "ESP32-C3 revision v0.3 or newer; exactly 4 MiB flash; no PSRAM.",
    runtime: "Native C agent, NimBLE, FAT, upstream NeoPixel, upload window 8.",
    provisioning: "ESP Web Serial. HIL reference: ESP32-C3-MINI-1-N4.",
  },
  {
    id: "rpi-pico2-w",
    hardware: "Exact Raspberry Pi Pico 2 W; RP2350 with CYW43439.",
    runtime:
      "Frozen-Python agent, BTstack, LFS2, upload window 4; named LED is available. Identify and NeoPixel are not claimed; transfer during RUN returns EBUSY.",
    provisioning: "Verified UF2 download followed by a manual BOOTSEL copy.",
  },
] as const;

export default function FeaturesPage() {
  return (
    <main id="main-content">
      <PageIntro
        eyebrow="Firmware 0.6.0 · PBLE/1"
        title="How PyBLE firmware works"
      >
        <p>
          A functional view of qualified PyBLE firmware 0.6.0—from the tablet
          app over Bluetooth Low Energy to the embedded agent and MicroPython
          runtime. This is a versioned reference, not a live installer promise,
          board drawing, or pinout.
        </p>
        <p className="page-intro__meta">
          Before provisioning,{" "}
          <Link href="/flash">check current firmware availability</Link> for the
          exact profile and active release selected today.
        </p>
      </PageIntro>

      <div className="features-page">
        <section
          className="container feature-diagram-section"
          aria-labelledby="functional-diagram-title"
        >
          <div className="section-heading">
            <p className="eyebrow">One control plane · five exact profiles</p>
            <h2 id="functional-diagram-title">Functional block diagram</h2>
            <p>
              Follow the app, BLE transport, protocol engine, agent services,
              and normal MicroPython runtime from left to right. On a small
              screen, scroll the diagram or open the full-size vector.
            </p>
          </div>

          <figure
            className="firmware-diagram"
            aria-labelledby="firmware-diagram-caption"
          >
            <div
              className="firmware-diagram__viewport"
              role="region"
              aria-label="Scrollable PyBLE firmware diagram"
              tabIndex={0}
            >
              <Image
                className="firmware-diagram__image"
                src={diagramPath}
                width={1920}
                height={1470}
                alt="Functional block diagram of PyBLE firmware 0.6.0, from the tablet app over BLE and PBLE/1 to files, execution, console, boot, and five qualified release profiles; it is not a board drawing, schematic, or pinout"
                priority
                unoptimized
              />
            </div>
            <figcaption id="firmware-diagram-caption">
              <p>
                Original PyBLE diagram for firmware 0.6.0. This is a protocol
                and runtime diagram—not a board drawing, automatic board
                detector, schematic, or pinout.
              </p>
              <a href={diagramPath} target="_blank" rel="noopener noreferrer">
                Open full-size SVG diagram (opens in a new tab)
                <ExternalIcon />
              </a>
            </figcaption>
          </figure>
        </section>

        <section
          className="section section--tint feature-description"
          aria-labelledby="diagram-description"
        >
          <div className="container feature-reading-width">
            <div className="section-heading">
              <p className="eyebrow">Accessible diagram equivalent</p>
              <h2 id="diagram-description">Diagram description</h2>
            </div>
            <div className="feature-description__body">
              <p>
                Read from left to right, the diagram begins with the PyBLE app
                on iPadOS or Android. After a separate one-time wired
                installation, the app discovers a board, reads its capabilities,
                manages files, runs and stops code, sends console input, and
                receives standard output and errors over Bluetooth Low Energy.
                ESP images use desktop Chromium and Web Serial; Pico 2 W uses a
                verified UF2 download and manual BOOTSEL copy. Installation
                replaces the existing firmware and workspace.
              </p>
              <p>
                Inside the qualified-device boundary, RX writes, TX
                notifications, and the readable INFO characteristic connect the
                app to the BLE GATT transport. Transport, identity, boot, and
                security modules feed the central PBLE/1 protocol engine. PBLE/1
                version 1 defines 24 opcodes for device information, files,
                execution, console, labels, autorun, and optional Identify
                control. Frames carry request IDs and CRC-32 checks.
              </p>
              <p>
                Below the engine, the filesystem bridge lists and inspects
                files, downloads from an offset, resumes windowed uploads,
                verifies CRC-32, and commits through a temporary{" "}
                <code>.pbltmp</code> sibling and rename. The run controller
                executes one file or inline source at a time and supports
                idempotent Stop and soft reboot. The console carries tagged
                standard output and error plus bounded standard input.
                Connection-generation and virtual-machine-epoch controls discard
                stale work after disconnects or resets.
              </p>
              <p>
                The agent runs beside a normal upstream MicroPython 1.28.0 user
                runtime with zero PyBLE patches to upstream MicroPython. User
                programs retain ordinary filesystem and machine APIs and must
                select pins and buses explicitly; PyBLE does not detect a
                carrier board or supply a pin map.
              </p>
              <p>
                The lower strip distinguishes five qualified firmware 0.6.0
                profiles. Four ESP profiles use the native C agent, NimBLE, FAT
                storage, upload window eight, and Web Serial. Pico 2 W uses the
                frozen-Python agent, BTstack, LFS2, upload window four, and
                manual UF2 provisioning. Memory alone does not identify a board,
                and matching N16R8 hardware does not make an arbitrary ESP32-S3
                board the Waveshare B version.
              </p>
            </div>
          </div>
        </section>

        <section
          className="section container feature-reference"
          aria-labelledby="complete-feature-reference"
        >
          <div className="section-heading">
            <p className="eyebrow">Complete release surface</p>
            <h2 id="complete-feature-reference">
              Complete PBLE/1 feature reference
            </h2>
            <p>
              These are firmware-agent capabilities. Hardware behavior still
              depends on the exact profile, board, wiring, and user program.
            </p>
          </div>

          <div className="feature-reference__grid">
            {featureReference.map((feature) => (
              <article key={feature.title}>
                <h3>{feature.title}</h3>
                <p>{feature.body}</p>
              </article>
            ))}
          </div>

          <section
            className="operation-surface"
            aria-labelledby="operation-surface-title"
          >
            <div>
              <p className="eyebrow">PBLE/1 version 1</p>
              <h3 id="operation-surface-title">All 24 operation identities</h3>
              <p>
                Events and no-response writes share these public identities;
                their direction and framing are defined by the protocol.
              </p>
            </div>
            <div className="operation-groups">
              {operationGroups.map((group) => (
                <section key={group.title} aria-label={group.title}>
                  <h4>{group.title}</h4>
                  <ul>
                    {group.operations.map((operation) => (
                      <li key={operation}>
                        <code>{operation}</code>
                      </li>
                    ))}
                  </ul>
                </section>
              ))}
            </div>
          </section>
        </section>

        <section
          className="section section--tint feature-profiles"
          aria-labelledby="qualified-profiles"
        >
          <div className="container">
            <div className="section-heading">
              <p className="eyebrow">Exact image constraints</p>
              <h2 id="qualified-profiles">Qualified firmware 0.6.0 profiles</h2>
              <p>
                All five exact-byte HIL rows passed. Profile constraints select
                firmware bytes; they do not visually identify a carrier board or
                promise a pin map.
              </p>
            </div>

            <div
              className="feature-table-scroll"
              role="region"
              aria-label="Scrollable qualified profile table"
              tabIndex={0}
            >
              <table className="feature-profile-table">
                <caption>
                  Five qualified release profiles in firmware 0.6.0. Reference
                  HIL hardware is evidence, not visual board detection or an
                  exhaustive carrier-board allowlist.
                </caption>
                <thead>
                  <tr>
                    <th scope="col">Profile</th>
                    <th scope="col">Exact hardware constraint</th>
                    <th scope="col">Agent and runtime</th>
                    <th scope="col">Provisioning and HIL reference</th>
                  </tr>
                </thead>
                <tbody>
                  {firmwareProfiles.map((profile) => (
                    <tr key={profile.id}>
                      <th scope="row">
                        <code>{profile.id}</code>
                      </th>
                      <td>{profile.hardware}</td>
                      <td>{profile.runtime}</td>
                      <td>{profile.provisioning}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </section>

        <section
          className="section feature-limits"
          aria-labelledby="firmware-limits"
        >
          <div className="container feature-limits__grid">
            <div>
              <p className="eyebrow">Limits and safe use</p>
              <h2 id="firmware-limits">Know the boundaries.</h2>
            </div>
            <div className="feature-limits__copy">
              <p>
                Install only the exact matching profile: provisioning replaces
                installed firmware and user files. A matching chip family does
                not prove flash size, PSRAM type, silicon revision, or board
                wiring.
              </p>
              <p>
                PBLE/1 trusts the connected client, so use it only where nearby
                BLE clients are trusted. The advertised label is public. This
                release reports no SD card, allows one program and one active
                transfer class, does not recursively delete folders, and rejects
                compiled <code>.mpy</code> and <code>.pyc</code> transfers.
              </p>
              <p>
                User code can defeat remote Stop by calling{" "}
                <code>micropython.kbd_intr(-1)</code>. Console output may be
                dropped during sustained congestion. The PBLE/1 workspace jail
                protects the agent from PBLE/1 file commands; user MicroPython
                code retains ordinary <code>os</code> and VFS access.
              </p>
            </div>
          </div>
        </section>

        <section
          className="section feature-evidence"
          aria-labelledby="feature-evidence-title"
        >
          <div className="container feature-evidence__card">
            <div>
              <p className="eyebrow eyebrow--light">Versioned evidence</p>
              <h2 id="feature-evidence-title">
                Inspect the release, then put it to work.
              </h2>
              <p>
                This reference is bound to firmware 0.6.0. The installer page
                remains authoritative for what is active now.
              </p>
              <div className="button-row">
                <Link className="button button--primary" href="/flash">
                  Check current firmware availability
                  <ArrowIcon />
                </Link>
                <Link className="button button--ghost" href="/learn">
                  Start the guided tutorials
                </Link>
              </div>
            </div>
            <nav
              className="feature-evidence__links"
              aria-label="Release evidence"
            >
              <a href="/firmware/v0.6.0/release.json">
                <span>Machine-readable evidence</span>
                Release descriptor
              </a>
              <a
                href="https://github.com/PyBLE-dev/PyBLE/releases/tag/firmware-v0.6.0"
                target="_blank"
                rel="noopener noreferrer"
              >
                <span>Immutable source</span>
                Firmware v0.6.0 source tag
              </a>
              <a
                href="https://github.com/PyBLE-dev/PyBLE/blob/firmware-v0.6.0/docs/specifications/protocol.md"
                target="_blank"
                rel="noopener noreferrer"
              >
                <span>Open wire contract</span>
                PBLE/1 specification
              </a>
            </nav>
          </div>
        </section>
      </div>
    </main>
  );
}

# PyBLE — Hardware Support & Pin Guidance

Status: **DRAFT** · Last updated: 2026-08-12

PyBLE's platform scope is any microcontroller board that can run MicroPython
and provide a Bluetooth Low Energy peripheral stack capable of hosting a
conforming PBLE/1 agent. Its general connection/user-code model makes no
assumptions about wiring and carries no generalized board routing profile. The
narrow ADR-0024 exact-board cosmetic companion, as amended by ADR-0029, is
factory-enabled after an erased exact-board install and persistently
disableable. Under ADR-0028 it exists only in its explicitly selected
exact-board provisioning-image contract; it changes neither model and this
documentation does not itself qualify public bytes. Hardware eligibility is
broader than current support. A qualified port must pass its complete protocol,
resource, recovery, and hardware-in-the-loop gates; a narrower beta must name
the exact evidence it has passed and the qualification that remains open.

Classic ESP32, ESP32-S3, and ESP32-C3 are the **initial v1 reference target
families**, not the permanent product boundary. A public browser image is
narrower than a target family and is supported only for an exact listed memory
profile and its stated release status. Their firmware exposes hardware through
standard runtime APIs, including `machine` and the frozen upstream `neopixel`
package. The exact Waveshare image alone carries the explicit
`pyble_st7789` user-runtime and exact-board companion described below. The lean
S3 image carries neither, so adding future S3 boards does not accumulate their
drivers in a family image. The app may ship read-only target guidance and
manually selected examples to help users avoid common footguns.

## 1. Supported chip families (v1)

| Family | IDF target | Cores | RAM (typical) | BLE | Notes |
|---|---|---|---|---|---|
| Classic **ESP32** | `esp32` | 2 (Xtensa) | ~520 KB SRAM | NimBLE | The conservative baseline; tightest heap for the agent. |
| **ESP32-S3** | `esp32s3` | 2 (Xtensa) | ~512 KB SRAM (+PSRAM common) | NimBLE | Most headroom; native USB. |
| **ESP32-C3** | `esp32c3` | 1 (RISC-V) | ~400 KB SRAM | NimBLE | Smallest footprint — the constraint to validate early. |

These are the targets for the initial firmware. A board still needs an exact
matching image and flash layout. ESP32-C6/H2 and
non-Espressif MicroPython targets are candidates for later conforming ports
under the same PBLE/1 protocol.

### 1.1 Browser-provisioning release profiles

| Image profile | Required memory configuration | Provisioning check/action | Release status | Public compatibility claim |
|---|---|---|---|---|
| `esp32-4mb` | Classic ESP32; 4 MiB external SPI flash; no PSRAM assumed | `ESP32` | v0.4.2 hardware-tested beta; browser install/recovery passed; qualification pending. Current v0.6.0 source requires fresh exact-byte qualification. | Only boards whose module documentation confirms this flash layout |
| `esp32-s3-n16r8` | ESP32-S3; 16 MiB flash; 8 MiB Octal PSRAM; lean board-neutral payload | `ESP32-S3` | v0.4.2 hardware-tested beta; browser install/recovery passed; qualification pending. Current v0.6.0 source requires independent exact-byte qualification. | N16R8-class modules only; no bundled TFT driver or splash |
| `waveshare-esp32-s3-lcd-147b` | Exact Waveshare ESP32-S3-LCD-1.47B; 16 MiB flash; 8 MiB Octal PSRAM | ESP Web Serial · `ESP32-S3` | Selected for v0.6.0; exact-board qualification pending | B-version board only after the full candidate passes; exact image bundles the ST7789 runtime and fresh-install QR splash |
| `esp32-c3-4mb` | ESP32-C3 revision v0.3 or newer; 4 MiB addressable flash; no PSRAM assumed | ESP Web Serial · `ESP32-C3` | Selected for v0.6.0; C3-G0…C3-G6 and common qualification pending | Exact generic profile after the full candidate passes |
| `rpi-pico2-w` | Raspberry Pi Pico 2 W; RP2350 + CYW43439 | Browser-verified `firmware.uf2`; manual BOOTSEL copy | Selected for v0.6.0; GP2 and common qualification pending | Exact Pico 2 W profile after the full candidate passes |

The installer family check cannot establish flash capacity, PSRAM type, USB
wiring, or power integrity. The user therefore selects and confirms the exact
profile before flashing, and each release names the physical reference board
and module marking that passed HIL. Unknown ESP32-S3 variants, including a
different flash size or Quad/no PSRAM, are not covered by
`esp32-s3-n16r8`; they require another profile and its own HIL evidence.
Matching the N16R8 memory tuple also does not imply that an onboard display or
other peripheral exists. The Waveshare row is separate even though ESP Web
Tools reports the same family for both S3 images and cannot distinguish them.
The C3 and Pico profiles remain inactive while their status is pending; owning
or building either target is not a substitute for HIL. The
ESP32-C3-MINI-1-N4 v0.4/4 MiB/no-PSRAM module is the selected physical
engineering reference for that generic profile, with all gates still pending
under [its derived qualification contract](firmware/ports/esp32-c3-4mb.md).
The carrier's reported GPIO8 NeoPixel is an operator-supplied test input only,
not a generic pin promise or board-routing profile. The
immutable v0.4.2 machine-readable resource policy and HIL ledger contain
exactly the first two profile IDs and no C3 thresholds or record. The
[supplemental production-browser attestation](../validation/browser-flashing/v0.4.2-production.md)
records the two completed browser rows; the ledger's other formal rows remain
pending. The unfinished v0.5.1 candidate policy/HIL work is historical and
cannot qualify the source-selected v0.6.0 tree. ADR-0033 selects one atomic
five-profile v0.6.0 candidate; it MUST generate fresh schema-3 resource policy
and V5 HIL evidence for every row. Pre-split or earlier-candidate evidence
cannot qualify it. C3-G0…C3-G6 and Pico GP2 remain mandatory, and either
pending/failed profile blocks the whole qualified release.

These are **provisioning image profiles**, not board-routing profiles. They
exist solely to keep destructive flash layouts honest. They do not define GPIO
roles, mediate user code, change PBLE/1 discovery, or make the app gate a
runtime connection by chip. Exact offsets, integrity, recovery, and release
qualification live in
[firmware/browser-flashing.md](firmware/browser-flashing.md).

### 1.2 Waveshare ESP32-S3-LCD-1.47B qualification contract

The exact **B** board uses the separate
`waveshare-esp32-s3-lcd-147b` provisioning image. It shares the generic
profile's flash/PSRAM layout and ESP Web Tools family, but its firmware bytes,
manifest, compatibility consent, release record, and HIL evidence are
independent. The local schematic is byte-identical to Waveshare's official
schematic (SHA-256
`43738d1480ef9c983bca3e7f1f7ad852c288a1bd00f1621f9ac3e6974e7539fd`),
and connected-hardware discovery must independently prove ESP32-S3, 16 MiB
flash, and 8 MiB PSRAM before a destructive write.

| Function | Exact B-board contract |
|---|---|
| Panel | ST7789V3, 172 × 320 visible pixels, write-only 4-line SPI, X offset 34, Y offset 0 |
| LCD SPI | MicroPython `machine.SPI(1)` at 40 MHz mode 0; MOSI GPIO45, SCLK GPIO40, CS GPIO42 active-low, D/C GPIO41 |
| Control | Reset GPIO39 active-low; backlight GPIO46 active-high through the onboard transistor |
| Other onboard parts | WS2812 GPIO38; QMI8658 I2C SCL47/SDA48; these are not initialized by TFT support |

GPIO45 and GPIO46 are ESP32-S3 strapping pins. Importing `pyble_st7789` never
drives them. The exact-board image's sole automatic exception is the bounded
ADR-0024/ADR-0029 splash: after a fresh erased installation, and only after BLE
is actually ready, its `_boot.py` may invoke the named companion to
render one bounded frame, release SPI/framebuffer, and assert the backlight.
The lean `esp32-s3-n16r8` image contains no driver, companion, hook, QR matrix,
or splash-only native readiness API, so even a stale NVS key cannot make it
drive these pins. The similarly named non-B board uses a different backlight
pin, so instructions, the module name, profile ID, and examples MUST retain the
`B` suffix. Rotation, touch, SD, IMU, and battery support are not implied by
the display increment.

The bus identifier above is part of the exact-board HIL contract, not a hidden
driver default. Connected-hardware qualification proved `machine.SPI(1)` with
the documented pins. Constructing `machine.SPI(2)` reset the pinned ESP32-S3
runtime, so the named-board Blocky example and TFT HIL workload MUST use bus 1.
Other boards still supply their own explicit bus identifier.

### 1.3 Selected ports pending qualification

| Board / family | Upstream port · board | BLE stack | Status |
|---|---|---|---|
| Raspberry Pi **Pico 2 W** (RP2350 + CYW43439 radio) | `rp2` · `RPI_PICO2_W` | BTstack via MicroPython `bluetooth` | Selected for the v0.6.0 candidate by ADR-0033; GP2, schema-3 resource evidence, verified-UF2/BOOTSEL recovery, and V5 HIL all remain pending ([firmware/ports/rpi-pico2-w.md](firmware/ports/rpi-pico2-w.md)). It is not an active qualified target until all pass. |

A selected-pending row may appear in candidate metadata and a visibly
unqualified loopback preview, but never widens an active qualified selector or
support claim before its gates pass. The port's PBLE/1 `chip` token is
`rpi-pico2-w`; per §3, absent pin guidance MUST NOT block connection.

## 2. Requirements for a board to work with PyBLE

1. A maintained upstream MicroPython port for the target.
2. Bluetooth Low Energy hardware and a stack that can advertise and host the
   PBLE/1 GATT service as a peripheral.
3. Enough flash and RAM for MicroPython, the protected PyBLE agent, its
   filesystem/configuration storage, and usable headroom for user code.
4. A runtime mechanism that keeps BLE and authoritative `STOP` responsive while
   user code runs.
5. A target adapter/board overlay and versioned PyBLE firmware port that has
   passed protocol conformance and HIL validation.
6. That matching agent firmware installed through the target's documented
   provisioning path. The initial ESP32 release uses USB through
   `pyble.dev/flash` or a self-build; future ports may require another one-time
   provisioning tool while normal PyBLE use remains BLE-first. The Pico 2 W
   port-in-progress provisioning path is the RP2 UF2/BOOTSEL flow
   (drag-and-drop or picotool); normal use remains BLE-first.

No specific GPIO wiring is required — PyBLE is an IDE, not a board product. A board needs **no screen, no LED, and no buttons** to be fully usable; screenless identification is by advertised name (`PyBLE-XXXX`, or a user-set label) plus RSSI and the pre-connect INFO read. The **Identify** blink (`IDENTIFY`, `0x52`) is **best-effort and optional**: it works only if the user has configured a single status-LED GPIO (`SET_IDENTIFY_LED`, `0x51`); with no LED configured the board reports `has_identify = false` and `IDENTIFY` returns `EUNSUPPORTED` (`0x0A`). The app offers the Identify action only when `has_identify` is set.

## 3. Generic pin reference (shown in-app, read-only)

The app surfaces cautions only for targets with reviewed reference data.
Missing guidance for a new or unknown target MUST NOT block connection or imply
that every pin is safe; the app directs the user to that board's documentation.
For the initial **classic ESP32** target, highlights include:

| Pins | Caution |
|---|---|
| GPIO6–11 | Connected to internal SPI flash — **do not use**. |
| GPIO34–39 | **Input-only** (no output, no internal pull-ups). |
| GPIO0, 2, 12, 15 | **Strapping pins** — affect boot; use carefully. |
| ADC2 (GPIO0,2,4,12–15,25–27) | Unusable while Wi-Fi is active. |
| GPIO1/3 | Default UART0 (USB console) — avoid for I/O if you need the REPL. |

**ESP32-S3** and **ESP32-C3** have their own maps (different strapping pins,
fewer/more GPIOs, native-USB pins). Each reviewed target reference is a static
asset keyed by the port-defined `chip` reported in `DEVICE_INFO`. These are
**informational warnings**, not enforced restrictions — user code can do what
it likes; PyBLE just warns.

## 4. What PyBLE does NOT do with hardware

- It does **not** impose or store a generalized board routing profile. The
  exact Waveshare 1.47B companion exists only in that board's
  separately selected image and contains only its published display wiring for
  its own cosmetic app-discovery frame; it is not a lookup, user-code routing
  layer, capability map, detector, or connection gate.
- It does **not** drive actuators, manage calibration, or contain a hardware safety guard. Those belong to user code and to whatever the user's project is.
- It does **not** gate by MAC or board identity. Any matching chip running the agent is fine; the `device_id` (MAC-derived suffix) is for recognition/display only, never authorization.
- The **device label** (`SET_LABEL`, `0x50`) and the **single optional identify-LED GPIO** (`SET_IDENTIFY_LED`, `0x51`) are **per-device configuration the agent owns for its own UX** — they are **not** a routing/pin profile and **not** a board-capability map. They map no hardware for user code (which reaches GPIO directly through the standard `machine` API), and they never gate access. The identify-LED config drives only the Identify blink; it is never exposed to user code.
- Blockly's generic digital-GPIO blocks are only an inspectable source-code
  front end to that same user-code `machine.Pin` API. They require an explicit
  numeric GPIO and do not consult or enforce this reference, `DeviceInfo.chip`,
  an allowed-pin catalog, or an implied safe/default pin. The running
  MicroPython port remains authoritative for physical validity.
- Blockly's NeoPixel blocks likewise generate only the standard user-code
  `neopixel.NeoPixel` API. The user explicitly connects a `Pin`, pixel count,
  index, RGB colour, and write operation. PyBLE neither assumes that a board
  contains an addressable LED nor maps an ESP32-S3 GPIO such as 48. The current
  ESP32 firmware freezes this upstream module; another target port MUST document
  whether the standard module and its required runtime primitive are available.
- Blockly's TFT blocks generate the PyBLE-owned `pyble_st7789` user API with
  explicit SPI, Pin, dimensions, offsets, colour order, and inversion. The
  generic constructor stores no board wiring. The named Waveshare 1.47B example
  supplies only read-only wiring guidance and disconnected GPIO roles; it is
  manually selected and never reads `DeviceInfo`, auto-runs, or gates another
  board. The frozen module is bundled only in
  `waveshare-esp32-s3-lcd-147b`; another image needs a separately installed
  compatible module before generated TFT code can run.
- The bundled Blink/Read-button/Button-controls-LED starter workspaces contain
  disconnected GPIO roles, not example pin numbers. Before PyBLE can generate a
  preview or editable copy, the user supplies each role explicitly. Generic
  wiring notes describe an external LED/resistor or button/pull behavior and
  direct the user back to this informational reference and their board
  documentation; they do not certify a pin, voltage, or circuit.

The pin reference is purely a convenience layer; the source of truth for what a pin does is the chip datasheet, linked from the in-app reference.

Historical v0.4.2 release metadata retains its two-profile shape. The
unqualified v0.5.1 source candidate retains its three-profile identity. The
v0.6.0 schema-4 five-profile bundle does not add directories to or reinterpret
either historical contract.

<!-- SPDX-License-Identifier: MIT -->

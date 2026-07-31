# PyBLE — Hardware Support & Pin Guidance

Status: **DRAFT** · Last updated: 2026-07-30

PyBLE's platform scope is any microcontroller board that can run MicroPython
and provide a Bluetooth Low Energy peripheral stack capable of hosting a
conforming PBLE/1 agent. It makes no assumptions about wiring and carries no
board-specific routing profile. Hardware eligibility is broader than current
support: a board works with PyBLE only after a maintained agent port or firmware
image for that target passes the protocol, resource, recovery, and
hardware-in-the-loop gates.

Classic ESP32, ESP32-S3, and ESP32-C3 are the **initial v1 reference target
families**, not the permanent product boundary. A public browser image is
narrower than a target family and is supported only for the exact memory profile
qualified below. Their firmware exposes hardware to user MicroPython through
standard runtime APIs, including `machine` and the frozen upstream `neopixel`
package. The app may ship read-only target guidance to help users avoid common
footguns.

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

### 1.1 Browser-installer image profiles

| Image profile | Required memory configuration | Installer family check | Release status | Public compatibility claim |
|---|---|---|---|---|
| `esp32-4mb` | Classic ESP32; 4 MiB external SPI flash; no PSRAM assumed | `ESP32` | v0.4.2 HIL pending; installer unavailable | Only boards whose module documentation confirms this flash layout |
| `esp32-s3-n16r8` | ESP32-S3; 16 MiB flash; 8 MiB Octal PSRAM | `ESP32-S3` | v0.4.2 HIL pending; installer unavailable | N16R8-class modules only; not generic ESP32-S3 |
| `esp32-c3-4mb` | ESP32-C3 revision v0.3 or newer; 4 MiB external flash; no PSRAM assumed | `ESP32-C3` | Unavailable pending exact-profile HIL | No public installer compatibility claim yet |

The installer family check cannot establish flash capacity, PSRAM type, USB
wiring, or power integrity. The user therefore selects and confirms the exact
profile before flashing, and each release names the physical reference board
and module marking that passed HIL. Unknown ESP32-S3 variants, including a
different flash size or Quad/no PSRAM, are not covered by
`esp32-s3-n16r8`; they require another profile and its own HIL evidence.
The C3 profile is neither selectable nor published while its status is
unavailable; owning or building the target is not a substitute for HIL. The
current machine-readable resource policy and HIL report therefore contain
exactly the first two profile IDs and no C3 thresholds or record. C3 continues
to build and participate in source/reproducibility/license audits, but its
real-board resource qualification remains required before C3 enablement and
before v1.0.

These are **provisioning image profiles**, not board-routing profiles. They
exist solely to keep destructive flash layouts honest. They do not define GPIO
roles, mediate user code, change PBLE/1 discovery, or make the app gate a
runtime connection by chip. Exact offsets, integrity, recovery, and release
qualification live in
[firmware/browser-flashing.md](firmware/browser-flashing.md).

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
   provisioning tool while normal PyBLE use remains BLE-first.

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

- It does **not** impose or store a board "routing profile."
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
- The bundled Blink/Read-button/Button-controls-LED starter workspaces contain
  disconnected GPIO roles, not example pin numbers. Before PyBLE can generate a
  preview or editable copy, the user supplies each role explicitly. Generic
  wiring notes describe an external LED/resistor or button/pull behavior and
  direct the user back to this informational reference and their board
  documentation; they do not certify a pin, voltage, or circuit.

The pin reference is purely a convenience layer; the source of truth for what a pin does is the chip datasheet, linked from the in-app reference.

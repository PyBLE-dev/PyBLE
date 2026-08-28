// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

export type TutorialDifficulty = "Beginner" | "Beginner hardware";

export interface TutorialRecord {
  slug: string;
  href: `/learn/${string}`;
  title: string;
  position: number;
  difficulty: TutorialDifficulty;
  minutes: number;
  prerequisites: readonly string[];
  outcomes: readonly string[];
  summary: string;
  description: string;
}

export const tutorials = [
  {
    slug: "setup",
    href: "/learn/setup",
    title: "Setup",
    position: 1,
    difficulty: "Beginner",
    minutes: 20,
    prerequisites: ["A supported board, a data-capable USB cable, and an iPad"],
    outcomes: [
      "Install the PyBLE app beta",
      "Provision the exact firmware profile safely",
      "Connect over Bluetooth and verify board identity",
    ],
    summary: "Install the app, provision the right firmware, and connect.",
    description:
      "Prepare one of the five qualified firmware profiles and confirm its identity in PyBLE before writing code.",
  },
  {
    slug: "first-program",
    href: "/learn/first-program",
    title: "First program",
    position: 2,
    difficulty: "Beginner",
    minutes: 10,
    prerequisites: ["A board connected to PyBLE after completing Setup"],
    outcomes: [
      "Create and save a Python file on the board",
      "Run the file and read its Console output",
    ],
    summary: "Create, save, and run a first MicroPython program.",
    description:
      "Complete the smallest full PyBLE workflow with a one-line program that works on every qualified profile.",
  },
  {
    slug: "files",
    href: "/learn/files",
    title: "Files",
    position: 3,
    difficulty: "Beginner",
    minutes: 15,
    prerequisites: ["A connected board and a completed first program"],
    outcomes: [
      "Browse, create, open, edit, save, and refresh board files",
      "Select and delete disposable files with informed confirmation",
      "Recognize protected paths and non-atomic deletion behavior",
    ],
    summary: "Manage board files without risking protected agent files.",
    description:
      "Practice the Files workflow with disposable content, including explicit multi-file selection and deletion safeguards.",
  },
  {
    slug: "github-import",
    href: "/learn/github-import",
    title: "GitHub import",
    position: 4,
    difficulty: "Beginner",
    minutes: 15,
    prerequisites: ["A connected board with an /examples directory"],
    outcomes: [
      "Review and import selected public Python files",
      "Pin an immutable commit instead of relying on a moving branch",
      "Understand GitHub request, rate-limit, and execution boundaries",
    ],
    summary: "Review and import examples from a public GitHub repository.",
    description:
      "Use the editable official-repository default, select a branch or exact commit, and explicitly open and run imported files.",
  },
  {
    slug: "blocks",
    href: "/learn/blocks",
    title: "Blocks",
    position: 5,
    difficulty: "Beginner",
    minutes: 20,
    prerequisites: ["A connected board and familiarity with Save and Run"],
    outcomes: [
      "Open a starter and preview generated Python",
      "Create an editable copy and run it explicitly",
      "Choose hardware starters only after checking their assumptions",
    ],
    summary: "Build a program visually and inspect the generated Python.",
    description:
      "Learn the Blocks-to-Python workflow, its bundled starters, and the hardware checks required before running generated code.",
  },
  {
    slug: "examples",
    href: "/learn/examples",
    title: "Examples catalog",
    position: 6,
    difficulty: "Beginner",
    minutes: 15,
    prerequisites: ["Familiarity with GitHub import and explicit Run"],
    outcomes: [
      "Find an example by category and planned release",
      "Distinguish designed profiles from physical validation",
      "Open every source link at one immutable repository commit",
    ],
    summary:
      "Explore all 32 development examples without overstating evidence.",
    description:
      "Browse the immutable development snapshot by topic, planned release, and accurately bounded hardware design scope.",
  },
  {
    slug: "hardware",
    href: "/learn/hardware",
    title: "Hardware safety",
    position: 7,
    difficulty: "Beginner hardware",
    minutes: 15,
    prerequisites: ["A board-specific pinout and a powered-off circuit"],
    outcomes: [
      "Check voltage, current, polarity, and common ground",
      "Avoid assuming pins from a generic firmware profile",
      "Review wiring before applying power or running code",
    ],
    summary: "Check electrical and profile assumptions before wiring.",
    description:
      "Establish a safe hardware checklist and separate generic firmware compatibility from an exact carrier-board pin map.",
  },
  {
    slug: "configured-hardware",
    href: "/learn/configured-hardware",
    title: "Configured hardware",
    position: 8,
    difficulty: "Beginner hardware",
    minutes: 30,
    prerequisites: [
      "The Hardware safety lesson, exact board documentation, and reviewed components",
    ],
    outcomes: [
      "Configure pins explicitly for common digital and bus examples",
      "Choose a bounded example whose capability matches the circuit",
      "Stop the program and restore a safe hardware state",
    ],
    summary: "Configure external GPIO, analog, bus, and pixel hardware.",
    description:
      "Progress from an external LED and button to PWM, ADC, I2C, SPI, and ESP NeoPixel examples using reviewed pins.",
  },
  {
    slug: "pico-2-w",
    href: "/learn/pico-2-w",
    title: "Pico 2 W",
    position: 9,
    difficulty: "Beginner hardware",
    minutes: 15,
    prerequisites: [
      "A Raspberry Pi Pico 2 W provisioned with its exact profile",
    ],
    outcomes: [
      "Use the named onboard LED safely",
      "Run finite LED patterns designed for the exact Pico 2 W profile",
      "Recognize that firmware 0.6.0 does not claim NeoPixel on this profile",
    ],
    summary: "Use the exact Pico 2 W onboard LED surface.",
    description:
      "Work with the Pico 2 W named LED and its exact-board examples without importing ESP-only NeoPixel assumptions.",
  },
  {
    slug: "waveshare-lcd-147b",
    href: "/learn/waveshare-lcd-147b",
    title: "Waveshare LCD 1.47B",
    position: 10,
    difficulty: "Beginner hardware",
    minutes: 25,
    prerequisites: [
      "An exact Waveshare ESP32-S3-LCD-1.47B provisioned with its exact profile",
    ],
    outcomes: [
      "Use the frozen display runtime and fixed board wiring",
      "Run bounded display examples for the exact B version",
      "Control the exact board's GPIO38 onboard pixel separately",
    ],
    summary: "Draw on the exact B-version display and use its onboard pixel.",
    description:
      "Use the qualified ST7789 surface and exact onboard hardware without treating the board as a generic ESP32-S3 N16R8 carrier.",
  },
] as const satisfies readonly TutorialRecord[];

export type TutorialSlug = (typeof tutorials)[number]["slug"];

export type FirmwareProfileId =
  | "esp32-4mb"
  | "esp32-s3-n16r8"
  | "waveshare-esp32-s3-lcd-147b"
  | "esp32-c3-4mb"
  | "rpi-pico2-w";

export type FirmwareProfileScope = "generic-profile" | "exact-board";

export interface TutorialFirmwareProfile {
  id: FirmwareProfileId;
  label: string;
  shortLabel: string;
  family: string;
  scope: FirmwareProfileScope;
  installMethod: "ESP Web Serial" | "UF2 / BOOTSEL";
  requirements: string;
  guidance: string;
}

export const firmwareProfiles = [
  {
    id: "esp32-4mb",
    label: "Classic ESP32 · 4 MiB flash",
    shortLabel: "ESP32 4 MiB",
    family: "ESP32",
    scope: "generic-profile",
    installMethod: "ESP Web Serial",
    requirements: "4 MiB external SPI flash; no PSRAM assumed",
    guidance:
      "The firmware profile does not define the carrier board's pin map.",
  },
  {
    id: "esp32-s3-n16r8",
    label: "ESP32-S3 · N16R8",
    shortLabel: "ESP32-S3 N16R8",
    family: "ESP32-S3",
    scope: "generic-profile",
    installMethod: "ESP Web Serial",
    requirements: "16 MiB flash and 8 MiB Octal PSRAM",
    guidance:
      "This lean generic profile does not define a display, LED, or carrier pin map.",
  },
  {
    id: "waveshare-esp32-s3-lcd-147b",
    label: "Waveshare ESP32-S3-LCD-1.47B",
    shortLabel: "Waveshare LCD 1.47B",
    family: "ESP32-S3",
    scope: "exact-board",
    installMethod: "ESP Web Serial",
    requirements: "Exact B version; 16 MiB flash and 8 MiB Octal PSRAM",
    guidance:
      "Only this exact-board profile carries the documented display and onboard-pixel assumptions.",
  },
  {
    id: "esp32-c3-4mb",
    label: "ESP32-C3 · 4 MiB flash",
    shortLabel: "ESP32-C3 4 MiB",
    family: "ESP32-C3",
    scope: "generic-profile",
    installMethod: "ESP Web Serial",
    requirements: "Revision 0.3 or newer and 4 MiB external SPI flash",
    guidance:
      "The firmware profile does not define the carrier board's pin map.",
  },
  {
    id: "rpi-pico2-w",
    label: "Raspberry Pi Pico 2 W",
    shortLabel: "Pico 2 W",
    family: "RP2350 + CYW43439",
    scope: "exact-board",
    installMethod: "UF2 / BOOTSEL",
    requirements: "Exact Raspberry Pi Pico 2 W board",
    guidance:
      "This exact-board profile supports the named onboard LED; it does not claim NeoPixel in firmware 0.6.0.",
  },
] as const satisfies readonly TutorialFirmwareProfile[];

export const compatibilityLabels = {
  qualifiedFirmware: "Qualified firmware",
  designed: "Designed for this profile",
  exactBoardOnly: "Exact board only",
  developmentUnvalidated:
    "Development example — physical validation not recorded",
  notApplicable: "Not applicable",
} as const;

export type ExamplePlannedRelease = "0.1.0" | "0.2.0" | "0.3.0";
export type ExampleCategory =
  | "basics"
  | "workflow"
  | "data"
  | "gpio"
  | "buses"
  | "neopixel"
  | "display"
  | "projects";
export type ExampleClassification =
  "portable" | "capability" | "exact-hardware" | "project";

export interface ExampleRecord {
  id: string;
  title: string;
  summary: string;
  plannedRelease: ExamplePlannedRelease;
  category: ExampleCategory;
  classification: ExampleClassification;
  path: string;
  entrypoint: string;
  designedProfiles: readonly FirmwareProfileId[];
  validatedProfiles: readonly FirmwareProfileId[];
  validationStatus: "planned";
  sourceUrl: string;
}

type ExampleSeed = Omit<
  ExampleRecord,
  "sourceUrl" | "validatedProfiles" | "validationStatus"
>;

export const examplesRepositoryUrl =
  "https://github.com/PyBLE-dev/examples" as const;
export const examplesCommit =
  "8f4529b3cd0d62e8d53d7deb4f37e5cd2a171fd1" as const;

const allProfiles = firmwareProfiles.map(({ id }) => id);
const espProfiles = allProfiles.slice(0, 4);

function example(seed: ExampleSeed): ExampleRecord {
  return {
    ...seed,
    validatedProfiles: [],
    validationStatus: "planned",
    sourceUrl: `${examplesRepositoryUrl}/blob/${examplesCommit}/${seed.path}/${seed.entrypoint}`,
  };
}

const examples = [
  example({
    id: "portable-hello-console",
    title: "Hello Console",
    summary: "Confirm import, Run, and bounded console output.",
    plannedRelease: "0.1.0",
    category: "basics",
    classification: "portable",
    path: "examples/portable/basics/hello_console",
    entrypoint: "pyble_hello_console.py",
    designedProfiles: allProfiles,
  }),
  example({
    id: "portable-paced-counter",
    title: "Paced Counter",
    summary: "Use variables, a finite loop, and paced console output.",
    plannedRelease: "0.1.0",
    category: "basics",
    classification: "portable",
    path: "examples/portable/basics/paced_counter",
    entrypoint: "pyble_paced_counter.py",
    designedProfiles: allProfiles,
  }),
  example({
    id: "portable-runtime-info",
    title: "Runtime Information",
    summary: "Report non-identifying runtime and free-heap information.",
    plannedRelease: "0.1.0",
    category: "basics",
    classification: "portable",
    path: "examples/portable/basics/runtime_info",
    entrypoint: "pyble_runtime_info.py",
    designedProfiles: allProfiles,
  }),
  example({
    id: "portable-file-round-trip",
    title: "File Round Trip",
    summary: "Create, verify, and remove one tiny text file safely.",
    plannedRelease: "0.1.0",
    category: "workflow",
    classification: "portable",
    path: "examples/portable/workflow/file_round_trip",
    entrypoint: "pyble_file_round_trip.py",
    designedProfiles: allProfiles,
  }),
  example({
    id: "gpio-blink-external-led",
    title: "Blink an External LED",
    summary: "Drive an explicitly configured external LED for finite toggles.",
    plannedRelease: "0.1.0",
    category: "gpio",
    classification: "capability",
    path: "examples/capabilities/gpio/blink_external_led",
    entrypoint: "pyble_gpio_blink.py",
    designedProfiles: allProfiles,
  }),
  example({
    id: "neopixel-single-pixel",
    title: "Single NeoPixel",
    summary:
      "Show a dim finite color sequence on an explicitly configured pixel.",
    plannedRelease: "0.1.0",
    category: "neopixel",
    classification: "capability",
    path: "examples/capabilities/neopixel/single_pixel",
    entrypoint: "pyble_neopixel_single.py",
    designedProfiles: espProfiles,
  }),
  example({
    id: "pico2w-onboard-led",
    title: "Pico 2 W Onboard LED",
    summary: "Blink the exact Pico 2 W onboard LED by its named pin.",
    plannedRelease: "0.1.0",
    category: "gpio",
    classification: "exact-hardware",
    path: "examples/exact_hardware/rpi_pico2_w/onboard_led",
    entrypoint: "pyble_pico2w_onboard_led.py",
    designedProfiles: ["rpi-pico2-w"],
  }),
  example({
    id: "waveshare-lcd147b-hello",
    title: "Waveshare LCD Hello",
    summary: "Render one bounded hello frame on the exact B-version display.",
    plannedRelease: "0.1.0",
    category: "display",
    classification: "exact-hardware",
    path: "examples/exact_hardware/waveshare_esp32_s3_lcd_147b/lcd_hello",
    entrypoint: "pyble_waveshare_lcd147b_hello.py",
    designedProfiles: ["waveshare-esp32-s3-lcd-147b"],
  }),
  example({
    id: "portable-data-decisions",
    title: "Data and Decisions",
    summary:
      "Combine values, collections, and branching in one bounded example.",
    plannedRelease: "0.2.0",
    category: "basics",
    classification: "portable",
    path: "examples/portable/basics/data_decisions",
    entrypoint: "pyble_data_decisions.py",
    designedProfiles: allProfiles,
  }),
  example({
    id: "portable-reusable-functions",
    title: "Reusable Functions",
    summary: "Use parameters, return values, and function composition.",
    plannedRelease: "0.2.0",
    category: "basics",
    classification: "portable",
    path: "examples/portable/basics/reusable_functions",
    entrypoint: "pyble_reusable_functions.py",
    designedProfiles: allProfiles,
  }),
  example({
    id: "portable-error-handling",
    title: "Error Handling",
    summary: "Validate data and catch one deliberate expected error.",
    plannedRelease: "0.2.0",
    category: "basics",
    classification: "portable",
    path: "examples/portable/basics/error_handling",
    entrypoint: "pyble_error_handling.py",
    designedProfiles: allProfiles,
  }),
  example({
    id: "portable-console-input",
    title: "Console Input",
    summary: "Read one non-secret console response without an input loop.",
    plannedRelease: "0.2.0",
    category: "workflow",
    classification: "portable",
    path: "examples/portable/workflow/console_input",
    entrypoint: "pyble_console_input.py",
    designedProfiles: allProfiles,
  }),
  example({
    id: "portable-json-data",
    title: "JSON Data",
    summary: "Encode and decode a small object entirely in memory.",
    plannedRelease: "0.2.0",
    category: "data",
    classification: "portable",
    path: "examples/portable/data/json_data",
    entrypoint: "pyble_json_data.py",
    designedProfiles: allProfiles,
  }),
  example({
    id: "portable-async-cooperation",
    title: "Async Cooperation",
    summary: "Run two finite cooperative tasks with paced waits.",
    plannedRelease: "0.2.0",
    category: "workflow",
    classification: "portable",
    path: "examples/portable/workflow/async_cooperation",
    entrypoint: "pyble_async_cooperation.py",
    designedProfiles: allProfiles,
  }),
  example({
    id: "portable-binary-data",
    title: "Binary Data",
    summary: "Pack, inspect, and unpack one fixed-size binary record.",
    plannedRelease: "0.2.0",
    category: "data",
    classification: "portable",
    path: "examples/portable/data/binary_data",
    entrypoint: "pyble_binary_data.py",
    designedProfiles: allProfiles,
  }),
  example({
    id: "workflow-stop-a-program",
    title: "Stop a Program",
    summary: "Practice Stop on visible paced work with a hard upper bound.",
    plannedRelease: "0.2.0",
    category: "workflow",
    classification: "portable",
    path: "examples/portable/workflow/stop_a_program",
    entrypoint: "pyble_stop_a_program.py",
    designedProfiles: allProfiles,
  }),
  example({
    id: "workflow-expected-error",
    title: "Expected Runner Error",
    summary: "Raise one announced ValueError to teach runner error state.",
    plannedRelease: "0.2.0",
    category: "workflow",
    classification: "portable",
    path: "examples/portable/workflow/expected_error",
    entrypoint: "pyble_expected_error.py",
    designedProfiles: allProfiles,
  }),
  example({
    id: "filesystem-list-directory",
    title: "List a Directory",
    summary:
      "List a capped set of sanitized names from one absolute directory.",
    plannedRelease: "0.2.0",
    category: "workflow",
    classification: "portable",
    path: "examples/portable/workflow/list_directory",
    entrypoint: "pyble_list_directory.py",
    designedProfiles: allProfiles,
  }),
  example({
    id: "gpio-read-external-button",
    title: "Read an External Button",
    summary: "Report transitions from an explicitly configured button input.",
    plannedRelease: "0.2.0",
    category: "gpio",
    classification: "capability",
    path: "examples/capabilities/gpio/read_external_button",
    entrypoint: "pyble_gpio_button.py",
    designedProfiles: allProfiles,
  }),
  example({
    id: "gpio-button-controls-led",
    title: "Button Controls LED",
    summary: "Combine an explicitly configured button and external LED.",
    plannedRelease: "0.2.0",
    category: "gpio",
    classification: "capability",
    path: "examples/capabilities/gpio/button_controls_led",
    entrypoint: "pyble_gpio_button_led.py",
    designedProfiles: allProfiles,
  }),
  example({
    id: "gpio-pwm-fade",
    title: "PWM Fade",
    summary: "Apply a bounded low-duty PWM fade on a reviewed pin.",
    plannedRelease: "0.2.0",
    category: "gpio",
    classification: "capability",
    path: "examples/capabilities/gpio/pwm_fade",
    entrypoint: "pyble_gpio_pwm_fade.py",
    designedProfiles: allProfiles,
  }),
  example({
    id: "gpio-adc-sampling",
    title: "ADC Sampling",
    summary: "Take a small set of raw and 0-to-1 scaled ADC readings.",
    plannedRelease: "0.2.0",
    category: "gpio",
    classification: "capability",
    path: "examples/capabilities/gpio/adc_sampling",
    entrypoint: "pyble_gpio_adc_sampling.py",
    designedProfiles: allProfiles,
  }),
  example({
    id: "bus-i2c-scan",
    title: "I2C Scan",
    summary: "Scan one explicitly configured software I2C bus.",
    plannedRelease: "0.2.0",
    category: "buses",
    classification: "capability",
    path: "examples/capabilities/buses/i2c_scan",
    entrypoint: "pyble_i2c_scan.py",
    designedProfiles: allProfiles,
  }),
  example({
    id: "bus-spi-loopback",
    title: "SPI Loopback",
    summary:
      "Verify one finite payload on an explicitly configured SoftSPI bus.",
    plannedRelease: "0.2.0",
    category: "buses",
    classification: "capability",
    path: "examples/capabilities/buses/spi_loopback",
    entrypoint: "pyble_spi_loopback.py",
    designedProfiles: allProfiles,
  }),
  example({
    id: "neopixel-strip-chase",
    title: "NeoPixel Strip Chase",
    summary: "Move one dim pixel through a capped strip for finite cycles.",
    plannedRelease: "0.2.0",
    category: "neopixel",
    classification: "capability",
    path: "examples/capabilities/neopixel/strip_chase",
    entrypoint: "pyble_neopixel_chase.py",
    designedProfiles: espProfiles,
  }),
  example({
    id: "pico2w-onboard-led-patterns",
    title: "Pico 2 W LED Patterns",
    summary: "Compose reusable finite patterns on the exact onboard LED.",
    plannedRelease: "0.3.0",
    category: "gpio",
    classification: "exact-hardware",
    path: "examples/exact_hardware/rpi_pico2_w/onboard_led_patterns",
    entrypoint: "pyble_pico2w_led_patterns.py",
    designedProfiles: ["rpi-pico2-w"],
  }),
  example({
    id: "waveshare-lcd147b-shapes",
    title: "Waveshare LCD Shapes",
    summary: "Draw the qualified framebuffer primitives in one bounded frame.",
    plannedRelease: "0.3.0",
    category: "display",
    classification: "exact-hardware",
    path: "examples/exact_hardware/waveshare_esp32_s3_lcd_147b/lcd_shapes",
    entrypoint: "pyble_waveshare_lcd147b_shapes.py",
    designedProfiles: ["waveshare-esp32-s3-lcd-147b"],
  }),
  example({
    id: "waveshare-lcd147b-onboard-pixel",
    title: "Waveshare Onboard Pixel",
    summary: "Show a dim finite sequence on the exact board's GPIO38 pixel.",
    plannedRelease: "0.3.0",
    category: "neopixel",
    classification: "exact-hardware",
    path: "examples/exact_hardware/waveshare_esp32_s3_lcd_147b/onboard_pixel",
    entrypoint: "pyble_waveshare_lcd147b_pixel.py",
    designedProfiles: ["waveshare-esp32-s3-lcd-147b"],
  }),
  example({
    id: "project-button-press-counter",
    title: "Button Press Counter",
    summary:
      "Debounce and count external button presses for a finite interval.",
    plannedRelease: "0.3.0",
    category: "projects",
    classification: "project",
    path: "examples/projects/button_press_counter",
    entrypoint: "pyble_project_button_counter.py",
    designedProfiles: allProfiles,
  }),
  example({
    id: "project-adc-data-logger",
    title: "ADC Data Logger",
    summary: "Write finite ADC samples to one capped CSV-style board file.",
    plannedRelease: "0.3.0",
    category: "projects",
    classification: "project",
    path: "examples/projects/adc_data_logger",
    entrypoint: "pyble_project_adc_logger.py",
    designedProfiles: allProfiles,
  }),
  example({
    id: "project-button-neopixel",
    title: "Button and NeoPixel",
    summary: "Map a configured button state to dim strip feedback.",
    plannedRelease: "0.3.0",
    category: "projects",
    classification: "project",
    path: "examples/projects/button_neopixel",
    entrypoint: "pyble_project_button_neopixel.py",
    designedProfiles: espProfiles,
  }),
  example({
    id: "project-waveshare-lcd147b-dashboard",
    title: "Waveshare LCD Dashboard",
    summary:
      "Refresh elapsed-time and free-memory data in five display frames.",
    plannedRelease: "0.3.0",
    category: "display",
    classification: "exact-hardware",
    path: "examples/exact_hardware/waveshare_esp32_s3_lcd_147b/lcd_dashboard",
    entrypoint: "pyble_waveshare_lcd147b_dashboard.py",
    designedProfiles: ["waveshare-esp32-s3-lcd-147b"],
  }),
] as const satisfies readonly ExampleRecord[];

export const examplesSnapshot = {
  repositoryUrl: examplesRepositoryUrl,
  commit: examplesCommit,
  status: "development",
  releaseTag: null,
  catalogVersion: "0.1.0",
  firmwareBaseline: "0.6.0",
  protocol: "PBLE/1",
  examples,
} as const;

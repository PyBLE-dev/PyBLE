// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

/**
 * Headless smoke test for the committed offline Blockly runtime.
 *
 * Run after tools/build_blockly_assets.sh. It uses the pinned upstream's
 * build-only puppeteer-core and a locally installed Chrome/Chromium; neither is
 * a shipped app dependency.
 */

import fs from "node:fs";
import path from "node:path";
import process from "node:process";
import { fileURLToPath, pathToFileURL } from "node:url";

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.dirname(scriptDir);
const puppeteerUrl = pathToFileURL(
  path.join(
    repoRoot,
    "app/upstream/blockly/node_modules/puppeteer-core/lib/puppeteer/puppeteer-core.js",
  ),
);
const { default: puppeteer } = await import(puppeteerUrl.href);

const browserCandidates = [
  process.env.CHROME_BIN,
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
  "/usr/bin/google-chrome",
  "/usr/bin/chromium",
  "/usr/bin/chromium-browser",
].filter(Boolean);
const executablePath = browserCandidates.find((candidate) =>
  fs.existsSync(candidate),
);
if (!executablePath) {
  throw new Error("Chrome/Chromium not found; set CHROME_BIN.");
}

const browser = await puppeteer.launch({
  executablePath,
  headless: true,
  args: ["--allow-file-access-from-files"],
});

try {
  const page = await browser.newPage();
  await page.setViewport({ width: 1024, height: 760, deviceScaleFactor: 1 });
  const requests = [];
  const pageErrors = [];
  page.on("request", (request) => requests.push(request.url()));
  page.on("pageerror", (error) => pageErrors.push(String(error)));
  await page.evaluateOnNewDocument(() => {
    window.__pybleMessages = [];
    window.PybleBlocks = {
      postMessage(message) {
        window.__pybleMessages.push(JSON.parse(message));
      },
    };
  });

  const localizedHostMessages = {
    examplesCategory: "Localized starter examples",
    exampleTitles: {
      "hello-pyble": "Localized greeting",
      "count-repeatedly": "Localized counting",
      "blink-led": "Localized blinking",
      "blink-neopixel": "Localized RGB blinking",
      "read-button": "Localized input",
      "button-controls-led": "Localized control",
      "reusable-function": "Localized function",
    },
    timeCategory: "Localized timing",
    timeBlockMessage: "localized wait %1 milliseconds",
    timeBlockTooltip: "Localized timing tooltip.",
    timeRequiredError: "Localized duration is required.",
    timeInvalidError: "Localized duration must be a safe integer.",
    gpioCategory: "E/S numériques localisées",
    gpioPinMessage: "BROCHE-LOCALE %1 MODE-LOCAL %2 TIRAGE-LOCAL %3",
    gpioModeInput: "entrée locale",
    gpioModeOutput: "sortie locale",
    gpioPullNone: "sans tirage local",
    gpioPullUp: "tirage haut local",
    gpioPullDown: "tirage bas local",
    gpioPinTooltip: "Info-broche localisée.",
    gpioWriteMessage: "ÉCRIRE-LOCAL %1 NIVEAU-LOCAL %2",
    gpioLevelLow: "niveau bas local",
    gpioLevelHigh: "niveau haut local",
    gpioWriteTooltip: "Info-écriture localisée.",
    gpioReadMessage: "LIRE-LOCAL %1",
    gpioReadTooltip: "Info-lecture localisée.",
    gpioPinRequiredError: "Broche locale requise.",
    gpioPinInvalidError: "Numéro de broche local invalide.",
    gpioModeInvalidError: "Mode de broche local invalide.",
    gpioPullInvalidError: "Tirage de broche local invalide.",
    gpioWritePinRequiredError: "Broche d’écriture locale requise.",
    gpioLevelInvalidError: "Niveau de sortie local invalide.",
    gpioReadPinRequiredError: "Broche de lecture locale requise.",
    gpioRestoreModeInvalidError: "Mode restauré local invalide.",
    gpioRestorePullInvalidError: "Tirage restauré local invalide.",
    gpioRestoreLevelInvalidError: "Niveau restauré local invalide.",
    neopixelCategory: "Pixels RVB localisés",
    neopixelCreateMessage: "CRÉER-PIXEL-LOCAL broche %1 nombre %2",
    neopixelRgbMessage: "COULEUR-LOCALE rouge %1 vert %2 bleu %3",
    neopixelSetPixelMessage: "RÉGLER-PIXEL-LOCAL ruban %1 index %2 couleur %3",
    neopixelFillMessage: "REMPLIR-PIXELS-LOCAL ruban %1 couleur %2",
    neopixelWriteMessage: "AFFICHER-PIXELS-LOCAL ruban %1",
    neopixelCreateTooltip: "Info-création NeoPixel localisée.",
    neopixelRgbTooltip: "Info-couleur NeoPixel localisée.",
    neopixelSetPixelTooltip: "Info-pixel individuel localisée.",
    neopixelFillTooltip: "Info-remplissage NeoPixel localisée.",
    neopixelWriteTooltip: "Info-transmission NeoPixel localisée.",
    neopixelPinRequiredError: "Broche NeoPixel locale requise.",
    neopixelPixelsRequiredError: "Nombre de pixels local requis.",
    neopixelPixelsInvalidError:
      "Nombre de pixels local doit être un entier positif sûr.",
    neopixelRedRequiredError: "Composante rouge locale requise.",
    neopixelGreenRequiredError: "Composante verte locale requise.",
    neopixelBlueRequiredError: "Composante bleue locale requise.",
    neopixelStripRequiredError: "Ruban NeoPixel local requis.",
    neopixelIndexRequiredError: "Index NeoPixel local requis.",
    neopixelColorRequiredError: "Couleur NeoPixel locale requise.",
    multilineValueError: "Valeur locale multiligne refusée.",
  };
  const indexUrl = pathToFileURL(
    path.join(repoRoot, "app/assets/blockly/index.html"),
  );
  await page.goto(indexUrl.href, { waitUntil: "load" });
  const hostEpoch = 101;
  const invalidHostEpoch = await page.evaluate((messages) => {
    try {
      window.pybleBlocks.configureHost(messages, 0);
      return "accepted";
    } catch (error) {
      return String(error);
    }
  }, localizedHostMessages);
  if (!invalidHostEpoch.includes("host epoch")) {
    throw new Error(
      `Blockly accepted an invalid Dart host epoch: ${invalidHostEpoch}`,
    );
  }
  const hostConfiguration = await page.evaluate(({ messages, epoch }) => {
    const configurable =
      typeof window.pybleBlocks?.configureHost === "function";
    return {
      configurable,
      accepted: configurable
        ? window.pybleBlocks.configureHost(messages, epoch)
        : false,
    };
  }, { messages: localizedHostMessages, epoch: hostEpoch });
  if (!hostConfiguration.configurable || hostConfiguration.accepted !== true) {
    throw new Error(
      `localized Blockly host configuration failed: ${JSON.stringify(hostConfiguration)}`,
    );
  }
  await page.waitForFunction(() =>
    window.__pybleMessages.some((message) => message.type === "snapshot"),
  );
  const initialSnapshot = await page.evaluate(() =>
    window.__pybleMessages.find((message) => message.type === "snapshot"),
  );
  if (
    !initialSnapshot ||
    JSON.stringify(initialSnapshot.workspace) !== "{}"
  ) {
    throw new Error(
      `Blockly's canonical empty serialization changed: ${JSON.stringify(initialSnapshot)}`,
    );
  }

  async function assertWorkspaceGeometry(width, height) {
    await page.setViewport({ width, height, deviceScaleFactor: 1 });
    await page.waitForFunction(
      (expectedWidth, expectedHeight) => {
        const svg = document.querySelector(".blocklySvg");
        if (!svg) return false;
        const rect = svg.getBoundingClientRect();
        return (
          Math.abs(rect.width - expectedWidth) <= 1 &&
          Math.abs(rect.height - expectedHeight) <= 1
        );
      },
      {},
      width,
      height,
    );

    const geometry = await page.evaluate(() => {
      const svg = document.querySelector(".blocklySvg").getBoundingClientRect();
      return {
        svg: { width: svg.width, height: svg.height },
        viewport: { width: innerWidth, height: innerHeight },
      };
    });
    if (
      Math.abs(geometry.svg.width - geometry.viewport.width) > 1 ||
      Math.abs(geometry.svg.height - geometry.viewport.height) > 1
    ) {
      throw new Error(
        `Blockly SVG did not fill ${width}x${height}: ${JSON.stringify(geometry)}`,
      );
    }

    const categories = await page.$$(".blocklyToolboxCategory");
    for (let index = 0; index < categories.length; index += 1) {
      await categories[index].click();
      await page.waitForFunction(
        () => {
          const flyout = document.querySelector(
            ".blocklyFlyout.blocklyToolboxFlyout",
          );
          return flyout && flyout.getBoundingClientRect().width > 0;
        },
        { timeout: 3000 },
      );

      const bounds = await page.evaluate((categoryIndex) => {
        const category = document
          .querySelectorAll(".blocklyToolboxCategory")
          [categoryIndex].getBoundingClientRect();
        const flyout = document
          .querySelector(".blocklyFlyout.blocklyToolboxFlyout")
          .getBoundingClientRect();
        return {
          category: {
            width: category.width,
            height: category.height,
            lineHeight: getComputedStyle(
              document.querySelectorAll(".blocklyToolboxCategory")[
                categoryIndex
              ],
            ).lineHeight,
            marginBottom: getComputedStyle(
              document.querySelectorAll(".blocklyToolboxCategory")[
                categoryIndex
              ],
            ).marginBottom,
          },
          flyout: {
            left: flyout.left,
            top: flyout.top,
            right: flyout.right,
            bottom: flyout.bottom,
          },
          viewport: { width: innerWidth, height: innerHeight },
        };
      }, index);
      if (
        bounds.category.height !== 48 ||
        bounds.category.lineHeight !== "48px" ||
        bounds.category.marginBottom !== "0px"
      ) {
        throw new Error(
          `toolbox category ${index} spacing is wrong: ${JSON.stringify(bounds.category)}`,
        );
      }
      if (
        bounds.flyout.left < -1 ||
        bounds.flyout.top < -1 ||
        bounds.flyout.right > bounds.viewport.width + 1 ||
        bounds.flyout.bottom > bounds.viewport.height + 1
      ) {
        throw new Error(
          `toolbox flyout ${index} escaped ${width}x${height}: ${JSON.stringify(bounds.flyout)}`,
        );
      }
    }
  }

  async function assertToolboxTheme(scheme, background, foreground) {
    await page.emulateMediaFeatures([
      { name: "prefers-color-scheme", value: scheme },
    ]);
    await page.waitForFunction(
      (expectedBackground, expectedForeground) => {
        const style = getComputedStyle(
          document.querySelector(".blocklyToolbox"),
        );
        return (
          style.backgroundColor === expectedBackground &&
          style.color === expectedForeground
        );
      },
      {},
      background,
      foreground,
    );
  }

  await assertToolboxTheme("light", "rgb(242, 242, 248)", "rgb(27, 27, 31)");
  await assertToolboxTheme("dark", "rgb(37, 37, 43)", "rgb(242, 242, 248)");
  await assertToolboxTheme("light", "rgb(242, 242, 248)", "rgb(27, 27, 31)");

  const gpioTypes = ["pyble_gpio_pin", "pyble_gpio_write", "pyble_gpio_read"];
  const gpioContract = await page.evaluate(
    ({ types, labels }) => {
      const mainWorkspace = Blockly.getMainWorkspace();
      const toolbox = mainWorkspace.getToolbox();
      const gpioCategory = toolbox
        .getToolboxItems()
        .find(
          (item) =>
            typeof item.getName === "function" &&
            item.getName() === labels.gpioCategory,
        );
      const gpioContents =
        gpioCategory && Array.isArray(gpioCategory.getContents())
          ? gpioCategory.getContents()
          : [];
      const toolboxTypes = gpioContents
        .filter((item) => item.kind === "block")
        .map((item) => item.type);
      const pinToolboxItem = gpioContents.find(
        (item) => item.kind === "block" && item.type === "pyble_gpio_pin",
      );
      const definitions = Object.fromEntries(
        types.map((type) => [type, Boolean(Blockly.Blocks[type])]),
      );
      const generators = Object.fromEntries(
        types.map((type) => [
          type,
          typeof python.pythonGenerator.forBlock[type] === "function",
        ]),
      );

      let shape = null;
      let copy = null;
      if (
        Object.values(definitions).every(Boolean) &&
        Object.values(generators).every(Boolean)
      ) {
        const scratch = new Blockly.Workspace();
        try {
          const pin = scratch.newBlock("pyble_gpio_pin");
          const write = scratch.newBlock("pyble_gpio_write");
          const read = scratch.newBlock("pyble_gpio_read");
          const checks = (connection) =>
            connection && connection.getCheck()
              ? [...(connection.getCheck() || [])].sort()
              : null;
          const optionValues = (block, fieldName) => {
            const field = block.getField(fieldName);
            return field && typeof field.getOptions === "function"
              ? field
                  .getOptions(false)
                  .map((option) => option[1])
                  .sort()
              : null;
          };
          const optionLabels = (block, fieldName) => {
            const field = block.getField(fieldName);
            return field && typeof field.getOptions === "function"
              ? field.getOptions(false).map((option) => option[0])
              : null;
          };
          shape = {
            pin: {
              gpioCheck: checks(pin.getInput("GPIO")?.connection),
              gpioConnected: Boolean(
                pin.getInput("GPIO")?.connection.targetConnection,
              ),
              outputCheck: checks(pin.outputConnection),
              modes: optionValues(pin, "MODE"),
              pulls: optionValues(pin, "PULL"),
            },
            write: {
              pinCheck: checks(write.getInput("PIN")?.connection),
              pinConnected: Boolean(
                write.getInput("PIN")?.connection.targetConnection,
              ),
              levels: optionValues(write, "LEVEL"),
              isStatement: Boolean(
                write.previousConnection && write.nextConnection,
              ),
            },
            read: {
              pinCheck: checks(read.getInput("PIN")?.connection),
              pinConnected: Boolean(
                read.getInput("PIN")?.connection.targetConnection,
              ),
              outputCheck: checks(read.outputConnection),
            },
          };
          copy = {
            pinText: pin.toString(),
            pinTooltip: pin.getTooltip(),
            modeLabels: optionLabels(pin, "MODE"),
            pullLabels: optionLabels(pin, "PULL"),
            writeText: write.toString(),
            writeTooltip: write.getTooltip(),
            levelLabels: optionLabels(write, "LEVEL"),
            readText: read.toString(),
            readTooltip: read.getTooltip(),
          };
        } finally {
          scratch.dispose();
        }
      }

      return {
        categoryFound: Boolean(gpioCategory),
        toolboxTypes,
        toolboxHasGpioPreset: Boolean(
          pinToolboxItem && pinToolboxItem.inputs && pinToolboxItem.inputs.GPIO,
        ),
        definitions,
        generators,
        shape,
        copy,
      };
    },
    { types: gpioTypes, labels: localizedHostMessages },
  );
  const gpioContractProblems = [];
  if (!gpioContract.categoryFound) {
    gpioContractProblems.push(
      `missing localized toolbox category "${localizedHostMessages.gpioCategory}"`,
    );
  }
  for (const type of gpioTypes) {
    if (!gpioContract.toolboxTypes.includes(type)) {
      gpioContractProblems.push(`${type} is absent from the GPIO toolbox`);
    }
    if (!gpioContract.definitions[type]) {
      gpioContractProblems.push(`${type} has no authored block definition`);
    }
    if (!gpioContract.generators[type]) {
      gpioContractProblems.push(`${type} has no MicroPython generator`);
    }
  }
  if (gpioContract.toolboxHasGpioPreset) {
    gpioContractProblems.push(
      "pyble_gpio_pin supplies a board-specific GPIO shadow/default",
    );
  }
  if (gpioContractProblems.length > 0) {
    throw new Error(
      `GPIO Blockly contract is incomplete: ${gpioContractProblems.join("; ")}`,
    );
  }

  function assertSameJson(label, actual, expected) {
    if (JSON.stringify(actual) !== JSON.stringify(expected)) {
      throw new Error(
        `${label}: expected ${JSON.stringify(expected)}, got ${JSON.stringify(actual)}`,
      );
    }
  }

  const requiredNeopixelRuntimeTypes = [
    "pyble_neopixel_create",
    "pyble_neopixel_rgb",
    "pyble_neopixel_set_pixel",
    "pyble_neopixel_fill",
    "pyble_neopixel_write",
  ];
  const missingNeopixelRuntimeTypes = await page.evaluate(
    (types) =>
      types.filter(
        (type) =>
          !Blockly.Blocks[type] ||
          typeof python.pythonGenerator.forBlock[type] !== "function",
      ),
    requiredNeopixelRuntimeTypes,
  );
  if (missingNeopixelRuntimeTypes.length > 0) {
    throw new Error(
      "NeoPixel Blockly runtime is missing definitions/generators: " +
        missingNeopixelRuntimeTypes.join(", "),
    );
  }

  assertSameJson(
    "pyble_gpio_pin connection and dropdown contract",
    gpioContract.shape.pin,
    {
      gpioCheck: ["Number"],
      gpioConnected: false,
      outputCheck: ["Pin"],
      modes: ["IN", "OUT"],
      pulls: ["DOWN", "NONE", "UP"],
    },
  );
  assertSameJson(
    "pyble_gpio_write connection and dropdown contract",
    gpioContract.shape.write,
    {
      pinCheck: ["Pin"],
      pinConnected: false,
      levels: ["HIGH", "LOW"],
      isStatement: true,
    },
  );
  assertSameJson(
    "pyble_gpio_read connection contract",
    gpioContract.shape.read,
    {
      pinCheck: ["Pin"],
      pinConnected: false,
      outputCheck: ["Number"],
    },
  );
  assertSameJson("localized GPIO mode labels", gpioContract.copy.modeLabels, [
    localizedHostMessages.gpioModeInput,
    localizedHostMessages.gpioModeOutput,
  ]);
  assertSameJson("localized GPIO pull labels", gpioContract.copy.pullLabels, [
    localizedHostMessages.gpioPullNone,
    localizedHostMessages.gpioPullUp,
    localizedHostMessages.gpioPullDown,
  ]);
  assertSameJson("localized GPIO level labels", gpioContract.copy.levelLabels, [
    localizedHostMessages.gpioLevelLow,
    localizedHostMessages.gpioLevelHigh,
  ]);
  assertSameJson(
    "localized GPIO pin tooltip",
    gpioContract.copy.pinTooltip,
    localizedHostMessages.gpioPinTooltip,
  );
  assertSameJson(
    "localized GPIO write tooltip",
    gpioContract.copy.writeTooltip,
    localizedHostMessages.gpioWriteTooltip,
  );
  assertSameJson(
    "localized GPIO read tooltip",
    gpioContract.copy.readTooltip,
    localizedHostMessages.gpioReadTooltip,
  );
  for (const [label, actual, markers] of [
    [
      "GPIO pin block message",
      gpioContract.copy.pinText,
      ["BROCHE-LOCALE", "MODE-LOCAL", "TIRAGE-LOCAL"],
    ],
    [
      "GPIO write block message",
      gpioContract.copy.writeText,
      ["ÉCRIRE-LOCAL", "NIVEAU-LOCAL"],
    ],
    ["GPIO read block message", gpioContract.copy.readText, ["LIRE-LOCAL"]],
  ]) {
    for (const marker of markers) {
      if (!actual.includes(marker)) {
        throw new Error(
          `${label} did not render injected copy "${marker}": ${JSON.stringify(actual)}`,
        );
      }
    }
  }

  async function restoreWorkspace(state, priorRevision) {
    const result = await page.evaluate(
      ({ workspaceState, baseRevision }) => {
        const firstMessage = window.__pybleMessages.length;
        const accepted = window.pybleBlocks.restore(
          JSON.stringify(workspaceState),
          baseRevision,
        );
        return {
          accepted,
          messages: window.__pybleMessages.slice(firstMessage),
        };
      },
      { workspaceState: state, baseRevision: priorRevision },
    );
    if (!result.accepted) {
      throw new Error("the public Blockly restore bridge rejected valid JSON");
    }
    if (result.messages.length === 0) {
      throw new Error("the public Blockly restore bridge emitted no result");
    }
    return result.messages[result.messages.length - 1];
  }

  // Beginner examples are ordinary Blockly serialization. The catalog never
  // stores generated source: these checks materialize explicit test-only GPIO
  // choices, then ask the real pinned generator for the exact Python.
  const examplesCatalog = JSON.parse(
    fs.readFileSync(
      path.join(repoRoot, "app/assets/blockly/examples/catalog.json"),
      "utf8",
    ),
  );
  const expectedExampleIds = [
    "hello-pyble",
    "count-repeatedly",
    "blink-led",
    "blink-neopixel",
    "read-button",
    "button-controls-led",
    "reusable-function",
  ];
  assertSameJson(
    "beginner example catalog IDs",
    examplesCatalog.examples.map((example) => example.id),
    expectedExampleIds,
  );
  const examplesToolboxContract = await page.evaluate(
    ({ ids, labels }) => {
      const mainWorkspace = Blockly.getMainWorkspace();
      const configurable =
        typeof window.pybleBlocks.configureHost === "function";
      const category = mainWorkspace
        .getToolbox()
        .getToolboxItems()
        .find(
          (item) =>
            typeof item.getName === "function" &&
            item.getName() === labels.examplesCategory,
        );
      const contents =
        category && Array.isArray(category.getContents())
          ? category.getContents()
          : [];
      const buttons = contents.filter((item) => item.kind === "button");
      const callbackKeys = buttons.map((item) => item.callbackKey);
      const callbacksReady = callbackKeys.every(
        (key) => typeof mainWorkspace.getButtonCallback(key) === "function",
      );
      const before = window.__pybleMessages.length;
      if (callbacksReady && callbackKeys.length === ids.length) {
        mainWorkspace.getButtonCallback(callbackKeys[2])();
      }
      return {
        configurable,
        categoryFound: Boolean(category),
        buttonTexts: buttons.map((item) => item.text),
        callbackKeys,
        callbacksReady,
        request: window.__pybleMessages.slice(before).at(-1),
      };
    },
    { ids: expectedExampleIds, labels: localizedHostMessages },
  );
  assertSameJson("Examples toolbox bridge", examplesToolboxContract, {
    configurable: true,
    categoryFound: true,
    buttonTexts: expectedExampleIds.map(
      (id) => localizedHostMessages.exampleTitles[id],
    ),
    callbackKeys: expectedExampleIds.map((id) => `PYBLE_EXAMPLE_${id}`),
    callbacksReady: true,
    request: {
      version: 1,
      type: "openExamples",
      exampleId: "blink-led",
      hostEpoch,
    },
  });

  const timeContract = await page.evaluate((timeCategoryLabel) => {
    const mainWorkspace = Blockly.getMainWorkspace();
    const category = mainWorkspace
      .getToolbox()
      .getToolboxItems()
      .find(
        (item) =>
          typeof item.getName === "function" &&
          item.getName() === timeCategoryLabel,
      );
    const contents =
      category && Array.isArray(category.getContents())
        ? category.getContents()
        : [];
    const item = contents.find(
      (value) => value.kind === "block" && value.type === "pyble_time_sleep_ms",
    );
    const scratch = new Blockly.Workspace();
    try {
      const first = scratch.newBlock("pyble_time_sleep_ms");
      const second = scratch.newBlock("pyble_time_sleep_ms");
      const number = (value) => {
        const block = scratch.newBlock("math_number");
        block.setFieldValue(value, "NUM");
        return block;
      };
      first
        .getInput("MILLISECONDS")
        .connection.connect(number(250).outputConnection);
      second
        .getInput("MILLISECONDS")
        .connection.connect(number(1000).outputConnection);
      first.nextConnection.connect(second.previousConnection);
      return {
        categoryFound: Boolean(category),
        toolboxFound: Boolean(item),
        toolboxHasDefault: Boolean(item && item.inputs),
        inputCheck: first.getInput("MILLISECONDS").connection.getCheck() || [],
        isStatement: Boolean(first.previousConnection && first.nextConnection),
        source: python.pythonGenerator.workspaceToCode(scratch),
      };
    } finally {
      scratch.dispose();
    }
  }, localizedHostMessages.timeCategory);
  assertSameJson("sleep_ms runtime shape", timeContract, {
    categoryFound: true,
    toolboxFound: true,
    toolboxHasDefault: false,
    inputCheck: ["Number"],
    isStatement: true,
    source:
      "from time import sleep_ms\n\n\n" +
      "sleep_ms(250)\n" +
      "sleep_ms(1000)\n",
  });

  const promptHelperSource = await page.evaluate(() => {
    const scratch = new Blockly.Workspace();
    try {
      const prompt = scratch.newBlock("text_prompt_ext");
      prompt.setFieldValue("TEXT", "TYPE");
      const message = scratch.newBlock("text");
      message.setFieldValue("Prompt", "TEXT");
      prompt.getInput("TEXT").connection.connect(message.outputConnection);
      return python.pythonGenerator.workspaceToCode(scratch);
    } finally {
      scratch.dispose();
    }
  });
  if (
    !promptHelperSource.includes("  try:\n") ||
    !promptHelperSource.includes("  except NameError:\n") ||
    promptHelperSource.includes('${"try"}')
  ) {
    throw new Error(
      `normalized Python helper changed at runtime:\n${promptHelperSource}`,
    );
  }

  const invalidTimeValues = await page.evaluate(() => {
    const rejects = (value, connected = true) => {
      const scratch = new Blockly.Workspace();
      try {
        const sleep = scratch.newBlock("pyble_time_sleep_ms");
        if (connected) {
          const number = scratch.newBlock("math_number");
          number.setFieldValue(value, "NUM");
          sleep
            .getInput("MILLISECONDS")
            .connection.connect(number.outputConnection);
        }
        try {
          python.pythonGenerator.workspaceToCode(scratch);
          return null;
        } catch (error) {
          return error instanceof Error ? error.message : String(error);
        }
      } finally {
        scratch.dispose();
      }
    };
    return {
      missing: rejects(0, false),
      negative: rejects(-1),
      fractional: rejects(1.5),
    };
  });
  assertSameJson("sleep_ms rejects invalid literals", invalidTimeValues, {
    missing: localizedHostMessages.timeRequiredError,
    negative: localizedHostMessages.timeInvalidError,
    fractional: localizedHostMessages.timeInvalidError,
  });

  const neopixelTypes = [
    "pyble_neopixel_create",
    "pyble_neopixel_rgb",
    "pyble_neopixel_set_pixel",
    "pyble_neopixel_fill",
    "pyble_neopixel_write",
  ];
  const neopixelContract = await page.evaluate(
    ({ types, labels }) => {
      const mainWorkspace = Blockly.getMainWorkspace();
      const category = mainWorkspace
        .getToolbox()
        .getToolboxItems()
        .find(
          (item) =>
            typeof item.getName === "function" &&
            item.getName() === labels.neopixelCategory,
        );
      const contents =
        category && Array.isArray(category.getContents())
          ? category.getContents()
          : [];
      const toolboxBlocks = contents.filter((item) => item.kind === "block");
      const definitions = Object.fromEntries(
        types.map((type) => [type, Boolean(Blockly.Blocks[type])]),
      );
      const generators = Object.fromEntries(
        types.map((type) => [
          type,
          typeof python.pythonGenerator.forBlock[type] === "function",
        ]),
      );
      if (
        !Object.values(definitions).every(Boolean) ||
        !Object.values(generators).every(Boolean)
      ) {
        return {
          categoryFound: Boolean(category),
          toolboxTypes: toolboxBlocks.map((item) => item.type),
          toolboxHasDefaults: toolboxBlocks.some((item) => item.inputs),
          definitions,
          generators,
          shape: null,
          copy: null,
        };
      }

      const scratch = new Blockly.Workspace();
      try {
        const create = scratch.newBlock("pyble_neopixel_create");
        const rgb = scratch.newBlock("pyble_neopixel_rgb");
        const setPixel = scratch.newBlock("pyble_neopixel_set_pixel");
        const fill = scratch.newBlock("pyble_neopixel_fill");
        const write = scratch.newBlock("pyble_neopixel_write");
        const checks = (connection) =>
          connection && connection.getCheck
            ? [...(connection.getCheck() || [])].sort()
            : null;
        const disconnected = (block, inputName) =>
          !block.getInput(inputName)?.connection.targetConnection;
        return {
          categoryFound: Boolean(category),
          toolboxTypes: toolboxBlocks.map((item) => item.type),
          toolboxHasDefaults: toolboxBlocks.some((item) => item.inputs),
          definitions,
          generators,
          shape: {
            create: {
              pinCheck: checks(create.getInput("PIN")?.connection),
              pixelsCheck: checks(create.getInput("PIXELS")?.connection),
              outputCheck: checks(create.outputConnection),
              disconnected:
                disconnected(create, "PIN") && disconnected(create, "PIXELS"),
            },
            rgb: {
              redCheck: checks(rgb.getInput("RED")?.connection),
              greenCheck: checks(rgb.getInput("GREEN")?.connection),
              blueCheck: checks(rgb.getInput("BLUE")?.connection),
              outputCheck: checks(rgb.outputConnection),
              disconnected:
                disconnected(rgb, "RED") &&
                disconnected(rgb, "GREEN") &&
                disconnected(rgb, "BLUE"),
            },
            setPixel: {
              stripCheck: checks(setPixel.getInput("STRIP")?.connection),
              indexCheck: checks(setPixel.getInput("INDEX")?.connection),
              colorCheck: checks(setPixel.getInput("COLOR")?.connection),
              isStatement: Boolean(
                setPixel.previousConnection && setPixel.nextConnection,
              ),
              disconnected:
                disconnected(setPixel, "STRIP") &&
                disconnected(setPixel, "INDEX") &&
                disconnected(setPixel, "COLOR"),
            },
            fill: {
              stripCheck: checks(fill.getInput("STRIP")?.connection),
              colorCheck: checks(fill.getInput("COLOR")?.connection),
              isStatement: Boolean(
                fill.previousConnection && fill.nextConnection,
              ),
              disconnected:
                disconnected(fill, "STRIP") && disconnected(fill, "COLOR"),
            },
            write: {
              stripCheck: checks(write.getInput("STRIP")?.connection),
              isStatement: Boolean(
                write.previousConnection && write.nextConnection,
              ),
              disconnected: disconnected(write, "STRIP"),
            },
          },
          copy: {
            createText: create.toString(),
            rgbText: rgb.toString(),
            setPixelText: setPixel.toString(),
            fillText: fill.toString(),
            writeText: write.toString(),
            tooltips: [
              create.getTooltip(),
              rgb.getTooltip(),
              setPixel.getTooltip(),
              fill.getTooltip(),
              write.getTooltip(),
            ],
          },
        };
      } finally {
        scratch.dispose();
      }
    },
    { types: neopixelTypes, labels: localizedHostMessages },
  );
  const neopixelContractProblems = [];
  if (!neopixelContract.categoryFound) {
    neopixelContractProblems.push(
      `missing localized toolbox category "${localizedHostMessages.neopixelCategory}"`,
    );
  }
  if (
    JSON.stringify(neopixelContract.toolboxTypes) !==
    JSON.stringify(neopixelTypes)
  ) {
    neopixelContractProblems.push(
      `expected exactly ${JSON.stringify(neopixelTypes)} in the toolbox, got ${JSON.stringify(neopixelContract.toolboxTypes)}`,
    );
  }
  for (const type of neopixelTypes) {
    if (!neopixelContract.definitions[type]) {
      neopixelContractProblems.push(`${type} has no block definition`);
    }
    if (!neopixelContract.generators[type]) {
      neopixelContractProblems.push(`${type} has no Python generator`);
    }
  }
  if (neopixelContract.toolboxHasDefaults) {
    neopixelContractProblems.push(
      "NeoPixel toolbox blocks contain a shadow/default",
    );
  }
  if (neopixelContractProblems.length > 0) {
    throw new Error(
      `NeoPixel Blockly contract is incomplete: ${neopixelContractProblems.join("; ")}`,
    );
  }
  assertSameJson("NeoPixel block connection contract", neopixelContract.shape, {
    create: {
      pinCheck: ["Pin"],
      pixelsCheck: ["Number"],
      outputCheck: ["NeoPixel"],
      disconnected: true,
    },
    rgb: {
      redCheck: ["Number"],
      greenCheck: ["Number"],
      blueCheck: ["Number"],
      outputCheck: ["NeoPixelColor"],
      disconnected: true,
    },
    setPixel: {
      stripCheck: ["NeoPixel"],
      indexCheck: ["Number"],
      colorCheck: ["NeoPixelColor"],
      isStatement: true,
      disconnected: true,
    },
    fill: {
      stripCheck: ["NeoPixel"],
      colorCheck: ["NeoPixelColor"],
      isStatement: true,
      disconnected: true,
    },
    write: {
      stripCheck: ["NeoPixel"],
      isStatement: true,
      disconnected: true,
    },
  });
  assertSameJson(
    "localized NeoPixel tooltips",
    neopixelContract.copy.tooltips,
    [
      localizedHostMessages.neopixelCreateTooltip,
      localizedHostMessages.neopixelRgbTooltip,
      localizedHostMessages.neopixelSetPixelTooltip,
      localizedHostMessages.neopixelFillTooltip,
      localizedHostMessages.neopixelWriteTooltip,
    ],
  );
  for (const [label, actual, marker] of [
    [
      "NeoPixel create block message",
      neopixelContract.copy.createText,
      "CRÉER-PIXEL-LOCAL",
    ],
    [
      "NeoPixel RGB block message",
      neopixelContract.copy.rgbText,
      "COULEUR-LOCALE",
    ],
    [
      "NeoPixel set block message",
      neopixelContract.copy.setPixelText,
      "RÉGLER-PIXEL-LOCAL",
    ],
    [
      "NeoPixel fill block message",
      neopixelContract.copy.fillText,
      "REMPLIR-PIXELS-LOCAL",
    ],
    [
      "NeoPixel write block message",
      neopixelContract.copy.writeText,
      "AFFICHER-PIXELS-LOCAL",
    ],
  ]) {
    if (!actual.includes(marker)) {
      throw new Error(
        `${label} did not render injected copy "${marker}": ${JSON.stringify(actual)}`,
      );
    }
  }

  const neopixelGeneration = await page.evaluate(() => {
    const scratch = new Blockly.Workspace();
    try {
      const variableMap = scratch.getVariableMap();
      const reservedStrip = variableMap.createVariable(
        "NeoPixel",
        "",
        "neopixel-reserved",
      );
      const secondStrip = variableMap.createVariable(
        "other_strip",
        "",
        "neopixel-other",
      );
      const number = (value) => {
        const block = scratch.newBlock("math_number");
        block.setFieldValue(value, "NUM");
        return block;
      };
      const variableGet = (model) => {
        const block = scratch.newBlock("variables_get");
        block.setFieldValue(model.getId(), "VAR");
        return block;
      };
      const connect = (parent, input, child) =>
        parent.getInput(input).connection.connect(child.outputConnection);
      const pin = (gpio) => {
        const block = scratch.newBlock("pyble_gpio_pin");
        block.setFieldValue("OUT", "MODE");
        block.setFieldValue("NONE", "PULL");
        connect(block, "GPIO", number(gpio));
        return block;
      };
      const create = (gpio, count) => {
        const block = scratch.newBlock("pyble_neopixel_create");
        connect(block, "PIN", pin(gpio));
        connect(block, "PIXELS", number(count));
        return block;
      };
      const rgb = (red, green, blue) => {
        const block = scratch.newBlock("pyble_neopixel_rgb");
        connect(block, "RED", red);
        connect(block, "GREEN", green);
        connect(block, "BLUE", blue);
        return block;
      };

      const declareReserved = scratch.newBlock("variables_set");
      declareReserved.setFieldValue(reservedStrip.getId(), "VAR");
      connect(declareReserved, "VALUE", create(48, 1));

      const declareOther = scratch.newBlock("variables_set");
      declareOther.setFieldValue(secondStrip.getId(), "VAR");
      connect(declareOther, "VALUE", create(4, 2));

      const redExpression = scratch.newBlock("math_arithmetic");
      redExpression.setFieldValue("ADD", "OP");
      connect(redExpression, "A", number(10));
      connect(redExpression, "B", number(10));
      const indexExpression = scratch.newBlock("math_arithmetic");
      indexExpression.setFieldValue("ADD", "OP");
      connect(indexExpression, "A", number(0));
      connect(indexExpression, "B", number(0));

      const setPixel = scratch.newBlock("pyble_neopixel_set_pixel");
      connect(setPixel, "STRIP", variableGet(reservedStrip));
      connect(setPixel, "INDEX", indexExpression);
      connect(setPixel, "COLOR", rgb(redExpression, number(0), number(5)));

      const firstWrite = scratch.newBlock("pyble_neopixel_write");
      connect(firstWrite, "STRIP", variableGet(reservedStrip));

      const fill = scratch.newBlock("pyble_neopixel_fill");
      connect(fill, "STRIP", variableGet(reservedStrip));
      connect(fill, "COLOR", rgb(number(0), number(0), number(0)));

      const secondWrite = scratch.newBlock("pyble_neopixel_write");
      connect(secondWrite, "STRIP", variableGet(reservedStrip));

      declareReserved.nextConnection.connect(declareOther.previousConnection);
      declareOther.nextConnection.connect(setPixel.previousConnection);
      setPixel.nextConnection.connect(firstWrite.previousConnection);
      firstWrite.nextConnection.connect(fill.previousConnection);
      fill.nextConnection.connect(secondWrite.previousConnection);

      const source = python.pythonGenerator.workspaceToCode(scratch);

      const rgbOnly = new Blockly.Workspace();
      let rgbOnlySource;
      try {
        const tuple = rgbOnly.newBlock("pyble_neopixel_rgb");
        for (const [input, value] of [
          ["RED", 1],
          ["GREEN", 2],
          ["BLUE", 3],
        ]) {
          const component = rgbOnly.newBlock("math_number");
          component.setFieldValue(value, "NUM");
          tuple.getInput(input).connection.connect(component.outputConnection);
        }
        rgbOnlySource = python.pythonGenerator.workspaceToCode(rgbOnly);
      } finally {
        rgbOnly.dispose();
      }
      return { source, rgbOnlySource };
    } finally {
      scratch.dispose();
    }
  });
  const expectedNeopixelSource =
    "from machine import Pin\n" +
    "from neopixel import NeoPixel\n\n" +
    "NeoPixel2 = None\n" +
    "other_strip = None\n\n\n" +
    "NeoPixel2 = NeoPixel(Pin(48, Pin.OUT, None), 1)\n" +
    "other_strip = NeoPixel(Pin(4, Pin.OUT, None), 2)\n" +
    "NeoPixel2[0 + 0] = (10 + 10, 0, 5)\n" +
    "NeoPixel2.write()\n" +
    "NeoPixel2.fill((0, 0, 0))\n" +
    "NeoPixel2.write()\n";
  if (neopixelGeneration.source !== expectedNeopixelSource) {
    throw new Error(
      "NeoPixel standard-API generation mismatch:\n" +
        `expected:\n${expectedNeopixelSource}\n` +
        `actual:\n${neopixelGeneration.source}`,
    );
  }
  if (neopixelGeneration.rgbOnlySource !== "(1, 2, 3)\n") {
    throw new Error(
      "an RGB tuple without a constructor must not generate a NeoPixel import: " +
        JSON.stringify(neopixelGeneration.rgbOnlySource),
    );
  }
  const neopixelImportCount = (
    neopixelGeneration.source.match(/^from neopixel import NeoPixel$/gm) || []
  ).length;
  if (neopixelImportCount !== 1) {
    throw new Error(
      `NeoPixel source must contain exactly one unaliased import, got ${neopixelImportCount}`,
    );
  }
  if ((neopixelGeneration.source.match(/\.write\(\)/g) || []).length !== 2) {
    throw new Error(
      "set-pixel/fill must not hide a write; only two explicit write blocks may transmit",
    );
  }

  const neopixelInvalidWorkspaces = await page.evaluate(() => {
    const serialize = (build) => {
      const scratch = new Blockly.Workspace();
      try {
        build(scratch);
        return Blockly.serialization.workspaces.save(scratch);
      } finally {
        scratch.dispose();
      }
    };
    const number = (workspace, value) => {
      const block = workspace.newBlock("math_number");
      block.setFieldValue(value, "NUM");
      return block;
    };
    const connect = (parent, input, child) =>
      parent.getInput(input).connection.connect(child.outputConnection);
    const pin = (workspace) => {
      const block = workspace.newBlock("pyble_gpio_pin");
      block.setFieldValue("OUT", "MODE");
      block.setFieldValue("NONE", "PULL");
      connect(block, "GPIO", number(workspace, 48));
      return block;
    };
    const createWith = (workspace, count) => {
      const block = workspace.newBlock("pyble_neopixel_create");
      connect(block, "PIN", pin(workspace));
      if (count !== undefined) {
        connect(block, "PIXELS", number(workspace, count));
      }
      return block;
    };
    const testValue = (workspace, outputType, code, suffix) => {
      const type = `pyble_test_neopixel_${suffix}`;
      if (!Blockly.Blocks[type]) {
        Blockly.Blocks[type] = {
          init() {
            this.setOutput(true, outputType);
          },
        };
        python.pythonGenerator.forBlock[type] = () => [
          code,
          python.Order.ATOMIC,
        ];
      }
      return workspace.newBlock(type);
    };
    const rgbWith = (workspace, components = {}) => {
      const block = workspace.newBlock("pyble_neopixel_rgb");
      for (const [input, value] of Object.entries(components)) {
        connect(block, input, value);
      }
      return block;
    };
    return {
      createMissingPin: serialize((workspace) => {
        workspace.newBlock("pyble_neopixel_create");
      }),
      createMissingCount: serialize((workspace) => {
        createWith(workspace);
      }),
      createZeroCount: serialize((workspace) => {
        createWith(workspace, 0);
      }),
      createFractionalCount: serialize((workspace) => {
        createWith(workspace, 1.5);
      }),
      createNegativeCount: serialize((workspace) => {
        createWith(workspace, -1);
      }),
      createUnsafeCount: serialize((workspace) => {
        createWith(workspace, "9007199254740992");
      }),
      createExpressionCount: serialize((workspace) => {
        const block = createWith(workspace);
        connect(
          block,
          "PIXELS",
          testValue(workspace, "Number", "1 + 1", "expression_count"),
        );
      }),
      createMultilinePin: serialize((workspace) => {
        const block = workspace.newBlock("pyble_neopixel_create");
        connect(
          block,
          "PIN",
          testValue(workspace, "Pin", "pin\nimport os", "multiline_pin"),
        );
        connect(block, "PIXELS", number(workspace, 1));
      }),
      createMultilineCount: serialize((workspace) => {
        const block = createWith(workspace);
        connect(
          block,
          "PIXELS",
          testValue(workspace, "Number", "1\nimport os", "multiline_count"),
        );
      }),
      rgbMissingRed: serialize((workspace) => {
        workspace.newBlock("pyble_neopixel_rgb");
      }),
      rgbMissingGreen: serialize((workspace) => {
        rgbWith(workspace, { RED: number(workspace, 1) });
      }),
      rgbMissingBlue: serialize((workspace) => {
        rgbWith(workspace, {
          RED: number(workspace, 1),
          GREEN: number(workspace, 2),
        });
      }),
      setMissingStrip: serialize((workspace) => {
        workspace.newBlock("pyble_neopixel_set_pixel");
      }),
      setMissingIndex: serialize((workspace) => {
        const block = workspace.newBlock("pyble_neopixel_set_pixel");
        connect(block, "STRIP", createWith(workspace, 1));
      }),
      setMissingColor: serialize((workspace) => {
        const block = workspace.newBlock("pyble_neopixel_set_pixel");
        connect(block, "STRIP", createWith(workspace, 1));
        connect(block, "INDEX", number(workspace, 0));
      }),
      fillMissingStrip: serialize((workspace) => {
        workspace.newBlock("pyble_neopixel_fill");
      }),
      fillMissingColor: serialize((workspace) => {
        const block = workspace.newBlock("pyble_neopixel_fill");
        connect(block, "STRIP", createWith(workspace, 1));
      }),
      writeMissingStrip: serialize((workspace) => {
        workspace.newBlock("pyble_neopixel_write");
      }),
      rgbMultilineRed: serialize((workspace) => {
        const rgb = workspace.newBlock("pyble_neopixel_rgb");
        connect(
          rgb,
          "RED",
          testValue(workspace, "Number", "1\nimport os", "multiline_red"),
        );
      }),
      setMultilineStrip: serialize((workspace) => {
        const block = workspace.newBlock("pyble_neopixel_set_pixel");
        connect(
          block,
          "STRIP",
          testValue(
            workspace,
            "NeoPixel",
            "pixels\nimport os",
            "multiline_strip",
          ),
        );
      }),
      setMultilineIndex: serialize((workspace) => {
        const block = workspace.newBlock("pyble_neopixel_set_pixel");
        connect(block, "STRIP", createWith(workspace, 1));
        connect(
          block,
          "INDEX",
          testValue(workspace, "Number", "0\nimport os", "multiline_index"),
        );
      }),
      setMultilineColor: serialize((workspace) => {
        const block = workspace.newBlock("pyble_neopixel_set_pixel");
        connect(block, "STRIP", createWith(workspace, 1));
        connect(block, "INDEX", number(workspace, 0));
        connect(
          block,
          "COLOR",
          testValue(
            workspace,
            "NeoPixelColor",
            "(1, 2, 3)\nimport os",
            "multiline_color",
          ),
        );
      }),
      fillMultilineColor: serialize((workspace) => {
        const block = workspace.newBlock("pyble_neopixel_fill");
        connect(block, "STRIP", createWith(workspace, 1));
        connect(
          block,
          "COLOR",
          testValue(
            workspace,
            "NeoPixelColor",
            "(1, 2, 3)\nimport os",
            "multiline_fill_color",
          ),
        );
      }),
      writeMultilineStrip: serialize((workspace) => {
        const block = workspace.newBlock("pyble_neopixel_write");
        connect(
          block,
          "STRIP",
          testValue(
            workspace,
            "NeoPixel",
            "pixels\nimport os",
            "multiline_write_strip",
          ),
        );
      }),
    };
  });
  let neopixelRevision = 700;
  for (const [name, type, expectedMessage] of [
    [
      "createMissingPin",
      "pyble_neopixel_create",
      localizedHostMessages.neopixelPinRequiredError,
    ],
    [
      "createMissingCount",
      "pyble_neopixel_create",
      localizedHostMessages.neopixelPixelsRequiredError,
    ],
    [
      "createZeroCount",
      "pyble_neopixel_create",
      localizedHostMessages.neopixelPixelsInvalidError,
    ],
    [
      "createFractionalCount",
      "pyble_neopixel_create",
      localizedHostMessages.neopixelPixelsInvalidError,
    ],
    [
      "createNegativeCount",
      "pyble_neopixel_create",
      localizedHostMessages.neopixelPixelsInvalidError,
    ],
    [
      "createUnsafeCount",
      "pyble_neopixel_create",
      localizedHostMessages.neopixelPixelsInvalidError,
    ],
    [
      "createExpressionCount",
      "pyble_neopixel_create",
      localizedHostMessages.neopixelPixelsInvalidError,
    ],
    [
      "createMultilinePin",
      "pyble_neopixel_create",
      `${localizedHostMessages.neopixelPinRequiredError} ${localizedHostMessages.multilineValueError}`,
    ],
    [
      "createMultilineCount",
      "pyble_neopixel_create",
      `${localizedHostMessages.neopixelPixelsRequiredError} ${localizedHostMessages.multilineValueError}`,
    ],
    [
      "rgbMissingRed",
      "pyble_neopixel_rgb",
      localizedHostMessages.neopixelRedRequiredError,
    ],
    [
      "rgbMissingGreen",
      "pyble_neopixel_rgb",
      localizedHostMessages.neopixelGreenRequiredError,
    ],
    [
      "rgbMissingBlue",
      "pyble_neopixel_rgb",
      localizedHostMessages.neopixelBlueRequiredError,
    ],
    [
      "setMissingStrip",
      "pyble_neopixel_set_pixel",
      localizedHostMessages.neopixelStripRequiredError,
    ],
    [
      "setMissingIndex",
      "pyble_neopixel_set_pixel",
      localizedHostMessages.neopixelIndexRequiredError,
    ],
    [
      "setMissingColor",
      "pyble_neopixel_set_pixel",
      localizedHostMessages.neopixelColorRequiredError,
    ],
    [
      "fillMissingStrip",
      "pyble_neopixel_fill",
      localizedHostMessages.neopixelStripRequiredError,
    ],
    [
      "fillMissingColor",
      "pyble_neopixel_fill",
      localizedHostMessages.neopixelColorRequiredError,
    ],
    [
      "writeMissingStrip",
      "pyble_neopixel_write",
      localizedHostMessages.neopixelStripRequiredError,
    ],
    [
      "rgbMultilineRed",
      "pyble_neopixel_rgb",
      `${localizedHostMessages.neopixelRedRequiredError} ${localizedHostMessages.multilineValueError}`,
    ],
    [
      "setMultilineStrip",
      "pyble_neopixel_set_pixel",
      `${localizedHostMessages.neopixelStripRequiredError} ${localizedHostMessages.multilineValueError}`,
    ],
    [
      "setMultilineIndex",
      "pyble_neopixel_set_pixel",
      `${localizedHostMessages.neopixelIndexRequiredError} ${localizedHostMessages.multilineValueError}`,
    ],
    [
      "setMultilineColor",
      "pyble_neopixel_set_pixel",
      `${localizedHostMessages.neopixelColorRequiredError} ${localizedHostMessages.multilineValueError}`,
    ],
    [
      "fillMultilineColor",
      "pyble_neopixel_fill",
      `${localizedHostMessages.neopixelColorRequiredError} ${localizedHostMessages.multilineValueError}`,
    ],
    [
      "writeMultilineStrip",
      "pyble_neopixel_write",
      `${localizedHostMessages.neopixelStripRequiredError} ${localizedHostMessages.multilineValueError}`,
    ],
  ]) {
    neopixelRevision = await expectGenerationError(
      neopixelInvalidWorkspaces[name],
      neopixelRevision,
      type,
      `NeoPixel ${name}`,
      expectedMessage,
    );
  }

  const expectedExampleSources = {
    "hello-pyble": "print('Hello, PyBLE!')\n",
    "count-repeatedly":
      "from time import sleep_ms\n\n" +
      "count = None\n\n\n" +
      "for count in range(1, 6):\n" +
      "  print(count)\n" +
      "  sleep_ms(500)\n",
    "blink-led":
      "from machine import Pin\n" +
      "from time import sleep_ms\n\n" +
      "led = None\n\n\n" +
      "led = Pin(17, Pin.OUT, None)\n" +
      "for count in range(10):\n" +
      "  led.value(1)\n" +
      "  sleep_ms(500)\n" +
      "  led.value(0)\n" +
      "  sleep_ms(500)\n",
    "blink-neopixel":
      "from machine import Pin\n" +
      "from neopixel import NeoPixel\n" +
      "from time import sleep_ms\n\n" +
      "pixels = None\n\n\n" +
      "pixels = NeoPixel(Pin(48, Pin.OUT, None), 1)\n" +
      "for count in range(10):\n" +
      "  pixels[0] = (20, 0, 0)\n" +
      "  pixels.write()\n" +
      "  sleep_ms(500)\n" +
      "  pixels[0] = (0, 0, 0)\n" +
      "  pixels.write()\n" +
      "  sleep_ms(500)\n",
    "read-button":
      "from machine import Pin\n" +
      "from time import sleep_ms\n\n" +
      "button = None\n\n\n" +
      "button = Pin(23, Pin.IN, Pin.PULL_UP)\n" +
      "while True:\n" +
      "  print(button.value())\n" +
      "  sleep_ms(100)\n",
    "button-controls-led":
      "from machine import Pin\n" +
      "from time import sleep_ms\n\n" +
      "led = None\n" +
      "button = None\n\n\n" +
      "led = Pin(17, Pin.OUT, None)\n" +
      "button = Pin(23, Pin.IN, Pin.PULL_UP)\n" +
      "while True:\n" +
      "  if button.value() == 0:\n" +
      "    led.value(1)\n" +
      "  else:\n" +
      "    led.value(0)\n" +
      "  sleep_ms(20)\n",
    "reusable-function":
      "name = None\n\n" +
      "# Print a greeting for the supplied name.\n" +
      "def greet(name):\n" +
      "  print('Hello, ' + str(name))\n\n\n" +
      "greet('PyBLE')\n",
  };
  const explicitTestPins = {
    "blink-led": { led: 17 },
    "blink-neopixel": { pixel: 48 },
    "read-button": { button: 23 },
    "button-controls-led": { led: 17, button: 23 },
  };
  const findBlockState = (value, id) => {
    if (!value || typeof value !== "object") return undefined;
    if (!Array.isArray(value) && value.id === id && value.type) return value;
    for (const child of Object.values(value)) {
      const found = findBlockState(child, id);
      if (found) return found;
    }
    return undefined;
  };
  const materializeExample = (example) => {
    const state = JSON.parse(JSON.stringify(example.workspace));
    for (const role of example.gpioRoles) {
      const target = findBlockState(state, role.blockId);
      const number = explicitTestPins[example.id]?.[role.role];
      if (!target || role.input !== "GPIO" || !Number.isInteger(number)) {
        throw new Error(
          `invalid GPIO role metadata for ${example.id}:${role.role}`,
        );
      }
      target.inputs ||= {};
      if (
        target.inputs.GPIO &&
        (target.inputs.GPIO.block || target.inputs.GPIO.shadow)
      ) {
        throw new Error(
          `${example.id}:${role.role} shipped a GPIO pin default`,
        );
      }
      target.inputs.GPIO = {
        block: {
          type: "math_number",
          id: `${example.id}-${role.role}-gpio-value`,
          fields: { NUM: number },
        },
      };
    }
    return state;
  };

  let examplesRevision = 900;
  for (const example of examplesCatalog.examples) {
    let state = example.workspace;
    if (example.gpioRoles.length > 0) {
      const incomplete = await restoreWorkspace(state, examplesRevision);
      if (
        incomplete.type !== "error" ||
        !incomplete.workspace ||
        incomplete.revision <= examplesRevision
      ) {
        throw new Error(
          `${example.id} did not retain its incomplete GPIO workspace`,
        );
      }
      examplesRevision = incomplete.revision;
      state = materializeExample(example);
    }

    const generated = await restoreWorkspace(state, examplesRevision);
    if (
      generated.type !== "snapshot" ||
      generated.source !== expectedExampleSources[example.id]
    ) {
      throw new Error(
        `${example.id} source mismatch:\nexpected:\n` +
          `${expectedExampleSources[example.id]}\nactual:\n` +
          `${generated.source || JSON.stringify(generated)}`,
      );
    }
    examplesRevision = generated.revision;

    const cleared = await restoreWorkspace(
      { blocks: { languageVersion: 0, blocks: [] } },
      examplesRevision,
    );
    const restored = await restoreWorkspace(
      generated.workspace,
      cleared.revision,
    );
    if (
      restored.type !== "snapshot" ||
      restored.source !== generated.source ||
      JSON.stringify(restored.workspace) !== JSON.stringify(generated.workspace)
    ) {
      throw new Error(
        `${example.id} changed across ordinary serialize/restore recovery`,
      );
    }
    examplesRevision = restored.revision;
  }

  async function expectRestoreRejected(state, label, expectedMessage) {
    const result = await page.evaluate((workspaceState) => {
      const firstMessage = window.__pybleMessages.length;
      const accepted = window.pybleBlocks.restore(
        JSON.stringify(workspaceState),
        500,
      );
      return {
        accepted,
        messages: window.__pybleMessages.slice(firstMessage),
      };
    }, state);
    const lastMessage = result.messages[result.messages.length - 1];
    if (
      result.accepted ||
      !lastMessage ||
      lastMessage.type !== "error" ||
      lastMessage.message !== expectedMessage
    ) {
      throw new Error(
        `${label} did not use injected restore copy ${JSON.stringify(expectedMessage)}: ${JSON.stringify(result)}`,
      );
    }
  }

  const serializedBlock = (type, fields) => ({
    blocks: {
      languageVersion: 0,
      blocks: [{ type, id: `tampered-${type}`, x: 0, y: 0, fields }],
    },
  });
  await expectRestoreRejected(
    serializedBlock("pyble_gpio_pin", {
      MODE: "ANALOG",
      PULL: "NONE",
    }),
    "a serialized GPIO mode token",
    localizedHostMessages.gpioRestoreModeInvalidError,
  );
  await expectRestoreRejected(
    serializedBlock("pyble_gpio_pin", {
      MODE: "IN",
      PULL: "SIDEWAYS",
    }),
    "a serialized GPIO pull token",
    localizedHostMessages.gpioRestorePullInvalidError,
  );
  await expectRestoreRejected(
    serializedBlock("pyble_gpio_write", { LEVEL: "MAYBE" }),
    "a serialized GPIO level token",
    localizedHostMessages.gpioRestoreLevelInvalidError,
  );

  async function singleBlockWorkspace(type, configure) {
    return page.evaluate(
      ({ blockType, configuration }) => {
        const scratch = new Blockly.Workspace();
        try {
          const block = scratch.newBlock(blockType);
          if (configuration) {
            for (const [field, value] of Object.entries(
              configuration.fields || {},
            )) {
              block.setFieldValue(value, field);
            }
            if (configuration.gpioGenerator) {
              const testType = `pyble_test_${configuration.gpioGenerator}`;
              if (!Blockly.Blocks[testType]) {
                Blockly.Blocks[testType] = {
                  init() {
                    this.setOutput(true, "Number");
                  },
                };
                python.pythonGenerator.forBlock[testType] = () => [
                  configuration.gpioGenerator === "non_finite"
                    ? "float('inf')"
                    : "2\nimport os",
                  python.Order.ATOMIC,
                ];
              }
              const gpio = scratch.newBlock(testType);
              block.getInput("GPIO").connection.connect(gpio.outputConnection);
            } else if (configuration.gpio !== undefined) {
              const gpio = scratch.newBlock("math_number");
              gpio.setFieldValue(configuration.gpio, "NUM");
              block.getInput("GPIO").connection.connect(gpio.outputConnection);
            }
          }
          return Blockly.serialization.workspaces.save(scratch);
        } finally {
          scratch.dispose();
        }
      },
      { blockType: type, configuration: configure || null },
    );
  }

  async function expectGenerationError(
    state,
    priorRevision,
    expectedBlockType,
    label,
    expectedMessage,
  ) {
    const result = await restoreWorkspace(state, priorRevision);
    if (result.type !== "error" || result.message !== expectedMessage) {
      throw new Error(
        `${label} did not use injected generator copy ${JSON.stringify(expectedMessage)}: ${JSON.stringify(result)}`,
      );
    }
    if (
      !Number.isSafeInteger(result.revision) ||
      result.revision <= priorRevision
    ) {
      throw new Error(
        `${label} did not publish a newer retained revision: ${JSON.stringify(result)}`,
      );
    }
    if (
      !result.workspace ||
      !JSON.stringify(result.workspace).includes(expectedBlockType)
    ) {
      throw new Error(
        `${label} did not retain its repairable workspace: ${JSON.stringify(result)}`,
      );
    }
    return result.revision;
  }

  let gpioRevision = 600;
  for (const [type, label, expectedMessage] of [
    [
      "pyble_gpio_pin",
      "a disconnected GPIO socket",
      localizedHostMessages.gpioPinRequiredError,
    ],
    [
      "pyble_gpio_write",
      "a disconnected digital-write Pin socket",
      localizedHostMessages.gpioWritePinRequiredError,
    ],
    [
      "pyble_gpio_read",
      "a disconnected digital-read Pin socket",
      localizedHostMessages.gpioReadPinRequiredError,
    ],
  ]) {
    gpioRevision = await expectGenerationError(
      await singleBlockWorkspace(type),
      gpioRevision,
      type,
      label,
      expectedMessage,
    );
  }
  for (const [configuration, label, expectedMessage] of [
    [
      { gpio: -1 },
      "a negative GPIO",
      localizedHostMessages.gpioPinInvalidError,
    ],
    [
      { gpio: 2.5 },
      "a fractional GPIO",
      localizedHostMessages.gpioPinInvalidError,
    ],
    [
      { gpioGenerator: "non_finite" },
      "a non-finite GPIO expression",
      localizedHostMessages.gpioPinInvalidError,
    ],
    [
      { gpioGenerator: "tampered" },
      "a tampered GPIO expression",
      `${localizedHostMessages.gpioPinRequiredError} ${localizedHostMessages.multilineValueError}`,
    ],
  ]) {
    gpioRevision = await expectGenerationError(
      await singleBlockWorkspace("pyble_gpio_pin", configuration),
      gpioRevision,
      "pyble_gpio_pin",
      label,
      expectedMessage,
    );
  }

  const tamperedDropdowns = await page.evaluate(() => {
    const rejects = (blockType, fieldName, invalidValue) => {
      const scratch = new Blockly.Workspace();
      try {
        const number = scratch.newBlock("math_number");
        number.setFieldValue(2, "NUM");
        const pin = scratch.newBlock("pyble_gpio_pin");
        pin.getInput("GPIO").connection.connect(number.outputConnection);
        let target = pin;
        if (blockType === "pyble_gpio_write") {
          const write = scratch.newBlock("pyble_gpio_write");
          write.getInput("PIN").connection.connect(pin.outputConnection);
          target = write;
        }
        const field = target.getField(fieldName);
        field.getValue = () => invalidValue;
        try {
          python.pythonGenerator.workspaceToCode(scratch);
          return null;
        } catch (error) {
          return error instanceof Error ? error.message : String(error);
        }
      } finally {
        scratch.dispose();
      }
    };
    return {
      mode: rejects("pyble_gpio_pin", "MODE", "ANALOG"),
      pull: rejects("pyble_gpio_pin", "PULL", "SIDEWAYS"),
      level: rejects("pyble_gpio_write", "LEVEL", "MAYBE"),
    };
  });
  const expectedTamperedDropdownErrors = {
    mode: localizedHostMessages.gpioModeInvalidError,
    pull: localizedHostMessages.gpioPullInvalidError,
    level: localizedHostMessages.gpioLevelInvalidError,
  };
  for (const [field, message] of Object.entries(tamperedDropdowns)) {
    if (message !== expectedTamperedDropdownErrors[field]) {
      throw new Error(
        `tampered GPIO ${field.toUpperCase()} did not use injected copy: ${JSON.stringify(message)}`,
      );
    }
  }

  const gpioWorkspace = await page.evaluate(() => {
    const scratch = new Blockly.Workspace();
    try {
      const led = scratch
        .getVariableMap()
        .createVariable("led", "", "gpio-led");
      const button = scratch
        .getVariableMap()
        .createVariable("button", "", "gpio-button");

      const number = (value) => {
        const block = scratch.newBlock("math_number");
        block.setFieldValue(value, "NUM");
        return block;
      };
      const variableGet = (model) => {
        const block = scratch.newBlock("variables_get");
        block.setFieldValue(model.getId(), "VAR");
        return block;
      };
      const connectValue = (parent, inputName, child) => {
        parent.getInput(inputName).connection.connect(child.outputConnection);
      };

      const declareLed = scratch.newBlock("variables_set");
      declareLed.setFieldValue(led.getId(), "VAR");
      const ledPin = scratch.newBlock("pyble_gpio_pin");
      ledPin.setFieldValue("OUT", "MODE");
      ledPin.setFieldValue("NONE", "PULL");
      connectValue(ledPin, "GPIO", number(2));
      connectValue(declareLed, "VALUE", ledPin);

      const declareButton = scratch.newBlock("variables_set");
      declareButton.setFieldValue(button.getId(), "VAR");
      const buttonPin = scratch.newBlock("pyble_gpio_pin");
      buttonPin.setFieldValue("IN", "MODE");
      buttonPin.setFieldValue("UP", "PULL");
      connectValue(buttonPin, "GPIO", number(4));
      connectValue(declareButton, "VALUE", buttonPin);

      const writeLed = scratch.newBlock("pyble_gpio_write");
      writeLed.setFieldValue("HIGH", "LEVEL");
      connectValue(writeLed, "PIN", variableGet(led));

      const printButton = scratch.newBlock("text_print");
      const readButton = scratch.newBlock("pyble_gpio_read");
      connectValue(readButton, "PIN", variableGet(button));
      connectValue(printButton, "TEXT", readButton);

      declareLed.nextConnection.connect(declareButton.previousConnection);
      declareButton.nextConnection.connect(writeLed.previousConnection);
      writeLed.nextConnection.connect(printButton.previousConnection);

      return Blockly.serialization.workspaces.save(scratch);
    } finally {
      scratch.dispose();
    }
  });
  const expectedGpioSource =
    "from machine import Pin\n\n" +
    "led = None\n" +
    "button = None\n\n\n" +
    "led = Pin(2, Pin.OUT, None)\n" +
    "button = Pin(4, Pin.IN, Pin.PULL_UP)\n" +
    "led.value(1)\n" +
    "print(button.value())\n";
  const gpioSnapshot = await restoreWorkspace(gpioWorkspace, gpioRevision);
  if (gpioSnapshot.type !== "snapshot") {
    throw new Error(
      `valid GPIO workspace did not generate: ${JSON.stringify(gpioSnapshot)}`,
    );
  }
  if (gpioSnapshot.source !== expectedGpioSource) {
    throw new Error(
      `GPIO MicroPython mismatch:\nexpected:\n${expectedGpioSource}\nactual:\n${gpioSnapshot.source}`,
    );
  }
  const pinImportCount = (
    gpioSnapshot.source.match(/^from machine import Pin$/gm) || []
  ).length;
  if (pinImportCount !== 1) {
    throw new Error(
      `GPIO source must contain exactly one machine.Pin import, got ${pinImportCount}`,
    );
  }

  const coldStartPage = await browser.newPage();
  const coldStartPageErrors = [];
  coldStartPage.on("pageerror", (error) =>
    coldStartPageErrors.push(String(error)),
  );
  await coldStartPage.evaluateOnNewDocument(() => {
    window.__pybleMessages = [];
    window.PybleBlocks = {
      postMessage(message) {
        window.__pybleMessages.push(JSON.parse(message));
      },
    };
  });
  await coldStartPage.goto(indexUrl.href, { waitUntil: "load" });
  const retainedRevision = 4096;
  const coldStartHostEpoch = 202;
  const coldStartConfiguration = await coldStartPage.evaluate(
    ({ messages, epoch, retainedWorkspaceJson, priorRevision }) => ({
      accepted: window.pybleBlocks.configureHost(
        messages,
        epoch,
        retainedWorkspaceJson,
        priorRevision,
      ),
    }),
    {
      messages: localizedHostMessages,
      epoch: coldStartHostEpoch,
      retainedWorkspaceJson: JSON.stringify(gpioWorkspace),
      priorRevision: retainedRevision,
    },
  );
  await coldStartPage.waitForFunction(() => window.__pybleMessages.length > 0);
  await coldStartPage.evaluate(
    () =>
      new Promise((resolve) => {
        requestAnimationFrame(() => requestAnimationFrame(resolve));
      }),
  );
  const coldStart = await coldStartPage.evaluate(() => ({
    messages: window.__pybleMessages,
    workspaceCount: document.querySelectorAll(".blocklySvg").length,
  }));
  await coldStartPage.close();

  if (coldStartPageErrors.length > 0) {
    throw new Error(
      `atomic retained-workspace startup raised page errors: ${coldStartPageErrors.join("; ")}`,
    );
  }
  if (coldStartConfiguration.accepted !== true) {
    throw new Error(
      `atomic retained-workspace startup was rejected: ${JSON.stringify(coldStartConfiguration)}`,
    );
  }
  if (coldStart.workspaceCount !== 1 || coldStart.messages.length !== 2) {
    throw new Error(
      `atomic retained-workspace startup must publish one readiness event then one snapshot: ${JSON.stringify(coldStart)}`,
    );
  }
  const [coldStartReady, firstColdStartSnapshot] = coldStart.messages;
  if (
    coldStartReady.type !== "hostReady" ||
    coldStartReady.version !== 1 ||
    Object.keys(coldStartReady).length !== 2
  ) {
    throw new Error(
      `atomic retained-workspace startup did not publish exactly one versioned readiness event first: ${JSON.stringify(coldStart.messages)}`,
    );
  }
  if (
    firstColdStartSnapshot.type !== "snapshot" ||
    firstColdStartSnapshot.hostEpoch !== coldStartHostEpoch ||
    firstColdStartSnapshot.source !== expectedGpioSource ||
    !Number.isSafeInteger(firstColdStartSnapshot.revision) ||
    firstColdStartSnapshot.revision <= retainedRevision ||
    !JSON.stringify(firstColdStartSnapshot.workspace).includes("pyble_gpio_pin")
  ) {
    throw new Error(
      `the first atomic cold-start snapshot was not the retained GPIO program: ${JSON.stringify(firstColdStartSnapshot)}`,
    );
  }

  const emptyWorkspace = {
    blocks: { languageVersion: 0, blocks: [] },
  };
  const clearedSnapshot = await restoreWorkspace(
    emptyWorkspace,
    gpioSnapshot.revision,
  );
  if (clearedSnapshot.type !== "snapshot" || clearedSnapshot.source !== "") {
    throw new Error("could not clear the GPIO workspace before restore");
  }
  const restoredGpioSnapshot = await restoreWorkspace(
    gpioSnapshot.workspace,
    clearedSnapshot.revision,
  );
  if (
    restoredGpioSnapshot.type !== "snapshot" ||
    restoredGpioSnapshot.source !== expectedGpioSource ||
    JSON.stringify(restoredGpioSnapshot.workspace) !==
      JSON.stringify(gpioSnapshot.workspace)
  ) {
    throw new Error(
      `GPIO serialization/restore changed the program: ${JSON.stringify(restoredGpioSnapshot)}`,
    );
  }

  const gpioEdgeWorkspace = await page.evaluate(() => {
    const scratch = new Blockly.Workspace();
    try {
      const variableMap = scratch.getVariableMap();
      const reservedPin = variableMap.createVariable("Pin", "", "reserved-pin");
      const buttonDown = variableMap.createVariable(
        "button_down",
        "",
        "button-down",
      );
      const number = (value) => {
        const block = scratch.newBlock("math_number");
        block.setFieldValue(value, "NUM");
        return block;
      };
      const variableGet = (model) => {
        const block = scratch.newBlock("variables_get");
        block.setFieldValue(model.getId(), "VAR");
        return block;
      };
      const configuredPin = (gpio, mode, pull) => {
        const block = scratch.newBlock("pyble_gpio_pin");
        block.setFieldValue(mode, "MODE");
        block.setFieldValue(pull, "PULL");
        block
          .getInput("GPIO")
          .connection.connect(number(gpio).outputConnection);
        return block;
      };

      const declareReserved = scratch.newBlock("variables_set");
      declareReserved.setFieldValue(reservedPin.getId(), "VAR");
      declareReserved
        .getInput("VALUE")
        .connection.connect(configuredPin(0, "OUT", "NONE").outputConnection);

      const declareDown = scratch.newBlock("variables_set");
      declareDown.setFieldValue(buttonDown.getId(), "VAR");
      declareDown
        .getInput("VALUE")
        .connection.connect(configuredPin(5, "IN", "DOWN").outputConnection);

      const writeLow = scratch.newBlock("pyble_gpio_write");
      writeLow.setFieldValue("LOW", "LEVEL");
      writeLow
        .getInput("PIN")
        .connection.connect(variableGet(reservedPin).outputConnection);

      declareReserved.nextConnection.connect(declareDown.previousConnection);
      declareDown.nextConnection.connect(writeLow.previousConnection);
      return Blockly.serialization.workspaces.save(scratch);
    } finally {
      scratch.dispose();
    }
  });
  const expectedGpioEdgeSource =
    "from machine import Pin\n\n" +
    "Pin2 = None\n" +
    "button_down = None\n\n\n" +
    "Pin2 = Pin(0, Pin.OUT, None)\n" +
    "button_down = Pin(5, Pin.IN, Pin.PULL_DOWN)\n" +
    "Pin2.value(0)\n";
  const gpioEdgeSnapshot = await restoreWorkspace(
    gpioEdgeWorkspace,
    restoredGpioSnapshot.revision,
  );
  if (
    gpioEdgeSnapshot.type !== "snapshot" ||
    gpioEdgeSnapshot.source !== expectedGpioEdgeSource
  ) {
    throw new Error(
      "LOW/PULL_DOWN/reserved-Pin generation mismatch:\n" +
        `expected:\n${expectedGpioEdgeSource}\n` +
        `actual:\n${gpioEdgeSnapshot.source || JSON.stringify(gpioEdgeSnapshot)}`,
    );
  }

  const workspace = {
    blocks: {
      languageVersion: 0,
      blocks: [
        {
          type: "text_print",
          id: "print-block",
          x: 24,
          y: 24,
          inputs: {
            TEXT: {
              block: {
                type: "text",
                id: "text-block",
                fields: { TEXT: "hello" },
              },
            },
          },
        },
      ],
    },
  };
  await page.evaluate((state) => {
    window.pybleBlocks.restore(JSON.stringify(state), 42);
  }, workspace);
  await page.waitForFunction(() =>
    window.__pybleMessages.some(
      (message) =>
        message.type === "snapshot" &&
        message.revision > 42 &&
        message.source.includes("print('hello')"),
    ),
  );

  const snapshotBeforeResize = await page.evaluate(() => {
    window.pybleBlocks.snapshot(201);
    return true;
  });
  if (!snapshotBeforeResize) {
    throw new Error("could not request pre-resize snapshot");
  }
  await page.waitForFunction(() =>
    window.__pybleMessages.some(
      (message) => message.type === "snapshot" && message.requestId === 201,
    ),
  );

  await assertWorkspaceGeometry(1024, 760);
  await assertWorkspaceGeometry(820, 500);
  await assertWorkspaceGeometry(1024, 760);

  await page.evaluate(() => {
    window.pybleBlocks.snapshot(202);
  });
  await page.waitForFunction(() =>
    window.__pybleMessages.some(
      (message) => message.type === "snapshot" && message.requestId === 202,
    ),
  );
  const resizeSnapshots = await page.evaluate(() => {
    const findSnapshot = (requestId) =>
      window.__pybleMessages.find(
        (message) =>
          message.type === "snapshot" && message.requestId === requestId,
      );
    return {
      before: findSnapshot(201),
      after: findSnapshot(202),
    };
  });
  if (
    resizeSnapshots.before.source !== resizeSnapshots.after.source ||
    JSON.stringify(resizeSnapshots.before.workspace) !==
      JSON.stringify(resizeSnapshots.after.workspace)
  ) {
    throw new Error("workspace or generated Python changed across resize");
  }

  await page.evaluate(() => {
    window.pybleBlocks.snapshot(123);
  });
  await page.waitForFunction(() =>
    window.__pybleMessages.some(
      (message) =>
        message.type === "snapshot" &&
        message.requestId === 123 &&
        message.source.includes("print('hello')"),
    ),
  );

  const bridgeEpochs = await page.evaluate(() => window.__pybleMessages);
  const readyMessages = bridgeEpochs.filter(
    (message) => message.type === "hostReady",
  );
  const postConfigMessages = bridgeEpochs.filter(
    (message) => message.type !== "hostReady",
  );
  if (
    readyMessages.length !== 1 ||
    Object.keys(readyMessages[0]).length !== 2 ||
    postConfigMessages.length === 0 ||
    postConfigMessages.some((message) => message.hostEpoch !== hostEpoch)
  ) {
    throw new Error(
      `Blockly bridge traffic was not bound to host epoch ${hostEpoch}: ${JSON.stringify(bridgeEpochs)}`,
    );
  }

  const external = requests.filter((request) => {
    const url = new URL(request);
    return url.protocol !== "file:" && url.protocol !== "data:";
  });
  if (external.length > 0) {
    throw new Error(`external requests observed: ${external.join(", ")}`);
  }
  if (pageErrors.length > 0) {
    throw new Error(`page errors observed: ${pageErrors.join(", ")}`);
  }

  process.stdout.write(
    "Blockly asset smoke: generated Python, responsive flyouts/themes, retained resize state, echoed request 123, no network.\n",
  );
} finally {
  await browser.close();
}

// SPDX-License-Identifier: MIT

(() => {
  "use strict";

  const bridgeVersion = 1;
  const maxErrorLength = 512;
  const maxRevision = 0xffffffff;
  const gpioColour = 190;
  const neopixelColour = 315;
  const timeColour = 30;
  const examplesColour = 45;
  const gpioPinType = "Pin";
  const neopixelType = "NeoPixel";
  const neopixelColorType = "NeoPixelColor";
  const beginnerExampleIds = Object.freeze([
    "hello-pyble",
    "count-repeatedly",
    "blink-led",
    "blink-neopixel",
    "read-button",
    "button-controls-led",
    "reusable-function",
  ]);
  let hostMessages;
  const gpioModes = Object.freeze({
    IN: "Pin.IN",
    OUT: "Pin.OUT",
  });
  const gpioPulls = Object.freeze({
    NONE: "None",
    UP: "Pin.PULL_UP",
    DOWN: "Pin.PULL_DOWN",
  });
  const gpioLevels = Object.freeze({
    LOW: "0",
    HIGH: "1",
  });

  function hasOwn(object, key) {
    return Object.prototype.hasOwnProperty.call(object, key);
  }

  function requiredValueCode(block, generator, inputName, order, message) {
    const code = generator.valueToCode(block, inputName, order).trim();
    if (code.length === 0) {
      throw new Error(message);
    }
    if (/[\r\n]/u.test(code)) {
      throw new Error(`${message} ${hostMessages.multilineValueError}`);
    }
    return code;
  }

  function positiveIntegerCode(
    block,
    generator,
    inputName,
    requiredMessage,
    invalidMessage,
  ) {
    const code = requiredValueCode(
      block,
      generator,
      inputName,
      python.Order.NONE,
      requiredMessage,
    );
    const value = Number(code);
    if (
      !/^(?:0|[1-9][0-9]*)$/u.test(code) ||
      !Number.isSafeInteger(value) ||
      value <= 0
    ) {
      throw new Error(invalidMessage);
    }
    return code;
  }

  function gpioNumberCode(block, generator) {
    const code = requiredValueCode(
      block,
      generator,
      "GPIO",
      python.Order.NONE,
      hostMessages.gpioPinRequiredError,
    );
    if (!/^(?:0|[1-9][0-9]*)$/u.test(code) || !Number.isFinite(Number(code))) {
      throw new Error(hostMessages.gpioPinInvalidError);
    }
    return code;
  }

  function millisecondsCode(block, generator) {
    const code = requiredValueCode(
      block,
      generator,
      "MILLISECONDS",
      python.Order.NONE,
      hostMessages.timeRequiredError,
    );
    if (!/^(?:0|[1-9][0-9]*)$/u.test(code) || !Number.isFinite(Number(code))) {
      throw new Error(hostMessages.timeInvalidError);
    }
    return code;
  }

  function selectedValue(block, fieldName, allowed, message) {
    const value = block.getFieldValue(fieldName);
    if (typeof value !== "string" || !hasOwn(allowed, value)) {
      throw new Error(message);
    }
    return allowed[value];
  }

  function registerGpioBlocks() {
    Blockly.defineBlocksWithJsonArray([
      {
        type: "pyble_gpio_pin",
        message0: hostMessages.gpioPinMessage,
        args0: [
          {
            type: "input_value",
            name: "GPIO",
            check: "Number",
          },
          {
            type: "field_dropdown",
            name: "MODE",
            options: () => [
              [hostMessages.gpioModeInput, "IN"],
              [hostMessages.gpioModeOutput, "OUT"],
            ],
          },
          {
            type: "field_dropdown",
            name: "PULL",
            options: () => [
              [hostMessages.gpioPullNone, "NONE"],
              [hostMessages.gpioPullUp, "UP"],
              [hostMessages.gpioPullDown, "DOWN"],
            ],
          },
        ],
        inputsInline: true,
        output: gpioPinType,
        colour: gpioColour,
        tooltip: hostMessages.gpioPinTooltip,
        helpUrl: "",
      },
      {
        type: "pyble_gpio_write",
        message0: hostMessages.gpioWriteMessage,
        args0: [
          {
            type: "input_value",
            name: "PIN",
            check: gpioPinType,
          },
          {
            type: "field_dropdown",
            name: "LEVEL",
            options: () => [
              [hostMessages.gpioLevelLow, "LOW"],
              [hostMessages.gpioLevelHigh, "HIGH"],
            ],
          },
        ],
        inputsInline: true,
        previousStatement: null,
        nextStatement: null,
        colour: gpioColour,
        tooltip: hostMessages.gpioWriteTooltip,
        helpUrl: "",
      },
      {
        type: "pyble_gpio_read",
        message0: hostMessages.gpioReadMessage,
        args0: [
          {
            type: "input_value",
            name: "PIN",
            check: gpioPinType,
          },
        ],
        inputsInline: true,
        output: "Number",
        colour: gpioColour,
        tooltip: hostMessages.gpioReadTooltip,
        helpUrl: "",
      },
    ]);

    // Reserve before the first workspace generation initializes Blockly's
    // Python name database, so a user variable named Pin cannot shadow this
    // standard MicroPython import.
    python.pythonGenerator.addReservedWords("Pin");

    python.pythonGenerator.forBlock.pyble_gpio_pin = (block, generator) => {
      const gpio = gpioNumberCode(block, generator);
      const mode = selectedValue(
        block,
        "MODE",
        gpioModes,
        hostMessages.gpioModeInvalidError,
      );
      const pull = selectedValue(
        block,
        "PULL",
        gpioPulls,
        hostMessages.gpioPullInvalidError,
      );
      generator.definitions_["import_machine_pin"] = "from machine import Pin";
      const args = [gpio, mode, pull];
      return [`Pin(${args.join(", ")})`, python.Order.FUNCTION_CALL];
    };

    python.pythonGenerator.forBlock.pyble_gpio_write = (block, generator) => {
      const pin = requiredValueCode(
        block,
        generator,
        "PIN",
        python.Order.MEMBER,
        hostMessages.gpioWritePinRequiredError,
      );
      const level = selectedValue(
        block,
        "LEVEL",
        gpioLevels,
        hostMessages.gpioLevelInvalidError,
      );
      return `${pin}.value(${level})\n`;
    };

    python.pythonGenerator.forBlock.pyble_gpio_read = (block, generator) => {
      const pin = requiredValueCode(
        block,
        generator,
        "PIN",
        python.Order.MEMBER,
        hostMessages.gpioReadPinRequiredError,
      );
      return [`${pin}.value()`, python.Order.FUNCTION_CALL];
    };
  }

  function registerNeopixelBlocks() {
    Blockly.defineBlocksWithJsonArray([
      {
        type: "pyble_neopixel_create",
        message0: hostMessages.neopixelCreateMessage,
        args0: [
          {
            type: "input_value",
            name: "PIN",
            check: gpioPinType,
          },
          {
            type: "input_value",
            name: "PIXELS",
            check: "Number",
          },
        ],
        inputsInline: true,
        output: neopixelType,
        colour: neopixelColour,
        tooltip: hostMessages.neopixelCreateTooltip,
        helpUrl: "",
      },
      {
        type: "pyble_neopixel_rgb",
        message0: hostMessages.neopixelRgbMessage,
        args0: [
          {
            type: "input_value",
            name: "RED",
            check: "Number",
          },
          {
            type: "input_value",
            name: "GREEN",
            check: "Number",
          },
          {
            type: "input_value",
            name: "BLUE",
            check: "Number",
          },
        ],
        inputsInline: true,
        output: neopixelColorType,
        colour: neopixelColour,
        tooltip: hostMessages.neopixelRgbTooltip,
        helpUrl: "",
      },
      {
        type: "pyble_neopixel_set_pixel",
        message0: hostMessages.neopixelSetPixelMessage,
        args0: [
          {
            type: "input_value",
            name: "STRIP",
            check: neopixelType,
          },
          {
            type: "input_value",
            name: "INDEX",
            check: "Number",
          },
          {
            type: "input_value",
            name: "COLOR",
            check: neopixelColorType,
          },
        ],
        inputsInline: true,
        previousStatement: null,
        nextStatement: null,
        colour: neopixelColour,
        tooltip: hostMessages.neopixelSetPixelTooltip,
        helpUrl: "",
      },
      {
        type: "pyble_neopixel_fill",
        message0: hostMessages.neopixelFillMessage,
        args0: [
          {
            type: "input_value",
            name: "STRIP",
            check: neopixelType,
          },
          {
            type: "input_value",
            name: "COLOR",
            check: neopixelColorType,
          },
        ],
        inputsInline: true,
        previousStatement: null,
        nextStatement: null,
        colour: neopixelColour,
        tooltip: hostMessages.neopixelFillTooltip,
        helpUrl: "",
      },
      {
        type: "pyble_neopixel_write",
        message0: hostMessages.neopixelWriteMessage,
        args0: [
          {
            type: "input_value",
            name: "STRIP",
            check: neopixelType,
          },
        ],
        inputsInline: true,
        previousStatement: null,
        nextStatement: null,
        colour: neopixelColour,
        tooltip: hostMessages.neopixelWriteTooltip,
        helpUrl: "",
      },
    ]);

    // Reserve before the generator initializes its name database so a user
    // variable cannot shadow the standard MicroPython class import.
    python.pythonGenerator.addReservedWords("NeoPixel");

    python.pythonGenerator.forBlock.pyble_neopixel_create = (
      block,
      generator,
    ) => {
      const pin = requiredValueCode(
        block,
        generator,
        "PIN",
        python.Order.NONE,
        hostMessages.neopixelPinRequiredError,
      );
      const pixels = positiveIntegerCode(
        block,
        generator,
        "PIXELS",
        hostMessages.neopixelPixelsRequiredError,
        hostMessages.neopixelPixelsInvalidError,
      );
      generator.definitions_["import_neopixel"] =
        "from neopixel import NeoPixel";
      return [`NeoPixel(${pin}, ${pixels})`, python.Order.FUNCTION_CALL];
    };

    python.pythonGenerator.forBlock.pyble_neopixel_rgb = (block, generator) => {
      const red = requiredValueCode(
        block,
        generator,
        "RED",
        python.Order.NONE,
        hostMessages.neopixelRedRequiredError,
      );
      const green = requiredValueCode(
        block,
        generator,
        "GREEN",
        python.Order.NONE,
        hostMessages.neopixelGreenRequiredError,
      );
      const blue = requiredValueCode(
        block,
        generator,
        "BLUE",
        python.Order.NONE,
        hostMessages.neopixelBlueRequiredError,
      );
      return [`(${red}, ${green}, ${blue})`, python.Order.ATOMIC];
    };

    python.pythonGenerator.forBlock.pyble_neopixel_set_pixel = (
      block,
      generator,
    ) => {
      const strip = requiredValueCode(
        block,
        generator,
        "STRIP",
        python.Order.MEMBER,
        hostMessages.neopixelStripRequiredError,
      );
      const index = requiredValueCode(
        block,
        generator,
        "INDEX",
        python.Order.NONE,
        hostMessages.neopixelIndexRequiredError,
      );
      const color = requiredValueCode(
        block,
        generator,
        "COLOR",
        python.Order.NONE,
        hostMessages.neopixelColorRequiredError,
      );
      return `${strip}[${index}] = ${color}\n`;
    };

    python.pythonGenerator.forBlock.pyble_neopixel_fill = (
      block,
      generator,
    ) => {
      const strip = requiredValueCode(
        block,
        generator,
        "STRIP",
        python.Order.MEMBER,
        hostMessages.neopixelStripRequiredError,
      );
      const color = requiredValueCode(
        block,
        generator,
        "COLOR",
        python.Order.NONE,
        hostMessages.neopixelColorRequiredError,
      );
      return `${strip}.fill(${color})\n`;
    };

    python.pythonGenerator.forBlock.pyble_neopixel_write = (
      block,
      generator,
    ) => {
      const strip = requiredValueCode(
        block,
        generator,
        "STRIP",
        python.Order.MEMBER,
        hostMessages.neopixelStripRequiredError,
      );
      return `${strip}.write()\n`;
    };
  }

  function registerTimeBlocks() {
    Blockly.defineBlocksWithJsonArray([
      {
        type: "pyble_time_sleep_ms",
        message0: hostMessages.timeBlockMessage,
        args0: [
          {
            type: "input_value",
            name: "MILLISECONDS",
            check: "Number",
          },
        ],
        inputsInline: true,
        previousStatement: null,
        nextStatement: null,
        colour: timeColour,
        tooltip: hostMessages.timeBlockTooltip,
        helpUrl: "",
      },
    ]);

    // Reserve before the first generator initialization so a user variable
    // cannot shadow the standard MicroPython timing function.
    python.pythonGenerator.addReservedWords("sleep_ms");
    python.pythonGenerator.forBlock.pyble_time_sleep_ms = (
      block,
      generator,
    ) => {
      const milliseconds = millisecondsCode(block, generator);
      generator.definitions_["import_time_sleep_ms"] =
        "from time import sleep_ms";
      return `sleep_ms(${milliseconds})\n`;
    };
  }

  function categoryName(key) {
    if (
      typeof MSG !== "object" ||
      MSG === null ||
      typeof MSG[key] !== "string"
    ) {
      throw new Error(`Missing Blockly category message: ${key}`);
    }
    return MSG[key];
  }

  function createToolbox() {
    return {
      kind: "categoryToolbox",
      contents: [
        {
          kind: "category",
          name: categoryName("catLogic"),
          colour: "%{BKY_LOGIC_HUE}",
          contents: [
            { kind: "block", type: "controls_if" },
            { kind: "block", type: "logic_compare" },
            { kind: "block", type: "logic_operation" },
            { kind: "block", type: "logic_negate" },
            { kind: "block", type: "logic_boolean" },
            { kind: "block", type: "logic_null" },
            { kind: "block", type: "logic_ternary" },
          ],
        },
        {
          kind: "category",
          name: categoryName("catLoops"),
          colour: "%{BKY_LOOPS_HUE}",
          contents: [
            { kind: "block", type: "controls_repeat_ext" },
            { kind: "block", type: "controls_whileUntil" },
            { kind: "block", type: "controls_for" },
            { kind: "block", type: "controls_forEach" },
            { kind: "block", type: "controls_flow_statements" },
          ],
        },
        {
          kind: "category",
          name: categoryName("catMath"),
          colour: "%{BKY_MATH_HUE}",
          contents: [
            { kind: "block", type: "math_number" },
            { kind: "block", type: "math_arithmetic" },
            { kind: "block", type: "math_single" },
            { kind: "block", type: "math_trig" },
            { kind: "block", type: "math_constant" },
            { kind: "block", type: "math_number_property" },
            { kind: "block", type: "math_round" },
            { kind: "block", type: "math_on_list" },
            { kind: "block", type: "math_modulo" },
            { kind: "block", type: "math_constrain" },
            { kind: "block", type: "math_random_int" },
            { kind: "block", type: "math_random_float" },
            { kind: "block", type: "math_atan2" },
          ],
        },
        {
          kind: "category",
          name: categoryName("catText"),
          colour: "%{BKY_TEXTS_HUE}",
          contents: [
            { kind: "block", type: "text" },
            { kind: "block", type: "text_join" },
            { kind: "block", type: "text_append" },
            { kind: "block", type: "text_length" },
            { kind: "block", type: "text_isEmpty" },
            { kind: "block", type: "text_indexOf" },
            { kind: "block", type: "text_charAt" },
            { kind: "block", type: "text_getSubstring" },
            { kind: "block", type: "text_changeCase" },
            { kind: "block", type: "text_trim" },
            { kind: "block", type: "text_count" },
            { kind: "block", type: "text_replace" },
            { kind: "block", type: "text_reverse" },
            { kind: "block", type: "text_print" },
            { kind: "block", type: "text_prompt_ext" },
          ],
        },
        {
          kind: "category",
          name: categoryName("catLists"),
          colour: "%{BKY_LISTS_HUE}",
          contents: [
            { kind: "block", type: "lists_create_empty" },
            { kind: "block", type: "lists_create_with" },
            { kind: "block", type: "lists_repeat" },
            { kind: "block", type: "lists_length" },
            { kind: "block", type: "lists_isEmpty" },
            { kind: "block", type: "lists_indexOf" },
            { kind: "block", type: "lists_getIndex" },
            { kind: "block", type: "lists_setIndex" },
            { kind: "block", type: "lists_getSublist" },
            { kind: "block", type: "lists_split" },
            { kind: "block", type: "lists_sort" },
            { kind: "block", type: "lists_reverse" },
          ],
        },
        {
          kind: "category",
          name: hostMessages.gpioCategory,
          colour: gpioColour,
          contents: [
            { kind: "block", type: "pyble_gpio_pin" },
            { kind: "block", type: "pyble_gpio_write" },
            { kind: "block", type: "pyble_gpio_read" },
          ],
        },
        {
          kind: "category",
          name: hostMessages.neopixelCategory,
          colour: neopixelColour,
          contents: [
            { kind: "block", type: "pyble_neopixel_create" },
            { kind: "block", type: "pyble_neopixel_rgb" },
            { kind: "block", type: "pyble_neopixel_set_pixel" },
            { kind: "block", type: "pyble_neopixel_fill" },
            { kind: "block", type: "pyble_neopixel_write" },
          ],
        },
        {
          kind: "category",
          name: hostMessages.timeCategory,
          colour: timeColour,
          contents: [{ kind: "block", type: "pyble_time_sleep_ms" }],
        },
        {
          kind: "category",
          name: hostMessages.examplesCategory,
          colour: examplesColour,
          contents: beginnerExampleIds.map((id) => ({
            kind: "button",
            text: hostMessages.exampleTitles[id],
            callbackKey: `PYBLE_EXAMPLE_${id}`,
          })),
        },
        {
          kind: "category",
          name: categoryName("catVariables"),
          colour: "%{BKY_VARIABLES_HUE}",
          custom: "VARIABLE",
        },
        {
          kind: "category",
          name: categoryName("catFunctions"),
          colour: "%{BKY_PROCEDURES_HUE}",
          custom: "PROCEDURE",
        },
      ],
    };
  }

  let workspace;
  let revision = 0;
  let hostEpoch;
  let snapshotScheduled = false;
  let pendingRestore;
  let resizeFrame = 0;
  const workspaceElement = document.getElementById("blockly-workspace");

  function postMessage(message) {
    const channel = window.PybleBlocks;
    if (channel && typeof channel.postMessage === "function") {
      const envelope =
        message.type === "hostReady" ? message : { ...message, hostEpoch };
      channel.postMessage(JSON.stringify(envelope));
    }
  }

  function errorText(error) {
    const text =
      error instanceof Error && error.message ? error.message : String(error);
    return text.slice(0, maxErrorLength);
  }

  function isValidRequestId(value) {
    return Number.isSafeInteger(value) && value >= 1 && value <= maxRevision;
  }

  function publishError(error, requestId, workspaceState, errorRevision) {
    const message = {
      version: bridgeVersion,
      type: "error",
      message: errorText(error),
    };
    if (
      workspaceState !== undefined &&
      Number.isSafeInteger(errorRevision) &&
      errorRevision >= 1 &&
      errorRevision <= maxRevision
    ) {
      message.workspace = workspaceState;
      message.revision = errorRevision;
    }
    if (requestId !== undefined) {
      message.requestId = requestId;
    }
    postMessage(message);
  }

  function publishSnapshot(requestId) {
    if (!workspace) {
      return;
    }

    let workspaceState;
    let nextRevision;
    try {
      if (requestId !== undefined && !isValidRequestId(requestId)) {
        throw new RangeError("Snapshot request ID is outside the safe range.");
      }
      workspaceState = Blockly.serialization.workspaces.save(workspace);
      if (!Number.isSafeInteger(revision) || revision >= maxRevision) {
        throw new RangeError("Workspace revision limit reached.");
      }
      revision += 1;
      nextRevision = revision;
      const source = python.pythonGenerator.workspaceToCode(workspace);
      const message = {
        version: bridgeVersion,
        type: "snapshot",
        source,
        workspace: workspaceState,
        revision,
      };
      if (requestId !== undefined) {
        message.requestId = requestId;
      }
      postMessage(message);
    } catch (error) {
      publishError(error, requestId, workspaceState, nextRevision);
    }
  }

  function scheduleSnapshot(event) {
    if (!event || event.isUiEvent) {
      return;
    }
    if (snapshotScheduled) {
      return;
    }
    snapshotScheduled = true;
    window.queueMicrotask(() => {
      snapshotScheduled = false;
      publishSnapshot();
    });
  }

  function validateSerializedChoice(blockState, fieldName, allowed, message) {
    const fields = blockState.fields;
    if (
      !fields ||
      typeof fields !== "object" ||
      Array.isArray(fields) ||
      !hasOwn(fields, fieldName) ||
      typeof fields[fieldName] !== "string" ||
      !hasOwn(allowed, fields[fieldName])
    ) {
      throw new Error(message);
    }
  }

  function validateSerializedGpioState(value) {
    if (!value || typeof value !== "object") {
      return;
    }
    if (Array.isArray(value)) {
      for (const item of value) {
        validateSerializedGpioState(item);
      }
      return;
    }

    if (value.type === "pyble_gpio_pin") {
      validateSerializedChoice(
        value,
        "MODE",
        gpioModes,
        hostMessages.gpioRestoreModeInvalidError,
      );
      validateSerializedChoice(
        value,
        "PULL",
        gpioPulls,
        hostMessages.gpioRestorePullInvalidError,
      );
    } else if (value.type === "pyble_gpio_write") {
      validateSerializedChoice(
        value,
        "LEVEL",
        gpioLevels,
        hostMessages.gpioRestoreLevelInvalidError,
      );
    }

    for (const child of Object.values(value)) {
      validateSerializedGpioState(child);
    }
  }

  function parseRestore(workspaceJson, priorRevision) {
    if (typeof workspaceJson !== "string") {
      throw new TypeError("Workspace state must be a JSON string.");
    }

    const workspaceState = JSON.parse(workspaceJson);
    if (
      !workspaceState ||
      typeof workspaceState !== "object" ||
      Array.isArray(workspaceState)
    ) {
      throw new TypeError("Workspace state must be a JSON object.");
    }
    validateSerializedGpioState(workspaceState);

    const baseRevision =
      Number.isSafeInteger(priorRevision) &&
      priorRevision >= 0 &&
      priorRevision <= maxRevision
        ? priorRevision
        : 0;
    return { workspaceState, baseRevision };
  }

  function applyRestore(restore) {
    snapshotScheduled = false;
    revision = Math.max(revision, restore.baseRevision);

    Blockly.Events.disable();
    try {
      workspace.clear();
      Blockly.serialization.workspaces.load(restore.workspaceState, workspace);
    } finally {
      Blockly.Events.enable();
    }

    Blockly.svgResize(workspace);
    publishSnapshot();
  }

  function restore(workspaceJson, priorRevision) {
    try {
      const parsedRestore = parseRestore(workspaceJson, priorRevision);
      if (!workspace) {
        pendingRestore = parsedRestore;
      } else {
        applyRestore(parsedRestore);
      }
      return true;
    } catch (error) {
      publishError(error);
      return false;
    }
  }

  function previewExample(workspaceJson) {
    const parsed = parseRestore(workspaceJson, 0);
    const scratch = new Blockly.Workspace();
    try {
      Blockly.serialization.workspaces.load(parsed.workspaceState, scratch);
      const source = python.pythonGenerator.workspaceToCode(scratch);
      const canonicalWorkspace = Blockly.serialization.workspaces.save(scratch);
      return JSON.stringify({
        source,
        workspace: canonicalWorkspace,
      });
    } finally {
      scratch.dispose();
    }
  }

  function requiredHostMessage(messages, key) {
    const value = messages[key];
    if (typeof value !== "string" || value.trim().length === 0) {
      throw new Error(`Missing localized Blockly host message: ${key}`);
    }
    return value;
  }

  function configureHost(messages, dartHostEpoch, workspaceJson, priorRevision) {
    if (workspace) {
      throw new Error("Blockly host is already configured.");
    }
    if (
      !Number.isSafeInteger(dartHostEpoch) ||
      dartHostEpoch < 1 ||
      dartHostEpoch > maxRevision
    ) {
      throw new TypeError("Dart host epoch must be a positive safe integer.");
    }
    if (!messages || typeof messages !== "object" || Array.isArray(messages)) {
      throw new TypeError("Blockly host messages must be an object.");
    }
    const rawTitles = messages.exampleTitles;
    if (
      !rawTitles ||
      typeof rawTitles !== "object" ||
      Array.isArray(rawTitles)
    ) {
      throw new TypeError("Localized example titles must be an object.");
    }
    const exampleTitles = Object.fromEntries(
      beginnerExampleIds.map((id) => [id, requiredHostMessage(rawTitles, id)]),
    );
    hostMessages = Object.freeze({
      examplesCategory: requiredHostMessage(messages, "examplesCategory"),
      exampleTitles: Object.freeze(exampleTitles),
      timeCategory: requiredHostMessage(messages, "timeCategory"),
      timeBlockMessage: requiredHostMessage(messages, "timeBlockMessage"),
      timeBlockTooltip: requiredHostMessage(messages, "timeBlockTooltip"),
      timeRequiredError: requiredHostMessage(messages, "timeRequiredError"),
      timeInvalidError: requiredHostMessage(messages, "timeInvalidError"),
      gpioCategory: requiredHostMessage(messages, "gpioCategory"),
      gpioPinMessage: requiredHostMessage(messages, "gpioPinMessage"),
      gpioWriteMessage: requiredHostMessage(messages, "gpioWriteMessage"),
      gpioReadMessage: requiredHostMessage(messages, "gpioReadMessage"),
      gpioModeInput: requiredHostMessage(messages, "gpioModeInput"),
      gpioModeOutput: requiredHostMessage(messages, "gpioModeOutput"),
      gpioPullNone: requiredHostMessage(messages, "gpioPullNone"),
      gpioPullUp: requiredHostMessage(messages, "gpioPullUp"),
      gpioPullDown: requiredHostMessage(messages, "gpioPullDown"),
      gpioLevelLow: requiredHostMessage(messages, "gpioLevelLow"),
      gpioLevelHigh: requiredHostMessage(messages, "gpioLevelHigh"),
      gpioPinTooltip: requiredHostMessage(messages, "gpioPinTooltip"),
      gpioWriteTooltip: requiredHostMessage(messages, "gpioWriteTooltip"),
      gpioReadTooltip: requiredHostMessage(messages, "gpioReadTooltip"),
      gpioPinRequiredError: requiredHostMessage(
        messages,
        "gpioPinRequiredError",
      ),
      gpioPinInvalidError: requiredHostMessage(messages, "gpioPinInvalidError"),
      gpioModeInvalidError: requiredHostMessage(
        messages,
        "gpioModeInvalidError",
      ),
      gpioPullInvalidError: requiredHostMessage(
        messages,
        "gpioPullInvalidError",
      ),
      gpioWritePinRequiredError: requiredHostMessage(
        messages,
        "gpioWritePinRequiredError",
      ),
      gpioLevelInvalidError: requiredHostMessage(
        messages,
        "gpioLevelInvalidError",
      ),
      gpioReadPinRequiredError: requiredHostMessage(
        messages,
        "gpioReadPinRequiredError",
      ),
      gpioRestoreModeInvalidError: requiredHostMessage(
        messages,
        "gpioRestoreModeInvalidError",
      ),
      gpioRestorePullInvalidError: requiredHostMessage(
        messages,
        "gpioRestorePullInvalidError",
      ),
      gpioRestoreLevelInvalidError: requiredHostMessage(
        messages,
        "gpioRestoreLevelInvalidError",
      ),
      neopixelCategory: requiredHostMessage(messages, "neopixelCategory"),
      neopixelCreateMessage: requiredHostMessage(
        messages,
        "neopixelCreateMessage",
      ),
      neopixelRgbMessage: requiredHostMessage(messages, "neopixelRgbMessage"),
      neopixelSetPixelMessage: requiredHostMessage(
        messages,
        "neopixelSetPixelMessage",
      ),
      neopixelFillMessage: requiredHostMessage(messages, "neopixelFillMessage"),
      neopixelWriteMessage: requiredHostMessage(
        messages,
        "neopixelWriteMessage",
      ),
      neopixelCreateTooltip: requiredHostMessage(
        messages,
        "neopixelCreateTooltip",
      ),
      neopixelRgbTooltip: requiredHostMessage(messages, "neopixelRgbTooltip"),
      neopixelSetPixelTooltip: requiredHostMessage(
        messages,
        "neopixelSetPixelTooltip",
      ),
      neopixelFillTooltip: requiredHostMessage(messages, "neopixelFillTooltip"),
      neopixelWriteTooltip: requiredHostMessage(
        messages,
        "neopixelWriteTooltip",
      ),
      neopixelPinRequiredError: requiredHostMessage(
        messages,
        "neopixelPinRequiredError",
      ),
      neopixelPixelsRequiredError: requiredHostMessage(
        messages,
        "neopixelPixelsRequiredError",
      ),
      neopixelPixelsInvalidError: requiredHostMessage(
        messages,
        "neopixelPixelsInvalidError",
      ),
      neopixelRedRequiredError: requiredHostMessage(
        messages,
        "neopixelRedRequiredError",
      ),
      neopixelGreenRequiredError: requiredHostMessage(
        messages,
        "neopixelGreenRequiredError",
      ),
      neopixelBlueRequiredError: requiredHostMessage(
        messages,
        "neopixelBlueRequiredError",
      ),
      neopixelStripRequiredError: requiredHostMessage(
        messages,
        "neopixelStripRequiredError",
      ),
      neopixelIndexRequiredError: requiredHostMessage(
        messages,
        "neopixelIndexRequiredError",
      ),
      neopixelColorRequiredError: requiredHostMessage(
        messages,
        "neopixelColorRequiredError",
      ),
      multilineValueError: requiredHostMessage(messages, "multilineValueError"),
    });
    const hasWorkspace = workspaceJson !== undefined;
    const hasRevision = priorRevision !== undefined;
    if (hasWorkspace !== hasRevision) {
      throw new TypeError(
        "A retained workspace and its revision must be configured together.",
      );
    }
    const initialRestore = hasWorkspace
      ? parseRestore(workspaceJson, priorRevision)
      : undefined;
    registerGpioBlocks();
    registerNeopixelBlocks();
    registerTimeBlocks();
    hostEpoch = dartHostEpoch;
    pendingRestore = initialRestore;
    initialise();
    return true;
  }

  window.pybleBlocks = Object.freeze({
    configureHost,
    previewExample,
    restore,
    snapshot: publishSnapshot,
  });
  postMessage({ version: bridgeVersion, type: "hostReady" });

  function resizeWorkspace() {
    if (!workspace) {
      return;
    }
    cancelAnimationFrame(resizeFrame);
    resizeFrame = requestAnimationFrame(() => {
      resizeFrame = 0;
      Blockly.svgResize(workspace);
    });
  }

  function initialise() {
    try {
      workspace = Blockly.inject("blockly-workspace", {
        toolbox: createToolbox(),
        renderer: "zelos",
        media: "vendor/media/",
        trashcan: true,
        sounds: false,
        grid: {
          spacing: 24,
          length: 3,
          colour: "#d8d8e2",
          snap: true,
        },
        move: {
          scrollbars: true,
          drag: true,
          wheel: true,
        },
        zoom: {
          controls: true,
          wheel: true,
          pinch: true,
          startScale: 0.9,
          maxScale: 1.8,
          minScale: 0.45,
          scaleSpeed: 1.1,
        },
      });
      for (const exampleId of beginnerExampleIds) {
        workspace.registerButtonCallback(`PYBLE_EXAMPLE_${exampleId}`, () => {
          postMessage({
            version: bridgeVersion,
            type: "openExamples",
            exampleId,
          });
        });
      }
      workspace.addChangeListener(scheduleSnapshot);
      window.addEventListener("resize", resizeWorkspace);
      if (typeof ResizeObserver === "function") {
        new ResizeObserver(resizeWorkspace).observe(workspaceElement);
      }

      if (pendingRestore) {
        const restoreState = pendingRestore;
        pendingRestore = undefined;
        applyRestore(restoreState);
      } else {
        publishSnapshot();
      }
    } catch (error) {
      publishError(error);
    }
  }
})();

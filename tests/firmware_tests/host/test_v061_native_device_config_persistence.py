#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.

"""Compiled ESP device-configuration persistence contract for v0.6.1.

The production ``pble_device_config.c`` and ``pble_wire.c`` translation units
are compiled unchanged against deterministic host shims for NVS, advertising,
GPIO, timers, and VM lifecycle.  Each scenario is a fresh process so the
production file's boot-lifetime static state is exercised exactly once.
"""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[3]
NATIVE = ROOT / "firmware" / "user_c_modules" / "pyble"
DEVICE_CONFIG = NATIVE / "pble_device_config.c"
WIRE = NATIVE / "pble_wire.c"


class NativeDeviceConfigPersistenceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = shutil.which(os.environ.get("CC", "cc"))
        if compiler is None:
            raise unittest.SkipTest("a host C compiler is required")

        cls._temporary = tempfile.TemporaryDirectory(
            prefix="pyble-v061-native-device-config-"
        )
        temp = Path(cls._temporary.name)
        for relative, source in STUB_HEADERS.items():
            target = temp / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(source, encoding="utf-8")

        harness = temp / "native_device_config_harness.c"
        harness.write_text(HARNESS, encoding="utf-8")
        cls._executable = temp / "native_device_config_harness"
        compiled = subprocess.run(
            [
                compiler,
                "-std=c11",
                "-Wall",
                "-Wextra",
                "-Werror",
                "-I",
                str(temp),
                "-I",
                str(NATIVE),
                str(DEVICE_CONFIG),
                str(WIRE),
                str(harness),
                "-o",
                str(cls._executable),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        if compiled.returncode != 0:
            raise AssertionError(
                "native device-config harness did not compile:\n"
                + compiled.stdout
                + compiled.stderr
            )

    @classmethod
    def tearDownClass(cls):
        cls._temporary.cleanup()

    def run_scenario(self, scenario):
        completed = subprocess.run(
            [str(self._executable), scenario],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        self.assertEqual(
            completed.returncode,
            0,
            "native device-config scenario {!r} failed:\n{}{}".format(
                scenario, completed.stdout, completed.stderr
            ),
        )

    def test_label_set_erase_and_commit_failures_retain_runtime_surfaces(self):
        for scenario in (
            "label-set-failure",
            "label-erase-failure",
            "label-commit-failure",
            "label-clear-commit-failure",
        ):
            with self.subTest(scenario=scenario):
                self.run_scenario(scenario)

    def test_identify_set_and_commit_failures_retain_caps_and_gpio(self):
        for scenario in (
            "identify-set-failure",
            "identify-commit-failure",
            "identify-clear-set-failure",
            "identify-clear-commit-failure",
        ):
            with self.subTest(scenario=scenario):
                self.run_scenario(scenario)

    def test_invalid_authoritative_blob_never_falls_back_to_legacy(self):
        for scenario in (
            "authoritative-bad-version",
            "authoritative-bad-length",
            "authoritative-bad-disabled-shape",
            "authoritative-bad-active-level",
            "authoritative-bad-gpio",
            "authoritative-probe-failure",
            "authoritative-read-failure",
        ):
            with self.subTest(scenario=scenario):
                self.run_scenario(scenario)

    def test_missing_authoritative_blob_accepts_only_wholly_valid_legacy_pair(self):
        for scenario in (
            "legacy-valid",
            "legacy-both-missing",
            "legacy-missing-gpio",
            "legacy-missing-active-level",
            "legacy-bad-active-level",
            "legacy-bad-gpio",
            "legacy-gpio-read-failure",
            "legacy-active-read-failure",
        ):
            with self.subTest(scenario=scenario):
                self.run_scenario(scenario)

    def test_successful_repair_clears_only_its_configuration_domain(self):
        for scenario in ("repair-label-only", "repair-identify-only"):
            with self.subTest(scenario=scenario):
                self.run_scenario(scenario)


STUB_HEADERS = {
    "esp_mac.h": r"""
#ifndef ESP_MAC_H
#define ESP_MAC_H
#include <stdint.h>
#ifndef ESP_ERR_T_DEFINED
#define ESP_ERR_T_DEFINED
typedef int esp_err_t;
#endif
#define ESP_MAC_BT 1
esp_err_t esp_read_mac(uint8_t *mac, int type);
#endif
""",
    "nvs.h": r"""
#ifndef NVS_H
#define NVS_H
#include <stddef.h>
#include <stdint.h>
#ifndef ESP_ERR_T_DEFINED
#define ESP_ERR_T_DEFINED
typedef int esp_err_t;
#endif
typedef unsigned nvs_handle_t;
#define ESP_OK 0
#define ESP_FAIL (-1)
#define ESP_ERR_NVS_NOT_FOUND 0x1102
#define ESP_ERR_INVALID_STATE 0x103
#define NVS_READONLY 1
#define NVS_READWRITE 2
esp_err_t nvs_open(const char *name, int mode, nvs_handle_t *handle);
esp_err_t nvs_get_str(nvs_handle_t handle, const char *key, char *value,
                      size_t *length);
esp_err_t nvs_get_blob(nvs_handle_t handle, const char *key, void *value,
                       size_t *length);
esp_err_t nvs_get_u8(nvs_handle_t handle, const char *key, uint8_t *value);
esp_err_t nvs_set_str(nvs_handle_t handle, const char *key, const char *value);
esp_err_t nvs_erase_key(nvs_handle_t handle, const char *key);
esp_err_t nvs_set_blob(nvs_handle_t handle, const char *key,
                       const void *value, size_t length);
esp_err_t nvs_commit(nvs_handle_t handle);
void nvs_close(nvs_handle_t handle);
#endif
""",
    "esp_timer.h": r"""
#ifndef ESP_TIMER_H
#define ESP_TIMER_H
#include <stdint.h>
#include "nvs.h"
typedef void *esp_timer_handle_t;
typedef struct {
    void (*callback)(void *);
    const char *name;
} esp_timer_create_args_t;
esp_err_t esp_timer_create(const esp_timer_create_args_t *args,
                           esp_timer_handle_t *timer);
esp_err_t esp_timer_stop(esp_timer_handle_t timer);
esp_err_t esp_timer_start_once(esp_timer_handle_t timer, uint64_t timeout_us);
esp_err_t esp_timer_start_periodic(esp_timer_handle_t timer,
                                   uint64_t period_us);
int64_t esp_timer_get_time(void);
#endif
""",
    "esp_system.h": r"""
#ifndef ESP_SYSTEM_H
#define ESP_SYSTEM_H
void esp_restart(void) __attribute__((noreturn));
#endif
""",
    "driver/gpio.h": r"""
#ifndef DRIVER_GPIO_H
#define DRIVER_GPIO_H
#include "nvs.h"
#define GPIO_MODE_OUTPUT 1
esp_err_t gpio_reset_pin(int gpio);
esp_err_t gpio_set_direction(int gpio, int mode);
esp_err_t gpio_set_level(int gpio, int level);
#endif
""",
    "soc/gpio_num.h": r"""
#ifndef SOC_GPIO_NUM_H
#define SOC_GPIO_NUM_H
#define GPIO_NUM_MAX 16
#define GPIO_IS_VALID_OUTPUT_GPIO(gpio) ((gpio) >= 0 && (gpio) < 10)
#endif
""",
    "freertos/FreeRTOS.h": r"""
#ifndef FREERTOS_FREERTOS_H
#define FREERTOS_FREERTOS_H
typedef int portMUX_TYPE;
#define portMUX_INITIALIZER_UNLOCKED 0
#define taskENTER_CRITICAL(mux) ((void)(mux))
#define taskEXIT_CRITICAL(mux) ((void)(mux))
#endif
""",
    "freertos/task.h": r"""
#ifndef FREERTOS_TASK_H
#define FREERTOS_TASK_H
#endif
""",
}


HARNESS = r"""
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "pble_device_config.h"
#include "esp_mac.h"
#include "nvs.h"
#include "esp_timer.h"
#include "driver/gpio.h"
#include "pble_vm_lifecycle.h"

#define FAULT_LABEL 1u
#define FAULT_IDENTIFY 2u
#define VALID_OLD_GPIO 5u
#define VALID_NEW_GPIO 6u

typedef struct {
    bool label_present;
    char label[64];
    bool id_cfg_present;
    uint8_t id_cfg[16];
    size_t id_cfg_len;
    bool legacy_gpio_present;
    uint8_t legacy_gpio;
    bool legacy_active_present;
    uint8_t legacy_active;
} fake_store_t;

static fake_store_t durable;
static fake_store_t staged;
static bool staged_open;

static esp_err_t open_read_rc;
static esp_err_t open_write_rc;
static esp_err_t get_str_rc;
static esp_err_t get_blob_probe_rc;
static esp_err_t get_blob_read_rc;
static esp_err_t get_gpio_rc;
static esp_err_t get_active_rc;
static esp_err_t set_str_rc;
static esp_err_t erase_rc;
static esp_err_t set_blob_rc;
static esp_err_t commit_rc;

static unsigned adv_calls;
static char last_adv[64];
static unsigned gpio_reset_calls;
static unsigned gpio_direction_calls;
static unsigned gpio_level_calls;
static int last_gpio = -1;
static int last_gpio_level = -1;

#define CHECK(condition, message) do {                                      \
    if (!(condition)) {                                                     \
        fprintf(stderr, "%s\n", (message));                               \
        return 1;                                                           \
    }                                                                       \
} while (0)

static void backend_defaults(void) {
    memset(&durable, 0, sizeof(durable));
    memset(&staged, 0, sizeof(staged));
    staged_open = false;
    open_read_rc = ESP_OK;
    open_write_rc = ESP_OK;
    get_str_rc = ESP_OK;
    get_blob_probe_rc = ESP_OK;
    get_blob_read_rc = ESP_OK;
    get_gpio_rc = ESP_OK;
    get_active_rc = ESP_OK;
    set_str_rc = ESP_OK;
    erase_rc = ESP_OK;
    set_blob_rc = ESP_OK;
    commit_rc = ESP_OK;
    adv_calls = 0;
    memset(last_adv, 0, sizeof(last_adv));
    gpio_reset_calls = 0;
    gpio_direction_calls = 0;
    gpio_level_calls = 0;
    last_gpio = -1;
    last_gpio_level = -1;
}

static void seed_label(const char *label) {
    durable.label_present = true;
    snprintf(durable.label, sizeof(durable.label), "%s", label);
}

static void seed_valid_id(uint8_t gpio, uint8_t active) {
    durable.id_cfg_present = true;
    durable.id_cfg_len = 4u;
    durable.id_cfg[0] = 1u;
    durable.id_cfg[1] = 1u;
    durable.id_cfg[2] = gpio;
    durable.id_cfg[3] = active;
}

static void seed_valid_legacy(uint8_t gpio, uint8_t active) {
    durable.id_cfg_present = false;
    durable.legacy_gpio_present = true;
    durable.legacy_gpio = gpio;
    durable.legacy_active_present = true;
    durable.legacy_active = active;
}

static void clear_observations(void) {
    adv_calls = 0;
    memset(last_adv, 0, sizeof(last_adv));
    gpio_reset_calls = 0;
    gpio_direction_calls = 0;
    gpio_level_calls = 0;
    last_gpio = -1;
    last_gpio_level = -1;
}

static bool label_equals(const char *expected) {
    char actual[64];
    size_t length = pble_dc_label(actual, sizeof(actual));
    return length == strlen(expected) && strcmp(actual, expected) == 0;
}

static bool identify_equals(uint8_t expected_gpio, uint8_t expected_active) {
    uint8_t gpio = 0xffu;
    uint8_t active = 0xffu;
    return pble_dc_identify_led(&gpio, &active) &&
           gpio == expected_gpio && active == expected_active;
}

static bool no_gpio_effect(void) {
    return gpio_reset_calls == 0u && gpio_direction_calls == 0u &&
           gpio_level_calls == 0u;
}

esp_err_t esp_read_mac(uint8_t *mac, int type) {
    if (mac == NULL || type != ESP_MAC_BT) {
        return ESP_FAIL;
    }
    const uint8_t fixed[6] = {0x02u, 0, 0, 0, 0x56u, 0x46u};
    memcpy(mac, fixed, sizeof(fixed));
    return ESP_OK;
}

esp_err_t nvs_open(const char *name, int mode, nvs_handle_t *handle) {
    if (strcmp(name, "pyble") != 0 || handle == NULL) {
        return ESP_FAIL;
    }
    if (mode == NVS_READONLY) {
        *handle = 1u;
        return open_read_rc;
    }
    if (mode == NVS_READWRITE) {
        *handle = 2u;
        if (open_write_rc == ESP_OK) {
            staged = durable;
            staged_open = true;
        }
        return open_write_rc;
    }
    return ESP_FAIL;
}

esp_err_t nvs_get_str(nvs_handle_t handle, const char *key, char *value,
                      size_t *length) {
    if (handle != 1u || strcmp(key, "label") != 0 || length == NULL) {
        return ESP_FAIL;
    }
    if (get_str_rc != ESP_OK) {
        return get_str_rc;
    }
    if (!durable.label_present) {
        return ESP_ERR_NVS_NOT_FOUND;
    }
    size_t needed = strlen(durable.label) + 1u;
    if (value == NULL || *length < needed) {
        *length = needed;
        return ESP_FAIL;
    }
    memcpy(value, durable.label, needed);
    *length = needed;
    return ESP_OK;
}

esp_err_t nvs_get_blob(nvs_handle_t handle, const char *key, void *value,
                       size_t *length) {
    if (handle != 1u || strcmp(key, "id_cfg") != 0 || length == NULL) {
        return ESP_FAIL;
    }
    if (!durable.id_cfg_present) {
        return ESP_ERR_NVS_NOT_FOUND;
    }
    if (value == NULL) {
        if (get_blob_probe_rc != ESP_OK) {
            return get_blob_probe_rc;
        }
        *length = durable.id_cfg_len;
        return ESP_OK;
    }
    if (get_blob_read_rc != ESP_OK) {
        return get_blob_read_rc;
    }
    if (*length < durable.id_cfg_len) {
        *length = durable.id_cfg_len;
        return ESP_FAIL;
    }
    memcpy(value, durable.id_cfg, durable.id_cfg_len);
    *length = durable.id_cfg_len;
    return ESP_OK;
}

esp_err_t nvs_get_u8(nvs_handle_t handle, const char *key, uint8_t *value) {
    if (handle != 1u || value == NULL) {
        return ESP_FAIL;
    }
    if (strcmp(key, "id_gpio") == 0) {
        if (get_gpio_rc != ESP_OK) {
            return get_gpio_rc;
        }
        if (!durable.legacy_gpio_present) {
            return ESP_ERR_NVS_NOT_FOUND;
        }
        *value = durable.legacy_gpio;
        return ESP_OK;
    }
    if (strcmp(key, "id_al") == 0) {
        if (get_active_rc != ESP_OK) {
            return get_active_rc;
        }
        if (!durable.legacy_active_present) {
            return ESP_ERR_NVS_NOT_FOUND;
        }
        *value = durable.legacy_active;
        return ESP_OK;
    }
    return ESP_FAIL;
}

esp_err_t nvs_set_str(nvs_handle_t handle, const char *key, const char *value) {
    if (handle != 2u || !staged_open || strcmp(key, "label") != 0 ||
        value == NULL) {
        return ESP_FAIL;
    }
    if (set_str_rc != ESP_OK) {
        return set_str_rc;
    }
    staged.label_present = true;
    snprintf(staged.label, sizeof(staged.label), "%s", value);
    return ESP_OK;
}

esp_err_t nvs_erase_key(nvs_handle_t handle, const char *key) {
    if (handle != 2u || !staged_open || strcmp(key, "label") != 0) {
        return ESP_FAIL;
    }
    if (erase_rc != ESP_OK) {
        return erase_rc;
    }
    staged.label_present = false;
    staged.label[0] = '\0';
    return ESP_OK;
}

esp_err_t nvs_set_blob(nvs_handle_t handle, const char *key,
                       const void *value, size_t length) {
    if (handle != 2u || !staged_open || strcmp(key, "id_cfg") != 0 ||
        value == NULL || length > sizeof(staged.id_cfg)) {
        return ESP_FAIL;
    }
    if (set_blob_rc != ESP_OK) {
        return set_blob_rc;
    }
    staged.id_cfg_present = true;
    staged.id_cfg_len = length;
    memcpy(staged.id_cfg, value, length);
    return ESP_OK;
}

esp_err_t nvs_commit(nvs_handle_t handle) {
    if (handle != 2u || !staged_open) {
        return ESP_FAIL;
    }
    if (commit_rc != ESP_OK) {
        return commit_rc;
    }
    durable = staged;
    return ESP_OK;
}

void nvs_close(nvs_handle_t handle) {
    if (handle == 2u) {
        staged_open = false;
    }
}

void pble_ble_set_adv_name(const char *name) {
    adv_calls++;
    snprintf(last_adv, sizeof(last_adv), "%s", name == NULL ? "" : name);
}

esp_err_t gpio_reset_pin(int gpio) {
    gpio_reset_calls++;
    last_gpio = gpio;
    return ESP_OK;
}

esp_err_t gpio_set_direction(int gpio, int mode) {
    if (mode != GPIO_MODE_OUTPUT) {
        return ESP_FAIL;
    }
    gpio_direction_calls++;
    last_gpio = gpio;
    return ESP_OK;
}

esp_err_t gpio_set_level(int gpio, int level) {
    gpio_level_calls++;
    last_gpio = gpio;
    last_gpio_level = level;
    return ESP_OK;
}

esp_err_t esp_timer_create(const esp_timer_create_args_t *args,
                           esp_timer_handle_t *timer) {
    if (args == NULL || args->callback == NULL || timer == NULL) {
        return ESP_FAIL;
    }
    *timer = (void *)1;
    return ESP_OK;
}

esp_err_t esp_timer_stop(esp_timer_handle_t timer) {
    (void)timer;
    return ESP_ERR_INVALID_STATE;
}

esp_err_t esp_timer_start_once(esp_timer_handle_t timer, uint64_t timeout_us) {
    (void)timer;
    (void)timeout_us;
    return ESP_OK;
}

esp_err_t esp_timer_start_periodic(esp_timer_handle_t timer,
                                   uint64_t period_us) {
    (void)timer;
    (void)period_us;
    return ESP_OK;
}

int64_t esp_timer_get_time(void) {
    return 1;
}

void esp_restart(void) {
    abort();
}

bool pble_vm_callback_enter(uint64_t epoch, pble_vm_activity_t *activity) {
    if (activity != NULL) {
        activity->epoch = epoch;
        activity->active = true;
    }
    return epoch != 0;
}

void pble_vm_callback_leave(pble_vm_activity_t *activity) {
    if (activity != NULL) {
        activity->active = false;
    }
}

void pble_proto_register(uint8_t opcode, pble_handler_t handler) {
    (void)opcode;
    (void)handler;
}

static int initialize_old_state(void) {
    seed_label("old");
    seed_valid_id(VALID_OLD_GPIO, 1u);
    pble_dc_init();
    CHECK(label_equals("old"), "initial label did not load");
    CHECK(identify_equals(VALID_OLD_GPIO, 1u),
          "initial Identify configuration did not load");
    CHECK(pble_dc_config_fault() == 0u,
          "valid initial state unexpectedly set a fault marker");
    clear_observations();
    return 0;
}

static int check_label_failure(bool clear, esp_err_t write_rc,
                               esp_err_t transaction_commit_rc) {
    CHECK(initialize_old_state() == 0, "initial state failed");
    if (clear) {
        erase_rc = write_rc;
    } else {
        set_str_rc = write_rc;
    }
    commit_rc = transaction_commit_rc;
    const uint8_t replacement[] = "new";
    uint8_t status = pble_dc_set_label(
        clear ? NULL : replacement,
        clear ? 0u : sizeof(replacement) - 1u);
    CHECK(status == PBLE_EIO, "failed label transaction was not EIO");
    CHECK(label_equals("old"), "failed label transaction changed RAM/caps");
    CHECK(durable.label_present && strcmp(durable.label, "old") == 0,
          "failed label transaction changed durable state");
    CHECK(adv_calls == 0u && last_adv[0] == '\0',
          "failed label transaction changed advertisement");
    CHECK(identify_equals(VALID_OLD_GPIO, 1u),
          "label failure changed Identify caps");
    CHECK(no_gpio_effect(), "label failure changed GPIO state");
    CHECK(pble_dc_config_fault() == FAULT_LABEL,
          "label failure changed the wrong fault domain");
    return 0;
}

static int check_identify_failure(bool clear, esp_err_t write_rc,
                                  esp_err_t transaction_commit_rc) {
    CHECK(initialize_old_state() == 0, "initial state failed");
    set_blob_rc = write_rc;
    commit_rc = transaction_commit_rc;
    const uint8_t replacement[2] = {VALID_NEW_GPIO, 0u};
    CHECK(pble_dc_set_identify_led(clear ? NULL : replacement,
                                   clear ? 0u : sizeof(replacement)) == PBLE_EIO,
          "failed Identify transaction was not EIO");
    CHECK(identify_equals(VALID_OLD_GPIO, 1u),
          "failed Identify transaction changed RAM/caps");
    CHECK(durable.id_cfg_present && durable.id_cfg_len == 4u &&
          durable.id_cfg[1] == 1u && durable.id_cfg[2] == VALID_OLD_GPIO &&
          durable.id_cfg[3] == 1u,
          "failed Identify transaction changed durable state");
    CHECK(label_equals("old"), "Identify failure changed label caps");
    CHECK(adv_calls == 0u, "Identify failure changed advertisement");
    CHECK(no_gpio_effect(), "Identify failure changed GPIO state");
    CHECK(pble_dc_config_fault() == FAULT_IDENTIFY,
          "Identify failure changed the wrong fault domain");
    return 0;
}

static int check_authoritative_invalid(const char *scenario) {
    seed_valid_legacy(VALID_OLD_GPIO, 1u);
    durable.id_cfg_present = true;
    durable.id_cfg_len = 4u;
    durable.id_cfg[0] = 1u;
    durable.id_cfg[1] = 1u;
    durable.id_cfg[2] = VALID_NEW_GPIO;
    durable.id_cfg[3] = 0u;
    if (strcmp(scenario, "authoritative-bad-version") == 0) {
        durable.id_cfg[0] = 2u;
    } else if (strcmp(scenario, "authoritative-bad-length") == 0) {
        durable.id_cfg_len = 3u;
    } else if (strcmp(scenario, "authoritative-bad-disabled-shape") == 0) {
        durable.id_cfg[1] = 0u;
        durable.id_cfg[2] = 1u;
    } else if (strcmp(scenario, "authoritative-bad-active-level") == 0) {
        durable.id_cfg[3] = 2u;
    } else if (strcmp(scenario, "authoritative-bad-gpio") == 0) {
        durable.id_cfg[2] = 12u;
    } else if (strcmp(scenario, "authoritative-probe-failure") == 0) {
        get_blob_probe_rc = ESP_FAIL;
    } else if (strcmp(scenario, "authoritative-read-failure") == 0) {
        get_blob_read_rc = ESP_FAIL;
    } else {
        return 90;
    }
    pble_dc_init();
    CHECK(!pble_dc_identify_led(NULL, NULL),
          "invalid authoritative id_cfg fell back to legacy keys");
    CHECK((pble_dc_config_fault() & FAULT_IDENTIFY) != 0u,
          "invalid authoritative id_cfg did not mark Identify fault");
    CHECK(no_gpio_effect(),
          "invalid authoritative id_cfg configured or drove legacy GPIO");
    return 0;
}

static int check_legacy(const char *scenario) {
    durable.id_cfg_present = false;
    if (strcmp(scenario, "legacy-valid") == 0) {
        seed_valid_legacy(VALID_OLD_GPIO, 1u);
    } else if (strcmp(scenario, "legacy-both-missing") == 0) {
        /* Clean first boot: neither legacy key exists. */
    } else if (strcmp(scenario, "legacy-missing-gpio") == 0) {
        durable.legacy_active_present = true;
        durable.legacy_active = 1u;
    } else if (strcmp(scenario, "legacy-missing-active-level") == 0) {
        durable.legacy_gpio_present = true;
        durable.legacy_gpio = VALID_OLD_GPIO;
    } else if (strcmp(scenario, "legacy-bad-active-level") == 0) {
        seed_valid_legacy(VALID_OLD_GPIO, 2u);
    } else if (strcmp(scenario, "legacy-bad-gpio") == 0) {
        seed_valid_legacy(12u, 1u);
    } else if (strcmp(scenario, "legacy-gpio-read-failure") == 0) {
        seed_valid_legacy(VALID_OLD_GPIO, 1u);
        get_gpio_rc = ESP_FAIL;
    } else if (strcmp(scenario, "legacy-active-read-failure") == 0) {
        seed_valid_legacy(VALID_OLD_GPIO, 1u);
        get_active_rc = ESP_FAIL;
    } else {
        return 91;
    }
    pble_dc_init();
    if (strcmp(scenario, "legacy-valid") == 0) {
        CHECK(identify_equals(VALID_OLD_GPIO, 1u),
              "wholly valid legacy pair was not accepted");
        CHECK((pble_dc_config_fault() & FAULT_IDENTIFY) == 0u,
              "wholly valid legacy pair set an Identify fault");
        CHECK(gpio_reset_calls == 1u && gpio_direction_calls == 1u &&
              gpio_level_calls == 1u && last_gpio == VALID_OLD_GPIO,
              "wholly valid legacy pair did not configure its GPIO once");
    } else if (strcmp(scenario, "legacy-both-missing") == 0) {
        CHECK(!pble_dc_identify_led(NULL, NULL),
              "missing legacy keys unexpectedly configured Identify");
        CHECK((pble_dc_config_fault() & FAULT_IDENTIFY) == 0u,
              "clean first boot was classified as corruption");
        CHECK(no_gpio_effect(), "missing legacy keys changed GPIO state");
    } else {
        CHECK(!pble_dc_identify_led(NULL, NULL),
              "partial or invalid legacy keys configured Identify");
        CHECK((pble_dc_config_fault() & FAULT_IDENTIFY) != 0u,
              "partial or invalid legacy keys did not mark Identify fault");
        CHECK(no_gpio_effect(), "partial or invalid legacy keys changed GPIO");
    }
    return 0;
}

static int repair_label_only(void) {
    seed_label("old");
    durable.id_cfg_present = true;
    durable.id_cfg_len = 4u;
    durable.id_cfg[0] = 2u; /* authoritative Identify corruption */
    pble_dc_init();
    CHECK(pble_dc_config_fault() == FAULT_IDENTIFY,
          "initial Identify fault was not isolated");
    clear_observations();

    set_str_rc = ESP_FAIL;
    CHECK(pble_dc_set_label((const uint8_t *)"new", 3u) == PBLE_EIO,
          "synthetic label failure was not EIO");
    CHECK(pble_dc_config_fault() == (FAULT_LABEL | FAULT_IDENTIFY),
          "synthetic label failure did not latch both domains");
    CHECK(label_equals("old") && adv_calls == 0u,
          "failed label repair changed runtime state");

    set_str_rc = ESP_OK;
    CHECK(pble_dc_set_label((const uint8_t *)"new", 3u) == PBLE_OK,
          "successful label repair failed");
    CHECK(label_equals("new") && durable.label_present &&
          strcmp(durable.label, "new") == 0,
          "successful label repair did not publish committed value");
    CHECK(adv_calls == 1u && strcmp(last_adv, "new") == 0,
          "successful label repair did not update advertisement exactly once");
    CHECK(pble_dc_config_fault() == FAULT_IDENTIFY,
          "label repair cleared another configuration domain");
    CHECK(!pble_dc_identify_led(NULL, NULL) && no_gpio_effect(),
          "label repair changed failed-closed Identify state");
    return 0;
}

static int repair_identify_only(void) {
    seed_label("unsafe\nlabel"); /* strict label load failure */
    seed_valid_id(VALID_OLD_GPIO, 1u);
    pble_dc_init();
    CHECK(pble_dc_config_fault() == FAULT_LABEL,
          "initial label fault was not isolated");
    CHECK(identify_equals(VALID_OLD_GPIO, 1u),
          "initial valid Identify state did not load");
    clear_observations();

    const uint8_t replacement[2] = {VALID_NEW_GPIO, 0u};
    set_blob_rc = ESP_FAIL;
    CHECK(pble_dc_set_identify_led(replacement, sizeof(replacement)) == PBLE_EIO,
          "synthetic Identify failure was not EIO");
    CHECK(pble_dc_config_fault() == (FAULT_LABEL | FAULT_IDENTIFY),
          "synthetic Identify failure did not latch both domains");
    CHECK(identify_equals(VALID_OLD_GPIO, 1u) && no_gpio_effect(),
          "failed Identify repair changed runtime/GPIO state");

    set_blob_rc = ESP_OK;
    CHECK(pble_dc_set_identify_led(replacement, sizeof(replacement)) == PBLE_OK,
          "successful Identify repair failed");
    CHECK(identify_equals(VALID_NEW_GPIO, 0u),
          "successful Identify repair did not publish committed caps");
    CHECK(durable.id_cfg_present && durable.id_cfg[2] == VALID_NEW_GPIO &&
          durable.id_cfg[3] == 0u,
          "successful Identify repair did not update durable state");
    CHECK(gpio_reset_calls == 1u && gpio_direction_calls == 1u &&
          gpio_level_calls >= 2u && last_gpio == VALID_NEW_GPIO,
          "successful Identify repair did not apply GPIO after commit");
    CHECK(pble_dc_config_fault() == FAULT_LABEL,
          "Identify repair cleared another configuration domain");
    CHECK(label_equals("") && adv_calls == 0u,
          "Identify repair changed failed-closed label/advertisement state");
    return 0;
}

int main(int argc, char **argv) {
    if (argc != 2) {
        return 64;
    }
    backend_defaults();
    const char *scenario = argv[1];
    if (strcmp(scenario, "label-set-failure") == 0) {
        return check_label_failure(false, ESP_FAIL, ESP_OK);
    }
    if (strcmp(scenario, "label-erase-failure") == 0) {
        return check_label_failure(true, ESP_FAIL, ESP_OK);
    }
    if (strcmp(scenario, "label-commit-failure") == 0) {
        return check_label_failure(false, ESP_OK, ESP_FAIL);
    }
    if (strcmp(scenario, "label-clear-commit-failure") == 0) {
        return check_label_failure(true, ESP_OK, ESP_FAIL);
    }
    if (strcmp(scenario, "identify-set-failure") == 0) {
        return check_identify_failure(false, ESP_FAIL, ESP_OK);
    }
    if (strcmp(scenario, "identify-commit-failure") == 0) {
        return check_identify_failure(false, ESP_OK, ESP_FAIL);
    }
    if (strcmp(scenario, "identify-clear-set-failure") == 0) {
        return check_identify_failure(true, ESP_FAIL, ESP_OK);
    }
    if (strcmp(scenario, "identify-clear-commit-failure") == 0) {
        return check_identify_failure(true, ESP_OK, ESP_FAIL);
    }
    if (strncmp(scenario, "authoritative-", 14u) == 0) {
        return check_authoritative_invalid(scenario);
    }
    if (strncmp(scenario, "legacy-", 7u) == 0) {
        return check_legacy(scenario);
    }
    if (strcmp(scenario, "repair-label-only") == 0) {
        return repair_label_only();
    }
    if (strcmp(scenario, "repair-identify-only") == 0) {
        return repair_identify_only();
    }
    return 65;
}
"""


if __name__ == "__main__":
    unittest.main(verbosity=2)

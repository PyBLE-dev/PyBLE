#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.

"""[red] compiled ESP autorun persistence/cache contract for v0.6.1.

The production ``pble_boot`` core is compiled against a deterministic fake NVS
backend.  This keeps the regression at the native state boundary: the first
autorun observation loads persisted state, later observations use that cached
state, and only a successful set+commit transaction may publish a new runtime
value.
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
BOOT = NATIVE / "pble_boot.c"


class NativeAutorunPersistenceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = shutil.which(os.environ.get("CC", "cc"))
        if compiler is None:
            raise unittest.SkipTest("a host C compiler is required")

        source = BOOT.read_text(encoding="utf-8", errors="strict")
        marker = "// Thin MicroPython surface (boot wiring)"
        if marker not in source:
            raise AssertionError("pble_boot native-core boundary is missing")
        # Compile the production persistence and autorun core verbatim.  The
        # MicroPython module-object declarations below this marker need the
        # complete target ABI but do not participate in this state contract.
        core = source.partition(marker)[0]

        cls._temporary = tempfile.TemporaryDirectory(
            prefix="pyble-v061-native-autorun-"
        )
        temp = Path(cls._temporary.name)
        (temp / "py").mkdir()
        (temp / "nvs.h").write_text(NVS_STUB, encoding="utf-8")
        (temp / "py" / "runtime.h").write_text(
            "#ifndef MP_RUNTIME_H\n#define MP_RUNTIME_H\n#endif\n",
            encoding="utf-8",
        )
        (temp / "py" / "obj.h").write_text(
            "#ifndef MP_OBJ_H\n#define MP_OBJ_H\n#endif\n",
            encoding="utf-8",
        )
        (temp / "py" / "builtin.h").write_text(
            BUILTIN_STUB, encoding="utf-8"
        )

        harness = temp / "native_autorun_harness.c"
        harness.write_text(core + HARNESS, encoding="utf-8")
        cls._executable = temp / "native_autorun_harness"
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
                "native autorun harness did not compile:\n"
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
            "native autorun scenario {!r} failed:\n{}{}".format(
                scenario, completed.stdout, completed.stderr
            ),
        )

    def test_startup_load_is_cached_after_one_nvs_read(self):
        self.run_scenario("cache")

    def test_successful_commit_publishes_the_new_cached_value(self):
        self.run_scenario("success")

    def test_set_failure_keeps_the_prior_runtime_value(self):
        self.run_scenario("set-failure")

    def test_commit_failure_keeps_the_prior_runtime_value(self):
        self.run_scenario("commit-failure")


NVS_STUB = r"""
#ifndef NVS_H
#define NVS_H
#include <stdint.h>
typedef int esp_err_t;
typedef unsigned nvs_handle_t;
#define ESP_OK 0
#define ESP_FAIL (-1)
#define ESP_ERR_NVS_NOT_FOUND 0x1102
#define NVS_READONLY 1
#define NVS_READWRITE 2
esp_err_t nvs_open(const char *name, int mode, nvs_handle_t *handle);
esp_err_t nvs_get_u8(nvs_handle_t handle, const char *key, uint8_t *value);
esp_err_t nvs_set_u8(nvs_handle_t handle, const char *key, uint8_t value);
esp_err_t nvs_commit(nvs_handle_t handle);
void nvs_close(nvs_handle_t handle);
#endif
"""


BUILTIN_STUB = r"""
#ifndef MP_BUILTIN_H
#define MP_BUILTIN_H
#define MP_IMPORT_STAT_FILE 1
int mp_import_stat(const char *path);
#endif
"""


HARNESS = r"""

#include <stdio.h>
#include <string.h>

static uint8_t durable_autorun = 1u;
static uint8_t staged_autorun;
static bool staged_valid;
static esp_err_t read_open_result = ESP_OK;
static esp_err_t write_open_result = ESP_OK;
static esp_err_t get_result = ESP_OK;
static esp_err_t set_result = ESP_OK;
static esp_err_t commit_result = ESP_OK;
static unsigned read_open_calls;
static unsigned write_open_calls;
static unsigned get_calls;
static unsigned set_calls;
static unsigned commit_calls;
static unsigned register_calls;

#define CHECK(condition, message) do {                                      \
    if (!(condition)) {                                                     \
        fprintf(stderr, "%s\n", (message));                               \
        return 1;                                                           \
    }                                                                       \
} while (0)

esp_err_t nvs_open(const char *name, int mode, nvs_handle_t *handle) {
    if (strcmp(name, "pyble") != 0) {
        return ESP_FAIL;
    }
    *handle = 1u;
    if (mode == NVS_READONLY) {
        read_open_calls++;
        return read_open_result;
    }
    write_open_calls++;
    return write_open_result;
}

esp_err_t nvs_get_u8(nvs_handle_t handle, const char *key, uint8_t *value) {
    (void)handle;
    if (strcmp(key, "autorun") != 0) {
        return ESP_FAIL;
    }
    get_calls++;
    if (get_result == ESP_OK) {
        *value = durable_autorun;
    }
    return get_result;
}

esp_err_t nvs_set_u8(nvs_handle_t handle, const char *key, uint8_t value) {
    (void)handle;
    if (strcmp(key, "autorun") != 0) {
        return ESP_FAIL;
    }
    set_calls++;
    if (set_result == ESP_OK) {
        staged_autorun = value;
        staged_valid = true;
    }
    return set_result;
}

esp_err_t nvs_commit(nvs_handle_t handle) {
    (void)handle;
    commit_calls++;
    if (commit_result == ESP_OK && staged_valid) {
        durable_autorun = staged_autorun;
        staged_valid = false;
    }
    return commit_result;
}

void nvs_close(nvs_handle_t handle) {
    (void)handle;
    staged_valid = false;
}

void pble_proto_register(uint8_t opcode, pble_handler_t handler) {
    if (opcode == PBLE_OP_SET_AUTORUN && handler == pble_boot_set_autorun_cmd) {
        register_calls++;
    }
}

int mp_import_stat(const char *path) {
    (void)path;
    return 0;
}

uint8_t pble_runner_run_file(const char *path) {
    (void)path;
    return PBLE_OK;
}

static int initialize_enabled(void) {
    CHECK(pble_boot_autorun_enabled(),
          "initial persisted autorun=1 was not loaded");
    CHECK(read_open_calls == 1u && get_calls == 1u,
          "initial autorun observation must read NVS exactly once");
    return 0;
}

static int scenario_cache(void) {
    CHECK(initialize_enabled() == 0, "initial cache load failed");
    durable_autorun = 0u;
    get_result = ESP_FAIL;
    CHECK(pble_boot_autorun_enabled(),
          "a later NVS change/failure replaced the cached runtime value");
    CHECK(pble_boot_autorun_enabled(),
          "repeated capability reads did not retain the cached value");
    CHECK(read_open_calls == 1u && get_calls == 1u,
          "runtime autorun queries reopened NVS after initialization");
    return 0;
}

static int scenario_success(void) {
    CHECK(initialize_enabled() == 0, "initial cache load failed");
    CHECK(pble_boot_set_autorun(false) == PBLE_OK,
          "successful disable did not return PBLE_OK");
    CHECK(durable_autorun == 0u,
          "successful disable was not durably committed");
    CHECK(!pble_boot_autorun_enabled(),
          "successful disable did not publish the cached runtime value");
    CHECK(read_open_calls == 1u && get_calls == 1u,
          "successful set forced a second NVS read instead of publishing RAM");
    CHECK(write_open_calls == 1u && set_calls == 1u && commit_calls == 1u,
          "successful set did not perform exactly one write transaction");

    CHECK(pble_boot_set_autorun(true) == PBLE_OK,
          "successful enable did not return PBLE_OK");
    CHECK(durable_autorun == 1u && pble_boot_autorun_enabled(),
          "successful enable did not update durable and cached state");
    CHECK(read_open_calls == 1u && get_calls == 1u,
          "successful enable forced a second NVS read");
    CHECK(pble_boot_config_fault() == 0u,
          "successful persistence did not clear the bounded fault marker");
    return 0;
}

static int scenario_set_failure(void) {
    CHECK(initialize_enabled() == 0, "initial cache load failed");
    set_result = ESP_FAIL;
    CHECK(pble_boot_set_autorun(false) == PBLE_EIO,
          "failed nvs_set_u8 did not return PBLE_EIO");
    CHECK(durable_autorun == 1u && commit_calls == 0u,
          "failed nvs_set_u8 changed persistence or attempted commit");
    get_result = ESP_FAIL;
    CHECK(pble_boot_autorun_enabled(),
          "failed nvs_set_u8 changed the prior runtime autorun value");
    CHECK(read_open_calls == 1u && get_calls == 1u,
          "set failure made runtime behavior depend on a later NVS read");
    CHECK(pble_boot_config_fault() != 0u,
          "set failure did not latch the bounded fault marker");
    return 0;
}

static int scenario_commit_failure(void) {
    CHECK(initialize_enabled() == 0, "initial cache load failed");
    commit_result = ESP_FAIL;
    CHECK(pble_boot_set_autorun(false) == PBLE_EIO,
          "failed nvs_commit did not return PBLE_EIO");
    CHECK(durable_autorun == 1u && set_calls == 1u && commit_calls == 1u,
          "failed commit changed durable state or skipped the transaction");
    get_result = ESP_FAIL;
    CHECK(pble_boot_autorun_enabled(),
          "failed nvs_commit changed the prior runtime autorun value");
    CHECK(read_open_calls == 1u && get_calls == 1u,
          "commit failure made runtime behavior depend on a later NVS read");
    CHECK(pble_boot_config_fault() != 0u,
          "commit failure did not latch the bounded fault marker");
    return 0;
}

int main(int argc, char **argv) {
    if (argc != 2) {
        fputs("expected exactly one scenario\n", stderr);
        return 2;
    }
    pble_boot_register();
    CHECK(register_calls == 1u, "SET_AUTORUN handler was not registered");
    if (strcmp(argv[1], "cache") == 0) {
        return scenario_cache();
    }
    if (strcmp(argv[1], "success") == 0) {
        return scenario_success();
    }
    if (strcmp(argv[1], "set-failure") == 0) {
        return scenario_set_failure();
    }
    if (strcmp(argv[1], "commit-failure") == 0) {
        return scenario_commit_failure();
    }
    fputs("unknown scenario\n", stderr);
    return 2;
}
"""


if __name__ == "__main__":
    unittest.main(verbosity=2)

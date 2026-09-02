// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.
//
// pble_boot — cold-boot safety + opt-in /main.py auto-run (F-12). See pble_boot.h.
//
// DESIGN (fail-safe, lean): the auto-run flag is a single NVS byte in the shared
// "pyble" namespace (default 0 = off), so a fresh/unowned board never auto-runs
// (SEC-6, FR-BOOT-1/2). pble_boot_maybe_autorun is the ONLY place that starts a
// program at boot; it is self-guarded (no-op unless BOTH the flag is on AND
// /main.py exists) and hands the file to the runner WORKER — it never runs user
// code inline, so a broken/looping /main.py cannot wedge the agent (FR-BOOT-4/6,
// NFR-SAFE-2/3). The existence pre-check uses mp_import_stat (the VFS import-stat),
// which requires a valid MP thread + GIL — guaranteed because the MP module wrapper
// is invoked from _boot.py on the main task after the workers are up.
//
// Clean-room: authored fresh against protocol.md §4/§7 + the public MicroPython /
// ESP-IDF NVS API. No proprietary source is referenced.
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <string.h>

#include "nvs.h"             // NVS autorun byte (namespace shared with identity)

#include "py/runtime.h"      // mp module machinery
#include "py/obj.h"
#include "py/builtin.h"      // mp_import_stat / MP_IMPORT_STAT_FILE (VFS import-stat)

#include "pble_boot.h"
#include "pble_runner.h"     // pble_runner_run_file — hand /main.py to the WORKER

#define BOOT_NS          "pyble"     // shared device-config NVS namespace
#define BOOT_KEY_AUTORUN "autorun"   // u8: 0 = off (default), 1 = on
#define BOOT_MAIN_PATH   "/main.py"  // the opt-in auto-run entry at fs_root

enum {
    BOOT_CONFIG_OK = 0,
    BOOT_CONFIG_CORRUPT = 1,
};
static uint8_t boot_config_fault;
static bool boot_autorun_loaded;
static bool boot_autorun_cached;

// --- Persisted opt-in flag (FR-BOOT-3) ---------------------------------------
bool pble_boot_autorun_enabled(void) {
    if (boot_autorun_loaded) {
        return boot_autorun_cached;
    }
    uint8_t v = 0;                      // default off if the key is absent
    nvs_handle_t h;
    esp_err_t open_rc = nvs_open(BOOT_NS, NVS_READONLY, &h);
    if (open_rc == ESP_ERR_NVS_NOT_FOUND) {
        // A never-created namespace is the clean erased-device first boot,
        // not evidence of corrupt persisted configuration.
        boot_autorun_loaded = true;
        return false;
    }
    if (open_rc != ESP_OK) {
        boot_config_fault = BOOT_CONFIG_CORRUPT;
        boot_autorun_loaded = true;
        return false;
    }
    esp_err_t rc = nvs_get_u8(h, BOOT_KEY_AUTORUN, &v);
    nvs_close(h);
    if (rc == ESP_ERR_NVS_NOT_FOUND) {
        boot_autorun_loaded = true;
        return false;
    }
    if (rc != ESP_OK || v > 1) {
        boot_config_fault = BOOT_CONFIG_CORRUPT;
        boot_autorun_loaded = true;
        return false;
    }
    boot_autorun_cached = v == 1;
    boot_autorun_loaded = true;
    return v == 1;
}

uint8_t pble_boot_config_fault(void) {
    return boot_config_fault;
}

uint8_t pble_boot_set_autorun(bool enable) {
    // Establish the prior runtime value before beginning the transaction. NVS
    // write/commit failure must leave that value observable through caps,
    // DEVICE_INFO, and boot admission for the rest of this boot.
    if (!boot_autorun_loaded) {
        (void)pble_boot_autorun_enabled();
    }
    nvs_handle_t h;
    if (nvs_open(BOOT_NS, NVS_READWRITE, &h) != ESP_OK) {
        boot_config_fault = BOOT_CONFIG_CORRUPT;
        return PBLE_EIO;
    }
    uint8_t st = PBLE_OK;
    if (nvs_set_u8(h, BOOT_KEY_AUTORUN, enable ? 1 : 0) != ESP_OK) {
        st = PBLE_EIO;
    } else {
        esp_err_t commit_rc = nvs_commit(h);
        if (commit_rc != ESP_OK) {
            st = PBLE_EIO;
        }
    }
    nvs_close(h);
    if (st == PBLE_OK) {
        boot_autorun_cached = enable;
        boot_autorun_loaded = true;
    }
    boot_config_fault = st == PBLE_OK ? BOOT_CONFIG_OK : BOOT_CONFIG_CORRUPT;
    return st;
}

uint8_t pble_boot_set_autorun_cmd(const pble_frame_t *req, uint8_t *rsp,
                                  size_t *rsp_len,
                                  const pble_session_token_t *session) {
    (void)rsp;
    (void)session;
    if (rsp_len) {
        *rsp_len = 0;                   // RSP{status} carries no extra bytes
    }
    // §4 SET_AUTORUN payload is exactly one Boolean-domain byte.
    if (req == NULL || req->payload == NULL || req->len != 1 ||
        req->payload[0] > 1) {
        return PBLE_EBADREQ;
    }
    return pble_boot_set_autorun(req->payload[0] == 1);
}

// --- Opt-in auto-run at boot (FR-BOOT-3/4/6, FR-MODE-1) -----------------------
void pble_boot_maybe_autorun(void) {
    if (!pble_boot_autorun_enabled()) {
        return;                         // opt-out (default): stay advertise-and-wait
    }
    // Self-guard: only auto-run a /main.py that actually exists as a file, so a
    // board with the flag on but no /main.py stays at RUN_STATE idle (no spurious
    // error transition). mp_import_stat is the VFS import-stat — safe here because
    // this runs on a valid MP thread (the _boot.py main task, after the worker up).
    if (mp_import_stat(BOOT_MAIN_PATH) != MP_IMPORT_STAT_FILE) {
        return;
    }
    // Hand /main.py to the runner WORKER — never execute inline. Status is ignored:
    // if the runner is somehow already busy we simply skip (fail-safe, no wedge).
    (void)pble_runner_run_file(BOOT_MAIN_PATH);
}

void pble_boot_register(void) {
    pble_proto_register(PBLE_OP_SET_AUTORUN, pble_boot_set_autorun_cmd);
}

// ============================================================================
// Thin MicroPython surface (boot wiring)
// ============================================================================
// _boot.py calls pble_boot.maybe_autorun() on the MAIN task AFTER init_agent() and
// AFTER the runner worker is launched — the only VM-safe site for the VFS import-stat
// and the runner hand-off. register() is idempotent (called from init_agent at boot).
static mp_obj_t mod_pble_boot_maybe_autorun(void) {
    pble_boot_maybe_autorun();
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_0(mod_pble_boot_maybe_autorun_obj, mod_pble_boot_maybe_autorun);

static mp_obj_t mod_pble_boot_register(void) {
    pble_boot_register();
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_0(mod_pble_boot_register_obj, mod_pble_boot_register);

static const mp_rom_map_elem_t pble_boot_globals_table[] = {
    { MP_ROM_QSTR(MP_QSTR___name__), MP_ROM_QSTR(MP_QSTR_pble_boot) },
    { MP_ROM_QSTR(MP_QSTR_maybe_autorun), MP_ROM_PTR(&mod_pble_boot_maybe_autorun_obj) },
    { MP_ROM_QSTR(MP_QSTR_register), MP_ROM_PTR(&mod_pble_boot_register_obj) },
};
static MP_DEFINE_CONST_DICT(pble_boot_globals, pble_boot_globals_table);

const mp_obj_module_t pble_boot_user_cmodule = {
    .base = { &mp_type_module },
    .globals = (mp_obj_dict_t *)&pble_boot_globals,
};

MP_REGISTER_MODULE(MP_QSTR_pble_boot, pble_boot_user_cmodule);

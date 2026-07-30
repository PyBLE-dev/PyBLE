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

// --- Persisted opt-in flag (FR-BOOT-3) ---------------------------------------
bool pble_boot_autorun_enabled(void) {
    uint8_t v = 0;                      // default off if the key is absent
    nvs_handle_t h;
    if (nvs_open(BOOT_NS, NVS_READONLY, &h) == ESP_OK) {
        (void)nvs_get_u8(h, BOOT_KEY_AUTORUN, &v);   // leaves 0 if not found
        nvs_close(h);
    }
    return v != 0;
}

uint8_t pble_boot_set_autorun(bool enable) {
    nvs_handle_t h;
    if (nvs_open(BOOT_NS, NVS_READWRITE, &h) != ESP_OK) {
        return PBLE_EIO;
    }
    uint8_t st = PBLE_OK;
    if (nvs_set_u8(h, BOOT_KEY_AUTORUN, enable ? 1 : 0) != ESP_OK) {
        st = PBLE_EIO;
    } else {
        (void)nvs_commit(h);
    }
    nvs_close(h);
    return st;
}

uint8_t pble_boot_set_autorun_cmd(const pble_frame_t *req, uint8_t *rsp,
                                  size_t *rsp_len, uint16_t conn) {
    (void)rsp;
    (void)conn;
    if (rsp_len) {
        *rsp_len = 0;                   // RSP{status} carries no extra bytes
    }
    // §4 SET_AUTORUN payload = [enable:u8]; anything shorter is malformed.
    if (req == NULL || req->payload == NULL || req->len < 1) {
        return PBLE_EBADREQ;
    }
    return pble_boot_set_autorun(req->payload[0] != 0);
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

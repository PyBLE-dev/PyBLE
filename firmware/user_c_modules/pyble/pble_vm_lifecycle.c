// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

#include "pble_vm_lifecycle.h"

#include <limits.h>

#include "esp_system.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "py/mpstate.h"
#include "py/obj.h"

#include "pble_ble.h"
#include "pble_console.h"
#include "pble_device_config.h"
#include "pble_fs.h"
#include "pble_proto.h"
#include "pble_runner.h"

#define PBLE_VM_DEINIT_BUDGET_MS 2500u

static portMUX_TYPE pble_vm_mux = portMUX_INITIALIZER_UNLOCKED;
static uint64_t pble_vm_epoch;
static uint32_t pble_vm_activity_count;
static uint32_t pble_vm_worker_mask;
static bool pble_vm_lifecycle_active;
static bool pble_vm_dispatch_open;
static bool pble_vm_non_reboot_open;

static bool pble_vm_activity_enter_locked(uint64_t expected_epoch,
                                          bool require_dispatch,
                                          pble_vm_activity_t *activity) {
    if (activity == NULL || !pble_vm_lifecycle_active ||
        (require_dispatch && !pble_vm_dispatch_open) ||
        expected_epoch != pble_vm_epoch) {
        return false;
    }
    if (pble_vm_activity_count == UINT32_MAX) {
        esp_restart();
        return false;
    }
    pble_vm_activity_count++;
    activity->epoch = pble_vm_epoch;
    activity->active = true;
    return true;
}

uint64_t pble_vm_epoch_current(void) {
    uint64_t epoch;
    taskENTER_CRITICAL(&pble_vm_mux);
    epoch = pble_vm_epoch;
    taskEXIT_CRITICAL(&pble_vm_mux);
    return epoch;
}

bool pble_vm_epoch_valid(uint64_t epoch) {
    bool valid;
    taskENTER_CRITICAL(&pble_vm_mux);
    valid = pble_vm_lifecycle_active && epoch != 0 && epoch == pble_vm_epoch;
    taskEXIT_CRITICAL(&pble_vm_mux);
    return valid;
}

bool pble_vm_admission_ready(void) {
    bool ready;
    taskENTER_CRITICAL(&pble_vm_mux);
    ready = pble_vm_lifecycle_active && pble_vm_dispatch_open;
    taskEXIT_CRITICAL(&pble_vm_mux);
    return ready;
}

bool pble_vm_dispatch_enter(uint64_t expected_epoch,
                            pble_vm_activity_t *activity) {
    bool entered;
    taskENTER_CRITICAL(&pble_vm_mux);
    if (pble_vm_activity_count == UINT32_MAX) {
        taskEXIT_CRITICAL(&pble_vm_mux);
        esp_restart();
        return false;
    }
    entered = pble_vm_activity_enter_locked(expected_epoch, true, activity);
    taskEXIT_CRITICAL(&pble_vm_mux);
    return entered;
}

void pble_vm_dispatch_leave(pble_vm_activity_t *activity) {
    taskENTER_CRITICAL(&pble_vm_mux);
    if (activity == NULL || !activity->active ||
        activity->epoch != pble_vm_epoch || pble_vm_activity_count <= 0) {
        taskEXIT_CRITICAL(&pble_vm_mux);
        esp_restart();
        return;
    }
    activity->active = false;
    pble_vm_activity_count--;
    taskEXIT_CRITICAL(&pble_vm_mux);
}

bool pble_vm_callback_enter(uint64_t epoch, pble_vm_activity_t *activity) {
    bool entered;
    taskENTER_CRITICAL(&pble_vm_mux);
    entered = pble_vm_activity_enter_locked(epoch, false, activity);
    taskEXIT_CRITICAL(&pble_vm_mux);
    return entered;
}

void pble_vm_callback_leave(pble_vm_activity_t *activity) {
    pble_vm_dispatch_leave(activity);
}

bool pble_vm_rx_callback_enter(pble_vm_activity_t *activity) {
    bool entered;
    taskENTER_CRITICAL(&pble_vm_mux);
    if (!pble_vm_lifecycle_active || !pble_vm_dispatch_open) {
        pble_ble_vm_rx_reset();
        entered = false;
    } else {
        entered = pble_vm_activity_enter_locked(pble_vm_epoch, true, activity);
    }
    taskEXIT_CRITICAL(&pble_vm_mux);
    return entered;
}

void pble_vm_close_admission(void) {
    taskENTER_CRITICAL(&pble_vm_mux);
    pble_vm_dispatch_open = false;
    pble_vm_lifecycle_active = false;
    pble_vm_non_reboot_open = false;
    taskEXIT_CRITICAL(&pble_vm_mux);
}

void pble_vm_open_admission(void) {
    taskENTER_CRITICAL(&pble_vm_mux);
    if (pble_vm_epoch != 0) {
        pble_vm_lifecycle_active = true;
        pble_vm_dispatch_open = true;
        pble_vm_non_reboot_open = true;
    }
    taskEXIT_CRITICAL(&pble_vm_mux);
}

bool pble_vm_reboot_close(uint64_t epoch) {
    bool closed = false;
    taskENTER_CRITICAL(&pble_vm_mux);
    if (pble_vm_lifecycle_active && pble_vm_dispatch_open &&
        pble_vm_non_reboot_open && epoch == pble_vm_epoch) {
        pble_vm_non_reboot_open = false;
        closed = true;
    }
    taskEXIT_CRITICAL(&pble_vm_mux);
    return closed;
}

void pble_vm_reboot_abort(uint64_t epoch) {
    taskENTER_CRITICAL(&pble_vm_mux);
    if (pble_vm_lifecycle_active && epoch == pble_vm_epoch) {
        pble_vm_non_reboot_open = true;
    }
    taskEXIT_CRITICAL(&pble_vm_mux);
}

bool pble_vm_reboot_command_admitted(bool is_soft_reboot) {
    bool admitted;
    taskENTER_CRITICAL(&pble_vm_mux);
    admitted = pble_vm_lifecycle_active && pble_vm_dispatch_open &&
               (pble_vm_non_reboot_open || is_soft_reboot);
    taskEXIT_CRITICAL(&pble_vm_mux);
    return admitted;
}

bool pble_vm_wait_activity_idle(int64_t deadline_us) {
    for (;;) {
        uint32_t count;
        taskENTER_CRITICAL(&pble_vm_mux);
        count = pble_vm_activity_count;
        taskEXIT_CRITICAL(&pble_vm_mux);
        if (esp_timer_get_time() >= deadline_us) {
            esp_restart();
            return false;
        }
        if (count == 0) {
            return true;
        }
        vTaskDelay(1);
    }
}

bool pble_vm_wait_ready_epoch(uint64_t epoch) {
    for (;;) {
        bool ready;
        bool valid;
        taskENTER_CRITICAL(&pble_vm_mux);
        valid = pble_vm_lifecycle_active && epoch == pble_vm_epoch;
        ready = valid && pble_vm_dispatch_open;
        taskEXIT_CRITICAL(&pble_vm_mux);
        if (!valid || ready) {
            return ready;
        }
        vTaskDelay(1);
    }
}

void pble_vm_worker_ready(uint32_t worker) {
    taskENTER_CRITICAL(&pble_vm_mux);
    if (pble_vm_lifecycle_active) {
        pble_vm_worker_mask |= worker;
    }
    taskEXIT_CRITICAL(&pble_vm_mux);
}

bool pble_vm_ready(int64_t deadline_us) {
    const uint32_t required = PBLE_VM_WORKER_RUNNER | PBLE_VM_WORKER_FS;
    for (;;) {
        uint32_t workers;
        taskENTER_CRITICAL(&pble_vm_mux);
        workers = pble_vm_worker_mask;
        taskEXIT_CRITICAL(&pble_vm_mux);
        if ((workers & required) == required) {
            pble_ble_vm_enable_response_callout();
            pble_vm_open_admission();
            return true;
        }
        if (esp_timer_get_time() >= deadline_us) {
            return false;
        }
        vTaskDelay(1);
    }
}

void pble_vm_restart_if_closing(void) {
    if (pble_ble_session_closing()) {
        esp_restart();
    }
}

void pble_vm_epoch_begin(void) {
    pble_vm_restart_if_closing();

    taskENTER_CRITICAL(&pble_vm_mux);
    if (pble_vm_activity_count != 0) {
        taskEXIT_CRITICAL(&pble_vm_mux);
        esp_restart();
        return;
    }
    pble_vm_epoch++;
    if (pble_vm_epoch == 0) {
        pble_vm_epoch++;
    }
    uint64_t epoch = pble_vm_epoch;
    pble_vm_worker_mask = 0;
    pble_vm_lifecycle_active = true;
    pble_vm_dispatch_open = false;
    pble_vm_non_reboot_open = false;
    taskEXIT_CRITICAL(&pble_vm_mux);

    MP_STATE_VM(pble_runner_sysexit) = MP_OBJ_NULL;
    MP_STATE_VM(pble_fs_put_file) = MP_OBJ_NULL;
    pble_ble_vm_reset(epoch);
    pble_fs_vm_reset();
    pble_runner_vm_reset();
    pble_console_vm_reset();
}

void pble_vm_epoch_pre_deinit(void) {
    pble_vm_restart_if_closing();
    pble_vm_close_admission();
    pble_ble_vm_invalidate_session();
    int64_t deadline_us = esp_timer_get_time() +
                          (int64_t)PBLE_VM_DEINIT_BUDGET_MS * INT64_C(1000);
    if (!pble_vm_wait_activity_idle(deadline_us) ||
        !pble_runner_vm_timer_disarm(deadline_us) ||
        !pble_dc_vm_timer_disarm(deadline_us) ||
        !pble_ble_vm_stop_response_callout(deadline_us) ||
        !pble_ble_vm_tx_lock(deadline_us)) {
        esp_restart();
        return;
    }
    pble_vm_restart_if_closing();
    pble_runner_vm_detach();
    pble_console_vm_detach();
    MP_STATE_VM(pble_runner_sysexit) = MP_OBJ_NULL;
    MP_STATE_VM(pble_fs_put_file) = MP_OBJ_NULL;
}

void pble_vm_epoch_post_deinit(void) {
    pble_ble_vm_tx_unlock();
}

void __real_mp_thread_deinit(void);

void __wrap_mp_thread_deinit(void) {
    pble_vm_epoch_pre_deinit();
    __real_mp_thread_deinit();
    pble_vm_epoch_post_deinit();
}

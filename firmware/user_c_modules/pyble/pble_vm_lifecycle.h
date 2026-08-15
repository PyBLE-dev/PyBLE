// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

#ifndef PBLE_VM_LIFECYCLE_H
#define PBLE_VM_LIFECYCLE_H

#include <stdbool.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define PBLE_VM_READY_BUDGET_MS 2500u
#define PBLE_VM_WORKER_RUNNER (1u << 0)
#define PBLE_VM_WORKER_FS     (1u << 1)

typedef struct {
    uint64_t epoch;
    bool active;
} pble_vm_activity_t;

uint64_t pble_vm_epoch_current(void);
bool pble_vm_epoch_valid(uint64_t epoch);
bool pble_vm_admission_ready(void);

bool pble_vm_dispatch_enter(uint64_t expected_epoch,
                            pble_vm_activity_t *activity);
void pble_vm_dispatch_leave(pble_vm_activity_t *activity);
bool pble_vm_callback_enter(uint64_t epoch, pble_vm_activity_t *activity);
void pble_vm_callback_leave(pble_vm_activity_t *activity);
bool pble_vm_rx_callback_enter(pble_vm_activity_t *activity);

void pble_vm_close_admission(void);
void pble_vm_open_admission(void);
bool pble_vm_reboot_close(uint64_t epoch);
void pble_vm_reboot_abort(uint64_t epoch);
bool pble_vm_reboot_command_admitted(bool is_soft_reboot);
bool pble_vm_wait_activity_idle(int64_t deadline_us);
bool pble_vm_wait_ready_epoch(uint64_t epoch);

void pble_vm_worker_ready(uint32_t worker);
bool pble_vm_ready(int64_t deadline_us);
void pble_vm_epoch_begin(void);

void pble_vm_restart_if_closing(void);
void pble_vm_epoch_pre_deinit(void);
void pble_vm_epoch_post_deinit(void);
void __wrap_mp_thread_deinit(void);

#ifdef __cplusplus
}
#endif

#endif  // PBLE_VM_LIFECYCLE_H

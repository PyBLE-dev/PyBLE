// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.
//
// pble_device_config — PyBLE identity store (F-22). See pble_device_config.h.
// Clean-room vs protocol.md §2/§4/§7; identity is display-only (SEC-11).
#include "pble_device_config.h"
#include "pble_ble.h"        // pble_ble_set_adv_name

#include <string.h>
#include <stdio.h>
#include <stdbool.h>

#include "esp_mac.h"         // esp_read_mac, ESP_MAC_BT
#include "nvs.h"             // NVS label store (namespace outside the fs jail)
#include "esp_timer.h"       // non-blocking identify blink (F-23)
#include "esp_system.h"      // fail closed before arm-incarnation wrap
#include "driver/gpio.h"     // identify-LED GPIO config
#include "soc/gpio_num.h"    // GPIO_IS_VALID_OUTPUT_GPIO
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#include "pble_vm_lifecycle.h"

#define DC_NS         "pyble"
#define DC_KEY_LABEL  "label"
#define DC_KEY_IDGPIO "id_gpio"    // identify-LED GPIO number
#define DC_KEY_IDAL   "id_al"      // identify-LED active level (0/1)

static char dc_device_id[5];               // "XXXX" + NUL
static char dc_label[PBLE_LABEL_MAX + 1];  // persisted label or ""
static bool dc_inited = false;

// --- Identify LED (F-23): the single optional status LED (CON-13) ------------
static bool    dc_id_configured;
static uint8_t dc_id_gpio;
static uint8_t dc_id_active_high;          // 1 = active-high, 0 = active-low
static esp_timer_handle_t dc_blink_timer;

typedef enum {
    DC_BLINK_IDLE = 0,
    DC_BLINK_QUIESCE,
    DC_BLINK_ACTIVATE,
    DC_BLINK_ACTIVE,
} dc_blink_phase_t;

static dc_blink_phase_t dc_blink_phase;
static uint64_t dc_blink_pending_epoch;
static int dc_blink_pending_ticks;
static int dc_blink_ticks;                 // active remaining 100 ms toggles
static bool dc_blink_on;
static uint64_t dc_blink_epoch;
static uint64_t dc_blink_arm_incarnation;
static portMUX_TYPE dc_blink_mux = portMUX_INITIALIZER_UNLOCKED;

#define DC_BLINK_TICK_US          100000
#define DC_BLINK_BOUNDARY_US      1

// ESP-IDF's output-capability macro uses the GPIO number as a mask shift on
// some targets. Bound untrusted persisted/BLE bytes before invoking it.
static bool dc_gpio_is_valid_output(int gpio) {
    return gpio >= 0 && gpio < GPIO_NUM_MAX &&
           GPIO_IS_VALID_OUTPUT_GPIO(gpio);
}

// Drive the LED to logical on/off honouring the active level.
static void dc_led_write(bool on) {
    gpio_set_level(dc_id_gpio, dc_id_active_high ? (on ? 1 : 0) : (on ? 0 : 1));
}
static void dc_led_configure(void) {
    gpio_reset_pin(dc_id_gpio);
    gpio_set_direction(dc_id_gpio, GPIO_MODE_OUTPUT);
    dc_led_write(false);                   // idle = off
}

// Caller owns dc_blink_mux. Incarnations are deliberately retained across an
// invalidation: resetting that counter would make a dequeued callback's exact
// active-arm ticket reusable within the same VM epoch.
static void dc_blink_clear_locked(void) {
    dc_blink_phase = DC_BLINK_IDLE;
    dc_blink_pending_epoch = 0;
    dc_blink_pending_ticks = 0;
    dc_blink_ticks = 0;
    dc_blink_on = false;
    dc_blink_epoch = 0;
    if (dc_id_configured) {
        dc_led_write(false);
    }
}

void pble_dc_init(void) {
    if (dc_inited) {
        return;
    }
    uint8_t mac[6] = {0};
    esp_read_mac(mac, ESP_MAC_BT);         // BT MAC == the advertised BLE address
    snprintf(dc_device_id, sizeof(dc_device_id), "%02X%02X", mac[4], mac[5]);

    dc_label[0] = '\0';
    dc_id_configured = false;
    nvs_handle_t h;
    if (nvs_open(DC_NS, NVS_READONLY, &h) == ESP_OK) {
        size_t n = sizeof(dc_label);
        (void)nvs_get_str(h, DC_KEY_LABEL, dc_label, &n);   // leaves "" if absent
        uint8_t g, al;
        if (nvs_get_u8(h, DC_KEY_IDGPIO, &g) == ESP_OK &&
            nvs_get_u8(h, DC_KEY_IDAL, &al) == ESP_OK &&
            dc_gpio_is_valid_output(g)) {
            dc_id_gpio = g;
            dc_id_active_high = al ? 1 : 0;
            dc_id_configured = true;
        }
        nvs_close(h);
    }
    if (dc_id_configured) {
        dc_led_configure();
    }
    dc_inited = true;
}

const char *pble_dc_device_id(void) {
    pble_dc_init();
    return dc_device_id;
}

size_t pble_dc_label(char *out, size_t cap) {
    pble_dc_init();
    size_t n = strlen(dc_label);
    if (n >= cap) {
        n = cap ? cap - 1 : 0;
    }
    if (cap) {
        memcpy(out, dc_label, n);
        out[n] = '\0';
    }
    return n;
}

size_t pble_dc_adv_name(char *out, size_t cap) {
    pble_dc_init();
    if (dc_label[0] != '\0') {
        return pble_dc_label(out, cap);
    }
    int n = snprintf(out, cap, "PyBLE-%s", dc_device_id);
    return (n > 0 && (size_t)n < cap) ? (size_t)n : 0;
}

uint8_t pble_dc_set_label(const uint8_t *utf8, size_t len) {
    if (len > PBLE_LABEL_MAX) {
        return PBLE_ERANGE;                // OI-6: over-length rejected, not stored
    }
    pble_dc_init();
    nvs_handle_t h;
    if (nvs_open(DC_NS, NVS_READWRITE, &h) != ESP_OK) {
        return PBLE_EIO;
    }
    uint8_t st = PBLE_OK;
    if (len == 0) {
        esp_err_t e = nvs_erase_key(h, DC_KEY_LABEL);   // clear to default
        if (e != ESP_OK && e != ESP_ERR_NVS_NOT_FOUND) {
            st = PBLE_EIO;
        } else {
            dc_label[0] = '\0';
        }
    } else {
        char tmp[PBLE_LABEL_MAX + 1];
        memcpy(tmp, utf8, len);
        tmp[len] = '\0';
        if (nvs_set_str(h, DC_KEY_LABEL, tmp) != ESP_OK) {
            st = PBLE_EIO;
        } else {
            memcpy(dc_label, tmp, len + 1);
        }
    }
    if (st == PBLE_OK) {
        (void)nvs_commit(h);
    }
    nvs_close(h);

    if (st == PBLE_OK) {
        char name[PBLE_LABEL_MAX + 8];     // "PyBLE-XXXX" or a bounded label
        pble_dc_adv_name(name, sizeof(name));
        pble_ble_set_adv_name(name);       // re-advertise pre-connect (FR-BLE-12)
    }
    return st;
}

uint8_t pble_dc_set_label_cmd(const pble_frame_t *req, uint8_t *rsp,
                              size_t *rsp_len,
                              const pble_session_token_t *session) {
    (void)rsp;
    (void)session;
    if (rsp_len) {
        *rsp_len = 0;
    }
    return pble_dc_set_label(req ? req->payload : NULL, req ? req->len : 0);
}

// --- Identify LED (F-23) -----------------------------------------------------

bool pble_dc_identify_led(uint8_t *gpio_out, uint8_t *active_high_out) {
    pble_dc_init();
    if (!dc_id_configured) {
        return false;
    }
    if (gpio_out) {
        *gpio_out = dc_id_gpio;
    }
    if (active_high_out) {
        *active_high_out = dc_id_active_high;
    }
    return true;
}

// esp_timer callback (esp_timer task — never the BLE host or the worker, so a
// blink never stalls the link or user code, FR-BLE-11). An IDF timer stop does
// not revoke a callback that the timer task has already dequeued. QUIESCE makes
// that invocation drain-only; a distinct ACTIVATE callback then publishes the
// successor arm before periodic ticks are allowed to touch the GPIO.
static void dc_blink_cb(void *arg) {
    (void)arg;
    dc_blink_phase_t phase_snapshot;
    uint64_t pending_epoch;
    uint64_t epoch;
    uint64_t arm_incarnation;

    taskENTER_CRITICAL(&dc_blink_mux);
    phase_snapshot = dc_blink_phase;
    pending_epoch = dc_blink_pending_epoch;
    epoch = dc_blink_epoch;
    arm_incarnation = dc_blink_arm_incarnation;

    if (dc_blink_phase == DC_BLINK_QUIESCE) {
        // Remove the handler's boundary if this invocation was an older,
        // already-dequeued callback. If this is the boundary itself, the
        // one-shot is already inactive and INVALID_STATE is the expected result.
        esp_err_t stop_rc = esp_timer_stop(dc_blink_timer);
        if (stop_rc != ESP_OK && stop_rc != ESP_ERR_INVALID_STATE) {
            dc_blink_clear_locked();
            taskEXIT_CRITICAL(&dc_blink_mux);
            return;
        }
        dc_blink_phase = DC_BLINK_ACTIVATE;
        esp_err_t start_rc = esp_timer_start_once(dc_blink_timer,
                                                  DC_BLINK_BOUNDARY_US);
        if (start_rc != ESP_OK) {
            dc_blink_clear_locked();
        }
        taskEXIT_CRITICAL(&dc_blink_mux);
        return;
    }
    taskEXIT_CRITICAL(&dc_blink_mux);

    // ACTIVE callbacks enter the exact VM epoch captured with their arm
    // incarnation. An overtaking request can change the phase while lifecycle
    // entry runs, so the GPIO/stop cut revalidates the whole ticket below.
    if (phase_snapshot == DC_BLINK_ACTIVE && epoch != 0) {
        pble_vm_activity_t activity = {0};
        bool entered = pble_vm_callback_enter(epoch, &activity);
        if (!entered) {
            return;
        }

        taskENTER_CRITICAL(&dc_blink_mux);
        if (dc_blink_phase == DC_BLINK_ACTIVE &&
            dc_blink_epoch == epoch &&
            dc_blink_arm_incarnation == arm_incarnation) {
            if (dc_blink_ticks <= 0) {
                // The exact active ticket owns terminal stop. Even an
                // unexpected timer result clears logical state so no stale
                // invocation can retain GPIO authority.
                (void)esp_timer_stop(dc_blink_timer);
                dc_blink_clear_locked();
            } else {
                dc_blink_on = !dc_blink_on;
                dc_blink_ticks--;
                dc_led_write(dc_blink_on);
            }
        }
        taskEXIT_CRITICAL(&dc_blink_mux);
        pble_vm_callback_leave(&activity);
        return;
    }

    if (phase_snapshot != DC_BLINK_ACTIVATE || pending_epoch == 0) {
        return;
    }

    // ACTIVATE is intentionally a second timer-task turn after QUIESCE. Enter
    // lifecycle outside the identify domain, then publish only if this exact
    // pending request still owns the phase.
    pble_vm_activity_t activity = {0};
    if (!pble_vm_callback_enter(pending_epoch, &activity)) {
        taskENTER_CRITICAL(&dc_blink_mux);
        if (dc_blink_phase == DC_BLINK_ACTIVATE &&
            dc_blink_pending_epoch == pending_epoch) {
            dc_blink_phase = DC_BLINK_IDLE;
            dc_blink_pending_epoch = 0;
            dc_blink_pending_ticks = 0;
            dc_blink_ticks = 0;
            dc_blink_on = false;
            dc_blink_epoch = 0;
            if (dc_id_configured) {
                dc_led_write(false);
            }
        }
        taskEXIT_CRITICAL(&dc_blink_mux);
        return;
    }

    taskENTER_CRITICAL(&dc_blink_mux);
    if (dc_blink_phase == DC_BLINK_ACTIVATE) {
        if (dc_blink_pending_epoch == pending_epoch) {
            if (dc_blink_arm_incarnation == UINT64_MAX) {
                esp_restart();             // wrapped arm identity could ABA
            }
            dc_blink_arm_incarnation++;
            if (dc_blink_arm_incarnation == 0) {
                dc_blink_arm_incarnation = 1;
            }
            dc_blink_epoch = pending_epoch;
            dc_blink_ticks = dc_blink_pending_ticks;
            dc_blink_pending_epoch = 0;
            dc_blink_pending_ticks = 0;
            dc_blink_on = false;
            dc_blink_phase = DC_BLINK_ACTIVE;
            esp_err_t start_rc = esp_timer_start_periodic(dc_blink_timer,
                                                          DC_BLINK_TICK_US);
            if (start_rc != ESP_OK) {
                dc_blink_clear_locked();
            }
        }
        taskEXIT_CRITICAL(&dc_blink_mux);
        pble_vm_callback_leave(&activity);
        return;
    }
    taskEXIT_CRITICAL(&dc_blink_mux);
    pble_vm_callback_leave(&activity);
    return;
}

uint8_t pble_dc_set_identify_led(const uint8_t *payload, size_t len) {
    pble_dc_init();
    nvs_handle_t h;
    if (len == 0) {                        // clear / disable
        if (nvs_open(DC_NS, NVS_READWRITE, &h) == ESP_OK) {
            (void)nvs_erase_key(h, DC_KEY_IDGPIO);
            (void)nvs_erase_key(h, DC_KEY_IDAL);
            (void)nvs_commit(h);
            nvs_close(h);
        }
        taskENTER_CRITICAL(&dc_blink_mux);
        if (dc_blink_timer != NULL) {
            (void)esp_timer_stop(dc_blink_timer);
        }
        dc_blink_phase = DC_BLINK_IDLE;
        dc_blink_pending_epoch = 0;
        dc_blink_pending_ticks = 0;
        dc_blink_ticks = 0;
        dc_blink_on = false;
        dc_blink_epoch = 0;
        if (dc_id_configured) {
            dc_led_write(false);
        }
        dc_id_configured = false;
        taskEXIT_CRITICAL(&dc_blink_mux);
        return PBLE_OK;
    }
    if (len != 2) {
        return PBLE_EBADREQ;
    }
    uint8_t gpio = payload[0];
    uint8_t al = payload[1];
    if (al > 1) {
        return PBLE_EBADREQ;               // active_level ∉ {0,1}
    }
    if (!dc_gpio_is_valid_output(gpio)) {
        return PBLE_ERANGE;                // gpio out of range
    }
    if (nvs_open(DC_NS, NVS_READWRITE, &h) != ESP_OK) {
        return PBLE_EIO;
    }
    uint8_t st = PBLE_OK;
    if (nvs_set_u8(h, DC_KEY_IDGPIO, gpio) != ESP_OK ||
        nvs_set_u8(h, DC_KEY_IDAL, al) != ESP_OK) {
        st = PBLE_EIO;
    }
    if (st == PBLE_OK) {
        (void)nvs_commit(h);
    }
    nvs_close(h);
    if (st == PBLE_OK) {
        taskENTER_CRITICAL(&dc_blink_mux);
        if (dc_blink_timer != NULL) {
            (void)esp_timer_stop(dc_blink_timer);
        }
        dc_blink_phase = DC_BLINK_IDLE;
        dc_blink_pending_epoch = 0;
        dc_blink_pending_ticks = 0;
        dc_blink_ticks = 0;
        dc_blink_on = false;
        dc_blink_epoch = 0;
        if (dc_id_configured) {
            dc_led_write(false);
        }
        dc_id_gpio = gpio;
        dc_id_active_high = al;
        dc_id_configured = true;
        taskEXIT_CRITICAL(&dc_blink_mux);
        dc_led_configure();
    }
    return st;
}

uint8_t pble_dc_set_identify_led_cmd(const pble_frame_t *req, uint8_t *rsp,
                                     size_t *rsp_len,
                                     const pble_session_token_t *session) {
    (void)rsp;
    (void)session;
    if (rsp_len) {
        *rsp_len = 0;
    }
    return pble_dc_set_identify_led(req ? req->payload : NULL, req ? req->len : 0);
}

uint8_t pble_dc_identify_cmd(const pble_frame_t *req, uint8_t *rsp,
                             size_t *rsp_len,
                             const pble_session_token_t *session) {
    (void)rsp;
    if (rsp_len) {
        *rsp_len = 0;
    }
    pble_dc_init();
    if (!dc_id_configured) {
        return PBLE_EUNSUPPORTED;          // no identify LED (FR-IDENT-4)
    }
    if (session == NULL) {
        return PBLE_EINTERNAL;
    }
    // Optional [duration_ds] 1..50 deciseconds; absent/0 → default 20, >50 clamped.
    uint8_t ds = 20;
    if (req && req->payload && req->len >= 1) {
        uint8_t d = req->payload[0];
        ds = (d == 0) ? 20 : (d > 50 ? 50 : d);
    }
    if (dc_blink_timer == NULL) {
        const esp_timer_create_args_t args = { .callback = dc_blink_cb, .name = "pble_id" };
        if (esp_timer_create(&args, &dc_blink_timer) != ESP_OK) {
            return PBLE_EINTERNAL;
        }
    }
    esp_err_t stop_rc;
    esp_err_t arm_rc = ESP_FAIL;
    taskENTER_CRITICAL(&dc_blink_mux);
    stop_rc = esp_timer_stop(dc_blink_timer);
    if (stop_rc != ESP_OK && stop_rc != ESP_ERR_INVALID_STATE) {
        dc_blink_clear_locked();
    } else {
        // Do not expose this request as active yet: the next timer-task callback
        // is a drain boundary for any invocation that stop could not revoke.
        dc_blink_phase = DC_BLINK_QUIESCE;
        dc_blink_pending_epoch = session->vm_epoch;
        dc_blink_pending_ticks = ds;
        dc_blink_ticks = 0;
        dc_blink_on = false;
        dc_blink_epoch = 0;
        dc_led_write(false);
        arm_rc = esp_timer_start_once(dc_blink_timer, DC_BLINK_BOUNDARY_US);
        if (arm_rc != ESP_OK) {
            dc_blink_clear_locked();
        }
    }
    taskEXIT_CRITICAL(&dc_blink_mux);
    return arm_rc == ESP_OK ? PBLE_OK : PBLE_EINTERNAL;
                                             // non-blocking — returns immediately
}

bool pble_dc_vm_timer_disarm(int64_t deadline_us) {
    if (esp_timer_get_time() >= deadline_us) {
        return false;
    }
    esp_err_t rc = ESP_ERR_INVALID_STATE;
    taskENTER_CRITICAL(&dc_blink_mux);
    if (dc_blink_timer != NULL) {
        rc = esp_timer_stop(dc_blink_timer);
    }
    bool stop_ok = rc == ESP_OK || rc == ESP_ERR_INVALID_STATE;
    dc_blink_phase = DC_BLINK_IDLE;
    dc_blink_pending_epoch = 0;
    dc_blink_pending_ticks = 0;
    dc_blink_ticks = 0;
    dc_blink_on = false;
    dc_blink_epoch = 0;
    if (dc_id_configured) {
        dc_led_write(false);
    }
    taskEXIT_CRITICAL(&dc_blink_mux);
    if (!stop_ok) {
        return false;
    }
    return esp_timer_get_time() < deadline_us;
}

void pble_dc_identify_register(void) {
    pble_proto_register(PBLE_OP_SET_IDENTIFY_LED, pble_dc_set_identify_led_cmd);
    pble_proto_register(PBLE_OP_IDENTIFY, pble_dc_identify_cmd);
}

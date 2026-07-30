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
#include "driver/gpio.h"     // identify-LED GPIO config
#include "soc/gpio_num.h"    // GPIO_IS_VALID_OUTPUT_GPIO

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
static volatile int  dc_blink_ticks;       // remaining 100 ms toggles
static volatile bool dc_blink_on;

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
                              size_t *rsp_len, uint16_t conn) {
    (void)rsp;
    (void)conn;
    *rsp_len = 0;
    return pble_dc_set_label(req->payload, req->len);
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
// blink never stalls the link or user code, FR-BLE-11). Toggles until the bounded
// tick budget is spent, then leaves the LED idle-off and stops.
static void dc_blink_cb(void *arg) {
    (void)arg;
    if (dc_blink_ticks <= 0) {
        dc_led_write(false);
        esp_timer_stop(dc_blink_timer);
        return;
    }
    dc_blink_on = !dc_blink_on;
    dc_led_write(dc_blink_on);
    dc_blink_ticks--;
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
        if (dc_id_configured && dc_blink_timer) {
            esp_timer_stop(dc_blink_timer);
        }
        dc_id_configured = false;
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
        dc_id_gpio = gpio;
        dc_id_active_high = al;
        dc_id_configured = true;
        dc_led_configure();
    }
    return st;
}

uint8_t pble_dc_set_identify_led_cmd(const pble_frame_t *req, uint8_t *rsp,
                                     size_t *rsp_len, uint16_t conn) {
    (void)rsp;
    (void)conn;
    if (rsp_len) {
        *rsp_len = 0;
    }
    return pble_dc_set_identify_led(req ? req->payload : NULL, req ? req->len : 0);
}

uint8_t pble_dc_identify_cmd(const pble_frame_t *req, uint8_t *rsp,
                             size_t *rsp_len, uint16_t conn) {
    (void)rsp;
    (void)conn;
    if (rsp_len) {
        *rsp_len = 0;
    }
    pble_dc_init();
    if (!dc_id_configured) {
        return PBLE_EUNSUPPORTED;          // no identify LED (FR-IDENT-4)
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
    esp_timer_stop(dc_blink_timer);        // restart if already blinking
    dc_blink_ticks = ds;                   // one toggle per 100 ms ⇒ 5 Hz, ds·100 ms
    dc_blink_on = false;
    esp_timer_start_periodic(dc_blink_timer, 100000);   // 100 ms
    return PBLE_OK;                        // non-blocking — returns immediately
}

void pble_dc_identify_register(void) {
    pble_proto_register(PBLE_OP_SET_IDENTIFY_LED, pble_dc_set_identify_led_cmd);
    pble_proto_register(PBLE_OP_IDENTIFY, pble_dc_identify_cmd);
}

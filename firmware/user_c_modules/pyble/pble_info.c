// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.
//
// pble_info — DEVICE_INFO/HELLO/caps (F-03). See pble_info.h. Clean-room vs
// protocol.md §7 (FROZEN). The caps are assembled ONCE here and served verbatim
// by both the INFO characteristic read and the HELLO/DEVICE_INFO replies.
#include "pble_info.h"
#include "pble_ble.h"             // pble_ble_mtu
#include "pble_device_config.h"   // device_id + label
#include "pble_boot.h"            // auto_run cap (S6 F-12)

#include <stdio.h>

#include "py/runtime.h"           // MICROPY_VERSION_STRING (+ MP_STRINGIFY)
#include "esp_system.h"           // esp_get_free_heap_size

#ifndef PBLE_TARGET_ID
#error "The board overlay must define its canonical PBLE_TARGET_ID"
#endif

// Agent SemVer — generated from versions.lock [pyble] by build.sh (BLD-12); the
// default keeps dev/editor builds compiling (mirrors the upstream-pin discipline).
#if __has_include("pble_version.h")
#include "pble_version.h"
#endif
#ifndef PBLE_AGENT_VERSION
#define PBLE_AGENT_VERSION "0.0.0-dev"
#endif

// Caps as newline-separated `key=value` (lean + debuggable; the app parses it).
// One source of truth for §7: proto/chip/mpy/fs_root/mtu/window/chunk/free_mem/
// has_sd/device_id/label. INFO read == this payload == the HELLO/DEVICE_INFO extra.
size_t pble_info_device_info(uint8_t *out, size_t cap) {
    char label[PBLE_LABEL_MAX + 1];
    pble_dc_label(label, sizeof(label));
    unsigned mtu = pble_ble_mtu();
    // chunk_size keeps each FILE data chunk to ONE notify packet (§3.2): the
    // full §3.1 message (header + offset + data + CRC) must fit mtu − ATT −
    // FRAG. mtu − 4 here was the 11.9 kB-download-stall bug: it overshot by the
    // 14 framing bytes, silently making every stream event TWO packets.
    unsigned chunk = (mtu > PBLE_CHUNK_OVERHEAD) ? (mtu - PBLE_CHUNK_OVERHEAD) : 0;
    uint8_t id_gpio = 0xFF, id_ah = 0;
    bool has_id = pble_dc_identify_led(&id_gpio, &id_ah);   // F-23 caps

    int n = snprintf((char *)out, cap,
        "proto=%d\nagent=%s\nchip=%s\nmpy=%s\nfs_root=/\nmtu=%u\nwindow=8\nchunk=%u\n"
        "free_mem=%u\nhas_sd=0\nhas_identify=%d\nidentify_led=%d\nauto_run=%d\ndevice_id=%s\nlabel=%s\n",
        PBLE_PROTO_VERSION, PBLE_AGENT_VERSION, PBLE_TARGET_ID, MICROPY_VERSION_STRING,
        mtu, chunk, (unsigned)esp_get_free_heap_size(),
        has_id ? 1 : 0, has_id ? id_gpio : 0xFF, pble_boot_autorun_enabled() ? 1 : 0,
        pble_dc_device_id(), label);

    if (n < 0) {
        return 0;
    }
    return ((size_t)n < cap) ? (size_t)n : cap;
}

uint8_t pble_info_hello(const pble_frame_t *req, uint8_t *rsp,
                        size_t *rsp_len,
                        const pble_session_token_t *session) {
    (void)req;
    (void)session;
    // §9 VER guard (frame VER != 0x01) already rejected in dispatch; v1.0 is the
    // single supported version, so a well-formed HELLO is served the caps.
    *rsp_len = pble_info_device_info(rsp, PBLE_RSP_MAX);
    return PBLE_OK;
}

uint8_t pble_info_device_info_cmd(const pble_frame_t *req, uint8_t *rsp,
                                  size_t *rsp_len,
                                  const pble_session_token_t *session) {
    (void)req;
    (void)session;
    *rsp_len = pble_info_device_info(rsp, PBLE_RSP_MAX);
    return PBLE_OK;
}

// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.
//
// pble_info — DEVICE_INFO / HELLO / capabilities (F-03). One caps source shared
// by the INFO characteristic read and the HELLO/DEVICE_INFO replies (protocol.md
// §7, FROZEN). Clean-room.
#ifndef PBLE_INFO_H
#define PBLE_INFO_H

#include <stddef.h>
#include <stdint.h>
#include "pble_proto.h"   // pble_frame_t

#ifdef __cplusplus
extern "C" {
#endif

// The DEVICE_INFO caps payload (also the INFO-characteristic read value —
// §7: an INFO read returns the same DEVICE_INFO payload). Returns bytes written.
size_t  pble_info_device_info(uint8_t *out, size_t cap);

// 0x01 HELLO handler — returns OK + the caps payload (HELLO is the first exchange).
uint8_t pble_info_hello(const pble_frame_t *req, uint8_t *rsp, size_t *rsp_len, uint16_t conn);

// 0x02 DEVICE_INFO handler — returns OK + the same caps payload.
uint8_t pble_info_device_info_cmd(const pble_frame_t *req, uint8_t *rsp, size_t *rsp_len, uint16_t conn);

#ifdef __cplusplus
}
#endif

#endif  // PBLE_INFO_H

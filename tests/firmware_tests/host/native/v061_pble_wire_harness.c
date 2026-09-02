// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.
//
// Dependency-free host harness for the v0.6.1 pble_wire contract.  This is a
// real compiled consumer of the same production C unit linked into firmware;
// it deliberately includes no ESP-IDF, FreeRTOS, MicroPython, or test shim.

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "pble_wire.h"

#define LINE_CAP 16384u
#define BYTES_CAP 8192u

static int hex_nibble(char value) {
    if (value >= '0' && value <= '9') {
        return value - '0';
    }
    if (value >= 'a' && value <= 'f') {
        return value - 'a' + 10;
    }
    if (value >= 'A' && value <= 'F') {
        return value - 'A' + 10;
    }
    return -1;
}

static bool decode_hex(const char *text, uint8_t *out, size_t *out_len) {
    if (strcmp(text, "-") == 0) {
        *out_len = 0;
        return true;
    }
    size_t chars = strlen(text);
    if ((chars & 1u) != 0u || chars / 2u > BYTES_CAP) {
        return false;
    }
    for (size_t i = 0; i < chars / 2u; ++i) {
        int high = hex_nibble(text[2u * i]);
        int low = hex_nibble(text[2u * i + 1u]);
        if (high < 0 || low < 0) {
            return false;
        }
        out[i] = (uint8_t)((high << 4) | low);
    }
    *out_len = chars / 2u;
    return true;
}

static const char *action_name(pble_wire_action_t action) {
    switch (action) {
        case PBLE_WIRE_DROP:
            return "drop";
        case PBLE_WIRE_DISPATCH:
            return "dispatch";
        case PBLE_WIRE_RSP:
            return "rsp";
        case PBLE_WIRE_EVT:
            return "evt";
        default:
            return "invalid";
    }
}

int main(void) {
    char line[LINE_CAP];
    uint8_t bytes[BYTES_CAP];
    pble_wire_session_t session;
    pble_wire_session_reset(&session);

    while (fgets(line, sizeof(line), stdin) != NULL) {
        char *command = strtok(line, " \t\r\n");
        if (command == NULL) {
            continue;
        }
        if (strcmp(command, "RESET") == 0) {
            pble_wire_session_reset(&session);
            printf("RESET %u\n",
                   pble_wire_session_negotiated(&session) ? 1u : 0u);
            continue;
        }
        if (strcmp(command, "LABEL") == 0) {
            char *hex = strtok(NULL, " \t\r\n");
            size_t len = 0;
            if (hex == NULL || !decode_hex(hex, bytes, &len)) {
                fputs("invalid LABEL input\n", stderr);
                return 2;
            }
            printf("LABEL %u\n", (unsigned)pble_wire_label_status(bytes, len));
            continue;
        }
        if (strcmp(command, "FRAME") == 0) {
            char *published_text = strtok(NULL, " \t\r\n");
            char *hex = strtok(NULL, " \t\r\n");
            size_t len = 0;
            if (published_text == NULL || hex == NULL ||
                (strcmp(published_text, "0") != 0 &&
                 strcmp(published_text, "1") != 0) ||
                !decode_hex(hex, bytes, &len)) {
                fputs("invalid FRAME input\n", stderr);
                return 2;
            }
            pble_wire_decision_t decision;
            pble_wire_decide(&session, bytes, len, &decision);
            if (published_text[0] == '1' && decision.commit_hello) {
                pble_wire_session_commit_v1(&session);
            }
            printf("FRAME %s %u %u %u %u %u %u\n",
                   action_name(decision.action),
                   (unsigned)decision.opcode,
                   (unsigned)decision.id,
                   (unsigned)decision.status,
                   decision.violation ? 1u : 0u,
                   decision.commit_hello ? 1u : 0u,
                   pble_wire_session_negotiated(&session) ? 1u : 0u);
            continue;
        }
        fputs("unknown harness command\n", stderr);
        return 2;
    }
    return ferror(stdin) ? 3 : 0;
}

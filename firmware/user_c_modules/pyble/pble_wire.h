// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.
//
// Dependency-free PBLE/1 wire admission.  This unit intentionally depends
// only on the C standard library so the exact firmware parser is also compiled
// by the host conformance harness.
#ifndef PBLE_WIRE_H
#define PBLE_WIRE_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define PBLE_WIRE_VERSION          0x01u
#define PBLE_WIRE_TYPE_CMD         0x01u
#define PBLE_WIRE_TYPE_RSP         0x02u
#define PBLE_WIRE_TYPE_EVT         0x03u
#define PBLE_WIRE_OP_HELLO         0x01u
#define PBLE_WIRE_OK               0x00u
#define PBLE_WIRE_EBADREQ          0x01u
#define PBLE_WIRE_EBUSY            0x07u
#define PBLE_WIRE_ECRC             0x08u
#define PBLE_WIRE_ERANGE           0x09u
#define PBLE_WIRE_EUNSUPPORTED     0x0au
#define PBLE_WIRE_HELLO_MAX        192u
#define PBLE_WIRE_HELLO_FIELD_MAX  32u
#define PBLE_WIRE_HELLO_OFFERS_MAX 8u
#define PBLE_WIRE_LABEL_MAX        24u

typedef enum {
    PBLE_WIRE_DROP = 0,
    PBLE_WIRE_DISPATCH,
    PBLE_WIRE_RSP,
    PBLE_WIRE_EVT,
} pble_wire_action_t;

typedef struct {
    bool negotiated_v1;
} pble_wire_session_t;

// A decision is deliberately pure with respect to successful HELLO.  The
// caller commits `commit_hello` only after the final response fragment has
// been accepted by the local Notify path.
typedef struct {
    pble_wire_action_t action;
    uint8_t opcode;
    uint8_t id;
    uint8_t status;
    bool violation;
    bool commit_hello;
} pble_wire_decision_t;

void pble_wire_session_reset(pble_wire_session_t *session);
bool pble_wire_session_negotiated(const pble_wire_session_t *session);
void pble_wire_session_commit_v1(pble_wire_session_t *session);

// Apply PBLE/1's complete-frame validation precedence and session gate.
void pble_wire_decide(const pble_wire_session_t *session,
                      const uint8_t *message, size_t message_len,
                      pble_wire_decision_t *decision);

// Same pure reducer with the accepted-SOFT_REBOOT global admission boundary.
// `closing` is consulted only after structural/CRC/CMD/ID/version validation
// and before HELLO/session/opcode admission.  The compatibility wrapper above
// passes false for host callers that do not model VM lifecycle.
void pble_wire_decide_with_closing(const pble_wire_session_t *session,
                                   const uint8_t *message, size_t message_len,
                                   bool closing,
                                   pble_wire_decision_t *decision);

// Validate SET_LABEL bytes: length first, then strict UTF-8 and control scalar
// rejection.  Empty input is the defined clear operation.
uint8_t pble_wire_label_status(const uint8_t *label, size_t label_len);

#ifdef __cplusplus
}
#endif

#endif  // PBLE_WIRE_H

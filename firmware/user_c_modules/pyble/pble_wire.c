// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

#include "pble_wire.h"

#include <string.h>

#define PBLE_WIRE_HEADER_LEN 6u
#define PBLE_WIRE_CRC_LEN    4u

static uint32_t pble_wire_crc32(const uint8_t *data, size_t len) {
    uint32_t crc = 0xffffffffu;
    for (size_t i = 0; i < len; ++i) {
        crc ^= data[i];
        for (unsigned bit = 0; bit < 8u; ++bit) {
            crc = (crc & 1u) != 0u
                      ? (crc >> 1) ^ 0xedb88320u
                      : crc >> 1;
        }
    }
    return crc ^ 0xffffffffu;
}

void pble_wire_session_reset(pble_wire_session_t *session) {
    if (session != NULL) {
        session->negotiated_v1 = false;
    }
}

bool pble_wire_session_negotiated(const pble_wire_session_t *session) {
    return session != NULL && session->negotiated_v1;
}

void pble_wire_session_commit_v1(pble_wire_session_t *session) {
    if (session != NULL) {
        session->negotiated_v1 = true;
    }
}

static void pble_wire_set_decision(pble_wire_decision_t *decision,
                                   pble_wire_action_t action,
                                   uint8_t opcode, uint8_t id, uint8_t status,
                                   bool violation, bool commit_hello) {
    decision->action = action;
    decision->opcode = opcode;
    decision->id = id;
    decision->status = status;
    decision->violation = violation;
    decision->commit_hello = commit_hello;
}

static bool pble_wire_ascii_value(const uint8_t *value, size_t len,
                                  bool allow_empty) {
    if ((!allow_empty && len == 0u) ||
        len > PBLE_WIRE_HELLO_FIELD_MAX) {
        return false;
    }
    for (size_t i = 0; i < len; ++i) {
        if (value[i] < 0x20u || value[i] > 0x7eu) {
            return false;
        }
    }
    return true;
}

static bool pble_wire_key_valid(const uint8_t *key, size_t len) {
    if (len == 0u || len > PBLE_WIRE_HELLO_FIELD_MAX ||
        key[0] < (uint8_t)'a' ||
        key[0] > (uint8_t)'z') {
        return false;
    }
    for (size_t i = 1; i < len; ++i) {
        uint8_t ch = key[i];
        if (!((ch >= (uint8_t)'a' && ch <= (uint8_t)'z') ||
              (ch >= (uint8_t)'0' && ch <= (uint8_t)'9') || ch == '_')) {
            return false;
        }
    }
    return true;
}

static bool pble_wire_key_equals(const uint8_t *key, size_t len,
                                 const char *literal) {
    size_t literal_len = strlen(literal);
    return len == literal_len && memcmp(key, literal, len) == 0;
}

static bool pble_wire_versions_valid(const uint8_t *value, size_t len,
                                     bool *offers_v1) {
    if (len == 0u || len > PBLE_WIRE_HELLO_FIELD_MAX) {
        return false;
    }
    size_t start = 0u;
    unsigned count = 0u;
    *offers_v1 = false;
    while (start < len) {
        size_t end = start;
        while (end < len && value[end] != (uint8_t)',') {
            ++end;
        }
        size_t token_len = end - start;
        if (token_len == 0u || ++count > PBLE_WIRE_HELLO_OFFERS_MAX ||
            (token_len > 1u && value[start] == (uint8_t)'0')) {
            return false;
        }
        unsigned number = 0u;
        for (size_t i = start; i < end; ++i) {
            if (value[i] < (uint8_t)'0' || value[i] > (uint8_t)'9') {
                return false;
            }
            number = number * 10u + (unsigned)(value[i] - (uint8_t)'0');
            if (number > 255u) {
                return false;
            }
        }
        if (number == 1u) {
            *offers_v1 = true;
        }
        if (end == len) {
            break;
        }
        start = end + 1u;
        if (start == len) {
            return false;
        }
    }
    return count != 0u;
}

static uint8_t pble_wire_hello_status(const uint8_t *payload, size_t len) {
    if (payload == NULL || len == 0u || len > PBLE_WIRE_HELLO_MAX) {
        return PBLE_WIRE_EBADREQ;
    }

    // One trailing LF is grammar, not an empty line.  A second trailing LF
    // remains an empty interior line and is rejected by the loop below.
    size_t content_len = len;
    if (payload[content_len - 1u] == (uint8_t)'\n') {
        --content_len;
    }
    if (content_len == 0u ||
        payload[content_len - 1u] == (uint8_t)'\n') {
        return PBLE_WIRE_EBADREQ;
    }

    bool seen_versions = false;
    bool seen_name = false;
    bool seen_app_version = false;
    bool offers_v1 = false;
    size_t line_start = 0u;

    while (line_start < content_len) {
        size_t line_end = line_start;
        while (line_end < content_len &&
               payload[line_end] != (uint8_t)'\n') {
            ++line_end;
        }
        if (line_end == line_start) {
            return PBLE_WIRE_EBADREQ;
        }

        size_t equals = line_start;
        while (equals < line_end && payload[equals] != (uint8_t)'=') {
            ++equals;
        }
        if (equals == line_end) {
            return PBLE_WIRE_EBADREQ;
        }
        const uint8_t *key = payload + line_start;
        size_t key_len = equals - line_start;
        const uint8_t *value = payload + equals + 1u;
        size_t value_len = line_end - equals - 1u;
        if (!pble_wire_key_valid(key, key_len) ||
            !pble_wire_ascii_value(value, value_len, true)) {
            return PBLE_WIRE_EBADREQ;
        }

        if (pble_wire_key_equals(key, key_len, "proto_versions")) {
            bool line_offers_v1 = false;
            if (seen_versions ||
                !pble_wire_versions_valid(value, value_len,
                                          &line_offers_v1)) {
                return PBLE_WIRE_EBADREQ;
            }
            seen_versions = true;
            offers_v1 = line_offers_v1;
        } else if (pble_wire_key_equals(key, key_len, "app_name")) {
            if (seen_name || !pble_wire_ascii_value(value, value_len, false)) {
                return PBLE_WIRE_EBADREQ;
            }
            seen_name = true;
        } else if (pble_wire_key_equals(key, key_len, "app_version")) {
            if (seen_app_version ||
                !pble_wire_ascii_value(value, value_len, false)) {
                return PBLE_WIRE_EBADREQ;
            }
            seen_app_version = true;
        }

        if (line_end == content_len) {
            break;
        }
        line_start = line_end + 1u;
    }

    if (!seen_versions || !seen_name || !seen_app_version) {
        return PBLE_WIRE_EBADREQ;
    }
    return offers_v1 ? PBLE_WIRE_OK : PBLE_WIRE_EUNSUPPORTED;
}

static bool pble_wire_no_response_opcode(uint8_t opcode) {
    return opcode == 0x16u || opcode == 0x31u;
}

static bool pble_wire_command_opcode(uint8_t opcode) {
    switch (opcode) {
        case 0x02u:  // DEVICE_INFO
        case 0x10u:  // FILE_LIST
        case 0x11u:  // FILE_STAT
        case 0x12u:  // FILE_GET_BEGIN
        case 0x15u:  // FILE_PUT_BEGIN
        case 0x16u:  // FILE_PUT_DATA
        case 0x17u:  // FILE_PUT_END
        case 0x18u:  // FILE_DELETE
        case 0x19u:  // MKDIR
        case 0x1au:  // FILE_RENAME
        case 0x20u:  // RUN
        case 0x21u:  // STOP
        case 0x22u:  // SOFT_REBOOT
        case 0x23u:  // SET_AUTORUN
        case 0x31u:  // CONSOLE_INPUT
        case 0x50u:  // SET_LABEL
        case 0x51u:  // SET_IDENTIFY_LED
        case 0x52u:  // IDENTIFY
            return true;
        default:
            return false;
    }
}

static bool pble_wire_path_end(const uint8_t *payload, size_t len,
                               size_t offset, size_t *end) {
    if (payload == NULL || end == NULL || offset > len || len - offset < 2u) {
        return false;
    }
    size_t path_len = (size_t)payload[offset] |
                      ((size_t)payload[offset + 1u] << 8);
    offset += 2u;
    if (path_len > len - offset) {
        return false;
    }
    *end = offset + path_len;
    return true;
}

static bool pble_wire_payload_exact(uint8_t opcode,
                                    const uint8_t *payload, size_t len) {
    size_t first_end;
    size_t second_end;
    switch (opcode) {
        case 0x02u:  // DEVICE_INFO
        case 0x21u:  // STOP
        case 0x22u:  // SOFT_REBOOT
            return len == 0u;
        case 0x10u:  // FILE_LIST
        case 0x11u:  // FILE_STAT
        case 0x18u:  // FILE_DELETE
        case 0x19u:  // MKDIR
            return pble_wire_path_end(payload, len, 0u, &first_end) &&
                   first_end == len;
        case 0x12u:  // FILE_GET_BEGIN: offset + path
            return len >= 4u &&
                   pble_wire_path_end(payload, len, 4u, &first_end) &&
                   first_end == len;
        case 0x15u:  // FILE_PUT_BEGIN: total + crc + path
            return len >= 8u &&
                   pble_wire_path_end(payload, len, 8u, &first_end) &&
                   first_end == len;
        case 0x17u:  // FILE_PUT_END
            return len == 4u;
        case 0x1au:  // FILE_RENAME: path + path
            return pble_wire_path_end(payload, len, 0u, &first_end) &&
                   pble_wire_path_end(payload, len, first_end, &second_end) &&
                   second_end == len;
        case 0x23u:  // SET_AUTORUN
            return len == 1u;
        case 0x51u:  // SET_IDENTIFY_LED
            return len == 0u || len == 2u;
        case 0x52u:  // IDENTIFY
            return len <= 1u;
        default:
            // HELLO has its own grammar. RUN, PUT_DATA, CONSOLE_INPUT, and
            // SET_LABEL consume their final field as all remaining bytes;
            // semantic minimum/range validation remains in their handlers.
            return true;
    }
}

void pble_wire_decide_with_closing(const pble_wire_session_t *session,
                                   const uint8_t *message, size_t message_len,
                                   bool closing,
                                   pble_wire_decision_t *decision) {
    if (decision == NULL) {
        return;
    }
    pble_wire_set_decision(decision, PBLE_WIRE_DROP, 0u, 0u, 0u,
                           false, false);

    // Exact structural length is first.  Correlate an EBADREQ only from a
    // complete, safe v1/CMD/nonzero six-byte header.
    bool structure_valid = message != NULL &&
                           message_len >= PBLE_WIRE_HEADER_LEN +
                                              PBLE_WIRE_CRC_LEN;
    uint16_t payload_len = 0u;
    if (structure_valid) {
        payload_len = (uint16_t)((uint16_t)message[4] |
                                 ((uint16_t)message[5] << 8));
        structure_valid = message_len == PBLE_WIRE_HEADER_LEN +
                                            (size_t)payload_len +
                                            PBLE_WIRE_CRC_LEN;
    }
    if (!structure_valid) {
        if (message != NULL && message_len >= PBLE_WIRE_HEADER_LEN &&
            message[0] == PBLE_WIRE_VERSION &&
            message[1] == PBLE_WIRE_TYPE_CMD && message[3] != 0u) {
            pble_wire_set_decision(decision, PBLE_WIRE_RSP, message[2],
                                   message[3], PBLE_WIRE_EBADREQ, true, false);
        } else {
            decision->violation = true;
        }
        return;
    }

    uint8_t opcode = message[2];
    uint8_t id = message[3];
    size_t crc_offset = message_len - PBLE_WIRE_CRC_LEN;
    uint32_t received_crc = (uint32_t)message[crc_offset] |
                            ((uint32_t)message[crc_offset + 1u] << 8) |
                            ((uint32_t)message[crc_offset + 2u] << 16) |
                            ((uint32_t)message[crc_offset + 3u] << 24);
    if (pble_wire_crc32(message, crc_offset) != received_crc) {
        pble_wire_set_decision(decision, PBLE_WIRE_EVT, opcode, 0u,
                               PBLE_WIRE_ECRC, true, false);
        return;
    }

    if (message[1] != PBLE_WIRE_TYPE_CMD || id == 0u) {
        pble_wire_set_decision(decision, PBLE_WIRE_DROP, opcode, id, 0u,
                               true, false);
        return;
    }
    if (message[0] != PBLE_WIRE_VERSION) {
        pble_wire_set_decision(decision, PBLE_WIRE_RSP, opcode, id,
                               PBLE_WIRE_EBADREQ, true, false);
        return;
    }

    if (closing) {
        pble_wire_set_decision(
            decision,
            pble_wire_no_response_opcode(opcode) ? PBLE_WIRE_DROP
                                                  : PBLE_WIRE_RSP,
            opcode, id, PBLE_WIRE_EBUSY, false, false);
        return;
    }

    if (opcode == PBLE_WIRE_OP_HELLO) {
        uint8_t hello_status = pble_wire_hello_status(
            message + PBLE_WIRE_HEADER_LEN, payload_len);
        bool malformed = hello_status == PBLE_WIRE_EBADREQ;
        pble_wire_set_decision(decision, PBLE_WIRE_RSP, opcode, id,
                               hello_status, malformed,
                               hello_status == PBLE_WIRE_OK);
        return;
    }

    if (!pble_wire_session_negotiated(session)) {
        pble_wire_set_decision(
            decision,
            pble_wire_no_response_opcode(opcode) ? PBLE_WIRE_DROP
                                                  : PBLE_WIRE_RSP,
            opcode, id, PBLE_WIRE_EBADREQ, true, false);
        return;
    }

    if (!pble_wire_command_opcode(opcode)) {
        pble_wire_set_decision(decision, PBLE_WIRE_RSP, opcode, id,
                               PBLE_WIRE_EUNSUPPORTED, false, false);
        return;
    }
    const uint8_t *payload = message + PBLE_WIRE_HEADER_LEN;
    if (!pble_wire_payload_exact(opcode, payload, payload_len)) {
        pble_wire_set_decision(
            decision,
            pble_wire_no_response_opcode(opcode) ? PBLE_WIRE_DROP
                                                  : PBLE_WIRE_RSP,
            opcode, id, PBLE_WIRE_EBADREQ, false, false);
        return;
    }
    pble_wire_set_decision(decision, PBLE_WIRE_DISPATCH, opcode, id,
                           PBLE_WIRE_OK, false, false);
}

void pble_wire_decide(const pble_wire_session_t *session,
                      const uint8_t *message, size_t message_len,
                      pble_wire_decision_t *decision) {
    pble_wire_decide_with_closing(session, message, message_len, false,
                                  decision);
}

uint8_t pble_wire_label_status(const uint8_t *label, size_t label_len) {
    if (label_len > PBLE_WIRE_LABEL_MAX) {
        return PBLE_WIRE_ERANGE;
    }
    if (label_len != 0u && label == NULL) {
        return PBLE_WIRE_EBADREQ;
    }

    size_t i = 0u;
    while (i < label_len) {
        uint32_t scalar;
        uint8_t first = label[i++];
        if (first <= 0x7fu) {
            scalar = first;
        } else if (first >= 0xc2u && first <= 0xdfu) {
            if (i >= label_len || (label[i] & 0xc0u) != 0x80u) {
                return PBLE_WIRE_EBADREQ;
            }
            scalar = ((uint32_t)(first & 0x1fu) << 6) |
                     (uint32_t)(label[i++] & 0x3fu);
        } else if (first >= 0xe0u && first <= 0xefu) {
            if (i + 1u >= label_len || (label[i] & 0xc0u) != 0x80u ||
                (label[i + 1u] & 0xc0u) != 0x80u ||
                (first == 0xe0u && label[i] < 0xa0u) ||
                (first == 0xedu && label[i] >= 0xa0u)) {
                return PBLE_WIRE_EBADREQ;
            }
            scalar = ((uint32_t)(first & 0x0fu) << 12) |
                     ((uint32_t)(label[i] & 0x3fu) << 6) |
                     (uint32_t)(label[i + 1u] & 0x3fu);
            i += 2u;
        } else if (first >= 0xf0u && first <= 0xf4u) {
            if (i + 2u >= label_len || (label[i] & 0xc0u) != 0x80u ||
                (label[i + 1u] & 0xc0u) != 0x80u ||
                (label[i + 2u] & 0xc0u) != 0x80u ||
                (first == 0xf0u && label[i] < 0x90u) ||
                (first == 0xf4u && label[i] > 0x8fu)) {
                return PBLE_WIRE_EBADREQ;
            }
            scalar = ((uint32_t)(first & 0x07u) << 18) |
                     ((uint32_t)(label[i] & 0x3fu) << 12) |
                     ((uint32_t)(label[i + 1u] & 0x3fu) << 6) |
                     (uint32_t)(label[i + 2u] & 0x3fu);
            i += 3u;
        } else {
            return PBLE_WIRE_EBADREQ;
        }

        if (scalar <= 0x1fu ||
            (scalar >= 0x7fu && scalar <= 0x9fu)) {
            return PBLE_WIRE_EBADREQ;
        }
    }
    return PBLE_WIRE_OK;
}

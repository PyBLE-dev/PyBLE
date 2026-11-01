#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.

"""Compile the production v0.7 execution snapshot core against shared vectors.

The state core is the implementation used under the native runner lock; this
suite also compiles the actual wire admission/grammar to check negotiation,
closing precedence and empty-query validation. Device scheduling remains HIL.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest

import test_v061_native_run_source_boundary as boundary
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
NATIVE = ROOT / "firmware/user_c_modules/pyble"
VECTORS = ROOT / "tests/firmware_tests/host/conformance/v070_run_status_vectors.json"


def cbytes(value):
    return ",".join(str(x) for x in bytes.fromhex(value))


class NativeRunStatusTest(unittest.TestCase):
    def test_compiled_snapshot_lifecycle_vectors_and_wire_admission(self):
        compiler = shutil.which("cc")
        self.assertIsNotNone(compiler, "a host C compiler is required")
        self.assertTrue((NATIVE / "pble_run_status.c").is_file(),
                        "native committed snapshot implementation is missing")
        vectors = json.loads(VECTORS.read_text())
        valid = []
        for row in vectors["valid"]:
            valid.append("""
            { pble_run_status_t s = {0}; uint8_t out[25];
              const uint8_t boot[8] = {%s}; const uint8_t expected[25] = {%s};
              memcpy(s.boot_id, boot, 8); s.run_id = UINT32_C(%d);
              s.revision = UINT64_C(%d); s.state = %d; s.origin = %d;
              s.terminal_reason = %d; s.flags = %d;
              pble_run_status_encode(&s, out);
              CHECK(memcmp(out, expected, 25) == 0); }
            """ % (cbytes(row["boot_id"]), cbytes(row["hex"]),
                     row["run_id"], row["revision"], row["state"],
                     row["origin"], row["terminal_reason"], row["flags"]))
        with tempfile.TemporaryDirectory(prefix="pyble-v070-native-status-") as tmp:
            path = Path(tmp)
            source = path / "status.c"
            source.write_text(PREAMBLE + "\nint main(void) {\n" + SCENARIOS
                              + "\n".join(valid) + "\nreturn 0; }\n")
            binary = path / "status"
            built = subprocess.run(
                [compiler, "-std=c11", "-Wall", "-Wextra", "-Werror",
                 "-I", str(NATIVE), str(source), str(NATIVE / "pble_run_status.c"),
                 "-o", str(binary)],
                capture_output=True, text=True, check=False)
            self.assertEqual(built.returncode, 0, built.stderr)
            ran = subprocess.run([str(binary)], capture_output=True,
                                 text=True, check=False)
            self.assertEqual(ran.returncode, 0, ran.stderr)


    def test_compiled_runner_response_cut_query_and_terminal_integration(self):
        compiler = shutil.which("cc")
        runner = (NATIVE / "pble_runner.c").read_text()
        proto = (NATIVE / "pble_proto.c").read_text().partition(
            "// --- MicroPython module shim")[0]
        functions = "\n\n".join(boundary._function(runner, name) for name in (
            "pble_rsm_init", "pble_rsm_on_run", "pble_rsm_on_finished",
            "pble_rsm_on_stopped", "pble_runner_run", "pble_runner_run_file",
            "pble_runner_status", "runner_terminal_transition",
            "runner_control_attempt_begin", "runner_control_attempt_resolve",
            "pble_runner_vm_reset", "runner_emit_status"))
        prelude = boundary.HARNESS_PREAMBLE.replace("__MESSAGE_MAX__", "3072").replace(
            "__RUNNER_MAX__", "2048") + INTEGRATION_GLOBALS
        prelude = "\n".join(line for line in prelude.splitlines()
                            if not (line.startswith("static ") and "pble_rx_" in line and line.endswith(";")))
        helpers = boundary.HARNESS_MAIN.partition("int main(void)")[0]
        helpers = helpers.replace(
            "    specialized_responses++;", "    if (fail_run_rsp) return PBLE_TX_NO_CONN;\n"
            "    specialized_responses++;")
        with tempfile.TemporaryDirectory(prefix="pyble-v070-native-runner-") as tmp:
            path = Path(tmp)
            (path / "py").mkdir()
            (path / "freertos").mkdir()
            for name, contents in (
                ("py/runtime.h", boundary.RUNTIME_STUB),
                ("py/obj.h", "#pragma once\n"),
                ("py/mpstate.h", boundary.MPSTATE_STUB),
                ("freertos/FreeRTOS.h", boundary.FREERTOS_STUB),
                ("freertos/task.h", boundary.TASK_STUB),
                ("freertos/semphr.h", boundary.SEMPHR_STUB)):
                (path / name).write_text(contents)
            source = path / "runner.c"
            source.write_text(proto + prelude + functions + helpers + INTEGRATION_MAIN)
            binary = path / "runner"
            import sys
            gc = "-Wl,-dead_strip" if sys.platform == "darwin" else "-Wl,--gc-sections"
            built = subprocess.run(
                [compiler, "-std=c11", "-Wall", "-Wextra", "-Werror",
                 "-ffunction-sections", "-fdata-sections", "-I", str(path),
                 "-I", str(NATIVE), str(source), str(NATIVE / "pble_wire.c"),
                 str(NATIVE / "pble_run_status.c"), gc, "-o", str(binary)],
                capture_output=True, text=True, check=False)
            self.assertEqual(built.returncode, 0, built.stderr)
            ran = subprocess.run([str(binary)], capture_output=True, text=True,
                                 check=False)
            self.assertEqual(ran.returncode, 0, ran.stderr)


    def test_compiled_default_mtu_event_fragmentation_retry_and_retirement(self):
        ble = (NATIVE / "pble_ble.c").read_text()
        functions = "\n\n".join(boundary._function(ble, name) for name in (
            "pble_notify_message", "pble_ble_notify_control_message_paced"))
        with tempfile.TemporaryDirectory(prefix="pyble-v070-native-tx-") as tmp:
            path = Path(tmp)
            source, binary = path / "tx.c", path / "tx"
            source.write_text(TX_PREAMBLE + functions + TX_MAIN)
            built = subprocess.run(
                [shutil.which("cc"), "-std=c11", "-Wall", "-Wextra", "-Werror",
                 str(source), "-o", str(binary)],
                capture_output=True, text=True, check=False)
            self.assertEqual(built.returncode, 0, built.stderr)
            ran = subprocess.run([str(binary)], capture_output=True,
                                 text=True, check=False)
            self.assertEqual(ran.returncode, 0, ran.stderr)


PREAMBLE = r'''
#include <stdint.h>
#include <stdbool.h>
#include <stdio.h>
#include <string.h>
#include "pble_run_status.h"
#include "pble_wire.c"
#define CHECK(x) do { if (!(x)) { fprintf(stderr, "failed line %d: %s\n", __LINE__, #x); return 1; } } while (0)
static size_t frame(uint8_t *out, uint8_t op, uint8_t n) {
    out[0]=1; out[1]=1; out[2]=op; out[3]=1; out[4]=n; out[5]=0;
    memset(out+6, 0, n);
    uint32_t crc=pble_wire_crc32(out,6+n);
    for (unsigned i=0;i<4;i++) out[6+n+i]=(uint8_t)(crc>>(8*i));
    return 10+n;
}
'''

SCENARIOS = r'''
    const uint8_t boot[8] = {1,2,3,4,5,6,7,8};
    const uint8_t next_boot[8] = {8,7,6,5,4,3,2,1};
    const uint8_t zero[8] = {0};
    pble_run_status_t s, before;
    CHECK(pble_run_status_init(&s, boot));
    CHECK(s.run_id==0 && s.revision==0 && s.state==0 && s.origin==0);
    before=s;
    CHECK(!pble_run_status_init(&s, zero));
    CHECK(memcmp(&s, &before, sizeof(s))==0);
    CHECK(pble_run_status_admit(&s, 2));
    CHECK(s.run_id==1 && s.revision==1 && s.state==1 && s.flags==1);
    CHECK(s.origin==2 && s.terminal_reason==0);
    before=s;
    CHECK(!pble_run_status_admit(&s, 1));
    CHECK(memcmp(&s, &before, sizeof(s))==0);
    pble_run_status_pickup(&s);
    CHECK(s.revision==2 && s.flags==0);
    pble_run_status_pickup(&s);
    CHECK(s.revision==2);
    pble_run_status_stop(&s);
    CHECK(s.revision==3 && s.flags==2 && s.state==1);
    pble_run_status_stop(&s);
    CHECK(s.revision==3);
    pble_run_status_finish(&s, true, true);
    CHECK(s.revision==4 && s.state==0 && s.terminal_reason==3 && s.flags==0);
    before=s;
    pble_run_status_stop(&s);
    pble_run_status_finish(&s, false, false);
    CHECK(memcmp(&s, &before, sizeof(s))==0);
    CHECK(pble_run_status_admit(&s, 1));
    CHECK(s.run_id==2 && s.origin==1 && s.terminal_reason==0);
    pble_run_status_pickup(&s);
    pble_run_status_finish(&s, true, false);
    CHECK(s.state==2 && s.terminal_reason==1 && s.run_id==2 && s.origin==1);
    CHECK(pble_run_status_admit(&s, 3));
    pble_run_status_stop(&s);
    pble_run_status_pickup(&s);
    pble_run_status_finish(&s, false, true);
    CHECK(s.state==0 && s.terminal_reason==3 && s.origin==3 && s.flags==0);
    CHECK(pble_run_status_admit(&s, 2));
    pble_run_status_pickup(&s);
    pble_run_status_finish(&s, false, false);
    CHECK(s.state==3 && s.terminal_reason==2);
    s.run_id=UINT32_MAX;
    before=s;
    CHECK(!pble_run_status_admit(&s, 1));
    CHECK(memcmp(&s, &before, sizeof(s))==0);
    CHECK(pble_run_status_init(&s, next_boot));
    CHECK(s.run_id==0 && s.revision==0 && memcmp(s.boot_id,next_boot,8)==0);
    CHECK(!pble_run_status_admit(&s, 0));
    CHECK(!pble_run_status_admit(&s, 4));

    uint8_t message[16];
    pble_wire_session_t session;
    pble_wire_session_reset(&session);
    pble_wire_decision_t decision;
    size_t n=frame(message,0x24,0);
    pble_wire_decide(&session,message,n,&decision);
    CHECK(decision.action==PBLE_WIRE_RSP && decision.status==PBLE_WIRE_EBADREQ);
    pble_wire_session_commit_v1(&session);
    pble_wire_decide(&session,message,n,&decision);
    CHECK(decision.action==PBLE_WIRE_DISPATCH);
    pble_wire_decide_with_closing(&session,message,n,true,&decision);
    CHECK(decision.action==PBLE_WIRE_RSP && decision.status==PBLE_WIRE_EBUSY);
    n=frame(message,0x24,1);
    pble_wire_decide(&session,message,n,&decision);
    CHECK(decision.action==PBLE_WIRE_RSP && decision.status==PBLE_WIRE_EBADREQ);
'''

INTEGRATION_GLOBALS = r'''
#define CHECK(x) do { if (!(x)) { fprintf(stderr,"line %d: %s\n",__LINE__,#x); return 1; } } while(0)
#define PBLE_RUNSTATE_TX_BUDGET_MS 1000u
#define MP_THREAD_GIL_EXIT() do {} while(0)
#define MP_THREAD_GIL_ENTER() do {} while(0)
static bool g_control_unresolved;
static bool g_soft_reboot_pending;
static uint64_t g_soft_reboot_epoch;
static bool g_run_status_observing;
static pble_session_token_t g_run_status_observer;
static StaticSemaphore_t control_storage;
static SemaphoreHandle_t g_control_resolution_sem = &control_storage;
static bool fail_run_rsp;
static unsigned random_calls;
static bool fail_random;
static unsigned restarts;
static unsigned event_attempts;
static unsigned event_deliveries;
static uint8_t event_frame[35];
int pble_ble_notify_control_message_paced(const uint8_t *message, size_t length,
                                          uint32_t budget,
                                          const pble_session_token_t *session) {
    (void)budget;
    ++event_attempts;
    if (!pble_ble_session_live(session)) return PBLE_TX_NO_CONN;
    if (length != sizeof(event_frame)) return PBLE_TX_OVERSIZE;
    memcpy(event_frame, message, length);
    ++event_deliveries;
    return PBLE_TX_OK;
}
static void inject_worker_kbd_interrupt(void) {}
static void pble_console_stdin_end(void) {}
static void pble_rx_ingest(const uint8_t *fragment, size_t length,
                           const pble_session_token_t *session) {
    (void)fragment; (void)length; (void)session;
}
static void esp_fill_random(void *out, size_t len) {
    ++random_calls;
    memset(out, fail_random ? 0 : (int)random_calls, len);
}
static void esp_restart(void) { ++restarts; }
'''

INTEGRATION_MAIN = r'''
int main(void) {
    (void)send_source;
    (void)observed_runner;
    (void)take_generic_status;
    (void)expect_equal;
    pble_runner_vm_reset();
    CHECK(restarts==0 && g_run_status_ready && random_calls==1);
    runner_emit_status();
    CHECK(event_attempts==0);
    uint8_t first_boot[8]; memcpy(first_boot,g_run_status.boot_id,8);
    uint8_t out[25]; size_t length=0;
    pble_frame_t q={.opcode=PBLE_OP_RUN_STATUS,.id=1,.len=0,.payload=NULL};
    CHECK(pble_runner_status(&q,out,&length,&live_session)==PBLE_OK);
    CHECK(length==25 && out[21]==0 && out[9]==0 && g_run_status_observing);
    CHECK(g_run_status_observer.generation==live_session.generation);
    uint8_t initial[25]; memcpy(initial,out,25);
    q.len=1;
    CHECK(pble_runner_status(&q,out,&length,&live_session)==PBLE_EBADREQ && length==0);
    q.len=0;
    const uint8_t data[]={PBLE_RUN_MODE_SOURCE,'p','a','s','s'};
    pble_frame_t run={.opcode=PBLE_OP_RUN,.id=2,.len=sizeof(data),.payload=data};
    fail_run_rsp=true;
    CHECK(pble_runner_run(&run,out,&length,&live_session)==PBLE_NO_RSP);
    CHECK(g_rsm.state==0 && g_run_status.run_id==0 && stdin_begins==0);
    CHECK(pble_runner_status(&q,out,&length,&live_session)==PBLE_OK);
    CHECK(memcmp(out,initial,25)==0);
    fail_run_rsp=false;
    CHECK(pble_runner_run(&run,out,&length,&live_session)==PBLE_NO_RSP);
    CHECK(g_run_status.run_id==1 && g_run_status.state==1 && g_run_status.flags==1);
    CHECK(g_run_status.origin==2 && stdin_begins==1);
    uint8_t expected_status[25];
    pble_run_status_encode(&g_run_status, expected_status);
    runner_emit_status();
    CHECK(event_deliveries==1 && event_frame[1]==PBLE_TYPE_EVT);
    CHECK(event_frame[2]==PBLE_OP_RUN_STATUS_CHANGED && event_frame[3]==0);
    CHECK(event_frame[4]==25 && memcmp(event_frame+6,expected_status,25)==0);
    ++live_session.generation;
    runner_emit_status();
    CHECK(event_deliveries==1);
    CHECK(pble_runner_status(&q,out,&length,&live_session)==PBLE_OK);
    runner_emit_status();
    CHECK(event_deliveries==2);
    CHECK(pble_runner_run(&run,out,&length,&live_session)==PBLE_EBUSY);
    CHECK(g_run_status.run_id==1 && g_run_status.revision==1);
    runner_control_attempt_begin();
    runner_control_attempt_resolve(false);
    CHECK(g_run_status.flags==1 && g_run_status.revision==1);
    runner_control_attempt_begin();
    runner_control_attempt_resolve(true);
    CHECK(g_run_status.flags==3 && g_run_status.revision==2);
    CHECK(xSemaphoreTake(g_run_sem, 0)==pdTRUE);
    pble_run_status_pickup(&g_run_status);
    CHECK(runner_terminal_transition(false)==PBLE_RUN_IDLE);
    CHECK(g_run_status.run_id==1 && g_run_status.terminal_reason==3);
    CHECK(g_run_status.flags==0 && g_run_status.revision==4);
    CHECK(pble_runner_run_file("main.py")==PBLE_OK);
    CHECK(g_run_status.run_id==2 && g_run_status.origin==3);
    CHECK(xSemaphoreTake(g_run_sem, 0)==pdTRUE);
    pble_run_status_pickup(&g_run_status);
    CHECK(runner_terminal_transition(true)==PBLE_RUN_DONE);
    CHECK(g_run_status.terminal_reason==1 && g_run_status.origin==3);
    g_run_status.run_id=UINT32_MAX;
    CHECK(pble_runner_run(&run,out,&length,&live_session)==PBLE_ERANGE);
    CHECK(pble_runner_run_file("main.py")==PBLE_ERANGE);
    pble_runner_vm_reset();
    CHECK(!g_run_status_observing && g_run_status.run_id==0 && g_run_status.revision==0);
    CHECK(memcmp(first_boot,g_run_status.boot_id,8)!=0);
    fail_random=true;
    pble_runner_vm_reset();
    CHECK(restarts==1 && !g_run_status_ready);
    CHECK(pble_runner_status(&q,out,&length,&live_session)==PBLE_EINTERNAL);
    CHECK(pble_runner_run(&run,out,&length,&live_session)==PBLE_EINTERNAL);
    return 0;
}
'''

TX_PREAMBLE = r'''
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <assert.h>
#define CHECK(x) do { if (!(x)) { fprintf(stderr,"line %d: %s\n",__LINE__,#x); return 1; } } while(0)
#define PBLE_TX_OK 0
#define PBLE_TX_NO_CONN -1
#define PBLE_TX_AGAIN -2
#define PBLE_TX_OVERSIZE -3
#define PBLE_FRAG_FIRST 0x80u
#define PBLE_FRAG_LAST 0x40u
#define PBLE_FRAG_IDX_MOD 64u
#define PBLE_FRAG_PKT_MAX 244u
#define PBLE_RSP_FRAME_MAX 491u
#define pdTRUE 1
#define pdMS_TO_TICKS(ms) (ms)
typedef uint32_t TickType_t;
typedef struct { uint16_t conn; uint32_t generation; uint64_t vm_epoch; } pble_session_token_t;
static pble_session_token_t live={42,3,9};
static void *pble_tx_mutex=(void *)1;
static void *pble_tx_drain_sem=(void *)2;
static unsigned pble_mtu_val=23;
static bool locked;
static bool busy;
static TickType_t tick;
static unsigned calls;
static unsigned fail_at;
static unsigned retire_at;
static uint8_t packets[100][244];
static size_t lengths[100];
static bool pble_ble_session_live(const pble_session_token_t *s) {
    return s && s->conn==live.conn && s->generation==live.generation && s->vm_epoch==live.vm_epoch;
}
static size_t pble_payload_size(unsigned mtu) { return mtu-4; }
static TickType_t xTaskGetTickCount(void) { return tick; }
static int xSemaphoreTakeRecursive(void *sem, TickType_t timeout) {
    (void)sem; (void)timeout; assert(!locked); locked=true; return pdTRUE;
}
static void xSemaphoreGiveRecursive(void *sem) { (void)sem; assert(locked); locked=false; }
static int xSemaphoreTake(void *sem, TickType_t wait) { (void)sem; assert(!locked); tick+=wait; return pdTRUE; }
static bool pble_control_tx_boundary_pending(void) { return false; }
static bool pble_rsp_owner_active(void) { return busy; }
static int pble_notify_packet(const uint8_t *bytes, size_t len, unsigned reserve,
                              const pble_session_token_t *session) {
    assert(locked && reserve==0 && calls<100 && len<=pble_mtu_val-3);
    ++calls;
    memcpy(packets[calls-1],bytes,len); lengths[calls-1]=len;
    if (calls==retire_at) ++live.generation;
    if (!pble_ble_session_live(session)) return PBLE_TX_NO_CONN;
    if (calls==fail_at) return PBLE_TX_AGAIN;
    return PBLE_TX_OK;
}
'''
TX_MAIN = r'''
int main(void) {
    uint8_t frame[35]; for (unsigned i=0;i<35;i++) frame[i]=(uint8_t)i;
    pble_session_token_t original=live;
    CHECK(pble_ble_notify_control_message_paced(frame,35,1000,&original)==PBLE_TX_OK);
    CHECK(calls==2 && lengths[0]==20 && lengths[1]==17);
    CHECK(packets[0][0]==0x80 && packets[1][0]==0x41);
    CHECK(memcmp(packets[0]+1,frame,19)==0 && memcmp(packets[1]+1,frame+19,16)==0);
    CHECK(!locked);
    calls=0; fail_at=2;
    CHECK(pble_ble_notify_control_message_paced(frame,35,1000,&original)==PBLE_TX_OK);
    CHECK(calls==4 && packets[2][0]==0x80 && packets[3][0]==0x41);
    CHECK(memcmp(packets[0],packets[2],20)==0 && memcmp(packets[1],packets[3],17)==0);
    CHECK(tick==15 && !locked);
    calls=0; fail_at=0; retire_at=2;
    CHECK(pble_ble_notify_control_message_paced(frame,35,1000,&original)==PBLE_TX_NO_CONN);
    CHECK(calls==2 && !locked);
    CHECK(pble_ble_notify_control_message_paced(frame,35,1000,&original)==PBLE_TX_NO_CONN);
    CHECK(calls==2);
    calls=0; retire_at=0; busy=true; tick=0;
    CHECK(pble_ble_notify_control_message_paced(frame,35,40,&live)==PBLE_TX_AGAIN);
    CHECK(calls==0 && tick==40 && !locked);
    busy=false; pble_mtu_val=247;
    CHECK(pble_ble_notify_control_message_paced(frame,35,1000,&live)==PBLE_TX_OK);
    CHECK(calls==1 && packets[0][0]==0xc0 && lengths[0]==36);
    CHECK(pble_ble_notify_control_message_paced(frame,492,1000,&live)==PBLE_TX_OVERSIZE);
    CHECK(calls==1 && !locked);
    return 0;
}
'''

if __name__ == "__main__":
    unittest.main(verbosity=2)

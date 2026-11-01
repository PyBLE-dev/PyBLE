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
                 str(NATIVE / "pble_wire.c"), "-o", str(binary)],
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
#include "pble_wire.h"
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

if __name__ == "__main__":
    unittest.main(verbosity=2)

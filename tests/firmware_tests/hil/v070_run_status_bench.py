#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
"""Physical-only committed execution/reconnect probe for the selected v0.7 slice.

No persistent files/configuration are changed. A pre-existing active run refuses
execution. Only a run admitted by this bench is stopped during cleanup. Output
is private: it binds actual observations, never fabricates a qualification row.
"""
import argparse
import asyncio
import datetime
import json
import os
from pathlib import Path
import struct

from _pble_central import PbleCentral, rsp_status
import _pble_wire as wire


def decode_snapshot(data):
    if len(data) != 25:
        raise ValueError('snapshot length')
    schema, boot, run, rev, state, origin, reason, flags = struct.unpack('<B8sIQBBBB', data)
    if schema != 1 or boot == b'\0' * 8 or rev > 9007199254740991:
        raise ValueError('snapshot schema/identity/revision')
    if state > 3 or origin > 3 or reason > 3 or flags & ~3:
        raise ValueError('snapshot enum/flags')
    if run == 0:
        if (rev, state, origin, reason, flags) != (0, 0, 0, 0, 0):
            raise ValueError('initial snapshot')
    elif origin == 0 or rev < run:
        raise ValueError('snapshot run identity')
    elif state == 1:
        if reason != 0:
            raise ValueError('running reason')
    elif flags != 0 or reason != {0: 3, 2: 1, 3: 2}[state]:
        raise ValueError('terminal snapshot')
    return dict(boot_id=boot.hex(), run_id=run, revision=rev, state=state,
                origin=origin, terminal_reason=reason, flags=flags)


async def negotiate(address, expected_chip, expected_agent, mtu):
    c = await PbleCentral.connect(address)
    try:
        rsp = await c.send_cmd(wire.OP_HELLO, 1, b'proto_versions=1\napp_name=v070-status-bench\napp_version=0')
        if rsp_status(rsp) != wire.ST_OK:
            raise ValueError('HELLO refused')
        caps = dict(line.split('=', 1) for line in rsp.payload[1:].decode().splitlines() if '=' in line)
        if caps.get('chip') != expected_chip or caps.get('agent') != expected_agent or caps.get('run_status') != '1':
            raise ValueError('candidate chip/version/capability mismatch')
        c.confirm_caps_mtu(mtu)
        return c, caps
    except BaseException:
        await c.disconnect()
        raise


async def stop_owned_run(query, stop, identity):
    """Cleanup may stop only the same admitted run in the same VM epoch."""
    try:
        current = await query()
        if (current['boot_id'], current['run_id']) != identity or current['state'] != 1:
            return False
        await stop()
        return True
    except Exception:
        # Loss of authoritative ownership is a refusal, never permission to
        # interrupt another program. The probe's original failure is retained.
        return False


async def probe(args):
    c = None
    owned_run = False
    owned_identity = None
    seq = 1
    observations = []

    async def command(op, payload=b''):
        nonlocal seq
        seq = seq % 255 + 1
        return await c.send_cmd(op, seq, payload)

    async def snapshot():
        rsp = await command(wire.OP_RUN_STATUS)
        if rsp_status(rsp) != wire.ST_OK:
            raise ValueError('status refused')
        return decode_snapshot(rsp.payload[1:])

    async def terminal(run_id, state, reason):
        deadline = asyncio.get_running_loop().time() + 12
        while asyncio.get_running_loop().time() < deadline:
            value = await snapshot()
            if value['run_id'] != run_id:
                raise ValueError('unexpected successor run')
            if value['state'] == state and value['terminal_reason'] == reason:
                return value
            await asyncio.sleep(.1)
        raise TimeoutError('terminal state not observed')

    try:
        c, caps = await negotiate(args.address, args.expect_chip, args.expect_agent, args.mtu)
        before = await snapshot()
        if before['state'] == 1:
            raise RuntimeError('pre-existing active program; no bench RUN/STOP performed')
        malformed = await command(wire.OP_RUN_STATUS, b'\0')
        if rsp_status(malformed) != wire.ST_EBADREQ or await snapshot() != before:
            raise ValueError('malformed query changed execution state')
        observations.append('exact-empty-grammar')
        rsp = await command(wire.OP_RUN, b'\1import time\ntime.sleep(30)')
        if rsp_status(rsp) != wire.ST_OK:
            raise ValueError('test RUN refused')
        owned_run = True
        owned_identity = (before['boot_id'], before['run_id'] + 1)
        active = await snapshot()
        if active['state'] != 1 or active['origin'] != 2 or active['run_id'] != before['run_id'] + 1:
            raise ValueError('accepted RUN snapshot mismatch')
        boot = active['boot_id']
        await c.disconnect()
        c = None
        await asyncio.sleep(.5)
        c, caps = await negotiate(args.address, args.expect_chip, args.expect_agent, args.mtu)
        recovered = await snapshot()
        if recovered['boot_id'] != boot or recovered['run_id'] != active['run_id'] or recovered['state'] != 1:
            raise ValueError('reconnect lost continuing run identity')
        observations.append('reconnect-running-snapshot')
        if rsp_status(await command(wire.OP_STOP)) != wire.ST_OK:
            raise ValueError('STOP refused')
        stopped = await terminal(active['run_id'], 0, 3)
        owned_run = False
        if rsp_status(await command(wire.OP_STOP)) != wire.ST_OK or await snapshot() != stopped:
            raise ValueError('inactive STOP changed snapshot')
        observations.append('stop-terminal-idempotence')
        for source, expected_state, reason in [(b'pass', 2, 1), (b"raise ValueError('v070_status_probe')", 3, 2)]:
            previous = await snapshot()
            if rsp_status(await command(wire.OP_RUN, b'\1' + source)) != wire.ST_OK:
                raise ValueError('terminal probe RUN refused')
            owned_run = True
            owned_identity = (previous['boot_id'], previous['run_id'] + 1)
            value = await terminal(previous['run_id'] + 1, expected_state, reason)
            owned_run = False
            if value['boot_id'] != boot or value['revision'] <= previous['revision']:
                raise ValueError('terminal identity/revision regression')
        observations.append('normal-error-terminals')
        if rsp_status(await command(wire.OP_SOFT_REBOOT)) != wire.ST_OK:
            raise ValueError('SOFT_REBOOT refused')
        await c.disconnect()
        c = None
        await asyncio.sleep(2)
        for attempt in range(5):
            try:
                c, caps = await negotiate(args.address, args.expect_chip, args.expect_agent, args.mtu)
                break
            except Exception:
                if attempt == 4:
                    raise
                await asyncio.sleep(1)
        rotated = await snapshot()
        if rotated['boot_id'] == boot:
            raise ValueError('VM reset reused boot identity')
        observations.append('vm-reset-identity')
        return dict(status='pass', observed_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                    source_commit=args.source_commit, profile=args.profile,
                    expected_agent=args.expect_agent, command_fragment_mtu=args.mtu,
                    backend_mtu=c.backend_mtu, observations=observations,
                    scope='Selected run-status functional BLE bench only; no full release qualification or tablet-row claim')
    finally:
        if c is not None:
            try:
                if owned_run and owned_identity is not None:
                    async def stop():
                        if rsp_status(await command(wire.OP_STOP)) != wire.ST_OK:
                            raise ValueError('cleanup STOP refused')
                    await stop_owned_run(snapshot, stop, owned_identity)
            finally:
                await c.disconnect()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for key in ['address', 'expect-chip', 'expect-agent', 'profile', 'source-commit', 'output']:
        p.add_argument('--' + key, required=True)
    p.add_argument('--mtu', type=int, choices=[23, 247], default=23)
    args = p.parse_args()
    path = Path(args.output)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as out:
        try:
            result = asyncio.run(probe(args))
        except Exception as e:
            result = dict(status='fail', profile=args.profile, error_type=type(e).__name__,
                          detail=str(e), source_commit=args.source_commit)
        json.dump(result, out, indent=2)
        out.write('\n')
    print(json.dumps({'profile':args.profile, 'status':result['status']}))
    return 0 if result['status'] == 'pass' else 1


if __name__ == '__main__':
    raise SystemExit(main())

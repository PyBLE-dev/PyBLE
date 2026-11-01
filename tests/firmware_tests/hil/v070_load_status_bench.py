#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
"""Optional physical RUN_STATUS probe during tight Python and console loads.

Use only on an exclusively held board. Both inline programs are bounded to 15
seconds using ticks_diff; no files or configuration change. Three queries per
case must prove the same picked-up source run after its unique console marker
is received. Latencies are observations, with no invented performance limit.
"""
import argparse
import asyncio
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
from time import monotonic

from _pble_central import rsp_status
import _pble_wire as wire
import v070_run_status_bench as status_bench


def source_for(case, nonce):
    if case not in ('tight', 'flood') or re.fullmatch('[0-9a-f]{16,64}', nonce) is None:
        raise ValueError('invalid load source case/nonce')
    marker = ('PyBLE v070 load %s %s' % (nonce, case)).encode()
    source = ('import time\nprint(%r)\n_start=time.ticks_ms()\n'
              'while time.ticks_diff(time.ticks_ms(),_start)<15000:\n'
              % marker.decode())
    source += '    pass\n' if case == 'tight' else '    print(%r)\n' % marker.decode()
    return source.encode(), marker


class LoadProbe:
    def __init__(self, args):
        self.args = args
        self.central = None
        self.caps = {}
        self.seq = 1
        self.owned_identity = None
        self.uncertain_run = False
        self.cases = []
        self.cleanup = dict(verified=True, errors=[])

    async def command(self, opcode, payload=b''):
        self.seq = self.seq % 255 + 1
        return await self.central.send_cmd(opcode, self.seq, payload)

    @staticmethod
    def require_ok(response, name):
        if rsp_status(response) != wire.ST_OK:
            raise ValueError('%s refused' % name)
        return response.payload[1:]

    async def snapshot(self):
        return status_bench.decode_snapshot(self.require_ok(
            await self.command(wire.OP_RUN_STATUS), 'RUN_STATUS'))

    async def terminal(self, identity):
        deadline = monotonic() + 12
        while monotonic() < deadline:
            current = await self.snapshot()
            if (current['boot_id'], current['run_id']) != identity:
                raise ValueError('terminal run ownership changed; no successor STOP')
            if (current['state'], current['terminal_reason'], current['flags']) == (0, 3, 0):
                return current
            await asyncio.sleep(.05)
        raise TimeoutError('owned run stopped terminal not observed')

    async def stop_owned(self):
        identity = self.owned_identity
        async def stop():
            self.require_ok(await self.command(wire.OP_STOP), 'owned STOP')
        if not await status_bench.stop_owned_run(self.snapshot, stop, identity):
            raise ValueError('owned active run/STOP no longer confirmed; no foreign STOP')
        stopped = await self.terminal(identity)
        self.owned_identity = None
        self.cleanup['verified'] = True
        return stopped

    def collect_console(self, row, tracker, marker):
        tracker['cursor'], events = self.central.events_since(tracker['cursor'])
        for event in events:
            if event.opcode != wire.OP_CONSOLE_DATA:
                continue
            if not event.payload or event.payload[0] not in (0, 1):
                raise ValueError('malformed CONSOLE_DATA')
            if event.payload[0] != 0:
                continue
            chunk = event.payload[1:]
            row['console']['stdout_events'] += 1
            row['console']['stdout_bytes'] += len(chunk)
            combined = tracker['tail'] + chunk
            row['console']['marker_count'] += combined.count(marker)
            # At most one incomplete marker is retained across notifications.
            tracker['tail'] = combined[-(len(marker) - 1):]

    async def require_marker(self, row, tracker, marker, required):
        deadline = monotonic() + 3
        while monotonic() < deadline:
            self.collect_console(row, tracker, marker)
            if row['console']['marker_count'] >= required:
                return
            await asyncio.sleep(.02)
        raise TimeoutError('console execution marker not observed with required repetition')

    async def exercise_case(self, case):
        before = await self.snapshot()
        if before['state'] == 1:
            raise ValueError('pre-existing active program; no bench RUN/STOP')
        source, marker = source_for(case, secrets.token_hex(8))
        row = dict(case=case, preflight=before, source_sha256=hashlib.sha256(source).hexdigest(),
                   source_bound_ms=15000, execution_marker=marker.decode(), queries=[],
                   console=dict(marker_count=0, stdout_events=0, stdout_bytes=0))
        self.cases.append(row)
        tracker = dict(cursor=self.central.event_cursor(), tail=b'')
        # A lost RUN response does not prove ownership; the bounded source is
        # allowed to expire rather than adopting an unproven active run.
        self.uncertain_run = True
        response = await self.command(wire.OP_RUN, b'\1' + source)
        self.uncertain_run = False
        self.require_ok(response, 'load RUN')
        self.owned_identity = (before['boot_id'], before['run_id'] + 1)
        self.cleanup['verified'] = False
        await self.require_marker(row, tracker, marker, 2 if case == 'flood' else 1)
        previous_revision = before['revision']
        for _ in range(3):
            started = monotonic()
            current = await self.snapshot()
            latency = (monotonic() - started) * 1000
            self.collect_console(row, tracker, marker)
            sample = dict(latency_ms=latency, snapshot=current,
                          console_marker_count=row['console']['marker_count'])
            row['queries'].append(sample)
            if ((current['boot_id'], current['run_id']) != self.owned_identity or
                    (current['state'], current['origin'], current['flags']) != (1, 2, 0) or
                    current['revision'] < previous_revision):
                raise ValueError('running picked-up owned source snapshot mismatch')
            previous_revision = current['revision']
        row['stopped'] = await self.stop_owned()

    async def exercise(self):
        self.central, self.caps = await status_bench.negotiate(
            self.args.address, self.args.expect_chip, self.args.expect_agent, self.args.mtu)
        if int(self.caps['mtu']) != 247:
            raise ValueError('load probe requires actual negotiated caps MTU 247')
        if (await self.snapshot())['state'] == 1:
            raise ValueError('pre-existing active program; no bench RUN/STOP')
        for case in ('tight', 'flood'):
            await self.exercise_case(case)

    async def run(self):
        failure = None
        backend_mtu = None
        try:
            await self.exercise()
        except (Exception, asyncio.CancelledError) as exc:
            failure = dict(error_type=type(exc).__name__, detail=str(exc))
        finally:
            if self.central is not None:
                backend_mtu = self.central.backend_mtu
                try:
                    if self.owned_identity is not None:
                        await self.stop_owned()
                    if self.uncertain_run:
                        self.cleanup['verified'] = False
                        self.cleanup['errors'].append('RUN response lost; no unproven STOP; finite source bound 15000 ms')
                except Exception as exc:
                    self.cleanup['verified'] = False
                    self.cleanup['errors'].append(type(exc).__name__ + ': ' + str(exc))
                finally:
                    try:
                        await self.central.disconnect()
                    except Exception as exc:
                        self.cleanup['verified'] = False
                        self.cleanup['errors'].append(type(exc).__name__ + ': ' + str(exc))
        bench_commit = subprocess.check_output(
            ['git', '-C', str(Path(__file__).resolve().parents[3]), 'rev-parse', 'HEAD'],
            text=True).strip()
        return dict(status='pass' if failure is None and self.cleanup['verified'] else 'fail',
                    observed_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                    source_commit=self.args.source_commit, bench_commit=bench_commit,
                    profile=self.args.profile, expected_agent=self.args.expect_agent,
                    command_fragment_mtu=self.args.mtu, backend_mtu=backend_mtu,
                    negotiated_caps_mtu=int(self.caps['mtu']) if self.caps else None,
                    cases=self.cases, failure=failure, cleanup=self.cleanup,
                    scope='Optional physical status-under-load observations only; no latency SLO or full release qualification')


async def probe(args):
    return await LoadProbe(args).run()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ('address', 'expect-chip', 'expect-agent', 'profile', 'source-commit', 'output'):
        parser.add_argument('--' + key, required=True)
    parser.add_argument('--mtu', type=int, choices=(23, 247), default=23,
                        help='CMD fragmentation cap; actual negotiated ATT MTU remains 247')
    args = parser.parse_args()
    # Refuse an existing evidence path before connecting or submitting RUN.
    fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as output:
        result = asyncio.run(probe(args))
        json.dump(result, output, indent=2)
        output.write('\n')
    print(json.dumps(dict(profile=args.profile, status=result['status'],
                          cleanup_verified=result['cleanup']['verified'])))
    return 0 if result['status'] == 'pass' else 1


if __name__ == '__main__':
    raise SystemExit(main())

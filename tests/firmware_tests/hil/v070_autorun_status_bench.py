#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
"""Optional physical autorun-origin probe with an exclusively owned main.py.

Invoke only on an exclusively held board whose main.py is absent and auto_run
is off. The probe creates one nonce-bearing, bounded 60-second program. A pass
requires verified restoration of configuration, file absence and idle reboot.
Host tests use a fake transport; they never establish physical qualification.
"""
import argparse
import asyncio
import datetime
import json
import os
import secrets
import struct

import _pble_bench as pble_bench
import _pble_wire as wire
from _pble_central import rsp_status
import v070_run_status_bench as status_bench

MAIN = '/main.py'


class AutorunProbe:
    def __init__(self, args):
        self.args = args
        self.central = None
        self.ids = pble_bench.CommandIds()
        self.source = ('import time\nprint("PyBLE autorun probe %s")\n'
                       'time.sleep(60)\n' % secrets.token_hex(8)).encode()
        self.file_identity = (len(self.source), wire.crc32(self.source))
        self.file_attempted = self.put_completed = False
        self.config_attempted = self.enable_observed = self.reboot_attempted = False
        self.initial = self.owned_run = None
        self.observations = []
        self.snapshots = {}
        self.cleanup = dict(verified=False, main_absent=False,
                            auto_run_restored=False, idle_after_reboot=False,
                            errors=[])

    async def connect(self):
        self.central, caps = await status_bench.negotiate(
            self.args.address, self.args.expect_chip,
            self.args.expect_agent, self.args.mtu)
        return caps

    async def disconnect(self):
        central, self.central = self.central, None
        if central is not None:
            await central.disconnect()

    async def reconnect(self, delay=0):
        await self.disconnect()
        await asyncio.sleep(delay)
        for attempt in range(5):
            try:
                return await asyncio.wait_for(self.connect(), timeout=8)
            except Exception:
                if attempt == 4:
                    raise
                await asyncio.sleep(1)

    async def command(self, opcode, payload=b''):
        return await self.central.send_cmd(opcode, self.ids.next(), payload)

    @staticmethod
    def require_ok(response, operation):
        if rsp_status(response) != wire.ST_OK:
            raise ValueError('%s refused' % operation)
        return response.payload[1:]

    async def caps(self):
        body = self.require_ok(await self.command(wire.OP_DEVICE_INFO), 'DEVICE_INFO')
        caps = dict(line.split('=', 1) for line in body.decode().splitlines() if '=' in line)
        if (caps.get('chip') != self.args.expect_chip or
                caps.get('agent') != self.args.expect_agent or
                caps.get('run_status') != '1'):
            raise ValueError('candidate identity changed')
        return caps

    async def snapshot(self):
        body = self.require_ok(await self.command(wire.OP_RUN_STATUS), 'RUN_STATUS')
        return status_bench.decode_snapshot(body)

    async def stat_main(self):
        response = await self.command(wire.OP_FILE_STAT, pble_bench.path_payload(MAIN))
        if rsp_status(response) == wire.ST_ENOENT:
            return None
        body = self.require_ok(response, 'FILE_STAT main.py')
        if len(body) != 8:
            raise ValueError('FILE_STAT main.py has malformed size/CRC')
        return struct.unpack('<II', body)

    async def set_auto(self, value):
        self.require_ok(await self.command(wire.OP_SET_AUTORUN, bytes((value,))),
                        'SET_AUTORUN %d' % value)

    async def terminal(self, identity):
        deadline = asyncio.get_running_loop().time() + 12
        while asyncio.get_running_loop().time() < deadline:
            value = await self.snapshot()
            if (value['boot_id'], value['run_id']) != identity:
                raise ValueError('terminal run ownership changed')
            if value['state'] == 0 and value['terminal_reason'] == 3 and value['flags'] == 0:
                return value
            await asyncio.sleep(.1)
        raise TimeoutError('owned autorun did not reach stopped terminal')

    async def stop_owned(self):
        current = await self.snapshot()
        if (current['boot_id'], current['run_id']) != self.owned_run:
            raise ValueError('active run ownership changed; no STOP sent')
        if current['state'] == 1:
            self.require_ok(await self.command(wire.OP_STOP), 'owned STOP')
            self.snapshots['stopped'] = await self.terminal(self.owned_run)
        elif (current['state'], current['terminal_reason'], current['flags']) == (0, 3, 0):
            self.snapshots['stopped'] = current
        else:
            raise ValueError('owned autorun ended before stopped terminal was observed')
        # Retain the established identity after STOP. A later active autorun
        # must never be adopted just because the fixture still exists.

    async def reboot(self):
        self.require_ok(await self.command(wire.OP_SOFT_REBOOT), 'SOFT_REBOOT')
        return await self.reconnect(2)

    async def exercise(self):
        caps = await self.connect()
        if caps.get('auto_run') != '0':
            raise ValueError('pre-existing autorun setting; no fixture created')
        self.initial = await self.snapshot()
        self.snapshots['initial'] = self.initial
        if self.initial['state'] == 1:
            raise ValueError('pre-existing active program; no fixture created')
        if await self.stat_main() is not None:
            raise ValueError('pre-existing main.py; no fixture created')
        self.observations.append('main-absent-autorun-disabled-preflight')
        # Repeat the absent check immediately before the maintained PUT helper.
        # Never call a remove/overwrite convenience helper on this reserved path.
        if await self.stat_main() is not None:
            raise ValueError('main.py appeared before fixture PUT')
        self.file_attempted = True
        await pble_bench.put_file(
            self.central, MAIN, self.source, window=int(caps['window']),
            chunk=int(caps['chunk']), next_id=self.ids.next)
        self.put_completed = True
        await pble_bench.get_file(self.central, MAIN, self.source, next_id=self.ids.next)
        if await self.stat_main() != self.file_identity:
            raise ValueError('owned main.py failed CRC/size verification')
        self.observations.append('owned-main-crc-and-byte-readback')
        # Record possible mutation before sending: a lost response is not proof
        # that persistence did not commit, so cleanup must restore the baseline.
        self.config_attempted = True
        await self.set_auto(1)
        if (await self.caps()).get('auto_run') != '1':
            raise ValueError('enabled autorun was not read back')
        self.enable_observed = True
        self.reboot_attempted = True
        await self.reboot()
        active = await self.snapshot()
        if (active['boot_id'] == self.initial['boot_id'] or active['run_id'] == 0 or
                active['state'] != 1 or active['origin'] != 3 or
                await self.stat_main() != self.file_identity):
            raise ValueError('new-boot owned autorun identity not established')
        self.owned_run = (active['boot_id'], active['run_id'])
        self.snapshots['running'] = active
        self.observations.append('new-boot-autorun-origin3')
        await self.reconnect(.5)
        recovered = await self.snapshot()
        if ((recovered['boot_id'], recovered['run_id']) != self.owned_run or
                recovered['state'] != 1 or recovered['origin'] != 3 or
                recovered['revision'] < active['revision']):
            raise ValueError('autorun identity lost on reconnect')
        self.snapshots['reconnected'] = recovered
        self.observations.append('autorun-origin3-reconnect')
        await self.stop_owned()
        self.observations.append('autorun-stopped-terminal')

    async def restore(self):
        if not self.file_attempted and not self.config_attempted:
            self.cleanup.update(verified=True, no_mutations_performed=True)
            return
        try:
            if self.central is None:
                await self.reconnect()
            # Configuration restoration precedes file deletion and final reset.
            if self.config_attempted:
                try:
                    await self.set_auto(0)
                except Exception as exc:
                    self.cleanup['errors'].append(type(exc).__name__ + ': ' + str(exc))
            self.cleanup['auto_run_restored'] = (await self.caps()).get('auto_run') == '0'
            identity = await self.stat_main()
            file_owned = identity == self.file_identity
            current = await self.snapshot()
            if current['state'] == 1:
                current_identity = (current['boot_id'], current['run_id'])
                # A failed first post-reboot query can still recover ownership
                # from the exact fixture, observed enable, our requested reset,
                # a new VM identity and autorun origin. Never adopt inline/file
                # programs or a run executing a replacement main.py.
                if (self.owned_run is None and file_owned and
                        self.enable_observed and self.reboot_attempted and
                        current['origin'] == 3 and self.initial is not None and
                        current['boot_id'] != self.initial['boot_id']):
                    self.owned_run = current_identity
                if self.owned_run != current_identity or not file_owned:
                    raise ValueError('active program ownership unproven; no STOP/delete/reset')
                await self.stop_owned()
            if not self.cleanup['auto_run_restored']:
                raise ValueError('original disabled autorun setting not restored')
            if identity is not None:
                if not file_owned:
                    raise ValueError('main.py differs from owned CRC/size; preserved')
                await pble_bench.get_file(self.central, MAIN, self.source, next_id=self.ids.next)
                if await self.stat_main() != self.file_identity:
                    raise ValueError('main.py changed during cleanup; preserved')
                self.require_ok(await self.command(
                    wire.OP_FILE_DELETE, pble_bench.path_payload(MAIN)), 'owned FILE_DELETE')
            self.cleanup['main_absent'] = await self.stat_main() is None
            if not self.cleanup['main_absent']:
                raise ValueError('owned main.py deletion was not verified')
            before = await self.snapshot()
            await self.reboot()
            final = await self.snapshot()
            self.snapshots['restored'] = final
            self.cleanup['auto_run_restored'] = (await self.caps()).get('auto_run') == '0'
            self.cleanup['idle_after_reboot'] = (
                final['boot_id'] != before['boot_id'] and
                (final['run_id'], final['revision'], final['state'], final['origin'],
                 final['terminal_reason'], final['flags']) == (0, 0, 0, 0, 0, 0))
            if not self.put_completed:
                self.cleanup['errors'].append('failed PUT scratch state is unverified')
            self.cleanup['verified'] = (
                self.cleanup['main_absent'] and self.cleanup['auto_run_restored'] and
                self.cleanup['idle_after_reboot'] and not self.cleanup['errors'])
        except Exception as exc:
            self.cleanup['errors'].append(type(exc).__name__ + ': ' + str(exc))

    async def run(self):
        failure = None
        try:
            await self.exercise()
        except (Exception, asyncio.CancelledError) as exc:
            failure = dict(error_type=type(exc).__name__, detail=str(exc))
        finally:
            try:
                await self.restore()
            finally:
                try:
                    await self.disconnect()
                except Exception as exc:
                    self.cleanup['verified'] = False
                    self.cleanup['errors'].append(type(exc).__name__ + ': ' + str(exc))
        return dict(status='pass' if failure is None and self.cleanup['verified'] else 'fail',
                    observed_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                    source_commit=self.args.source_commit, profile=self.args.profile,
                    expected_agent=self.args.expect_agent,
                    command_fragment_mtu=self.args.mtu, failure=failure,
                    owned_fixture=dict(path=MAIN, size=self.file_identity[0], crc32=self.file_identity[1]),
                    observations=self.observations, snapshots=self.snapshots,
                    cleanup=self.cleanup,
                    scope='Optional physical autorun-origin/reconnect probe only; no full release qualification')


async def probe(args):
    return await AutorunProbe(args).run()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('address', 'expect-chip', 'expect-agent', 'profile', 'source-commit', 'output'):
        parser.add_argument('--' + name, required=True)
    parser.add_argument('--mtu', type=int, choices=(23, 247), default=23)
    args = parser.parse_args()
    fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as output:
        result = asyncio.run(probe(args))
        json.dump(result, output, indent=2)
        output.write('\n')
    print(json.dumps({'profile': args.profile, 'status': result['status'],
                      'cleanup_verified': result['cleanup']['verified']}))
    return 0 if result['status'] == 'pass' else 1


if __name__ == '__main__':
    raise SystemExit(main())

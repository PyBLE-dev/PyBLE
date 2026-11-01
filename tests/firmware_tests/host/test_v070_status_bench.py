# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
"""The physical status bench rejects malformed evidence using the shared corpus."""
import importlib.util
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'tests/firmware_tests/hil'))


class CleanupOwnershipTest(unittest.IsolatedAsyncioTestCase):
    async def test_does_not_stop_a_successor_or_another_boot(self):
        path = ROOT / 'tests/firmware_tests/hil/v070_run_status_bench.py'
        spec = importlib.util.spec_from_file_location('v070_status_cleanup', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        calls = []
        async def stop():
            calls.append('stop')
        async def query():
            return dict(boot_id='new-boot', run_id=3, state=1)
        self.assertFalse(await module.stop_owned_run(query, stop, ('old-boot', 3)))
        self.assertFalse(calls)
        async def query_successor():
            return dict(boot_id='old-boot', run_id=4, state=1)
        self.assertFalse(await module.stop_owned_run(query_successor, stop, ('old-boot', 3)))
        self.assertFalse(calls)
        async def query_owner():
            return dict(boot_id='old-boot', run_id=3, state=1)
        self.assertTrue(await module.stop_owned_run(query_owner, stop, ('old-boot', 3)))
        self.assertEqual(calls, ['stop'])


class StatusBenchTests(unittest.TestCase):
    def test_all_shared_status_vectors(self):
        path = ROOT / 'tests/firmware_tests/hil/v070_run_status_bench.py'
        self.assertTrue(path.exists(), 'missing physical status bench')
        spec = importlib.util.spec_from_file_location('v070_status_bench', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        corpus = json.loads((ROOT / 'tests/firmware_tests/host/conformance/v070_run_status_vectors.json').read_text())
        for row in corpus['valid']:
            got = module.decode_snapshot(bytes.fromhex(row['hex']))
            for key in ['boot_id', 'run_id', 'revision', 'state', 'origin', 'terminal_reason', 'flags']:
                self.assertEqual(got[key], row[key], row['name'])
        for row in corpus['invalid']:
            with self.assertRaises(ValueError, msg=row['name']):
                module.decode_snapshot(bytes.fromhex(row['hex']))

    def test_next_source_version_is_selected(self):
        import tomllib
        lock = tomllib.loads((ROOT / 'firmware/versions.lock').read_text())
        self.assertEqual(lock['pyble']['agent_version'], '0.7.0-dev.1')


if __name__ == '__main__':
    unittest.main()

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

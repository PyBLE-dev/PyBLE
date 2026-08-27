# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.

from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
VALIDATOR = REPO_ROOT / "tools" / "validate_ios_ipa.sh"


class IosIpaValidatorTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="pyble-ios-validator-")
        self.root = Path(self.temporary.name)
        self.fake_bin = self.root / "bin"
        self.fake_bin.mkdir()
        self.ipa = self.root / "fixture.ipa"
        self.ipa.touch()

        self._write_tool(
            "ditto",
            """#!/usr/bin/env bash
set -eu
app_path="$4/Payload/Runner.app"
mkdir -p "$app_path/Frameworks/App.framework/flutter_assets"
: > "$app_path/Info.plist"
: > "$app_path/Runner"
chmod 755 "$app_path/Runner"
""",
        )
        self._write_tool(
            "plutil",
            """#!/usr/bin/env bash
set -eu
case "${2:-}" in
  MinimumOSVersion)
    printf '%s\\n' "$PYBLE_TEST_APP_MINIMUM"
    ;;
  CFBundleExecutable)
    printf 'Runner\\n'
    ;;
  product-errors)
    exit 1
    ;;
  *)
    exit 1
    ;;
esac
""",
        )
        self._write_tool(
            "xcrun",
            """#!/usr/bin/env bash
set -eu
[ "${1:-}" = '--find' ]
printf '%s/%s\\n' "$PYBLE_FAKE_BIN" "$2"
""",
        )
        self._write_tool(
            "vtool",
            """#!/usr/bin/env bash
set -eu
printf '      cmd LC_BUILD_VERSION\\n'
printf ' platform %s\\n' "$PYBLE_TEST_COMPILED_PLATFORM"
printf '    minos %s\\n' "$PYBLE_TEST_COMPILED_MINIMUM"
""",
        )
        self._write_tool("swinfo", "#!/usr/bin/env bash\nexit 0\n")
        self._write_tool("codesign", "#!/usr/bin/env bash\nexit 0\n")
        self._write_tool(
            "file",
            "#!/usr/bin/env bash\nprintf 'Mach-O 64-bit executable\\n'\n",
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _write_tool(self, name: str, source: str) -> None:
        path = self.fake_bin / name
        path.write_text(source, encoding="utf-8")
        path.chmod(0o755)

    def _run(
        self,
        *,
        app_minimum: str,
        compiled_minimum: str,
        compiled_platform: str = "IOS",
    ) -> subprocess.CompletedProcess[str]:
        environment = os.environ.copy()
        environment.update(
            {
                "PATH": f"{self.fake_bin}:{environment['PATH']}",
                "PYBLE_FAKE_BIN": str(self.fake_bin),
                "PYBLE_TEST_APP_MINIMUM": app_minimum,
                "PYBLE_TEST_COMPILED_MINIMUM": compiled_minimum,
                "PYBLE_TEST_COMPILED_PLATFORM": compiled_platform,
            }
        )
        return subprocess.run(
            ["bash", str(VALIDATOR), str(self.ipa)],
            cwd=REPO_ROOT,
            env=environment,
            check=False,
            capture_output=True,
            text=True,
            timeout=20,
        )

    def test_rejects_application_plist_below_ios_15(self) -> None:
        result = self._run(app_minimum="14.99", compiled_minimum="15.0")

        self.assertNotEqual(0, result.returncode)
        self.assertIn(
            "expected iOS deployment floor >= 15.0; app plist has 14.99",
            result.stderr,
        )
        self.assertNotIn("awk:", result.stderr)

    def test_rejects_compiled_minimum_below_ios_15(self) -> None:
        result = self._run(app_minimum="15.0", compiled_minimum="14.99")

        self.assertNotEqual(0, result.returncode)
        self.assertIn(
            "compiled iOS minimum 14.99 is below 15.0",
            result.stderr,
        )
        self.assertNotIn("awk:", result.stderr)

    def test_rejects_non_ios_main_executable(self) -> None:
        result = self._run(
            app_minimum="15.0.1",
            compiled_minimum="16",
            compiled_platform="MACOS",
        )

        self.assertNotEqual(0, result.returncode)
        self.assertIn("unexpected compiled platform MACOS", result.stderr)
        self.assertNotIn("awk:", result.stderr)


if __name__ == "__main__":
    unittest.main()

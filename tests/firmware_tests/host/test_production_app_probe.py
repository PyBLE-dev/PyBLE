# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
"""Host contract for the ADR-0024 production app-discovery probe.

All HTTP responses are injected.  This test never opens a network connection.
"""

import copy
import hashlib
import json
import os
import re
import sys
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent
HIL_DIR = HERE.parent / "hil"
sys.path.insert(0, str(HIL_DIR))

import _production_app_probe as probe  # noqa: E402


TESTFLIGHT_URL = "https://testflight.apple.com/join/yU4e8s6d"
ACTIVE_RELEASE_PATH = "/firmware/v0.4.2/release.json"


APP_HTML = f"""<!doctype html>
<html lang="en"><head><title>PyBLE app</title></head><body>
<main>
  <h1>PyBLE for iPad external beta testing</h1>
  <a href="{TESTFLIGHT_URL}">Open PyBLE in TestFlight</a>
  <p>If the button fails, enter {TESTFLIGHT_URL}</p>
  <a href="/flash">Firmware setup</a>
  <a href="/support">Support</a>
  <img src="/testflight/pyble-testflight-qr.svg" alt="TestFlight QR">
</main>
</body></html>""".encode("utf-8")

QR_ASSET_PATH = (
    HERE.parents[2]
    / "tools"
    / "web"
    / "public"
    / "testflight"
    / "pyble-testflight-qr.svg"
)
QR_SVG = QR_ASSET_PATH.read_bytes()

FLASH_HTML = f"""<!doctype html>
<html lang="en"><body><main>
  <h1>Install PyBLE firmware</h1>
  <script type="application/json">{{"release":"{ACTIVE_RELEASE_PATH}"}}</script>
  <p>Hardware-tested firmware beta</p>
</main></body></html>""".encode("utf-8")


class FakeFetch:
    def __init__(self, responses=None):
        self.responses = responses or default_responses()
        self.calls = []

    def __call__(self, url, max_bytes):
        self.calls.append((url, max_bytes))
        value = self.responses[url]
        if isinstance(value, BaseException):
            raise value
        return value


def response(status, content_type, body=b"", location=None):
    return probe.FetchResponse(
        status=status,
        content_type=content_type,
        body=body,
        location=location,
    )


def default_responses():
    return {
        probe.APP_URL: response(200, "text/html; charset=utf-8", APP_HTML),
        probe.QR_URL: response(200, "image/svg+xml", QR_SVG),
        probe.APP_REDIRECT_URL: response(
            308,
            "text/html",
            b"permanent redirect",
            "/app?pyble_hil=1",
        ),
        probe.FLASH_URL: response(200, "text/html; charset=UTF-8", FLASH_HTML),
    }


def expected_evidence():
    return {
        "schema_version": 1,
        "app": {
            "status": 200,
            "size_bytes": len(APP_HTML),
            "sha256": hashlib.sha256(APP_HTML).hexdigest(),
        },
        "qr": {
            "status": 200,
            "size_bytes": len(QR_SVG),
            "sha256": hashlib.sha256(QR_SVG).hexdigest(),
        },
        "flash": {
            "status": 200,
            "size_bytes": len(FLASH_HTML),
            "sha256": hashlib.sha256(FLASH_HTML).hexdigest(),
        },
        "normalized_redirect": {
            "status": 308,
            "location": "/app?pyble_hil=1",
        },
        "link_facts": {
            "main_content": True,
            "testflight_href": True,
            "testflight_visible_fallback": True,
            "flash_href": True,
            "support_href": True,
            "qr_src": True,
        },
        "active_release_path": ACTIVE_RELEASE_PATH,
    }


class ProductionAppProbeTests(unittest.TestCase):
    def test_happy_path_fetches_only_the_four_exact_bounded_urls(self):
        fetch = FakeFetch()

        evidence = probe.collect_production_app_evidence(fetch=fetch)

        self.assertEqual(evidence, expected_evidence())
        self.assertEqual(
            fetch.calls,
            [
                (probe.APP_URL, probe.MAX_HTML_BYTES),
                (probe.QR_URL, probe.MAX_QR_BYTES),
                (probe.APP_REDIRECT_URL, probe.MAX_REDIRECT_BYTES),
                (probe.FLASH_URL, probe.MAX_HTML_BYTES),
            ],
        )
        self.assertIs(probe.validate_production_app_evidence(evidence), evidence)

    def test_evidence_is_deterministic_json_and_privacy_safe(self):
        first = probe.collect_production_app_evidence(fetch=FakeFetch())
        second = probe.collect_production_app_evidence(fetch=FakeFetch())
        self.assertEqual(first, second)
        encoded = json.dumps(first, sort_keys=True, separators=(",", ":"))
        self.assertNotRegex(
            encoded.lower(),
            r"https?://|timestamp|address|device|label|header|body|owner|mac|uuid",
        )
        self.assertNotIn(TESTFLIGHT_URL, encoded)
        self.assertNotIn("pyble_hil=1&", encoded)

    def test_app_contract_fails_closed_for_status_type_body_or_location(self):
        cases = {
            "status": response(503, "text/html", APP_HTML),
            "type": response(200, "application/octet-stream", APP_HTML),
            "empty": response(200, "text/html", b""),
            "not-utf8": response(200, "text/html", b"\xff\xfe"),
            "oversize": response(
                200, "text/html", b"x" * (probe.MAX_HTML_BYTES + 1)
            ),
            "unexpected-location": response(
                200, "text/html", APP_HTML, "/somewhere"
            ),
        }
        for label, bad in cases.items():
            with self.subTest(label=label):
                responses = default_responses()
                responses[probe.APP_URL] = bad
                with self.assertRaises(probe.ProductionAppProbeError):
                    probe.collect_production_app_evidence(fetch=FakeFetch(responses))

    def test_app_contract_requires_real_main_and_every_exact_authored_link(self):
        cases = {
            "no-main": APP_HTML.replace(b"<main>", b"<div>").replace(
                b"</main>", b"</div>"
            ),
            "empty-main": b"<html><main>   </main></html>",
            "wrong-testflight": APP_HTML.replace(b"yU4e8s6d", b"wrong-code"),
            "href-only": APP_HTML.replace(
                f"enter {TESTFLIGHT_URL}".encode(), b"enter the address shown above"
            ),
            "text-only": APP_HTML.replace(
                f'href="{TESTFLIGHT_URL}"'.encode(), b'href="#testflight"'
            ),
            "missing-flash": APP_HTML.replace(b'href="/flash"', b'href="/flashing"'),
            "missing-support": APP_HTML.replace(
                b'href="/support"', b'href="/help"'
            ),
            "missing-qr": APP_HTML.replace(
                b'src="/testflight/pyble-testflight-qr.svg"',
                b'src="https://remote.invalid/qr.svg"',
            ),
            "script-fake-fallback": APP_HTML.replace(
                f"enter {TESTFLIGHT_URL}".encode(),
                f"enter the address<script>{TESTFLIGHT_URL}</script>".encode(),
            ),
        }
        for label, body in cases.items():
            with self.subTest(label=label):
                responses = default_responses()
                responses[probe.APP_URL] = response(200, "text/html", body)
                with self.assertRaises(probe.ProductionAppProbeError):
                    probe.collect_production_app_evidence(fetch=FakeFetch(responses))

    def test_qr_contract_fails_closed(self):
        cases = {
            "status": response(404, "image/svg+xml", QR_SVG),
            "type": response(200, "text/html", QR_SVG),
            "empty": response(200, "image/svg+xml", b""),
            "not-svg": response(200, "image/svg+xml", b"not svg"),
            "doctype": response(
                200,
                "image/svg+xml",
                b'<!DOCTYPE svg SYSTEM "https://remote.invalid/a"><svg/>',
            ),
            "oversize": response(
                200, "image/svg+xml", b"x" * (probe.MAX_QR_BYTES + 1)
            ),
            "unexpected-location": response(
                200, "image/svg+xml", QR_SVG, probe.QR_URL + "?moved=1"
            ),
        }
        for label, bad in cases.items():
            with self.subTest(label=label):
                responses = default_responses()
                responses[probe.QR_URL] = bad
                with self.assertRaises(probe.ProductionAppProbeError):
                    probe.collect_production_app_evidence(fetch=FakeFetch(responses))

    def test_qr_is_bound_to_the_exact_reviewed_testflight_asset(self):
        self.assertEqual(len(QR_SVG), probe.EXPECTED_QR_SIZE_BYTES)
        self.assertEqual(
            hashlib.sha256(QR_SVG).hexdigest(),
            probe.EXPECTED_QR_SHA256,
        )

        responses = default_responses()
        responses[probe.QR_URL] = response(
            200,
            "image/svg+xml",
            (
                b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 8 8">'
                b'<path d="M0 0h8v8H0z"/></svg>'
            ),
        )
        with self.assertRaises(probe.ProductionAppProbeError):
            probe.collect_production_app_evidence(fetch=FakeFetch(responses))

        changed = copy.deepcopy(expected_evidence())
        changed["qr"]["sha256"] = "0" * 64
        with self.assertRaises(probe.ProductionAppProbeError):
            probe.validate_production_app_evidence(changed)

        changed = copy.deepcopy(expected_evidence())
        changed["qr"]["size_bytes"] += 1
        with self.assertRaises(probe.ProductionAppProbeError):
            probe.validate_production_app_evidence(changed)

    def test_trailing_slash_redirect_must_be_exact_and_permanent(self):
        cases = {
            "temporary": response(302, "text/html", b"", "/app?pyble_hil=1"),
            "lost-query": response(308, "text/html", b"", "/app"),
            "extra-query": response(
                308, "text/html", b"", "/app?pyble_hil=1&track=yes"
            ),
            "fragment": response(
                308, "text/html", b"", "/app?pyble_hil=1#fragment"
            ),
            "external": response(
                308,
                "text/html",
                b"",
                "https://example.invalid/app?pyble_hil=1",
            ),
            "downgrade": response(
                308,
                "text/html",
                b"",
                "http://pyble.dev/app?pyble_hil=1",
            ),
            "missing-location": response(308, "text/html", b"", None),
            "oversize": response(
                308,
                "text/html",
                b"x" * (probe.MAX_REDIRECT_BYTES + 1),
                "/app?pyble_hil=1",
            ),
        }
        for label, bad in cases.items():
            with self.subTest(label=label):
                responses = default_responses()
                responses[probe.APP_REDIRECT_URL] = bad
                with self.assertRaises(probe.ProductionAppProbeError):
                    probe.collect_production_app_evidence(fetch=FakeFetch(responses))

    def test_flash_contract_rejects_unavailable_or_ambiguous_release(self):
        cases = {
            "status": response(500, "text/html", FLASH_HTML),
            "type": response(200, "application/json", FLASH_HTML),
            "unavailable": response(
                200, "text/html", FLASH_HTML + b"Installer unavailable"
            ),
            "missing-release": response(
                200,
                "text/html",
                FLASH_HTML.replace(ACTIVE_RELEASE_PATH.encode(), b"release.json"),
            ),
            "two-releases": response(
                200,
                "text/html",
                FLASH_HTML + b"/firmware/v0.4.3/release.json",
            ),
            "non-semver": response(
                200,
                "text/html",
                FLASH_HTML.replace(b"v0.4.2", b"v00.4.2"),
            ),
            "unexpected-location": response(
                200, "text/html", FLASH_HTML, "/flash/"
            ),
            "oversize": response(
                200, "text/html", b"x" * (probe.MAX_HTML_BYTES + 1)
            ),
        }
        for label, bad in cases.items():
            with self.subTest(label=label):
                responses = default_responses()
                responses[probe.FLASH_URL] = bad
                with self.assertRaises(probe.ProductionAppProbeError):
                    probe.collect_production_app_evidence(fetch=FakeFetch(responses))

    def test_same_canonical_release_path_may_be_rendered_more_than_once(self):
        responses = default_responses()
        responses[probe.FLASH_URL] = response(
            200,
            "text/html",
            FLASH_HTML + ACTIVE_RELEASE_PATH.encode(),
        )
        evidence = probe.collect_production_app_evidence(fetch=FakeFetch(responses))
        self.assertEqual(evidence["active_release_path"], ACTIVE_RELEASE_PATH)

    def test_transport_or_injected_response_ambiguity_is_wrapped_and_closed(self):
        for failure in (
            OSError("network failed"),
            TimeoutError("timed out"),
            RuntimeError("ambiguous transport"),
            object(),
        ):
            with self.subTest(failure=type(failure).__name__):
                responses = default_responses()
                responses[probe.APP_URL] = failure
                with self.assertRaises(probe.ProductionAppProbeError):
                    probe.collect_production_app_evidence(fetch=FakeFetch(responses))

    def test_strict_evidence_validator_rejects_every_shape_or_value_drift(self):
        valid = expected_evidence()
        mutations = []

        for key in valid:
            changed = copy.deepcopy(valid)
            del changed[key]
            mutations.append(changed)
        changed = copy.deepcopy(valid)
        changed["timestamp"] = "2026-08-01T00:00:00Z"
        mutations.append(changed)

        for section in ("app", "qr", "flash"):
            changed = copy.deepcopy(valid)
            changed[section]["raw_body"] = "private"
            mutations.append(changed)
            for key, bad in (
                ("status", True),
                ("status", 201),
                ("size_bytes", 0),
                ("size_bytes", "10"),
                ("sha256", "A" * 64),
                ("sha256", "0" * 63),
            ):
                changed = copy.deepcopy(valid)
                changed[section][key] = bad
                mutations.append(changed)

        changed = copy.deepcopy(valid)
        changed["normalized_redirect"]["address"] = "private"
        mutations.append(changed)
        changed = copy.deepcopy(valid)
        changed["normalized_redirect"]["status"] = 301
        mutations.append(changed)
        changed = copy.deepcopy(valid)
        changed["normalized_redirect"]["location"] = "https://pyble.dev/app"
        mutations.append(changed)

        for fact in valid["link_facts"]:
            changed = copy.deepcopy(valid)
            changed["link_facts"][fact] = 1
            mutations.append(changed)
        changed = copy.deepcopy(valid)
        changed["link_facts"]["other"] = True
        mutations.append(changed)

        for bad_path in (
            "https://pyble.dev/firmware/v0.4.2/release.json",
            "/firmware/v00.4.2/release.json",
            "/firmware/v0.4/release.json",
            "/firmware/v0.4.2/../release.json",
        ):
            changed = copy.deepcopy(valid)
            changed["active_release_path"] = bad_path
            mutations.append(changed)

        for index, changed in enumerate(mutations):
            with self.subTest(index=index):
                with self.assertRaises(probe.ProductionAppProbeError):
                    probe.validate_production_app_evidence(changed)

    def test_source_is_stdlib_only_https_only_and_has_no_redirect_following(self):
        source = Path(probe.__file__).read_text(encoding="utf-8")
        tree_imports = re.findall(
            r"^(?:from|import)\s+([A-Za-z0-9_.]+)", source, re.MULTILINE
        )
        allowed_roots = {
            "dataclasses",
            "hashlib",
            "html",
            "json",
            "re",
            "ssl",
            "sys",
            "typing",
            "urllib",
            "xml",
        }
        self.assertTrue(tree_imports)
        self.assertEqual({item.split(".")[0] for item in tree_imports} - allowed_roots, set())
        self.assertIn("HTTPRedirectHandler", source)
        self.assertIn("redirect_request", source)
        self.assertNotIn("requests", tree_imports)
        with self.assertRaises(probe.ProductionAppProbeError):
            probe._stdlib_fetch("http://pyble.dev/app", probe.MAX_HTML_BYTES)
        with self.assertRaises(probe.ProductionAppProbeError):
            probe._stdlib_fetch("https://example.invalid/app", probe.MAX_HTML_BYTES)


if __name__ == "__main__":
    unittest.main(verbosity=2)

# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
"""Bounded, privacy-safe production probe for the ADR-0024 app route.

The default collector performs four synchronous HTTPS requests without
following redirects.  Host tests inject an in-memory fetch callable with the
same ``(url, max_bytes)`` interface and therefore never use the network.
"""

from dataclasses import dataclass
from hashlib import sha256
from html.parser import HTMLParser
import json
import re
import ssl
import sys
from typing import List, Optional
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ElementTree


APP_URL = "https://pyble.dev/app"
QR_URL = "https://pyble.dev/testflight/pyble-testflight-qr.svg"
APP_REDIRECT_URL = "https://pyble.dev/app/?pyble_hil=1"
FLASH_URL = "https://pyble.dev/flash"

TESTFLIGHT_URL = "https://testflight.apple.com/join/yU4e8s6d"
EXPECTED_REDIRECT = "/app?pyble_hil=1"
EXPECTED_QR_SIZE_BYTES = 2424
EXPECTED_QR_SHA256 = (
    "4ab6c814a8526c4d69a3b330dc563298edf5bf7eadbea4babd262fa75568e305"
)

MAX_HTML_BYTES = 512 * 1024
MAX_QR_BYTES = 256 * 1024
MAX_REDIRECT_BYTES = 16 * 1024
NETWORK_TIMEOUT_SECONDS = 12.0

_ALLOWED_URLS = frozenset((APP_URL, QR_URL, APP_REDIRECT_URL, FLASH_URL))
_ARTIFACT_KEYS = frozenset(("status", "size_bytes", "sha256"))
_LINK_FACT_KEYS = frozenset(
    (
        "main_content",
        "testflight_href",
        "testflight_visible_fallback",
        "flash_href",
        "support_href",
        "qr_src",
    )
)
_EVIDENCE_KEYS = frozenset(
    (
        "schema_version",
        "app",
        "qr",
        "flash",
        "normalized_redirect",
        "link_facts",
        "active_release_path",
    )
)

_SEMVER_IDENTIFIER = r"(?:0|[1-9][0-9]*|[A-Za-z-][0-9A-Za-z-]*)"
_SEMVER_BUILD_IDENTIFIER = r"[0-9A-Za-z-]+"
_SEMVER = (
    r"(?:0|[1-9][0-9]*)\."
    r"(?:0|[1-9][0-9]*)\."
    r"(?:0|[1-9][0-9]*)"
    r"(?:-" + _SEMVER_IDENTIFIER + r"(?:\." + _SEMVER_IDENTIFIER + r")*)?"
    r"(?:\+" + _SEMVER_BUILD_IDENTIFIER + r"(?:\." + _SEMVER_BUILD_IDENTIFIER + r")*)?"
)
_RELEASE_PATH_RE = re.compile(r"/firmware/v" + _SEMVER + r"/release\.json")
_RELEASE_TOKEN_RE = re.compile(r"/firmware/[^\s\"'<>\\]+")
_SHA256_RE = re.compile(r"[0-9a-f]{64}")


class ProductionAppProbeError(RuntimeError):
    """A production response was unavailable, ambiguous, or out of contract."""


@dataclass(frozen=True)
class FetchResponse:
    """Minimal response boundary accepted from a fetch implementation."""

    status: int
    content_type: str
    body: bytes
    location: Optional[str] = None


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Return redirect responses to the caller instead of following them."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        del req, fp, code, msg, headers, newurl
        return None


def _one_header(headers, name, required=False):
    values = headers.get_all(name, [])
    if len(values) > 1:
        raise ProductionAppProbeError("ambiguous %s response header" % name)
    if not values:
        if required:
            raise ProductionAppProbeError("missing %s response header" % name)
        return None
    value = values[0]
    if not isinstance(value, str) or not value or value != value.strip():
        raise ProductionAppProbeError("invalid %s response header" % name)
    if "\r" in value or "\n" in value:
        raise ProductionAppProbeError("invalid %s response header" % name)
    return value


def _read_stdlib_response(raw, url, max_bytes):
    status = getattr(raw, "status", None)
    if status is None:
        status = getattr(raw, "code", None)
    if type(status) is not int:
        raise ProductionAppProbeError("ambiguous HTTP response status")

    final_url = raw.geturl()
    if final_url != url:
        raise ProductionAppProbeError("unexpected implicit redirect")

    content_type = _one_header(raw.headers, "Content-Type", required=True)
    location = _one_header(raw.headers, "Location")
    content_length = _one_header(raw.headers, "Content-Length")
    transfer_encoding = _one_header(raw.headers, "Transfer-Encoding")
    content_encoding = _one_header(raw.headers, "Content-Encoding")
    if transfer_encoding is not None and content_length is not None:
        raise ProductionAppProbeError("ambiguous response framing")
    if content_encoding is not None and content_encoding.lower() != "identity":
        raise ProductionAppProbeError("encoded response body is not accepted")

    try:
        body = raw.read(max_bytes + 1)
    except Exception as exc:
        raise ProductionAppProbeError("response body read failed") from exc
    if not isinstance(body, bytes):
        raise ProductionAppProbeError("response body was not bytes")
    if len(body) > max_bytes:
        raise ProductionAppProbeError("response body exceeded its bound")
    if content_length is not None:
        if not content_length.isascii() or not content_length.isdecimal():
            raise ProductionAppProbeError("invalid Content-Length response header")
        if int(content_length, 10) != len(body):
            raise ProductionAppProbeError("truncated or ambiguous response body")

    return FetchResponse(status, content_type, body, location)


def _stdlib_fetch(url, max_bytes):
    """Fetch one fixed PyBLE URL with verified TLS and redirects disabled."""

    if url not in _ALLOWED_URLS:
        raise ProductionAppProbeError("URL is outside the fixed probe surface")
    parsed = urllib.parse.urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname != "pyble.dev"
        or parsed.netloc != "pyble.dev"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
    ):
        raise ProductionAppProbeError("probe URL is not exact HTTPS pyble.dev")
    if type(max_bytes) is not int or max_bytes <= 0 or max_bytes > MAX_HTML_BYTES:
        raise ProductionAppProbeError("invalid response bound")

    context = ssl.create_default_context()
    context.check_hostname = True
    context.verify_mode = ssl.CERT_REQUIRED
    opener = urllib.request.build_opener(
        _NoRedirect(), urllib.request.HTTPSHandler(context=context)
    )
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "image/svg+xml" if url == QR_URL else "text/html",
            "User-Agent": "PyBLE-ADR-0024-production-probe/1",
        },
        method="GET",
    )

    raw = None
    try:
        try:
            raw = opener.open(request, timeout=NETWORK_TIMEOUT_SECONDS)
        except urllib.error.HTTPError as exc:
            raw = exc
        except Exception as exc:
            raise ProductionAppProbeError("HTTPS request failed") from exc
        return _read_stdlib_response(raw, url, max_bytes)
    finally:
        if raw is not None:
            try:
                raw.close()
            except Exception as exc:
                raise ProductionAppProbeError("HTTPS response cleanup failed") from exc


def _call_fetch(fetch, url, max_bytes):
    try:
        result = fetch(url, max_bytes)
    except ProductionAppProbeError:
        raise
    except Exception as exc:
        raise ProductionAppProbeError("production fetch failed") from exc
    if type(result) is not FetchResponse:
        raise ProductionAppProbeError("fetch returned an ambiguous response shape")
    if type(result.status) is not int:
        raise ProductionAppProbeError("response status is not an integer")
    if type(result.content_type) is not str or not result.content_type:
        raise ProductionAppProbeError("response content type is missing")
    if type(result.body) is not bytes:
        raise ProductionAppProbeError("response body is not bytes")
    if result.location is not None and type(result.location) is not str:
        raise ProductionAppProbeError("response location is ambiguous")
    if len(result.body) > max_bytes:
        raise ProductionAppProbeError("response body exceeded its bound")
    return result


def _require_content_type(value, expected):
    if "\r" in value or "\n" in value or "," in value:
        raise ProductionAppProbeError("ambiguous response content type")
    media_type = value.split(";", 1)[0].strip().lower()
    if media_type != expected:
        raise ProductionAppProbeError("unexpected response content type")


def _require_ordinary_response(response, expected_type):
    if response.status != 200:
        raise ProductionAppProbeError("production resource did not return HTTP 200")
    if response.location is not None:
        raise ProductionAppProbeError("HTTP 200 response included a redirect location")
    if not response.body:
        raise ProductionAppProbeError("production resource body is empty")
    _require_content_type(response.content_type, expected_type)


class _AppDocumentParser(HTMLParser):
    _SUPPRESSED = frozenset(("script", "style", "template"))

    def __init__(self):
        HTMLParser.__init__(self, convert_charrefs=True)
        self.main_count = 0
        self.main_depth = 0
        self.suppressed_depth = 0
        self.main_text = []  # type: List[str]
        self.hrefs = []  # type: List[str]
        self.image_sources = []  # type: List[str]

    def handle_starttag(self, tag, attrs):
        lowered = tag.lower()
        values = dict(attrs)
        if lowered in self._SUPPRESSED:
            self.suppressed_depth += 1
        if lowered == "main":
            self.main_count += 1
            self.main_depth += 1
        if lowered == "a" and "href" in values:
            self.hrefs.append(values["href"])
        if lowered == "img" and "src" in values:
            self.image_sources.append(values["src"])

    def handle_startendtag(self, tag, attrs):
        lowered = tag.lower()
        values = dict(attrs)
        if lowered == "a" and "href" in values:
            self.hrefs.append(values["href"])
        if lowered == "img" and "src" in values:
            self.image_sources.append(values["src"])

    def handle_endtag(self, tag):
        lowered = tag.lower()
        if lowered == "main" and self.main_depth:
            self.main_depth -= 1
        if lowered in self._SUPPRESSED and self.suppressed_depth:
            self.suppressed_depth -= 1

    def handle_data(self, data):
        if self.main_depth and not self.suppressed_depth:
            self.main_text.append(data)


def _decode_html(body):
    try:
        return body.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise ProductionAppProbeError("HTML body is not strict UTF-8") from exc


def _app_link_facts(body):
    document = _decode_html(body)
    parser = _AppDocumentParser()
    try:
        parser.feed(document)
        parser.close()
    except Exception as exc:
        raise ProductionAppProbeError("app HTML could not be parsed") from exc

    visible_main = "".join(parser.main_text)
    facts = {
        "main_content": parser.main_count == 1 and bool(visible_main.strip()),
        "testflight_href": TESTFLIGHT_URL in parser.hrefs,
        "testflight_visible_fallback": TESTFLIGHT_URL in visible_main,
        "flash_href": "/flash" in parser.hrefs,
        "support_href": "/support" in parser.hrefs,
        "qr_src": "/testflight/pyble-testflight-qr.svg" in parser.image_sources,
    }
    if any(value is not True for value in facts.values()):
        raise ProductionAppProbeError("app document contract is incomplete")
    return facts


def _validate_qr_svg(body):
    upper = body.upper()
    if b"<!DOCTYPE" in upper or b"<!ENTITY" in upper:
        raise ProductionAppProbeError("QR SVG contains a document declaration")
    try:
        root = ElementTree.fromstring(body)
    except (ElementTree.ParseError, UnicodeError, ValueError) as exc:
        raise ProductionAppProbeError("QR response is not well-formed SVG") from exc
    local_name = root.tag.rsplit("}", 1)[-1] if isinstance(root.tag, str) else ""
    if local_name.lower() != "svg":
        raise ProductionAppProbeError("QR response root is not SVG")
    if (
        len(body) != EXPECTED_QR_SIZE_BYTES
        or sha256(body).hexdigest() != EXPECTED_QR_SHA256
    ):
        raise ProductionAppProbeError("QR response is not the reviewed TestFlight asset")


def _normalize_redirect(response):
    if response.status != 308:
        raise ProductionAppProbeError("app slash route is not HTTP 308")
    _require_content_type(response.content_type, "text/html")
    if response.location is None or response.location != response.location.strip():
        raise ProductionAppProbeError("app slash redirect location is missing")
    resolved = urllib.parse.urlsplit(
        urllib.parse.urljoin(APP_REDIRECT_URL, response.location)
    )
    if (
        resolved.scheme != "https"
        or resolved.netloc != "pyble.dev"
        or resolved.hostname != "pyble.dev"
        or resolved.username is not None
        or resolved.password is not None
        or resolved.path != "/app"
        or resolved.query != "pyble_hil=1"
        or resolved.fragment
    ):
        raise ProductionAppProbeError("app slash redirect changed its exact target")
    return {"status": 308, "location": EXPECTED_REDIRECT}


def _active_release_path(body):
    document = _decode_html(body)
    if "installer unavailable" in document.lower():
        raise ProductionAppProbeError("production installer reports unavailable")
    release_tokens = {
        token
        for token in _RELEASE_TOKEN_RE.findall(document)
        if "release.json" in token
    }
    if len(release_tokens) != 1:
        raise ProductionAppProbeError("production installer release is ambiguous")
    release_path = next(iter(release_tokens))
    if _RELEASE_PATH_RE.fullmatch(release_path) is None:
        raise ProductionAppProbeError("production installer release path is not canonical")
    return release_path


def _artifact_evidence(response):
    return {
        "status": response.status,
        "size_bytes": len(response.body),
        "sha256": sha256(response.body).hexdigest(),
    }


def collect_production_app_evidence(fetch=None):
    """Synchronously collect and validate bounded production-route evidence."""

    fetcher = _stdlib_fetch if fetch is None else fetch
    if not callable(fetcher):
        raise ProductionAppProbeError("fetch must be callable")

    app = _call_fetch(fetcher, APP_URL, MAX_HTML_BYTES)
    _require_ordinary_response(app, "text/html")
    link_facts = _app_link_facts(app.body)

    qr = _call_fetch(fetcher, QR_URL, MAX_QR_BYTES)
    _require_ordinary_response(qr, "image/svg+xml")
    _validate_qr_svg(qr.body)

    redirect = _call_fetch(fetcher, APP_REDIRECT_URL, MAX_REDIRECT_BYTES)
    normalized_redirect = _normalize_redirect(redirect)

    flash = _call_fetch(fetcher, FLASH_URL, MAX_HTML_BYTES)
    _require_ordinary_response(flash, "text/html")
    active_release_path = _active_release_path(flash.body)

    evidence = {
        "schema_version": 1,
        "app": _artifact_evidence(app),
        "qr": _artifact_evidence(qr),
        "flash": _artifact_evidence(flash),
        "normalized_redirect": normalized_redirect,
        "link_facts": link_facts,
        "active_release_path": active_release_path,
    }
    return validate_production_app_evidence(evidence)


def _require_exact_dict(value, keys, label):
    if type(value) is not dict or frozenset(value) != keys:
        raise ProductionAppProbeError("%s evidence shape is not exact" % label)


def _validate_artifact(value, label, maximum):
    _require_exact_dict(value, _ARTIFACT_KEYS, label)
    if type(value["status"]) is not int or value["status"] != 200:
        raise ProductionAppProbeError("%s status is invalid" % label)
    size = value["size_bytes"]
    if type(size) is not int or size <= 0 or size > maximum:
        raise ProductionAppProbeError("%s size is invalid" % label)
    digest = value["sha256"]
    if type(digest) is not str or _SHA256_RE.fullmatch(digest) is None:
        raise ProductionAppProbeError("%s digest is invalid" % label)


def validate_production_app_evidence(value):
    """Strictly validate the exact privacy-safe evidence shape and return it."""

    _require_exact_dict(value, _EVIDENCE_KEYS, "production app")
    if type(value["schema_version"]) is not int or value["schema_version"] != 1:
        raise ProductionAppProbeError("production app schema version is invalid")

    _validate_artifact(value["app"], "app", MAX_HTML_BYTES)
    _validate_artifact(value["qr"], "qr", MAX_QR_BYTES)
    _validate_artifact(value["flash"], "flash", MAX_HTML_BYTES)
    if (
        value["qr"]["size_bytes"] != EXPECTED_QR_SIZE_BYTES
        or value["qr"]["sha256"] != EXPECTED_QR_SHA256
    ):
        raise ProductionAppProbeError("QR evidence is not the reviewed TestFlight asset")

    normalized = value["normalized_redirect"]
    _require_exact_dict(
        normalized, frozenset(("status", "location")), "normalized redirect"
    )
    if type(normalized["status"]) is not int or normalized["status"] != 308:
        raise ProductionAppProbeError("normalized redirect status is invalid")
    if type(normalized["location"]) is not str or normalized["location"] != EXPECTED_REDIRECT:
        raise ProductionAppProbeError("normalized redirect location is invalid")

    facts = value["link_facts"]
    _require_exact_dict(facts, _LINK_FACT_KEYS, "link facts")
    if any(facts[key] is not True for key in _LINK_FACT_KEYS):
        raise ProductionAppProbeError("link fact is not exact true")

    release_path = value["active_release_path"]
    if type(release_path) is not str or _RELEASE_PATH_RE.fullmatch(release_path) is None:
        raise ProductionAppProbeError("active release path is invalid")
    return value


def main():
    try:
        evidence = collect_production_app_evidence()
    except ProductionAppProbeError as exc:
        print("production app probe failed: %s" % exc, file=sys.stderr)
        return 1
    print(json.dumps(evidence, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

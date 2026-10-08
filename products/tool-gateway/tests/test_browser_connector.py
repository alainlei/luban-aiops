"""Browser connector tests with a fake Playwright layer (SPEC-049).

Covers the session pool lifecycle (create/reuse/TTL/eviction), the origin
allowlist matrix, flow binding and the deviation-guard state machine,
credential-set handling with a leak assertion, and the screenshot byte
cap — all without a real browser.
"""

from __future__ import annotations

import asyncio
import json
import os
import unittest
from unittest.mock import patch

from tool_gateway.core.config import GatewaySettings
from tool_gateway.tools.browser_connector import (
    BrowserConnector,
    origin_of,
)
from tool_gateway.tools.browser_sessions import BrowserSessionPool, FlowState
from tool_gateway.tools.registry import ToolRegistry
# SPEC-058 R-6: the masking routine moved to the shared url_redaction module;
# aliased to its former private name so these browser-focused assertions read
# unchanged while exercising the same routine the connector now imports.
from tool_gateway.tools.url_redaction import (
    redact_secret_query as _redact_secret_query,
)

ALLOWED_ORIGIN = "https://inventory.internal:8443"
IDENTITY = {"sub": "dev.operator", "username": "dev.operator", "roles": ["operator"]}
PASSWORD_LITERAL = "s3cret-PASSWORD-xyz"


def _run(coro):
    return asyncio.run(coro)


# --- Fake Playwright layer -------------------------------------------------


class FakeElementHandle:
    def __init__(self, info: dict, page: "FakePage") -> None:
        self.info = info
        self.page = page
        self.clicks = 0
        self.fills: list[str] = []
        self.selects: list[str] = []
        self.hovers = 0
        self.focuses = 0
        self.uploaded_files: list[str] = []
        self._frame: FakeFrame | None = None

    async def evaluate(self, _js: str):
        return self.info

    async def click(self) -> None:
        self.clicks += 1

    async def fill(self, value: str) -> None:
        self.fills.append(value)
        # Like a real input, the value becomes readable on the next
        # snapshot — the leak assertion depends on gateway-side masking.
        self.info["value"] = value

    async def select_option(self, value: str) -> None:
        if self.info.get("tag", "").lower() != "select":
            raise RuntimeError("Element is not a select element")
        options = self.info.get("options", [])
        if value not in options:
            raise RuntimeError(f"Option '{value}' not found in select")
        self.selects.append(value)
        self.info["value"] = value

    async def hover(self) -> None:
        self.hovers += 1

    async def focus(self) -> None:
        self.focuses += 1

    async def set_input_files(self, path: str) -> None:
        if self.info.get("type", "").lower() != "file":
            raise RuntimeError("Element is not a file input")
        self.uploaded_files.append(path)

    async def content_frame(self) -> "FakeFrame | None":
        return self._frame


class FakeKeyboard:
    """Stand-in for Playwright's page.keyboard."""

    def __init__(self) -> None:
        self.presses: list[str] = []

    async def press(self, key: str) -> None:
        self.presses.append(key)


class FakeMouse:
    """Stand-in for Playwright's page.mouse."""

    def __init__(self) -> None:
        self.wheels: list[tuple[int, int]] = []
        self.moves: list[tuple[float, float]] = []

    async def move(self, x: float, y: float) -> None:
        self.moves.append((x, y))

    async def wheel(self, delta_x: int, delta_y: int) -> None:
        self.wheels.append((delta_x, delta_y))


class FakeFrameElement:
    """Stand-in for the ``<iframe>`` ElementHandle from Frame.frame_element().

    Only ``bounding_box()`` is needed: web.scroll centers the cursor over
    the frame before dispatching a Page-level wheel.
    """

    def __init__(self, box: dict | None) -> None:
        self._box = box

    async def bounding_box(self) -> dict | None:
        return self._box


class FakeFrame:
    """Stand-in for a Playwright Frame (iframe content).

    Real Playwright Frame objects do NOT expose .keyboard or .mouse —
    those live on Page only. The production code dispatches keyboard and
    mouse through entry.page, so the fake must not provide them here.
    """

    def __init__(self, url: str = "about:blank", box: dict | None = None) -> None:
        self.url = url
        self._title = "Frame"
        self.elements: list[FakeElementHandle] = []
        # Bounding box of the <iframe> element within the parent page; used
        # by web.scroll to center the cursor over the frame before wheeling.
        self._box = box if box is not None else {
            "x": 100.0, "y": 80.0, "width": 400.0, "height": 300.0,
        }

    async def frame_element(self) -> FakeFrameElement:
        return FakeFrameElement(self._box)

    async def title(self) -> str:
        return self._title

    async def query_selector_all(self, _selector: str) -> list[FakeElementHandle]:
        return list(self.elements)

    async def query_selector(self, selector: str) -> FakeElementHandle | None:
        for el in self.elements:
            if el.info.get("tag", "").lower() == selector.lower():
                return el
        return None

    async def evaluate(self, _js: str, arg=None):
        return None

    async def wait_for_selector(self, selector: str, **kwargs) -> FakeElementHandle | None:
        for el in self.elements:
            if el.info.get("tag", "").lower() == selector.lower():
                return el
        return None


class FakePage:
    def __init__(self) -> None:
        self.url = "about:blank"
        self._title = "Fake App"
        self.elements: list[FakeElementHandle] = []
        self.goto_calls: list[str] = []
        self.redirect_to: str | None = None
        self.viewport_size = {"width": 1280, "height": 720}
        # (quality, clip) -> byte length; default rule fits the 64 KiB cap.
        self.screenshot_rule = lambda quality, clip: b"x" * (quality * 100)
        # Values each element held at the last screenshot() call, so
        # masking tests can assert a credential never survives into it.
        self.last_capture_values: list = []
        # SPEC-050: keyboard, mouse, and wait support.
        self.keyboard = FakeKeyboard()
        self.mouse = FakeMouse()
        # wait_for_selector behaviour: by default the first matching element
        # is returned immediately; set wait_fail = True to simulate timeout.
        self.wait_fail = False

    async def goto(self, url: str, **kwargs) -> None:
        self.goto_calls.append(url)
        if self.redirect_to is not None:
            self.url, self.redirect_to = self.redirect_to, None
        else:
            self.url = url

    async def title(self) -> str:
        return self._title

    async def query_selector_all(self, _selector: str) -> list[FakeElementHandle]:
        return list(self.elements)

    async def query_selector(self, selector: str) -> FakeElementHandle | None:
        """Return the first element whose tag matches the selector."""
        for el in self.elements:
            if el.info.get("tag", "").lower() == selector.lower():
                return el
        return None

    async def wait_for_selector(
        self, selector: str, **kwargs
    ) -> FakeElementHandle | None:
        if self.wait_fail:
            raise RuntimeError("Timeout exceeded")
        return await self.query_selector(selector)

    async def screenshot(self, type: str | None = None, quality: int | None = None,
                         clip: dict | None = None) -> bytes:
        self.last_capture_values = [el.info.get("value") for el in self.elements]
        return self.screenshot_rule(quality or 70, clip)

    async def evaluate(self, _js: str, arg=None):
        # Stand-in for the screenshot credential mask/unmask JS: a mask pass
        # (called with the secret-value list) rewrites matching element
        # values to dots and stashes the originals; the unmask pass (no arg)
        # restores them. Mirrors _SCREENSHOT_MASK_JS/_SCREENSHOT_UNMASK_JS.
        if arg is not None:
            count = 0
            for el in self.elements:
                value = el.info.get("value")
                if isinstance(value, str) and value in arg:
                    el.info["__cv_orig"] = value
                    el.info["value"] = "\u2022" * 8
                    count += 1
            return count
        for el in self.elements:
            if "__cv_orig" in el.info:
                el.info["value"] = el.info.pop("__cv_orig")
        return None

    def add_element(self, **info) -> FakeElementHandle:
        handle = FakeElementHandle(info, self)
        self.elements.append(handle)
        return handle


class FakeContext:
    def __init__(self, browser: "FakeBrowser") -> None:
        self._browser = browser
        self.closed = False
        self.page = FakePage()

    async def new_page(self) -> FakePage:
        return self.page

    async def close(self) -> None:
        self.closed = True


class FakeBrowser:
    def __init__(self) -> None:
        self.contexts: list[FakeContext] = []
        self.closed = False

    async def new_context(self) -> FakeContext:
        context = FakeContext(self)
        self.contexts.append(context)
        return context

    async def close(self) -> None:
        self.closed = True


class _FakeChromium:
    def __init__(self, browser: FakeBrowser, fail: bool) -> None:
        self._browser = browser
        self._fail = fail
        self.dialed: list[str] = []

    async def connect_over_cdp(self, endpoint: str) -> FakeBrowser:
        self.dialed.append(endpoint)
        if self._fail:
            raise RuntimeError("sidecar unreachable")
        return self._browser


class _FakePlaywrightHost:
    def __init__(self, browser: FakeBrowser, fail: bool) -> None:
        self.chromium = _FakeChromium(browser, fail)
        self.stopped = False

    async def stop(self) -> None:
        self.stopped = True


def _playwright_factory(browser: FakeBrowser, fail: bool = False):
    host = _FakePlaywrightHost(browser, fail)

    class _Starter:
        async def start(self):
            return host

    return lambda: _Starter(), host


def _make_connector(
    allow_origins: tuple[str, ...] = (ALLOWED_ORIGIN,),
    session_ttl_seconds: int = 600,
    max_sessions: int = 4,
    flow_max_steps: int = 20,
    credential_sets_path: str = "",
    screenshot_max_bytes: int = 65536,
    browser: FakeBrowser | None = None,
    fail_connect: bool = False,
) -> tuple[BrowserConnector, FakeBrowser]:
    browser = browser or FakeBrowser()
    factory, _host = _playwright_factory(browser, fail_connect)
    connector = BrowserConnector(
        cdp_endpoint="ws://localhost:9222",
        allow_origins=allow_origins,
        session_ttl_seconds=session_ttl_seconds,
        max_sessions=max_sessions,
        flow_max_steps=flow_max_steps,
        credential_sets_path=credential_sets_path,
        screenshot_max_bytes=screenshot_max_bytes,
        skills_service_url="http://skills-hub:8000",
        playwright_factory=factory,
    )
    return connector, browser


def _registry(connector: BrowserConnector, allow_mutating: bool = True) -> ToolRegistry:
    registry = ToolRegistry(allow_mutating=allow_mutating)
    connector.register_tools(registry)
    return registry


def _stub_skill(connector: BrowserConnector, record: dict | None) -> None:
    async def _fetch(skill_id: str):
        if record is None:
            return None, "SKILL_NOT_FOUND", f"Skill '{skill_id}' was not found."
        return record, "", ""

    connector.fetch_skill = _fetch  # type: ignore[method-assign]


def _web_skill(
    risk_class: str | None = "write",
    title: str = "",
    description: str = "",
    flow_intent: str = "",
) -> dict:
    skill = {
        "skill_id": "team-a/web/inventoryhealth",
        "web_target": f"{ALLOWED_ORIGIN}/login",
        "risk_class": risk_class,
    }
    # SPEC-051 R-6 / SPEC-053 R-2: optional human-readable frontmatter; only
    # present when the caller supplies it so the default shape stays
    # byte-for-byte unchanged.
    if title:
        skill["title"] = title
    if description:
        skill["description"] = description
    if flow_intent:
        skill["flow_intent"] = flow_intent
    return skill


# --- Settings ---------------------------------------------------------------


class BrowserSettingsTests(unittest.TestCase):
    def test_knobs_parse_from_env(self) -> None:
        env = {
            "GATEWAY_BROWSER_ENABLED": "true",
            "GATEWAY_BROWSER_CDP_ENDPOINT": "ws://browser:9223",
            "GATEWAY_BROWSER_SESSION_TTL": "120",
            "GATEWAY_BROWSER_MAX_SESSIONS": "2",
            "GATEWAY_BROWSER_ALLOW_ORIGINS": "https://a.internal, https://b.internal:8443",
            "GATEWAY_BROWSER_FLOW_MAX_STEPS": "7",
            "GATEWAY_BROWSER_CREDENTIAL_SETS": "/etc/luban/browser-creds.json",
            "GATEWAY_BROWSER_SCREENSHOT_MAX_BYTES": "1024",
        }
        with patch.dict(os.environ, env):
            settings = GatewaySettings.from_env()
        self.assertTrue(settings.browser_enabled)
        self.assertEqual(settings.browser_cdp_endpoint, "ws://browser:9223")
        self.assertEqual(settings.browser_session_ttl_seconds, 120)
        self.assertEqual(settings.browser_max_sessions, 2)
        self.assertEqual(
            settings.browser_allow_origins,
            ("https://a.internal", "https://b.internal:8443"),
        )
        self.assertEqual(settings.browser_flow_max_steps, 7)
        self.assertEqual(
            settings.browser_credential_sets_path, "/etc/luban/browser-creds.json"
        )
        self.assertEqual(settings.browser_screenshot_max_bytes, 1024)

    def test_defaults_are_off_and_deny_all(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            settings = GatewaySettings.from_env()
        self.assertFalse(settings.browser_enabled)
        self.assertEqual(settings.browser_allow_origins, ())
        self.assertEqual(settings.browser_credential_sets_path, "")
        self.assertEqual(settings.browser_screenshot_max_bytes, 65536)

    def test_disabled_posture_registers_nothing(self) -> None:
        from tool_gateway.app import _build_tool_registry
        from tool_gateway.core.config import get_settings

        env = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith("GATEWAY_")
        }
        with patch.dict(os.environ, env, clear=True):
            get_settings.cache_clear()
            try:
                registry, browser_connector = _build_tool_registry()
            finally:
                get_settings.cache_clear()
        self.assertIsNone(browser_connector)
        names = {d.name for d in registry.list_definitions()}
        self.assertFalse(any(name.startswith("web.") for name in names))


# --- Session pool -----------------------------------------------------------


class SessionPoolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = [0.0]
        self.clock = lambda: self.now[0]
        self.browser = FakeBrowser()
        factory, host = _playwright_factory(self.browser)
        self.host = host
        self.pool = BrowserSessionPool(
            cdp_endpoint="ws://localhost:9222",
            ttl_seconds=600,
            max_sessions=2,
            playwright_factory=factory,
            clock=self.clock,
        )

    def test_session_reused_within_ttl(self) -> None:
        first = _run(self.pool.get_or_create("user-a"))
        second = _run(self.pool.get_or_create("user-a"))
        self.assertIs(first.page, second.page)
        self.assertEqual(self.pool.session_count, 1)
        self.assertEqual(len(self.browser.contexts), 1)

    def test_session_expires_after_ttl(self) -> None:
        entry = _run(self.pool.get_or_create("user-a"))
        self.now[0] = 601.0
        _run(self.pool.get_or_create("user-b"))
        context = self.browser.contexts[0]
        self.assertTrue(context.closed)
        self.assertNotIn("user-a", self.pool._sessions)
        self.assertIsNot(entry, self.pool.get("user-b"))

    def test_cap_evicts_oldest_idle(self) -> None:
        first = _run(self.pool.get_or_create("user-a"))
        self.now[0] = 10.0
        _run(self.pool.get_or_create("user-b"))
        self.now[0] = 20.0
        _run(self.pool.get_or_create("user-c"))
        self.assertTrue(self.browser.contexts[0].closed)  # oldest-idle
        self.assertEqual(self.pool.session_count, 2)
        self.assertIsNotNone(first)

    def test_drop_closes_context(self) -> None:
        _run(self.pool.get_or_create("user-a"))
        _run(self.pool.drop("user-a"))
        self.assertTrue(self.browser.contexts[0].closed)
        self.assertEqual(self.pool.session_count, 0)

    def test_start_failure_reports_not_ready(self) -> None:
        browser = FakeBrowser()
        factory, _ = _playwright_factory(browser, fail=True)
        pool = BrowserSessionPool(
            "ws://localhost:9222", 600, 4, playwright_factory=factory
        )
        self.assertFalse(_run(pool.start()))
        from tool_gateway.tools.browser_sessions import BrowserNotReady

        with self.assertRaises(BrowserNotReady):
            _run(pool.get_or_create("user-a"))

    def test_bare_ws_endpoint_dialed_as_http_discovery_base(self) -> None:
        # Playwright dials a bare ws:// endpoint verbatim and 404s on "/";
        # the pool must hand it the http:// discovery base instead so it
        # resolves /json/version for the real browser websocket.
        _run(self.pool.get_or_create("user-a"))
        self.assertEqual(self.host.chromium.dialed, ["http://localhost:9222/"])

    def test_endpoint_normalization_matrix(self) -> None:
        from tool_gateway.tools.browser_sessions import _normalize_cdp_endpoint

        cases = {
            "ws://localhost:9222": "http://localhost:9222/",
            "ws://localhost:9222/": "http://localhost:9222/",
            "wss://browser.example:9222": "https://browser.example:9222/",
            # a complete browser websocket URL passes through untouched
            "ws://localhost:9222/devtools/browser/abc-123": (
                "ws://localhost:9222/devtools/browser/abc-123"
            ),
            # http(s) discovery bases pass through untouched
            "http://localhost:9222": "http://localhost:9222",
        }
        for endpoint, expected in cases.items():
            with self.subTest(endpoint=endpoint):
                self.assertEqual(_normalize_cdp_endpoint(endpoint), expected)

    def test_concurrent_same_key_creates_one_context(self) -> None:
        # Two first-use callers for the same key must not each build a
        # browser context (the second insert would orphan the first). The
        # per-key creation lock + double-check collapse them onto one.
        _run(self.pool.start())  # isolate creation from the connect path

        async def _scenario():
            return await asyncio.gather(
                self.pool.get_or_create("user-a"),
                self.pool.get_or_create("user-a"),
            )

        first, second = _run(_scenario())
        self.assertIs(first, second)
        self.assertIs(first.page, second.page)
        self.assertEqual(len(self.browser.contexts), 1)
        self.assertEqual(self.pool.session_count, 1)


# --- Registration -----------------------------------------------------------


class RegistrationTests(unittest.TestCase):
    def test_read_tools_only_without_mutating_admission(self) -> None:
        connector, _ = _make_connector()
        registry = _registry(connector, allow_mutating=False)
        names = {d.name: d for d in registry.list_definitions()}
        # Read-tier tools only. web.evaluate is write-tier (arbitrary JS can
        # mutate the DOM and read back masked secrets), so it is NOT
        # registered when mutating admission is off.
        read_names = {
            "web.navigate", "web.snapshot", "web.screenshot",
            "web.fill_credential",
            # SPEC-050 read-tier tools.
            "web.extract", "web.wait_for", "web.hover",
            "web.scroll", "web.switch_frame",
        }
        self.assertEqual(set(names), read_names)
        # Write-tier tools must be absent.
        for write_name in ("web.click", "web.type", "web.select",
                           "web.press_key", "web.upload_file",
                           "web.evaluate"):
            self.assertNotIn(write_name, names)

    def test_interaction_tools_admitted_with_mutating_flag(self) -> None:
        connector, _ = _make_connector()
        registry = _registry(connector, allow_mutating=True)
        names = {d.name: d for d in registry.list_definitions()}
        # 6 original + 9 new SPEC-050 tools = 15 total.
        self.assertEqual(len(names), 15)
        # SPEC-049 write-tier.
        self.assertEqual(names["web.click"].risk_level, "write")
        self.assertEqual(names["web.type"].risk_level, "write")
        # SPEC-050 write-tier.
        self.assertEqual(names["web.select"].risk_level, "write")
        self.assertEqual(names["web.press_key"].risk_level, "write")
        self.assertEqual(names["web.upload_file"].risk_level, "write")
        # web.evaluate is write-tier (issues #2/#3): arbitrary JS can mutate
        # the DOM and read masked secrets, so it inherits the HITL gate.
        self.assertEqual(names["web.evaluate"].risk_level, "write")
        # SPEC-050 read-tier.
        self.assertEqual(names["web.navigate"].risk_level, "read")
        self.assertEqual(names["web.extract"].risk_level, "read")
        self.assertEqual(names["web.wait_for"].risk_level, "read")
        self.assertEqual(names["web.hover"].risk_level, "read")
        self.assertEqual(names["web.scroll"].risk_level, "read")
        self.assertEqual(names["web.switch_frame"].risk_level, "read")
        self.assertEqual(names["web.click"].category, "browser")

    def test_browser_not_ready_is_structured(self) -> None:
        connector, _ = _make_connector(fail_connect=True)
        registry = _registry(connector)
        result = _run(
            registry.invoke(
                "web.navigate", {"url": f"{ALLOWED_ORIGIN}/login"}, IDENTITY
            )
        )
        self.assertEqual(result.status, "error")
        self.assertEqual(result.error["code"], "BROWSER_NOT_READY")


# --- Origin allowlist -------------------------------------------------------


class AllowlistTests(unittest.TestCase):
    def test_origin_of(self) -> None:
        self.assertEqual(
            origin_of("https://Inventory.Internal:8443/login?x=1"),
            "https://inventory.internal:8443",
        )
        self.assertIsNone(origin_of("ftp://x.internal"))
        self.assertIsNone(origin_of("not a url"))

    def test_allowlist_matrix(self) -> None:
        connector, _ = _make_connector()
        self.assertTrue(connector.is_origin_allowed(f"{ALLOWED_ORIGIN}/login"))
        self.assertFalse(connector.is_origin_allowed("https://evil.example/x"))
        empty, _ = _make_connector(allow_origins=())
        self.assertFalse(empty.is_origin_allowed(f"{ALLOWED_ORIGIN}/login"))

    def test_navigate_outside_allowlist_denied(self) -> None:
        connector, browser = _make_connector()
        registry = _registry(connector)
        result = _run(
            registry.invoke(
                "web.navigate", {"url": "https://evil.example/login"}, IDENTITY
            )
        )
        self.assertEqual(result.status, "denied")
        self.assertEqual(result.error["code"], "BROWSER_ORIGIN_NOT_ALLOWED")
        self.assertIn("evil.example", result.error["message"])
        self.assertEqual(browser.contexts, [])  # no session was created

    def test_empty_allowlist_denies_all(self) -> None:
        connector, _ = _make_connector(allow_origins=())
        registry = _registry(connector)
        result = _run(
            registry.invoke(
                "web.navigate", {"url": f"{ALLOWED_ORIGIN}/login"}, IDENTITY
            )
        )
        self.assertEqual(result.status, "denied")
        self.assertEqual(result.error["code"], "BROWSER_ORIGIN_NOT_ALLOWED")

    def test_redirect_landing_outside_allowlist_errors_and_halts(self) -> None:
        connector, browser = _make_connector()
        registry = _registry(connector)

        async def _scenario():
            entry = await connector.pool.get_or_create("dev.operator")
            entry.page.redirect_to = "https://evil.example/phish"
            return await registry.invoke(
                "web.navigate", {"url": f"{ALLOWED_ORIGIN}/login"}, IDENTITY
            )

        result = _run(_scenario())
        self.assertEqual(result.status, "error")
        self.assertEqual(result.error["code"], "BROWSER_REDIRECT_NOT_ALLOWED")
        self.assertIn("evil.example", result.error["message"])
        # The session page was halted and its flow cleared.
        entry = connector.pool.get("dev.operator")
        self.assertEqual(entry.page.goto_calls[-1], "about:blank")
        self.assertIsNone(entry.flow)


# --- Secret query-param redaction (SPEC-049 R-5) ---------------------------


class SecretQueryRedactionTests(unittest.TestCase):
    def test_masks_secret_param_value(self) -> None:
        url = "https://app.internal/reset?user=alice&newpw=TempPass123!"
        self.assertEqual(
            _redact_secret_query(url),
            "https://app.internal/reset?user=alice&newpw=***",
        )

    def test_masks_multiple_secret_params_keeps_others(self) -> None:
        redacted = _redact_secret_query(
            "https://app.internal/x?password=a&token=b&q=keep"
        )
        self.assertIn("password=***", redacted)
        self.assertIn("token=***", redacted)
        self.assertIn("q=keep", redacted)
        self.assertNotIn("=a", redacted)
        self.assertNotIn("=b", redacted)

    def test_param_match_is_case_insensitive(self) -> None:
        self.assertIn(
            "NewPassword=***",
            _redact_secret_query("https://app.internal/x?NewPassword=hunter2"),
        )

    def test_param_match_is_substring(self) -> None:
        redacted = _redact_secret_query(
            "https://app.internal/x?user_password=p&api_key=k"
        )
        self.assertIn("user_password=***", redacted)
        self.assertIn("api_key=***", redacted)

    def test_url_without_secret_params_is_unchanged(self) -> None:
        url = "https://app.internal/status?user=alice&page=2"
        self.assertEqual(_redact_secret_query(url), url)

    def test_url_without_query_is_unchanged(self) -> None:
        url = "https://app.internal/status"
        self.assertEqual(_redact_secret_query(url), url)


class PostNavigateRedactionTests(unittest.TestCase):
    """SPEC-049 R-5 past ``web.navigate``: the follow-on results mask too.

    Navigate is only the *first* result carrying a secret-bearing URL. The
    browser then sits on that URL while the runbook snapshots it, clicks
    through it, and screenshots it, and each of those results re-serializes
    ``entry.active_target.url`` into the persisted evidence frames. Redacting
    navigate alone left ``?newpw=<plaintext>`` readable in the very next call's
    result — the runbook's own promise ("the gateway redacts the ``newpw``
    query parameter from every result, evidence frame, and audit record") was
    false for everything after the navigation.
    """

    RESET_PATH = "/admin/users/reset/?user=alice@example.com&newpw=TempPass123!"

    def setUp(self) -> None:
        self.connector, self.browser = _make_connector()
        self.registry = _registry(self.connector)
        nav = _run(
            self.registry.invoke(
                "web.navigate", {"url": f"{ALLOWED_ORIGIN}{self.RESET_PATH}"}, IDENTITY
            )
        )
        self.assertEqual(nav.status, "success")
        entry = self.connector.pool.get("dev.operator")
        entry.page.add_element(tag="BUTTON", text="Confirm reset")
        # Refs are only minted by a snapshot (R-2/R-4 contract).
        self.snapshot = _run(self.registry.invoke("web.snapshot", {}, IDENTITY))
        self.assertEqual(self.snapshot.status, "success")

    def test_fixture_page_really_carries_the_plaintext_secret(self) -> None:
        """Pin the fixture: every absence assertion below is vacuous unless the
        plaintext is genuinely sitting in the live page URL to begin with."""
        entry = self.connector.pool.get("dev.operator")
        self.assertIn("newpw=TempPass123!", entry.page.url)

    def test_snapshot_masks_url_and_snapshot_text(self) -> None:
        self.assertNotIn("TempPass123!", self.snapshot.data["url"])
        self.assertIn("newpw=***", self.snapshot.data["url"])
        self.assertIn("user=alice@example.com", self.snapshot.data["url"])
        # The header line inside the snapshot text is the same URL; masking
        # ``data["url"]`` while leaving the text raw would keep the secret
        # readable one field over in the very same result.
        self.assertNotIn("TempPass123!", self.snapshot.data["snapshot"])
        self.assertIn("newpw=***", self.snapshot.data["snapshot"])

    def test_write_interaction_result_masks_secret(self) -> None:
        """The reported leak: ``_step_result``, shared by ``web.click`` /
        ``web.type`` / ``web.select`` / ``web.upload_file`` /
        ``web.fill_credential``."""
        result = _run(self.registry.invoke("web.click", {"ref": 1}, IDENTITY))
        self.assertEqual(result.status, "success")
        self.assertNotIn("TempPass123!", result.data["url"])
        self.assertIn("newpw=***", result.data["url"])
        self.assertIn("user=alice@example.com", result.data["url"])
        # The interaction still landed on the real page with the real value.
        entry = self.connector.pool.get("dev.operator")
        self.assertIn("newpw=TempPass123!", entry.page.url)
        self.assertEqual(entry.page.elements[0].clicks, 1)

    def test_press_key_result_masks_secret(self) -> None:
        """``web.press_key`` builds its own data dict rather than calling
        ``_step_result``, so it needs its own masking."""
        result = _run(
            self.registry.invoke("web.press_key", {"key": "Enter"}, IDENTITY)
        )
        self.assertEqual(result.status, "success")
        self.assertEqual(result.data["key"], "Enter")
        self.assertNotIn("TempPass123!", result.data["url"])
        self.assertIn("newpw=***", result.data["url"])


# --- FlowState serialization (SPEC-051 R-6) ---------------------------------


class FlowStateSerializationTests(unittest.TestCase):
    def test_to_dict_surfaces_headline_and_omits_denied(self) -> None:
        """``to_dict()`` carries the human-readable title/description and the
        SPEC-053 ``flow_intent`` to the kernel card and deliberately omits the
        gateway-internal ``denied`` kill-switch (the HITL path enforces denial
        upstream, so it never rides the flow dict to the kernel)."""
        flow = FlowState(
            skill_id="team-a/web/inventoryhealth",
            origin="https://inventory.internal:8443",
            risk_class="write",
            max_steps=20,
            title="Reset User Password",
            description="Reset a user's password in the admin portal",
            flow_intent="Submit the password reset for the user.",
            steps_used=3,
            approved=False,
        )
        self.assertEqual(
            flow.to_dict(),
            {
                "skill_id": "team-a/web/inventoryhealth",
                "origin": "https://inventory.internal:8443",
                "risk_class": "write",
                "title": "Reset User Password",
                "description": "Reset a user's password in the admin portal",
                "flow_intent": "Submit the password reset for the user.",
                "steps_used": 3,
                "max_steps": 20,
                "approved": False,
            },
        )
        self.assertNotIn("denied", flow.to_dict())

    def test_to_dict_defaults_headline_empty(self) -> None:
        """A flow bound from a skill without frontmatter serializes empty
        headline strings — the kernel card then falls back to tool-level
        rendering rather than dropping the flow framing entirely."""
        flow = FlowState(
            skill_id="s",
            origin="https://a.internal",
            risk_class="read",
            max_steps=20,
        )
        payload = flow.to_dict()
        self.assertEqual(payload["title"], "")
        self.assertEqual(payload["description"], "")
        self.assertEqual(payload["flow_intent"], "")
        self.assertFalse(payload["approved"])


# --- Navigate + flow binding ------------------------------------------------


class FlowBindingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.connector, self.browser = _make_connector()
        self.registry = _registry(self.connector)

    def _navigate(self, params: dict):
        return _run(self.registry.invoke("web.navigate", params, IDENTITY))

    def test_navigate_success_without_skill(self) -> None:
        result = self._navigate({"url": f"{ALLOWED_ORIGIN}/status"})
        self.assertEqual(result.status, "success")
        self.assertEqual(result.data["url"], f"{ALLOWED_ORIGIN}/status")
        self.assertEqual(result.data["title"], "Fake App")
        self.assertNotIn("flow", result.data)
        self.assertEqual(result.evidence["source_system"], "browser")
        self.assertEqual(result.evidence["risk_level"], "read")

    def test_navigate_redacts_secret_query_params(self) -> None:
        # The password-reset demo passes ``?newpw=...`` so the legacy target
        # can auto-fill it; the plaintext value must never enter evidence
        # (SPEC-049 R-5), but the page still navigates with the real value.
        result = self._navigate(
            {"url": f"{ALLOWED_ORIGIN}/admin/reset?user=alice&newpw=TempPass123!"}
        )
        self.assertEqual(result.status, "success")
        self.assertNotIn("TempPass123!", result.data["url"])
        self.assertIn("newpw=***", result.data["url"])
        self.assertIn("user=alice", result.data["url"])
        # The real value still reached the page.
        entry = self.connector.pool.get("dev.operator")
        self.assertIn("newpw=TempPass123!", entry.page.url)

    def test_navigate_binds_write_flow(self) -> None:
        _stub_skill(self.connector, _web_skill("write"))
        result = self._navigate(
            {"url": f"{ALLOWED_ORIGIN}/login", "skill_id": "team-a/web/inventoryhealth"}
        )
        self.assertEqual(result.status, "success")
        self.assertEqual(result.data["flow"]["skill_id"], "team-a/web/inventoryhealth")
        self.assertEqual(result.data["flow"]["risk_class"], "write")
        self.assertFalse(result.data["flow"]["approved"])
        flow = self.connector.pool.get("dev.operator").flow
        self.assertIsInstance(flow, FlowState)
        self.assertEqual(flow.origin, "https://inventory.internal:8443")

    def test_navigate_binds_read_flow_approved(self) -> None:
        _stub_skill(self.connector, _web_skill("read"))
        result = self._navigate(
            {"url": f"{ALLOWED_ORIGIN}/login", "skill_id": "team-a/web/inventoryhealth"}
        )
        self.assertEqual(result.status, "success")
        self.assertTrue(result.data["flow"]["approved"])

    def test_navigate_flow_carries_skill_headline(self) -> None:
        """SPEC-051 R-6: the bound flow dict surfaces the skill's human-readable
        frontmatter so the kernel card headlines the workflow intent (e.g.
        "Reset a user's password") above the bare per-call tool action."""
        _stub_skill(
            self.connector,
            _web_skill(
                "write",
                title="Reset User Password",
                description="Reset a user's password in the admin portal",
            ),
        )
        result = self._navigate(
            {"url": f"{ALLOWED_ORIGIN}/login", "skill_id": "team-a/web/inventoryhealth"}
        )
        self.assertEqual(result.status, "success")
        flow = result.data["flow"]
        self.assertEqual(flow["title"], "Reset User Password")
        self.assertEqual(
            flow["description"], "Reset a user's password in the admin portal"
        )
        # The same headline rides the session's FlowState for later interactions.
        self.assertEqual(
            self.connector.pool.get("dev.operator").flow.title, "Reset User Password"
        )

    def test_navigate_flow_headline_defaults_empty_without_frontmatter(self) -> None:
        """A skill with no title/description frontmatter yields empty strings —
        the kernel card then falls back to tool-level rendering (SPEC-051 R-6)."""
        _stub_skill(self.connector, _web_skill("write"))
        result = self._navigate(
            {"url": f"{ALLOWED_ORIGIN}/login", "skill_id": "team-a/web/inventoryhealth"}
        )
        self.assertEqual(result.status, "success")
        self.assertEqual(result.data["flow"]["title"], "")
        self.assertEqual(result.data["flow"]["description"], "")

    def test_navigate_flow_carries_flow_intent(self) -> None:
        """SPEC-053 R-2: the bound flow dict surfaces the skill's authored
        ``flow_intent`` so the kernel card leads with the plain decision line
        (e.g. "Submit the password reset for the user.") above the technical
        DOM-level action description."""
        _stub_skill(
            self.connector,
            _web_skill(
                "write",
                title="Reset User Password",
                flow_intent="Submit the password reset for the user.",
            ),
        )
        result = self._navigate(
            {"url": f"{ALLOWED_ORIGIN}/login", "skill_id": "team-a/web/inventoryhealth"}
        )
        self.assertEqual(result.status, "success")
        self.assertEqual(
            result.data["flow"]["flow_intent"],
            "Submit the password reset for the user.",
        )
        # The same intent rides the session's FlowState for later interactions.
        self.assertEqual(
            self.connector.pool.get("dev.operator").flow.flow_intent,
            "Submit the password reset for the user.",
        )

    def test_navigate_flow_intent_defaults_empty_without_declaration(self) -> None:
        """A skill with no ``flow_intent`` frontmatter yields an empty string —
        the kernel card then renders exactly as it did pre-SPEC-053 (no intent
        lead line), keeping the change strictly additive."""
        _stub_skill(self.connector, _web_skill("write"))
        result = self._navigate(
            {"url": f"{ALLOWED_ORIGIN}/login", "skill_id": "team-a/web/inventoryhealth"}
        )
        self.assertEqual(result.status, "success")
        self.assertEqual(result.data["flow"]["flow_intent"], "")

    def test_risk_class_defaults_read_when_absent(self) -> None:
        skill = _web_skill(None)
        skill.pop("risk_class")
        _stub_skill(self.connector, skill)
        result = self._navigate(
            {"url": f"{ALLOWED_ORIGIN}/login", "skill_id": "team-a/web/inventoryhealth"}
        )
        self.assertEqual(result.status, "success")
        self.assertEqual(result.data["flow"]["risk_class"], "read")

    def test_flow_target_mismatch_denied(self) -> None:
        _stub_skill(self.connector, _web_skill("write"))
        result = self._navigate(
            {"url": f"{ALLOWED_ORIGIN}/other", "skill_id": "team-a/web/inventoryhealth"}
        )
        self.assertEqual(result.status, "denied")
        self.assertEqual(result.error["code"], "BROWSER_FLOW_TARGET_MISMATCH")

    def test_skill_without_web_target_errors(self) -> None:
        _stub_skill(self.connector, {"skill_id": "team-a/plain"})
        result = self._navigate(
            {"url": f"{ALLOWED_ORIGIN}/login", "skill_id": "team-a/plain"}
        )
        self.assertEqual(result.status, "error")
        self.assertEqual(result.error["code"], "SKILL_NOT_WEB_FLOW")

    def test_unknown_skill_errors(self) -> None:
        _stub_skill(self.connector, None)
        result = self._navigate(
            {"url": f"{ALLOWED_ORIGIN}/login", "skill_id": "team-a/web/ghost"}
        )
        self.assertEqual(result.status, "error")
        self.assertEqual(result.error["code"], "SKILL_NOT_FOUND")

    def test_invalid_url_rejected(self) -> None:
        result = self._navigate({"url": "javascript:alert(1)"})
        self.assertEqual(result.status, "error")
        self.assertEqual(result.error["code"], "INVALID_PARAMETERS")

    def test_flow_target_path_requires_segment_boundary(self) -> None:
        _stub_skill(self.connector, _web_skill("write"))
        # A sibling path sharing only the "/login" prefix is NOT "under" the
        # declared target and must be refused...
        denied = self._navigate(
            {"url": f"{ALLOWED_ORIGIN}/loginfoo",
             "skill_id": "team-a/web/inventoryhealth"}
        )
        self.assertEqual(denied.status, "denied")
        self.assertEqual(denied.error["code"], "BROWSER_FLOW_TARGET_MISMATCH")
        # ...while a real sub-path of the target is admitted.
        allowed = self._navigate(
            {"url": f"{ALLOWED_ORIGIN}/login/sso",
             "skill_id": "team-a/web/inventoryhealth"}
        )
        self.assertEqual(allowed.status, "success")

    def test_navigation_error_after_bind_clears_flow(self) -> None:
        _stub_skill(self.connector, _web_skill("write"))
        entry = _run(self.connector.pool.get_or_create("dev.operator"))

        async def _boom(url: str, **kwargs) -> None:
            raise RuntimeError("dns failure")

        entry.page.goto = _boom  # type: ignore[method-assign]
        result = self._navigate(
            {"url": f"{ALLOWED_ORIGIN}/login",
             "skill_id": "team-a/web/inventoryhealth"}
        )
        self.assertEqual(result.status, "error")
        self.assertEqual(result.error["code"], "BROWSER_NAVIGATION_ERROR")
        # The flow bound on this call never reached its target, so it is
        # dropped rather than left stale for a later interaction.
        self.assertIsNone(entry.flow)

    def test_navigation_error_masks_a_secret_in_the_exception_message(self) -> None:
        # A Playwright navigation error interpolates the target URL, which for
        # the password-reset demo carries ``?newpw=<value>``. That message rides
        # into results, evidence and the audit trail, so the secret query is
        # masked before it leaves (SPEC-049 R-5) — the page still navigated
        # with the real value, only the reported copy is redacted.
        entry = _run(self.connector.pool.get_or_create("dev.operator"))
        target = f"{ALLOWED_ORIGIN}/admin/reset?user=alice&newpw=TempPass123!"

        async def _boom(url: str, **kwargs) -> None:
            raise RuntimeError(f'Page.goto: navigating to "{url}", timed out')

        entry.page.goto = _boom  # type: ignore[method-assign]
        result = self._navigate({"url": target})
        self.assertEqual(result.status, "error")
        self.assertEqual(result.error["code"], "BROWSER_NAVIGATION_ERROR")
        self.assertNotIn("TempPass123!", result.error["message"])
        self.assertIn("newpw=***", result.error["message"])
        # The non-secret param survives, so the failure stays diagnosable.
        self.assertIn("user=alice", result.error["message"])


# --- Deviation guard --------------------------------------------------------


class DeviationGuardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.connector, self.browser = _make_connector(flow_max_steps=2)
        self.registry = _registry(self.connector)

    def _bind_write_flow(self) -> None:
        _stub_skill(self.connector, _web_skill("write"))
        result = _run(
            self.registry.invoke(
                "web.navigate",
                {
                    "url": f"{ALLOWED_ORIGIN}/login",
                    "skill_id": "team-a/web/inventoryhealth",
                },
                IDENTITY,
            )
        )
        self.assertEqual(result.status, "success")
        page = self.connector.pool.get("dev.operator").page
        page.add_element(tag="BUTTON", text="Submit")
        # Refs are only minted by a snapshot (R-2/R-4 contract).
        snap = _run(self.registry.invoke("web.snapshot", {}, IDENTITY))
        self.assertEqual(snap.status, "success")

    def _navigate_unbound(self, path: str = "/login") -> None:
        """Land on an allowlisted origin with NO skill bound (ad-hoc session).

        ``web.navigate`` without a ``skill_id`` binds no flow, so the
        interaction that follows exercises SPEC-054 R-2's unbound
        park-then-execute path. Refs are minted by the trailing snapshot.
        """
        result = _run(
            self.registry.invoke(
                "web.navigate", {"url": f"{ALLOWED_ORIGIN}{path}"}, IDENTITY
            )
        )
        self.assertEqual(result.status, "success")
        entry = self.connector.pool.get("dev.operator")
        self.assertIsNone(entry.flow)
        entry.page.add_element(tag="BUTTON", text="Delete pod")
        snap = _run(self.registry.invoke("web.snapshot", {}, IDENTITY))
        self.assertEqual(snap.status, "success")

    def test_click_unbound_allowlisted_origin_executes(self) -> None:
        # SPEC-054 R-2: an ad-hoc write on an allowlisted origin is no longer
        # hard-denied for lacking a bound flow. The kernel's per-action ASK
        # gated it upstream; once approved and signed, the gateway executes it.
        # Replaces test_click_without_bound_flow_denied.
        self._navigate_unbound()
        result = _run(self.registry.invoke("web.click", {"ref": 1}, IDENTITY))
        self.assertEqual(result.status, "success")
        self.assertEqual(result.evidence["risk_level"], "write")
        entry = self.connector.pool.get("dev.operator")
        self.assertIsNone(entry.flow)  # still no flow bound
        self.assertEqual(entry.page.elements[0].clicks, 1)
        # No flow => no step budget is accounted or reported: per-action consent
        # is the bound (SPEC-055 budgets an accumulated sequence at graduation).
        self.assertNotIn("steps_used", result.data)
        self.assertNotIn("steps_budget", result.data)

    def test_click_unbound_off_allowlist_halts_and_denies(self) -> None:
        # A fresh session sits at about:blank (no allowlisted origin): the
        # unbound path mirrors gate_capture's live-origin re-check and refuses,
        # so the deny-by-default allowlist posture is unchanged.
        result = _run(self.registry.invoke("web.click", {"ref": 1}, IDENTITY))
        self.assertEqual(result.status, "error")
        self.assertEqual(result.error["code"], "BROWSER_REDIRECT_NOT_ALLOWED")
        entry = self.connector.pool.get("dev.operator")
        self.assertIsNone(entry.flow)
        self.assertIn("about:blank", entry.page.goto_calls)  # page halted

    def test_click_unbound_origin_drift_halts(self) -> None:
        # A client-side redirect between web.navigate and the interaction lands
        # the page off the allowlist; the unbound write is halted (about:blank)
        # and refused rather than executed on the drifted page.
        self._navigate_unbound()
        entry = self.connector.pool.get("dev.operator")
        entry.page.url = "https://evil.external/pwned"  # post-load redirect
        result = _run(self.registry.invoke("web.click", {"ref": 1}, IDENTITY))
        self.assertEqual(result.status, "error")
        self.assertEqual(result.error["code"], "BROWSER_REDIRECT_NOT_ALLOWED")
        self.assertIn("about:blank", entry.page.goto_calls)  # halted
        self.assertEqual(entry.page.elements[0].clicks, 0)

    def test_unbound_flow_provenance_denied_authority_stale(self) -> None:
        # ADR-0010 / SPEC-054 R-2: an execution signed under a flow authority
        # but presented with no flow bound (the flow was cleared) is refused,
        # never reinterpreted as a per-action approval.
        self._navigate_unbound()
        stale = {**IDENTITY, "approval_kind": "flow"}
        result = _run(self.registry.invoke("web.click", {"ref": 1}, stale))
        self.assertEqual(result.status, "denied")
        self.assertEqual(result.error["code"], "BROWSER_FLOW_AUTHORITY_STALE")
        entry = self.connector.pool.get("dev.operator")
        self.assertEqual(entry.page.elements[0].clicks, 0)

    def test_unbound_action_provenance_executes(self) -> None:
        # The matching positive: an action-provenance execution on an
        # allowlisted unbound origin proceeds (the per-action approval path).
        self._navigate_unbound()
        action = {**IDENTITY, "approval_kind": "action"}
        result = _run(self.registry.invoke("web.click", {"ref": 1}, action))
        self.assertEqual(result.status, "success")
        self.assertEqual(
            self.connector.pool.get("dev.operator").page.elements[0].clicks, 1
        )

    def test_bound_flow_ignores_approval_kind(self) -> None:
        # One-directional / fail-closed: with a flow bound, approval_kind never
        # suppresses a bound-flow guard. A read-class binding still refuses a
        # write even when the envelope claims action provenance.
        _stub_skill(self.connector, _web_skill("read"))
        _run(
            self.registry.invoke(
                "web.navigate",
                {"url": f"{ALLOWED_ORIGIN}/login",
                 "skill_id": "team-a/web/inventoryhealth"},
                IDENTITY,
            )
        )
        entry = self.connector.pool.get("dev.operator")
        entry.page.add_element(tag="BUTTON", text="Submit")
        _run(self.registry.invoke("web.snapshot", {}, IDENTITY))
        action = {**IDENTITY, "approval_kind": "action"}
        result = _run(self.registry.invoke("web.click", {"ref": 1}, action))
        self.assertEqual(result.status, "denied")
        self.assertEqual(result.error["code"], "BROWSER_FLOW_READ_ONLY")

    def test_bound_flow_provenance_executes_normally(self) -> None:
        # A flow-provenance execution WITH a flow bound is the normal SPEC-051
        # auto-signed path: no staleness refusal, the step is accounted.
        self._bind_write_flow()
        flow_id = {**IDENTITY, "approval_kind": "flow"}
        result = _run(self.registry.invoke("web.click", {"ref": 1}, flow_id))
        self.assertEqual(result.status, "success")
        self.assertEqual(result.data["steps_used"], 1)

    def test_click_in_read_flow_denied(self) -> None:
        _stub_skill(self.connector, _web_skill("read"))
        _run(
            self.registry.invoke(
                "web.navigate",
                {
                    "url": f"{ALLOWED_ORIGIN}/login",
                    "skill_id": "team-a/web/inventoryhealth",
                },
                IDENTITY,
            )
        )
        result = _run(self.registry.invoke("web.click", {"ref": 1}, IDENTITY))
        self.assertEqual(result.status, "denied")
        self.assertEqual(result.error["code"], "BROWSER_FLOW_READ_ONLY")

    def test_approved_write_flow_executes_and_records(self) -> None:
        self._bind_write_flow()
        result = _run(self.registry.invoke("web.click", {"ref": 1}, IDENTITY))
        self.assertEqual(result.status, "success")
        self.assertEqual(result.evidence["risk_level"], "write")
        self.assertEqual(result.data["steps_used"], 1)
        self.assertEqual(result.data["steps_budget"], 2)
        flow = self.connector.pool.get("dev.operator").flow
        self.assertTrue(flow.approved)  # execution is evidence of approval
        element = self.connector.pool.get("dev.operator").page.elements[0]
        self.assertEqual(element.clicks, 1)

    def test_denied_flow_refuses_interactions(self) -> None:
        self._bind_write_flow()
        self.connector.pool.get("dev.operator").flow.denied = True
        result = _run(self.registry.invoke("web.click", {"ref": 1}, IDENTITY))
        self.assertEqual(result.status, "denied")
        self.assertEqual(result.error["code"], "BROWSER_FLOW_DENIED")
        element = self.connector.pool.get("dev.operator").page.elements[0]
        self.assertEqual(element.clicks, 0)

    def test_step_budget_exhaustion_denies(self) -> None:
        self._bind_write_flow()
        for expected_steps in (1, 2):
            result = _run(self.registry.invoke("web.click", {"ref": 1}, IDENTITY))
            self.assertEqual(result.status, "success")
            self.assertEqual(result.data["steps_used"], expected_steps)
        result = _run(self.registry.invoke("web.click", {"ref": 1}, IDENTITY))
        self.assertEqual(result.status, "denied")
        self.assertEqual(result.error["code"], "BROWSER_FLOW_EXHAUSTED")

    def test_unknown_ref_errors(self) -> None:
        self._bind_write_flow()
        result = _run(self.registry.invoke("web.click", {"ref": 99}, IDENTITY))
        self.assertEqual(result.status, "error")
        self.assertEqual(result.error["code"], "BROWSER_REF_UNKNOWN")

    def test_type_executes_inside_bound_flow(self) -> None:
        self._bind_write_flow()
        page = self.connector.pool.get("dev.operator").page
        field = page.add_element(tag="INPUT", type="text", name="note")
        _run(self.registry.invoke("web.snapshot", {}, IDENTITY))
        result = _run(
            self.registry.invoke(
                "web.type", {"ref": 2, "text": "maintenance window"}, IDENTITY
            )
        )
        self.assertEqual(result.status, "success")
        self.assertEqual(field.fills, ["maintenance window"])

    def test_interaction_off_flow_origin_denied(self) -> None:
        # A plain navigate to a *second* allowlisted origin leaves the flow
        # bound to the first; the guard must refuse the off-origin write
        # rather than run it under an approval that named the first target.
        other = "https://other.internal:8443"
        connector, _ = _make_connector(allow_origins=(ALLOWED_ORIGIN, other))
        registry = _registry(connector)
        _stub_skill(connector, _web_skill("write"))
        bind = _run(
            registry.invoke(
                "web.navigate",
                {"url": f"{ALLOWED_ORIGIN}/login",
                 "skill_id": "team-a/web/inventoryhealth"},
                IDENTITY,
            )
        )
        self.assertEqual(bind.status, "success")
        # Drift to the other allowlisted origin without rebinding the flow.
        drift = _run(
            registry.invoke("web.navigate", {"url": f"{other}/admin"}, IDENTITY)
        )
        self.assertEqual(drift.status, "success")
        entry = connector.pool.get("dev.operator")
        self.assertIsNotNone(entry.flow)  # still bound to the first origin
        entry.page.add_element(tag="BUTTON", text="Delete")
        _run(registry.invoke("web.snapshot", {}, IDENTITY))
        result = _run(registry.invoke("web.click", {"ref": 1}, IDENTITY))
        self.assertEqual(result.status, "denied")
        self.assertEqual(result.error["code"], "BROWSER_FLOW_ORIGIN_DEVIATED")
        self.assertEqual(entry.page.elements[0].clicks, 0)


# --- Chat-session keying (SPEC-049 R-1) -------------------------------------


class ChatSessionKeyingTests(unittest.TestCase):
    """The pool keys on the chat session id, so one browser context spans a
    whole web-check flow across the owner→approver HITL identity switch:
    the resumed write-tier interaction carries the approver's subject but
    the same chat session, and must land on the flow the owner bound."""

    def setUp(self) -> None:
        self.connector, self.browser = _make_connector(flow_max_steps=5)
        self.registry = _registry(self.connector)
        _stub_skill(self.connector, _web_skill("write"))

    def test_session_key_prefers_chat_session_then_subject(self) -> None:
        self.assertEqual(
            self.connector._session_key(
                {"sub": "luban-operator", "chat_session_id": "ses-1"}
            ),
            "ses-1",
        )
        self.assertEqual(
            self.connector._session_key({"sub": "luban-operator"}),
            "luban-operator",
        )
        self.assertIsNone(self.connector._session_key({"username": "x"}))

    def _bind_write_flow(self, identity: dict) -> None:
        result = _run(
            self.registry.invoke(
                "web.navigate",
                {
                    "url": f"{ALLOWED_ORIGIN}/login",
                    "skill_id": "team-a/web/inventoryhealth",
                },
                identity,
            )
        )
        self.assertEqual(result.status, "success")
        page = self.connector.pool.get(identity["chat_session_id"]).page
        page.add_element(tag="BUTTON", text="Submit")
        snap = _run(self.registry.invoke("web.snapshot", {}, identity))
        self.assertEqual(snap.status, "success")

    def test_write_flow_survives_owner_to_approver_switch(self) -> None:
        owner = {
            "sub": "luban-operator",
            "username": "luban-operator",
            "roles": ["operator"],
            "chat_session_id": "ses-flow-1",
        }
        approver = {
            "sub": "luban-approver",
            "username": "luban-approver",
            "roles": ["approver"],
            "chat_session_id": "ses-flow-1",
        }
        self._bind_write_flow(owner)
        # The approver resumes the write-tier interaction under a different
        # subject but the same chat session: it lands on the owner's bound
        # flow, never a fresh about:blank context.
        result = _run(self.registry.invoke("web.click", {"ref": 1}, approver))
        self.assertEqual(result.status, "success")
        self.assertEqual(result.data["steps_used"], 1)
        self.assertEqual(self.connector.pool.session_count, 1)
        self.assertIsNotNone(self.connector.pool.get("ses-flow-1"))
        element = self.connector.pool.get("ses-flow-1").page.elements[0]
        self.assertEqual(element.clicks, 1)

    def test_different_chat_session_does_not_share_flow(self) -> None:
        owner = {
            "sub": "luban-operator",
            "roles": ["operator"],
            "chat_session_id": "ses-flow-1",
        }
        other = {
            "sub": "luban-operator",
            "roles": ["operator"],
            "chat_session_id": "ses-flow-2",
        }
        self._bind_write_flow(owner)
        # A different chat session is a different browser context: it never
        # inherits ses-flow-1's bound flow. With no flow and a fresh
        # about:blank page (off the allowlist), the interaction is refused by
        # the unbound live-origin re-check — and it never touches the owner's
        # bound flow or page.
        result = _run(self.registry.invoke("web.click", {"ref": 1}, other))
        self.assertEqual(result.status, "error")
        self.assertEqual(result.error["code"], "BROWSER_REDIRECT_NOT_ALLOWED")
        self.assertIsNone(self.connector.pool.get("ses-flow-2").flow)
        self.assertIsNotNone(self.connector.pool.get("ses-flow-1").flow)
        self.assertEqual(
            self.connector.pool.get("ses-flow-1").page.elements[0].clicks, 0
        )


# --- Snapshot + masking -----------------------------------------------------


class SnapshotTests(unittest.TestCase):
    def setUp(self) -> None:
        self.connector, self.browser = _make_connector()
        self.registry = _registry(self.connector)
        _stub_skill(self.connector, _web_skill("write"))
        _run(
            self.registry.invoke(
                "web.navigate",
                {
                    "url": f"{ALLOWED_ORIGIN}/login",
                    "skill_id": "team-a/web/inventoryhealth",
                },
                IDENTITY,
            )
        )
        self.page = self.connector.pool.get("dev.operator").page

    def test_snapshot_enumerates_refs(self) -> None:
        self.page.add_element(tag="BUTTON", text="Sign in")
        self.page.add_element(tag="INPUT", type="text", name="username", value="svc-check")
        result = _run(self.registry.invoke("web.snapshot", {}, IDENTITY))
        self.assertEqual(result.status, "success")
        self.assertEqual(result.data["elements"], 2)
        snapshot = result.data["snapshot"]
        self.assertIn('[1] <button> "Sign in"', snapshot)
        self.assertIn("[2] <input type=text>", snapshot)
        self.assertIn("'svc-check'", snapshot)

    def test_password_values_masked(self) -> None:
        self.page.add_element(tag="INPUT", type="password", value=PASSWORD_LITERAL)
        result = _run(self.registry.invoke("web.snapshot", {}, IDENTITY))
        snapshot = result.data["snapshot"]
        self.assertIn("value=***", snapshot)
        self.assertNotIn(PASSWORD_LITERAL, json.dumps(result.to_dict()))


# --- Credentials ------------------------------------------------------------


class CredentialTests(unittest.TestCase):
    def setUp(self) -> None:
        import tempfile

        self._tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        )
        json.dump(
            {"inventory-app": {"username": "svc-check", "password": PASSWORD_LITERAL}},
            self._tmp,
        )
        self._tmp.close()
        self.connector, self.browser = _make_connector(
            credential_sets_path=self._tmp.name
        )
        self.registry = _registry(self.connector)
        _stub_skill(self.connector, _web_skill("write"))
        _run(
            self.registry.invoke(
                "web.navigate",
                {
                    "url": f"{ALLOWED_ORIGIN}/login",
                    "skill_id": "team-a/web/inventoryhealth",
                },
                IDENTITY,
            )
        )
        self.page = self.connector.pool.get("dev.operator").page
        self.password_field = self.page.add_element(
            tag="INPUT", type="password", name="password"
        )
        snap = _run(self.registry.invoke("web.snapshot", {}, IDENTITY))
        self.assertEqual(snap.status, "success")

    def tearDown(self) -> None:
        os.unlink(self._tmp.name)

    def test_fill_credential_end_to_end(self) -> None:
        result = _run(
            self.registry.invoke(
                "web.fill_credential",
                {"ref": 1, "credential_set": "inventory-app", "field": "password"},
                IDENTITY,
            )
        )
        self.assertEqual(result.status, "success")
        self.assertEqual(result.data["filled"], "password")
        self.assertEqual(self.password_field.fills, [PASSWORD_LITERAL])
        # Leak assertion: the password literal appears in no result field.
        self.assertNotIn(PASSWORD_LITERAL, json.dumps(result.to_dict()))

    def test_filled_value_masked_in_subsequent_snapshot(self) -> None:
        _run(
            self.registry.invoke(
                "web.fill_credential",
                {"ref": 1, "credential_set": "inventory-app", "field": "password"},
                IDENTITY,
            )
        )
        result = _run(self.registry.invoke("web.snapshot", {}, IDENTITY))
        serialized = json.dumps(result.to_dict())
        self.assertNotIn(PASSWORD_LITERAL, serialized)
        self.assertIn("value=***", result.data["snapshot"])

    def test_unknown_credential_set_errors(self) -> None:
        result = _run(
            self.registry.invoke(
                "web.fill_credential",
                {"ref": 1, "credential_set": "ghost", "field": "password"},
                IDENTITY,
            )
        )
        self.assertEqual(result.status, "error")
        self.assertEqual(result.error["code"], "CREDENTIAL_SET_NOT_FOUND")
        # W-3: the error must name the unknown set but must NOT enumerate
        # the available sets (information disclosure).
        self.assertIn("ghost", result.error["message"])
        self.assertNotIn("inventory-app", result.error["message"])

    def test_invalid_field_rejected(self) -> None:
        result = _run(
            self.registry.invoke(
                "web.fill_credential",
                {"ref": 1, "credential_set": "inventory-app", "field": "token"},
                IDENTITY,
            )
        )
        self.assertEqual(result.status, "error")
        self.assertEqual(result.error["code"], "INVALID_PARAMETERS")

    def test_non_basic_set_fails_closed(self) -> None:
        # SPEC-068 R-1: a bearer set carries no username/password, so a
        # browser login flow naming it must fail closed rather than fill a
        # blank (or raise KeyError on the absent field). Rotate the mounted
        # file to a non-basic set; the store reloads on the mtime bump.
        with open(self._tmp.name, "w", encoding="utf-8") as fh:
            json.dump(
                {"inventory-app": {"scheme": "bearer", "token": "abc"}}, fh
            )
        stat = os.stat(self._tmp.name)
        os.utime(self._tmp.name, (stat.st_atime + 10, stat.st_mtime + 10))
        result = _run(
            self.registry.invoke(
                "web.fill_credential",
                {"ref": 1, "credential_set": "inventory-app", "field": "password"},
                IDENTITY,
            )
        )
        self.assertEqual(result.status, "error")
        self.assertEqual(result.error["code"], "CREDENTIAL_SET_NOT_FOUND")
        # The password field was never filled.
        self.assertEqual(self.password_field.fills, [])

    def test_fill_credential_unbound_allowlisted_admitted(self) -> None:
        # SPEC-054 R-2: the flow-binding precondition is relaxed for read-tier
        # ref-addressed interactions so an unbound session can reach and
        # complete a login form. Entry unbound is by reference only
        # (credential_set + field); it stays read-tier and never admits a write
        # without a card. Replaces test_fill_requires_bound_flow.
        connector, _ = _make_connector(credential_sets_path=self._tmp.name)
        registry = _registry(connector)
        _run(
            registry.invoke(
                "web.navigate", {"url": f"{ALLOWED_ORIGIN}/login"}, IDENTITY
            )
        )
        entry = connector.pool.get("dev.operator")
        self.assertIsNone(entry.flow)
        entry.page.add_element(tag="INPUT", type="password")
        _run(registry.invoke("web.snapshot", {}, IDENTITY))
        result = _run(
            registry.invoke(
                "web.fill_credential",
                {"ref": 1, "credential_set": "inventory-app", "field": "password"},
                IDENTITY,
            )
        )
        self.assertEqual(result.status, "success")
        self.assertEqual(result.data["filled"], "password")
        self.assertIsNone(entry.flow)  # still unbound
        self.assertNotIn(PASSWORD_LITERAL, json.dumps(result.to_dict()))

    def test_fill_credential_unbound_off_allowlist_denied(self) -> None:
        # The read-tier relaxation is origin-gated: a fresh about:blank session
        # (off the allowlist) is still refused, mirroring gate_capture.
        connector, _ = _make_connector(credential_sets_path=self._tmp.name)
        registry = _registry(connector)
        entry = _run(connector.pool.get_or_create("dev.operator"))
        entry.page.add_element(tag="INPUT", type="password")
        result = _run(
            registry.invoke(
                "web.fill_credential",
                {"ref": 1, "credential_set": "inventory-app", "field": "password"},
                IDENTITY,
            )
        )
        self.assertEqual(result.status, "error")
        self.assertEqual(result.error["code"], "BROWSER_REDIRECT_NOT_ALLOWED")

    def test_password_masked_out_of_screenshot(self) -> None:
        # A legacy target may render a password into a type=text field; the
        # connector masks password-tier values out of the capture (R-5) and
        # restores the page afterward, so the secret never reaches evidence.
        legacy = self.page.add_element(tag="INPUT", type="text", name="legacy")
        _run(self.registry.invoke("web.snapshot", {}, IDENTITY))  # mint ref 2
        fill = _run(
            self.registry.invoke(
                "web.fill_credential",
                {"ref": 2, "credential_set": "inventory-app", "field": "password"},
                IDENTITY,
            )
        )
        self.assertEqual(fill.status, "success")
        shot = _run(self.registry.invoke("web.screenshot", {}, IDENTITY))
        self.assertEqual(shot.status, "success")
        # At capture time the password was masked to dots...
        self.assertNotIn(PASSWORD_LITERAL, self.page.last_capture_values)
        self.assertIn("\u2022" * 8, self.page.last_capture_values)
        # ...and the field was restored afterward (masking is transient).
        self.assertEqual(legacy.info["value"], PASSWORD_LITERAL)


# --- Session serialization ---------------------------------------------------


class SessionSerializationTests(unittest.TestCase):
    """One chat session's page is driven by one web.* call at a time.

    The kernel runs every tool call a model emits in a turn concurrently
    (agentscope gathers the batch), and one chat session owns exactly one
    browser page. Playwright's ``fill()`` focuses its element and then
    inserts text into whatever holds focus, so two concurrent fills race:
    one lands in the wrong field or is lost entirely, and both still report
    ``success``. The two tests below are a pair — the second proves the
    first has teeth by driving the same two calls past the guard.
    """

    def setUp(self) -> None:
        import tempfile

        self._tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        )
        json.dump(
            {"inventory-app": {"username": "svc-check", "password": PASSWORD_LITERAL}},
            self._tmp,
        )
        self._tmp.close()
        self.connector, self.browser = _make_connector(
            credential_sets_path=self._tmp.name
        )
        self.registry = _registry(self.connector)
        _stub_skill(self.connector, _web_skill("write"))
        _run(
            self.registry.invoke(
                "web.navigate",
                {
                    "url": f"{ALLOWED_ORIGIN}/login",
                    "skill_id": "team-a/web/inventoryhealth",
                },
                IDENTITY,
            )
        )
        self.page = self.connector.pool.get("dev.operator").page
        self.username_field = self.page.add_element(
            tag="INPUT", type="text", name="username"
        )
        self.password_field = self.page.add_element(
            tag="INPUT", type="password", name="password"
        )
        snap = _run(self.registry.invoke("web.snapshot", {}, IDENTITY))
        self.assertEqual(snap.status, "success")  # refs 1 and 2 minted

        # Overlap detector: the sleep(0) is the window a real fill exposes
        # between focusing its element and inserting the text.
        self.in_flight = 0
        self.max_in_flight = 0
        for handle in (self.username_field, self.password_field):
            handle.fill = self._tracked_fill(handle)

    def tearDown(self) -> None:
        os.unlink(self._tmp.name)

    def _tracked_fill(self, handle: FakeElementHandle):
        async def fill(value: str) -> None:
            self.in_flight += 1
            self.max_in_flight = max(self.max_in_flight, self.in_flight)
            try:
                await asyncio.sleep(0)
                handle.fills.append(value)
                handle.info["value"] = value
            finally:
                self.in_flight -= 1

        return fill

    async def _two_fills(self, invoke) -> list:
        return list(
            await asyncio.gather(
                invoke(
                    "web.fill_credential",
                    {
                        "ref": 1,
                        "credential_set": "inventory-app",
                        "field": "username",
                    },
                    IDENTITY,
                ),
                invoke(
                    "web.fill_credential",
                    {
                        "ref": 2,
                        "credential_set": "inventory-app",
                        "field": "password",
                    },
                    IDENTITY,
                ),
            )
        )

    def test_concurrent_fills_are_serialized(self) -> None:
        results = _run(self._two_fills(self.registry.invoke))
        self.assertEqual([r.status for r in results], ["success", "success"])
        self.assertEqual(
            self.max_in_flight, 1,
            "two web.* calls for one session overlapped on its page",
        )
        # Each value landed in the field it was aimed at.
        self.assertEqual(self.username_field.info.get("value"), "svc-check")
        self.assertEqual(self.password_field.info.get("value"), PASSWORD_LITERAL)

    def test_unguarded_calls_would_overlap(self) -> None:
        # Teeth check: driving the same two calls past the guard (straight to
        # the wrapped tool) reproduces the race the lock removes.
        def _bypass(name: str, parameters: dict, identity: dict):
            tool = self.registry.get(name)
            assert tool is not None
            return tool._inner.execute(parameters, identity)

        results = _run(self._two_fills(_bypass))
        self.assertEqual([r.status for r in results], ["success", "success"])
        self.assertEqual(self.max_in_flight, 2)

    def test_refused_call_leaves_no_lock_behind(self) -> None:
        # The guard takes a lock by key without resolving a session, so a key
        # whose only call was refused must not keep its lock for good: the
        # next sweep prunes it, while a live session's lock survives.
        pool = self.connector.pool
        stranger = {
            "sub": "dev.stranger",
            "username": "dev.stranger",
            "roles": ["operator"],
        }
        denied = _run(
            self.registry.invoke(
                "web.navigate", {"url": "https://evil.example/login"}, stranger
            )
        )
        self.assertEqual(denied.error["code"], "BROWSER_ORIGIN_NOT_ALLOWED")
        self.assertIn("dev.stranger", pool._interaction_locks)
        pool.sweep_expired()
        self.assertNotIn("dev.stranger", pool._interaction_locks)
        self.assertIn("dev.operator", pool._interaction_locks)


# --- Screenshots ------------------------------------------------------------


class ScreenshotTests(unittest.TestCase):
    def setUp(self) -> None:
        self.connector, self.browser = _make_connector(screenshot_max_bytes=65536)
        self.registry = _registry(self.connector)
        _run(
            self.registry.invoke(
                "web.navigate", {"url": f"{ALLOWED_ORIGIN}/status"}, IDENTITY
            )
        )
        self.page = self.connector.pool.get("dev.operator").page

    def test_screenshot_success_within_cap(self) -> None:
        result = _run(self.registry.invoke("web.screenshot", {}, IDENTITY))
        self.assertEqual(result.status, "success")
        self.assertEqual(result.data["format"], "jpeg")
        self.assertLessEqual(result.data["bytes"], 65536)
        import base64

        self.assertEqual(
            len(base64.b64decode(result.data["screenshot"])), result.data["bytes"]
        )

    def test_oversize_screenshot_compressed_to_cap(self) -> None:
        # Every quality alone exceeds the cap; only the shrinking clip fits.
        def _rule(quality: int, clip: dict | None) -> bytes:
            size = 100_000
            if clip is not None:
                size = int(size * clip["width"] * clip["height"] / (1280 * 720))
            return b"x" * size

        self.page.screenshot_rule = _rule
        result = _run(self.registry.invoke("web.screenshot", {}, IDENTITY))
        self.assertEqual(result.status, "success")
        self.assertLessEqual(result.data["bytes"], 65536)

    def test_uncompressible_screenshot_errors(self) -> None:
        self.page.screenshot_rule = lambda quality, clip: b"x" * 200_000
        result = _run(self.registry.invoke("web.screenshot", {}, IDENTITY))
        self.assertEqual(result.status, "error")
        self.assertEqual(result.error["code"], "BROWSER_SCREENSHOT_TOO_LARGE")


# --- SPEC-050: new tool tests -----------------------------------------------


class _BoundFlowMixin:
    """Shared helper: bind a write flow and mint refs for interaction tests."""

    connector: BrowserConnector
    registry: ToolRegistry

    def _bind_write_flow(self, identity=None) -> None:
        identity = identity or IDENTITY
        _stub_skill(self.connector, _web_skill("write"))
        result = _run(
            self.registry.invoke(
                "web.navigate",
                {
                    "url": f"{ALLOWED_ORIGIN}/login",
                    "skill_id": "team-a/web/inventoryhealth",
                },
                identity,
            )
        )
        self.assertEqual(result.status, "success")
        page = self.connector.pool.get(
            identity.get("chat_session_id", identity["sub"])
        ).page
        page.add_element(tag="BUTTON", text="Submit")
        snap = _run(self.registry.invoke("web.snapshot", {}, identity))
        self.assertEqual(snap.status, "success")


class WebSelectTests(unittest.TestCase, _BoundFlowMixin):
    def setUp(self) -> None:
        self.connector, self.browser = _make_connector()
        self.registry = _registry(self.connector)

    def test_select_success(self) -> None:
        self._bind_write_flow()
        page = self.connector.pool.get("dev.operator").page
        select_el = page.add_element(
            tag="SELECT", name="priority", options=["low", "high"]
        )
        _run(self.registry.invoke("web.snapshot", {}, IDENTITY))
        result = _run(
            self.registry.invoke(
                "web.select", {"ref": 2, "value": "high"}, IDENTITY
            )
        )
        self.assertEqual(result.status, "success")
        self.assertEqual(select_el.selects, ["high"])
        self.assertEqual(result.data["selected"], "high")
        self.assertEqual(result.data["steps_used"], 1)

    def test_select_not_a_select_element(self) -> None:
        self._bind_write_flow()
        # ref 1 is the BUTTON from _bind_write_flow
        result = _run(
            self.registry.invoke(
                "web.select", {"ref": 1, "value": "x"}, IDENTITY
            )
        )
        self.assertEqual(result.status, "error")
        self.assertEqual(result.error["code"], "BROWSER_SELECT_NOT_A_SELECT")

    def test_select_option_not_found(self) -> None:
        self._bind_write_flow()
        page = self.connector.pool.get("dev.operator").page
        page.add_element(
            tag="SELECT", name="priority", options=["low", "high"]
        )
        _run(self.registry.invoke("web.snapshot", {}, IDENTITY))
        result = _run(
            self.registry.invoke(
                "web.select", {"ref": 2, "value": "missing"}, IDENTITY
            )
        )
        self.assertEqual(result.status, "error")
        self.assertEqual(result.error["code"], "BROWSER_SELECT_OPTION_NOT_FOUND")

    def test_select_unbound_off_allowlist_denied(self) -> None:
        # Fresh about:blank session: the unbound live-origin re-check refuses.
        result = _run(
            self.registry.invoke(
                "web.select", {"ref": 1, "value": "x"}, IDENTITY
            )
        )
        self.assertEqual(result.status, "error")
        self.assertEqual(result.error["code"], "BROWSER_REDIRECT_NOT_ALLOWED")

    def test_select_unbound_allowlisted_executes(self) -> None:
        # SPEC-054 R-2: an ad-hoc select on an allowlisted origin executes once
        # approved upstream — no bound flow required, no step budget accounted.
        _run(
            self.registry.invoke(
                "web.navigate", {"url": f"{ALLOWED_ORIGIN}/edit"}, IDENTITY
            )
        )
        entry = self.connector.pool.get("dev.operator")
        self.assertIsNone(entry.flow)
        select_el = entry.page.add_element(
            tag="SELECT", name="priority", options=["low", "high"]
        )
        _run(self.registry.invoke("web.snapshot", {}, IDENTITY))
        result = _run(
            self.registry.invoke(
                "web.select", {"ref": 1, "value": "high"}, IDENTITY
            )
        )
        self.assertEqual(result.status, "success")
        self.assertEqual(select_el.selects, ["high"])
        self.assertNotIn("steps_used", result.data)


class WebPressKeyTests(unittest.TestCase, _BoundFlowMixin):
    def setUp(self) -> None:
        self.connector, self.browser = _make_connector()
        self.registry = _registry(self.connector)

    def test_press_key_success(self) -> None:
        self._bind_write_flow()
        page = self.connector.pool.get("dev.operator").page
        result = _run(
            self.registry.invoke(
                "web.press_key", {"key": "Enter"}, IDENTITY
            )
        )
        self.assertEqual(result.status, "success")
        self.assertEqual(page.keyboard.presses, ["Enter"])
        self.assertEqual(result.data["key"], "Enter")

    def test_press_key_with_ref_focuses_first(self) -> None:
        self._bind_write_flow()
        page = self.connector.pool.get("dev.operator").page
        field = page.add_element(tag="INPUT", type="text", name="search")
        _run(self.registry.invoke("web.snapshot", {}, IDENTITY))
        result = _run(
            self.registry.invoke(
                "web.press_key", {"ref": 2, "key": "Tab"}, IDENTITY
            )
        )
        self.assertEqual(result.status, "success")
        self.assertEqual(field.focuses, 1)
        self.assertEqual(page.keyboard.presses, ["Tab"])

    def test_press_key_unbound_off_allowlist_denied(self) -> None:
        # Fresh about:blank session: the unbound live-origin re-check refuses.
        result = _run(
            self.registry.invoke(
                "web.press_key", {"key": "Enter"}, IDENTITY
            )
        )
        self.assertEqual(result.status, "error")
        self.assertEqual(result.error["code"], "BROWSER_REDIRECT_NOT_ALLOWED")

    def test_press_key_unbound_allowlisted_executes(self) -> None:
        # SPEC-054 R-2: an ad-hoc keypress on an allowlisted origin executes
        # once approved upstream — no bound flow, no step budget accounted.
        _run(
            self.registry.invoke(
                "web.navigate", {"url": f"{ALLOWED_ORIGIN}/edit"}, IDENTITY
            )
        )
        entry = self.connector.pool.get("dev.operator")
        self.assertIsNone(entry.flow)
        result = _run(
            self.registry.invoke(
                "web.press_key", {"key": "Enter"}, IDENTITY
            )
        )
        self.assertEqual(result.status, "success")
        self.assertEqual(entry.page.keyboard.presses, ["Enter"])
        self.assertNotIn("steps_used", result.data)


class WebExtractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.connector, self.browser = _make_connector()
        self.registry = _registry(self.connector)
        _run(
            self.registry.invoke(
                "web.navigate", {"url": f"{ALLOWED_ORIGIN}/status"}, IDENTITY
            )
        )
        self.page = self.connector.pool.get("dev.operator").page

    def test_extract_list_items(self) -> None:
        self.page.add_element(tag="LI", text="Alert 1")
        self.page.add_element(tag="LI", text="Alert 2")
        result = _run(
            self.registry.invoke(
                "web.extract", {"selector": "li"}, IDENTITY
            )
        )
        self.assertEqual(result.status, "success")
        self.assertEqual(result.data["count"], 2)
        self.assertIn("Alert 1", result.data["items"])

    def test_extract_empty_result(self) -> None:
        result = _run(
            self.registry.invoke(
                "web.extract", {"selector": ".nonexistent"}, IDENTITY
            )
        )
        self.assertEqual(result.status, "success")
        self.assertEqual(result.data["items"], [])
        self.assertEqual(result.data["count"], 0)


class WebWaitForTests(unittest.TestCase):
    def setUp(self) -> None:
        self.connector, self.browser = _make_connector()
        self.registry = _registry(self.connector)
        _run(
            self.registry.invoke(
                "web.navigate", {"url": f"{ALLOWED_ORIGIN}/status"}, IDENTITY
            )
        )
        self.page = self.connector.pool.get("dev.operator").page

    def test_wait_for_visible_success(self) -> None:
        self.page.add_element(tag="DIV", text="Loaded")
        result = _run(
            self.registry.invoke(
                "web.wait_for", {"selector": "div"}, IDENTITY
            )
        )
        self.assertEqual(result.status, "success")
        self.assertEqual(result.data["state"], "visible")

    def test_wait_for_timeout(self) -> None:
        self.page.wait_fail = True
        result = _run(
            self.registry.invoke(
                "web.wait_for",
                {"selector": ".loading", "timeout_ms": 1000},
                IDENTITY,
            )
        )
        self.assertEqual(result.status, "error")
        self.assertEqual(result.error["code"], "BROWSER_WAIT_TIMEOUT")

    def test_wait_for_timeout_capped(self) -> None:
        self.page.wait_fail = True
        result = _run(
            self.registry.invoke(
                "web.wait_for",
                {"selector": ".x", "timeout_ms": 99999},
                IDENTITY,
            )
        )
        # Server caps at 30000ms; the error message should reflect the cap.
        self.assertEqual(result.status, "error")
        self.assertIn("30000", result.error["message"])


class WebHoverTests(unittest.TestCase, _BoundFlowMixin):
    def setUp(self) -> None:
        self.connector, self.browser = _make_connector()
        self.registry = _registry(self.connector)

    def test_hover_success(self) -> None:
        self._bind_write_flow()
        page = self.connector.pool.get("dev.operator").page
        btn = page.add_element(tag="BUTTON", text="Menu")
        _run(self.registry.invoke("web.snapshot", {}, IDENTITY))
        # Hover is read-tier, so no write flow needed — just need a bound
        # flow for gate_capture. Use a read flow instead.
        _stub_skill(self.connector, _web_skill("read"))
        _run(
            self.registry.invoke(
                "web.navigate",
                {"url": f"{ALLOWED_ORIGIN}/login",
                 "skill_id": "team-a/web/inventoryhealth"},
                IDENTITY,
            )
        )
        _run(self.registry.invoke("web.snapshot", {}, IDENTITY))
        result = _run(
            self.registry.invoke("web.hover", {"ref": 2}, IDENTITY)
        )
        self.assertEqual(result.status, "success")
        self.assertEqual(btn.hovers, 1)


class WebEvaluateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.connector, self.browser = _make_connector()
        self.registry = _registry(self.connector)
        _run(
            self.registry.invoke(
                "web.navigate", {"url": f"{ALLOWED_ORIGIN}/status"}, IDENTITY
            )
        )
        self.page = self.connector.pool.get("dev.operator").page

    def test_evaluate_simple_expression(self) -> None:
        # The fake evaluate returns None for any JS, which serializes fine.
        result = _run(
            self.registry.invoke(
                "web.evaluate", {"expression": "document.title"}, IDENTITY
            )
        )
        self.assertEqual(result.status, "success")
        # Write tier (issues #2/#3): the evidence reflects the HITL-gated
        # classification, not the old read tier.
        self.assertEqual(result.evidence["risk_level"], "write")

    def test_evaluate_empty_expression_errors(self) -> None:
        result = _run(
            self.registry.invoke(
                "web.evaluate", {"expression": ""}, IDENTITY
            )
        )
        self.assertEqual(result.status, "error")
        self.assertEqual(result.error["code"], "INVALID_PARAMETERS")

    def test_evaluate_blocks_click_mutation(self) -> None:
        result = _run(
            self.registry.invoke(
                "web.evaluate",
                {"expression": "document.querySelector('button').click()"},
                IDENTITY,
            )
        )
        self.assertEqual(result.status, "error")
        self.assertEqual(result.error["code"], "BROWSER_EVAL_MUTATION_BLOCKED")

    def test_evaluate_blocks_submit_mutation(self) -> None:
        result = _run(
            self.registry.invoke(
                "web.evaluate",
                {"expression": "document.forms[0].submit()"},
                IDENTITY,
            )
        )
        self.assertEqual(result.status, "error")
        self.assertEqual(result.error["code"], "BROWSER_EVAL_MUTATION_BLOCKED")

    def test_evaluate_blocks_fetch(self) -> None:
        result = _run(
            self.registry.invoke(
                "web.evaluate",
                {"expression": "fetch('/api/delete', {method:'DELETE'})"},
                IDENTITY,
            )
        )
        self.assertEqual(result.status, "error")
        self.assertEqual(result.error["code"], "BROWSER_EVAL_MUTATION_BLOCKED")

    def test_evaluate_blocks_innerHTML_assignment(self) -> None:
        result = _run(
            self.registry.invoke(
                "web.evaluate",
                {"expression": "document.body.innerHTML = '<p>pwned</p>'"},
                IDENTITY,
            )
        )
        self.assertEqual(result.status, "error")
        self.assertEqual(result.error["code"], "BROWSER_EVAL_MUTATION_BLOCKED")

    def test_evaluate_blocks_navigation(self) -> None:
        result = _run(
            self.registry.invoke(
                "web.evaluate",
                {"expression": "window.location = 'http://evil.com'"},
                IDENTITY,
            )
        )
        self.assertEqual(result.status, "error")
        self.assertEqual(result.error["code"], "BROWSER_EVAL_MUTATION_BLOCKED")

    def test_evaluate_allows_read_only_expressions(self) -> None:
        # These should pass the guard (no mutation patterns).
        for expr in (
            "document.title",
            "document.querySelectorAll('a').length",
            "JSON.stringify(window.performance.timing)",
            "document.cookie",
            "navigator.userAgent",
            "window.innerWidth",
            # Equality comparisons must NOT be blocked (issue #7)
            "document.querySelector('#user').value === 'alice'",
            "el.textContent === 'Deployed'",
            "document.querySelectorAll('td')[0].innerText == 'OK'",
            "cb.checked === true",
            "btn.disabled == false",
            # String.prototype.replace is a read-only transform
            "[...tds].map(td => td.innerText.replace(/\\s+/g,' '))",
            # classList.contains is a read
            "document.querySelector('.row').classList.contains('active')",
            # Reading style properties is legitimate
            "el.style.zIndex",
            "getComputedStyle(el).display",
        ):
            result = _run(
                self.registry.invoke(
                    "web.evaluate", {"expression": expr}, IDENTITY
                )
            )
            self.assertNotEqual(
                result.error.get("code") if result.error else None,
                "BROWSER_EVAL_MUTATION_BLOCKED",
                f"Expression wrongly blocked: {expr}",
            )


class WebScrollTests(unittest.TestCase):
    def setUp(self) -> None:
        self.connector, self.browser = _make_connector()
        self.registry = _registry(self.connector)
        _run(
            self.registry.invoke(
                "web.navigate", {"url": f"{ALLOWED_ORIGIN}/status"}, IDENTITY
            )
        )
        self.page = self.connector.pool.get("dev.operator").page

    def test_scroll_success(self) -> None:
        result = _run(
            self.registry.invoke(
                "web.scroll", {"delta_x": 0, "delta_y": 500}, IDENTITY
            )
        )
        self.assertEqual(result.status, "success")
        self.assertEqual(self.page.mouse.wheels, [(0, 500)])
        # No frame is active, so the cursor is never repositioned.
        self.assertEqual(self.page.mouse.moves, [])

    def test_scroll_defaults(self) -> None:
        result = _run(self.registry.invoke("web.scroll", {}, IDENTITY))
        self.assertEqual(result.status, "success")
        # Default: delta_x=0, delta_y=300.
        self.assertEqual(self.page.mouse.wheels, [(0, 300)])

    def test_scroll_centers_cursor_over_active_frame(self) -> None:
        # A Page-level wheel scrolls whatever is under the cursor, so when
        # an iframe is active web.scroll must first move the cursor to the
        # frame's center (issue #5).
        frame = FakeFrame(
            url=f"{ALLOWED_ORIGIN}/dashboard/chart",
            box={"x": 200.0, "y": 100.0, "width": 300.0, "height": 150.0},
        )
        iframe_el = self.page.add_element(tag="IFRAME", name="chart")
        iframe_el._frame = frame
        _run(self.registry.invoke("web.snapshot", {}, IDENTITY))
        switch = _run(
            self.registry.invoke(
                "web.switch_frame", {"selector": "iframe"}, IDENTITY
            )
        )
        self.assertEqual(switch.status, "success")
        result = _run(
            self.registry.invoke(
                "web.scroll", {"delta_x": 0, "delta_y": 250}, IDENTITY
            )
        )
        self.assertEqual(result.status, "success")
        # Cursor moved to the frame center (200+300/2, 100+150/2) first.
        self.assertEqual(self.page.mouse.moves, [(350.0, 175.0)])
        self.assertEqual(self.page.mouse.wheels, [(0, 250)])


class WebSwitchFrameTests(unittest.TestCase):
    def setUp(self) -> None:
        self.connector, self.browser = _make_connector()
        self.registry = _registry(self.connector)
        _run(
            self.registry.invoke(
                "web.navigate", {"url": f"{ALLOWED_ORIGIN}/dashboard"}, IDENTITY
            )
        )
        self.page = self.connector.pool.get("dev.operator").page

    def test_switch_frame_success(self) -> None:
        frame = FakeFrame(url=f"{ALLOWED_ORIGIN}/dashboard/chart")
        frame.add_element = lambda **kw: (
            el := FakeElementHandle(kw, self.page),
            frame.elements.append(el),
            el
        )[-1]
        iframe_el = self.page.add_element(tag="IFRAME", name="chart")
        iframe_el._frame = frame
        _run(self.registry.invoke("web.snapshot", {}, IDENTITY))
        result = _run(
            self.registry.invoke(
                "web.switch_frame", {"selector": "iframe"}, IDENTITY
            )
        )
        self.assertEqual(result.status, "success")
        self.assertEqual(result.data["frame_depth"], 1)
        entry = self.connector.pool.get("dev.operator")
        self.assertEqual(len(entry.frame_stack), 1)

    def test_switch_frame_not_found(self) -> None:
        result = _run(
            self.registry.invoke(
                "web.switch_frame", {"selector": "iframe"}, IDENTITY
            )
        )
        self.assertEqual(result.status, "error")
        self.assertEqual(result.error["code"], "BROWSER_FRAME_NOT_FOUND")

    def test_switch_frame_cross_origin_denied(self) -> None:
        frame = FakeFrame(url="https://evil.example/embed")
        iframe_el = self.page.add_element(tag="IFRAME", name="ad")
        iframe_el._frame = frame
        # Bind a write flow first so the origin check fires.
        _stub_skill(self.connector, _web_skill("write"))
        _run(
            self.registry.invoke(
                "web.navigate",
                {"url": f"{ALLOWED_ORIGIN}/login",
                 "skill_id": "team-a/web/inventoryhealth"},
                IDENTITY,
            )
        )
        _run(self.registry.invoke("web.snapshot", {}, IDENTITY))
        result = _run(
            self.registry.invoke(
                "web.switch_frame", {"selector": "iframe"}, IDENTITY
            )
        )
        self.assertEqual(result.status, "denied")
        self.assertEqual(result.error["code"], "BROWSER_FRAME_ORIGIN_MISMATCH")

    def test_navigate_resets_frame_stack(self) -> None:
        frame = FakeFrame(url=f"{ALLOWED_ORIGIN}/inner")
        iframe_el = self.page.add_element(tag="IFRAME", name="inner")
        iframe_el._frame = frame
        _run(self.registry.invoke("web.snapshot", {}, IDENTITY))
        _run(
            self.registry.invoke(
                "web.switch_frame", {"selector": "iframe"}, IDENTITY
            )
        )
        entry = self.connector.pool.get("dev.operator")
        self.assertEqual(len(entry.frame_stack), 1)
        # Navigate resets the frame stack.
        _run(
            self.registry.invoke(
                "web.navigate", {"url": f"{ALLOWED_ORIGIN}/other"}, IDENTITY
            )
        )
        self.assertEqual(len(entry.frame_stack), 0)


class WebUploadFileTests(unittest.TestCase, _BoundFlowMixin):
    def setUp(self) -> None:
        import tempfile
        self._tmpdir = tempfile.mkdtemp()
        # Create a test file.
        self._test_file = os.path.join(self._tmpdir, "config.yaml")
        with open(self._test_file, "w") as f:
            f.write("test: true")
        self.connector, self.browser = _make_connector()
        self.connector._upload_dir = self._tmpdir
        self.registry = _registry(self.connector)

    def tearDown(self) -> None:
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_upload_success(self) -> None:
        self._bind_write_flow()
        page = self.connector.pool.get("dev.operator").page
        file_input = page.add_element(tag="INPUT", type="file", name="upload")
        _run(self.registry.invoke("web.snapshot", {}, IDENTITY))
        result = _run(
            self.registry.invoke(
                "web.upload_file",
                {"ref": 2, "filename": "config.yaml"},
                IDENTITY,
            )
        )
        self.assertEqual(result.status, "success")
        self.assertEqual(result.data["uploaded"], "config.yaml")
        self.assertEqual(len(file_input.uploaded_files), 1)

    def test_upload_path_traversal_denied(self) -> None:
        self._bind_write_flow()
        result = _run(
            self.registry.invoke(
                "web.upload_file",
                {"ref": 1, "filename": "../etc/passwd"},
                IDENTITY,
            )
        )
        self.assertEqual(result.status, "error")
        self.assertEqual(result.error["code"], "BROWSER_UPLOAD_PATH_NOT_ALLOWED")

    def test_upload_not_a_file_input(self) -> None:
        self._bind_write_flow()
        # ref 1 is the BUTTON from _bind_write_flow
        result = _run(
            self.registry.invoke(
                "web.upload_file",
                {"ref": 1, "filename": "config.yaml"},
                IDENTITY,
            )
        )
        self.assertEqual(result.status, "error")
        self.assertEqual(result.error["code"], "BROWSER_UPLOAD_NOT_A_FILE_INPUT")

    def test_upload_file_not_found(self) -> None:
        self._bind_write_flow()
        page = self.connector.pool.get("dev.operator").page
        page.add_element(tag="INPUT", type="file", name="upload")
        _run(self.registry.invoke("web.snapshot", {}, IDENTITY))
        result = _run(
            self.registry.invoke(
                "web.upload_file",
                {"ref": 2, "filename": "nonexistent.txt"},
                IDENTITY,
            )
        )
        self.assertEqual(result.status, "error")
        self.assertEqual(result.error["code"], "BROWSER_UPLOAD_FILE_NOT_FOUND")


# --- SPEC-055 R-5: replaying a graduated executable flow --------------------

# What a graduated executable flow looks like once a human merges the R-4
# draft and skills-hub ingests it: the declaration a hand-authored browser
# flow already had (``web_target`` + ``risk_class`` + frontmatter), PLUS the
# v2 ``kind`` and ``steps`` stage 5 added. The title/description are the ones
# ``build_executable_flow_draft`` derives, so this fixture is a graduated
# skill and not merely a skill with two extra keys.
GRADUATED_TITLE = "https://inventory.internal:8443 executable flow"
GRADUATED_DESCRIPTION = (
    "Replays 3 approved mutating step(s) captured from an operator session "
    "against https://inventory.internal:8443/login: web.select, web.type, "
    "web.click."
)
GRADUATED_STEPS = [
    {"tool": "web.select", "args": {"selector": "#role", "value": "admin"}},
    {"tool": "web.type", "args": {"ref": 2, "text": "maintenance window"}},
    {"tool": "web.click", "args": {"ref": 1}},
]


def _graduated_skill(steps: list[dict] | None = None) -> dict:
    """An ingested executable-flow skill record (``kind`` + ``steps``)."""
    skill = _web_skill(
        "write", title=GRADUATED_TITLE, description=GRADUATED_DESCRIPTION
    )
    skill["kind"] = "executable_flow"
    skill["steps"] = GRADUATED_STEPS if steps is None else steps
    return skill


def _declared_skill() -> dict:
    """The same declaration, hand-authored: no ``kind``, no ``steps``."""
    return _web_skill(
        "write", title=GRADUATED_TITLE, description=GRADUATED_DESCRIPTION
    )


class GraduatedFlowReplayTests(unittest.TestCase):
    """R-5: a graduated *browser* executable flow replays through the SPEC-051
    path with no new executor, and the gateway bounds it identically.

    The claim is one of *indistinguishability*. ``steps`` is the replay
    contract the **agent** follows under the single gate; nothing on the
    gateway's binding or guard path reads it, so a skill author cannot widen
    their own blast radius by writing a longer step list. Asserted as
    whole-dict equality rather than field-by-field, because a field-by-field
    comparison would pass even if the graduated binding contributed an extra
    key — and an extra key is exactly the knob that must not exist.
    """

    def _bind(self, skill: dict, *, flow_max_steps: int = 20,
              allow_origins: tuple[str, ...] = (ALLOWED_ORIGIN,),
              credential_sets_path: str = ""):
        """Bind ``skill`` in a fresh connector; return ``(connector, registry,
        navigate_result)``."""
        connector, _ = _make_connector(
            flow_max_steps=flow_max_steps,
            allow_origins=allow_origins,
            credential_sets_path=credential_sets_path,
        )
        registry = _registry(connector)
        _stub_skill(connector, skill)
        result = _run(
            registry.invoke(
                "web.navigate",
                {
                    "url": f"{ALLOWED_ORIGIN}/login",
                    "skill_id": "team-a/web/inventoryhealth",
                },
                IDENTITY,
            )
        )
        return connector, registry, result

    def test_a_graduated_flow_binds_the_same_flow_dict_as_a_declaration(self) -> None:
        _connector, _registry_a, graduated = self._bind(_graduated_skill())
        _connector, _registry_b, declared = self._bind(_declared_skill())

        self.assertEqual(graduated.status, "success")
        self.assertEqual(declared.status, "success")
        self.assertEqual(graduated.data["flow"], declared.data["flow"])

    def test_the_step_list_never_reaches_the_flow_binding(self) -> None:
        """The mechanism behind the equality above, pinned separately.

        ``FlowState`` declares no ``kind``/``steps`` field and ``to_dict()``
        emits a fixed nine-key envelope, so the replay contract cannot ride
        ``web.navigate``'s ``data["flow"]`` to the kernel either. Equality
        alone could pass by coincidence (two skills missing the same
        frontmatter); this asserts *why* it holds, and would fail on a
        ``FlowState`` that gained a ``steps`` field even if ``to_dict()``
        still omitted it.
        """
        connector, _registry, result = self._bind(_graduated_skill())

        self.assertEqual(result.status, "success")
        flow = connector.pool.get("dev.operator").flow
        self.assertNotIn("kind", flow.to_dict())
        self.assertNotIn("steps", flow.to_dict())
        self.assertFalse(hasattr(flow, "kind"))
        self.assertFalse(hasattr(flow, "steps"))

    def test_the_step_list_cannot_buy_a_larger_step_budget(self) -> None:
        """Box: a replay past step budget fails closed.

        The budget is ``GATEWAY_BROWSER_FLOW_MAX_STEPS`` (here 2), not
        ``len(steps)`` (here 5). Were it the latter, a skill author would set
        their own blast radius by writing more steps — the one knob R-5 must
        not hand them. The two writes inside the budget land; the third is
        refused rather than re-parked, so an over-long replay degrades to a
        denial and never to a silent continuation.
        """
        connector, registry, bind = self._bind(
            _graduated_skill(
                steps=GRADUATED_STEPS
                + [{"tool": "web.click", "args": {"ref": 1}}] * 2
            ),
            flow_max_steps=2,
        )

        self.assertEqual(bind.status, "success")
        self.assertEqual(bind.data["flow"]["max_steps"], 2)
        page = connector.pool.get("dev.operator").page
        page.add_element(tag="BUTTON", text="Submit")
        self.assertEqual(
            _run(registry.invoke("web.snapshot", {}, IDENTITY)).status, "success"
        )
        for expected in (1, 2):
            result = _run(registry.invoke("web.click", {"ref": 1}, IDENTITY))
            self.assertEqual(result.status, "success")
            self.assertEqual(result.data["steps_used"], expected)
        exhausted = _run(registry.invoke("web.click", {"ref": 1}, IDENTITY))
        self.assertEqual(exhausted.status, "denied")
        self.assertEqual(exhausted.error["code"], "BROWSER_FLOW_EXHAUSTED")
        self.assertEqual(page.elements[0].clicks, 2)

    def test_the_deviation_guard_bounds_both_kinds_identically(self) -> None:
        """Box: the guard bounds a replayed executable-flow write identically.

        Both bindings drift to a *second allowlisted* origin without rebinding
        and then attempt a write. Same refusal code, same zero clicks — the
        guard reads the bound origin, not the skill's provenance.
        """
        other = "https://other.internal:8443"
        for label, skill in (
            ("declared", _declared_skill()),
            ("graduated", _graduated_skill()),
        ):
            with self.subTest(binding=label):
                connector, registry, bind = self._bind(
                    skill, allow_origins=(ALLOWED_ORIGIN, other)
                )
                self.assertEqual(bind.status, "success")
                drift = _run(
                    registry.invoke(
                        "web.navigate", {"url": f"{other}/admin"}, IDENTITY
                    )
                )
                self.assertEqual(drift.status, "success")
                entry = connector.pool.get("dev.operator")
                self.assertIsNotNone(entry.flow)  # still bound to the first
                entry.page.add_element(tag="BUTTON", text="Delete")
                _run(registry.invoke("web.snapshot", {}, IDENTITY))
                result = _run(registry.invoke("web.click", {"ref": 1}, IDENTITY))
                self.assertEqual(result.status, "denied")
                self.assertEqual(
                    result.error["code"], "BROWSER_FLOW_ORIGIN_DEVIATED"
                )
                self.assertEqual(entry.page.elements[0].clicks, 0)

    def test_an_executable_flow_without_a_web_target_binds_nothing(self) -> None:
        """Box: the infra (non-browser) binding is deferred (OQ-2) — asserted.

        ``web.navigate`` is the only binding seam the platform has, and it
        requires ``web_target``. So ``kind: executable_flow`` is *not* a
        binding: an infra executable flow has no flow to bind, no authority to
        arm, and each of its steps can therefore only reach the gateway as an
        individually-approved per-action write (SPEC-054 R-2). That is the safe
        fallback R-5 claims, and this is the check that says the generalized
        binding genuinely does not exist yet rather than existing untested.
        """
        connector, _ = _make_connector()
        registry = _registry(connector)
        _stub_skill(
            connector,
            {
                "skill_id": "team-a/infra/scaleup",
                "kind": "executable_flow",
                "risk_class": "write",
                "steps": [
                    {
                        "tool": "k8s.scale_deployment",
                        "args": {"name": "api", "replicas": 3},
                    }
                ],
            },
        )

        result = _run(
            registry.invoke(
                "web.navigate",
                {
                    "url": f"{ALLOWED_ORIGIN}/login",
                    "skill_id": "team-a/infra/scaleup",
                },
                IDENTITY,
            )
        )

        self.assertEqual(result.status, "error")
        self.assertEqual(result.error["code"], "SKILL_NOT_WEB_FLOW")
        # Nothing bound: the refusal is structural, not a flow left stale.
        self.assertIsNone(connector.pool.get("dev.operator").flow)

    def test_a_credential_step_replays_by_reference_only(self) -> None:
        """Box: credentials resolve at replay from the named sets — never literals.

        ``CredentialTests`` pins the single call; this pins the *replay
        sequence*, which is the shape a graduated flow actually has. R-4 never
        emits a credential step (``web.fill_credential`` is read-tier, so a
        trace cannot hold one, and an unresolved hole refuses), so the
        reference step here stands for the one a human adds at merge time. What
        must hold is that the literal reaches the page and nothing else: not
        the fill's result, and not the flow-bound write that follows it.
        """
        import tempfile

        tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
        json.dump(
            {"inventory-app": {"username": "svc-check", "password": PASSWORD_LITERAL}},
            tmp,
        )
        tmp.close()
        self.addCleanup(os.unlink, tmp.name)

        connector, registry, bind = self._bind(
            _graduated_skill(), credential_sets_path=tmp.name
        )
        self.assertEqual(bind.status, "success")
        page = connector.pool.get("dev.operator").page
        page.add_element(tag="BUTTON", text="Submit")
        password = page.add_element(tag="INPUT", type="password", name="password")
        _run(registry.invoke("web.snapshot", {}, IDENTITY))

        filled = _run(
            registry.invoke(
                "web.fill_credential",
                {"ref": 2, "credential_set": "inventory-app", "field": "password"},
                IDENTITY,
            )
        )
        write = _run(registry.invoke("web.click", {"ref": 1}, IDENTITY))

        self.assertEqual(filled.status, "success")
        self.assertEqual(filled.data["filled"], "password")
        self.assertEqual(filled.data["credential_set"], "inventory-app")
        self.assertEqual(password.fills, [PASSWORD_LITERAL])  # reached the page
        self.assertEqual(write.status, "success")
        for result in (filled, write):
            self.assertNotIn(PASSWORD_LITERAL, json.dumps(result.to_dict()))
        # Pinned because it is a surprise, not because it is wanted: the fill
        # is read-tier for *approval* (D-3) but shares ``_WebInteractionTool``'s
        # step accounting, so it spends one of the write flow's budget — and
        # the human-added credential reference steps R-4's refusal names as the
        # remedy spend it too. The direction is conservative (fewer writes than
        # the budget advertises, never more), so it fails safe; what it costs is
        # honesty in ``steps_budget``, and a tight
        # ``GATEWAY_BROWSER_FLOW_MAX_STEPS`` can be exhausted by reference steps
        # rather than mutations. Recorded in tasks.md stage 7 rather than
        # silently absorbed (the plan.md §6 precedent).
        self.assertEqual(filled.data["steps_used"], 1)
        self.assertEqual(write.data["steps_used"], 2)


if __name__ == "__main__":
    unittest.main()

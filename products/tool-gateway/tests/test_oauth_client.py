"""OAuth2 ``client_credentials`` token client tests (SPEC-068 R-2).

Every test drives the real grant logic against an ``httpx.MockTransport`` token
endpoint, so CI makes no live external call. A fake clock makes near-expiry
refresh deterministic; hit-counting proves the cache and the single-flight lock.
"""

from __future__ import annotations

import asyncio
import base64
import unittest
from urllib.parse import parse_qsl

import httpx

from tool_gateway.tools.oauth_client import (
    CREDENTIAL_ACQUISITION_FAILED,
    OAuth2TokenClient,
)

TOKEN_URL = "https://auth.example/oauth_token.do"
CLIENT_ID = "cid"
CLIENT_SECRET = "csec-SUPERSECRET"
ACCESS_TOKEN = "atok-TOKENVALUE"
_LOG = "tool_gateway.tools.oauth_client"


def _run(coro):
    return asyncio.run(coro)


def _entry(**overrides) -> dict[str, str]:
    base = {
        "scheme": "oauth2_client_credentials",
        "token_url": TOKEN_URL,
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
    }
    base.update(overrides)
    return base


def _client(handler, **kwargs) -> OAuth2TokenClient:
    return OAuth2TokenClient(transport=httpx.MockTransport(handler), **kwargs)


def _ok(token=ACCESS_TOKEN, expires_in=3600) -> httpx.Response:
    return httpx.Response(
        200, json={"access_token": token, "token_type": "Bearer",
                   "expires_in": expires_in}
    )


class _FakeClock:
    def __init__(self, now: float = 1000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class CacheAndRefreshTests(unittest.TestCase):
    def test_cache_miss_then_hit_fetches_once(self) -> None:
        hits = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            hits["n"] += 1
            return _ok()

        client = _client(handler)

        async def scenario():
            first = await client.acquire("snow", _entry())
            second = await client.acquire("snow", _entry())
            return first, second

        (tok1, err1), (tok2, err2) = _run(scenario())
        self.assertEqual(tok1, ACCESS_TOKEN)
        self.assertEqual(tok2, ACCESS_TOKEN)
        self.assertIsNone(err1)
        self.assertIsNone(err2)
        self.assertEqual(hits["n"], 1)  # the second call was served from cache

    def test_near_expiry_refresh(self) -> None:
        hits = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            hits["n"] += 1
            return _ok(token=f"tok{hits['n']}", expires_in=100)

        clock = _FakeClock()
        client = _client(handler, clock=clock, refresh_margin_seconds=30)

        async def scenario():
            t1, _ = await client.acquire("s", _entry())  # expires_at = 1100
            clock.advance(50)  # now 1050 < 1070 -> still fresh
            t2, _ = await client.acquire("s", _entry())
            clock.advance(30)  # now 1080 >= 1070 -> within margin, refresh
            t3, _ = await client.acquire("s", _entry())
            return t1, t2, t3

        t1, t2, t3 = _run(scenario())
        self.assertEqual((t1, t2, t3), ("tok1", "tok1", "tok2"))
        self.assertEqual(hits["n"], 2)

    def test_single_flight_shares_one_fetch(self) -> None:
        hits = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            hits["n"] += 1
            return _ok()

        client = _client(handler)

        async def scenario():
            return await asyncio.gather(
                *(client.acquire("s", _entry()) for _ in range(6))
            )

        results = _run(scenario())
        self.assertTrue(all(tok == ACCESS_TOKEN for tok, _ in results))
        self.assertTrue(all(err is None for _, err in results))
        self.assertEqual(hits["n"], 1)  # no thundering herd


class ClientAuthVariantTests(unittest.TestCase):
    def _capture(self, **entry_kwargs):
        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["auth"] = request.headers.get("authorization")
            captured["body"] = dict(parse_qsl(request.content.decode()))
            return _ok()

        _run(_client(handler).acquire("s", _entry(**entry_kwargs)))
        return captured

    def test_client_secret_basic_is_the_default(self) -> None:
        captured = self._capture()
        self.assertIsNotNone(captured["auth"])
        self.assertTrue(captured["auth"].startswith("Basic "))
        decoded = base64.b64decode(captured["auth"].split(" ", 1)[1]).decode()
        self.assertEqual(decoded, f"{CLIENT_ID}:{CLIENT_SECRET}")
        self.assertEqual(captured["body"]["grant_type"], "client_credentials")
        # The secret rides the header, never the body, for this variant.
        self.assertNotIn("client_secret", captured["body"])
        self.assertNotIn("client_id", captured["body"])

    def test_client_secret_post_puts_credentials_in_the_body(self) -> None:
        captured = self._capture(client_auth="client_secret_post")
        self.assertIsNone(captured["auth"])  # no Basic header
        self.assertEqual(captured["body"]["client_id"], CLIENT_ID)
        self.assertEqual(captured["body"]["client_secret"], CLIENT_SECRET)

    def test_optional_params_forwarded_when_configured(self) -> None:
        captured = self._capture(
            scope="read", audience="urn:snow", resource="https://api/"
        )
        self.assertEqual(captured["body"]["scope"], "read")
        self.assertEqual(captured["body"]["audience"], "urn:snow")
        self.assertEqual(captured["body"]["resource"], "https://api/")

    def test_absent_optional_params_omitted(self) -> None:
        captured = self._capture()
        for key in ("scope", "audience", "resource"):
            self.assertNotIn(key, captured["body"])


class FailClosedTests(unittest.TestCase):
    def _assert_acquisition_error(self, client, entry=None) -> None:
        tok, err = _run(client.acquire("s", entry or _entry()))
        self.assertIsNone(tok)
        self.assertIsNotNone(err)
        self.assertEqual(err[0], CREDENTIAL_ACQUISITION_FAILED)
        self.assertEqual(err[2], "error")
        # The set name may surface; a secret never may.
        self.assertIn("s", err[1])
        self.assertNotIn(CLIENT_SECRET, err[1])

    def test_non_2xx_fails_closed(self) -> None:
        self._assert_acquisition_error(
            _client(lambda r: httpx.Response(401, json={"error": "invalid_client"}))
        )

    def test_missing_access_token_fails_closed(self) -> None:
        self._assert_acquisition_error(
            _client(lambda r: httpx.Response(200, json={"token_type": "Bearer"}))
        )

    def test_empty_access_token_fails_closed(self) -> None:
        self._assert_acquisition_error(
            _client(lambda r: httpx.Response(200, json={"access_token": ""}))
        )

    def test_non_json_response_fails_closed(self) -> None:
        self._assert_acquisition_error(
            _client(lambda r: httpx.Response(200, text="<html>nope</html>"))
        )

    def test_timeout_fails_closed(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectTimeout("timed out")

        self._assert_acquisition_error(_client(handler))

    def test_connect_error_fails_closed(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("refused")

        self._assert_acquisition_error(_client(handler))

    def test_incomplete_entry_fails_closed_without_a_call(self) -> None:
        hits = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            hits["n"] += 1
            return _ok()

        # No client_secret -> rejected before any request is made.
        self._assert_acquisition_error(
            _client(handler),
            entry={
                "scheme": "oauth2_client_credentials",
                "token_url": TOKEN_URL,
                "client_id": CLIENT_ID,
            },
        )
        self.assertEqual(hits["n"], 0)

    def test_unknown_client_auth_variant_fails_closed(self) -> None:
        self._assert_acquisition_error(
            _client(lambda r: _ok()), entry=_entry(client_auth="mtls")
        )


class SecretHandlingTests(unittest.TestCase):
    def test_secret_and_token_never_logged_on_the_failure_path(self) -> None:
        state = {"fail": False}

        def handler(request: httpx.Request) -> httpx.Response:
            if state["fail"]:
                return httpx.Response(500, json={"error": "boom"})
            return _ok(expires_in=100)

        clock = _FakeClock()
        client = _client(handler, clock=clock, refresh_margin_seconds=30)

        async def scenario():
            await client.acquire("s", _entry())  # caches ACCESS_TOKEN
            state["fail"] = True
            clock.advance(200)  # force a refresh that now fails
            return await client.acquire("s", _entry())

        with self.assertLogs(_LOG, level="WARNING") as cap:
            tok, err = _run(scenario())
        self.assertIsNone(tok)
        self.assertEqual(err[0], CREDENTIAL_ACQUISITION_FAILED)
        joined = "\n".join(cap.output)
        self.assertNotIn(CLIENT_SECRET, joined)
        self.assertNotIn(ACCESS_TOKEN, joined)
        self.assertNotIn(CLIENT_SECRET, err[1])
        self.assertNotIn(ACCESS_TOKEN, err[1])


if __name__ == "__main__":
    unittest.main()

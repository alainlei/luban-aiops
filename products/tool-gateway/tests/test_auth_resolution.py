"""Reusable outbound auth-resolution seam tests (SPEC-068 R-3).

These are pure unit tests on the resolver itself: given a credential entry and
its scheme, it returns the right ``httpx.Auth`` (plus the raw bearer token for a
non-httpx transport) or a structured **gateway** error. The OAuth2 grant it
delegates to is exercised in ``test_oauth_client.py``; here a stub token client
stands in so each case isolates the resolver's dispatch and its fail-closed
contract. The end-to-end wiring through ``HttpConnector`` lives in
``test_http_connector.py``.
"""

from __future__ import annotations

import asyncio
import base64
import unittest
from dataclasses import FrozenInstanceError

import httpx

from tool_gateway.tools.auth_resolution import (
    BearerAuth,
    ResolvedAuth,
    resolve_outbound_auth,
)
from tool_gateway.tools.oauth_client import CREDENTIAL_ACQUISITION_FAILED

PASSWORD = "s3cret-SUPERSECRET"
CLIENT_SECRET = "csec-SUPERSECRET"


def _run(coro):
    return asyncio.run(coro)


class _StubTokenClient:
    """Stands in for :class:`OAuth2TokenClient`.

    Returns a canned ``(token, err)`` and records each ``acquire`` call so a test
    can assert a non-oauth2 scheme never triggers a token fetch, and that oauth2
    drives exactly one.
    """

    def __init__(self, token=None, err=None) -> None:
        self._result = (token, err)
        self.calls: list[tuple[str, dict[str, str]]] = []

    async def acquire(self, name, entry):
        self.calls.append((name, entry))
        return self._result


def _resolve(set_name: str, entry: dict, token_client=None):
    return _run(
        resolve_outbound_auth(
            set_name=set_name,
            entry=entry,
            token_client=token_client or _StubTokenClient(),
        )
    )


def _auth_header(auth: httpx.Auth) -> str:
    """Drive one ``auth_flow`` step and read the ``Authorization`` it sets."""
    request = httpx.Request("GET", "https://target/x")
    sent = next(auth.auth_flow(request))
    return sent.headers["Authorization"]


class BasicSchemeTests(unittest.TestCase):
    def test_resolves_to_httpx_basic_auth_with_no_bearer_form(self) -> None:
        resolved, err = _resolve(
            "acme", {"scheme": "basic", "username": "svc", "password": PASSWORD}
        )
        self.assertIsNone(err)
        self.assertEqual(resolved.scheme, "basic")
        self.assertIsInstance(resolved.auth, httpx.BasicAuth)
        self.assertIsNone(resolved.bearer_token)
        expected = "Basic " + base64.b64encode(
            f"svc:{PASSWORD}".encode()
        ).decode()
        self.assertEqual(_auth_header(resolved.auth), expected)

    def test_entry_without_a_scheme_key_defaults_to_basic(self) -> None:
        """The additive invariant: a pre-SPEC-068 entry still resolves."""
        resolved, err = _resolve("acme", {"username": "svc", "password": PASSWORD})
        self.assertIsNone(err)
        self.assertEqual(resolved.scheme, "basic")
        self.assertIsInstance(resolved.auth, httpx.BasicAuth)

    def test_basic_never_triggers_a_token_fetch(self) -> None:
        stub = _StubTokenClient(token="SHOULD-NOT-BE-USED")
        _resolve(
            "acme",
            {"scheme": "basic", "username": "svc", "password": PASSWORD},
            token_client=stub,
        )
        self.assertEqual(stub.calls, [])

    def test_missing_username_fails_closed_and_never_echoes_the_secret(self) -> None:
        resolved, err = _resolve(
            "acme", {"scheme": "basic", "username": "", "password": PASSWORD}
        )
        self.assertIsNone(resolved)
        self.assertEqual(err[0], CREDENTIAL_ACQUISITION_FAILED)
        self.assertEqual(err[2], "error")
        self.assertIn("acme", err[1])  # the set name is safe to surface
        self.assertNotIn(PASSWORD, err[1])
        self.assertNotIn("s3cret", err[1])

    def test_missing_password_fails_closed(self) -> None:
        resolved, err = _resolve(
            "acme", {"scheme": "basic", "username": "svc", "password": ""}
        )
        self.assertIsNone(resolved)
        self.assertEqual(err[0], CREDENTIAL_ACQUISITION_FAILED)


class BearerSchemeTests(unittest.TestCase):
    def test_resolves_to_bearer_auth_and_exposes_the_raw_token(self) -> None:
        resolved, err = _resolve("snow", {"scheme": "bearer", "token": "static-tok"})
        self.assertIsNone(err)
        self.assertEqual(resolved.scheme, "bearer")
        self.assertIsInstance(resolved.auth, BearerAuth)
        # The raw token is returned for a non-httpx transport (SPEC-067's MCP
        # client), which takes a header rather than an ``httpx.Auth``.
        self.assertEqual(resolved.bearer_token, "static-tok")
        self.assertEqual(_auth_header(resolved.auth), "Bearer static-tok")

    def test_bearer_never_triggers_a_token_fetch(self) -> None:
        stub = _StubTokenClient(token="SHOULD-NOT-BE-USED")
        _resolve("snow", {"scheme": "bearer", "token": "static-tok"}, token_client=stub)
        self.assertEqual(stub.calls, [])

    def test_missing_token_fails_closed(self) -> None:
        resolved, err = _resolve("snow", {"scheme": "bearer", "token": ""})
        self.assertIsNone(resolved)
        self.assertEqual(err[0], CREDENTIAL_ACQUISITION_FAILED)
        self.assertIn("snow", err[1])


class OAuth2SchemeTests(unittest.TestCase):
    def _entry(self) -> dict:
        return {
            "scheme": "oauth2_client_credentials",
            "token_url": "https://auth.example/oauth_token.do",
            "client_id": "cid",
            "client_secret": CLIENT_SECRET,
        }

    def test_acquires_then_resolves_to_bearer(self) -> None:
        stub = _StubTokenClient(token="TOK123")
        resolved, err = _resolve("snow", self._entry(), token_client=stub)
        self.assertIsNone(err)
        self.assertEqual(resolved.scheme, "oauth2_client_credentials")
        self.assertIsInstance(resolved.auth, BearerAuth)
        self.assertEqual(resolved.bearer_token, "TOK123")
        self.assertEqual(_auth_header(resolved.auth), "Bearer TOK123")
        # Exactly one acquisition, for this set.
        self.assertEqual([name for name, _ in stub.calls], ["snow"])

    def test_acquisition_failure_propagates_verbatim(self) -> None:
        failure = (
            CREDENTIAL_ACQUISITION_FAILED,
            "OAuth2 token acquisition failed for credential set 'snow': "
            "token endpoint returned 401.",
            "error",
        )
        stub = _StubTokenClient(err=failure)
        resolved, err = _resolve("snow", self._entry(), token_client=stub)
        self.assertIsNone(resolved)
        self.assertEqual(err, failure)

    def test_acquisition_returning_no_token_is_a_gateway_error(self) -> None:
        stub = _StubTokenClient(token=None, err=None)
        resolved, err = _resolve("snow", self._entry(), token_client=stub)
        self.assertIsNone(resolved)
        self.assertEqual(err[0], CREDENTIAL_ACQUISITION_FAILED)
        self.assertIn("no token", err[1])
        self.assertNotIn(CLIENT_SECRET, err[1])


class UnknownSchemeTests(unittest.TestCase):
    def test_unsupported_scheme_fails_closed(self) -> None:
        resolved, err = _resolve(
            "x", {"scheme": "magic-link", "token": "tok-SUPERSECRET"}
        )
        self.assertIsNone(resolved)
        self.assertEqual(err[0], CREDENTIAL_ACQUISITION_FAILED)
        self.assertIn("magic-link", err[1])
        self.assertNotIn("tok-SUPERSECRET", err[1])


class BearerAuthTests(unittest.TestCase):
    def test_auth_flow_sets_the_bearer_header(self) -> None:
        self.assertEqual(_auth_header(BearerAuth("tok-value")), "Bearer tok-value")

    def test_auth_flow_replaces_an_existing_authorization_header(self) -> None:
        """A stale header is overwritten, never appended (one value only)."""
        request = httpx.Request(
            "GET", "https://target/x", headers={"Authorization": "Bearer stale"}
        )
        sent = next(BearerAuth("good").auth_flow(request))
        self.assertEqual(sent.headers["Authorization"], "Bearer good")
        self.assertEqual(sent.headers.get_list("authorization"), ["Bearer good"])


class ResolvedAuthTests(unittest.TestCase):
    def test_is_frozen_and_defaults_bearer_token_to_none(self) -> None:
        resolved = ResolvedAuth(scheme="basic", auth=None)
        self.assertIsNone(resolved.bearer_token)
        with self.assertRaises(FrozenInstanceError):
            resolved.scheme = "bearer"  # type: ignore[misc]


if __name__ == "__main__":
    unittest.main()

"""Connector-local OAuth2 ``client_credentials`` token client (SPEC-068 R-2).

Option A of the machine-consumer credential memo §4: the tool-gateway acquires a
**target-issued** token itself, with no new signing authority and no centralized
broker. The whole grant is a single ``application/x-www-form-urlencoded`` POST
that ``httpx`` already performs, so SPEC-068 adds **no new dependency**.

The acquired token lives in memory only — never on disk, in a tool result, an
evidence field, audit, or a log line (only the failure *class* and the set
**name** are logged). It is cached per credential-set name and refreshed on
near-expiry so a call never rides a token that expires mid-flight, and
concurrent callers for one set share a single in-flight fetch (per-set lock +
double-check, so there is no thundering herd of token requests). Any failure
(unreachable, timeout, non-2xx, or a response carrying no ``access_token``)
fails closed with a structured gateway error — never an unauthenticated call and
never a fabricated token.

The ``token_url`` is operator-provisioned platform config (the file-mounted
credential secret), **not** a model-supplied URL, so it is not subject to the
``http.get``/``http.post`` origin allowlist; redirects are never followed so an
``Authorization`` header can never be replayed to another host.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import time
from dataclasses import dataclass
from typing import Callable

import httpx

LOGGER = logging.getLogger(__name__)

# Refresh this long before ``expires_in`` elapses so a call never rides a token
# that expires mid-flight.
DEFAULT_REFRESH_MARGIN_SECONDS = 30.0
# Used only when a token response omits ``expires_in``; deliberately short so an
# unknown-lifetime token is never cached long enough to go stale.
DEFAULT_TOKEN_TTL_SECONDS = 300.0
DEFAULT_TIMEOUT_SECONDS = 10.0

# The two OAuth 2.1 client-authentication variants. ``client_secret_basic`` is
# the default; the variant is explicit per set (never auto-negotiated) because
# servers differ and guessing could send a secret to the wrong place.
CLIENT_AUTH_BASIC = "client_secret_basic"
CLIENT_AUTH_POST = "client_secret_post"
_CLIENT_AUTH_VARIANTS = frozenset({CLIENT_AUTH_BASIC, CLIENT_AUTH_POST})

# Optional request parameters forwarded to the token endpoint when configured.
_OPTIONAL_PARAMS = ("scope", "audience", "resource")

# A credential/config failure maps to this structured **gateway** error code
# (SPEC-068 R-3) — the deliberate inverse of SPEC-058's "an upstream 4xx/5xx is
# a fact, not a tool error": a token we could not acquire is our failure to
# authenticate, never the target's answer.
CREDENTIAL_ACQUISITION_FAILED = "CREDENTIAL_ACQUISITION_FAILED"


@dataclass(frozen=True)
class _CachedToken:
    """An in-memory-only cached access token and its monotonic expiry."""

    access_token: str
    expires_at: float


def _coerce_expires_in(value: object) -> float:
    """A positive TTL in seconds, or the short default when absent/invalid."""
    try:
        seconds = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return DEFAULT_TOKEN_TTL_SECONDS
    if not seconds > 0:
        return DEFAULT_TOKEN_TTL_SECONDS
    return seconds


class OAuth2TokenClient:
    """Acquires and caches ``client_credentials`` tokens, keyed by set name.

    One instance is owned by a connector so the cache persists across calls. An
    injected ``transport`` (``httpx.MockTransport``) replaces the real socket at
    the single fetch site, so tests drive the whole grant against a mock token
    endpoint with no live external call. An injected ``clock`` makes near-expiry
    deterministic.
    """

    def __init__(
        self,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        refresh_margin_seconds: float = DEFAULT_REFRESH_MARGIN_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._transport = transport
        self._timeout = timeout_seconds
        self._margin = refresh_margin_seconds
        self._clock = clock
        self._cache: dict[str, _CachedToken] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    def _lock_for(self, name: str) -> asyncio.Lock:
        # asyncio is single-threaded, so get-or-create needs no await between
        # the read and the write and cannot race.
        lock = self._locks.get(name)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[name] = lock
        return lock

    def _fresh_token(self, name: str) -> str | None:
        cached = self._cache.get(name)
        if cached is None:
            return None
        if self._clock() >= cached.expires_at - self._margin:
            return None  # expired or within the refresh margin -> re-fetch
        return cached.access_token

    async def acquire(
        self, name: str, entry: dict[str, str]
    ) -> tuple[str | None, tuple[str, str, str] | None]:
        """Return ``(access_token, None)`` or ``(None, (code, message, status))``.

        Serves a still-valid cached token when one exists; otherwise fetches
        under a per-set lock so concurrent callers share one in-flight request.
        """
        cached = self._fresh_token(name)
        if cached is not None:
            return cached, None
        async with self._lock_for(name):
            # Double-check: a caller that held the lock may have just fetched.
            cached = self._fresh_token(name)
            if cached is not None:
                return cached, None
            return await self._fetch_and_cache(name, entry)

    async def _fetch_and_cache(
        self, name: str, entry: dict[str, str]
    ) -> tuple[str | None, tuple[str, str, str] | None]:
        token_url = entry.get("token_url")
        client_id = entry.get("client_id")
        client_secret = entry.get("client_secret")
        if not token_url or not client_id or not client_secret:
            # The store validates these; guard anyway so a hand-built entry can
            # never produce an unauthenticated or half-formed token request.
            LOGGER.warning("oauth2 credential set %r is incomplete", name)
            return None, self._error(name, "incomplete oauth2 credential set")
        client_auth = entry.get("client_auth") or CLIENT_AUTH_BASIC
        if client_auth not in _CLIENT_AUTH_VARIANTS:
            LOGGER.warning(
                "oauth2 credential set %r has an unknown client_auth variant", name
            )
            return None, self._error(name, "unknown client_auth variant")

        data: dict[str, str] = {"grant_type": "client_credentials"}
        for key in _OPTIONAL_PARAMS:
            if entry.get(key):
                data[key] = entry[key]
        headers = {"Accept": "application/json"}
        if client_auth == CLIENT_AUTH_POST:
            data["client_id"] = client_id
            data["client_secret"] = client_secret
        else:  # client_secret_basic
            raw = f"{client_id}:{client_secret}".encode("utf-8")
            headers["Authorization"] = (
                "Basic " + base64.b64encode(raw).decode("ascii")
            )

        client_kwargs: dict = {
            "timeout": self._timeout,
            "follow_redirects": False,
        }
        if self._transport is not None:
            client_kwargs["transport"] = self._transport
        try:
            async with httpx.AsyncClient(**client_kwargs) as client:
                response = await client.post(token_url, data=data, headers=headers)
        except httpx.TimeoutException:
            LOGGER.warning("oauth2 token endpoint timed out for set %r", name)
            return None, self._error(name, "token endpoint timed out")
        except httpx.HTTPError as exc:
            # Log the failure class only — never the URL, secret, or token.
            LOGGER.warning(
                "oauth2 token fetch failed for set %r: %s", name, exc.__class__.__name__
            )
            return None, self._error(name, "token endpoint unreachable")

        if response.status_code != 200:
            LOGGER.warning(
                "oauth2 token endpoint returned %d for set %r",
                response.status_code, name,
            )
            return None, self._error(
                name, f"token endpoint returned {response.status_code}"
            )
        try:
            payload = response.json()
        except ValueError:
            LOGGER.warning("oauth2 token response was not JSON for set %r", name)
            return None, self._error(name, "token response was not valid JSON")
        access_token = (
            payload.get("access_token") if isinstance(payload, dict) else None
        )
        if not isinstance(access_token, str) or not access_token:
            LOGGER.warning(
                "oauth2 token response carried no access_token for set %r", name
            )
            return None, self._error(name, "token response carried no access_token")

        expires_in = _coerce_expires_in(
            payload.get("expires_in") if isinstance(payload, dict) else None
        )
        self._cache[name] = _CachedToken(
            access_token=access_token,
            expires_at=self._clock() + expires_in,
        )
        return access_token, None

    @staticmethod
    def _error(name: str, detail: str) -> tuple[str, str, str]:
        """A structured gateway error naming only the set (never a secret)."""
        return (
            CREDENTIAL_ACQUISITION_FAILED,
            f"OAuth2 token acquisition failed for credential set '{name}': "
            f"{detail}.",
            "error",
        )

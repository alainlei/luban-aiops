"""Reusable outbound auth-resolution seam (SPEC-068 R-3).

One acquisition path every connector reuses: resolve a named credential set's
scheme into the correct outbound auth. SPEC-058's ``http_connector`` is the
first consumer; SPEC-067's ServiceNow/MCP adapter is the second, reusing this
resolver and the same :class:`OAuth2TokenClient` with no re-implementation.

The resolver returns both an ``httpx.Auth`` (for httpx-based connectors) and the
resolved bearer token (for a non-httpx transport such as the MCP SDK's
streamable-HTTP client, which takes a header or client factory), so a single
acquisition serves either.

A credential/config failure is a structured **gateway** error — the deliberate
inverse of SPEC-058's "an upstream 4xx/5xx is a fact, not a tool error": a
missing credential is our failure to authenticate, never the target's answer, so
it is never projected as a successful result and never falls back to an
unauthenticated call. Only the set **name** ever surfaces; a credential value or
an acquired token never does.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from tool_gateway.tools.credential_sets import scheme_of
from tool_gateway.tools.oauth_client import (
    CREDENTIAL_ACQUISITION_FAILED,
    OAuth2TokenClient,
)


class BearerAuth(httpx.Auth):
    """Attaches ``Authorization: Bearer <token>`` to an outbound request."""

    def __init__(self, token: str) -> None:
        self._token = token

    def auth_flow(self, request: httpx.Request):
        request.headers["Authorization"] = f"Bearer {self._token}"
        yield request


@dataclass(frozen=True)
class ResolvedAuth:
    """The resolved outbound credential for one call.

    ``auth`` is what an httpx connector attaches; ``bearer_token`` is the raw
    token for a non-httpx transport (``None`` for ``basic``, which has no bearer
    form). ``scheme`` is recorded so a consumer can branch without re-deriving it
    from the entry.
    """

    scheme: str
    auth: httpx.Auth | None
    bearer_token: str | None = None


def _error(set_name: str, detail: str) -> tuple[str, str, str]:
    """A structured gateway error naming only the set (never a secret)."""
    return (
        CREDENTIAL_ACQUISITION_FAILED,
        f"Credential set '{set_name}': {detail}.",
        "error",
    )


async def resolve_outbound_auth(
    *,
    set_name: str,
    entry: dict[str, str],
    token_client: OAuth2TokenClient,
) -> tuple[ResolvedAuth | None, tuple[str, str, str] | None]:
    """Resolve one credential entry into outbound auth for its scheme.

    Returns ``(ResolvedAuth, None)`` on success or
    ``(None, (code, message, status))`` on a credential/config failure. Fails
    closed on every scheme: a missing field or a failed token acquisition is a
    gateway error, never an unauthenticated fallback.
    """
    scheme = scheme_of(entry)
    if scheme == "basic":
        username = entry.get("username")
        password = entry.get("password")
        if not username or not password:
            return None, _error(set_name, "a basic set needs username and password")
        return (
            ResolvedAuth(scheme="basic", auth=httpx.BasicAuth(username, password)),
            None,
        )
    if scheme == "bearer":
        token = entry.get("token")
        if not token:
            return None, _error(set_name, "a bearer set needs a token")
        return (
            ResolvedAuth(scheme="bearer", auth=BearerAuth(token), bearer_token=token),
            None,
        )
    if scheme == "oauth2_client_credentials":
        token, err = await token_client.acquire(set_name, entry)
        if err is not None:
            return None, err
        if not token:
            return None, _error(set_name, "OAuth2 token acquisition returned no token")
        return (
            ResolvedAuth(scheme=scheme, auth=BearerAuth(token), bearer_token=token),
            None,
        )
    # ``CredentialSetStore`` already rejects unknown schemes at parse time; this
    # is the belt-and-braces fail-closed for a hand-built entry.
    return None, _error(set_name, f"unsupported scheme '{scheme}'")

"""Named credential sets for outbound execution (SPEC-049 R-5, SPEC-068).

Credentials are platform configuration, never skill content: the connector
resolves a named set from a secret-mounted JSON file at call time. The
knob accepts a file path only (no inline values), unknown set names are a
structured error rather than a crash, and set values are never logged or
serialized into tool results — a ``basic`` set flows into a Playwright
``fill`` call or ``httpx.BasicAuth``; a bearer/OAuth2 token flows into an
outbound ``Authorization`` header. The file reloads on mtime change so
secret rotation needs no gateway restart.

Each set carries an optional ``scheme`` (default ``basic``, byte-for-byte
the pre-SPEC-068 shape). ``bearer`` needs ``token``;
``oauth2_client_credentials`` needs ``token_url``/``client_id``/
``client_secret`` and may carry ``scope``/``audience``/``resource``/
``client_auth``. An unknown scheme or a missing required field is ignored
with a warning (fail-closed), never admitted half-formed.

Expected file shape::

    {
      "inventory-app": {"username": "svc-check", "password": "..."},
      "legacy-crm": {"username": "checker", "password": "..."},
      "snow-read": {"scheme": "oauth2_client_credentials",
                    "token_url": "https://.../oauth_token.do",
                    "client_id": "...", "client_secret": "..."}
    }
"""

from __future__ import annotations

import json
import logging
import os

LOGGER = logging.getLogger(__name__)

# The scheme vocabulary (SPEC-068 R-1). Each scheme names the fields it
# requires; a set is admitted only when every one is a non-empty string.
_SCHEME_REQUIRED_FIELDS: dict[str, tuple[str, ...]] = {
    "basic": ("username", "password"),
    "bearer": ("token",),
    "oauth2_client_credentials": ("token_url", "client_id", "client_secret"),
}
DEFAULT_SCHEME = "basic"
# Retained when present on an ``oauth2_client_credentials`` set (SPEC-068 R-2).
_OPTIONAL_FIELDS = ("scope", "audience", "resource", "client_auth")
# Back-compat alias: ``basic`` was the only scheme before SPEC-068.
REQUIRED_FIELDS = _SCHEME_REQUIRED_FIELDS[DEFAULT_SCHEME]


def scheme_of(entry: dict[str, str]) -> str:
    """A set's scheme, defaulting to ``basic`` when the key is absent."""
    return entry.get("scheme", DEFAULT_SCHEME)


def _parse_set(name: object, value: object) -> dict[str, str] | None:
    """Validate one credential set; ``None`` (with a warning) when unusable.

    Retains the declared scheme's required fields plus any optional OAuth
    keys, so a non-``basic`` set survives reload intact instead of being
    projected down to ``username``/``password``. Fails closed: an unknown
    scheme, or a missing/empty required field, is ignored rather than
    admitted half-formed. A ``basic`` set with no ``scheme`` key yields the
    exact pre-SPEC-068 dict.
    """
    if not isinstance(value, dict):
        LOGGER.warning("credential set %r ignored: not a JSON object", name)
        return None
    scheme = value.get("scheme", DEFAULT_SCHEME)
    if not isinstance(scheme, str) or scheme not in _SCHEME_REQUIRED_FIELDS:
        LOGGER.warning(
            "credential set %r ignored: unknown scheme %r (expected one of: %s)",
            name, scheme, ", ".join(sorted(_SCHEME_REQUIRED_FIELDS)),
        )
        return None
    required = _SCHEME_REQUIRED_FIELDS[scheme]
    if any(
        not isinstance(value.get(field), str) or not value.get(field)
        for field in required
    ):
        LOGGER.warning(
            "credential set %r ignored: scheme %r needs non-empty %s",
            name, scheme, " and ".join(required),
        )
        return None
    entry: dict[str, str] = {field: value[field] for field in required}
    for field in _OPTIONAL_FIELDS:
        optional = value.get(field)
        if isinstance(optional, str) and optional:
            entry[field] = optional
    if isinstance(value.get("scheme"), str):
        entry["scheme"] = scheme
    return entry


class CredentialSetStore:
    """Lazy, mtime-refreshed view of the credential-set secret file."""

    def __init__(self, path: str) -> None:
        self._path = path
        self._mtime: float | None = None
        self._sets: dict[str, dict[str, str]] = {}

    @property
    def configured(self) -> bool:
        return bool(self._path)

    def names(self) -> list[str]:
        """Set names are safe to surface (names are not secrets)."""
        self._maybe_reload()
        return sorted(self._sets)

    def get(self, name: str) -> dict[str, str] | None:
        """Resolve one named set; None when unconfigured or unknown."""
        self._maybe_reload()
        return self._sets.get(name)

    def _maybe_reload(self) -> None:
        if not self._path:
            return
        try:
            mtime = os.stat(self._path).st_mtime
        except OSError:
            if self._sets:
                LOGGER.warning(
                    "credential sets file disappeared; keeping last good load"
                )
            return
        if mtime == self._mtime:
            return
        self._reload(mtime)

    def _reload(self, mtime: float) -> None:
        try:
            with open(self._path, encoding="utf-8") as handle:
                raw = json.load(handle)
        except (OSError, ValueError) as exc:
            # Log the failure class only — never the file contents.
            LOGGER.warning(
                "credential sets file unreadable (%s); keeping last good "
                "load",
                exc.__class__.__name__,
            )
            return
        if not isinstance(raw, dict):
            LOGGER.warning("credential sets file must be a JSON object")
            return
        parsed: dict[str, dict[str, str]] = {}
        for name, value in raw.items():
            entry = _parse_set(name, value)
            if entry is not None:
                parsed[str(name)] = entry
        self._sets = parsed
        self._mtime = mtime
        LOGGER.info("credential sets loaded: %d set(s)", len(parsed))

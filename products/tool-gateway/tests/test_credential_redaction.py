"""Secret-handling invariants for the SPEC-068 credential schemes (R-4).

SPEC-068 introduces three secret-bearing names — an OAuth ``client_secret``, an
acquired ``access_token``, and a static bearer ``token``. This module proves the
platform's **existing** redaction already covers every one of them across the
surfaces R-4 names (a URL projection, a tool result, an evidence field), so no
new redaction vocabulary was needed and ``make validate-secret-vocabulary`` is
untouched.

Two layers do the work, and the tests pin both:

* the URL secret-query vocabulary (``url_redaction``) matches by **substring**,
  so ``client_secret`` and ``access_token`` are caught without being listed
  verbatim;
* the tool-output redactor (``redaction``) catches a secret by exact **key**
  name (``client_secret``/``token``/``authorization``/``secret`` are in
  ``_SENSITIVE_KEYS``) *or* by value **shape** (a ``Bearer <value>`` or JWT is
  masked whatever key it rides under).

Each fixture carries the real secret value and the assertion is on its *absence*
from the output, so a coverage regression fails loudly rather than passing
vacuously. The structural half of the invariant — an acquired token is never
serialized into a result at all — is proven end-to-end in ``test_http_connector``
(``test_oauth2_set_acquires_token_then_sends_bearer``).
"""

from __future__ import annotations

import json
import unittest

from tool_gateway.tools.base import ToolResult, build_evidence
from tool_gateway.tools.redaction import (
    REDACTION_MARKER,
    _SENSITIVE_KEYS,
    redact_result,
)
from tool_gateway.tools.url_redaction import is_secret_param, redact_secret_query

CLIENT_SECRET = "csec-SUPERSECRET"
ACCESS_TOKEN = "atok-TOKENVALUE"
STATIC_TOKEN = "static-tok-SECRETVALUE"
_JWT = (
    "eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiJzZXJ2aWNlLWFjY291bnQifQ.sig-value-12345678"
)


def _result(data=None, evidence=None) -> ToolResult:
    return ToolResult(
        tool_name="http.get",
        status="success",
        data=data,
        evidence=evidence if evidence is not None else build_evidence("read", "http", 1),
    )


class UrlProjectionCoverageTests(unittest.TestCase):
    """A secret riding a URL query is masked for the new scheme names."""

    def test_new_scheme_secret_names_match_by_substring(self) -> None:
        for name in ("client_secret", "access_token", "token", "refresh_token"):
            self.assertTrue(is_secret_param(name), name)

    def test_non_secret_oauth_params_are_not_over_masked(self) -> None:
        # The vocabulary is deliberately substring-based but bounded: an
        # identifier or a grant parameter is not a secret and must survive.
        for name in ("client_id", "grant_type", "scope", "audience", "resource"):
            self.assertFalse(is_secret_param(name), name)

    def test_oauth_token_url_secrets_are_masked_in_projection(self) -> None:
        url = (
            "https://auth.example/oauth_token.do?grant_type=client_credentials"
            f"&client_secret={CLIENT_SECRET}&access_token={ACCESS_TOKEN}"
        )
        redacted = redact_secret_query(url)
        self.assertIn("grant_type=client_credentials", redacted)
        self.assertIn("client_secret=***", redacted)
        self.assertIn("access_token=***", redacted)
        self.assertNotIn(CLIENT_SECRET, redacted)
        self.assertNotIn(ACCESS_TOKEN, redacted)


class ResultKeyCoverageTests(unittest.TestCase):
    """A secret under a listed key is masked, key visible, value gone."""

    def test_sensitive_key_list_covers_the_spec068_names(self) -> None:
        self.assertTrue(
            {"client_secret", "authorization", "token", "secret",
             "access_key", "private_key"} <= _SENSITIVE_KEYS
        )

    def test_credential_envelope_values_are_masked_key_visible(self) -> None:
        redacted, stats = redact_result(_result(data={
            "client_secret": CLIENT_SECRET,
            "token": STATIC_TOKEN,
            "authorization": f"Bearer {ACCESS_TOKEN}",
        }))
        self.assertEqual(redacted.data["client_secret"], REDACTION_MARKER)
        self.assertEqual(redacted.data["token"], REDACTION_MARKER)
        self.assertEqual(redacted.data["authorization"], REDACTION_MARKER)
        self.assertEqual(stats.spans, 3)
        blob = json.dumps(redacted.to_dict())
        for secret in (CLIENT_SECRET, STATIC_TOKEN, ACCESS_TOKEN):
            self.assertNotIn(secret, blob)

    def test_secret_in_an_evidence_field_is_masked(self) -> None:
        redacted, _ = redact_result(_result(
            data={"ok": True},
            evidence={
                "authorization": f"Bearer {ACCESS_TOKEN}",
                "client_secret": CLIENT_SECRET,
            },
        ))
        self.assertEqual(redacted.evidence["authorization"], REDACTION_MARKER)
        self.assertEqual(redacted.evidence["client_secret"], REDACTION_MARKER)
        blob = json.dumps(redacted.to_dict())
        self.assertNotIn(ACCESS_TOKEN, blob)
        self.assertNotIn(CLIENT_SECRET, blob)


class ValueShapeCoverageTests(unittest.TestCase):
    """A token *value* is masked by shape even under an unlisted key."""

    def test_bearer_token_value_masked_regardless_of_key(self) -> None:
        redacted, stats = redact_result(_result(data={
            "echo": f"upstream saw Bearer {ACCESS_TOKEN} in the header",
        }))
        self.assertNotIn(ACCESS_TOKEN, redacted.data["echo"])
        self.assertIn(REDACTION_MARKER, redacted.data["echo"])
        self.assertEqual(stats.spans, 1)

    def test_jwt_shaped_access_token_masked_under_an_unlisted_key(self) -> None:
        # ``access_token`` is not an exact key in _SENSITIVE_KEYS, but a
        # JWT-shaped value is caught by the shape layer, so an echoed token
        # cannot survive under a novel key name.
        self.assertNotIn("access_token", _SENSITIVE_KEYS)
        redacted, stats = redact_result(_result(data={"access_token": _JWT}))
        self.assertEqual(redacted.data["access_token"], REDACTION_MARKER)
        self.assertNotIn(_JWT, json.dumps(redacted.to_dict()))
        self.assertEqual(stats.spans, 1)


if __name__ == "__main__":
    unittest.main()

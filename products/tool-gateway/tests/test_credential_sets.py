"""Credential-set store tests (SPEC-068 R-1: per-scheme parsing).

The store is the file-mounted secret every outbound connector resolves a
named set from. SPEC-068 generalized it from a fixed ``username``/``password``
projection to a per-scheme model that *retains* each scheme's fields, so these
tests pin three invariants:

* a ``basic`` set (and a set with no ``scheme`` key) is byte-for-byte the
  pre-SPEC-068 dict — the additive guarantee every existing consumer relies on;
* each scheme's required and optional fields survive reload instead of being
  projected away;
* every malformed set fails closed — ignored with a warning, never admitted
  half-formed, never a crash, and never leaking a secret value into the log.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from tool_gateway.tools.credential_sets import (
    DEFAULT_SCHEME,
    CredentialSetStore,
    _parse_set,
    scheme_of,
)

_LOG = "tool_gateway.tools.credential_sets"


class ParseSetTests(unittest.TestCase):
    """Unit tests on the pure per-set parser (no file I/O)."""

    def test_basic_with_no_scheme_is_byte_identical(self) -> None:
        # The additive invariant: no ``scheme`` key -> the exact old dict.
        self.assertEqual(
            _parse_set("acme", {"username": "svc", "password": "pw"}),
            {"username": "svc", "password": "pw"},
        )

    def test_basic_with_explicit_scheme_retains_scheme(self) -> None:
        self.assertEqual(
            _parse_set(
                "acme",
                {"scheme": "basic", "username": "svc", "password": "pw"},
            ),
            {"username": "svc", "password": "pw", "scheme": "basic"},
        )

    def test_bearer_requires_and_retains_token(self) -> None:
        self.assertEqual(
            _parse_set("api", {"scheme": "bearer", "token": "abc123"}),
            {"token": "abc123", "scheme": "bearer"},
        )

    def test_oauth2_retains_required_and_optional_fields(self) -> None:
        self.assertEqual(
            _parse_set(
                "snow",
                {
                    "scheme": "oauth2_client_credentials",
                    "token_url": "https://x/oauth_token.do",
                    "client_id": "cid",
                    "client_secret": "csec",
                    "scope": "read",
                    "audience": "urn:snow",
                    "resource": "https://api/",
                    "client_auth": "client_secret_post",
                },
            ),
            {
                "token_url": "https://x/oauth_token.do",
                "client_id": "cid",
                "client_secret": "csec",
                "scope": "read",
                "audience": "urn:snow",
                "resource": "https://api/",
                "client_auth": "client_secret_post",
                "scheme": "oauth2_client_credentials",
            },
        )

    def test_oauth2_drops_unknown_keys(self) -> None:
        entry = _parse_set(
            "snow",
            {
                "scheme": "oauth2_client_credentials",
                "token_url": "https://x",
                "client_id": "cid",
                "client_secret": "csec",
                "surprise": "nope",
            },
        )
        assert entry is not None
        self.assertNotIn("surprise", entry)

    def test_optional_empty_string_is_dropped(self) -> None:
        entry = _parse_set(
            "snow",
            {
                "scheme": "oauth2_client_credentials",
                "token_url": "https://x",
                "client_id": "cid",
                "client_secret": "csec",
                "scope": "",
            },
        )
        assert entry is not None
        self.assertNotIn("scope", entry)

    def test_unknown_scheme_ignored_with_warning(self) -> None:
        with self.assertLogs(_LOG, level="WARNING") as cap:
            self.assertIsNone(
                _parse_set("x", {"scheme": "mtls", "cert": "..."})
            )
        self.assertIn("unknown scheme", "\n".join(cap.output).lower())

    def test_missing_required_field_ignored(self) -> None:
        # oauth2 without client_secret.
        with self.assertLogs(_LOG, level="WARNING"):
            self.assertIsNone(
                _parse_set(
                    "snow",
                    {
                        "scheme": "oauth2_client_credentials",
                        "token_url": "https://x",
                        "client_id": "cid",
                    },
                )
            )

    def test_empty_required_field_ignored(self) -> None:
        self.assertIsNone(_parse_set("api", {"scheme": "bearer", "token": ""}))

    def test_basic_missing_password_ignored(self) -> None:
        self.assertIsNone(_parse_set("acme", {"username": "svc"}))

    def test_non_dict_value_ignored(self) -> None:
        self.assertIsNone(_parse_set("x", "not-a-dict"))

    def test_warning_names_the_set_but_never_leaks_the_secret(self) -> None:
        with self.assertLogs(_LOG, level="WARNING") as cap:
            # client_id empty -> ignored, but the present client_secret must
            # never reach the log line (only the failure class + set name).
            _parse_set(
                "snow",
                {
                    "scheme": "oauth2_client_credentials",
                    "token_url": "https://x",
                    "client_id": "",
                    "client_secret": "SUPERSECRET",
                },
            )
        joined = "\n".join(cap.output)
        self.assertNotIn("SUPERSECRET", joined)
        self.assertIn("snow", joined)


class SchemeOfTests(unittest.TestCase):
    def test_defaults_to_basic(self) -> None:
        self.assertEqual(DEFAULT_SCHEME, "basic")
        self.assertEqual(scheme_of({"username": "a", "password": "b"}), "basic")

    def test_reads_explicit_scheme(self) -> None:
        self.assertEqual(scheme_of({"scheme": "bearer", "token": "t"}), "bearer")


class StoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "creds.json"

    def _write(self, mapping: dict) -> None:
        self.path.write_text(json.dumps(mapping), encoding="utf-8")

    def _bump_mtime(self) -> None:
        stat = os.stat(self.path)
        os.utime(self.path, (stat.st_atime + 10, stat.st_mtime + 10))

    def test_mixed_schemes_all_loaded(self) -> None:
        self._write(
            {
                "acme": {"username": "svc", "password": "pw"},
                "api": {"scheme": "bearer", "token": "t"},
                "snow": {
                    "scheme": "oauth2_client_credentials",
                    "token_url": "https://x",
                    "client_id": "cid",
                    "client_secret": "csec",
                },
            }
        )
        store = CredentialSetStore(str(self.path))
        self.assertEqual(store.names(), ["acme", "api", "snow"])
        self.assertEqual(scheme_of(store.get("acme")), "basic")
        self.assertEqual(scheme_of(store.get("api")), "bearer")
        snow = store.get("snow")
        assert snow is not None
        self.assertEqual(snow["client_secret"], "csec")

    def test_bad_set_skipped_others_loaded(self) -> None:
        self._write(
            {
                "good": {"username": "svc", "password": "pw"},
                "bad": {"scheme": "nope"},
            }
        )
        store = CredentialSetStore(str(self.path))
        self.assertEqual(store.names(), ["good"])

    def test_get_unknown_returns_none(self) -> None:
        self._write({"acme": {"username": "svc", "password": "pw"}})
        store = CredentialSetStore(str(self.path))
        self.assertIsNone(store.get("ghost"))

    def test_unconfigured_store_is_empty(self) -> None:
        store = CredentialSetStore("")
        self.assertFalse(store.configured)
        self.assertEqual(store.names(), [])
        self.assertIsNone(store.get("acme"))

    def test_keep_last_good_on_unreadable(self) -> None:
        self._write({"acme": {"username": "svc", "password": "pw"}})
        store = CredentialSetStore(str(self.path))
        self.assertEqual(store.names(), ["acme"])
        # Corrupt the file; the store must retain the last good load.
        self.path.write_text("{not json", encoding="utf-8")
        self._bump_mtime()
        self.assertEqual(store.names(), ["acme"])

    def test_reload_picks_up_a_new_scheme_on_mtime(self) -> None:
        self._write({"acme": {"username": "svc", "password": "pw"}})
        store = CredentialSetStore(str(self.path))
        self.assertEqual(scheme_of(store.get("acme")), "basic")
        self._write({"acme": {"scheme": "bearer", "token": "t"}})
        self._bump_mtime()
        acme = store.get("acme")
        assert acme is not None
        self.assertEqual(scheme_of(acme), "bearer")
        self.assertEqual(acme["token"], "t")


if __name__ == "__main__":
    unittest.main()

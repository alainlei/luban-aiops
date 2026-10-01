"""Reconcile the harness host clock with the disposable Postgres clock.

SPEC-063 admission evaluates ``requested_at <= clock_timestamp() < expires_at``
against the *database* clock, while the harness stamps envelopes from the *host*
clock. Two host-side effects break that comparison, and neither says anything
about the code under test:

* at-rest skew — the two clocks differ by a small, *unstable* amount: measured
  at +3ms and +7ms (container marginally ahead) on two campaigns, against the
  ~0.75s lag an earlier revision assumed, so no constant is safe to hardcode;
* host suspension — ``time.time()`` follows the RTC across a sleep while the
  suspended VM clock resumes behind it. A 973s host sleep was observed leaving
  the host ahead of the container by far more than any static backdate, which
  surfaced as a spurious ``request_not_yet_valid``.

That skew is therefore *measured*, not budgeted for. :func:`measure` brackets one
``clock_timestamp()`` round trip between two host reads and takes the midpoint,
which bounds the estimate's error by half the round-trip time (milliseconds on
loopback). A wall-vs-monotonic divergence shows the host slept — ``time.monotonic()``
does not advance during macOS sleep while ``time.time()`` does — and re-measures
once, so a suspension costs a single query at the moment it would otherwise
matter instead of invalidating every envelope signed afterwards.

Stdlib only at import time (psycopg is deferred into the query builders) so both
harness interpreters can import this module: the pytest process, and the agent
probe, which runs under ``products/agent-platform/.venv``.
"""
from __future__ import annotations

from datetime import datetime, timezone
import threading
import time

# ``extract(epoch ...)`` rather than a timestamptz: a float is unambiguous about
# time zone and directly comparable with ``time.time()``, where a returned
# datetime would depend on the server's TimeZone setting.
CLOCK_SQL = "SELECT extract(epoch from clock_timestamp())"

# Wall/monotonic divergence above which the host is treated as having been
# suspended. Far above scheduling jitter so a loaded run does not re-measure,
# far below the 973s sleep this exists to survive.
SUSPENSION_THRESHOLD = 5.0

# Statement bound matching DisposablePostgres.connect(): a re-sync must fail fast
# rather than stall inside a test that budgets seconds.
STATEMENT_OPTIONS = "-c statement_timeout=2000 -c lock_timeout=2000"

_installed: list[DatabaseClock] = []


def measure(query) -> float:
    """Estimate ``database epoch - host epoch`` in seconds.

    ``query`` returns the database's current epoch seconds. Bracketing the round
    trip and taking its midpoint bounds the error by half the round-trip time.
    """
    before = time.time()
    database_now = float(query())
    after = time.time()
    return database_now - (before + (after - before) / 2.0)


def database_query(connect):
    """Build a :func:`measure` query from a ``DisposablePostgres``-style connect.

    The connection bounds come from ``connect`` itself, which already carries the
    harness's connect and statement timeouts.
    """
    def query():
        with connect() as conn:
            return conn.execute(CLOCK_SQL).fetchone()[0]
    return query


def dsn_query(dsn):
    """Build a :func:`measure` query for a bare DSN (the agent probe's shape).

    ``dsn`` is expected to carry its own ``connect_timeout``, as the harness DSN
    does, so none is added here and the two cannot disagree.
    """
    def query():
        import psycopg
        with psycopg.connect(dsn, options=STATEMENT_OPTIONS) as conn:
            return conn.execute(CLOCK_SQL).fetchone()[0]
    return query


class DatabaseClock:
    """The host wall clock, corrected by a measured database-clock offset."""

    def __init__(self, query, threshold=SUSPENSION_THRESHOLD):
        self._query = query
        self._threshold = threshold
        self._lock = threading.Lock()
        self._offset = 0.0
        self._wall = None
        self._monotonic = None
        self.measurements = 0
        self.suspensions = 0
        self.resync()

    def resync(self) -> float:
        """Re-measure the offset and return it in seconds."""
        with self._lock:
            return self._resync()

    def _resync(self) -> float:
        # Callers hold the lock; this must never acquire it again.
        self._offset = measure(self._query)
        self.measurements += 1
        return self._offset

    def now(self) -> datetime:
        """The current time as the database would report it.

        A suspension detected here is repaired *before* the returned timestamp is
        computed, so no caller can be handed a value derived from a stale offset.
        """
        self._check_suspension()
        with self._lock:
            offset = self._offset
        # Read the wall clock after the offset settles: reading it earlier would
        # add the re-sync's round-trip time to the result, and drifting forwards
        # is the one direction admission punishes.
        return datetime.fromtimestamp(time.time() + offset, timezone.utc)

    def _check_suspension(self) -> None:
        wall, monotonic = time.time(), time.monotonic()
        with self._lock:
            if self._wall is not None:
                divergence = (wall - self._wall) - (monotonic - self._monotonic)
                if abs(divergence) > self._threshold:
                    self.suspensions += 1
                    self._resync()
            self._wall, self._monotonic = wall, monotonic

    def facts(self) -> dict:
        """Bounded, safe facts for the proof manifest."""
        with self._lock:
            return {"offset_seconds": round(self._offset, 3),
                    "measurements": self.measurements,
                    "suspensions": self.suspensions}


def use_database_clock(database) -> DatabaseClock:
    """Adopt ``database``'s clock as the harness-wide envelope clock."""
    clock = DatabaseClock(database_query(database.connect))
    _installed[:] = [clock]
    return clock


def installed() -> DatabaseClock | None:
    return _installed[0] if _installed else None


def now() -> datetime:
    """The clock envelope timestamps must be stamped from.

    Falls back to the uncorrected host clock only when no database has been
    registered, so the envelope helpers stay importable outside a proof session.
    ``pytest_sessionfinish`` records which of the two happened, so a dropped
    wiring shows up in the evidence instead of silently regressing.
    """
    clock = installed()
    return clock.now() if clock else datetime.now(timezone.utc)

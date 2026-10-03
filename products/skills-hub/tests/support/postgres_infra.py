"""Owned, disposable local Docker PostgreSQL for the retrieval tests (SPEC-066).

R-6 mandates a **real** Postgres: a ``_fake_connect`` returning canned rows
cannot exercise the ``to_tsvector`` prefilter, and a fake returning every row
would make the parity harness pass vacuously (tasks.md Stage 1). This module is
the SPEC-063 ``DisposablePostgres`` precedent adapted for skills-hub — products
never import each other, so it is a deliberate second copy rather than a shared
dependency.

Safety posture carried over from the precedent:

* the container binds **loopback only** on an ephemeral port, and the published
  endpoint is asserted to be ``127.0.0.1:<port>``;
* every Compose object (container, volume, network) carries an owner label and
  teardown **refuses** to remove anything it does not own;
* Docker command output is never propagated (it can contain the generated
  password) and every subprocess call is bounded by a watchdog timeout, so a
  wedged daemon fails loudly with ``PrerequisiteError`` instead of hanging the
  suite;
* the server is verified to be PostgreSQL **16**, matching the live
  ``postgres-0`` the R-5 index migration targets.

Unlike the SPEC-063 failure campaign, this harness does **not** assert crash
durability settings (fsync/full_page_writes/synchronous_commit): retrieval
parity and the index migration do not exercise crash recovery, so those checks
would only add startup failure modes.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import shutil
import subprocess
from pathlib import Path
from uuid import uuid4

import psycopg

COMPOSE = Path(__file__).with_name("compose.yaml")
OWNER_LABEL = "io.luban.spec066.owner"
PROJECT_LABEL = "com.docker.compose.project"


class PrerequisiteError(RuntimeError):
    """A local prerequisite (Docker, compose, PostgreSQL 16) is unavailable."""


def command(args: list[str], *, env=None, timeout=30) -> str:
    """Run a Docker/compose command; never propagate its output.

    Docker errors can contain the generated password, so only a generic failure
    message is raised. The watchdog ``timeout`` bounds every call so a wedged
    daemon surfaces as ``PrerequisiteError`` rather than an infinite hang.
    """
    try:
        result = subprocess.run(
            args, env=env, capture_output=True, text=True, timeout=timeout, check=False
        )
    except (OSError, subprocess.TimeoutExpired):
        raise PrerequisiteError(
            f"{args[0]} unavailable or exceeded its watchdog"
        ) from None
    if result.returncode:
        raise PrerequisiteError(f"{args[0]} prerequisite/resource operation failed")
    return result.stdout.strip()


def prerequisites() -> None:
    """Fail fast on a missing/non-local Docker toolchain.

    Deliberately client-side only (no ``docker version``/``docker info`` server
    round-trip): those contact the daemon and would hang on a wedged engine. The
    PostgreSQL major version is asserted later, from inside the started server.
    """
    for executable in ("docker",):
        if not shutil.which(executable):
            raise PrerequisiteError(
                f"install {executable} before running the SPEC-066 retrieval tests"
            )
    # Only a local Unix-socket daemon is in scope; refuse an implicit remote host.
    host = command(["docker", "context", "inspect", "--format",
                    "{{.Endpoints.docker.Host}}"])
    if not host.startswith("unix://"):
        raise PrerequisiteError(
            "the retrieval tests require a local Unix-socket Docker daemon"
        )
    compose = command(["docker", "compose", "version", "--short"])
    match = re.match(r"v?(\d+)\.", compose)
    if not match or int(match[1]) < 2:
        raise PrerequisiteError("Docker Compose v2 or a compatible successor is required")


class DisposablePostgres:
    """A single-project PostgreSQL 16 container, owned and torn down by us."""

    def __init__(self) -> None:
        self.owner = uuid4().hex
        self.project = f"spec066-{self.owner}"
        self.password = secrets.token_hex(24)  # URL-safe hex; no escaping needed
        self.env = {
            key: value
            for key, value in os.environ.items()
            if key in {"PATH", "HOME", "TMPDIR", "DOCKER_CONFIG"}
        }
        self.env.update(SPEC066_OWNER=self.owner, SPEC066_DB_PASSWORD=self.password)
        self.port = 0
        self.dsn = ""
        self.started = False

    # -- compose plumbing ---------------------------------------------------
    def compose(self, *args: str, timeout: int = 60) -> str:
        return command(
            ["docker", "compose", "--project-name", self.project,
             "--file", str(COMPOSE), *args],
            env=self.env, timeout=timeout,
        )

    def start(self) -> "DisposablePostgres":
        prerequisites()
        self.started = True
        try:
            self.compose("up", "--detach", "--wait", "--wait-timeout", "60", timeout=150)
            container = self.compose("ps", "--quiet", "postgres")
            label = command(["docker", "inspect", "--format",
                             '{{index .Config.Labels "%s"}}' % OWNER_LABEL, container])
            if label != self.owner:
                raise PrerequisiteError("database ownership verification failed")
            endpoint = self.compose("port", "postgres", "5432")
            if not re.fullmatch(r"127\.0\.0\.1:\d+", endpoint):
                raise PrerequisiteError("database must be bound only to loopback")
            self.port = int(endpoint.rsplit(":", 1)[1])
            self.dsn = (
                f"host=127.0.0.1 port={self.port} user=spec066 dbname=spec066 "
                f"password={self.password} connect_timeout=5 sslmode=disable"
            )
            with self._admin() as conn:
                version = conn.execute("SHOW server_version_num").fetchone()[0]
                if int(version) // 10000 != 16:
                    raise PrerequisiteError(
                        "the retrieval tests require PostgreSQL 16 (the live "
                        "postgres-0 major version the R-5 migration targets)"
                    )
            return self
        except BaseException:
            self.close()
            raise

    def _admin(self) -> "psycopg.Connection":
        """A sync autocommit connection to the maintenance database.

        Autocommit is required because ``CREATE DATABASE``/``DROP DATABASE``
        cannot run inside a transaction block.
        """
        if not self.dsn:
            raise PrerequisiteError("disposable Postgres has not started")
        return psycopg.connect(
            self.dsn, autocommit=True,
            options="-c statement_timeout=10000 -c lock_timeout=10000",
        )

    def database_url(self, dbname: str) -> str:
        """A ``postgresql://`` URL for the async store to connect to ``dbname``."""
        if not self.port:
            raise PrerequisiteError("disposable Postgres has not started")
        return (
            f"postgresql://spec066:{self.password}@127.0.0.1:{self.port}"
            f"/{dbname}?sslmode=disable"
        )

    def create_database(self, dbname: str) -> str:
        with self._admin() as conn:
            conn.execute(f'CREATE DATABASE "{dbname}"')
        return self.database_url(dbname)

    def drop_database(self, dbname: str) -> None:
        with self._admin() as conn:
            conn.execute(
                'SELECT pg_terminate_backend(pid) FROM pg_stat_activity '
                "WHERE datname = %s AND pid <> pg_backend_pid()", (dbname,)
            )
            conn.execute(f'DROP DATABASE IF EXISTS "{dbname}"')

    def close(self) -> None:
        if not self.started:
            return
        # Verify ownership of every object Compose created before removing any,
        # so a reused project name can never make us tear down someone else's
        # container, volume or network.
        for kind, list_args in (
            ("container", ["ps", "-aq"]),
            ("volume", ["volume", "ls", "-q"]),
            ("network", ["network", "ls", "-q"]),
        ):
            ids = command(
                ["docker", *list_args, "--filter", f"label={PROJECT_LABEL}={self.project}"]
            ).split()
            for object_id in ids:
                template = (
                    '{{index .Config.Labels "%s"}}' % OWNER_LABEL
                    if kind == "container"
                    else '{{index .Labels "%s"}}' % OWNER_LABEL
                )
                label = command(["docker", kind, "inspect", "--format", template, object_id])
                if label != self.owner:
                    raise PrerequisiteError("refusing teardown of unowned Docker resource")
        try:
            self.compose("down", "--volumes", "--timeout", "5")
        finally:
            self.started = False

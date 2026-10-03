"""Test support package for the skills-hub suite (SPEC-066).

Holds the retrieval test infrastructure that is shared by the R-6 parity
harness, the R-5 migration tests and the R-8 evaluation harness: a disposable
real PostgreSQL 16 (``postgres_infra``) and the pinned 18-document corpus
builder plus committed query-set loader (``corpus``).

Nothing here is collected as a test module (no ``test_*.py``); pytest imports
it as a package because ``tests/`` is on ``sys.path`` under the default prepend
import mode.
"""

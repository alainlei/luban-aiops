#!/bin/sh
# Disposable local proof only. Never uses kube context or caller-provided DB URLs.
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../../.." && pwd)
for command in docker uv; do
    if ! command -v "$command" >/dev/null 2>&1; then
        printf 'SPEC-063 prerequisite missing: %s\n' "$command" >&2
        exit 2
    fi
done
# No user-selectable subset/skip arguments at this required delivery entry point.
if [ "$#" -ne 0 ]; then
    printf 'execution-failure-test accepts no subset or skip arguments\n' >&2
    exit 2
fi
set -- uv run --frozen --project "$ROOT/products/execution-runtime" python \
    "$ROOT/products/execution-runtime/tests/failure/run.py" --stage campaign
# The campaign runs for tens of minutes, and admission compares envelope
# timestamps against the disposable Postgres clock. A host sleep suspends the VM
# and leaves its clock behind the host's on resume, which reads as a spurious
# request_not_yet_valid in tests that assert nothing about time. Hold the system
# awake where caffeinate exists; where it does not, the harness still measures
# the skew and records any suspension in the proof manifest.
if command -v caffeinate >/dev/null 2>&1; then
    exec caffeinate -is "$@"
fi
exec "$@"

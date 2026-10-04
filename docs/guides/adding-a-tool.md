# Adding a Tool to the Tool Gateway

A worked, end-to-end example of contributing a new tool: connector class, tool
definition, error envelope, configuration, wiring, authorization, deployment,
and tests. Written for contributors; the operator-facing activation checklists
live in the [Tool and Connector Guide](tool-configuration.md).

Every connector shipped so far (Kubernetes, Elastic, HTTP, skills, incidents,
secrets, browser) was delivered through a spec, and a new tool changes the
platform's action surface
— so start with a spec per [`docs/specs/README.md`](../specs/README.md) unless
you are extending an existing connector with a closely related tool.

## What the Gateway Gives You for Free

A tool implementation only has to talk to its upstream and shape the result.
The gateway wraps every invocation with:

- **Policy enforcement** — `tools:invoke` is checked before your code runs;
  write/admin tools additionally require `tools:mutate` (deny-by-default).
- **Approval flow** — mutating tools surface an approval card in the portal
  and can never be auto-approved by the agent.
- **Redaction** — all tool results pass through the redaction engine; no
  extra work for credential protection.
- **Audit** — `tool_invoked` and `policy_decision` events are emitted with
  the acting identity.
- **Metrics and evidence** — invocation counters and the portal evidence
  panel work as soon as your result carries the standard evidence envelope.

## Anatomy of a Tool

Three building blocks, all in `products/tool-gateway/src/tool_gateway/tools/`:

- A **connector class** owns the upstream client configuration and registers
  one or more tools.
- Each **tool class** extends `BaseTool` and provides two things: a
  `definition` property returning a `ToolDefinition`, and an async
  `execute(parameters, identity)` returning a `ToolResult`.
- The **`ToolRegistry`** holds registered tools and enforces risk-tier
  admission: `risk_level` must be `read`, `write`, or `admin`, and mutating
  (write/admin) tools are refused registration entirely unless
  `GATEWAY_MUTATING_TOOLS_ENABLED` is true.

The skills connector
(`products/tool-gateway/src/tool_gateway/tools/skills_connector.py`) is the
cleanest reference implementation; the example below follows it.

## Worked Example: a `cmdb.lookup` Tool

Suppose an internal CMDB service exposes
`GET /api/v1/entries/{entry_id}` behind Basic auth, and we want the agent to
be able to look up ownership records. One read-only tool: `cmdb.lookup`.

> **Two tool shapes, and this example is only one of them.** `cmdb.lookup`
> takes its upstream from *configuration* (`GATEWAY_CMDB_SERVICE_URL`) while
> the model supplies only a validated identifier — the deployment chooses the
> upstream, so the tool is SSRF-safe by construction. The other shape, where
> **the model supplies the full URL**, needs a different discipline: a
> server-side origin allowlist, deny-by-default, and redirects that halt the
> moment they leave it. That is `http.get`/`http.post`
> ([SPEC-058](../specs/SPEC-058-http-service-check-tools/spec.md)), which
> inherits `web.navigate`'s allowlist posture rather than this example's
> config-base-URL one. Do not assume the recipe below covers both.

### 1. Create the connector class

`products/tool-gateway/src/tool_gateway/tools/cmdb_connector.py`:

```python
import re
import time

import httpx

from tool_gateway.tools.base import (
    BaseTool,
    ToolDefinition,
    ToolResult,
    build_evidence,
    make_error_result,
)
from tool_gateway.tools.registry import ToolRegistry

SOURCE_SYSTEM = "cmdb"
REQUEST_TIMEOUT_SECONDS = 10.0


class CmdbConnector:
    """Registers read-only CMDB tools backed by the CMDB API."""

    def __init__(self, url: str = "", client_id: str = "", client_secret: str = "") -> None:
        self._url = url
        self._client_id = client_id
        self._client_secret = client_secret

    def register_tools(self, registry: ToolRegistry) -> None:
        registry.register(LookupEntryTool(self))

    async def _get(self, path: str, params: dict | None = None) -> httpx.Response:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
            return await client.get(
                f"{self._url.rstrip('/')}{path}",
                params=params,
                auth=(self._client_id, self._client_secret),
            )
```

Keep the connector thin: configuration plus one authenticated transport
helper. Tools stay small and testable when the HTTP call is a single seam
you can fake in tests.

### 2. Define the tool

```python
class LookupEntryTool(BaseTool):
    def __init__(self, connector: CmdbConnector) -> None:
        self._connector = connector

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="cmdb.lookup",
            description="Look up the CMDB ownership record for a service or host.",
            risk_level="read",
            category="cmdb",
            parameters_schema={
                "type": "object",
                "required": ["entry_id"],
                "properties": {
                    "entry_id": {
                        "type": "string",
                        "description": "CMDB entry id, e.g. svc-payments.",
                    },
                },
            },
        )
```

Choices that matter here:

- **Name** is `<category>.<verb>` — this is what the policy bundle, audit
  events, and the portal tool catalog all display.
- **`risk_level`** decides the enforcement path. `read` needs only
  `tools:invoke`; `write`/`admin` additionally need `tools:mutate`, the
  mutating-tools flag, and produce an approval card. Be honest: anything
  that changes upstream state is at least `write`.
- **`description` and `parameters_schema` are LLM-facing.** The agent
  decides when and how to call your tool from these strings alone, so
  document defaults, limits, and units in them.

### 3. Implement `execute()` with the standard error ladder

```python
_ENTRY_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]*$")


class LookupEntryTool(BaseTool):
    ...

    async def execute(self, parameters: dict, identity: dict) -> ToolResult:
        start = time.perf_counter()

        # 1. Validate parameters -> INVALID_PARAMETERS.
        entry_id = parameters.get("entry_id")
        if not entry_id or not str(entry_id).strip():
            return make_error_result(
                "cmdb.lookup", "INVALID_PARAMETERS",
                "Parameter 'entry_id' is required.", source_system=SOURCE_SYSTEM,
            )
        # 2. Values interpolated into the upstream URL are untrusted LLM
        #    input: validate against a strict pattern before use, or an
        #    adversarial parameter can inject path/query segments into the
        #    gateway's authenticated request.
        if not _ENTRY_ID_PATTERN.match(str(entry_id)):
            return make_error_result(
                "cmdb.lookup", "INVALID_PARAMETERS",
                "Parameter 'entry_id' is not a valid CMDB entry id.",
                source_system=SOURCE_SYSTEM,
            )

        # 3. Transport failures -> TOOL_EXECUTION_ERROR (never raise).
        try:
            response = await self._connector._get(f"/api/v1/entries/{entry_id}")
        except httpx.HTTPError as exc:
            duration_ms = int((time.perf_counter() - start) * 1000)
            return make_error_result(
                "cmdb.lookup", "TOOL_EXECUTION_ERROR",
                f"cmdb unreachable: {exc}",
                source_system=SOURCE_SYSTEM, duration_ms=duration_ms,
            )
        duration_ms = int((time.perf_counter() - start) * 1000)

        # 4. Upstream errors -> domain code or UPSTREAM_ERROR.
        if response.status_code == 404:
            return make_error_result(
                "cmdb.lookup", "ENTRY_NOT_FOUND",
                "The requested CMDB entry was not found.",
                source_system=SOURCE_SYSTEM, duration_ms=duration_ms,
            )
        if response.status_code != 200:
            return make_error_result(
                "cmdb.lookup", "UPSTREAM_ERROR",
                f"cmdb returned HTTP {response.status_code}.",
                source_system=SOURCE_SYSTEM, duration_ms=duration_ms,
            )

        # 5. Success -> project only the keys the agent needs, attach evidence.
        entry = response.json()
        return ToolResult(
            tool_name="cmdb.lookup",
            status="success",
            data={key: entry.get(key) for key in ("entry_id", "owner", "team", "tier")},
            evidence=build_evidence("read", SOURCE_SYSTEM, duration_ms),
        )
```

The rungs of the ladder are a platform convention, not a suggestion:
`execute()` **never raises** — every failure is a structured `ToolResult`
with a stable error code, so the agent can reason about it and the evidence
panel can render it. Project upstream payloads down to a fixed key set (see
`_MATCH_KEYS` in the skills connector) so the tool's output stays stable for
the agent even when the upstream grows fields.

### 4. Add configuration

Extend `GatewaySettings` in
`products/tool-gateway/src/tool_gateway/core/config.py` with
`GATEWAY_<CONNECTOR>_*` variables, following the existing fields:

```python
cmdb_service_url: str = ""
cmdb_client_id: str = "tool-gateway"
cmdb_client_secret: str = ""
```

and the matching `os.getenv("GATEWAY_CMDB_SERVICE_URL", "")` (etc.) entries
in the settings loader. Secrets are never defaulted.

### 5. Wire the connector in `app.py`

Add a gated block to `_build_tool_registry()`. Two gating styles exist:
boolean flags (`GATEWAY_K8S_ENABLED`, `GATEWAY_ELASTIC_ENABLED`) and
URL-presence (skills, incidents). For a connector that is meaningless
without a URL, gate on the URL:

```python
    if settings.cmdb_service_url:
        from tool_gateway.tools.cmdb_connector import CmdbConnector

        connector = CmdbConnector(
            url=settings.cmdb_service_url,
            client_id=settings.cmdb_client_id,
            client_secret=settings.cmdb_client_secret,
        )
        connector.register_tools(registry)
        LOGGER.info("cmdb connector registered")
```

Keep the import inside the branch (the established lazy-import pattern) so a
disabled connector's dependencies are never loaded.

### 6. Authorization

Nothing to do for a `read` tool: the bundle rule `allow-operators-tools`
already grants `tools:invoke` to the operational roles including
`read-only-observer`. For a `write`/`admin` tool, verify the
`allow-operators-tools-mutate` grant matches who should run it — and if it
does not, change the bundle via the
[policy bundle workflow](approval-and-hitl.md#policy-bundle-workflow), never
by editing enforcement code.

### 7. Deployment configuration

For dev-k8s, add the new `GATEWAY_CMDB_SERVICE_URL` to
`shared/platform-ops/gitops/dev-k8s/base/tool-gateway/runtime-config.env`
and put the credential in the `tool-gateway-runtime-secrets` secret
(see the audit-trail provisioning in the
[Tool and Connector Guide](tool-configuration.md) for the established
secret-sync pattern).

### 8. Tests

Per [CONTRIBUTING](../../CONTRIBUTING.md), deny and error paths are not
optional. Model the suite on
`products/tool-gateway/tests/test_skills_connector.py`, which uses a small
`FakeResponse` double patched over the connector's `_get` seam. Cover at
minimum:

- missing/invalid parameters → `INVALID_PARAMETERS` (including the
  URL-interpolation pattern guard, with a malicious value like
  `"../../admin"`)
- transport failure (`httpx.ConnectError`) → `TOOL_EXECUTION_ERROR`
- upstream 404 → your domain code; other non-200 → `UPSTREAM_ERROR`
- success → projected keys only, evidence envelope present
- registration: the tool appears in the registry when the connector is
  configured, and does not when it is not
- if the upstream payload has a shared contract, validate the fake payloads
  against the schema in `shared/shared-contracts/schemas/` (the skills tests
  do this with `jsonschema`) so the double cannot drift from reality

Run `make test` in `products/tool-gateway/` while iterating and `make verify`
at the root before the PR.

### 9. Documentation

Add the new tools and their activation variables to the
[Tool and Connector Guide](tool-configuration.md) so operators can enable
them, and list any new error codes your tool introduces.

## Checklist

- [ ] Spec drafted/linked (new action surface)
- [ ] Connector class + tool classes under `tool_gateway/tools/`
- [ ] Honest `risk_level`; LLM-facing description and schema reviewed
- [ ] `execute()` never raises; standard error-code ladder
- [ ] URL-interpolated parameters validated against a strict pattern
- [ ] Settings in `core/config.py` (`GATEWAY_<CONNECTOR>_*`)
- [ ] Gated wiring in `app.py` with lazy import
- [ ] Policy bundle grants verified (read vs mutate)
- [ ] dev-k8s runtime config + secrets
- [ ] Tests: parameters, transport, upstream errors, success, registration
- [ ] Operator docs updated

## Related Documentation

- [Tool and Connector Guide](tool-configuration.md) — operator activation and configuration
- [Approval and HITL Governance](approval-and-hitl.md) — mutating tools and the approval flow
- [User and Role Administration](user-and-role-administration.md) — who may invoke what
- [CONTRIBUTING](../../CONTRIBUTING.md) — testing expectations and PR checklist

import asyncio
import json
from types import SimpleNamespace

import pytest
from agentscope.event import RequireUserConfirmEvent
from agentscope.message import ToolCallBlock

from agent_service.runtime_kernel import AgentKernel
from agent_service.runtime_settings import RuntimeSettings
from agent_service.services.authoring_trace import AUTHORING_TRACE_STORE
from agent_service.services.execution_records import EXECUTION_RECORD_STORE
from agent_service.services.execution_run_guard import (
    CURRENT_RUN_GUARD,
    RunGuard,
    RunIdentity,
    RunStopLatch,
)
from agent_service.services.execution_signing import (
    canonical_digest,
    verify_envelope,
)
from agent_service.services.flow_approvals import (
    FLOW_APPROVALS,
    FLOW_CONTEXTS,
    FLOW_KILLING_ERROR_CODES,
)
from agent_service.services.hitl_confirmations import CONFIRMATION_REGISTRY
from agent_service.services.secret_params import TRACE_CREDENTIAL_PLACEHOLDER
from agent_service.tools.gateway_tools import (
    CHAT_SESSION_ID,
    EXECUTION_AUDIT_CONTEXT,
    EXECUTION_REQUESTS,
)


def test_placeholder_reply_without_credentials():
    kernel = AgentKernel(settings=RuntimeSettings(api_key=None))

    content, structured_output = asyncio.run(
        kernel.reply_text(
            message="hello",
            session_id="ses-123",
            user_name="alice",
        )
    )

    assert "placeholder response" in content
    assert "ses-123" in content
    assert structured_output is None


def test_placeholder_stream_without_credentials():
    kernel = AgentKernel(settings=RuntimeSettings(api_key=None))

    async def collect_events():
        return [
            event
            async for event in kernel.stream_events(
                message="hello",
                request_id="req-123",
                session_id="ses-123",
                user_name="alice",
            )
        ]

    events = asyncio.run(collect_events())

    assert [event["event"] for event in events] == [
        "message_start",
        "message_delta",
        "message_end",
    ]
    assert events[1]["request_id"] == "req-123"
    assert "placeholder response" in events[1]["delta"]


def test_configuration_hint_mentions_provider_when_configured():
    kernel = AgentKernel(
        settings=RuntimeSettings(
            provider="deepseek",
            model_name="deepseek-v4-flash",
            api_key="test-key",
            base_url="https://api.deepseek.com",
        )
    )

    assert kernel.configuration_hint() == (
        "AgentScope runtime ready through deepseek provider using model "
        "deepseek-v4-flash at https://api.deepseek.com."
    )


def test_runtime_metadata_exposes_provider_state():
    kernel = AgentKernel(
        settings=RuntimeSettings(
            profile="deepseek",
            provider="deepseek",
            model_name="deepseek-v4-flash",
            api_key="test-key",
            base_url="https://api.deepseek.com",
        )
    )

    metadata = kernel.runtime_metadata()

    assert metadata["runtime_state"] == "ready"
    assert metadata["profile"] == "deepseek"
    assert metadata["provider"] == "deepseek"
    assert metadata["model_name"] == "deepseek-v4-flash"
    assert metadata["provider_options"] == {
        "max_tokens": None,
        "temperature": None,
        "top_p": None,
        "thinking_enable": False,
        "reasoning_effort": None,
    }
    assert metadata["last_error"] is None


def test_runtime_metadata_uses_provider_defaults_when_unset():
    kernel = AgentKernel(
        settings=RuntimeSettings(
            provider="dashscope",
            api_key="test-key",
        )
    )

    metadata = kernel.runtime_metadata()

    assert metadata["model_name"] == "qwen-plus"
    assert metadata["base_url"] == "https://dashscope.aliyuncs.com/compatible-mode/v1"


def test_configuration_hint_mentions_provider_error():
    kernel = AgentKernel(
        settings=RuntimeSettings(
            provider="deepseek",
            model_name="deepseek-v4-flash",
            api_key="test-key",
        )
    )
    kernel._last_error = "model rejected request"

    assert kernel.runtime_state() == "provider_error"
    assert kernel.configuration_hint() == (
        "AgentScope runtime is configured through the deepseek provider, "
        "but the last provider call failed: model rejected request"
    )


def test_normalize_event_omits_delta_for_non_text_control_events():
    kernel = AgentKernel(settings=RuntimeSettings(api_key="test-key"))

    event = SimpleNamespace(type="REPLY_START", reply_id="reply-1")

    payload = kernel.normalize_event(
        event,
        request_id="req-123",
        session_id="ses-123",
    )

    assert payload["event"] == "reply_start"
    assert "delta" not in payload


def test_normalize_event_omits_delta_for_text_block_start_without_text():
    kernel = AgentKernel(settings=RuntimeSettings(api_key="test-key"))

    event = SimpleNamespace(
        type="TEXT_BLOCK_START",
        id="block-1",
        reply_id="reply-1",
        metadata={},
    )

    payload = kernel.normalize_event(
        event,
        request_id="req-123",
        session_id="ses-123",
    )

    assert payload["event"] == "text_block_start"
    assert "delta" not in payload


def test_normalize_event_keeps_delta_for_text_block_events():
    kernel = AgentKernel(settings=RuntimeSettings(api_key="test-key"))

    event = SimpleNamespace(type="TEXT_BLOCK_DELTA", delta="STREAM OK")

    payload = kernel.normalize_event(
        event,
        request_id="req-123",
        session_id="ses-123",
    )

    assert payload["event"] == "text_block_delta"
    assert payload["delta"] == "STREAM OK"


class FakeUserMsg:
    def __init__(self, name, content):
        self.name = name
        self.content = content


class FakeAgentState:
    """Minimal AgentState double for post-turn snapshotting."""

    def model_dump_json(self):
        return "{}"


class FakeMemoryAgent:
    def __init__(self):
        self.history = []
        self.state = FakeAgentState()

    async def reply(self, msg, structured_schema=None):
        self.history.append(msg.content)
        return SimpleNamespace(content=f"turn {len(self.history)}")


def test_agent_conversation_state_never_crosses_sessions(monkeypatch):
    kernel = AgentKernel(settings=RuntimeSettings(api_key="test-key"))

    async def fake_build_agent(session_id, bearer_token=None, model_id=None, read_only=False):
        return (FakeMemoryAgent(), FakeUserMsg, model_id or kernel.settings.provider)

    monkeypatch.setattr(kernel, "_build_agent", fake_build_agent)

    reply_a1, _ = asyncio.run(kernel.reply_text("first", "ses-a", "alice"))
    reply_b1, _ = asyncio.run(kernel.reply_text("hello", "ses-b", "bob"))
    reply_a2, _ = asyncio.run(kernel.reply_text("second", "ses-a", "alice"))

    # ses-b starts with fresh memory; ses-a keeps its own history
    assert reply_a1 == "turn 1"
    assert reply_b1 == "turn 1"
    assert reply_a2 == "turn 2"


def test_ensure_agent_reuses_instance_per_session(monkeypatch):
    kernel = AgentKernel(settings=RuntimeSettings(api_key="test-key"))

    async def fake_build_agent(session_id, bearer_token=None, model_id=None, read_only=False):
        return (FakeMemoryAgent(), FakeUserMsg, model_id or kernel.settings.provider)

    monkeypatch.setattr(kernel, "_build_agent", fake_build_agent)

    agent_a, _, _ = asyncio.run(kernel.ensure_agent("ses-a"))
    agent_b, _, _ = asyncio.run(kernel.ensure_agent("ses-b"))

    assert agent_a is not agent_b
    assert asyncio.run(kernel.ensure_agent("ses-a"))[0] is agent_a


def test_ensure_agent_cache_is_bounded(monkeypatch):
    kernel = AgentKernel(
        settings=RuntimeSettings(api_key="test-key"),
        max_cached_agents=1,
    )

    async def fake_build_agent(session_id, bearer_token=None, model_id=None, read_only=False):
        return (FakeMemoryAgent(), FakeUserMsg, model_id or kernel.settings.provider)

    monkeypatch.setattr(kernel, "_build_agent", fake_build_agent)

    agent_a, _, _ = asyncio.run(kernel.ensure_agent("ses-a"))
    asyncio.run(kernel.ensure_agent("ses-b"))

    assert asyncio.run(kernel.ensure_agent("ses-a"))[0] is not agent_a


def test_concurrent_ensure_agent_builds_one_agent_per_session(monkeypatch):
    """Agent creation awaits, so concurrent turns must not each build an agent.

    Without serialisation the loser's agent — and its conversation memory —
    would be silently discarded.
    """
    kernel = AgentKernel(settings=RuntimeSettings(api_key="test-key"))
    build_calls = 0

    async def fake_build_agent(session_id, bearer_token=None, model_id=None, read_only=False):
        nonlocal build_calls
        build_calls += 1
        # Yield control so a concurrent caller can interleave here.
        await asyncio.sleep(0)
        return (FakeMemoryAgent(), FakeUserMsg, model_id or kernel.settings.provider)

    monkeypatch.setattr(kernel, "_build_agent", fake_build_agent)

    async def race():
        return await asyncio.gather(
            kernel.ensure_agent("ses-a"),
            kernel.ensure_agent("ses-a"),
            kernel.ensure_agent("ses-a"),
        )

    results = asyncio.run(race())

    assert build_calls == 1
    first_agent = results[0][0]
    assert all(agent is first_agent for agent, _, _ in results)


class TestPerTokenToolkitCache:
    """SPEC-008 R-5: toolkits are cached per delegated token, never shared."""

    def _kernel(self):
        return AgentKernel(
            settings=RuntimeSettings(
                api_key="test-key",
                tool_gateway_url="http://gw:8080",
            )
        )

    def test_same_token_reuses_cached_toolkit(self, monkeypatch):
        kernel = self._kernel()
        calls = []

        async def fake_discover(gateway_url, bearer_token=None):
            calls.append((gateway_url, bearer_token))
            return [
                {
                    "name": "k8s.list_pods",
                    "description": "x",
                    "risk_level": "read",
                    "parameters_schema": {"type": "object"},
                }
            ]

        monkeypatch.setattr(
            "agent_service.tools.gateway_tools.discover_tools", fake_discover
        )

        first = asyncio.run(kernel._ensure_toolkit("token-a"))
        second = asyncio.run(kernel._ensure_toolkit("token-a"))

        assert first is second
        assert calls == [("http://gw:8080", "token-a")]

    def test_different_tokens_get_distinct_toolkits(self, monkeypatch):
        kernel = self._kernel()
        seen_tokens = []

        async def fake_discover(gateway_url, bearer_token=None):
            seen_tokens.append(bearer_token)
            return [
                {
                    "name": "k8s.list_pods",
                    "description": "x",
                    "risk_level": "read",
                    "parameters_schema": {"type": "object"},
                }
            ]

        monkeypatch.setattr(
            "agent_service.tools.gateway_tools.discover_tools", fake_discover
        )

        toolkit_a = asyncio.run(kernel._ensure_toolkit("token-a"))
        toolkit_b = asyncio.run(kernel._ensure_toolkit("token-b"))

        assert toolkit_a is not toolkit_b
        assert seen_tokens == ["token-a", "token-b"]

    def test_read_only_turn_gets_distinct_filtered_toolkit(self, monkeypatch):
        kernel = self._kernel()

        async def fake_discover(gateway_url, bearer_token=None):
            return [
                {
                    "name": "k8s.list_pods",
                    "description": "x",
                    "risk_level": "read",
                    "parameters_schema": {"type": "object"},
                },
                {
                    "name": "k8s.delete_pod",
                    "description": "x",
                    "risk_level": "write",
                    "parameters_schema": {"type": "object"},
                },
            ]

        monkeypatch.setattr(
            "agent_service.tools.gateway_tools.discover_tools", fake_discover
        )

        full = asyncio.run(kernel._ensure_toolkit("token-a"))
        restricted = asyncio.run(
            kernel._ensure_toolkit("token-a", read_only=True)
        )

        assert full is not restricted
        assert kernel._count_gateway_tools(full) == 2
        assert kernel._count_gateway_tools(restricted) == 1
        # Each cache entry is reused independently of the other.
        assert asyncio.run(kernel._ensure_toolkit("token-a")) is full
        assert (
            asyncio.run(kernel._ensure_toolkit("token-a", read_only=True))
            is restricted
        )

    def test_no_token_degrades_to_empty_toolkit_without_discovery(self, monkeypatch):
        kernel = self._kernel()
        calls = []

        async def fake_discover(gateway_url, bearer_token=None):
            # Without a token discovery short-circuits to an empty list.
            assert bearer_token is None
            calls.append(gateway_url)
            return []

        monkeypatch.setattr(
            "agent_service.tools.gateway_tools.discover_tools", fake_discover
        )

        toolkit = asyncio.run(kernel._ensure_toolkit(None))

        assert toolkit is not None
        # SPEC-018 R-2: an empty discovery is intentionally NOT cached, so a
        # later turn retries discovery instead of being stuck with no tools.
        assert asyncio.run(kernel._ensure_toolkit(None)) is not toolkit
        assert calls == ["http://gw:8080", "http://gw:8080"]


class TestToolkitRegistration:
    """Regression: the token-cached toolkit must really register gateway tools.

    AgentScope 2.x removed ``Toolkit.add``; a toolkit built without tools is
    empty and the model can never invoke the gateway (root cause of the
    hallucinated health report). After SPEC-018 removed the per-request
    toolkit rebuild, these tests assert the schemas are really present on the
    per-token cached toolkit.
    """

    DEFINITION = {
        "name": "k8s.list_pods",
        "description": "List pods in the cluster",
        "risk_level": "read",
        "parameters_schema": {
            "type": "object",
            "properties": {"namespace": {"type": "string"}},
        },
    }

    def _kernel(self, **overrides):
        return AgentKernel(
            settings=RuntimeSettings(
                api_key="test-key",
                tool_gateway_url="http://gw:8080",
                **overrides,
            )
        )

    def _patch_discover(self, monkeypatch, definitions):
        calls = []

        async def fake_discover(gateway_url, bearer_token=None):
            calls.append((gateway_url, bearer_token))
            return definitions

        monkeypatch.setattr(
            "agent_service.tools.gateway_tools.discover_tools", fake_discover
        )
        return calls

    def test_ensure_toolkit_registers_discovered_definitions(self, monkeypatch):
        kernel = self._kernel()
        calls = self._patch_discover(monkeypatch, [self.DEFINITION])

        toolkit = asyncio.run(kernel._ensure_toolkit("token-a"))

        schemas = asyncio.run(toolkit.get_tool_schemas())
        names = {schema["function"]["name"] for schema in schemas}
        assert names == {"k8s_list_pods"}
        assert calls == [("http://gw:8080", "token-a")]
        # Cached per token: a later turn reuses it without re-discovering.
        assert asyncio.run(kernel._ensure_toolkit("token-a")) is toolkit
        assert len(calls) == 1

    def test_rotated_token_discovers_on_cache_miss(self, monkeypatch):
        """Regression: delegated tokens rotate mid-session (portal token
        refresh). A token with no cached toolkit must run discovery instead
        of serving an empty toolkit (which injected the no-tools notice for
        every subsequent turn until browser refresh)."""
        kernel = self._kernel()
        calls = self._patch_discover(monkeypatch, [self.DEFINITION])

        asyncio.run(kernel._ensure_toolkit("token-old"))
        toolkit = asyncio.run(kernel._ensure_toolkit("token-new"))

        assert calls == [
            ("http://gw:8080", "token-old"),
            ("http://gw:8080", "token-new"),
        ]
        schemas = asyncio.run(toolkit.get_tool_schemas())
        names = {schema["function"]["name"] for schema in schemas}
        assert names == {"k8s_list_pods"}
        # The result is cached under the new token.
        assert asyncio.run(kernel._ensure_toolkit("token-new")) is toolkit

    def test_empty_discovery_result_is_not_cached(self, monkeypatch):
        """A failed/empty discovery must not poison the cache: the next turn
        retries discovery instead of being stuck with no tools."""
        kernel = self._kernel()
        results = [[], [self.DEFINITION]]

        async def fake_discover(gateway_url, bearer_token=None):
            return results.pop(0)

        monkeypatch.setattr(
            "agent_service.tools.gateway_tools.discover_tools", fake_discover
        )

        first = asyncio.run(kernel._ensure_toolkit("token-a"))
        assert asyncio.run(first.get_tool_schemas()) == []

        toolkit = asyncio.run(kernel._ensure_toolkit("token-a"))

        schemas = asyncio.run(toolkit.get_tool_schemas())
        names = {schema["function"]["name"] for schema in schemas}
        assert names == {"k8s_list_pods"}

    def test_task_tools_appended_and_excluded_from_gateway_count(self, monkeypatch):
        """R-5: opt-in task tools join the cached toolkit but never count as
        gateway tools, so the no-tools guard stays accurate."""
        kernel = self._kernel(task_tools_enabled=True)
        self._patch_discover(monkeypatch, [self.DEFINITION])

        toolkit = asyncio.run(kernel._ensure_toolkit("token-a"))

        schemas = asyncio.run(toolkit.get_tool_schemas())
        names = {schema["function"]["name"] for schema in schemas}
        assert names == {
            "k8s_list_pods",
            "TaskCreate",
            "TaskGet",
            "TaskList",
            "TaskUpdate",
        }
        assert kernel._count_gateway_tools(toolkit) == 1

    def test_task_tools_only_toolkit_when_gateway_empty(self, monkeypatch):
        kernel = self._kernel(task_tools_enabled=True)
        self._patch_discover(monkeypatch, [])

        toolkit = asyncio.run(kernel._ensure_toolkit("token-a"))

        schemas = asyncio.run(toolkit.get_tool_schemas())
        names = {schema["function"]["name"] for schema in schemas}
        assert names == {"TaskCreate", "TaskGet", "TaskList", "TaskUpdate"}
        assert kernel._count_gateway_tools(toolkit) == 0
        # Empty gateway discovery stays uncached even with task tools.
        assert asyncio.run(kernel._ensure_toolkit("token-a")) is not toolkit

    def test_count_gateway_tools(self):
        from agentscope.tool import Toolkit

        from agent_service.tools.gateway_tools import build_gateway_toolkit

        kernel = self._kernel()

        assert kernel._count_gateway_tools(Toolkit()) == 0

        populated = build_gateway_toolkit([self.DEFINITION], "http://gw:8080")
        assert kernel._count_gateway_tools(populated) == 1


class TestAgentRebuildOnToolRecovery:
    """SPEC-018 R-2: the agent is no longer rebuilt per request, so a cached
    agent that started with zero gateway tools must be rebuilt once discovery
    recovers — persisted state (SPEC-017 R-3) restores its memory."""

    def test_cached_agent_rebuilds_when_gateway_tools_recover(self, monkeypatch):
        kernel = AgentKernel(
            settings=RuntimeSettings(
                api_key="test-key",
                tool_gateway_url="http://gw:8080",
            )
        )
        results = [[], [TestToolkitRegistration.DEFINITION]]

        async def fake_discover(gateway_url, bearer_token=None):
            return results.pop(0)

        monkeypatch.setattr(
            "agent_service.tools.gateway_tools.discover_tools", fake_discover
        )

        builds = 0

        async def fake_build_agent(session_id, bearer_token=None, model_id=None, read_only=False):
            nonlocal builds
            builds += 1
            agent = FakeMemoryAgent()
            # Reflect the toolkit the real Agent would have received.
            agent.toolkit = await kernel._ensure_toolkit(bearer_token)
            return (agent, FakeUserMsg, model_id or kernel.settings.provider)

        monkeypatch.setattr(kernel, "_build_agent", fake_build_agent)

        agent_1, _, _ = asyncio.run(kernel.ensure_agent("ses-r", "token-a"))
        assert builds == 1
        assert kernel._count_gateway_tools(agent_1.toolkit) == 0

        # Discovery recovers: the stale agent is replaced, not reused.
        agent_2, _, _ = asyncio.run(kernel.ensure_agent("ses-r", "token-a"))
        assert builds == 2
        assert agent_2 is not agent_1
        assert kernel._count_gateway_tools(agent_2.toolkit) == 1

        # Steady state afterwards: no further rebuilds.
        agent_3, _, _ = asyncio.run(kernel.ensure_agent("ses-r", "token-a"))
        assert builds == 2
        assert agent_3 is agent_2

    def test_ensure_agent_survives_eviction_during_recovery_check(self, monkeypatch):
        """The await in the recovery check opens a preemption window: LRU
        eviction (or a concurrent rebuild) may remove the session entry while
        ``_ensure_toolkit`` is awaiting. The fast path must fall through to
        the locked rebuild instead of raising KeyError."""
        kernel = AgentKernel(settings=RuntimeSettings(api_key="test-key"))
        builds = 0

        async def fake_build_agent(session_id, bearer_token=None, model_id=None, read_only=False):
            nonlocal builds
            builds += 1
            return (FakeMemoryAgent(), FakeUserMsg, model_id or kernel.settings.provider)

        monkeypatch.setattr(kernel, "_build_agent", fake_build_agent)

        asyncio.run(kernel.ensure_agent("ses-e"))
        assert builds == 1

        # Simulate eviction happening inside the recovery-check await.
        async def evicting_ensure_toolkit(bearer_token=None, read_only=False):
            kernel._agents.pop("ses-e", None)
            from agentscope.tool import Toolkit

            return Toolkit()

        monkeypatch.setattr(kernel, "_ensure_toolkit", evicting_ensure_toolkit)

        agent, _, _ = asyncio.run(kernel.ensure_agent("ses-e"))

        assert builds == 2
        assert agent is not None


# ---------------------------------------------------------------------------
# SPEC-017 R-1: settings-driven kernel configs
# ---------------------------------------------------------------------------


class TestKernelConfigs:
    def test_configs_carry_settings_values(self):
        kernel = AgentKernel(
            settings=RuntimeSettings(
                api_key="test-key",
                max_iters=30,
                context_trigger_ratio=0.6,
                tool_result_limit=20000,
                timezone="Asia/Shanghai",
                model_max_retries=2,
            )
        )

        configs = kernel._build_kernel_configs()

        assert configs["react_config"].max_iters == 30
        assert configs["context_config"].trigger_ratio == 0.6
        assert configs["context_config"].tool_result_limit == 20000
        assert configs["injection_config"].timezone == "Asia/Shanghai"
        assert configs["injection_config"].inject_runtime_state is True
        assert configs["model_config"].max_retries == 2

    def test_configs_default_to_agentscope_values(self):
        kernel = AgentKernel(settings=RuntimeSettings(api_key="test-key"))

        configs = kernel._build_kernel_configs()

        assert configs["react_config"].max_iters == 20
        assert configs["context_config"].trigger_ratio == 0.8
        assert configs["context_config"].tool_result_limit == 50000
        assert configs["injection_config"].timezone == "UTC"
        assert configs["model_config"].max_retries == 0

    def test_configs_disable_compression_tool_by_default(self):
        """SPEC-064 R-2: agent-driven compression is opt-in. The default kernel
        config leaves ``compression_tool_enabled`` False, so agentscope never
        registers the ``CompressContext`` tool and the kernel is byte-identical
        to v0.43.2 (threshold compression still runs off ``trigger_ratio``)."""
        kernel = AgentKernel(settings=RuntimeSettings(api_key="test-key"))

        configs = kernel._build_kernel_configs()

        assert configs["context_config"].compression_tool_enabled is False

    def test_configs_enable_compression_tool_when_opted_in(self):
        """SPEC-064 R-2: the opt-in knob maps straight onto
        ``ContextConfig.compression_tool_enabled``. No ``offloader`` is wired —
        the kernel builds its Agent without one, so compression state stays in
        ``state.summary``/``state.context`` (SPEC-017 snapshot-covered) instead
        of a pod-local Workspace file."""
        kernel = AgentKernel(
            settings=RuntimeSettings(
                api_key="test-key",
                compress_context_enabled=True,
            )
        )

        configs = kernel._build_kernel_configs()

        assert configs["context_config"].compression_tool_enabled is True
        assert configs["context_config"].trigger_ratio == 0.8


# ---------------------------------------------------------------------------
# SPEC-017 R-2: structured output round trip
# ---------------------------------------------------------------------------


class FakeStructuredAgent:
    """Echoes the requested schema back as kernel-validated output."""

    def __init__(self):
        self.state = FakeAgentState()
        self.seen_schemas = []

    async def reply(self, msg, structured_schema=None):
        self.seen_schemas.append(structured_schema)
        structured = (
            {"summary": "validated", "schema_echo": structured_schema}
            if structured_schema is not None
            else None
        )
        return SimpleNamespace(
            content="structured turn", structured_output=structured
        )


SCHEMA = {"type": "object", "properties": {"summary": {"type": "string"}}}


def test_reply_text_passes_schema_and_returns_structured_output(monkeypatch):
    kernel = AgentKernel(settings=RuntimeSettings(api_key="test-key"))
    agent = FakeStructuredAgent()

    async def fake_build_agent(session_id, bearer_token=None, model_id=None, read_only=False):
        return (agent, FakeUserMsg, model_id or kernel.settings.provider)

    monkeypatch.setattr(kernel, "_build_agent", fake_build_agent)

    content, structured = asyncio.run(
        kernel.reply_text(
            "triage it", "ses-s", "alice", response_schema=SCHEMA
        )
    )

    assert content == "structured turn"
    assert structured["summary"] == "validated"
    assert structured["schema_echo"] == SCHEMA
    assert agent.seen_schemas == [SCHEMA]


def test_reply_text_without_schema_returns_none_structured(monkeypatch):
    kernel = AgentKernel(settings=RuntimeSettings(api_key="test-key"))
    agent = FakeStructuredAgent()

    async def fake_build_agent(session_id, bearer_token=None, model_id=None, read_only=False):
        return (agent, FakeUserMsg, model_id or kernel.settings.provider)

    monkeypatch.setattr(kernel, "_build_agent", fake_build_agent)

    content, structured = asyncio.run(
        kernel.reply_text("hello", "ses-s", "alice")
    )

    assert content == "structured turn"
    assert structured is None
    assert agent.seen_schemas == [None]


# ---------------------------------------------------------------------------
# SPEC-017 R-3: conversation state persistence
# ---------------------------------------------------------------------------


def test_reply_text_snapshots_state_after_turn(monkeypatch):
    from agent_service.services.agent_state_store import InMemoryAgentStateStore

    store = InMemoryAgentStateStore()
    monkeypatch.setattr(
        "agent_service.runtime_kernel.AGENT_STATE_STORE", store
    )
    kernel = AgentKernel(settings=RuntimeSettings(api_key="test-key"))

    async def fake_build_agent(session_id, bearer_token=None, model_id=None, read_only=False):
        return (FakeMemoryAgent(), FakeUserMsg, model_id or kernel.settings.provider)

    monkeypatch.setattr(kernel, "_build_agent", fake_build_agent)

    asyncio.run(kernel.reply_text("hello", "ses-durable", "alice"))

    assert store.load_state("ses-durable") == "{}"


def test_snapshot_failure_never_fails_the_turn(monkeypatch):
    class BrokenStore:
        def save_state(self, session_id, state_json):
            raise RuntimeError("state store down")

    monkeypatch.setattr(
        "agent_service.runtime_kernel.AGENT_STATE_STORE", BrokenStore()
    )
    kernel = AgentKernel(settings=RuntimeSettings(api_key="test-key"))

    async def fake_build_agent(session_id, bearer_token=None, model_id=None, read_only=False):
        return (FakeMemoryAgent(), FakeUserMsg, model_id or kernel.settings.provider)

    monkeypatch.setattr(kernel, "_build_agent", fake_build_agent)

    content, structured = asyncio.run(
        kernel.reply_text("hello", "ses-x", "alice")
    )
    assert content == "turn 1"
    assert structured is None


def test_restore_state_round_trips_real_agent_state(monkeypatch):
    from agentscope.state import AgentState

    from agent_service.services.agent_state_store import InMemoryAgentStateStore

    store = InMemoryAgentStateStore()
    monkeypatch.setattr(
        "agent_service.runtime_kernel.AGENT_STATE_STORE", store
    )
    kernel = AgentKernel(settings=RuntimeSettings(api_key="test-key"))

    store.save_state("ses-r", AgentState().model_dump_json())

    restored = kernel._restore_state("ses-r")
    assert isinstance(restored, AgentState)


def test_restore_state_missing_returns_none(monkeypatch):
    from agent_service.services.agent_state_store import InMemoryAgentStateStore

    monkeypatch.setattr(
        "agent_service.runtime_kernel.AGENT_STATE_STORE",
        InMemoryAgentStateStore(),
    )
    kernel = AgentKernel(settings=RuntimeSettings(api_key="test-key"))
    assert kernel._restore_state("ses-empty") is None


def test_restore_state_discards_corrupt_row(monkeypatch):
    from agent_service.services.agent_state_store import InMemoryAgentStateStore

    store = InMemoryAgentStateStore()
    monkeypatch.setattr(
        "agent_service.runtime_kernel.AGENT_STATE_STORE", store
    )
    kernel = AgentKernel(settings=RuntimeSettings(api_key="test-key"))

    store.save_state("ses-poison", "{not valid agent state")

    # A poisoned snapshot must never wedge the session: fresh agent instead.
    assert kernel._restore_state("ses-poison") is None


def test_task_state_round_trips_through_state_store(monkeypatch):
    """SPEC-018 R-5: task tools mutate only AgentState.tasks_context, so the
    SPEC-017 snapshot/restore path persists them with no extra machinery."""
    from agentscope.state import AgentState
    from agentscope.tool import TaskCreate

    from agent_service.services.agent_state_store import InMemoryAgentStateStore

    store = InMemoryAgentStateStore()
    monkeypatch.setattr(
        "agent_service.runtime_kernel.AGENT_STATE_STORE", store
    )
    kernel = AgentKernel(settings=RuntimeSettings(api_key="test-key"))

    state = AgentState()
    asyncio.run(
        TaskCreate().call(
            _agent_state=state,
            subject="diagnose crashloop",
            description="inspect pod restarts",
        )
    )

    # Post-turn snapshot, then restore as a freshly rebuilt agent would.
    kernel._snapshot_state("ses-task", SimpleNamespace(state=state))
    restored = kernel._restore_state("ses-task")

    assert restored is not None
    subjects = [task.subject for task in restored.tasks_context.tasks]
    assert subjects == ["diagnose crashloop"]


# ---------------------------------------------------------------------------
# SPEC-025 R-1: evidence persistence hook
# ---------------------------------------------------------------------------


class FakeEvidenceStore:
    def __init__(self, fail: bool = False):
        self.fail = fail
        self.saved: list[tuple] = []

    def save_turn(self, session_id, request_id, turn_index, frames, budget):
        if self.fail:
            raise RuntimeError("evidence store down")
        self.saved.append((session_id, request_id, turn_index, frames, budget))


def _evidence_frames():
    return [
        {
            "type": "tool_call",
            "tool_name": "k8s.list_pods",
            "call_id": "call-1",
            "parameters": {"namespace": "ops"},
        },
        {
            "type": "tool_result",
            "tool_name": "k8s.list_pods",
            "call_id": "call-1",
            "status": "success",
            "data": {"pods": []},
        },
    ]


class TestEvidencePersistenceHook:
    def test_count_user_turns_counts_user_messages(self):
        kernel = AgentKernel(settings=RuntimeSettings(api_key=None))
        agent = SimpleNamespace(
            state=SimpleNamespace(
                context=[
                    SimpleNamespace(role="system"),
                    SimpleNamespace(role="user"),
                    SimpleNamespace(role="assistant"),
                    SimpleNamespace(role="user"),
                ]
            )
        )
        assert kernel._count_user_turns(agent) == 2

    def test_count_user_turns_degrades_to_zero(self):
        kernel = AgentKernel(settings=RuntimeSettings(api_key=None))
        assert kernel._count_user_turns(SimpleNamespace()) == 0

    def test_persist_evidence_saves_prepared_frames(self, monkeypatch):
        import agent_service.runtime_kernel as rk

        store = FakeEvidenceStore()
        monkeypatch.setattr(rk, "EVIDENCE_STORE", store)
        kernel = AgentKernel(settings=RuntimeSettings(api_key=None))

        kernel._persist_evidence("ses-1", "req-1", 3, _evidence_frames())

        assert len(store.saved) == 1
        session_id, request_id, turn_index, frames, budget = store.saved[0]
        assert (session_id, request_id, turn_index) == ("ses-1", "req-1", 3)
        assert [frame["type"] for frame in frames] == [
            "tool_call",
            "tool_result",
        ]
        assert budget == kernel.settings.evidence_session_max_bytes

    def test_persist_evidence_applies_entry_cap(self, monkeypatch):
        import agent_service.runtime_kernel as rk

        store = FakeEvidenceStore()
        monkeypatch.setattr(rk, "EVIDENCE_STORE", store)
        kernel = AgentKernel(
            settings=RuntimeSettings(api_key=None, evidence_entry_max_chars=10)
        )
        frames = _evidence_frames()
        frames[1]["data"] = {"blob": "x" * 100}

        kernel._persist_evidence("ses-1", "req-1", 0, frames)

        saved_frame = store.saved[0][3][1]
        assert isinstance(saved_frame["data"], str)
        assert len(saved_frame["data"]) == 10
        assert saved_frame["truncated"]["reason"] == "entry_cap"

    def test_persist_evidence_failure_never_raises(self, monkeypatch):
        import agent_service.runtime_kernel as rk
        from prometheus_client import REGISTRY

        monkeypatch.setattr(rk, "EVIDENCE_STORE", FakeEvidenceStore(fail=True))
        kernel = AgentKernel(settings=RuntimeSettings(api_key=None))

        before = (
            REGISTRY.get_sample_value(
                "evidence_store_writes_total", {"result": "error"}
            )
            or 0.0
        )
        kernel._persist_evidence("ses-1", "req-1", 0, _evidence_frames())
        assert (
            REGISTRY.get_sample_value(
                "evidence_store_writes_total", {"result": "error"}
            )
            == before + 1
        )

    def test_persist_evidence_skips_empty_frame_list(self, monkeypatch):
        import agent_service.runtime_kernel as rk

        store = FakeEvidenceStore()
        monkeypatch.setattr(rk, "EVIDENCE_STORE", store)
        kernel = AgentKernel(settings=RuntimeSettings(api_key=None))

        kernel._persist_evidence("ses-1", "req-1", 0, [])
        assert store.saved == []


# --- SPEC-051 R-1/R-3: browser-flow unlock authority + auto-signing ----------

FLOW_SIGNING_KEY = "test-flow-execution-key"

_BROWSER_FLOW = {
    "skill_id": "samples/password-reset",
    "origin": "http://admin.local",
    "title": "Reset User Password",
    "description": "Reset a user's password in the admin portal",
    "risk_class": "write",
}


def _capture_flow_audits(monkeypatch) -> list:
    """Capture audit events the kernel emits (no audit URL is configured)."""
    events: list = []

    def fake_emit(settings, event):
        events.append(event)

    monkeypatch.setattr("agent_service.runtime_kernel.emit_audit_event", fake_emit)
    return events


def _register_flow_pending(session_id, tool_calls, gateway_names, browser_flow):
    return CONFIRMATION_REGISTRY.register(
        session_id,
        "alice",
        "reply-1",
        tool_calls,
        600,
        gateway_names=gateway_names,
        browser_flow=browser_flow,
    )


def _risk_snapshot(*tool_calls, level="write"):
    """A park-time risk-tier snapshot, keyed the way the registry looks it up.

    ``pending_calls_payload`` reads ``risk_levels[tool_call.name]``, so keying
    off the call itself keeps the snapshot honest whichever name form a
    fixture parks (production parks the sanitized gateway name). The R-2
    capture gate reads this tier back off the payload.
    """
    return {call.name: level for call in tool_calls}


def _record_authority(
    session_id,
    *,
    skill_id="samples/password-reset",
    origin="http://admin.local",
    confirm_id="conf-approving",
    owner="alice",
    decider="bob-approver",
    ttl=900.0,
):
    FLOW_APPROVALS.record(
        session_id=session_id,
        confirm_id=confirm_id,
        owner_user_id=owner,
        decider_user_id=decider,
        skill_id=skill_id,
        origin=origin,
        ttl=ttl,
    )


def _record_context(
    session_id,
    *,
    skill_id="samples/password-reset",
    origin="http://admin.local",
):
    FLOW_CONTEXTS.record(
        session_id,
        {
            "skill_id": skill_id,
            "origin": origin,
            "title": "Reset User Password",
            "description": "Reset a user's password in the admin portal",
            "risk_class": "write",
        },
    )


def _run_signer(kernel, tool_call, gateway_tool_name, session_id, requests):
    """Invoke ``_sign_flow_execution`` with the execution contextvars armed
    exactly as ``stream_events``/``resume_confirmation`` arm them for a turn."""
    session_token = CHAT_SESSION_ID.set(session_id)
    requests_token = EXECUTION_REQUESTS.set(requests)
    audit_token = EXECUTION_AUDIT_CONTEXT.set(
        {"request_id": "req-9", "session_id": session_id}
    )
    try:
        return kernel._sign_flow_execution(tool_call, gateway_tool_name)
    finally:
        EXECUTION_AUDIT_CONTEXT.reset(audit_token)
        EXECUTION_REQUESTS.reset(requests_token)
        CHAT_SESSION_ID.reset(session_token)


class TestRecordFlowApproval:
    """SPEC-051 R-1: approving a card whose batch holds a browser write records
    a session+identity-scoped flow authority; anything else records nothing."""

    def _kernel(self, **overrides):
        return AgentKernel(settings=RuntimeSettings(api_key="test-key", **overrides))

    def test_browser_write_batch_records_flow_authority(self):
        FLOW_APPROVALS.clear_all()
        kernel = self._kernel(browser_flow_approval_ttl=900)
        pending = _register_flow_pending(
            "ses-rec-1",
            [ToolCallBlock(id="call-1", name="web_click", input='{"ref": 12}')],
            {"web_click": "web.click"},
            dict(_BROWSER_FLOW),
        )

        kernel._record_flow_approval(pending, "bob-approver", "ses-rec-1")

        approval = FLOW_APPROVALS.get("ses-rec-1")
        assert approval is not None
        assert approval.confirm_id == pending.confirm_id
        assert approval.owner_user_id == "alice"
        assert approval.decider_user_id == "bob-approver"
        assert approval.identity() == (
            "samples/password-reset",
            "http://admin.local",
        )
        assert approval.ttl == 900

    def test_non_browser_write_batch_records_nothing(self):
        """A k8s.* write must never arm browser flow-unlock."""
        FLOW_APPROVALS.clear_all()
        kernel = self._kernel(browser_flow_approval_ttl=900)
        pending = _register_flow_pending(
            "ses-rec-2",
            [ToolCallBlock(id="call-1", name="k8s_restart_service", input="{}")],
            {"k8s_restart_service": "k8s.restart_service"},
            dict(_BROWSER_FLOW),
        )

        kernel._record_flow_approval(pending, "bob-approver", "ses-rec-2")

        assert FLOW_APPROVALS.get("ses-rec-2") is None

    def test_read_tier_browser_batch_records_nothing(self):
        """A batch of only read-tier browser probes is not a mutating flow."""
        FLOW_APPROVALS.clear_all()
        kernel = self._kernel(browser_flow_approval_ttl=900)
        pending = _register_flow_pending(
            "ses-rec-3",
            [ToolCallBlock(id="call-1", name="web_snapshot", input="{}")],
            {"web_snapshot": "web.snapshot"},
            dict(_BROWSER_FLOW),
        )

        kernel._record_flow_approval(pending, "bob", "ses-rec-3")

        assert FLOW_APPROVALS.get("ses-rec-3") is None

    def test_browser_write_without_flow_identity_records_nothing(self):
        """No bound skill/origin ⇒ nothing to scope the authority to, so the
        browser write records nothing and every later write keeps parking."""
        FLOW_APPROVALS.clear_all()
        kernel = self._kernel(browser_flow_approval_ttl=900)
        pending = _register_flow_pending(
            "ses-rec-4",
            [ToolCallBlock(id="call-1", name="web_click", input='{"ref": 1}')],
            {"web_click": "web.click"},
            {},
        )

        kernel._record_flow_approval(pending, "bob", "ses-rec-4")

        assert FLOW_APPROVALS.get("ses-rec-4") is None

    def test_read_class_binding_records_nothing(self):
        """SPEC-054 R-2: a ``risk_class == "read"`` binding can never execute an
        unlocked write — the gateway refuses it BROWSER_FLOW_READ_ONLY on every
        attempt — so no authority is armed and each write keeps parking. The card
        still carries the binding's headline; only the auto-signing is withheld."""
        FLOW_APPROVALS.clear_all()
        kernel = self._kernel(browser_flow_approval_ttl=900)
        pending = _register_flow_pending(
            "ses-rec-6",
            [ToolCallBlock(id="call-1", name="web_click", input='{"ref": 12}')],
            {"web_click": "web.click"},
            {**_BROWSER_FLOW, "risk_class": "read"},
        )

        kernel._record_flow_approval(pending, "bob-approver", "ses-rec-6")

        assert FLOW_APPROVALS.get("ses-rec-6") is None
        # The batch really is a browser write, so the withheld authority is the
        # risk_class condition and not the R-1 predicate.
        assert kernel._batch_has_browser_write(pending) is True

    def test_binding_without_risk_class_records_nothing(self):
        """``FlowContext.risk_class`` defaults to ``read``, so a binding that
        never declared a class arms nothing — the safe default, not a guess."""
        FLOW_APPROVALS.clear_all()
        kernel = self._kernel(browser_flow_approval_ttl=900)
        declared = dict(_BROWSER_FLOW)
        declared.pop("risk_class")
        pending = _register_flow_pending(
            "ses-rec-7",
            [ToolCallBlock(id="call-1", name="web_click", input='{"ref": 12}')],
            {"web_click": "web.click"},
            declared,
        )

        kernel._record_flow_approval(pending, "bob-approver", "ses-rec-7")

        assert FLOW_APPROVALS.get("ses-rec-7") is None

    def test_ttl_zero_records_disabled_authority(self):
        """AGENT_BROWSER_FLOW_APPROVAL_TTL=0 disables flow-unlock: the recorded
        authority is immediately expired (the pre-fix posture)."""
        FLOW_APPROVALS.clear_all()
        kernel = self._kernel(browser_flow_approval_ttl=0)
        pending = _register_flow_pending(
            "ses-rec-5",
            [ToolCallBlock(id="call-1", name="web_click", input='{"ref": 1}')],
            {"web_click": "web.click"},
            dict(_BROWSER_FLOW),
        )

        kernel._record_flow_approval(pending, "bob", "ses-rec-5")

        assert FLOW_APPROVALS.has_approval("ses-rec-5") is False


def _fake_toolkit(*tools):
    """A minimal toolkit exposing the gateway name/risk maps the kernel reads.

    ``tools`` are ``(sanitized_name, gateway_tool_name, gateway_risk_level)``
    triples; ``_toolkit_gateway_name_map``/``_toolkit_risk_map`` walk
    ``tool_groups[].tools[]`` for ``name``/``gateway_tool_name``/
    ``gateway_risk_level``.
    """
    group = SimpleNamespace(
        tools=[
            SimpleNamespace(name=name, gateway_tool_name=gw, gateway_risk_level=risk)
            for (name, gw, risk) in tools
        ]
    )
    return SimpleNamespace(tool_groups=[group])


class TestConfirmationFrameFlowHeadline:
    """SPEC-051 R-6 headline-leak fix + SPEC-054 R-1 declared kind: the card's
    flow headline must describe *this parked batch*, and ``approval_kind`` is
    emitted from the SAME branch, so ``flow_summary`` is present iff the kind is
    ``"flow"``. A non-browser batch parked while a browser flow lingers must
    fall back to action-level rendering — never inherit the stale flow headline
    (the reset-password headline leaking onto a k8s.delete_pod card, the exact
    v0.34.1 regression). A browser-write batch with a bound flow carries both."""

    def _kernel(self):
        return AgentKernel(
            settings=RuntimeSettings(api_key="test-key", hitl_confirm_timeout=600)
        )

    def test_non_browser_batch_carries_no_flow_summary(self):
        FLOW_CONTEXTS.clear_all()
        _record_context("ses-frame-1")  # a lingering "reset password" flow
        kernel = self._kernel()
        toolkit = _fake_toolkit(("k8s_delete_pod", "k8s.delete_pod", "write"))
        event = RequireUserConfirmEvent(
            reply_id="reply-1",
            tool_calls=[
                ToolCallBlock(
                    id="call-1",
                    name="k8s_delete_pod",
                    input='{"pod": "scratch-restart-demo"}',
                )
            ],
        )

        frame = kernel._build_confirmation_frame(
            event, "ses-frame-1", "alice", toolkit=toolkit
        )

        assert frame is not None
        # The leak is fixed: no stale browser-flow headline on an action card.
        assert "flow_summary" not in frame
        # SPEC-054 R-1: the declared kind is "action" — the biconditional
        # (flow_summary present iff kind == "flow") makes the v0.34.1
        # headline-leak structurally impossible, not merely gated.
        assert frame["approval_kind"] == "action"
        # The action itself is still surfaced for action-level rendering.
        assert frame["pending_calls"][0]["tool_name"] == "k8s.delete_pod"
        assert frame["pending_calls"][0]["risk_level"] == "write"

    def test_browser_write_batch_carries_flow_summary(self):
        FLOW_CONTEXTS.clear_all()
        _record_context("ses-frame-2")
        kernel = self._kernel()
        toolkit = _fake_toolkit(("web_click", "web.click", "write"))
        event = RequireUserConfirmEvent(
            reply_id="reply-1",
            tool_calls=[
                ToolCallBlock(id="call-1", name="web_click", input='{"ref": 12}')
            ],
        )

        frame = kernel._build_confirmation_frame(
            event, "ses-frame-2", "alice", toolkit=toolkit
        )

        assert frame is not None
        assert frame["flow_summary"]["title"] == "Reset User Password"
        assert frame["flow_summary"]["skill_id"] == "samples/password-reset"
        assert frame["flow_summary"]["risk_class"] == "write"
        # SPEC-054 R-1: a browser-write batch with a bound flow declares
        # "flow" and carries the headline — the two ride the same branch.
        assert frame["approval_kind"] == "flow"

    def test_read_only_browser_batch_carries_no_flow_summary(self):
        FLOW_CONTEXTS.clear_all()
        _record_context("ses-frame-3")  # a lingering "reset password" flow
        kernel = self._kernel()
        toolkit = _fake_toolkit(("web_snapshot", "web.snapshot", "read"))
        event = RequireUserConfirmEvent(
            reply_id="reply-1",
            tool_calls=[
                ToolCallBlock(id="call-1", name="web_snapshot", input="{}")
            ],
        )

        frame = kernel._build_confirmation_frame(
            event, "ses-frame-3", "alice", toolkit=toolkit
        )

        assert frame is not None
        # A read-tier browser probe is not a browser write, so a lingering
        # flow's headline must not ride this card — the exact leak class the
        # gate fixes (framing follows the parked batch, not ambient session
        # state). Locks the shared predicate against future drift.
        assert "flow_summary" not in frame
        # SPEC-054 R-1: not a browser write, so the kind is "action".
        assert frame["approval_kind"] == "action"
        assert frame["pending_calls"][0]["tool_name"] == "web.snapshot"

    def test_browser_write_without_bound_flow_is_action(self):
        """SPEC-054 R-1/R-2: an ad-hoc browser write with NO flow bound to the
        session is an individually-approved ``action`` (the park-not-deny path),
        not a ``flow`` — ``browser_flow`` is empty when no FlowContext exists,
        so the kind is "action" and no headline rides the card."""
        FLOW_CONTEXTS.clear_all()  # nothing bound at all
        kernel = self._kernel()
        toolkit = _fake_toolkit(("web_click", "web.click", "write"))
        event = RequireUserConfirmEvent(
            reply_id="reply-1",
            tool_calls=[
                ToolCallBlock(id="call-1", name="web_click", input='{"ref": 12}')
            ],
        )

        frame = kernel._build_confirmation_frame(
            event, "ses-frame-4", "alice", toolkit=toolkit
        )

        assert frame is not None
        assert frame["approval_kind"] == "action"
        assert "flow_summary" not in frame
        assert frame["pending_calls"][0]["tool_name"] == "web.click"


class TestCompositionGateCount:
    """SPEC-057 R-4: a mixed browser+infra composition's gate count is the *sum*
    of its browser bindings and its infra writes — one ``flow`` card per distinct
    browser binding, one ``action`` card per infra write — never a single
    composite gate. The composition carries no authority (ADR-0011); the two
    sub-skills' own gates park, each naming only its own tool. This is the unit
    leg the R-8 live demo (password-reset browser write + lock-unlock-user
    ``http.post`` infra write ⇒ 2 cards > any single sub-skill's 1) exercises
    end to end. Both frames are built in ONE session, so the lingering
    password-reset flow context must not leak a headline onto the infra card —
    the ``approval_kind``/``flow_summary`` biconditional (SPEC-054 R-1) is what
    keeps the two gates distinct.
    """

    def _kernel(self):
        return AgentKernel(
            settings=RuntimeSettings(api_key="test-key", hitl_confirm_timeout=600)
        )

    def test_mixed_browser_and_infra_composition_gates_once_per_sub_skill(self):
        FLOW_CONTEXTS.clear_all()
        session = "ses-composition-gates"
        # Sub-skill 1: password-reset, a browser write flow bound to the session.
        _record_context(session)  # samples/password-reset @ http://admin.local
        kernel = self._kernel()

        browser_toolkit = _fake_toolkit(("web_click", "web.click", "write"))
        browser_event = RequireUserConfirmEvent(
            reply_id="reply-1",
            tool_calls=[
                ToolCallBlock(id="call-browser", name="web_click", input='{"ref": 12}')
            ],
        )
        flow_card = kernel._build_confirmation_frame(
            browser_event, session, "alice", toolkit=browser_toolkit
        )

        # Sub-skill 2: lock-unlock-user, an infra ``http.post`` write. It binds
        # no browser flow, so it parks as an individually-approved action even
        # though sub-skill 1's flow context still lingers on the session.
        infra_toolkit = _fake_toolkit(("http_post", "http.post", "write"))
        infra_event = RequireUserConfirmEvent(
            reply_id="reply-2",
            tool_calls=[
                ToolCallBlock(
                    id="call-infra",
                    name="http_post",
                    input='{"url": "https://infra.internal/lock"}',
                )
            ],
        )
        action_card = kernel._build_confirmation_frame(
            infra_event, session, "alice", toolkit=infra_toolkit
        )

        # Two sub-skills ⇒ two gates: one flow card, one action card. The count
        # is the sum (2), exceeding any single sub-skill run (1 each), and the
        # two are distinct parked confirmations.
        assert flow_card is not None
        assert action_card is not None
        assert flow_card["approval_kind"] == "flow"
        assert action_card["approval_kind"] == "action"
        assert flow_card["confirm_id"] != action_card["confirm_id"]
        # Each card names only its own sub-skill — no card claims authority over
        # a sub-skill it does not name (R-4, asserted live by R-8).
        assert flow_card["flow_summary"]["skill_id"] == "samples/password-reset"
        assert flow_card["pending_calls"][0]["tool_name"] == "web.click"
        assert "flow_summary" not in action_card
        assert action_card["pending_calls"][0]["tool_name"] == "http.post"


class TestSignFlowExecution:
    """SPEC-051 R-1/R-3: the kernel's ``flow_signer`` auto-signs a subsequent
    browser write under a live, identity-matched flow authority — injecting the
    envelope into ``EXECUTION_REQUESTS`` and auditing ``execution_requested`` —
    and fails safe (returns ``None`` ⇒ the write parks) on every missing
    precondition. Returning an envelope is what lets the permission middleware
    ALLOW the call instead of parking a second card."""

    def _kernel(self, **overrides):
        kwargs = dict(
            api_key="test-key",
            execution_signing_key=FLOW_SIGNING_KEY,
            browser_flow_approval_ttl=900,
        )
        kwargs.update(overrides)
        return AgentKernel(settings=RuntimeSettings(**kwargs))

    def test_auto_signs_injects_and_audits(self, monkeypatch):
        audits = _capture_flow_audits(monkeypatch)
        FLOW_APPROVALS.clear_all()
        FLOW_CONTEXTS.clear_all()
        kernel = self._kernel()
        session_id = "ses-sign-1"
        _record_authority(session_id, confirm_id="conf-approving")
        _record_context(session_id)
        requests: dict = {}
        tool_call = ToolCallBlock(id="call-77", name="web_click", input='{"ref": 12}')

        envelope = _run_signer(kernel, tool_call, "web.click", session_id, requests)

        assert envelope is not None
        # Injected so the tool closure verifies + hands off like a card call.
        assert requests["call-77"] is envelope
        assert envelope["tool_name"] == "web.click"
        assert envelope["call_id"] == "call-77"
        assert envelope["args_digest"] == canonical_digest({"ref": 12})
        # Reuses the approving card's correlation + identity (ADR-0007).
        assert envelope["confirm_id"] == "conf-approving"
        assert envelope["owner_user_id"] == "alice"
        assert envelope["decider_user_id"] == "bob-approver"
        assert verify_envelope(envelope, envelope["signature"], FLOW_SIGNING_KEY)
        # Durable + audited exactly like a card-signed request.
        rows = EXECUTION_RECORD_STORE.load_for_session(session_id)
        assert [row["execution_id"] for row in rows] == [envelope["execution_id"]]
        assert rows[0]["status"] == "requested"
        requested = [a for a in audits if a["event_type"] == "execution_requested"]
        assert len(requested) == 1
        assert requested[0]["details"]["call_id"] == "call-77"
        assert requested[0]["details"]["confirm_id"] == "conf-approving"
        assert requested[0]["request_id"] == "req-9"
        assert requested[0]["session_id"] == session_id

    def test_fails_safe_on_identity_mismatch(self, monkeypatch):
        """A rebind to a different origin since approval ⇒ the identity guard
        fails safe (None ⇒ the write re-parks). This eliminates the ADR-0007
        cross-flow auto-sign window."""
        _capture_flow_audits(monkeypatch)
        FLOW_APPROVALS.clear_all()
        FLOW_CONTEXTS.clear_all()
        kernel = self._kernel()
        session_id = "ses-sign-2"
        _record_authority(session_id, origin="http://admin.local")
        _record_context(session_id, origin="http://other.local")  # rebound
        requests: dict = {}
        tool_call = ToolCallBlock(id="call-1", name="web_click", input='{"ref": 1}')

        envelope = _run_signer(kernel, tool_call, "web.click", session_id, requests)

        assert envelope is None
        assert requests == {}

    def test_fails_safe_without_approval(self, monkeypatch):
        _capture_flow_audits(monkeypatch)
        FLOW_APPROVALS.clear_all()
        FLOW_CONTEXTS.clear_all()
        kernel = self._kernel()
        session_id = "ses-sign-3"
        _record_context(session_id)  # bound flow, but no approval recorded
        requests: dict = {}
        tool_call = ToolCallBlock(id="call-1", name="web_click", input='{"ref": 1}')

        assert _run_signer(kernel, tool_call, "web.click", session_id, requests) is None
        assert requests == {}

    def test_fails_safe_without_flow_context(self, monkeypatch):
        _capture_flow_audits(monkeypatch)
        FLOW_APPROVALS.clear_all()
        FLOW_CONTEXTS.clear_all()
        kernel = self._kernel()
        session_id = "ses-sign-4"
        _record_authority(session_id)  # approval, but the flow context dropped
        requests: dict = {}
        tool_call = ToolCallBlock(id="call-1", name="web_click", input='{"ref": 1}')

        assert _run_signer(kernel, tool_call, "web.click", session_id, requests) is None
        assert requests == {}

    def test_fails_safe_when_execution_requests_unset(self, monkeypatch):
        """``EXECUTION_REQUESTS`` not armed for the turn ⇒ nothing to inject
        into, so the write cannot be verified/handed off and must park."""
        _capture_flow_audits(monkeypatch)
        FLOW_APPROVALS.clear_all()
        FLOW_CONTEXTS.clear_all()
        kernel = self._kernel()
        session_id = "ses-sign-5"
        _record_authority(session_id)
        _record_context(session_id)
        tool_call = ToolCallBlock(id="call-1", name="web_click", input='{"ref": 1}')

        assert _run_signer(kernel, tool_call, "web.click", session_id, None) is None

    def test_fails_safe_without_signing_key(self, monkeypatch):
        _capture_flow_audits(monkeypatch)
        FLOW_APPROVALS.clear_all()
        FLOW_CONTEXTS.clear_all()
        kernel = self._kernel(execution_signing_key=None)
        session_id = "ses-sign-6"
        _record_authority(session_id)
        _record_context(session_id)
        requests: dict = {}
        tool_call = ToolCallBlock(id="call-1", name="web_click", input='{"ref": 1}')

        assert _run_signer(kernel, tool_call, "web.click", session_id, requests) is None
        assert requests == {}

    def test_fails_safe_without_session_id(self, monkeypatch):
        _capture_flow_audits(monkeypatch)
        FLOW_APPROVALS.clear_all()
        FLOW_CONTEXTS.clear_all()
        kernel = self._kernel()
        _record_authority("ses-sign-7")
        _record_context("ses-sign-7")
        requests: dict = {}
        tool_call = ToolCallBlock(id="call-1", name="web_click", input='{"ref": 1}')

        # CHAT_SESSION_ID unset (None) ⇒ no session to scope an authority to.
        assert _run_signer(kernel, tool_call, "web.click", None, requests) is None
        assert requests == {}

    def test_expired_authority_fails_safe(self, monkeypatch):
        """A TTL-disabled (ttl=0) authority reads as absent ⇒ the write parks."""
        _capture_flow_audits(monkeypatch)
        FLOW_APPROVALS.clear_all()
        FLOW_CONTEXTS.clear_all()
        kernel = self._kernel()
        session_id = "ses-sign-8"
        _record_authority(session_id, ttl=0)
        _record_context(session_id)
        requests: dict = {}
        tool_call = ToolCallBlock(id="call-1", name="web_click", input='{"ref": 1}')

        assert _run_signer(kernel, tool_call, "web.click", session_id, requests) is None
        assert requests == {}

    def test_fails_safe_on_stopped_run(self, monkeypatch):
        """SPEC-063 R-4 (T-21): a stopped run never auto-signs a flow-unlocked
        write. The gate at the flow-signing seam fails safe (``None`` ⇒ the write
        parks) ahead of the intent registration, authoring-trace step, and
        ``execution_requested`` audit, so a stopped run leaves no trace of a
        request that was never made — independent of the permission middleware
        that also denies it first."""
        audits = _capture_flow_audits(monkeypatch)
        FLOW_APPROVALS.clear_all()
        FLOW_CONTEXTS.clear_all()
        kernel = self._kernel()
        session_id = "ses-sign-9"
        _record_authority(session_id)
        _record_context(session_id)
        requests: dict = {}
        tool_call = ToolCallBlock(id="call-1", name="web_click", input='{"ref": 1}')
        latch = RunStopLatch()
        guard = RunGuard(RunIdentity("run-stopped", session_id, "alice"), latch=latch)
        guard.mark_stopped("wait_expired")
        token = CURRENT_RUN_GUARD.set(guard)
        try:
            assert _run_signer(kernel, tool_call, "web.click", session_id, requests) is None
        finally:
            CURRENT_RUN_GUARD.reset(token)
        assert requests == {}
        # No intent/trace/audit side effect escaped the stopped run.
        assert EXECUTION_RECORD_STORE.load_for_session(session_id) == []
        assert [a for a in audits if a["event_type"] == "execution_requested"] == []


# --- SPEC-054 R-2: flow authority invalidation -------------------------------


def _tool_result(tool_name, *, status="error", code=None, call_id="call-1"):
    """A gateway ``tool_result`` trace frame; ``code`` shapes the ``_denied``
    envelope (``error={"code", "message"}``) the kernel inspects."""
    frame = {
        "type": "tool_result",
        "tool_name": tool_name,
        "call_id": call_id,
        "status": status,
    }
    if code is not None:
        frame["error"] = {"code": code, "message": "refused"}
    return frame


def _navigate_call(call_id="call-nav", **parameters):
    """The ``tool_call`` frame the middleware emits ahead of the result."""
    return {
        "type": "tool_call",
        "tool_name": "web.navigate",
        "call_id": call_id,
        "parameters": parameters,
    }


class TestObserveFlowInvalidation:
    """SPEC-054 R-2: a flow-killing gateway result drops BOTH the flow
    reflection and the auto-signing authority for that session, so an authority
    can never outlive the binding it was scoped to — the kernel-side half of
    ADR-0010's two-part backstop."""

    def _kernel(self, **overrides):
        kwargs = dict(
            api_key="test-key",
            execution_signing_key=FLOW_SIGNING_KEY,
            browser_flow_approval_ttl=900,
        )
        kwargs.update(overrides)
        return AgentKernel(settings=RuntimeSettings(**kwargs))

    def _armed(self, session_id):
        """A session holding a live context and a matching authority."""
        FLOW_APPROVALS.clear_all()
        FLOW_CONTEXTS.clear_all()
        _record_authority(session_id)
        _record_context(session_id)
        assert FLOW_APPROVALS.has_approval(session_id)
        assert FLOW_CONTEXTS.get(session_id) is not None

    @pytest.mark.parametrize("code", sorted(FLOW_KILLING_ERROR_CODES))
    def test_flow_killing_refusal_drops_both_stores(self, code):
        session_id = f"ses-inv-{code.lower()}"
        self._armed(session_id)

        AgentKernel._observe_flow_invalidation(
            _tool_result("web.click", code=code), session_id, []
        )

        assert FLOW_CONTEXTS.get(session_id) is None
        assert FLOW_APPROVALS.has_approval(session_id) is False

    @pytest.mark.parametrize(
        "code",
        [
            # The flow is still bound and correctly identified in both cases, so
            # the headline stays truthful and the gateway keeps refusing the
            # write on every attempt without the kernel forgetting the flow.
            "BROWSER_FLOW_READ_ONLY",
            "BROWSER_FLOW_EXHAUSTED",
            # Ordinary tool failures say nothing about the binding.
            "BROWSER_ACTION_ERROR",
            "BROWSER_REF_UNKNOWN",
            "BROWSER_ORIGIN_NOT_ALLOWED",
            "BROWSER_FLOW_TARGET_MISMATCH",
            "TOOL_NOT_FOUND",
        ],
    )
    def test_other_refusals_leave_both_stores_alone(self, code):
        """Over-clearing would cost a legitimately one-gated flow an extra
        approval card, so the set is pinned from both sides (ADR-0007)."""
        session_id = f"ses-keep-{code.lower()}"
        self._armed(session_id)

        AgentKernel._observe_flow_invalidation(
            _tool_result("web.click", code=code), session_id, []
        )

        assert FLOW_CONTEXTS.get(session_id) is not None
        assert FLOW_APPROVALS.has_approval(session_id) is True

    def test_failed_binding_navigate_drops_both_stores(self):
        """The gateway nulls ``entry.flow`` when a navigate that bound the flow
        fails to reach its target, so the kernel's reflection is stale."""
        session_id = "ses-inv-nav-bind"
        self._armed(session_id)
        evidence = [_navigate_call(
            call_id="call-nav",
            url="http://admin.local/x",
            skill_id="samples/password-reset",
        )]

        AgentKernel._observe_flow_invalidation(
            _tool_result("web.navigate", code="BROWSER_NAVIGATION_ERROR",
                         call_id="call-nav"),
            session_id,
            evidence,
        )

        assert FLOW_CONTEXTS.get(session_id) is None
        assert FLOW_APPROVALS.has_approval(session_id) is False

    def test_failed_plain_navigate_keeps_both_stores(self):
        """A navigate without ``skill_id`` left the gateway's binding intact
        ("A pre-existing flow is left intact — the page did not move"), so the
        reflection is still truthful and the authority still valid."""
        session_id = "ses-inv-nav-plain"
        self._armed(session_id)
        evidence = [_navigate_call(call_id="call-nav", url="http://admin.local/x")]

        AgentKernel._observe_flow_invalidation(
            _tool_result("web.navigate", code="BROWSER_NAVIGATION_ERROR",
                         call_id="call-nav"),
            session_id,
            evidence,
        )

        assert FLOW_CONTEXTS.get(session_id) is not None
        assert FLOW_APPROVALS.has_approval(session_id) is True

    def test_unpaired_navigate_failure_keeps_both_stores(self):
        """No ``tool_call`` frame to pair with ⇒ the kernel declines to guess
        and leaves the refusal to the gateway, the fail-closed boundary."""
        session_id = "ses-inv-nav-unpaired"
        self._armed(session_id)

        AgentKernel._observe_flow_invalidation(
            _tool_result("web.navigate", code="BROWSER_NAVIGATION_ERROR",
                         call_id="call-unknown"),
            session_id,
            [],
        )

        assert FLOW_APPROVALS.has_approval(session_id) is True

    def test_successful_navigate_is_not_an_invalidation(self):
        session_id = "ses-inv-nav-ok"
        self._armed(session_id)

        AgentKernel._observe_flow_invalidation(
            _tool_result("web.navigate", status="success"), session_id, []
        )

        assert FLOW_CONTEXTS.get(session_id) is not None
        assert FLOW_APPROVALS.has_approval(session_id) is True

    def test_non_result_frames_and_errorless_results_are_ignored(self):
        """Only a ``tool_result`` carries a gateway refusal; a malformed
        ``error`` degrades instead of raising."""
        session_id = "ses-inv-shape"
        self._armed(session_id)
        kernel = self._kernel()

        kernel._observe_flow_invalidation(
            {"type": "tool_call", "tool_name": "web.click",
             "error": {"code": "BROWSER_FLOW_DENIED"}},
            session_id,
            [],
        )
        kernel._observe_flow_invalidation(
            _tool_result("web.click", status="success"), session_id, []
        )
        kernel._observe_flow_invalidation(
            {"type": "tool_result", "tool_name": "web.click",
             "status": "error", "error": "BROWSER_FLOW_DENIED"},
            session_id,
            [],
        )

        assert FLOW_CONTEXTS.get(session_id) is not None
        assert FLOW_APPROVALS.has_approval(session_id) is True

    def test_clears_only_the_refusing_session(self):
        self._armed("ses-inv-a")
        _record_authority("ses-inv-b")
        _record_context("ses-inv-b")

        AgentKernel._observe_flow_invalidation(
            _tool_result("web.click", code="BROWSER_FLOW_ORIGIN_DEVIATED"),
            "ses-inv-a",
            [],
        )

        assert FLOW_APPROVALS.has_approval("ses-inv-a") is False
        assert FLOW_APPROVALS.has_approval("ses-inv-b") is True
        assert FLOW_CONTEXTS.get("ses-inv-b") is not None

    def test_cleared_session_no_longer_auto_signs(self, monkeypatch):
        """The point of clearing: the next ``web.*`` write in the session fails
        safe (``None`` ⇒ parks for a fresh operator decision) instead of riding
        an authority whose gateway binding is gone."""
        _capture_flow_audits(monkeypatch)
        session_id = "ses-inv-sign"
        self._armed(session_id)
        kernel = self._kernel()
        requests: dict = {}
        tool_call = ToolCallBlock(id="call-88", name="web_click", input='{"ref": 1}')

        # Sanity: while armed, the write auto-signs.
        assert _run_signer(kernel, tool_call, "web.click", session_id, requests)

        kernel._observe_flow_invalidation(
            _tool_result("web.click", code="BROWSER_FLOW_DENIED"), session_id, []
        )
        requests.clear()

        assert _run_signer(kernel, tool_call, "web.click", session_id, requests) is None
        assert requests == {}

    def test_wired_into_the_trace_drain(self):
        """Pins the call site, not just the method: the live and the resumed
        stream both drain through ``_drain_trace_queue``, so that is where a
        refusal has to reach the invalidation path before any later write in the
        same turn can ride the stale authority."""
        session_id = "ses-inv-drain"
        self._armed(session_id)
        kernel = self._kernel()
        queue = asyncio.Queue()
        queue.put_nowait(
            _tool_result("web.click", code="BROWSER_FLOW_ORIGIN_DEVIATED")
        )

        frames = kernel._drain_trace_queue(queue, "req-9", session_id, [], {})

        assert len(frames) == 1
        assert frames[0]["session_id"] == session_id
        assert FLOW_CONTEXTS.get(session_id) is None
        assert FLOW_APPROVALS.has_approval(session_id) is False

    def test_drain_records_a_rebind_then_clears_a_refusal(self):
        """One drain, two frames: a successful navigate records the rebind and a
        later deviation clears it — the single population point and the single
        invalidation point stay ordered, so the session ends the turn holding no
        authority at all."""
        session_id = "ses-inv-drain-2"
        self._armed(session_id)
        kernel = self._kernel()
        queue = asyncio.Queue()
        queue.put_nowait({
            "type": "tool_result",
            "tool_name": "web.navigate",
            "call_id": "call-nav",
            "status": "success",
            "data": {"flow": {**_BROWSER_FLOW, "skill_id": "samples/other"}},
        })
        queue.put_nowait(
            _tool_result("web.click", code="BROWSER_FLOW_DENIED", call_id="call-2")
        )

        kernel._drain_trace_queue(queue, "req-9", session_id, [], {})

        assert FLOW_CONTEXTS.get(session_id) is None
        assert FLOW_APPROVALS.has_approval(session_id) is False


# --- SPEC-055 R-2: authoring-trace capture at both signing sites ------------


class TestAuthoringTraceCapture:
    """SPEC-055 R-2: an approved **and signed** mutation appends one
    replayable, secret-safe step to the session's authoring trace at
    whichever of the two signing sites produced it, so a mixed session
    yields one coherent ordered trace. Nothing else appends — not a denial,
    not an unsigned batch, not a call the park-time tier snapshot does not
    classify as mutating (read-tier *and* unclassified alike: being signed
    is not what makes a call a mutation). Capture is best-effort: a store
    failure degrades graduation candidacy and never the mutation's execution
    or its ``execution_records`` row.
    """

    @pytest.fixture(autouse=True)
    def _clean_trace_store(self):
        """Isolate the module-level singletons between tests.

        Reaches into the in-memory backends' private maps the way
        ``test_execution_records._clean_stores`` does: both stores are
        process-wide singletons, so a leaked session would make another
        test's ``load_for_session`` non-deterministic — and a leaked
        ``(confirm_id, call_id)`` key would silently drop a later
        ``save_request``, since a request persists exactly once.
        """
        traces = getattr(AUTHORING_TRACE_STORE, "_by_session", None)
        targets = getattr(AUTHORING_TRACE_STORE, "_targets", None)
        records = getattr(EXECUTION_RECORD_STORE, "_by_key", None)
        CONFIRMATION_REGISTRY._by_session.clear()
        FLOW_APPROVALS.clear_all()
        FLOW_CONTEXTS.clear_all()
        if traces is not None:
            traces.clear()
        if targets is not None:
            # R-4's declaration map is a separate key space from the step
            # rows: a leaked target would make another test's first-wins
            # assertion read a scope this test never declared.
            targets.clear()
        if records is not None:
            records.clear()
        yield
        if traces is not None:
            traces.clear()
        if targets is not None:
            targets.clear()
        if records is not None:
            records.clear()

    def _kernel(self, **overrides):
        kwargs = dict(
            api_key="test-key",
            execution_signing_key=FLOW_SIGNING_KEY,
            browser_flow_approval_ttl=900,
        )
        kwargs.update(overrides)
        return AgentKernel(settings=RuntimeSettings(**kwargs))

    def _arm_flow(self, session_id):
        _record_authority(session_id, confirm_id="conf-approving")
        _record_context(session_id)

    def _flow_write(self, kernel, session_id, call_id, tool, name, raw):
        """Auto-sign one browser write under the session's flow authority."""
        requests: dict = {}
        envelope = _run_signer(
            kernel,
            ToolCallBlock(id=call_id, name=name, input=raw),
            tool,
            session_id,
            requests,
        )
        assert envelope is not None
        return envelope

    def _run_batch(
        self, kernel, session_id, tool_calls, *, confirmed=True, risk_levels=None
    ):
        """Drive the per-action signing site directly (the resume path is
        exercised end to end in ``test_hitl_confirmations``).

        ``risk_levels`` defaults to snapshotting every parked call at the
        write tier — what ``_toolkit_risk_map`` yields for these tools in
        production — because the R-2 capture gate reads the tier, and a
        fixture that parks with no tier at all would exercise the gate's
        fail-closed branch instead of the seam under test.
        """
        pending = CONFIRMATION_REGISTRY.register(
            session_id,
            "alice",
            "reply-1",
            tool_calls,
            600,
            risk_levels=(
                _risk_snapshot(*tool_calls)
                if risk_levels is None
                else risk_levels
            ),
        )
        requests, rejection = kernel._prepare_executions(
            pending, "bob-approver", confirmed, "req-9", session_id
        )
        return requests, rejection, pending

    def test_per_action_approval_appends_one_step_per_signed_call(
        self, monkeypatch
    ):
        """The card path: one signed request ⇒ one replayable step, carrying
        the arguments a graduation will replay and *references* to the
        execution and card rather than the receipt."""
        audits = _capture_flow_audits(monkeypatch)
        kernel = self._kernel()
        session_id = "ses-trace-action"

        requests, rejection, pending = self._run_batch(
            kernel,
            session_id,
            [
                ToolCallBlock(
                    id="call-1",
                    name="k8s.restart_service",
                    input='{"namespace": "ops"}',
                ),
                ToolCallBlock(
                    id="call-2",
                    name="k8s.scale_deployment",
                    input='{"namespace": "ops", "replicas": 3}',
                ),
            ],
        )

        assert rejection is None
        rows = AUTHORING_TRACE_STORE.load_for_session(session_id)
        assert [row["position"] for row in rows] == [1, 2]
        assert [row["tool_name"] for row in rows] == [
            "k8s.restart_service",
            "k8s.scale_deployment",
        ]
        # Replayable arguments, not the digest — this is exactly what
        # ``execution_records`` cannot give a graduation. ``namespace`` is
        # off the KNOWN_SAFE_FIELDS allow-list for these two tools, so a
        # fail-closed projection would have placeholdered it and made the
        # trace un-graduable; it is off-vocabulary, so it rides verbatim.
        assert rows[0]["args"] == {"namespace": "ops"}
        assert rows[1]["args"] == {"namespace": "ops", "replicas": 3}
        assert TRACE_CREDENTIAL_PLACEHOLDER not in json.dumps(rows)
        # References only: the exact step shape, so no signature, receipt,
        # outcome or digest is duplicated out of ``execution_records``
        # (ADR-0009 — the trace never becomes a second copy of tamper
        # evidence). ``flow_origin`` is present but NULL at capture: this
        # seam runs before the call, and the receipt seam amends it with
        # the origin the gateway reports the interaction landed on
        # (SPEC-055 R-4).
        assert set(rows[0]) == {
            "session_id",
            "position",
            "tool_name",
            "args",
            "execution_id",
            "confirm_id",
            "status",
            "captured_at",
            "flow_origin",
        }
        assert [row["execution_id"] for row in rows] == [
            requests["call-1"]["execution_id"],
            requests["call-2"]["execution_id"],
        ]
        assert {row["confirm_id"] for row in rows} == {pending.confirm_id}
        # Dated from the signature, not from the append.
        assert rows[0]["captured_at"] == requests["call-1"]["requested_at"]
        assert rows[0]["status"] == "draft"
        # No origin yet: capture precedes execution, so there is nothing the
        # gateway could have reported. R-4 amends it from the receipt seam.
        assert all(row["flow_origin"] is None for row in rows)
        # The seam it sits beside is untouched: the durable record and the
        # audit event both still landed.
        assert len(EXECUTION_RECORD_STORE.load_for_session(session_id)) == 2
        assert len(
            [a for a in audits if a["event_type"] == "execution_requested"]
        ) == 2

    def test_flow_unlocked_write_appends_a_step(self, monkeypatch):
        """The flow path: an auto-signed write under a live flow authority
        appends too, stamped with the approving card's ``confirm_id``
        (ADR-0007 — one operator decision per flow)."""
        _capture_flow_audits(monkeypatch)
        kernel = self._kernel()
        session_id = "ses-trace-flow"
        self._arm_flow(session_id)

        envelope = self._flow_write(
            kernel, session_id, "call-77", "web.click", "web_click",
            '{"selector": "#submit"}',
        )

        rows = AUTHORING_TRACE_STORE.load_for_session(session_id)
        assert len(rows) == 1
        step = rows[0]
        assert step["position"] == 1
        assert step["tool_name"] == "web.click"
        assert step["args"] == {"selector": "#submit"}
        assert step["execution_id"] == envelope["execution_id"]
        assert step["confirm_id"] == "conf-approving"
        assert step["captured_at"] == envelope["requested_at"]

    def test_a_mixed_session_yields_one_ordered_trace(self, monkeypatch):
        """Both approval kinds contribute to **one** session-scoped trace, so
        a troubleshooting session mixing an ad-hoc infra write with
        flow-unlocked browser writes graduates as one ordered flow rather
        than two half-traces."""
        _capture_flow_audits(monkeypatch)
        kernel = self._kernel()
        session_id = "ses-trace-mixed"

        self._run_batch(
            kernel,
            session_id,
            [
                ToolCallBlock(
                    id="call-1",
                    name="k8s.restart_service",
                    input='{"namespace": "ops"}',
                )
            ],
        )
        self._arm_flow(session_id)
        # Both flow writes are write-tier members of ``BROWSER_WRITE_TOOLS``,
        # i.e. the only tools the permission middleware ever routes to the
        # flow signer — a read-tier probe would never reach this site.
        self._flow_write(
            kernel, session_id, "call-2", "web.select", "web_select",
            '{"selector": "#role", "value": "admin"}',
        )
        self._flow_write(
            kernel, session_id, "call-3", "web.click", "web_click",
            '{"selector": "#submit"}',
        )

        rows = AUTHORING_TRACE_STORE.load_for_session(session_id)
        assert [row["position"] for row in rows] == [1, 2, 3]
        assert [row["tool_name"] for row in rows] == [
            "k8s.restart_service",
            "web.select",
            "web.click",
        ]
        assert {row["session_id"] for row in rows} == {session_id}
        # One trace with one lifecycle, not one trace per approval kind.
        assert AUTHORING_TRACE_STORE.trace_status(session_id) == "draft"

    def test_a_flow_write_parameterizes_an_opaque_value(self, monkeypatch):
        """``web.type.text`` is opaque by tool rather than by name — the
        residual case of a credential typed straight into a field. It
        becomes a placeholder while its replayable sibling survives, and the
        signed digest still binds the raw arguments."""
        _capture_flow_audits(monkeypatch)
        kernel = self._kernel()
        session_id = "ses-trace-opaque"
        self._arm_flow(session_id)

        envelope = self._flow_write(
            kernel, session_id, "call-1", "web.type", "web_type",
            '{"selector": "#pw", "text": "hunter2-SECRET"}',
        )

        rows = AUTHORING_TRACE_STORE.load_for_session(session_id)
        assert rows[0]["args"] == {
            "selector": "#pw",
            "text": TRACE_CREDENTIAL_PLACEHOLDER,
        }
        # The fixture proves the secret was present to begin with, so the
        # absence assertion is not vacuous.
        assert "hunter2-SECRET" not in json.dumps(rows)
        # Parameterization is a trace-store projection, never a signing
        # input: the digest a gateway verifies against is byte-identical to
        # the pre-parameterization value.
        assert envelope["args_digest"] == canonical_digest(
            {"selector": "#pw", "text": "hunter2-SECRET"}
        )
        assert verify_envelope(envelope, envelope["signature"], FLOW_SIGNING_KEY)

    def test_a_flow_write_with_no_live_authority_appends_nothing(self, monkeypatch):
        """The signer's fail-safe path appends nothing.

        Every ``None`` return in ``_sign_flow_execution`` (no session, no live
        authority, an identity rebind, unarmed execution state, no key, no
        call_id) precedes the capture, so a write the kernel declines to sign
        can never enter a trace — and can never graduate into a flow nothing
        authorized. This is the trace-side half of the chain
        ``test_kernel_middleware``'s read-only-probe test points at.
        """
        _capture_flow_audits(monkeypatch)
        kernel = self._kernel()
        session_id = "ses-trace-no-authority"
        # Deliberately NOT self._arm_flow(session_id): no authority recorded.

        requests: dict = {}
        envelope = _run_signer(
            kernel,
            ToolCallBlock(id="call-1", name="web_click", input='{"ref": 1}'),
            "web.click",
            session_id,
            requests,
        )

        assert envelope is None
        assert requests == {}
        assert AUTHORING_TRACE_STORE.load_for_session(session_id) == []
        assert AUTHORING_TRACE_STORE.trace_status(session_id) is None

    def test_a_read_tier_call_is_signed_but_never_captured(self, monkeypatch):
        """The gate is the tier, not the signature.

        ``elastic.search_logs`` is read-tier but is *not* on the permission
        middleware's curated ``DEFAULT_AUTO_ALLOWED_TOOLS`` (auto-allow needs
        read-only AND allow-listed), so it parks, gets approved and gets
        signed exactly like a mutation — and must still not enter a trace.
        Signing alone would have captured it, which is why the per-action
        site gates on the park-time tier snapshot.
        """
        audits = _capture_flow_audits(monkeypatch)
        kernel = self._kernel()
        session_id = "ses-trace-read"
        read_call = ToolCallBlock(
            id="call-1", name="elastic.search_logs", input='{"query": "error"}'
        )

        requests, rejection, _ = self._run_batch(
            kernel,
            session_id,
            [read_call],
            risk_levels=_risk_snapshot(read_call, level="read"),
        )

        # Signed, persisted and audited like any other approved call...
        assert rejection is None
        assert set(requests) == {"call-1"}
        assert len(EXECUTION_RECORD_STORE.load_for_session(session_id)) == 1
        assert len(
            [a for a in audits if a["event_type"] == "execution_requested"]
        ) == 1
        # ...but it is not a mutation, so it is not a replay step.
        assert AUTHORING_TRACE_STORE.load_for_session(session_id) == []
        assert AUTHORING_TRACE_STORE.trace_status(session_id) is None

    def test_a_mixed_tier_batch_captures_only_the_mutations(self, monkeypatch):
        """One card can park a read beside a write; the trace keeps only the
        write, and the surviving step's ``position`` counts captured steps
        rather than signed ones."""
        _capture_flow_audits(monkeypatch)
        kernel = self._kernel()
        session_id = "ses-trace-mixed-tier"
        read_call = ToolCallBlock(
            id="call-1", name="elastic.search_logs", input='{"query": "error"}'
        )
        write_call = ToolCallBlock(
            id="call-2",
            name="k8s.restart_service",
            input='{"namespace": "ops"}',
        )

        requests, rejection, _ = self._run_batch(
            kernel,
            session_id,
            [read_call, write_call],
            risk_levels={read_call.name: "read", write_call.name: "write"},
        )

        assert rejection is None
        assert set(requests) == {"call-1", "call-2"}
        rows = AUTHORING_TRACE_STORE.load_for_session(session_id)
        assert [row["tool_name"] for row in rows] == ["k8s.restart_service"]
        assert rows[0]["position"] == 1

    def test_a_call_with_no_known_tier_is_never_captured(self, monkeypatch):
        """The gate fails closed on an *unclassified* tier.

        A parked call carries no ``risk_level`` when the toolkit snapshot has
        no entry for it, and ``RISK_LEVEL_ACTIONS`` maps no such key — so the
        gate treats it as "not a known mutation". Chosen over ``!= "read"``
        deliberately: the flow site is positively gated by
        ``BROWSER_WRITE_TOOLS``, the trace store outlives every receipt, and
        the degradation (no graduation candidate) is one R-2 already accepts
        for a store failure.
        """
        _capture_flow_audits(monkeypatch)
        kernel = self._kernel()
        session_id = "ses-trace-unclassified"
        call = ToolCallBlock(
            id="call-1", name="k8s.restart_service", input='{"namespace": "ops"}'
        )

        # Register with no risk snapshot at all: the payload entry carries no
        # ``risk_level`` key, which is the unclassified case.
        pending = CONFIRMATION_REGISTRY.register(
            session_id, "alice", "reply-1", [call], 600
        )
        assert "risk_level" not in pending.pending_calls_payload()[0]

        requests, rejection = kernel._prepare_executions(
            pending, "bob-approver", True, "req-9", session_id
        )

        assert rejection is None
        assert set(requests) == {"call-1"}
        assert len(EXECUTION_RECORD_STORE.load_for_session(session_id)) == 1
        assert AUTHORING_TRACE_STORE.load_for_session(session_id) == []

    def test_a_denied_batch_appends_no_step(self, monkeypatch):
        """A trace is a by-product of an *approved* mutation: a denial
        constructs no request, so it appends no step."""
        _capture_flow_audits(monkeypatch)
        kernel = self._kernel()
        session_id = "ses-trace-denied"

        requests, rejection, _ = self._run_batch(
            kernel,
            session_id,
            [
                ToolCallBlock(
                    id="call-1",
                    name="k8s.restart_service",
                    input='{"namespace": "ops"}',
                )
            ],
            confirmed=False,
        )

        assert (requests, rejection) == ({}, None)
        assert AUTHORING_TRACE_STORE.load_for_session(session_id) == []

    def test_an_unsigned_batch_appends_no_step(self, monkeypatch):
        """No signing key ⇒ the batch is rejected fail-closed *before* the
        capture seam, so an unsigned mutation never enters a trace and can
        never graduate into a flow nothing authorized."""
        audits = _capture_flow_audits(monkeypatch)
        kernel = self._kernel(execution_signing_key=None)
        session_id = "ses-trace-unsigned"

        requests, rejection, _ = self._run_batch(
            kernel,
            session_id,
            [
                ToolCallBlock(
                    id="call-1",
                    name="k8s.restart_service",
                    input='{"namespace": "ops"}',
                )
            ],
        )

        assert requests == {}
        assert rejection == "signing_unavailable"
        assert len(
            [a for a in audits if a["event_type"] == "execution_rejected"]
        ) == 1
        assert AUTHORING_TRACE_STORE.load_for_session(session_id) == []

    def test_a_trace_store_failure_never_blocks_the_execution_record(
        self, monkeypatch
    ):
        """Best-effort + fail-safe at **both** sites: a store that raises
        degrades to "no graduation candidate" while the signed request, the
        durable ``execution_records`` row and the audit all still land."""
        audits = _capture_flow_audits(monkeypatch)

        class BrokenTraceStore:
            backend_name = "broken"

            def append_step(self, step):
                raise RuntimeError("trace store down")

        monkeypatch.setattr(
            "agent_service.runtime_kernel.AUTHORING_TRACE_STORE",
            BrokenTraceStore(),
        )
        kernel = self._kernel()
        session_id = "ses-trace-broken"

        requests, rejection, _ = self._run_batch(
            kernel,
            session_id,
            [
                ToolCallBlock(
                    id="call-1",
                    name="k8s.restart_service",
                    input='{"namespace": "ops"}',
                )
            ],
        )
        self._arm_flow(session_id)
        envelope = self._flow_write(
            kernel, session_id, "call-2", "web.click", "web_click", '{"ref": 1}'
        )

        assert rejection is None
        assert set(requests) == {"call-1"}
        assert envelope is not None
        # The tamper evidence is unaffected by the derived trace failing.
        rows = EXECUTION_RECORD_STORE.load_for_session(session_id)
        assert [row["status"] for row in rows] == ["requested", "requested"]
        assert len(
            [a for a in audits if a["event_type"] == "execution_requested"]
        ) == 2


# --- SPEC-055 R-4: the observed step origin at the receipt seam --------------


class TestObserveStepOrigin:
    """SPEC-055 R-4: a captured browser step is amended with the origin the
    gateway reported the interaction actually landed on.

    R-2 appends at the *signing* seam, before the call runs, so the step
    cannot carry an origin; this is the only place the kernel can read one,
    because ``build_receipt`` digests the outcome and never stores it. Scoped
    to ``BROWSER_WRITE_TOOLS`` — the same set that gates the flow-unlock
    capture site — so the two ends cannot disagree about which steps carry
    origins, and to a ``succeeded`` result, so the trace cannot disagree with
    the receipt beside it either. Best-effort: a store failure degrades
    graduation candidacy and never the receipt already written or the audit
    about to be emitted.
    """

    @pytest.fixture(autouse=True)
    def _clean_trace_store(self):
        """Isolate the process-wide singletons (see ``TestAuthoringTraceCapture``)."""
        traces = getattr(AUTHORING_TRACE_STORE, "_by_session", None)
        targets = getattr(AUTHORING_TRACE_STORE, "_targets", None)
        records = getattr(EXECUTION_RECORD_STORE, "_by_key", None)
        CONFIRMATION_REGISTRY._by_session.clear()
        FLOW_APPROVALS.clear_all()
        FLOW_CONTEXTS.clear_all()
        for space in (traces, targets, records):
            if space is not None:
                space.clear()
        yield
        for space in (traces, targets, records):
            if space is not None:
                space.clear()

    def _kernel(self, **overrides):
        kwargs = dict(
            api_key="test-key",
            execution_signing_key=FLOW_SIGNING_KEY,
            browser_flow_approval_ttl=900,
        )
        kwargs.update(overrides)
        return AgentKernel(settings=RuntimeSettings(**kwargs))

    def _signed_browser_write(self, kernel, session_id, call_id="call-w1"):
        """One flow-unlocked ``web.click``: signed, captured, and returned as
        the request map ``_observe_tool_result`` looks the frame up in."""
        _record_authority(session_id, confirm_id="conf-approving")
        _record_context(session_id)
        requests: dict = {}
        envelope = _run_signer(
            kernel,
            ToolCallBlock(id=call_id, name="web_click", input='{"ref": 1}'),
            "web.click",
            session_id,
            requests,
        )
        assert envelope is not None
        requests[call_id] = envelope
        return requests

    def _result(self, call_id="call-w1", url="https://admin.internal/users/42"):
        return {
            "type": "tool_result",
            "tool_name": "web.click",
            "call_id": call_id,
            "status": "success",
            "request_id": "req-9",
            "data": {"url": url},
        }

    def test_a_captured_browser_step_gains_the_observed_origin(self):
        kernel = self._kernel()
        session_id = "ses-origin-1"
        requests = self._signed_browser_write(kernel, session_id)
        # Captured with no origin: the signing seam precedes execution.
        assert AUTHORING_TRACE_STORE.load_for_session(session_id)[0][
            "flow_origin"
        ] is None

        kernel._observe_tool_result(self._result(), requests)

        rows = AUTHORING_TRACE_STORE.load_for_session(session_id)
        assert len(rows) == 1
        # Normalized to an origin, not stored as the reported URL: the path
        # and query of a live page are not the operator's declared scope, and
        # a query string could carry a credential into a store that outlives
        # every receipt.
        assert rows[0]["flow_origin"] == "https://admin.internal"

    @pytest.mark.parametrize(
        ("error", "receipt_status"),
        [({}, "failed"), ({"code": "TIMEOUT"}, "timeout")],
    )
    def test_a_write_that_did_not_succeed_records_no_origin(
        self, error, receipt_status
    ):
        """Only a ``succeeded`` result is corroborated as having landed.

        A failed or timed-out browser write can still report the URL it was
        *attempting*, and recording that would let a mutation which never
        happened count toward graduation — the trace would claim a landing the
        receipt beside it denies. The gate reads the ``status`` the receipt was
        just built with rather than re-reading the frame, so the two cannot
        drift apart. A timeout is the sharper case: whether it landed is
        genuinely unknown, and unknown must stay NULL (unverified, so R-4
        refuses the draft) rather than harden into an assertion.
        """
        kernel = self._kernel()
        session_id = "ses-origin-failed"
        requests = self._signed_browser_write(kernel, session_id)

        kernel._observe_tool_result(
            {
                "type": "tool_result",
                "tool_name": "web.click",
                "call_id": "call-w1",
                "status": "error",
                "request_id": "req-9",
                "error": error,
                "data": {"url": "https://admin.internal/users/42"},
            },
            requests,
        )

        assert AUTHORING_TRACE_STORE.load_for_session(session_id)[0][
            "flow_origin"
        ] is None
        # The receipt still closed, and with the status that decided the gate:
        # the amendment is derived from the receipt, never the other way round.
        records = EXECUTION_RECORD_STORE.load_for_session(session_id)
        assert len(records) == 1
        assert records[0]["status"] == receipt_status

    def test_an_uncertain_v3_outcome_writes_no_definitive_receipt(
        self, monkeypatch
    ):
        """SPEC-063 R-3b (T-17): a v3 caller timeout / transport uncertainty
        surfaces as ``OUTCOME_UNKNOWN`` and must never close the v2 execution
        row with a synthetic ``timeout``/``failed`` receipt. The attributed
        ``wait_expired`` observation the coordinator appended to the durable
        ledger is the record, and a late worker result must stay appendable
        there; a definitive receipt here would contradict the unknown outcome.
        The row is left ``requested`` (unclosed) and no completion audit fires.
        """
        audits = _capture_flow_audits(monkeypatch)
        kernel = self._kernel()
        session_id = "ses-origin-uncertain"
        requests = self._signed_browser_write(kernel, session_id)

        kernel._observe_tool_result(
            {
                "type": "tool_result",
                "tool_name": "web.click",
                "call_id": "call-w1",
                "status": "error",
                "request_id": "req-9",
                "error": {"code": "OUTCOME_UNKNOWN", "reason": "wait_expired"},
            },
            requests,
        )

        records = EXECUTION_RECORD_STORE.load_for_session(session_id)
        assert len(records) == 1
        assert records[0]["status"] == "requested"
        assert records[0]["receipt"] is None
        assert not [
            a for a in audits if a["event_type"] == "execution_completed"
        ]
        # An unknown outcome is never corroborated as having landed.
        assert AUTHORING_TRACE_STORE.load_for_session(session_id)[0][
            "flow_origin"
        ] is None

    def test_a_non_browser_step_is_left_unobserved(self):
        kernel = self._kernel()
        session_id = "ses-origin-k8s"
        pending = CONFIRMATION_REGISTRY.register(
            session_id,
            "alice",
            "reply-1",
            [ToolCallBlock(id="call-1", name="k8s.restart_service",
                           input='{"namespace": "ops"}')],
            600,
            risk_levels=_risk_snapshot(
                ToolCallBlock(id="call-1", name="k8s.restart_service",
                              input='{"namespace": "ops"}')
            ),
        )
        requests, rejection = kernel._prepare_executions(
            pending, "bob-approver", True, "req-9", session_id
        )
        assert rejection is None

        # A frame that happens to carry an http URL on an infra tool must not
        # attach an origin: ``flow_origin`` is evidence about the web target a
        # mutation landed on, and a spurious value would read as a drift at
        # graduation.
        kernel._observe_tool_result(
            {
                "type": "tool_result",
                "tool_name": "k8s.restart_service",
                "call_id": "call-1",
                "status": "success",
                "request_id": "req-9",
                "data": {"url": "https://admin.internal/console"},
            },
            requests,
        )

        rows = AUTHORING_TRACE_STORE.load_for_session(session_id)
        assert len(rows) == 1
        assert rows[0]["flow_origin"] is None

    def test_a_frame_with_no_legible_url_leaves_the_step_unverified(self):
        kernel = self._kernel()
        session_id = "ses-origin-nourl"
        requests = self._signed_browser_write(kernel, session_id)

        # The evidence frame's size guard omits ``data`` entirely rather than
        # truncating it, so an over-budget payload reports no URL at all.
        for frame in (
            {"type": "tool_result", "tool_name": "web.click",
             "call_id": "call-w1", "status": "success", "request_id": "req-9"},
            {"type": "tool_result", "tool_name": "web.click",
             "call_id": "call-w1", "status": "success", "request_id": "req-9",
             "data": {"url": "about:blank"}},
            {"type": "tool_result", "tool_name": "web.click",
             "call_id": "call-w1", "status": "success", "request_id": "req-9",
             "data": "not-a-mapping"},
        ):
            kernel._observe_tool_result(frame, requests)

        # NULL, i.e. *unverified* — which R-4 refuses to graduate, rather than
        # a fabricated origin that would corroborate nothing.
        assert AUTHORING_TRACE_STORE.load_for_session(session_id)[0][
            "flow_origin"
        ] is None

    def test_a_rejected_call_records_no_origin(self):
        kernel = self._kernel()
        session_id = "ses-origin-rejected"
        requests = self._signed_browser_write(kernel, session_id)

        # An invocation-boundary rejection never reached the gateway, so there
        # is no page to have landed on; the seam returns before the receipt leg.
        kernel._observe_tool_result(
            {
                "type": "tool_result",
                "tool_name": "web.click",
                "call_id": "call-w1",
                "status": "error",
                "request_id": "req-9",
                "error": {"code": "EXECUTION_REJECTED", "reason": "digest_mismatch"},
                "data": {"url": "https://admin.internal/users/42"},
            },
            requests,
        )

        assert AUTHORING_TRACE_STORE.load_for_session(session_id)[0][
            "flow_origin"
        ] is None

    def test_a_frame_for_an_unknown_call_is_ignored(self):
        kernel = self._kernel()
        session_id = "ses-origin-unknown"
        requests = self._signed_browser_write(kernel, session_id)

        # No request for this call id ⇒ nothing was signed ⇒ nothing was
        # captured ⇒ nothing to amend.
        kernel._observe_tool_result(self._result(call_id="call-other"), requests)

        assert AUTHORING_TRACE_STORE.load_for_session(session_id)[0][
            "flow_origin"
        ] is None

    def test_a_trace_store_failure_never_blocks_the_receipt(self, monkeypatch):
        audits = _capture_flow_audits(monkeypatch)
        kernel = self._kernel()
        session_id = "ses-origin-broken"
        requests = self._signed_browser_write(kernel, session_id)

        class BrokenOriginStore:
            backend_name = "broken"

            def record_step_origin(self, session_id, execution_id, origin):
                raise RuntimeError("trace store down")

        monkeypatch.setattr(
            "agent_service.runtime_kernel.AUTHORING_TRACE_STORE",
            BrokenOriginStore(),
        )

        kernel._observe_tool_result(self._result(), requests)

        # The receipt closed and the completion audit went out: the derived
        # amendment failing degrades graduation candidacy only.
        rows = EXECUTION_RECORD_STORE.load_for_session(session_id)
        assert [row["status"] for row in rows] == ["succeeded"]
        assert len(
            [a for a in audits if a["event_type"] == "execution_completed"]
        ) == 1

    def test_wired_into_the_trace_drain(self):
        """Pins the call site, not just the method: both the live and the
        resumed stream drain through ``_drain_trace_queue``, so that is where
        the observation has to reach the store before the turn ends."""
        kernel = self._kernel()
        session_id = "ses-origin-drain"
        requests = self._signed_browser_write(kernel, session_id)
        queue = asyncio.Queue()
        queue.put_nowait(self._result())

        frames = kernel._drain_trace_queue(queue, "req-9", session_id, [], requests)

        assert len(frames) == 1
        assert AUTHORING_TRACE_STORE.load_for_session(session_id)[0][
            "flow_origin"
        ] == "https://admin.internal"

    def test_a_later_observation_never_rewrites_the_first(self):
        kernel = self._kernel()
        session_id = "ses-origin-twice"
        requests = self._signed_browser_write(kernel, session_id)

        kernel._observe_tool_result(self._result(), requests)
        # A second frame for the same execution — a retry surfacing twice on
        # the queue — must not move what the step was first seen to do.
        kernel._observe_tool_result(
            self._result(url="https://elsewhere.internal/x"), requests
        )

        assert AUTHORING_TRACE_STORE.load_for_session(session_id)[0][
            "flow_origin"
        ] == "https://admin.internal"


class TestExecutionAdmissionCutover:
    """SPEC-063 R-4a (T-08): under disabled-by-default durable admission the
    signing seams stamp the v3 run/epoch/expiry window onto every executable
    envelope, and a batch or flow authority missing its durable run identity
    fails closed (resume) or fails safe (park) rather than signing a v2 envelope
    a bound v3 guard would reject mid-dispatch. Inert when admission is off."""

    _EPOCH = "22222222-2222-4222-8222-222222222222"
    _RUN_ID = "11111111-1111-4111-8111-111111111111"

    @pytest.fixture(autouse=True)
    def _isolate_stores(self):
        traces = getattr(AUTHORING_TRACE_STORE, "_by_session", None)
        targets = getattr(AUTHORING_TRACE_STORE, "_targets", None)
        records = getattr(EXECUTION_RECORD_STORE, "_by_key", None)
        CONFIRMATION_REGISTRY._by_session.clear()
        FLOW_APPROVALS.clear_all()
        FLOW_CONTEXTS.clear_all()
        for space in (traces, targets, records):
            if space is not None:
                space.clear()
        yield
        for space in (traces, targets, records):
            if space is not None:
                space.clear()

    def _admission_kernel(self):
        return AgentKernel(settings=RuntimeSettings(
            api_key="test-key",
            execution_signing_key=FLOW_SIGNING_KEY,
            browser_flow_approval_ttl=900,
            execution_admission_enabled=True,
            execution_state_db_url="postgresql://u:p@127.0.0.1:1/db",
            execution_admission_epoch=self._EPOCH,
        ))

    def _legacy_kernel(self):
        return AgentKernel(settings=RuntimeSettings(
            api_key="test-key",
            execution_signing_key=FLOW_SIGNING_KEY,
            browser_flow_approval_ttl=900,
        ))

    def _pending(self, session_id, *, run_id=None):
        call = ToolCallBlock(
            id="call-1", name="k8s.restart_service", input='{"ns": "ops"}'
        )
        return CONFIRMATION_REGISTRY.register(
            session_id, "alice", "reply-1", [call], 600,
            risk_levels=_risk_snapshot(call), run_id=run_id,
        )

    def test_resume_batch_signs_the_v3_window_under_admission(self):
        kernel = self._admission_kernel()
        session_id = "ses-v3-resume"
        pending = self._pending(session_id, run_id=self._RUN_ID)

        requests, rejection = kernel._prepare_executions(
            pending, "bob-approver", True, "req-9", session_id
        )

        assert rejection is None
        envelope = requests["call-1"]
        assert envelope["protocol_version"] == 3
        assert envelope["run_id"] == self._RUN_ID
        assert envelope["admission_epoch"] == self._EPOCH
        assert envelope["expires_at"]
        # The window sits inside the HMAC, so it is a signed fact.
        assert verify_envelope(
            envelope, envelope["signature"], FLOW_SIGNING_KEY
        )

    def test_resume_missing_run_identity_fails_closed(self, monkeypatch):
        from agent_service.services.execution_signing import (
            REASON_REQUEST_MISSING,
        )

        audits = _capture_flow_audits(monkeypatch)
        kernel = self._admission_kernel()
        session_id = "ses-v3-resume-norunid"
        pending = self._pending(session_id)  # run_id None: a pre-cutover card

        requests, rejection = kernel._prepare_executions(
            pending, "bob-approver", True, "req-9", session_id
        )

        assert requests == {}
        assert rejection == REASON_REQUEST_MISSING
        rejected = [
            a for a in audits if a["event_type"] == "execution_rejected"
        ]
        assert len(rejected) == 1
        assert rejected[0]["details"]["reason"] == REASON_REQUEST_MISSING

    def test_admission_disabled_signs_the_legacy_v2_envelope(self):
        kernel = self._legacy_kernel()
        session_id = "ses-v2-resume"
        pending = self._pending(session_id)

        requests, rejection = kernel._prepare_executions(
            pending, "bob-approver", True, "req-9", session_id
        )

        assert rejection is None
        envelope = requests["call-1"]
        # No v3 window: the legacy envelope is byte-for-byte unchanged.
        assert "protocol_version" not in envelope
        assert "run_id" not in envelope
        assert "expires_at" not in envelope

    def test_flow_write_signs_the_v3_window_under_admission(self):
        kernel = self._admission_kernel()
        session_id = "ses-v3-flow"
        FLOW_APPROVALS.record(
            session_id=session_id, confirm_id="conf-approving",
            owner_user_id="alice", decider_user_id="bob-approver",
            skill_id="samples/password-reset", origin="http://admin.local",
            ttl=900.0, run_id=self._RUN_ID,
        )
        _record_context(session_id)
        requests: dict = {}

        envelope = _run_signer(
            kernel,
            ToolCallBlock(id="call-w1", name="web_click", input='{"ref": 1}'),
            "web.click", session_id, requests,
        )

        assert envelope is not None
        assert envelope["protocol_version"] == 3
        assert envelope["run_id"] == self._RUN_ID
        assert envelope["admission_epoch"] == self._EPOCH
        assert envelope["approval_kind"] == "flow"

    def test_flow_authority_without_run_identity_parks(self):
        kernel = self._admission_kernel()
        session_id = "ses-v3-flow-norunid"
        _record_authority(session_id)  # run_id defaults to None
        _record_context(session_id)
        requests: dict = {}

        envelope = _run_signer(
            kernel,
            ToolCallBlock(id="call-w1", name="web_click", input='{"ref": 1}'),
            "web.click", session_id, requests,
        )

        # Fails safe: park rather than sign a v2 envelope under a v3 guard.
        assert envelope is None
        assert requests == {}


# --- SPEC-055 R-5: replaying a graduated executable flow --------------------

# The flow dict a graduated *browser* executable flow rides back on
# ``web.navigate``'s ``data["flow"]`` once a human merges the R-4 draft and
# skills-hub ingests it: the declaration a hand-authored browser flow already
# had. There is no ``kind`` and no ``steps`` key here because the gateway's
# ``FlowState`` declares neither — ``GraduatedFlowReplayTests`` in tool-gateway
# pins that at the seam where the skill record is actually read. ``title`` and
# ``description`` are the strings ``build_executable_flow_draft`` derives, so
# this is a graduated flow and not merely a renamed one.
_GRADUATED_FLOW = {
    "skill_id": "team-a/web/inventoryhealth",
    "origin": "https://inventory.internal:8443",
    "risk_class": "write",
    "title": "https://inventory.internal:8443 executable flow",
    "description": (
        "Replays 3 approved mutating step(s) captured from an operator "
        "session against https://inventory.internal:8443/login: web.select, "
        "web.type, web.click."
    ),
    # Deliberately empty: the renderer never synthesizes a decision line,
    # because inventing a sentence the trace did not say is the composition
    # R-4 forbids. A human may add one at merge time.
    "flow_intent": "",
    "steps_used": 0,
    # The gateway's GATEWAY_BROWSER_FLOW_MAX_STEPS, not len(steps).
    "max_steps": 20,
    "approved": False,
}

# The v2 replay contract, as skills-hub stores it and ``skills.get`` returns
# it verbatim. Three steps against a twenty-step budget, so any code that read
# the budget off this list would be visibly wrong.
_GRADUATED_STEPS = [
    {"tool": "web.select", "args": {"selector": "#role", "value": "admin"}},
    {"tool": "web.type", "args": {"ref": 2, "text": "maintenance window"}},
    {"tool": "web.click", "args": {"ref": 1}},
]


def _navigate_result(flow):
    """The ``tool_result`` frame ``_observe_flow_binding`` reads."""
    return {
        "type": "tool_result",
        "tool_name": "web.navigate",
        "call_id": "call-nav",
        "status": "success",
        "data": {"url": f"{_GRADUATED_FLOW['origin']}/login", "flow": flow},
    }


class TestGraduatedFlowReplay:
    """R-5: a graduated browser executable flow binds and one-gates through the
    SPEC-051 path that already shipped — no new executor anywhere in the chain.

    The claim is *indistinguishability*. Once ingested, a graduated flow is an
    ordinary ``web_target`` + ``risk_class: write`` skill, and its ``steps``
    list is the replay contract the **agent** follows under the single gate,
    not an input to the gate. Were it an input, a skill author could widen
    their own blast radius by writing a longer step list — which is why the
    assertions below compare whole payloads rather than spot-checking fields.
    """

    def _kernel(self, **overrides):
        kwargs = dict(
            api_key="test-key",
            execution_signing_key=FLOW_SIGNING_KEY,
            browser_flow_approval_ttl=900,
            hitl_confirm_timeout=600,
        )
        kwargs.update(overrides)
        return AgentKernel(settings=RuntimeSettings(**kwargs))

    def test_a_graduated_binding_records_the_context_a_declaration_records(self):
        """The kernel's single population point cannot tell the two apart.

        Asserted twice over, because either half alone leaves a way in: the
        context recorded from a graduated binding equals the one a
        hand-authored declaration produces, *and* injecting keys the gateway's
        flow envelope should not carry — which today's gateway does not do for
        ``kind``/``steps``, but a future one might — changes nothing, because
        ``FlowContextStore.record`` reads eight named keys and drops the rest.

        ``approved`` is injected deliberately and is not hypothetical: the
        gateway really does re-publish it as ``True`` on any later in-flow
        ``web.navigate`` (``to_dict()``'s one call site is gated on a *bound*
        flow, not on this navigate being the one that bound it), after
        interactions have set it. That it cannot reach a ``FlowContext`` is the
        fact that makes the flag inert, so it is pinned rather than documented.
        """
        session_id = "ses-r5-ctx"
        FLOW_CONTEXTS.clear_all()
        AgentKernel._observe_flow_binding(
            _navigate_result(dict(_GRADUATED_FLOW)), session_id
        )
        declared = FLOW_CONTEXTS.get(session_id)

        FLOW_CONTEXTS.clear_all()
        AgentKernel._observe_flow_binding(
            _navigate_result(
                {
                    **_GRADUATED_FLOW,
                    "kind": "executable_flow",
                    "steps": _GRADUATED_STEPS,
                    "approved": True,
                }
            ),
            session_id,
        )
        graduated = FLOW_CONTEXTS.get(session_id)

        assert declared is not None and graduated is not None
        assert graduated.identity() == declared.identity()
        assert graduated.summary() == declared.summary()
        # The budget is the gateway's, not the step list's length (3 != 20).
        assert graduated.max_steps == declared.max_steps == 20
        assert not hasattr(graduated, "kind")
        assert not hasattr(graduated, "steps")
        assert not hasattr(graduated, "approved")

    def test_a_graduated_flow_collapses_to_one_gate_then_signs_each_write(
        self, monkeypatch
    ):
        """Boxes 1 + 6, driving the four functions plan.md §5 names, in order.

        ``_observe_flow_binding`` → one ``flow``-kind card → ``_record_flow_approval``
        → ``_sign_flow_execution``/``build_flow_request``. Nothing new is
        constructed along the way, which *is* the finding: R-5 needed no
        executor, no envelope variant and no guard of its own.
        """
        audits = _capture_flow_audits(monkeypatch)
        FLOW_APPROVALS.clear_all()
        FLOW_CONTEXTS.clear_all()
        kernel = self._kernel()
        session_id = "ses-r5-chain"

        # 1. Bind: the graduated flow arrives on web.navigate's result.
        AgentKernel._observe_flow_binding(
            _navigate_result(dict(_GRADUATED_FLOW)), session_id
        )
        assert FLOW_CONTEXTS.get(session_id) is not None

        # 2. Park: the flow's first write collapses to ONE flow-kind card.
        toolkit = _fake_toolkit(
            ("web_select", "web.select", "write"),
            ("web_type", "web.type", "write"),
            ("web_click", "web.click", "write"),
        )
        frame = kernel._build_confirmation_frame(
            RequireUserConfirmEvent(
                reply_id="reply-1",
                tool_calls=[
                    ToolCallBlock(
                        id="call-1", name="web_select",
                        input='{"selector": "#role", "value": "admin"}',
                    )
                ],
            ),
            session_id,
            "alice",
            toolkit=toolkit,
        )
        assert frame is not None
        assert frame["approval_kind"] == "flow"
        assert frame["flow_summary"]["title"] == _GRADUATED_FLOW["title"]
        assert frame["flow_summary"]["risk_class"] == "write"
        # One gate for the whole flow: the card names the step being unlocked,
        # not the three-step contract behind it.
        assert len(frame["pending_calls"]) == 1
        assert "steps" not in json.dumps(frame["flow_summary"])

        # 3. Approve: the one decision arms the session's flow authority.
        pending = CONFIRMATION_REGISTRY.peek_parked(session_id)
        assert pending is not None
        assert FLOW_APPROVALS.get(session_id) is None  # not armed before
        kernel._record_flow_approval(pending, "bob-approver", session_id)
        approval = FLOW_APPROVALS.get(session_id)
        assert approval is not None
        assert approval.identity() == FLOW_CONTEXTS.get(session_id).identity()

        # 4. Replay: every subsequent write auto-signs under that one decision.
        requests: dict = {}
        envelopes = [
            _run_signer(
                kernel,
                ToolCallBlock(
                    id=call_id, name=sanitized, input=json.dumps(arguments)
                ),
                gateway_name,
                session_id,
                requests,
            )
            for call_id, sanitized, gateway_name, arguments in (
                ("call-2", "web_type", "web.type", {"ref": 2, "text": "window"}),
                ("call-3", "web_click", "web.click", {"ref": 1}),
            )
        ]

        assert all(envelope is not None for envelope in envelopes)
        first, second = envelopes
        for envelope in (first, second):
            assert envelope["approval_kind"] == "flow"
            # One operator decision per flow (ADR-0007): both reuse the
            # approving card's correlation and identity.
            assert envelope["confirm_id"] == pending.confirm_id
            assert envelope["owner_user_id"] == "alice"
            assert envelope["decider_user_id"] == "bob-approver"
            assert verify_envelope(
                envelope, envelope["signature"], FLOW_SIGNING_KEY
            )
        # ...but each write is still its own execution, with its own digest.
        assert first["execution_id"] != second["execution_id"]
        assert first["args_digest"] == canonical_digest({"ref": 2, "text": "window"})
        assert second["args_digest"] == canonical_digest({"ref": 1})
        # Injected by call_id, so the tool closure verifies and hands each off
        # exactly like a card-approved call.
        assert requests["call-2"] is first
        assert requests["call-3"] is second
        # Durable + audited per write, exactly like a card-signed request.
        rows = EXECUTION_RECORD_STORE.load_for_session(session_id)
        assert [row["status"] for row in rows] == ["requested", "requested"]
        assert {row["execution_id"] for row in rows} == {
            first["execution_id"], second["execution_id"]
        }
        requested = [a for a in audits if a["event_type"] == "execution_requested"]
        assert len(requested) == 2
        # And each joins the same ordered trace R-2 captures (SPEC-055 R-2),
        # so a replay is itself graduable.
        traced = AUTHORING_TRACE_STORE.load_for_session(session_id)
        assert [step["tool_name"] for step in traced] == ["web.type", "web.click"]

    def test_an_infra_executable_flow_step_parks_per_action(self, monkeypatch):
        """Box 7: the OQ-2 safe fallback, asserted rather than delivered.

        An infra executable flow (``kind: executable_flow``, ``k8s.*`` steps,
        no ``web_target``) has no binding seam at all — ``web.navigate`` is the
        only one and it refuses ``SKILL_NOT_WEB_FLOW`` — so no authority is
        ever armed and each step parks individually under SPEC-054 R-2. Pinned
        from both ends: the card declares ``action``, and a *live* browser
        authority does not leak onto the infra write.
        """
        _capture_flow_audits(monkeypatch)
        FLOW_APPROVALS.clear_all()
        FLOW_CONTEXTS.clear_all()
        kernel = self._kernel()
        session_id = "ses-r5-infra"
        toolkit = _fake_toolkit(
            ("k8s_scale_deployment", "k8s.scale_deployment", "write")
        )
        event = RequireUserConfirmEvent(
            reply_id="reply-1",
            tool_calls=[
                ToolCallBlock(
                    id="call-1", name="k8s_scale_deployment",
                    input='{"name": "api", "replicas": 3}',
                )
            ],
        )

        frame = kernel._build_confirmation_frame(
            event, session_id, "alice", toolkit=toolkit
        )

        assert frame is not None
        assert frame["approval_kind"] == "action"
        assert "flow_summary" not in frame
        pending = CONFIRMATION_REGISTRY.peek_parked(session_id)
        kernel._record_flow_approval(pending, "bob-approver", session_id)
        # Approving it arms nothing, so the NEXT infra step parks again — one
        # card per step, which is the fallback's whole cost and its whole safety.
        assert FLOW_APPROVALS.get(session_id) is None

    def test_the_flow_signer_refuses_a_non_browser_tool_name(self, monkeypatch):
        """Box 7's other half: the signer enforces its own scope.

        ``_sign_flow_execution``'s contract is "auto-sign one unlocked *browser
        write*". What made that true until now was its single caller —
        ``GatewayPermissionMiddleware`` checks ``BROWSER_WRITE_TOOLS`` before
        consulting the signer (pinned in ``test_kernel_middleware``). Call-site
        discipline is one refactor from a hole: a second caller, or a middleware
        reordering, would let a live browser authority auto-sign an infra
        mutation with no per-action decision behind it — exactly what the OQ-2
        fallback must never do, and the one way an executable flow could
        self-admit a step nobody approved.
        """
        audits = _capture_flow_audits(monkeypatch)
        FLOW_APPROVALS.clear_all()
        FLOW_CONTEXTS.clear_all()
        kernel = self._kernel()
        session_id = "ses-r5-signer-scope"
        # A live, identity-matched browser authority: every precondition the
        # signer checks except the tool's own name.
        _record_authority(session_id)
        _record_context(session_id)
        assert FLOW_APPROVALS.has_approval(session_id)

        requests: dict = {}
        infra = _run_signer(
            kernel,
            ToolCallBlock(
                id="call-infra", name="k8s_scale_deployment",
                input='{"name": "api", "replicas": 5}',
            ),
            "k8s.scale_deployment",
            session_id,
            requests,
        )

        assert infra is None  # fails safe ⇒ the step parks per-action
        # All four side effects the guard sits ahead of, not just the return
        # value: no injected request, no durable execution record, and no
        # ``execution_requested`` audit line describing a request that was
        # never made.
        assert requests == {}
        assert EXECUTION_RECORD_STORE.load_for_session(session_id) == []
        assert audits == []

        # Control: the same authority still signs a browser write, so the
        # refusal above is the tool scope and not a broken signer — and the
        # empty audit list above is a real observation, not a capture that
        # never fired.
        browser = _run_signer(
            kernel,
            ToolCallBlock(id="call-web", name="web_click", input='{"ref": 1}'),
            "web.click",
            session_id,
            requests,
        )
        assert browser is not None
        assert browser["tool_name"] == "web.click"
        assert requests["call-web"] is browser
        assert [a["event_type"] for a in audits] == ["execution_requested"]
        assert audits[0]["details"]["call_id"] == "call-web"


def test_execution_recovery_factory_inert_when_admission_disabled():
    """SPEC-063 R-2a: disabled admission yields no recovery store (legacy path)."""
    kernel = AgentKernel(settings=RuntimeSettings(api_key=None))
    assert kernel.settings.execution_admission_enabled is False
    assert kernel._execution_recovery() is None
    # Repeated calls stay None and never build a store.
    assert kernel._execution_recovery() is None
    assert kernel._recovery_built is False


def test_execution_recovery_factory_builds_and_caches_when_enabled():
    from agent_service.services.execution_recovery import ExecutionRecovery

    kernel = AgentKernel(
        settings=RuntimeSettings(
            api_key=None,
            execution_signing_key="signing-key-1",
            execution_admission_enabled=True,
            execution_state_db_url="postgres://agent@ledger:5432/exec",
            execution_admission_epoch="epoch-7",
        )
    )
    recovery = kernel._execution_recovery()
    assert isinstance(recovery, ExecutionRecovery)
    # Cached: a second call returns the same instance, built once.
    assert kernel._execution_recovery() is recovery
    assert kernel._recovery_built is True


class _FakeRunRecovery:
    """Stand-in for ExecutionRecovery's run-minting surface (no DB)."""

    def __init__(self, *, run_id="run-minted", raise_on_create=None):
        self._run_id = run_id
        self._raise = raise_on_create
        self.create_calls = []

    def create_run(self, session_id, owner_user_id):
        self.create_calls.append((session_id, owner_user_id))
        if self._raise is not None:
            raise self._raise
        return self._run_id


def test_resolve_run_id_inherits_flow_authority_without_minting():
    """SPEC-063 R-4: a reused flow retains its originating run."""
    kernel = AgentKernel(settings=RuntimeSettings(api_key=None))
    recovery = _FakeRunRecovery()
    flow_approval = SimpleNamespace(run_id="run-origin")
    run_id = kernel._resolve_run_id(
        recovery, "ses-1", "alice", flow_approval=flow_approval
    )
    assert run_id == "run-origin"
    assert recovery.create_calls == []  # never minted a replacement


def test_resolve_run_id_mints_for_a_new_root_turn():
    kernel = AgentKernel(settings=RuntimeSettings(api_key=None))
    recovery = _FakeRunRecovery(run_id="run-new")
    run_id = kernel._resolve_run_id(recovery, "ses-1", "alice")
    assert run_id == "run-new"
    assert recovery.create_calls == [("ses-1", "alice")]


def test_resolve_run_id_returns_none_when_store_unavailable():
    """A failed mint yields no identity, so the lane fails closed (never mints)."""
    from agent_service.services.execution_protocol import ProtocolError

    kernel = AgentKernel(settings=RuntimeSettings(api_key=None))
    recovery = _FakeRunRecovery(raise_on_create=ProtocolError("store_unavailable"))
    assert kernel._resolve_run_id(recovery, "ses-1", "alice") is None


def test_bind_guard_carries_the_resolved_run_identity():
    from agent_service.services.execution_run_guard import RunGuard

    kernel = AgentKernel(settings=RuntimeSettings(api_key=None))
    recovery = _FakeRunRecovery()
    guard = kernel._bind_guard(recovery, "run-1", "ses-1", "alice")
    assert isinstance(guard, RunGuard)
    assert guard.run_id == "run-1"
    assert guard.identity.session_id == "ses-1"
    assert guard.identity.owner_user_id == "alice"
    assert guard.stopped() is False


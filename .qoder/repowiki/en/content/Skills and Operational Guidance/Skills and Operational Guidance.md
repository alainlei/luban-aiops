# Skills and Operational Guidance

<cite>
**Referenced Files in This Document**
- [skill-format.md](file://shared/shared-contracts/skill-format.md)
- [skills-guide.md](file://docs/guides/skills-guide.md)
- [validate.py](file://products/skills-hub/src/skills_hub/validate.py)
- [ingestion.py](file://products/skills-hub/src/skills_hub/services/ingestion.py)
- [scoring.py](file://products/skills-hub/src/skills_hub/services/scoring.py)
- [skill_store.py](file://products/skills-hub/src/skills_hub/services/skill_store.py)
- [skills routes](file://products/skills-hub/src/skills_hub/api/routes/skills.py)
- [skills_connector.py](file://products/tool-gateway/src/tool_gateway/tools/skills_connector.py)
- [test_skills_connector.py](file://products/tool-gateway/tests/test_skills_connector.py)
- [skill_graduation.py](file://products/agent-platform/src/agent_service/services/skill_graduation.py)
- [authoring_trace.py](file://products/agent-platform/src/agent_service/services/authoring_trace.py)
- [sessions routes](file://products/platform-gateway/src/platform_gateway/api/routes/sessions.py)
- [gateway_service.py](file://products/platform-gateway/src/platform_gateway/services/gateway_service.py)
- [SRE sample README](file://shared/platform-ops/skills/sre-alerting/README.md)
- [ACME Admin README](file://samples/acme-admin/README.md)
- [health-check skill](file://samples/acme-admin/health-check/skill/CheckServiceHealth.md)
- [user-status skill](file://samples/acme-admin/user-status/skill/CheckUserStatus.md)
- [lock-unlock-user skill](file://samples/acme-admin/lock-unlock-user/skill/LockUnlockUser.md)
- [password-reset skill](file://samples/acme-admin/password-reset/skill/ResetAcmePassword.md)
- [password-reset README](file://samples/acme-admin/password-reset/README.md)
- [password-reset WALKTHROUGH](file://samples/acme-admin/password-reset/WALKTHROUGH.md)
- [adhoc-password-reset skill](file://samples/acme-admin/adhoc-password-reset/skill/ResetPasswordAdHoc.md)
- [adhoc-password-reset README](file://samples/acme-admin/adhoc-password-reset/README.md)
- [adhoc-password-reset WALKTHROUGH](file://samples/acme-admin/adhoc-password-reset/WALKTHROUGH.md)
- [demo-suite.sh](file://samples/acme-admin/demo-suite.sh)
- [SPEC-066 spec](file://docs/specs/SPEC-066-skill-retrieval-ranking-fidelity/spec.md)
- [SPEC-066 plan](file://docs/specs/SPEC-066-skill-retrieval-ranking-fidelity/plan.md)
- [SPEC-066 tasks](file://docs/specs/SPEC-066-skill-retrieval-ranking-fidelity/tasks.md)
- [SPEC-066 delivery release note](file://docs/agentic-aiops-platform/release-notes/2026-10-03-spec-066-skill-retrieval-ranking-fidelity.md)
- [test_parity.py](file://products/skills-hub/tests/test_parity.py)
- [test_evaluation.py](file://products/skills-hub/tests/test_evaluation.py)
- [conftest.py](file://products/skills-hub/tests/conftest.py)
- [eval_harness.py](file://products/skills-hub/tests/support/eval_harness.py)
- [corpus.py](file://products/skills-hub/tests/support/corpus.py)
</cite>

## Update Summary
**Changes Made**
- Updated the skills hub service documentation to reflect SPEC-066 delivery: enhanced lexical ranking fidelity with four measured fixes (skill_id scoring, corpus-derived IDF weighting, sublinear body-length normalization, and query-side CamelCase splitting)
- Added comprehensive coverage of the new evaluation framework including R-8 merge gate with real PostgreSQL measurement through the prefilter path
- Documented the enforced cross-backend parity harness (R-6) that ensures byte-identical ordering and scores across InMemory and Postgres backends
- Updated search and ranking section with new scoring algorithm details, CorpusStats persistence, and de-duplication guardrail
- Enhanced troubleshooting guide with SPEC-066-specific issues including index migration and parity test failures
- Updated performance considerations to reflect GIN index changes and latency measurements on real PostgreSQL 16

## Table of Contents
1. [Introduction](#introduction)
2. [Project Structure](#project-structure)
3. [Core Components](#core-components)
4. [Architecture Overview](#architecture-overview)
5. [Detailed Component Analysis](#detailed-component-analysis)
6. [Dependency Analysis](#dependency-analysis)
7. [Performance Considerations](#performance-considerations)
8. [Troubleshooting Guide](#troubleshooting-guide)
9. [Conclusion](#conclusion)
10. [Appendices](#appendices)

## Introduction
This document explains the skills system that enables team-owned operational guidance in Markdown format. It covers the complete lifecycle from authoring drafts through validation, testing, graduation to production, and consumption by agents during operations. It also documents the skill format specification, the skills-hub service that ingests and serves skills, the graduation workflow with quality gates, common patterns, best practices, and integration with the agent runtime for grounded responses.

The system now includes comprehensive examples through the ACME Admin sample application, which demonstrates a complete approval model triad: health checks (read-only HTTP), user status verification (browser-based read), user account locking (action card), password resets (flow card), ad-hoc per-action approval, and develop-as-you-go skill graduation. These examples provide concrete implementations of abstract concepts and serve as templates for creating new skills.

**Updated** The skills system now supports conversational-first interactions where operators can ask for guidance naturally without needing to know or specify exact skill IDs. The agent uses `skills.search` to find relevant runbooks based on intent rather than requiring explicit naming.

**Updated** With SPEC-066 delivery, the skills-hub service now features enhanced lexical ranking fidelity with four measured improvements: skill_id slug scoring, corpus-derived IDF weighting, sublinear body-length normalization, and query-side CamelCase splitting. These changes improve search accuracy while maintaining byte-identical results across different storage backends through an enforced parity harness.

## Project Structure
The skills system spans several components:
- Skill format contract defines the Markdown + YAML frontmatter schema consumed by ingestion.
- skills-hub ingests skills from local directories or Git repositories, validates them, stores them, and exposes search/list/get endpoints with enhanced ranking.
- tool-gateway exposes read-only skills tools to agents (skills.search, skills.get, skills.list).
- agent-platform captures approved authoring traces and supports drafting and graduating executable-flow skills.
- platform-gateway enforces policy and proxies draft/graduation requests to the agent service.
- ACME Admin sample application provides six complete skill examples demonstrating different approval models and patterns.

```mermaid
graph TB
subgraph "Authoring"
A["Team skill sources<br/>Markdown + frontmatter"]
B["ACME Admin Samples<br/>Six skill patterns"]
end
subgraph "Ingestion & Storage"
C["skills-hub<br/>ingest_directory()"]
D["Skill store<br/>InMemory / Postgres"]
E["Scorer<br/>rank(), score() with IDF"]
F["CorpusStats<br/>Sync-time statistics"]
end
subgraph "Consumption"
G["tool-gateway<br/>skills.* tools"]
H["Agent runtime"]
end
subgraph "Graduation"
I["agent-platform<br/>skill_graduation.py"]
J["platform-gateway<br/>sessions routes"]
end
subgraph "Evaluation & Testing"
K["Parity Harness<br/>test_parity.py"]
L["Evaluation Framework<br/>test_evaluation.py"]
M["Real PostgreSQL<br/>conftest.py"]
end
A --> C --> D
B --> C
D --> E
E --> F
G --> D
H --> G
J --> I
I --> A
K --> D
L --> D
M --> K
```

**Diagram sources**
- [ingestion.py:476-559](file://products/skills-hub/src/skills_hub/services/ingestion.py#L476-L559)
- [skill_store.py:158-200](file://products/skills-hub/src/skills_hub/services/skill_store.py#L158-L200)
- [scoring.py:33-97](file://products/skills-hub/src/skills_hub/services/scoring.py#L33-L97)
- [skills_connector.py:219-250](file://products/tool-gateway/src/tool_gateway/tools/skills_connector.py#L219-L250)
- [skill_graduation.py:587-664](file://products/agent-platform/src/agent_service/services/skill_graduation.py#L587-L664)
- [sessions routes:267-322](file://products/platform-gateway/src/platform_gateway/api/routes/sessions.py#L267-L322)
- [test_parity.py:1-151](file://products/skills-hub/tests/test_parity.py#L1-L151)
- [test_evaluation.py:1-483](file://products/skills-hub/tests/test_evaluation.py#L1-L483)

**Section sources**
- [skills-guide.md:12-35](file://docs/guides/skills-guide.md#L12-L35)
- [skill-store.py:1-67](file://products/skills-hub/src/skills_hub/services/skill_store.py#L1-L67)
- [ACME Admin README:18-36](file://samples/acme-admin/README.md#L18-L36)

## Core Components
- Skill Format v2: Markdown with YAML frontmatter; optional executable-flow steps; strict validation rules and size caps.
- Ingestion pipeline: walks source directories, parses frontmatter, validates against the contract, builds records, and returns rejections.
- Store backends: in-memory for dev/test; PostgreSQL for production with full-text search index and per-source atomic replacement.
- **Enhanced Search and Ranking**: deterministic keyword scoring with title/tag/body/skill_id weights, corpus-derived IDF weighting, sublinear body-length normalization, and query-side CamelCase splitting.
- Agent tools: read-only skills tools exposed via tool-gateway, returning ranked matches and evidence.
- Graduation: deterministic rendering of an approved authoring trace into an executable-flow skill draft with blast-radius re-validation and human merge.
- **Evaluation Framework**: R-8 merge gate with real PostgreSQL measurement through the prefilter path, ensuring shipped behavior matches measured outcomes.
- **Cross-Backend Parity**: R-6 enforced harness ensuring byte-identical ordering and scores across InMemory and Postgres backends.
- Sample applications: ACME Admin provides six complete skill examples demonstrating different approval models including flow cards, action cards, and graduation workflows.

**Section sources**
- [skill-format.md:1-203](file://shared/shared-contracts/skill-format.md#L1-L203)
- [ingestion.py:1-113](file://products/skills-hub/src/skills_hub/services/ingestion.py#L1-L113)
- [skill_store.py:158-200](file://products/skills-hub/src/skills_hub/services/skill_store.py#L158-L200)
- [scoring.py:1-336](file://products/skills-hub/src/skills_hub/services/scoring.py#L1-L336)
- [skills_connector.py:219-250](file://products/tool-gateway/src/tool_gateway/tools/skills_connector.py#L219-L250)
- [skill_graduation.py:1-42](file://products/agent-platform/src/agent_service/services/skill_graduation.py#L1-L42)

## Architecture Overview
Skills flow from team-authored Markdown into a validated catalog, then are consumed by agents through gateway tools. Executable flows can be graduated from approved session traces into production-ready skills after quality gates. The ACME Admin sample demonstrates how different approval models integrate with this architecture.

**Updated** The architecture now includes enhanced evaluation and parity testing infrastructure that ensures the improved lexical ranking works correctly across all storage backends.

```mermaid
sequenceDiagram
participant Author as "Author"
participant ACME as "ACME Samples"
participant Hub as "skills-hub"
participant Store as "Skill Store"
participant Scorer as "Enhanced Scorer"
participant GW as "tool-gateway"
participant Agent as "Agent runtime"
participant PlatGW as "platform-gateway"
participant AgentSvc as "agent-service"
participant Eval as "Evaluation Framework"
Author->>Hub : Sync local dir or git repo
ACME->>Hub : Deploy sample skills
Hub->>Hub : ingest_directory() validate_document()
Hub->>Store : replace_source(source_id, records)
Store->>Scorer : compute_stats() refresh_statistics()
Agent->>GW : skills.search(q, limit)
GW->>Hub : GET /api/v1/skills/search
Hub->>Store : search(query, limit)
Store->>Scorer : rank(query, candidates, stats)
Scorer-->>Store : ranked hits with IDF weighting
Store-->>Hub : ranked hits
Hub-->>GW : matches + total
GW-->>Agent : ToolResult(matches, evidence)
Note over Author,Store : Executable flows graduate later
Author->>PlatGW : POST /sessions/{id}/skill-graduate
PlatGW->>AgentSvc : graduate_session_skill(...)
AgentSvc->>AgentSvc : revalidate_blast_radius()
AgentSvc-->>PlatGW : draft markdown (human review)
Note over Eval,Store : Evaluation runs through real PostgreSQL
Eval->>Store : search() with prefilter in path
Store-->>Eval : measured results
```

**Diagram sources**
- [ingestion.py:476-559](file://products/skills-hub/src/skills_hub/services/ingestion.py#L476-L559)
- [skill_store.py:417-443](file://products/skills-hub/src/skills_hub/services/skill_store.py#L417-L443)
- [skills routes:99-146](file://products/skills-hub/src/skills_hub/api/routes/skills.py#L99-L146)
- [skills_connector.py:219-250](file://products/tool-gateway/src/tool_gateway/tools/skills_connector.py#L219-L250)
- [skill_graduation.py:217-497](file://products/agent-platform/src/agent_service/services/skill_graduation.py#L217-L497)
- [sessions routes:267-322](file://products/platform-gateway/src/platform_gateway/api/routes/sessions.py#L267-L322)
- [test_evaluation.py:428-483](file://products/skills-hub/tests/test_evaluation.py#L428-L483)

## Detailed Component Analysis

### Skill Format Specification
- Frontmatter keys include title, description, tags, version, source_url, web_target, risk_class, flow_intent, kind, steps. Unknown keys are rejected.
- Size caps: body ≤ 64 KiB; description ≤ 500 chars; ≤ 10 tags; steps ≤ 200 and ≤ 64 KiB serialized.
- Identity: skill_id = <source_id>/<slug>, slug derived from file path; duplicate slugs within one source are rejected; README.md and NOTICE files are skipped.
- Executable-flow class: kind=executable_flow requires non-empty steps and risk_class=write; any web.* step requires web_target; credential values must be references, never literals.

```mermaid
flowchart TD
Start(["Validate frontmatter"]) --> Parse["Parse YAML frontmatter"]
Parse --> Keys{"Unknown keys?"}
Keys --> |Yes| RejectKeys["Reject: unknown keys"]
Keys --> |No| Required["Check required fields"]
Required --> Lengths{"Lengths OK?"}
Lengths --> |No| RejectLen["Reject: length exceeded"]
Lengths --> Steps{"kind=executable_flow?"}
Steps --> |Yes| StepsCheck["Validate steps list<br/>risk_class=write<br/>web.* needs web_target"]
Steps --> |No| Body["Check body size"]
StepsCheck --> Body
Body --> Done(["Accept or reject"])
```

**Diagram sources**
- [skill-format.md:31-147](file://shared/shared-contracts/skill-format.md#L31-L147)
- [ingestion.py:149-276](file://products/skills-hub/src/skills_hub/services/ingestion.py#L149-L276)
- [ingestion.py:375-460](file://products/skills-hub/src/skills_hub/services/ingestion.py#L375-L460)

**Section sources**
- [skill-format.md:31-147](file://shared/shared-contracts/skill-format.md#L31-L147)
- [ingestion.py:149-276](file://products/skills-hub/src/skills_hub/services/ingestion.py#L149-L276)
- [ingestion.py:375-460](file://products/skills-hub/src/skills_hub/services/ingestion.py#L375-L460)

### Ingestion and Validation Pipeline
- The CLI uses the same code path as sync time: python -m skills_hub.validate <directory>.
- ingest_directory walks *.md files, skips hidden segments and base names, derives slugs, validates frontmatter and steps, deduplicates slugs per source, and builds Skill records.
- Rejections are reported per document with reasons; accepted records form a snapshot replaced atomically per source.

```mermaid
flowchart TD
S(["Start sync"]) --> Walk["Walk root/*.md"]
Walk --> Skip{"Skip README/NOTICE or hidden?"}
Skip --> |Yes| Next["Next file"]
Skip --> |No| Slug["Derive slug from path"]
Slug --> Read["Read UTF-8 text"]
Read --> Validate["validate_document()"]
Validate --> Valid{"Valid?"}
Valid --> |No| Reject["Add rejection"]
Valid --> |Yes| Dedup{"Duplicate slug?"}
Dedup --> |Yes| Reject
Dedup --> |No| Record["Build Skill record"]
Record --> Next
Next --> End(["Return IngestResult"])
```

**Diagram sources**
- [ingestion.py:476-559](file://products/skills-hub/src/skills_hub/services/ingestion.py#L476-L559)
- [validate.py:23-43](file://products/skills-hub/src/skills_hub/validate.py#L23-L43)

**Section sources**
- [validate.py:1-48](file://products/skills-hub/src/skills_hub/validate.py#L1-L48)
- [ingestion.py:476-559](file://products/skills-hub/src/skills_hub/services/ingestion.py#L476-L559)

### Enhanced Search, Ranking, and Retrieval API
**Updated** The search and ranking system has been significantly enhanced with SPEC-066's four measured lexical fixes:

- **Search endpoint**: GET /api/v1/skills/search?q=... with optional source/tag filters and capped limit.
- **Four Measured Fixes**:
  - **R-1**: Score the `skill_id` slug at tag weight (×2) for identifier-owner recovery
  - **R-2**: Corpus-derived IDF weighting using `ln((1+N)/(1+df))+1` formula
  - **R-3**: Sublinear body-length normalization `1/log2(2 + len(body)/1000)`
  - **R-4**: Query-side CamelCase splitting while keeping document side unsplit
- **Deterministic Ranking**: Tokenized query scored against title (×3), tags (×2), skill_id (×2), body occurrences (×1, capped), with corpus-derived IDF scaling and bounded excerpts. Zero-score results excluded; ties broken by skill_id ascending.
- **Postgres Backend**: Pre-filters candidates using tsvector with widened expression covering skill_id, then re-ranks in Python to match in-memory behavior.
- **De-duplication Guardrail**: R-7 collapses byte-identical bodies before sorting and truncation, retaining lowest skill_id.

```mermaid
classDiagram
class Scoring {
+tokenize(text) list[str]
+tokenize_query(query) list[str]
+score(query, skill, stats) float
+excerpt(query, skill) str
+rank(query, records, limit, stats) list[SearchHit]
+compute_stats(skills) CorpusStats
+body_md5(skill) str
}
class CorpusStats {
+n : int
+df : Mapping[str, int]
+idf(token) float
}
class SkillStore {
+search(query, limit, source, tag) list[SearchHit]
+list(offset, limit, source, tag) tuple[list[Skill], int]
+get(skill_id) Skill?
+refresh_statistics() None
}
Scoring <.. SkillStore : "used by"
CorpusStats --> Scoring : "passed to score/rank"
```

**Diagram sources**
- [scoring.py:28-336](file://products/skills-hub/src/skills_hub/services/scoring.py#L28-L336)
- [skill_store.py:137-145](file://products/skills-hub/src/skills_hub/services/skill_store.py#L137-L145)
- [skill_store.py:417-443](file://products/skills-hub/src/skills_hub/services/skill_store.py#L417-L443)

**Section sources**
- [skills routes:99-146](file://products/skills-hub/src/skills_hub/api/routes/skills.py#L99-L146)
- [scoring.py:1-336](file://products/skills-hub/src/skills_hub/services/scoring.py#L1-L336)
- [skill_store.py:158-200](file://products/skills-hub/src/skills_hub/services/skill_store.py#L158-L200)

### Agent Consumption via tool-gateway
- tool-gateway registers three read-only skills tools: skills.search, skills.get, skills.list.
- On success, returns ToolResult with data and evidence; transport errors return TOOL_EXECUTION_ERROR.
- Tests assert registered tool names, risk_level=read, category=skills, and projected match keys.

```mermaid
sequenceDiagram
participant Agent as "Agent"
participant GW as "tool-gateway"
participant Hub as "skills-hub"
Agent->>GW : invoke("skills.search", {query})
GW->>Hub : GET /api/v1/skills/search?q=...&limit=...
Hub-->>GW : JSON {matches, total}
GW-->>Agent : ToolResult(status="success", data={matches,total}, evidence)
```

**Diagram sources**
- [skills_connector.py:219-250](file://products/tool-gateway/src/tool_gateway/tools/skills_connector.py#L219-L250)
- [test_skills_connector.py:87-135](file://products/tool-gateway/tests/test_skills_connector.py#L87-L135)

**Section sources**
- [skills_connector.py:219-250](file://products/tool-gateway/src/tool_gateway/tools/skills_connector.py#L219-L250)
- [test_skills_connector.py:87-135](file://products/tool-gateway/tests/test_skills_connector.py#L87-L135)

### Evaluation Framework and Cross-Backend Parity
**New Section** SPEC-066 introduces comprehensive evaluation infrastructure to ensure the enhanced ranking works correctly across all storage backends:

#### R-6 Enforced Cross-Backend Parity Harness
- **Purpose**: Ensures byte-identical ordering and numeric scores across InMemory and Postgres backends
- **Implementation**: Real PostgreSQL 16 instance provisioned lazily, failing loudly without Docker
- **Query Set**: Union of 63-query audit pool and 18 authored stratum-C paraphrases (81 distinct queries)
- **Invariant**: Preserved as written — no narrowing for semantic retrieval since this is lexical only

#### R-8 Evaluation Merge Gate
- **Purpose**: Re-measures the evaluation against committed label fixture through the Postgres backend
- **Measurement**: Drives store's async `search()` method so the `to_tsvector` prefilter is inside the measured path
- **Baseline**: Frozen V0 baseline (19/38 combined top-1 grade 2) vs shipped scorer (24/38)
- **Significance**: Paired bootstrap over queries (10,000 resamples, seed 20261001) giving 95% CIs on per-query metric deltas

```mermaid
sequenceDiagram
participant Test as "Test Suite"
participant Memory as "InMemorySkillStore"
participant Postgres as "PostgresSkillStore"
participant Harness as "Evaluation Harness"
participant Labels as "Label Fixture"
Test->>Harness : Load graded set (38 queries × 18 docs)
Harness->>Labels : Verify corpus MD5
Test->>Memory : Build store from corpus
Test->>Postgres : Build store from corpus
Harness->>Memory : search(query, depth) for each query
Harness->>Postgres : search(query, depth) for each query
Memory-->>Harness : Ranked results
Postgres-->>Harness : Ranked results
Harness->>Harness : Compare ordering + scores
Harness-->>Test : Assert identical results
```

**Diagram sources**
- [test_parity.py:111-151](file://products/skills-hub/tests/test_parity.py#L111-L151)
- [test_evaluation.py:428-483](file://products/skills-hub/tests/test_evaluation.py#L428-L483)
- [conftest.py:1-29](file://products/skills-hub/tests/conftest.py#L1-L29)

**Section sources**
- [test_parity.py:1-151](file://products/skills-hub/tests/test_parity.py#L1-L151)
- [test_evaluation.py:1-483](file://products/skills-hub/tests/test_evaluation.py#L1-L483)
- [conftest.py:1-29](file://products/skills-hub/tests/conftest.py#L1-L29)
- [eval_harness.py:1-29](file://products/skills-hub/tests/support/eval_harness.py#L1-L29)
- [corpus.py:129-166](file://products/skills-hub/tests/support/corpus.py#L129-L166)

### Graduation Workflow and Quality Gates
- Draft creation: agent-service builds a validated skill draft from a session or incident; validation runs on skills-hub's code path before returning.
- Graduation: deterministic rendering of an approved authoring trace into an executable-flow skill draft with blast-radius re-validation.
- Quality gates enforced at graduation:
  - Step budget check against replay budget.
  - Origin allowlist: every observed browser step origin must match declared target origin.
  - Consistent risk_class=write for executable flows; no read-tier steps in write-class traces.
  - Credential holes refused; secret-literal shapes refused.
  - Steps serialize within capacity limits.
- Human-in-the-loop: the platform never auto-publishes executable mutating skills; operators review and merge into their Git skills repo.

```mermaid
sequenceDiagram
participant Portal as "Portal"
participant PlatGW as "platform-gateway"
participant AgentSvc as "agent-service"
participant Trace as "AuthoringTraceStore"
participant Grad as "skill_graduation"
Portal->>PlatGW : POST /sessions/{id}/skill-graduate
PlatGW->>AgentSvc : graduate_session_skill(...)
AgentSvc->>Trace : load_for_session(id)
Trace-->>AgentSvc : ordered steps + declaration
AgentSvc->>Grad : revalidate_blast_radius(steps, target)
alt Passes all gates
Grad-->>AgentSvc : BlastRadius(graduable=true)
AgentSvc->>Grad : build_executable_flow_draft(steps, report)
Grad-->>AgentSvc : markdown, slug
AgentSvc-->>PlatGW : mode="graduated", details
PlatGW-->>Portal : draft for human review
else Refusal
Grad-->>AgentSvc : BlastRadius(refusals=[...])
AgentSvc-->>PlatGW : 409 with refusal detail
PlatGW-->>Portal : error with step positions
end
```

**Diagram sources**
- [skill_graduation.py:217-497](file://products/agent-platform/src/agent_service/services/skill_graduation.py#L217-L497)
- [skill_graduation.py:587-664](file://products/agent-platform/src/agent_service/services/skill_graduation.py#L587-L664)
- [sessions routes:267-322](file://products/platform-gateway/src/platform_gateway/api/routes/sessions.py#L267-L322)
- [gateway_service.py:607-613](file://products/platform-gateway/src/platform_gateway/services/gateway_service.py#L607-L613)

**Section sources**
- [skill_graduation.py:1-42](file://products/agent-platform/src/agent_service/services/skill_graduation.py#L1-L42)
- [skill_graduation.py:217-497](file://products/agent-platform/src/agent_service/services/skill_graduation.py#L217-L497)
- [skill_graduation.py:587-664](file://products/agent-platform/src/agent_service/services/skill_graduation.py#L587-L664)
- [sessions routes:267-322](file://products/platform-gateway/src/platform_gateway/api/routes/sessions.py#L267-L322)

### ACME Admin Sample Application and Approval Model Triad

**Updated** Enhanced documentation for the ACME Admin sample application demonstrating the complete approval model triad with improved operator guidance for password reset workflows and conversational-first interaction patterns.

The ACME Admin sample application provides a complete demonstration of the skills system through six carefully designed skill patterns that form a progressive learning ladder covering the entire approval model spectrum:

#### Complete Approval Model Triad

| # | Sample | Surface | Effect | Cards | `approval_kind` | Pattern |
|---|---|---|---|---|---|---|
| 1 | [health-check](samples/acme-admin/health-check/) | `http.get` | read | **0** | — | Pure Read |
| 2 | [user-status](samples/acme-admin/user-status/) | bound browser flow | read | **0** | — | Browser Read |
| 3 | [lock-unlock-user](samples/acme-admin/lock-unlock-user/) | `http.post` | write | **1** | `action` | Action Card |
| 4 | [password-reset](samples/acme-admin/password-reset/) | bound browser flow | write | **1** | `flow` | Flow Card |
| 5 | [adhoc-password-reset](samples/acme-admin/adhoc-password-reset/) | unbound browser | write | N | `action` | Per-Action |
| 6 | [skill-graduation](samples/acme-admin/skill-graduation/) | none → graduated | write | N→1 | `action`→`flow` | Graduation |

#### Conversational-First Interaction Patterns

**Updated** The skills system now supports natural, conversational interactions where operators can ask for guidance without needing to know specific skill IDs or technical details.

**How it works:**
- Operators describe outcomes in plain language: "reset alice's acme-admin password to 'TempPass-2026!'"
- The agent uses `skills.search` to find relevant runbooks based on intent
- Skills are discovered automatically through semantic matching rather than explicit naming
- Only essential inputs that cannot be inferred are required from the operator

**When to name skills anyway:**
- Testing scenarios require deterministic reproduction
- Assertions about specific card counts or tool sequences
- When you need to ensure the exact skill is used rather than relying on model selection

#### Pattern 1: Health Check (Pure Read Operation)
The health-check skill demonstrates a purely read-only operation using HTTP GET calls to verify service health. Key characteristics:
- No `risk_class` or `web_target` declarations (purely API-based)
- Zero confirmation cards due to read-only effect
- Uses `http.get` tool with unauthenticated endpoints
- Demonstrates proper error handling for upstream 4xx/5xx responses

**Section sources**
- [health-check skill:1-158](file://samples/acme-admin/health-check/skill/CheckServiceHealth.md#L1-L158)
- [health-check README:1-142](file://samples/acme-admin/health-check/README.md#L1-L142)
- [health-check demo:1-178](file://samples/acme-admin/health-check/demo/demo.sh#L1-L178)

#### Pattern 2: User Status Check (Browser-Based Read)
The user-status skill shows how to perform read-only operations through a browser interface while maintaining zero confirmation cards:
- Declares `web_target` without `risk_class` (treated as read)
- Signs in using `web.fill_credential` (read tier)
- Uses `web.extract` to read rendered table data
- Demonstrates element ID contracts and stable selectors

**Section sources**
- [user-status skill:1-175](file://samples/acme-admin/user-status/skill/CheckUserStatus.md#L1-L175)
- [user-status README:1-150](file://samples/acme-admin/user-status/README.md#L1-L150)
- [user-status demo:1-185](file://samples/acme-admin/user-status/demo/demo.sh#L1-L185)

#### Pattern 3: Lock/Unlock User (Action Card)
The lock-unlock-user skill demonstrates write operations that require explicit approval through action cards:
- Declares `risk_class: write` without browser flow
- Parks exactly one `action` type confirmation card
- Uses `http.post` for direct API mutations
- Shows proper credential handling via `credential_set`

**Section sources**
- [lock-unlock-user skill:1-186](file://samples/acme-admin/lock-unlock-user/skill/LockUnlockUser.md#L1-L186)
- [lock-unlock-user README:1-152](file://samples/acme-admin/lock-unlock-user/README.md#L1-L152)

#### Pattern 4: Password Reset (Flow Card)
The password-reset skill demonstrates complex browser workflows requiring flow-level approval:
- Binds a browser flow with `web_target` and `risk_class: write`
- Parks one `flow` type confirmation card covering multiple interactions
- Uses `flow_intent` to describe the operator-facing intent
- Demonstrates one-time secret handling and cross-surface verification

**Updated** Enhanced operator guidance with detailed walkthrough showing the difference between bound flow approval and the mutation-focused gate placement.

**Section sources**
- [password-reset skill:1-222](file://samples/acme-admin/password-reset/skill/ResetAcmePassword.md#L1-L222)
- [password-reset README:1-171](file://samples/acme-admin/password-reset/README.md#L1-L171)
- [password-reset WALKTHROUGH:1-366](file://samples/acme-admin/password-reset/WALKTHROUGH.md#L1-L366)

#### Pattern 5: Ad-Hoc Password Reset (Per-Action Approval)
The adhoc-password-reset skill demonstrates the unbound, per-action HITL approval model:
- **No `web_target` declaration** - intentionally stays unbound
- Each write-tier interaction parks its own per-action change-request card
- Uses `web.fill_credential` by reference (SPEC-054 R-2 relaxation)
- Demonstrates credential safety in unbound context
- Shows change-request projections with masked secrets

**Updated** Improved operator guidance explaining the differences between per-action and flow-based approval models, with clear examples of when to use each approach.

**Section sources**
- [adhoc-password-reset skill:1-230](file://samples/acme-admin/adhoc-password-reset/skill/ResetPasswordAdHoc.md#L1-L230)
- [adhoc-password-reset README:1-157](file://samples/acme-admin/adhoc-password-reset/README.md#L1-L157)
- [adhoc-password-reset WALKTHROUGH:1-298](file://samples/acme-admin/adhoc-password-reset/WALKTHROUGH.md#L1-L298)

#### Pattern 6: Skill Graduation (Develop-as-You-Go)
The skill-graduation sample demonstrates the complete graduation workflow end-to-end:
- **No initial skill** - the skill is the artifact produced by the demo
- Authors ad-hoc with per-action approvals, then graduates to one-gate replay
- Captures authoring trace during ad-hoc work
- Re-validates blast radius and renders executable-flow draft
- Demonstrates human-in-the-loop merge process

**Section sources**
- [skill-graduation README:1-238](file://samples/acme-admin/skill-graduation/README.md#L1-L238)

#### Cross-Skill Verification
The demo suite demonstrates how mutations made through one skill can be verified through another, proving that both surfaces access the same underlying store:

```mermaid
sequenceDiagram
participant LUL as "LockUnlockUser"
participant US as "UserStatus"
participant Store as "Shared Store"
LUL->>Store : http.post /api/users/{id}/lock
Store-->>LUL : revision bump
US->>Store : web.extract #user-row-{id}
Store-->>US : locked status + revision
Note over LUL,US : Same revision proves single store
```

**Diagram sources**
- [demo-suite.sh:139-224](file://samples/acme-admin/demo-suite.sh#L139-L224)

**Section sources**
- [ACME Admin README:18-36](file://samples/acme-admin/README.md#L18-L36)
- [demo-suite.sh:1-289](file://samples/acme-admin/demo-suite.sh#L1-L289)

### Integration with Agent Runtime for Grounded Responses
- Agents consume skills through read-only tools; successful tool calls surface cited guidance chips in the portal.
- Evidence panels capture reads and provenance; search results include excerpt and full provenance for citations.
- For executable flows, graduation produces a draft that operators merge into a skills repo; ingestion validates it and makes it available for grounding and replay under policy.
- ACME Admin samples demonstrate how different approval models integrate with the agent runtime, from simple health checks to complex browser workflows with multi-step approvals.

**Section sources**
- [skills-guide.md:294-336](file://docs/guides/skills-guide.md#L294-L336)
- [skills routes:99-146](file://products/skills-hub/src/skills_hub/api/routes/skills.py#L99-L146)
- [skills_connector.py:219-250](file://products/tool-gateway/src/tool_gateway/tools/skills_connector.py#L219-L250)

## Dependency Analysis
- skills-hub depends on:
  - Ingestion module for parsing and validating skills.
  - **Enhanced scorer** for deterministic ranking with IDF weighting and CamelCase splitting.
  - Store backends (in-memory or PostgreSQL) for persistence and retrieval.
  - **Evaluation framework** for parity testing and measurement through real PostgreSQL.
- tool-gateway depends on skills-hub via HTTP for skills tools.
- agent-platform depends on authoring trace store and graduation logic to produce executable-flow drafts.
- platform-gateway enforces policy and proxies to agent-service for draft/graduation endpoints.
- ACME Admin samples depend on skills-hub for skill ingestion and tool-gateway for execution.

```mermaid
graph LR
Ing["ingestion.py"] --> Sch["schemas/skill.schema.json"]
Ing --> Store["skill_store.py"]
Store --> Score["scoring.py (enhanced)"]
Store --> Stats["CorpusStats (sync-time)"]
Tools["skills_connector.py"] --> Store
PlatGW["platform-gateway sessions routes"] --> AgentSvc["agent-service skill_graduation.py"]
AgentSvc --> Trace["authoring_trace.py"]
ACME["ACME Samples"] --> Ing
Eval["evaluation framework"] --> Store
Parity["parity harness"] --> Store
```

**Diagram sources**
- [ingestion.py:1-113](file://products/skills-hub/src/skills_hub/services/ingestion.py#L1-L113)
- [skill_store.py:1-67](file://products/skills-hub/src/skills_hub/services/skill_store.py#L1-L67)
- [scoring.py:1-336](file://products/skills-hub/src/skills_hub/services/scoring.py#L1-L336)
- [skills_connector.py:219-250](file://products/tool-gateway/src/tool_gateway/tools/skills_connector.py#L219-L250)
- [sessions routes:267-322](file://products/platform-gateway/src/platform_gateway/api/routes/sessions.py#L267-L322)
- [skill_graduation.py:587-664](file://products/agent-platform/src/agent_service/services/skill_graduation.py#L587-L664)
- [authoring_trace.py:1-48](file://products/agent-platform/src/agent_service/services/authoring_trace.py#L1-L48)

**Section sources**
- [skill_store.py:1-67](file://products/skills-hub/src/skills_hub/services/skill_store.py#L1-L67)
- [skills_connector.py:219-250](file://products/tool-gateway/src/tool_gateway/tools/skills_connector.py#L219-L250)
- [skill_graduation.py:587-664](file://products/agent-platform/src/agent_service/services/skill_graduation.py#L587-L664)
- [authoring_trace.py:1-48](file://products/agent-platform/src/agent_service/services/authoring_trace.py#L1-L48)

## Performance Considerations
- **Search performance**: Postgres uses GIN tsvector index on title||body with skill_id included; tags filtered separately due to STABLE functions; final ranking done in Python for determinism.
- **Index Migration**: New `idx_skills_search_v2` replaces old index (+8,192 bytes at 18 rows); old index retained for one release.
- **Measured Latency**: End-to-end search latency on Postgres path is p50 19.077 ms / p95 24.849 ms, well within tool-gateway's 10.0 s timeout.
- **Limits**: search limit capped at 20; list limit capped at 100; excerpts bounded to 400 chars; steps capped at 200 and 64 KiB serialized.
- **Ingestion**: atomic per-source replacement ensures readers always see consistent snapshots; failed syncs do not poison healthy sources.
- **IDF Statistics**: Computed in Python at sync time over whole catalog; refresh is full catalog pass but cheap against sync's git clone.
- **Graduation**: blast-radius checks run before rendering to avoid producing un-replayable artifacts; large arguments elided in runbook to respect body cap.
- **Evaluation**: R-8 measures through real PostgreSQL with prefilter in path; R-6 parity harness fails loudly without Docker.
- ACME Admin samples demonstrate performance considerations including connection pooling, response caching, and efficient browser automation.

## Troubleshooting Guide
- New/revised skill not visible: wait one sync interval or restart deployment; verify ConfigMap wiring for local sources.
- Source reports rejections: inspect status endpoint for per-document reasons; fix frontmatter or steps per contract.
- Git source errors mention auth or subpath: update SKILLS_GIT_TOKENS or correct configured path; previous snapshot remains served.
- Search returns no matches: use skills.list to confirm existence; check status and sync outcomes.
- kustomize build fails: align kustomization.yaml keys with actual files under skills directory.
- Agent claims no skills exist: verify GATEWAY_SKILLS_SERVICE_URL and query-secret match.
- ACME Admin samples fail: check credential synchronization, browser sidecar status, and network policies.
- **Updated**: After web-checks migration, ensure all browser samples point to acme-admin instead of the retired static target.
- **SPEC-066 Specific Issues**:
  - **Index migration needed**: Run database migration to create `idx_skills_search_v2`; old index retained for rollback safety.
  - **Parity test failures**: Ensure real PostgreSQL 16 is available; tests fail loudly without Docker rather than skipping.
  - **Evaluation harness failures**: Check that corpus MD5 matches label fixture; verify PostgreSQL connectivity for PostgresPath tests.
  - **Ranking changes**: The four measured fixes may change result ordering; review new IDF weighting and CamelCase splitting effects.
  - **Statistics staleness**: If IDF statistics appear stale, verify sync cycle completed successfully and `refresh_statistics()` was called.

**Section sources**
- [skills-guide.md:338-374](file://docs/guides/skills-guide.md#L338-L374)

## Conclusion
The skills system provides a robust, team-owned operational guidance model with clear contracts, deterministic ingestion and search, safe agent consumption, and a high-trust graduation pathway for executable flows. By enforcing strict validation, blast-radius re-validation, and human-in-the-loop merges, it balances agility with safety, enabling grounded responses during operations while preserving auditability and reproducibility.

**Updated** The enhanced skills system now supports conversational-first interactions where operators can ask for guidance naturally without needing to know specific skill IDs. The improved operator guidance for password reset workflows demonstrates the complete approval model triad—from simple health checks to complex browser workflows with multi-step approvals, ad-hoc per-action approval, and develop-as-you-go skill graduation. 

**Updated** With SPEC-066 delivery, the skills-hub service now features enhanced lexical ranking fidelity with four measured improvements that move combined top-1 correctness from 0.500 to 0.711, while maintaining byte-identical results across different storage backends through an enforced parity harness. The comprehensive evaluation framework ensures these improvements work correctly through the real PostgreSQL path, providing confidence in the enhanced search capabilities.

## Appendices

### Skill Lifecycle Summary
- Authoring: create Markdown skill with frontmatter; validate locally with CLI.
- Ingestion: skills-hub syncs sources, validates documents, stores records.
- **Statistics Refresh**: CorpusStats computed at sync time with corpus-derived IDF weighting.
- **Enhanced Ranking**: Four measured fixes applied: skill_id scoring, IDF weighting, length normalization, CamelCase splitting.
- Consumption: agents call skills tools; results include provenance and excerpts.
- **Evaluation**: R-8 merge gate measures through real PostgreSQL; R-6 parity harness ensures backend consistency.
- Graduation: approve session trace, re-validate blast radius, render draft, merge into repo.
- Production: merged skill ingested and available for grounding and replay under policy.
- Testing: ACME Admin samples provide comprehensive test suites for each skill pattern.

**Section sources**
- [skills-guide.md:12-35](file://docs/guides/skills-guide.md#L12-L35)
- [skill-format.md:1-203](file://shared/shared-contracts/skill-format.md#L1-L203)
- [skill_graduation.py:217-497](file://products/agent-platform/src/agent_service/services/skill_graduation.py#L217-L497)

### ACME Admin Sample Deployment and Usage

**Updated** Enhanced deployment and usage instructions with improved operator guidance for password reset workflows and conversational interaction patterns.

#### Prerequisites
- Platform deployed with browser-dev and mutating-dev runtime profiles
- ACME Admin application deployed (`make deploy-sample-app`)
- Browser credentials synchronized (`sync-browser-credentials.sh`)
- Skills installed (`make deploy-samples`)

#### Running the Demo Suite
```bash
# Run all six skill demonstrations in order
RUN_CHAT_LEG=true samples/acme-admin/demo-suite.sh

# Run individual skill demos
samples/acme-admin/health-check/demo/demo.sh
samples/acme-admin/user-status/demo/demo.sh
samples/acme-admin/lock-unlock-user/demo/demo.sh
samples/acme-admin/password-reset/demo/demo.sh
samples/acme-admin/adhoc-password-reset/demo/demo.sh
samples/acme-admin/skill-graduation/demo/demo.sh
```

#### Key Features Demonstrated
- **Zero-card read operations**: Health checks and user status verification
- **Action cards**: Single-operation mutations requiring explicit approval
- **Flow cards**: Complex browser workflows with multi-step approvals
- **Per-action approval**: Unbound browser interactions with individual gating
- **Skill graduation**: Develop-as-you-go workflow from ad-hoc to reusable flow
- **Cross-skill verification**: Proving mutations across different interfaces
- **Credential management**: Secure handling of secrets through credential sets
- **Error handling**: Proper treatment of upstream errors and edge cases
- **Conversational interactions**: Natural language queries without skill naming

**Section sources**
- [ACME Admin README:38-77](file://samples/acme-admin/README.md#L38-L77)
- [ACME Admin README:232-250](file://samples/acme-admin/README.md#L232-L250)
- [demo-suite.sh:127-137](file://samples/acme-admin/demo-suite.sh#L127-L137)

### Common Skill Patterns Reference

**Updated** Enhanced common patterns section with concrete examples from the complete ACME Admin sample suite including improved operator guidance for password reset workflows.

#### Complete Pattern Categories

1. **Pure Read Operations** (Zero Cards)
   - HTTP GET calls to APIs
   - Browser-based reads with auto-submit forms
   - Examples: `CheckServiceHealth`, `CheckUserStatus`

2. **Single-Operation Mutations** (Action Cards)
   - Direct API calls that change state
   - Require explicit approval for each operation
   - Example: `LockUnlockUser`

3. **Complex Browser Workflows** (Flow Cards)
   - Multi-step browser interactions
   - One approval covers entire workflow
   - Example: `ResetAcmePassword`

4. **Unbound Per-Action Approval** (N Action Cards)
   - Interactive browser sessions without flow binding
   - Each write-tier interaction parks its own card
   - Example: `ResetPasswordAdHoc`

5. **Develop-as-You-Go Graduation** (N Action → 1 Flow)
   - Author ad-hoc, capture trace, graduate to reusable flow
   - Initial per-action approvals become one-gate replay
   - Example: `skill-graduation`

6. **Composition Patterns**
   - Combining multiple skills for complex operations
   - Cross-skill verification and state consistency
   - Demonstrated through demo suite

#### Best Practices from Samples

- **Separation of concerns**: Keep mutation and verification as separate skills
- **Proper error handling**: Treat upstream errors as findings, not failures
- **Credential management**: Use credential sets, never embed secrets
- **Element stability**: Assert element IDs from outside the application
- **Cross-surface verification**: Verify changes through multiple interfaces
- **Documentation**: Include comprehensive README and WALKTHROUGH files
- **Approval model selection**: Choose between flow, action, or per-action based on workflow complexity
- **Conversational design**: Write skills that can be found through natural language queries

**Section sources**
- [health-check README:63-89](file://samples/acme-admin/health-check/README.md#L63-L89)
- [user-status README:63-99](file://samples/acme-admin/user-status/README.md#L63-L99)
- [lock-unlock-user README:55-100](file://samples/acme-admin/lock-unlock-user/README.md#L55-L100)
- [password-reset README:80-121](file://samples/acme-admin/password-reset/README.md#L80-121)
- [password-reset WALKTHROUGH:83-103](file://samples/acme-admin/password-reset/WALKTHROUGH.md#L83-L103)
- [adhoc-password-reset README:60-104](file://samples/acme-admin/adhoc-password-reset/README.md#L60-L104)
- [adhoc-password-reset WALKTHROUGH:67-90](file://samples/acme-admin/adhoc-password-reset/WALKTHROUGH.md#L67-L90)
- [skill-graduation README:96-169](file://samples/acme-admin/skill-graduation/README.md#L96-L169)

### Web-Checks Migration Notes

**Updated** Documentation reflecting the migration of samples from `samples/web-checks/` to `samples/acme-admin/`.

The `web-checks` category has been retired as part of SPEC-060, with the following changes:

- **Migrated samples**: `adhoc-password-reset` and `skill-graduation` moved to `samples/acme-admin/`
- **Retired sample**: Static `password-reset` sample removed (superseded by `acme-admin/password-reset`)
- **Platform consumers**: `browser-check-target` remains shipped for platform consumers only
- **Skill IDs**: Preserved for migrated samples to maintain backward compatibility
- **References**: All documentation and guides updated to point to new locations

The migration consolidates all browser samples under the stateful `acme-admin` application, ensuring every tutorial demonstrates against a target that really mutates and can be verified.

**Section sources**
- [SPEC-060 spec:47-80](file://docs/specs/SPEC-060-rebase-web-checks-samples-onto-acme-admin/spec.md#L47-L80)
- [SPEC-060 plan:1-101](file://docs/specs/SPEC-060-rebase-web-checks-samples-onto-acme-admin/plan.md#L1-L101)
- [release notes:59-80](file://docs/agentic-aiops-platform/release-notes/2026-09-19-web-checks-consolidation.md#L59-L80)

### SPEC-066 Implementation Details

**New Section** Technical details of the SPEC-066 delivery for enhanced skills hub service:

#### Four Measured Lexical Fixes
1. **R-1 - Skill ID Scoring**: The slug becomes a fourth scored field at tag weight (×2), recovering identifier-owner queries
2. **R-2 - Corpus-Derived IDF Weighting**: Smoothed inverse document frequency `ln((1+N)/(1+df))+1` with no stoplist
3. **R-3 - Sublinear Body-Length Normalization**: Damps long documents with `1/log2(2 + len(body)/1000)`
4. **R-4 - Query-Side CamelCase Splitting**: Splits identifiers like `KubePodNotReady` into parts while keeping document side unsplit

#### Cross-Backend Parity Mechanism
- **Query-Only Split**: R-4 applies CamelCase splitting only to queries, not documents
- **Sound Over-Approximation**: R-5's prefilter widens to admit all potential matches
- **Python Decider**: Both backends use shared Python `rank()` function for final ordering
- **Byte-Identical Results**: R-6 harness asserts identical ordering and scores across backends

#### Evaluation Framework
- **R-8 Merge Gate**: Re-measures through real PostgreSQL with prefilter in path
- **Frozen Baseline**: V0 fixture (19/38) vs shipped scorer (24/38) 
- **Statistical Significance**: nDCG@10 bootstrap CI [+0.022, +0.111] excludes zero
- **Known Regressions**: Q62 and Q63 in-window re-orderings disclosed

**Section sources**
- [SPEC-066 spec:1-800](file://docs/specs/SPEC-066-skill-retrieval-ranking-fidelity/spec.md#L1-L800)
- [SPEC-066 plan:87-396](file://docs/specs/SPEC-066-skill-retrieval-ranking-fidelity/plan.md#L87-L396)
- [SPEC-066 delivery release note:1-180](file://docs/agentic-aiops-platform/release-notes/2026-10-03-spec-066-skill-retrieval-ranking-fidelity.md#L1-L180)
# SPEC-066: Skill Retrieval Ranking Fidelity

<cite>
**Referenced Files in This Document**   
- [spec.md](file://docs/specs/SPEC-066-skill-retrieval-ranking-fidelity/spec.md)
- [plan.md](file://docs/specs/SPEC-066-skill-retrieval-ranking-fidelity/plan.md)
- [tasks.md](file://docs/specs/SPEC-066-skill-retrieval-ranking-fidelity/tasks.md)
- [scoring.py](file://products/skills-hub/src/skills_hub/services/scoring.py)
- [skill_store.py](file://products/skills-hub/src/skills_hub/services/skill_store.py)
- [test_scoring.py](file://products/skills-hub/tests/test_scoring.py)
- [test_skill_store.py](file://products/skills-hub/tests/test_skill_store.py)
- [semantic-skill-retrieval-eval-set.md](file://docs/workspace/semantic-skill-retrieval-eval-set.md)
</cite>

## Update Summary
**Changes Made**
- Updated status from `approved` to `delivered` (v0.46.0, 2026-10-03) with all requirements implemented and measurement results published
- Added comprehensive delivery metrics showing top-1 grade-2 improvement from 19/38 to 24/38 on the shipped Postgres path
- Updated implementation details to reflect the four measured lexical fixes now unconditional: skill_id scoring, corpus-derived IDF weighting, sublinear body-length normalization, and query-side CamelCase splitting
- Enhanced troubleshooting section with resolved issues and new symptoms related to delivered functionality
- Added delivery-specific sections covering index migration, flag removal, and operator deployment steps

## Table of Contents
1. [Introduction](#introduction)
2. [Project Structure](#project-structure)
3. [Core Components](#core-components)
4. [Architecture Overview](#architecture-overview)
5. [Detailed Component Analysis](#detailed-component-analysis)
6. [Dependency Analysis](#dependency-analysis)
7. [Performance Considerations](#performance-considerations)
8. [Delivery Status and Metrics](#delivery-status-and-metrics)
9. [Troubleshooting Guide](#troubleshooting-guide)
10. [Conclusion](#conclusion)

## Introduction
SPEC-066 proposes four measured lexical improvements to the skills-hub keyword retriever, plus cross-backend parity enforcement and a product-side de-duplication guardrail. **The spec is now `delivered` as of 2026-10-03 (v0.46.0)**, with all six Open Questions resolved against the shipped code and operator ratification. Its evidence base is the semantic skill retrieval spike's evaluation set, which established that combining inverse document frequency weighting, sublinear body-length normalization, CamelCase-splitting tokenization, and scoring the `skill_id` slug moves top-1 correctness from 0.500 to 0.711 on the labeled corpus — but only when all four are applied together.

The central risk remains that the measurement was taken over an in-memory corpus export, not through the deployed Postgres backend. Three of the four fixes are therefore not backend-neutral as measured, and two would silently under-deliver or regress recall without a co-change to the Postgres prefilter and its GIN index. The spec's primary requirement is thus **parity**: both backends must produce the same ordering (and, where IDF is backend-independent, the same scores), and the change must be re-measured on the shipped path before promotion.

**Updated** Status changed from approved to delivered; all six Open Questions resolved including score semantics, IDF statistics computation, cross-backend invariants, Postgres path reporting, versioned index creation, and sync-time overlap handling. The four measurement flags have been removed, making all fixes unconditional.

## Project Structure
SPEC-066 lives under `docs/specs/SPEC-066-skill-retrieval-ranking-fidelity/` alongside its specification, plan, and task scaffold. The implementation scope is concentrated in the `skills-hub` product:

```mermaid
graph TB
Spec["SPEC-066 spec.md"] --> Plan["SPEC-066 plan.md"]
Spec --> Tasks["SPEC-066 tasks.md"]
Plan --> Scoring["scoring.py<br/>tokenize(), tokenize_query(), score(), rank()"]
Plan --> Store["skill_store.py<br/>InMemorySkillStore, PostgresSkillStore"]
Tasks --> TestScoring["test_scoring.py"]
Tasks --> TestStore["test_skill_store.py"]
Spec --> EvalSet["semantic-skill-retrieval-eval-set.md"]
```

**Diagram sources**
- [spec.md:1-1414](file://docs/specs/SPEC-066-skill-retrieval-ranking-fidelity/spec.md#L1-L1414)
- [plan.md:1-838](file://docs/specs/SPEC-066-skill-retrieval-ranking-fidelity/plan.md#L1-L838)
- [tasks.md:1-735](file://docs/specs/SPEC-066-skill-retrieval-ranking-fidelity/tasks.md#L1-L735)
- [scoring.py:1-336](file://products/skills-hub/src/skills_hub/services/scoring.py#L1-L336)
- [skill_store.py:1-658](file://products/skills-hub/src/skills_hub/services/skill_store.py#L1-L658)
- [test_scoring.py:1-141](file://products/skills-hub/tests/test_scoring.py#L1-L141)
- [test_skill_store.py:1-652](file://products/skills-hub/tests/test_skill_store.py#L1-L652)
- [semantic-skill-retrieval-eval-set.md:1-200](file://docs/workspace/semantic-skill-retrieval-eval-set.md#L1-L200)

**Section sources**
- [spec.md:1-1414](file://docs/specs/SPEC-066-skill-retrieval-ranking-fidelity/spec.md#L1-L1414)
- [plan.md:1-838](file://docs/specs/SPEC-066-skill-retrieval-ranking-fidelity/plan.md#L1-L838)
- [tasks.md:1-735](file://docs/specs/SPEC-066-skill-retrieval-ranking-fidelity/tasks.md#L1-L735)

## Core Components
The current retriever has three layers:

| Layer | File | Responsibility |
|---|---|---|
| Tokenizer and scorer | `scoring.py` | Splits text into lowercase alphanumeric tokens, computes title/tag/body/skill_id contributions, ranks hits by score then `skill_id`, and produces excerpts. |
| In-memory store | `skill_store.py::InMemorySkillStore` | Holds per-source snapshots; `search()` passes all filtered records directly to `rank()`. |
| Postgres store | `skill_store.py::PostgresSkillStore` | Prefilters candidates with a `to_tsvector` full-text expression, maps rows to `Skill`, then delegates ranking to the shared `rank()`. |

The existing scorer weights title matches at 3.0, tag matches at 2.0, and capped body occurrences at 1.0, with ties broken by ascending `skill_id`. The Postgres `_SEARCH_VECTOR` covers `title || ' ' || body` and the tags array, but not `skill_id`; the GIN index `idx_skills_search_v2` mirrors that expression.

**Section sources**
- [scoring.py:1-336](file://products/skills-hub/src/skills_hub/services/scoring.py#L1-L336)
- [skill_store.py:88-182](file://products/skills-hub/src/skills_hub/services/skill_store.py#L88-L182)
- [skill_store.py:377-644](file://products/skills-hub/src/skills_hub/services/skill_store.py#L377-L644)
- [skill_store.py:196-275](file://products/skills-hub/src/skills_hub/services/skill_store.py#L196-L275)

## Architecture Overview
SPEC-066 does not introduce a new service. It modifies the shared scorer, the Postgres prefilter/index, and the ranking pipeline, while adding a parity harness and a content-hash de-duplication step.

```mermaid
sequenceDiagram
participant Client as "Skills client"
participant Store as "SkillStore.search()"
participant Backend as "InMemory or Postgres"
participant Scorer as "scoring.rank()"
participant Dedup as "R-7 de-duplication"
Client->>Store : search(query, limit, source?, tag?)
alt In-memory backend
Store->>Backend : _all_records(source, tag)
Backend-->>Store : list[Skill]
else Postgres backend
Store->>Backend : tokenize(query) + _SEARCH_VECTOR
Backend-->>Store : candidate rows
Store->>Store : map rows to Skill
end
Store->>Dedup : apply content-hash collapse (before sort/truncate)
Dedup->>Scorer : rank(query, deduplicated records, limit, stats)
Scorer-->>Client : list[SearchHit]
```

**Diagram sources**
- [skill_store.py:158-166](file://products/skills-hub/src/skills_hub/services/skill_store.py#L158-L166)
- [skill_store.py:564-604](file://products/skills-hub/src/skills_hub/services/skill_store.py#L564-L604)
- [scoring.py:302-336](file://products/skills-hub/src/skills_hub/services/scoring.py#L302-L336)

The spec requires R-7's de-duplication to happen **before** sorting and truncation so that byte-identical bodies do not consume distinct result slots. The spec also requires R-6's parity harness to drive both backends over the same corpus and query set and assert identical `skill_id` ordering (and, for backend-independent IDF, identical scores).

**Section sources**
- [spec.md:549-580](file://docs/specs/SPEC-066-skill-retrieval-ranking-fidelity/spec.md#L549-L580)
- [plan.md:489-529](file://docs/specs/SPEC-066-skill-retrieval-ranking-fidelity/plan.md#L489-L529)

## Detailed Component Analysis

### Requirement R-1: Score the `skill_id` slug
R-1 adds `skill_id` as a fourth scored field in `score()`. The measurement used `TAG_WEIGHT` (2.0); any other weight is explicitly unmeasured and rejected by the spec. The slug must tokenize consistently with the title, so separators such as `/` and `-` become separate tokens, and with R-4 active, CamelCase-derived tokens are included.

Acceptance criteria include stratum-A identifier-owner recovery against the committed label fixture, recording behaviour for queries naming identifiers absent from the corpus, and ensuring a slug-only match returns non-empty results on both backends once R-5 is delivered.

```mermaid
flowchart TD
Start(["score()"]) --> ReadSlug["Read skill.skill_id"]
ReadSlug --> TokenizeSlug["tokenize(slug)"]
TokenizeSlug --> CreditTokens["Credit slug tokens at TAG_WEIGHT (2.0)"]
CreditTokens --> TitleTagBody["Continue title / tag / body scoring"]
TitleTagBody --> ReturnScore["Return total"]
```

**Diagram sources**
- [scoring.py:207-257](file://products/skills-hub/src/skills_hub/services/scoring.py#L207-L257)
- [plan.md:115-129](file://docs/specs/SPEC-066-skill-retrieval-ranking-fidelity/plan.md#L115-L129)

**Section sources**
- [spec.md:189-215](file://docs/specs/SPEC-066-skill-retrieval-ranking-fidelity/spec.md#L189-L215)
- [plan.md:115-129](file://docs/specs/SPEC-066-skill-retrieval-ranking-fidelity/plan.md#L115-L129)
- [tasks.md:205-215](file://docs/specs/SPEC-066-skill-retrieval-ranking-fidelity/tasks.md#L205-L215)

### Requirement R-2: Corpus-derived IDF weighting
R-2 replaces fixed per-field weights with inverse document frequency weighting using the formula `ln((1+N)/(1+df))+1`, where `N` is the document count and `df` is the number of documents containing the token. No hand-maintained stopword list is introduced. Field-weight ordering remains title > tags > body, preserving SPEC-014 R-3's guarantee.

The recommended design computes `N` and `df` once per request over the whole catalog, ignoring `source`/`tag` filters, so both backends derive the same statistics. Computing over the pool passed to `rank()` is rejected because the in-memory and Postgres callers pass different pools, which would break the byte-identical invariant.

```mermaid
flowchart TD
Start(["Compute corpus statistics"]) --> CountDocs["Count N = number of documents"]
CountDocs --> TokenizeAll["Tokenize every document with the same tokenize()"]
TokenizeAll --> ComputeDF["Compute df(token) = documents containing token"]
ComputeDF --> BuildStats["Build immutable CorpusStats(N, df)"]
BuildStats --> ApplyIDF["Apply ln((1+N)/(1+df))+1 to each query token"]
ApplyIDF --> WeightFields["Multiply by unchanged field weights"]
```

**Diagram sources**
- [spec.md:216-275](file://docs/specs/SPEC-066-skill-retrieval-ranking-fidelity/spec.md#L216-L275)
- [plan.md:131-203](file://docs/specs/SPEC-066-skill-retrieval-ranking-fidelity/plan.md#L131-L203)

**Section sources**
- [spec.md:216-275](file://docs/specs/SPEC-066-skill-retrieval-ranking-fidelity/spec.md#L216-L275)
- [plan.md:131-203](file://docs/specs/SPEC-066-skill-retrieval-ranking-fidelity/plan.md#L131-L203)
- [tasks.md:293-333](file://docs/specs/SPEC-066-skill-retrieval-ranking-fidelity/tasks.md#L293-L333)

### Requirement R-3: Sublinear body-length normalization
R-3 dampens the body contribution by multiplying it by `1/log2(2 + len(body)/1000)` after the existing `BODY_OCCURRENCE_CAP = 5` cap. The factor is always in `(0, 1.0]`, including for empty bodies, so no division-by-zero or logarithm-of-zero branch is reachable. This fix is per-document and therefore backend-neutral by construction.

```mermaid
flowchart TD
Start(["Body contribution"]) --> Cap["Apply BODY_OCCURRENCE_CAP = 5"]
Cap --> LengthNorm["Multiply by 1/log2(2 + len(body)/1000)"]
LengthNorm --> BoundsCheck{"Factor in (0, 1.0]?"}
BoundsCheck --> |Yes| ReturnNormalized["Return normalized body contribution"]
BoundsCheck --> |No| FailAssertion["Fail assertion — should never reach here"]
```

**Diagram sources**
- [spec.md:276-298](file://docs/specs/SPEC-066-skill-retrieval-ranking-fidelity/spec.md#L276-L298)
- [plan.md:204-218](file://docs/specs/SPEC-066-skill-retrieval-ranking-fidelity/plan.md#L204-L218)

**Section sources**
- [spec.md:276-298](file://docs/specs/SPEC-066-skill-retrieval-ranking-fidelity/spec.md#L276-L298)
- [plan.md:204-218](file://docs/specs/SPEC-066-skill-retrieval-ranking-fidelity/plan.md#L204-L218)
- [tasks.md:200-205](file://docs/specs/SPEC-066-skill-retrieval-ranking-fidelity/tasks.md#L200-L205)

### Requirement R-4: Query-side CamelCase-splitting tokenization
R-4 changes `tokenize_query()` so CamelCase runs split into component words. The spec uses `KubePodCrashLooping` → `kube`, `pod`, `crash`, `looping` as the canonical example. The exact rule for digits, acronyms, and mixed runs is fixed in `plan.md` and covered by a committed case table.

The critical coupling is that the same whole-token decision must be applied in `tokenize_query()`, in R-2's `df` computation, and in R-5's prefilter. A partial application — keeping the whole token in one place and parts in another — is the failure mode this criterion exists to prevent.

```mermaid
flowchart TD
Start(["tokenize_query(text)"]) --> Lower["Lowercase original text"]
Lower --> SplitCamel["Split CamelCase/digit boundaries"]
SplitCamel --> ApplyPattern["Apply existing [a-z0-9]+ pattern to each part"]
ApplyPattern --> DecideWhole{"OQ-2 whole-token rule"}
DecideWhole --> |Keep both| EmitBoth["Emit whole token and its parts"]
DecideWhole --> |Parts only| EmitParts["Emit only parts"]
EmitBoth --> ReturnTokens["Return token list"]
EmitParts --> ReturnTokens
```

**Diagram sources**
- [scoring.py:102-133](file://products/skills-hub/src/skills_hub/services/scoring.py#L102-L133)
- [spec.md:299-433](file://docs/specs/SPEC-066-skill-retrieval-ranking-fidelity/spec.md#L299-L433)
- [plan.md:219-397](file://docs/specs/SPEC-066-skill-retrieval-ranking-fidelity/plan.md#L219-L397)

**Section sources**
- [spec.md:299-433](file://docs/specs/SPEC-066-skill-retrieval-ranking-fidelity/spec.md#L299-L433)
- [plan.md:219-397](file://docs/specs/SPEC-066-skill-retrieval-ranking-fidelity/plan.md#L219-L397)
- [tasks.md:216-293](file://docs/specs/SPEC-066-skill-retrieval-ranking-fidelity/tasks.md#L216-L293)

### Requirement R-5: Cross-backend parity for the new scorer
R-5 makes the Postgres prefilter admit every record the new scorer can rank above zero. Without it, R-1 does not ship (slug-only matches return zero rows on Postgres) and R-4 regresses recall (query-side splitting breaks the mirror between Python `tokenize_query()` and PostgreSQL `to_tsvector('simple', …)`).

Two strategies are considered:

| Strategy | Approach | Trade-off |
|---|---|---|
| Mirror tokenizer in SQL | Add `skill_id` to the `to_tsvector` expression and express R-4's split as an IMMUTABLE SQL function | Cleanest and keeps the index selective, but requires proving the function IMMUTABLE and pinning it against the Python case table. |
| Widen the prefilter (recommended) | Keep `to_tsvector('simple', …)` as-is, add `skill_id`, and additionally admit rows via a case-insensitive substring/LIKE arm for CamelCase-split tokens | Cannot drift from Python; failure mode is a slow sequential scan rather than a silent missing row. |

The migration must rebuild `idx_skills_search_v2` because `_DDL` uses `CREATE INDEX IF NOT EXISTS`, which will not rebuild an existing index when its expression changes. `CREATE INDEX CONCURRENTLY` cannot run inside a transaction block, so the concurrency window must be explicit.

```mermaid
flowchart TD
Start(["Prefilter strategy"]) --> AddSlug["_SEARCH_VECTOR covers skill_id"]
AddSlug --> ChoosePath{"IMMUTABLE SQL tokenizer vs widen prefilter"}
ChoosePath --> |Mirror| CreateSQLFunc["Create IMMUTABLE SQL split function"]
CreateSQLFunc --> UpdateIndex["Update idx_skills_search_v2 expression"]
ChoosePath --> |Widen| KeepSimple["Keep to_tsvector('simple', …)"]
KeepSimple --> AddLikeArm["Add LIKE arm for CamelCase-split tokens"]
AddLikeArm --> UpdateIndex
UpdateIndex --> Migrate["Drop and recreate index (not CREATE INDEX IF NOT EXISTS)"]
Migrate --> Verify["Assert expressions remain identical"]
```

**Diagram sources**
- [spec.md:434-548](file://docs/specs/SPEC-066-skill-retrieval-ranking-fidelity/spec.md#L434-L548)
- [plan.md:398-488](file://docs/specs/SPEC-066-skill-retrieval-ranking-fidelity/plan.md#L398-L488)
- [skill_store.py:186-275](file://products/skills-hub/src/skills_hub/services/skill_store.py#L186-L275)

**Section sources**
- [spec.md:434-548](file://docs/specs/SPEC-066-skill-retrieval-ranking-fidelity/spec.md#L434-L548)
- [plan.md:398-488](file://docs/specs/SPEC-066-skill-retrieval-ranking-fidelity/plan.md#L398-L488)
- [tasks.md:334-412](file://docs/specs/SPEC-066-skill-retrieval-ranking-fidelity/tasks.md#L334-L412)

### Requirement R-6: Enforced cross-backend parity harness
R-6 replaces the documented-but-untested byte-identical invariant with a test that actually enforces it. It drives both `InMemorySkillStore` and `PostgresSkillStore` over the same corpus and the same committed query set — the union of the 63-query audit pool and the 18 authored stratum-C paraphrases — and asserts identical `skill_id` ordering. With backend-independent IDF, it asserts identical scores, not merely equal ordering.

The harness must fail on the current code if the invariant is already violated, or pass and thereby establish the baseline. It must not be written so that it can only pass.

```mermaid
flowchart TD
Start(["Parity harness"]) --> LoadCorpus["Load same corpus into both stores"]
LoadCorpus --> LoadQueries["Load committed query fixture"]
LoadQueries --> RunMemory["Run search on InMemorySkillStore"]
RunMemory --> RunPostgres["Run search on PostgresSkillStore"]
RunPostgres --> CompareOrdering{"skill_id ordering identical?"}
CompareOrdering --> |No| RecordViolation["Record pre-existing violation"]
CompareOrdering --> |Yes| CompareScores{"Scores identical (if IDF backend-independent)?"}
CompareScores --> |No| RecordViolation
CompareScores --> |Yes| PassBaseline["Pass — baseline established"]
```

**Diagram sources**
- [spec.md:549-580](file://docs/specs/SPEC-066-skill-retrieval-ranking-fidelity/spec.md#L549-L580)
- [plan.md:489-529](file://docs/specs/SPEC-066-skill-retrieval-ranking-fidelity/plan.md#L489-L529)
- [tasks.md:151-185](file://docs/specs/SPEC-066-skill-retrieval-ranking-fidelity/tasks.md#L151-L185)

**Section sources**
- [spec.md:549-580](file://docs/specs/SPEC-066-skill-retrieval-ranking-fidelity/spec.md#L549-L580)
- [plan.md:489-529](file://docs/specs/SPEC-066-skill-retrieval-ranking-fidelity/plan.md#L489-L529)
- [tasks.md:151-185](file://docs/specs/SPEC-066-skill-retrieval-ranking-fidelity/tasks.md#L151-L185)

### Requirement R-7: Product-side de-duplication guardrail
R-7 collapses byte-identical bodies in `rank()` before sorting and truncation, retaining the lowest `skill_id` as the deterministic survivor. The identity key is `md5(body)`, consistent with the label fixture's `body_md5` pin. The spec explicitly states that MD5 here is a content-identity key, not a security digest.

Overlap rejection is deliberately kept out of `parse_sources`, because that function validates JSON shape and duplicate `source_id` values but never sees file content. If ingestion-time rejection is desired, it belongs at sync time and is scoped to OQ-6.

```mermaid
flowchart TD
Start(["rank()"]) --> ScoreAll["Score every record"]
ScoreAll --> FilterZero["Filter zero-score records"]
FilterZero --> BuildHits["Build SearchHit list"]
BuildHits --> Collapse["Collapse by md5(body), keep lowest skill_id"]
Collapse --> Sort["Sort by (-score, skill_id)"]
Sort --> Truncate["Truncate to [:limit]"]
Truncate --> Return["Return hits"]
```

**Diagram sources**
- [spec.md:581-647](file://docs/specs/SPEC-066-skill-retrieval-ranking-fidelity/spec.md#L581-L647)
- [plan.md:530-590](file://docs/specs/SPEC-066-skill-retrieval-ranking-fidelity/plan.md#L530-L590)
- [tasks.md:413-460](file://docs/specs/SPEC-066-skill-retrieval-ranking-fidelity/tasks.md#L413-L460)

**Section sources**
- [spec.md:581-647](file://docs/specs/SPEC-066-skill-retrieval-ranking-fidelity/spec.md#L581-L647)
- [plan.md:530-590](file://docs/specs/SPEC-066-skill-retrieval-ranking-fidelity/plan.md#L530-L590)
- [tasks.md:413-460](file://docs/specs/SPEC-066-skill-retrieval-ranking-fidelity/tasks.md#L413-L460)

### Requirement R-8: Re-measurement on the shipped path
R-8 extends the offline evaluation harness to drive `PostgresSkillStore.search()` rather than calling `rank()` directly, so the prefilter is inside the measured path. It asserts the fixture's `body_md5` per document before computing metrics, reports results per backend, and discloses the known Q63 re-ordering regression and unchanged abstention rate.

If the Postgres-path gain is not outside the noise band, the spec defines a null-result path: publish the result, do not merge R-1..R-5, and record the outcome on the backlog row.

**Section sources**
- [spec.md:648-758](file://docs/specs/SPEC-066-skill-retrieval-ranking-fidelity/spec.md#L648-L758)
- [plan.md:591-643](file://docs/specs/SPEC-066-skill-retrieval-ranking-fidelity/plan.md#L591-L643)
- [tasks.md:461-534](file://docs/specs/SPEC-066-skill-retrieval-ranking-fidelity/tasks.md#L461-L534)

### Requirement R-9: Contract and living-doc updates
R-9 updates the skills-hub README endpoint summary, the `scoring.py` module docstring, SPEC-014 R-3's wording, relevant guides, the CHANGELOG, version files, and the spec index. It explicitly notes that no JSON schema changes are made: `score` is published on the HTTP response but appears in no `shared/shared-contracts` schema, and changing its value distribution is not a contract-schema change.

**Section sources**
- [spec.md:759-838](file://docs/specs/SPEC-066-skill-retrieval-ranking-fidelity/spec.md#L759-L838)
- [plan.md:644-688](file://docs/specs/SPEC-066-skill-retrieval-ranking-fidelity/plan.md#L644-L688)
- [tasks.md:535-612](file://docs/specs/SPEC-066-skill-retrieval-ranking-fidelity/tasks.md#L535-L612)

## Dependency Analysis
The spec's requirements form a staged dependency graph. Only R-6 has no Open Question dependency; the others depend on OQ-1(b), OQ-2, OQ-4, OQ-5, or OQ-6.

```mermaid
graph LR
OQ1["OQ-1(b): skill_id weight"] --> R1["R-1: score skill_id"]
OQ2["OQ-2: IDF corpus source"] --> R2["R-2: corpus-derived IDF"]
OQ2 --> R4["R-4: CamelCase tokenizer"]
R4 --> R2
OQ5["OQ-5: GIN migration strategy"] --> R5["R-5: prefilter + index"]
R4 --> R5
R1 --> R6["R-6: parity harness"]
R2 --> R6
R3["R-3: length normalization"] --> R6
R4 --> R6
R5 --> R8["R-8: shipped-path re-measurement"]
R7["R-7: de-duplication"] --> R8
R6 --> R8
R8 --> R9["R-9: docs + delivery"]
```

**Diagram sources**
- [plan.md:689-733](file://docs/specs/SPEC-066-skill-retrieval-ranking-fidelity/plan.md#L689-L733)
- [tasks.md:18-79](file://docs/specs/SPEC-066-skill-retrieval-ranking-fidelity/tasks.md#L18-L79)
- [tasks.md:713-735](file://docs/specs/SPEC-066-skill-retrieval-ranking-fidelity/tasks.md#L713-L735)

The current codebase dependencies are narrower:

```mermaid
graph TB
TestScoring["test_scoring.py"] --> Scoring["scoring.py"]
TestStore["test_skill_store.py"] --> Store["skill_store.py"]
Store --> Scoring
Spec["spec.md"] --> Scoring
Spec --> Store
Plan["plan.md"] --> Scoring
Plan --> Store
Tasks["tasks.md"] --> TestScoring
Tasks --> TestStore
```

**Diagram sources**
- [test_scoring.py:1-141](file://products/skills-hub/tests/test_scoring.py#L1-L141)
- [test_skill_store.py:1-652](file://products/skills-hub/tests/test_skill_store.py#L1-L652)
- [scoring.py:1-336](file://products/skills-hub/src/skills_hub/services/scoring.py#L1-L336)
- [skill_store.py:1-658](file://products/skills-hub/src/skills_hub/services/skill_store.py#L1-L658)

**Section sources**
- [plan.md:689-733](file://docs/specs/SPEC-066-skill-retrieval-ranking-fidelity/plan.md#L689-L733)
- [tasks.md:18-79](file://docs/specs/SPEC-066-skill-retrieval-ranking-fidelity/tasks.md#L18-L79)

## Performance Considerations
SPEC-066 distinguishes several latency measurements:

| Measurement | Current state | Spec requirement |
|---|---|---|
| Offline pure-Python `rank()` p50 | 2.726 ms (eval-set) | Not end-to-end; excludes prefilter, HTTP, auth, and audit write. |
| Postgres search p95 | 24.849 ms (delivered) | Must stay inside tool-gateway's 10.0 s `REQUEST_TIMEOUT_SECONDS`, measured end to end. |
| Catalog growth trigger | pgvector scale trigger is >2,000 skills or search p95 >300 ms | Retained as the reopening condition for vector retrieval; not reached today. |
| De-duplication cost | Not measured as a retrieval improvement | Intended as regression protection; dev corpus already clean (0 of 63 pools contain duplicates). |

The widened-prefilter strategy in R-5 is preferred because its failure mode is a slow query (loud and measurable) rather than a missing row (silent). At the current 18-row catalog this is acceptable; the plan notes that the >2,000-skill trigger is the point to revisit.

**Section sources**
- [spec.md:457-465](file://docs/specs/SPEC-066-skill-retrieval-ranking-fidelity/spec.md#L457-L465)
- [spec.md:643-685](file://docs/specs/SPEC-066-skill-retrieval-ranking-fidelity/spec.md#L643-L685)
- [plan.md:485-488](file://docs/specs/SPEC-066-skill-retrieval-ranking-fidelity/plan.md#L485-L488)
- [plan.md:782-800](file://docs/specs/SPEC-066-skill-retrieval-ranking-fidelity/plan.md#L782-L800)

## Delivery Status and Metrics

### Implementation Status
SPEC-066 is now **delivered** as of v0.46.0 (2026-10-03). All four measurement flags have been removed, making the lexical fixes unconditional. The implementation includes:

- **Four measured lexical fixes**: skill_id scoring, corpus-derived IDF weighting, sublinear body-length normalization, and query-side CamelCase splitting
- **Cross-backend parity**: enforced by the parity harness with identical ordering and scores across backends
- **Content de-duplication**: collapsing byte-identical bodies before truncation
- **Versioned index migration**: `idx_skills_search_v2` created alongside retained `idx_skills_search`

### Measurement Results
The shipped candidate measures **24/38** combined top-1 grade-2 on real PostgreSQL 16, compared to the baseline of **19/38**. Key metrics:

| Config | Combined top-1 (grade 2) | Note |
|---|---|---|
| V0 (shipped, flags off) | **19/38** | fidelity gate — reproduces the baseline |
| V3 (IDF + length-norm + query-split, no `skill_id`) | **23/38** | the three backend-neutral fixes |
| **V6 / candidate (all four)** | **24/38** | R-1's `skill_id` adds the 24th |

Combined MRR **0.842**; stratum-B MRR **0.900**; stratum-C MRR **0.778**, stratum-C top-1 grade 2 **10/18**. Stratum-A identifier-owner recovery — R-1's headline — is intact at **0/3 → 3/3**.

### Known Regressions
Two top-1 regressions are disclosed:
1. **Q63**: `web check sign in inventory portal does not transition successful login troubleshooting` moves top-1 from `D18` (grade 2) to `D13` (grade 1), with `D18` falling to rank 2 of 5
2. **Q62**: `D17` grade 2 → `D18` grade 1 (introduced by query-only split)

Both are in-window re-orderings where the grade-2 document remains returned, so the null result stays 0 missing.

### Operator Deployment Steps
The live `idx_skills_search_v2` migration and deployment are the remaining operator step, and the drop of the retained `idx_skills_search` is scheduled for the following release. Index size delta: `idx_skills_search` **155,648 B** → `idx_skills_search_v2` **163,840 B** (+8,192 B, one 8 KiB page).

**Section sources**
- [spec.md:5-31](file://docs/specs/SPEC-066-skill-retrieval-ranking-fidelity/spec.md#L5-L31)
- [spec.md:653-700](file://docs/specs/SPEC-066-skill-retrieval-ranking-fidelity/spec.md#L653-L700)
- [tasks.md:26-40](file://docs/specs/SPEC-066-skill-retrieval-ranking-fidelity/tasks.md#L26-L40)

## Troubleshooting Guide

### Symptom: Slug-only search returns results in memory but zero on Postgres
**Cause:** `_SEARCH_VECTOR` does not cover `skill_id`. A slug-only match scores positive in memory but is excluded by the Postgres prefilter.

**Resolution:** Deliver R-5 so `_SEARCH_VECTOR` includes `skill_id`, and verify that a slug-only query returns rows on Postgres as well as in memory.

**Section sources**
- [spec.md:129-135](file://docs/specs/SPEC-066-skill-retrieval-ranking-fidelity/spec.md#L129-L135)
- [spec.md:468-469](file://docs/specs/SPEC-066-skill-retrieval-ranking-fidelity/spec.md#L468-L469)
- [tasks.md:342-356](file://docs/specs/SPEC-066-skill-retrieval-ranking-fidelity/tasks.md#L342-L356)

### Symptom: CamelCase-aware queries lose recall on Postgres
**Cause:** Query-side `tokenize_query()` splits CamelCase, but PostgreSQL `to_tsvector('simple', …)` lowercases and splits on non-alphanumerics without splitting CamelCase. The mirror is broken.

**Resolution:** Either mirror the tokenizer in an IMMUTABLE SQL function or widen the prefilter with prefix lexemes for CamelCase-split tokens. The spec recommends widening because the failure mode is loud (slow query) rather than silent (missing row).

**Section sources**
- [spec.md:136-144](file://docs/specs/SPEC-066-skill-retrieval-ranking-fidelity/spec.md#L136-L144)
- [plan.md:407-429](file://docs/specs/SPEC-066-skill-retrieval-ranking-fidelity/plan.md#L407-L429)
- [tasks.md:357-370](file://docs/specs/SPEC-066-skill-retrieval-ranking-fidelity/tasks.md#L357-L370)

### Symptom: Index is not rebuilt after deployment
**Cause:** `_DDL` uses `CREATE INDEX IF NOT EXISTS`, which preserves the old index when its expression changes.

**Resolution:** Write a migration that drops and recreates the index. Test that the migration actually rebuilds the index on an existing database and that the rollback path runs.

**Section sources**
- [plan.md:437-451](file://docs/specs/SPEC-066-skill-retrieval-ranking-fidelity/plan.md#L437-L451)
- [tasks.md:380-391](file://docs/specs/SPEC-066-skill-retrieval-ranking-fidelity/tasks.md#L380-L391)

### Symptom: Duplicate bodies consume multiple result slots
**Cause:** `rank()` has no content-level de-duplication. Two sources covering the same files produce distinct `skill_id` values with identical bodies, and both occupy slots up to `limit`.

**Resolution:** Implement R-7's content-hash collapse before sorting and truncation. Use `md5(body)` as the identity key and retain the lowest `skill_id`.

**Section sources**
- [semantic-skill-retrieval-eval-set.md:55-127](file://docs/workspace/semantic-skill-retrieval-eval-set.md#L55-L127)
- [spec.md:581-647](file://docs/specs/SPEC-066-skill-retrieval-ranking-fidelity/spec.md#L581-L647)
- [tasks.md:436-453](file://docs/specs/SPEC-066-skill-retrieval-ranking-fidelity/tasks.md#L436-L453)

### Symptom: Existing exact-score assertions fail after R-4
**Cause:** The eight exact-score assertions in `test_scoring.py` encode the old tokenization, including `score("KubePodNotReady", skill) == 7.0`, which encodes the defect R-4 removes.

**Resolution:** Update the assertions deliberately with old and new expected values visible in review. Do not weaken them to vague comparisons.

**Section sources**
- [spec.md:413-425](file://docs/specs/SPEC-066-skill-retrieval-ranking-fidelity/spec.md#L413-L425)
- [plan.md:369-397](file://docs/specs/SPEC-066-skill-retrieval-ranking-fidelity/plan.md#L369-L397)
- [tasks.md:271-290](file://docs/specs/SPEC-066-skill-retrieval-ranking-fidelity/tasks.md#L271-L290)

### New Symptom: Performance regression on large catalogs
**Cause:** The widened prefilter may cause slower queries as the catalog grows beyond 18 rows.

**Resolution:** Monitor search latency p95 against the 10.0 s gateway timeout. The >2,000-skill trigger is the point to revisit the prefilter strategy.

**Section sources**
- [spec.md:460-465](file://docs/specs/SPEC-066-skill-retrieval-ranking-fidelity/spec.md#L460-L465)
- [plan.md:431-436](file://docs/specs/SPEC-066-skill-retrieval-ranking-fidelity/plan.md#L431-L436)

## Conclusion
SPEC-066 is a narrowly scoped, measurement-driven improvement to the skills-hub lexical retriever. Its four fixes — indexing `skill_id`, corpus-derived IDF weighting, sublinear body-length normalization, and query-side CamelCase-splitting tokenization — were shown sufficient to close the measured gap, but only as an indivisible package. The spec's most consequential addition is the cross-backend parity requirement: without R-5, R-1 does not ship and R-4 regresses recall; without R-6, the byte-identical invariant remains documented but unenforced.

**Updated** SPEC-066 is now **delivered** as of 2026-10-03 (v0.46.0), with all six Open Questions resolved: OQ-1 established `TAG_WEIGHT` (2.0) for `skill_id` scoring; OQ-2 mandated sync-time Python-computed IDF statistics; OQ-3 preserved the byte-identical cross-backend invariant; OQ-4 accepted the Q63 re-ordering regression conditionally; OQ-5 selected prefix lexemes with versioned index names; and OQ-6 deferred sync-time overlap rejection. The four measurement flags have been removed, making all fixes unconditional. The live `idx_skills_search_v2` migration and deployment are the remaining operator step, and the drop of the retained `idx_skills_search` is scheduled for the following release. The measured result shows top-1 grade-2 improvement from 19/38 to 24/38 on the shipped Postgres path, with nDCG@10 bootstrap CI excluding zero.
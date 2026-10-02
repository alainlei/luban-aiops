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
- Updated status from draft to approved with all six Open Questions resolved
- Removed provisional banners from plan.md and tasks.md
- Added resolution details for all Open Questions (OQ-1 through OQ-6)
- Updated implementation guidance based on refined plan with detailed stages
- Enhanced troubleshooting section with resolved issues

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

## Introduction
SPEC-066 proposes four measured lexical improvements to the skills-hub keyword retriever, plus cross-backend parity enforcement and a product-side de-duplication guardrail. **The spec is now `approved` as of 2026-10-02**, with all six Open Questions resolved against the shipped code and operator ratification. Its evidence base is the semantic skill retrieval spike's evaluation set, which established that combining inverse document frequency weighting, sublinear body-length normalization, CamelCase-splitting tokenization, and scoring the `skill_id` slug moves top-1 correctness from 0.500 to 0.711 on the labeled corpus — but only when all four are applied together.

The central risk remains that the measurement was taken over an in-memory corpus export, not through the deployed Postgres backend. Three of the four fixes are therefore not backend-neutral as measured, and two would silently under-deliver or regress recall without a co-change to the Postgres prefilter and its GIN index. The spec's primary requirement is thus **parity**: both backends must produce the same ordering (and, where IDF is backend-independent, the same scores), and the change must be re-measured on the shipped path before promotion.

**Updated** Status changed from draft to approved; all six Open Questions resolved including score semantics, IDF statistics computation, cross-backend invariants, Postgres path reporting, versioned index creation, and sync-time overlap handling.

## Project Structure
SPEC-066 lives under `docs/specs/SPEC-066-skill-retrieval-ranking-fidelity/` alongside its specification, plan, and task scaffold. The implementation scope is concentrated in the `skills-hub` product:

```mermaid
graph TB
Spec["SPEC-066 spec.md"] --> Plan["SPEC-066 plan.md"]
Spec --> Tasks["SPEC-066 tasks.md"]
Plan --> Scoring["scoring.py<br/>tokenize(), score(), rank()"]
Plan --> Store["skill_store.py<br/>InMemorySkillStore, PostgresSkillStore"]
Tasks --> TestScoring["test_scoring.py"]
Tasks --> TestStore["test_skill_store.py"]
Spec --> EvalSet["semantic-skill-retrieval-eval-set.md"]
```

**Diagram sources**
- [spec.md:1-1002](file://docs/specs/SPEC-066-skill-retrieval-ranking-fidelity/spec.md#L1-L1002)
- [plan.md:1-729](file://docs/specs/SPEC-066-skill-retrieval-ranking-fidelity/plan.md#L1-L729)
- [tasks.md:1-555](file://docs/specs/SPEC-066-skill-retrieval-ranking-fidelity/tasks.md#L1-L555)
- [scoring.py:1-97](file://products/skills-hub/src/skills_hub/services/scoring.py#L1-L97)
- [skill_store.py:1-518](file://products/skills-hub/src/skills_hub/services/skill_store.py#L1-L518)
- [test_scoring.py:1-141](file://products/skills-hub/tests/test_scoring.py#L1-L141)
- [test_skill_store.py:1-652](file://products/skills-hub/tests/test_skill_store.py#L1-L652)
- [semantic-skill-retrieval-eval-set.md:1-200](file://docs/workspace/semantic-skill-retrieval-eval-set.md#L1-L200)

**Section sources**
- [spec.md:1-1002](file://docs/specs/SPEC-066-skill-retrieval-ranking-fidelity/spec.md#L1-L1002)
- [plan.md:1-729](file://docs/specs/SPEC-066-skill-retrieval-ranking-fidelity/plan.md#L1-L729)
- [tasks.md:1-555](file://docs/specs/SPEC-066-skill-retrieval-ranking-fidelity/tasks.md#L1-L555)

## Core Components
The current retriever has three layers:

| Layer | File | Responsibility |
|---|---|---|
| Tokenizer and scorer | `scoring.py` | Splits text into lowercase alphanumeric tokens, computes title/tag/body contributions, ranks hits by score then `skill_id`, and produces excerpts. |
| In-memory store | `skill_store.py::InMemorySkillStore` | Holds per-source snapshots; `search()` passes all filtered records directly to `rank()`. |
| Postgres store | `skill_store.py::PostgresSkillStore` | Prefilters candidates with a `to_tsvector` full-text expression, maps rows to `Skill`, then delegates ranking to the shared `rank()`. |

The existing scorer weights title matches at 3.0, tag matches at 2.0, and capped body occurrences at 1.0, with ties broken by ascending `skill_id`. The Postgres `_SEARCH_VECTOR` covers `title || ' ' || body` and the tags array, but not `skill_id`; the GIN index `idx_skills_search` mirrors that expression.

**Section sources**
- [scoring.py:1-97](file://products/skills-hub/src/skills_hub/services/scoring.py#L1-L97)
- [skill_store.py:69-144](file://products/skills-hub/src/skills_hub/services/skill_store.py#L69-L144)
- [skill_store.py:158-256](file://products/skills-hub/src/skills_hub/services/skill_store.py#L158-L256)
- [skill_store.py:437-463](file://products/skills-hub/src/skills_hub/services/skill_store.py#L437-L463)

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
Dedup->>Scorer : rank(query, deduplicated records, limit)
Scorer-->>Client : list[SearchHit]
```

**Diagram sources**
- [skill_store.py:137-144](file://products/skills-hub/src/skills_hub/services/skill_store.py#L137-L144)
- [skill_store.py:437-463](file://products/skills-hub/src/skills_hub/services/skill_store.py#L437-L463)
- [scoring.py:85-96](file://products/skills-hub/src/skills_hub/services/scoring.py#L85-L96)

The spec requires R-7's de-duplication to happen **before** sorting and truncation so that byte-identical bodies do not consume distinct result slots. The spec also requires R-6's parity harness to drive both backends over the same corpus and query set and assert identical `skill_id` ordering (and, for backend-independent IDF, identical scores).

**Section sources**
- [spec.md:321-357](file://docs/specs/SPEC-066-skill-retrieval-ranking-fidelity/spec.md#L321-L357)
- [plan.md:227-252](file://docs/specs/SPEC-066-skill-retrieval-ranking-fidelity/plan.md#L227-L252)

## Detailed Component Analysis

### Requirement R-1: Score the `skill_id` slug
R-1 adds `skill_id` as a fourth scored field in `score()`. The measurement used `TAG_WEIGHT` (2.0); any other weight is explicitly unmeasured and rejected by the spec. The slug must tokenize consistently with the title, so separators such as `/` and `-` become separate tokens, and with R-4 active, CamelCase-derived tokens are included.

Acceptance criteria include stratum-A identifier-owner recovery against the committed label fixture, recording behaviour for queries naming identifiers absent from the corpus, and ensuring a slug-only match returns non-empty results on both backends once R-5 is delivered.

```mermaid
flowchart TD
Start(["score()"]) --> ReadSlug["Read skill.skill_id"]
ReadSlug --> TokenizeSlug["tokenize(slug)"]
TokenizeSlug --> CreditTokens["Credit slug tokens at OQ-1(b) weight"]
CreditTokens --> TitleTagBody["Continue title / tag / body scoring"]
TitleTagBody --> ReturnScore["Return total"]
```

**Diagram sources**
- [scoring.py:33-52](file://products/skills-hub/src/skills_hub/services/scoring.py#L33-L52)
- [plan.md:62-75](file://docs/specs/SPEC-066-skill-retrieval-ranking-fidelity/plan.md#L62-L75)

**Section sources**
- [spec.md:174-199](file://docs/specs/SPEC-066-skill-retrieval-ranking-fidelity/spec.md#L174-L199)
- [plan.md:108-123](file://docs/specs/SPEC-066-skill-retrieval-ranking-fidelity/plan.md#L108-L123)
- [tasks.md:129-139](file://docs/specs/SPEC-066-skill-retrieval-ranking-fidelity/tasks.md#L129-L139)

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
- [spec.md:201-260](file://docs/specs/SPEC-066-skill-retrieval-ranking-fidelity/spec.md#L201-L260)
- [plan.md:124-191](file://docs/specs/SPEC-066-skill-retrieval-ranking-fidelity/plan.md#L124-L191)

**Section sources**
- [spec.md:201-260](file://docs/specs/SPEC-066-skill-retrieval-ranking-fidelity/spec.md#L201-L260)
- [plan.md:124-191](file://docs/specs/SPEC-066-skill-retrieval-ranking-fidelity/plan.md#L124-L191)
- [tasks.md:190-227](file://docs/specs/SPEC-066-skill-retrieval-ranking-fidelity/tasks.md#L190-L227)

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
- [spec.md:261-283](file://docs/specs/SPEC-066-skill-retrieval-ranking-fidelity/spec.md#L261-L283)
- [plan.md:192-206](file://docs/specs/SPEC-066-skill-retrieval-ranking-fidelity/plan.md#L192-L206)

**Section sources**
- [spec.md:261-283](file://docs/specs/SPEC-066-skill-retrieval-ranking-fidelity/spec.md#L261-L283)
- [plan.md:192-206](file://docs/specs/SPEC-066-skill-retrieval-ranking-fidelity/plan.md#L192-L206)
- [tasks.md:124-129](file://docs/specs/SPEC-066-skill-retrieval-ranking-fidelity/tasks.md#L124-L129)

### Requirement R-4: CamelCase-splitting tokenization
R-4 changes `tokenize()` so CamelCase runs split into component words. The spec uses `KubePodCrashLooping` → `kube`, `pod`, `crash`, `looping` as the canonical example. The exact rule for digits, acronyms, and mixed runs is fixed in `plan.md` and covered by a committed case table.

The critical coupling is that the same whole-token decision must be applied in `tokenize()`, in R-2's `df` computation, and in R-5's prefilter. A partial application — keeping the whole token in one place and parts in another — is the failure mode this criterion exists to prevent.

```mermaid
flowchart TD
Start(["tokenize(text)"]) --> Lower["Lowercase original text"]
Lower --> SplitCamel["Split CamelCase/digit boundaries"]
SplitCamel --> ApplyPattern["Apply existing [a-z0-9]+ pattern to each part"]
ApplyPattern --> DecideWhole{"OQ-2 whole-token rule"}
DecideWhole --> |Keep both| EmitBoth["Emit whole token and its parts"]
DecideWhole --> |Parts only| EmitParts["Emit only parts"]
EmitBoth --> ReturnTokens["Return token list"]
EmitParts --> ReturnTokens
```

**Diagram sources**
- [scoring.py:28-30](file://products/skills-hub/src/skills_hub/services/scoring.py#L28-L30)
- [spec.md:284-354](file://docs/specs/SPEC-066-skill-retrieval-ranking-fidelity/spec.md#L284-L354)
- [plan.md:207-327](file://docs/specs/SPEC-066-skill-retrieval-ranking-fidelity/plan.md#L207-L327)

**Section sources**
- [spec.md:284-354](file://docs/specs/SPEC-066-skill-retrieval-ranking-fidelity/spec.md#L284-L354)
- [plan.md:207-327](file://docs/specs/SPEC-066-skill-retrieval-ranking-fidelity/plan.md#L207-L327)
- [tasks.md:140-189](file://docs/specs/SPEC-066-skill-retrieval-ranking-fidelity/tasks.md#L140-L189)

### Requirement R-5: Cross-backend parity for the new scorer
R-5 makes the Postgres prefilter admit every record the new scorer can rank above zero. Without it, R-1 does not ship (slug-only matches return zero rows on Postgres) and R-4 regresses recall (query-side splitting breaks the mirror between Python `tokenize()` and PostgreSQL `to_tsvector('simple', …)`).

Two strategies are considered:

| Strategy | Approach | Trade-off |
|---|---|---|
| Mirror tokenizer in SQL | Add `skill_id` to the `to_tsvector` expression and express R-4's split as an IMMUTABLE SQL function | Cleanest and keeps the index selective, but requires proving the function IMMUTABLE and pinning it against the Python case table. |
| Widen the prefilter (recommended) | Keep `to_tsvector('simple', …)` as-is, add `skill_id`, and additionally admit rows via a case-insensitive substring/LIKE arm for CamelCase-split tokens | Cannot drift from Python; failure mode is a slow sequential scan rather than a silent missing row. |

The migration must rebuild `idx_skills_search` because `_DDL` uses `CREATE INDEX IF NOT EXISTS`, which will not rebuild an existing index when its expression changes. `CREATE INDEX CONCURRENTLY` cannot run inside a transaction block, so the concurrency window must be explicit.

```mermaid
flowchart TD
Start(["Prefilter strategy"]) --> AddSlug["_SEARCH_VECTOR covers skill_id"]
AddSlug --> ChoosePath{"IMMUTABLE SQL tokenizer vs widen prefilter"}
ChoosePath --> |Mirror| CreateSQLFunc["Create IMMUTABLE SQL split function"]
CreateSQLFunc --> UpdateIndex["Update idx_skills_search expression"]
ChoosePath --> |Widen| KeepSimple["Keep to_tsvector('simple', …)"]
KeepSimple --> AddLikeArm["Add LIKE arm for CamelCase-split tokens"]
AddLikeArm --> UpdateIndex
UpdateIndex --> Migrate["Drop and recreate index (not CREATE INDEX IF NOT EXISTS)"]
Migrate --> Verify["Assert expressions remain identical"]
```

**Diagram sources**
- [spec.md:355-426](file://docs/specs/SPEC-066-skill-retrieval-ranking-fidelity/spec.md#L355-L426)
- [plan.md:328-393](file://docs/specs/SPEC-066-skill-retrieval-ranking-fidelity/plan.md#L328-L393)
- [skill_store.py:243-256](file://products/skills-hub/src/skills_hub/services/skill_store.py#L243-L256)

**Section sources**
- [spec.md:355-426](file://docs/specs/SPEC-066-skill-retrieval-ranking-fidelity/spec.md#L355-L426)
- [plan.md:328-393](file://docs/specs/SPEC-066-skill-retrieval-ranking-fidelity/plan.md#L328-L393)
- [tasks.md:233-290](file://docs/specs/SPEC-066-skill-retrieval-ranking-fidelity/tasks.md#L233-L290)

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
- [spec.md:427-458](file://docs/specs/SPEC-066-skill-retrieval-ranking-fidelity/spec.md#L427-L458)
- [plan.md:394-434](file://docs/specs/SPEC-066-skill-retrieval-ranking-fidelity/plan.md#L394-L434)
- [tasks.md:87-108](file://docs/specs/SPEC-066-skill-retrieval-ranking-fidelity/tasks.md#L87-L108)

**Section sources**
- [spec.md:427-458](file://docs/specs/SPEC-066-skill-retrieval-ranking-fidelity/spec.md#L427-L458)
- [plan.md:394-434](file://docs/specs/SPEC-066-skill-retrieval-ranking-fidelity/plan.md#L394-L434)
- [tasks.md:87-108](file://docs/specs/SPEC-066-skill-retrieval-ranking-fidelity/tasks.md#L87-L108)

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
- [spec.md:459-525](file://docs/specs/SPEC-066-skill-retrieval-ranking-fidelity/spec.md#L459-L525)
- [plan.md:435-495](file://docs/specs/SPEC-066-skill-retrieval-ranking-fidelity/plan.md#L435-L495)
- [tasks.md:315-339](file://docs/specs/SPEC-066-skill-retrieval-ranking-fidelity/tasks.md#L315-L339)

**Section sources**
- [spec.md:459-525](file://docs/specs/SPEC-066-skill-retrieval-ranking-fidelity/spec.md#L459-L525)
- [plan.md:435-495](file://docs/specs/SPEC-066-skill-retrieval-ranking-fidelity/plan.md#L435-L495)
- [tasks.md:315-339](file://docs/specs/SPEC-066-skill-retrieval-ranking-fidelity/tasks.md#L315-L339)

### Requirement R-8: Re-measurement on the shipped path
R-8 extends the offline evaluation harness to drive `PostgresSkillStore.search()` rather than calling `rank()` directly, so the prefilter is inside the measured path. It asserts the fixture's `body_md5` per document before computing metrics, reports results per backend, and discloses the known Q63 re-ordering regression and unchanged abstention rate.

If the Postgres-path gain is not outside the noise band, the spec defines a null-result path: publish the result, do not merge R-1..R-5, and record the outcome on the backlog row.

**Section sources**
- [spec.md:526-579](file://docs/specs/SPEC-066-skill-retrieval-ranking-fidelity/spec.md#L526-L579)
- [plan.md:496-544](file://docs/specs/SPEC-066-skill-retrieval-ranking-fidelity/plan.md#L496-L544)
- [tasks.md:344-389](file://docs/specs/SPEC-066-skill-retrieval-ranking-fidelity/tasks.md#L344-L389)

### Requirement R-9: Contract and living-doc updates
R-9 updates the skills-hub README endpoint summary, the `scoring.py` module docstring, SPEC-014 R-3's wording, relevant guides, the CHANGELOG, version files, and the spec index. It explicitly notes that no JSON schema changes are made: `score` is published on the HTTP response but appears in no `shared/shared-contracts` schema, and changing its value distribution is not a contract-schema change.

**Section sources**
- [spec.md:580-642](file://docs/specs/SPEC-066-skill-retrieval-ranking-fidelity/spec.md#L580-L642)
- [plan.md:545-589](file://docs/specs/SPEC-066-skill-retrieval-ranking-fidelity/plan.md#L545-L589)
- [tasks.md:392-460](file://docs/specs/SPEC-066-skill-retrieval-ranking-fidelity/tasks.md#L392-L460)

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
- [plan.md:590-626](file://docs/specs/SPEC-066-skill-retrieval-ranking-fidelity/plan.md#L590-L626)
- [tasks.md:18-79](file://docs/specs/SPEC-066-skill-retrieval-ranking-fidelity/tasks.md#L18-L79)
- [tasks.md:551-555](file://docs/specs/SPEC-066-skill-retrieval-ranking-fidelity/tasks.md#L551-L555)

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
- [scoring.py:1-97](file://products/skills-hub/src/skills_hub/services/scoring.py#L1-L97)
- [skill_store.py:1-518](file://products/skills-hub/src/skills_hub/services/skill_store.py#L1-L518)

**Section sources**
- [plan.md:590-626](file://docs/specs/SPEC-066-skill-retrieval-ranking-fidelity/plan.md#L590-L626)
- [tasks.md:18-79](file://docs/specs/SPEC-066-skill-retrieval-ranking-fidelity/tasks.md#L18-L79)

## Performance Considerations
SPEC-066 distinguishes several latency measurements:

| Measurement | Current state | Spec requirement |
|---|---|---|
| Offline pure-Python `rank()` p50 | 2.726 ms (eval-set) | Not end-to-end; excludes prefilter, HTTP, auth, and audit write. |
| Postgres search p95 | Not yet measured for the combined change | Must stay inside tool-gateway's 10.0 s `REQUEST_TIMEOUT_SECONDS`, measured end to end. |
| Catalog growth trigger | pgvector scale trigger is >2,000 skills or search p95 >300 ms | Retained as the reopening condition for vector retrieval; not reached today. |
| De-duplication cost | Not measured as a retrieval improvement | Intended as regression protection; dev corpus already clean (0 of 63 pools contain duplicates). |

The widened-prefilter strategy in R-5 is preferred because its failure mode is a slow query (loud and measurable) rather than a missing row (silent). At the current 18-row catalog this is acceptable; the plan notes that the >2,000-skill trigger is the point to revisit.

**Section sources**
- [spec.md:420-426](file://docs/specs/SPEC-066-skill-retrieval-ranking-fidelity/spec.md#L420-L426)
- [spec.md:643-685](file://docs/specs/SPEC-066-skill-retrieval-ranking-fidelity/spec.md#L643-L685)
- [plan.md:390-393](file://docs/specs/SPEC-066-skill-retrieval-ranking-fidelity/plan.md#L390-L393)
- [plan.md:675-709](file://docs/specs/SPEC-066-skill-retrieval-ranking-fidelity/plan.md#L675-L709)

## Troubleshooting Guide

### Symptom: Slug-only search returns results in memory but zero on Postgres
**Cause:** `_SEARCH_VECTOR` does not cover `skill_id`. A slug-only match scores positive in memory but is excluded by the Postgres prefilter.

**Resolution:** Deliver R-5 so `_SEARCH_VECTOR` includes `skill_id`, and verify that a slug-only query returns rows on Postgres as well as in memory.

**Section sources**
- [spec.md:114-120](file://docs/specs/SPEC-066-skill-retrieval-ranking-fidelity/spec.md#L114-L120)
- [spec.md:364-365](file://docs/specs/SPEC-066-skill-retrieval-ranking-fidelity/spec.md#L364-L365)
- [tasks.md:233-239](file://docs/specs/SPEC-066-skill-retrieval-ranking-fidelity/tasks.md#L233-L239)

### Symptom: CamelCase-aware queries lose recall on Postgres
**Cause:** Query-side `tokenize()` splits CamelCase, but PostgreSQL `to_tsvector('simple', …)` lowercases and splits on non-alphanumerics without splitting CamelCase. The mirror is broken.

**Resolution:** Either mirror the tokenizer in an IMMUTABLE SQL function or widen the prefilter with a LIKE arm for CamelCase-split tokens. The spec recommends widening because the failure mode is loud (slow query) rather than silent (missing row).

**Section sources**
- [spec.md:121-129](file://docs/specs/SPEC-066-skill-retrieval-ranking-fidelity/spec.md#L121-L129)
- [plan.md:337-355](file://docs/specs/SPEC-066-skill-retrieval-ranking-fidelity/plan.md#L337-L355)
- [tasks.md:240-252](file://docs/specs/SPEC-066-skill-retrieval-ranking-fidelity/tasks.md#L240-L252)

### Symptom: Index is not rebuilt after deployment
**Cause:** `_DDL` uses `CREATE INDEX IF NOT EXISTS`, which preserves the old index when its expression changes.

**Resolution:** Write a migration that drops and recreates the index. Test that the migration actually rebuilds the index on an existing database and that the rollback path runs.

**Section sources**
- [plan.md:358-372](file://docs/specs/SPEC-066-skill-retrieval-ranking-fidelity/plan.md#L358-L372)
- [tasks.md:259-270](file://docs/specs/SPEC-066-skill-retrieval-ranking-fidelity/tasks.md#L259-L270)

### Symptom: Duplicate bodies consume multiple result slots
**Cause:** `rank()` has no content-level de-duplication. Two sources covering the same files produce distinct `skill_id` values with identical bodies, and both occupy slots up to `limit`.

**Resolution:** Implement R-7's content-hash collapse before sorting and truncation. Use `md5(body)` as the identity key and retain the lowest `skill_id`.

**Section sources**
- [semantic-skill-retrieval-eval-set.md:55-127](file://docs/workspace/semantic-skill-retrieval-eval-set.md#L55-L127)
- [spec.md:459-525](file://docs/specs/SPEC-066-skill-retrieval-ranking-fidelity/spec.md#L459-L525)
- [tasks.md:315-333](file://docs/specs/SPEC-066-skill-retrieval-ranking-fidelity/tasks.md#L315-L333)

### Symptom: Existing exact-score assertions fail after R-4
**Cause:** The eight exact-score assertions in `test_scoring.py` encode the old tokenization, including `score("KubePodNotReady", skill) == 7.0`, which encodes the defect R-4 removes.

**Resolution:** Update the assertions deliberately with old and new expected values visible in review. Do not weaken them to vague comparisons.

**Section sources**
- [spec.md:334-346](file://docs/specs/SPEC-066-skill-retrieval-ranking-fidelity/spec.md#L334-L346)
- [plan.md:299-327](file://docs/specs/SPEC-066-skill-retrieval-ranking-fidelity/plan.md#L299-L327)
- [tasks.md:172-180](file://docs/specs/SPEC-066-skill-retrieval-ranking-fidelity/tasks.md#L172-L180)

## Conclusion
SPEC-066 is a narrowly scoped, measurement-driven improvement to the skills-hub lexical retriever. Its four fixes — indexing `skill_id`, corpus-derived IDF weighting, sublinear body-length normalization, and CamelCase-splitting tokenization — were shown sufficient to close the measured gap, but only as an indivisible package. The spec's most consequential addition is the cross-backend parity requirement: without R-5, R-1 does not ship and R-4 regresses recall; without R-6, the byte-identical invariant remains documented but unenforced.

**Updated** SPEC-066 is now `approved` as of 2026-10-02, with all six Open Questions resolved: OQ-1 established `TAG_WEIGHT` (2.0) for `skill_id` scoring; OQ-2 mandated sync-time Python-computed IDF statistics; OQ-3 preserved the byte-identical cross-backend invariant; OQ-4 accepted the Q63 re-ordering regression conditionally; OQ-5 selected prefix lexemes with versioned index names; and OQ-6 deferred sync-time overlap rejection. The work is blocked by Stage 0 verification tasks checking PostgreSQL prefix-lexeme behavior and the actual CamelCase variant that produced 0.711, but approval authorizes implementation to begin. The spec's delivery gate remains clear: every requirement must map to at least one asserting test, R-8 must re-measure on the shipped Postgres path, and the null-result path is a real possible ending rather than a failure.
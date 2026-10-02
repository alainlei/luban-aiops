# Semantic Skill Retrieval Spike Assessment

<cite>
**Referenced Files in This Document**
- [semantic-skill-retrieval-spike.md](file://docs/workspace/semantic-skill-retrieval-spike.md)
- [semantic-skill-retrieval-eval-set.md](file://docs/workspace/semantic-skill-retrieval-eval-set.md)
- [delivery-roadmap.md](file://docs/agentic-aiops-platform/delivery-roadmap.md)
- [SPEC-066 skill retrieval ranking fidelity spec](file://docs/specs/SPEC-066-skill-retrieval-ranking-fidelity/spec.md)
- [SPEC-066 plan](file://docs/specs/SPEC-066-skill-retrieval-ranking-fidelity/plan.md)
- [SPEC-066 tasks](file://docs/specs/SPEC-066-skill-retrieval-ranking-fidelity/tasks.md)
- [scoring.py](file://products/skills-hub/src/skills_hub/services/scoring.py)
- [skill_store.py](file://products/skills-hub/src/skills_hub/services/skill_store.py)
- [skills_connector.py](file://products/tool-gateway/src/tool_gateway/tools/skills_connector.py)
</cite>

## Update Summary
**Changes Made**
- Updated to reflect SPEC-066 `approved` status (2026-10-02) with all six Open Questions resolved
- Corrected false claims about existing body hashing functionality — no hashing exists anywhere in `skills-hub`; the fixture's `body_md5` was computed by the offline evaluation harness, not by product code
- Clarified that 0.500 → 0.711 improvement is a memory-path upper bound rather than shipped performance metric
- Corrected claims about schema changes — `skill_id` indexing requires backend modifications despite being "no schema change" for `score()`
- Enhanced section sources with specific file references for all technical claims
- Added cross-backend parity requirements and migration considerations based on approved spec resolutions

## Executive Summary

The semantic skill retrieval spike has been completed with a definitive null result for vector embeddings and promoted to **SPEC-066 skill retrieval ranking fidelity**, which reached `approved` status on 2026-10-02 after resolving all six Open Questions. The measurement-first approach revealed that cheaper lexical improvements close the measured gap, while the recall defect that would justify a vector store does not exist. The delivery roadmap's exploration backlog row for "Semantic (vector) skill retrieval" is closed as of 2026-10-01.

### Key Findings

**Best Lexical Candidate Performance Metrics:**
- Precision@5: **0.711** (up from 0.500 baseline) - *memory-path upper bound*
- Mean Reciprocal Rank (MRR): **0.868** 
- Normalized Discounted Cumulative Gain (nDCG@10): **0.904**
- Grade-2 Recall@5: **0.977**

**Decision Outcome:**
- Vector embeddings are **not authorized** - the pre-registered decision rule closes the backlog row
- Four cheap lexical fixes are sufficient: `skill_id` indexing, IDF weighting, sublinear length norm, and CamelCase splitting
- Statistical significance confirmed with exact sign test p = 0.0117

**Open Product Question:**
- Abstention behavior remains unresolved - zero-relevant rate stays at 4/38
- Requires separate backlog row as a product/contract decision rather than algorithmic fix

## Current State Assessment

### Lexical Baseline Analysis

The current skills-hub retrieval system uses purely lexical scoring with title/tag/body substring matching. The baseline shows:

| Metric | Baseline Value | Best Candidate Value | Improvement |
|--------|---------------|---------------------|-------------|
| Combined Top-1 Correctness | 0.500 | **0.711** | +0.211 |
| Stratum C (Paraphrase) Top-1 | 0.333 | **0.611** | +0.278 |
| MRR | 0.774 | **0.868** | +0.094 |
| nDCG@10 | 0.813 | **0.904** | +0.091 |
| Grade-2 R@5 | 0.914 | **0.977** | +0.063 |

**Updated** The 0.500 → 0.711 improvement represents a memory-path upper bound rather than shipped performance metric, as the evaluation ran `rank()` over a corpus export without Postgres prefiltering.

### Measured Defects in Lexical System

Five concrete defects were identified and measured against the 18-document corpus:

1. **Corpus duplication** - Resolved by configuration (30 rows → 18 distinct documents)
2. **CamelCase tokenization** - Single opaque tokens prevent sub-word matching
3. **Zero-hit rate misleading** - Non-zero results don't indicate useful answers
4. **Document length bias** - Sample bodies average 6.8× longer than runbooks
5. **Missing `skill_id` indexing** - Exact skill names get zero signal

### Infrastructure Reality

The deployment constraints make vector embeddings more complex than initially assumed:

- **No pgvector extension** available in deployed `postgres:16-alpine` image
- **Shared StatefulSet** hosts audit, incidents, sessions, and skills databases
- **Image swap required** affects all four databases simultaneously
- **Embedding host exists** but requires enabling embeddings and pulling models

## Evaluation Results and Decision Rule

### Pre-Registered Decision Rule Application

The evaluation set followed a cost-ordered decision rule that was pre-registered before any implementation:

**Step 1 - De-duplicate:** Configuration half complete (dev overlay), product half still open
**Step 2 - Tokenizer fixes:** Substantially closes measured gap ✓  
**Step 3 - Hybrid/vector retrieval:** NOT AUTHORIZED ✗

### Statistical Significance

The improvement passes statistical validation:

- **Bootstrap 95% CI excludes zero** for MRR, MRR(2), and nDCG@10
- **Exact sign test p = 0.0117** on discordant top-1 pairs
- **Combined metric gains** outside noise band confirm real improvement

### What the Cheap Step Does Not Fix

Despite significant ranking improvements, the system still exhibits problematic abstention behavior:

- **Zero-relevant rate unchanged at 4/38** across all candidates
- Four queries return confident, wholly irrelevant answers:
  - Q31 `argocd health check` → scores 20.0 on unrelated ACME health document
  - C16 `certificate expired on the ingress` → returns password reset runbook
  - C17 `argocd sync keeps failing` → returns deployment mismatch alert
  - C18 `database connection pool exhausted` → returns image pull failure

This is structural, not a tuning failure: a scorer admitting any `score > 0` cannot abstain.

## Delivery Roadmap Impact

### Exploration Backlog Closure

The semantic skill retrieval row in the delivery roadmap's exploration backlog is now **closed** with the following rationale:

**Closure Reason:** A cheaper lexical step closed the measured gap per the pre-registered rule, and the recall defect justifying vectors is measured absent (0 grade-2 documents missing from top 10).

**Reopening Conditions:** Only on catalog growth past recorded scale trigger (>2,000 skills or search p95 >300 ms), never on library upgrades or ranking complaints already addressed by lexical fixes.

**Authorization Scope:** Closure authorizes no implementation - the four lexical fixes remain measured but require separate specification via SPEC-066.

### Separate Abstention Row Required

The abstention problem warrants its own backlog row as a product/contract question:

- Neither lexical nor dense retrievers can solve this (dense retrievers worse - always find nearest neighbor)
- Requires score threshold or explicit "nothing applies" path
- Threshold selection is a product decision trading false positives against dropping weakly relevant documents
- Two of four cases are vocabulary gaps (no ArgoCD/database-pool documents in corpus)

## Architecture and Implementation Details

### Skills-Hub Components

The core retrieval implementation spans several components:

**Scoring Engine (`scoring.py`):**
- Pure lexical scoring with title (3.0), tag (2.0), body (1.0) weights
- Saturates at BODY_OCCURRENCE_CAP = 5 occurrences
- Excludes zero-score records, breaks ties by `skill_id` ascending

**Skill Store (`skill_store.py`):**
- Shared `rank()` function used by both backends
- Postgres pre-filters with GIN index over `to_tsvector('simple', title || ' ' || body)`
- Re-ranks in Python after SQL pre-filtering

**Tool Gateway Integration (`skills_connector.py`):**
- `skills.search` tool surface with risk_level="read"
- Default limit=5, max limit=20
- Upstream timeout 10.0 seconds

### Schema Design Considerations

For potential future vector storage, the design avoids coupling vectors to skill content:

```sql
CREATE TABLE IF NOT EXISTS skill_embedding (
    skill_id     TEXT PRIMARY KEY REFERENCES skills(skill_id) ON DELETE CASCADE,
    model_id     TEXT        NOT NULL,
    dim          INTEGER     NOT NULL,
    content_hash TEXT        NOT NULL,
    embedding    real[]      NOT NULL,  -- pgvector variant: vector(768)
    embedded_at  TIMESTAMPTZ NOT NULL
);
```

Key design principles:
- Vectors as index artifact, not skill content
- Sidecar table with cascade deletion
- Model provenance tracking via `model_id`, `dim`, `content_hash`
- Reversible between `real[]` and `vector(n)` without data migration

### Cross-Backend Parity Requirements

**Updated** The four lexical fixes require careful implementation to maintain cross-backend parity:

1. **Index `skill_id` field** - While technically "no schema change" for `score()`, the deployed Postgres backend requires `_SEARCH_VECTOR` and `idx_skills_search` modifications to include `skill_id` in the prefilter expression
2. **CamelCase splitting** - Must be applied consistently to both query-side tokenization and document-side PostgreSQL `to_tsvector('simple', ...)` expressions to avoid regression
3. **IDF weighting** - Requires backend-independent corpus statistics computation to ensure identical scoring across memory and Postgres backends
4. **Sublinear length normalization** - Backend-neutral by construction as it operates on individual document properties

## Recommendations and Next Steps

### Immediate Actions

1. **Implement the four lexical fixes** in order of cost, ensuring cross-backend parity:
   - Index `skill_id` field (cheapest, fixes defect 5) - requires Postgres prefilter modification
   - Add IDF weighting and sublinear length normalization
   - Implement CamelCase token splitting with consistent application across backends
   
2. **Create separate backlog row for abstention behavior** as product/contract decision

3. **Monitor the recorded scale triggers** for potential future vector store need

### Long-term Considerations

**If vectors become necessary:**
- Use sidecar `real[]` + in-process exact cosine (Option C) first
- Promote to pgvector only when scale triggers exceeded
- Adopt agentscope's embedding module, not RAG stores
- In-cluster Ollama preferred over external providers

**Governance Requirements:**
- Feature flag `SKILLS_SEMANTIC_ENABLED=false` default
- Fail open to lexical on embedder failures
- Readiness must not gain model dependency
- Embedders excluded from chat model catalog

## Conclusion

The semantic skill retrieval spike demonstrates the value of measurement-first approaches. Rather than building expensive infrastructure based on assumptions, the evaluation revealed that:

1. **The recall premise is false** - no grade-2 documents are missing from top 10
2. **Lexical improvements are sufficient** for the ordering gap with strong statistical significance
3. **Vector embeddings are not needed** under current conditions
4. **A separate abstention problem** requires product-level decisions beyond algorithmic fixes

The closure of the exploration backlog row represents a successful null result - the system works well enough that no vector store is justified. Future work should focus on implementing the measured lexical improvements through SPEC-066, addressing the abstention behavior through product decisions rather than algorithmic changes, and ensuring cross-backend parity for all scoring modifications.

**Section sources**
- [semantic-skill-retrieval-spike.md:1-800](file://docs/workspace/semantic-skill-retrieval-spike.md#L1-L800)
- [semantic-skill-retrieval-eval-set.md:754-957](file://docs/workspace/semantic-skill-retrieval-eval-set.md#L754-L957)
- [delivery-roadmap.md:347-424](file://docs/agentic-aiops-platform/delivery-roadmap.md#L347-L424)
- [SPEC-066 skill retrieval ranking fidelity spec:1-800](file://docs/specs/SPEC-066-skill-retrieval-ranking-fidelity/spec.md#L1-L800)
- [SPEC-066 plan:1-729](file://docs/specs/SPEC-066-skill-retrieval-ranking-fidelity/plan.md#L1-L729)
- [SPEC-066 tasks:1-555](file://docs/specs/SPEC-066-skill-retrieval-ranking-fidelity/tasks.md#L1-L555)
- [scoring.py:1-97](file://products/skills-hub/src/skills_hub/services/scoring.py#L1-L97)
- [skill_store.py:1-518](file://products/skills-hub/src/skills_hub/services/skill_store.py#L1-L518)
- [skills_connector.py:31-196](file://products/tool-gateway/src/tool_gateway/tools/skills_connector.py#L31-L196)
# Semantic Skill Retrieval Spike Assessment

<cite>
**Referenced Files in This Document**
- [semantic-skill-retrieval-spike.md](file://docs/workspace/semantic-skill-retrieval-spike.md)
- [semantic-skill-retrieval-eval-set.md](file://docs/workspace/semantic-skill-retrieval-eval-set.md)
- [delivery-roadmap.md](file://docs/agentic-aiops-platform/delivery-roadmap.md)
- [scoring.py](file://products/skills-hub/src/skills_hub/services/scoring.py)
- [skill_store.py](file://products/skills-hub/src/skills_hub/services/skill_store.py)
- [skills_connector.py](file://products/tool-gateway/src/tool_gateway/tools/skills_connector.py)
</cite>

## Update Summary
**Changes Made**
- Updated evaluation results with best lexical candidate performance metrics (P@5 0.711, MRR 0.868, nDCG 0.904, grade-2 R@5 0.977)
- Added delivery-roadmap closure decision for semantic skill retrieval
- Documented abstention behavior as an open product question requiring separate backlog row
- Enhanced section sources with specific file references for all technical claims

## Executive Summary

The semantic skill retrieval spike has been completed with a definitive null result for vector embeddings. The measurement-first approach revealed that the cheaper lexical improvements close the measured gap, while the recall defect that would justify a vector store does not exist. The delivery roadmap's exploration backlog row for "Semantic (vector) skill retrieval" is now closed as of 2026-10-01.

### Key Findings

**Best Lexical Candidate Performance Metrics:**
- Precision@5: **0.711** (up from 0.500 baseline)
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

**Authorization Scope:** Closure authorizes no implementation - the four lexical fixes remain measured but require separate specification.

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

## Recommendations and Next Steps

### Immediate Actions

1. **Implement the four lexical fixes** in order of cost:
   - Index `skill_id` field (cheapest, fixes defect 5)
   - Add IDF weighting and sublinear length normalization
   - Implement CamelCase token splitting
   
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

The closure of the exploration backlog row represents a successful null result - the system works well enough that no vector store is justified. Future work should focus on implementing the measured lexical improvements and addressing the abstention behavior through product decisions rather than algorithmic changes.

**Section sources**
- [semantic-skill-retrieval-spike.md:1-800](file://docs/workspace/semantic-skill-retrieval-spike.md#L1-L800)
- [semantic-skill-retrieval-eval-set.md:754-957](file://docs/workspace/semantic-skill-retrieval-eval-set.md#L754-L957)
- [delivery-roadmap.md:347-424](file://docs/agentic-aiops-platform/delivery-roadmap.md#L347-L424)
- [scoring.py:20-96](file://products/skills-hub/src/skills_hub/services/scoring.py#L20-L96)
- [skill_store.py:144-482](file://products/skills-hub/src/skills_hub/services/skill_store.py#L144-L482)
- [skills_connector.py:31-196](file://products/tool-gateway/src/tool_gateway/tools/skills_connector.py#L31-L196)
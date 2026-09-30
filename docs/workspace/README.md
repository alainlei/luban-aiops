# Workspace Documentation

This folder contains the documents that define how the platform should be organized as a modular workspace.

## Recommended Reading Order

1. `workspace-model.md`
2. `product-boundaries.md`
3. `product-structure-review.md`
4. `backend-service-layout-convention.md`
5. `python-container-strategy.md`
6. `repository-reorganization-plan.md`
7. `github-repository-governance.md`

## Document Set

- `workspace-model.md`
  - defines the workspace structure, design principles, dependency rules, and module layout

- `product-boundaries.md`
  - defines the responsibility boundaries, integration points, and ownership model for each product project

- `repository-reorganization-plan.md`
  - explains how the current repository and design set map into the new workspace model

- `github-repository-governance.md`
  - defines the baseline GitHub settings, labels, milestones, and review controls for the workspace repository

- `product-structure-review.md`
  - compares the current implementation structure of each workspace product and recommends where normalization should happen next

- `backend-service-layout-convention.md`
  - defines the recommended package structure for backend products that expose HTTP service boundaries

- `python-container-strategy.md`
  - defines the current Python container baseline, evaluates the environment-specific base image option, and records the recommended migration path

- [long-term-operator-memory-spike.md](long-term-operator-memory-spike.md)
  - evaluates the three agentscope 2.0.8 long-term-memory middlewares (`AgenticMemory`, `Mem0`, `ReME`) against SPEC-018's four-point adoption gate and the live audit record; finds all three fail gate points 1–3 with no passing configuration, finds the cross-session continuity need unevidenced (107 of 124 sessions single-turn, every session and incident table TTL-swept to 0 rows), and recommends closing the backlog row in favour of the governed SPEC-039 / SPEC-044/045 knowledge path; assessment only

- [mcp-exposure-spike.md](mcp-exposure-spike.md)
  - assesses independent MCP toolsets consumed by tool-gateway; recommends retaining native connectors until a concrete use case justifies a pilot, not exposing Luban workflows or promoting an implementation spec

- [mcp-ingestion-spike.md](mcp-ingestion-spike.md)
  - records that the MCP reopen trigger is now met, and the current MCP direction — tool-gateway as the MCP *client* of external servers via an ingestion connector beneath the gateway, staged ServiceNow → Ansible → Windows; assessment only, no implementation, ADR, or spec authorized

- [semantic-skill-retrieval-eval-set.md](semantic-skill-retrieval-eval-set.md)
  - the measurement artifact for gate 1 of the semantic-retrieval spike: an 18-document catalogue, the 63 real audit queries with their lexical candidate pools, and the labeling protocol, label sheet, metrics, and pre-registered decision rule operations needs to produce a baseline; records three measured lexical defects that no vector store is required to fix; labeling and offline scoring only, no implementation authorized

- [semantic-skill-retrieval-spike.md](semantic-skill-retrieval-spike.md)
  - evaluates semantic skill retrieval against skills-hub's lexical `rank()` baseline using live corpus and audit evidence; recommends measuring before building, corrects the `pgvector`-is-free premise, and records the sidecar-schema, embedding, gating, and go/no-go criteria; assessment only

## Relationship To The Platform Study

These documents extend the main platform study in `docs/agentic-aiops-platform/` by answering:

- how the platform should be split into products
- how those products should relate to one another
- how the repository should evolve into a modular workspace

## Current Status

- Workspace model: completed and documented
- Product boundaries: completed and documented
- Product structure review: completed and documented
- Backend service layout convention: completed and documented
- Python container strategy: completed and documented
- Repository reorganization plan: completed and documented
- GitHub repository governance: completed and documented

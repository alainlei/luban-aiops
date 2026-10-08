# Repository Reorganization Plan

> **Status: executed — historical planning doc.** This plan was written when the
> repository was still a platform study with only an initial directory skeleton, and it
> has since been carried out: `products/` and `shared/` now hold the implemented, tested,
> deployable build products. The "Current State" section below describes that original
> pre-reorganization starting point, not today's layout, and is retained only as a record
> of the reorganization rationale. For the present structure see the
> [architecture overview](../guides/architecture-overview.md) and the
> [spec index](../specs/README.md).

## Objective

Define how the current repository should evolve from a platform study repository into a modular workspace with multiple product-oriented projects.

## Current State

The repository currently contains:

- the platform study in `docs/agentic-aiops-platform/`
- the initial workspace documentation in `docs/workspace/`
- an initial modular directory skeleton under `products/` and `shared/`

This is a good starting point because it allows the conceptual design to remain visible while the implementation structure is introduced.

## Target State

The repository should become a workspace with:

- product projects under `products/`
- shared modules under `shared/`
- design and planning documents under `docs/`
- deployment and environment assets under `shared/platform-ops`

## Reorganization Strategy

### Step 1: Keep the study documents intact

Do not dissolve the design set into many small notes.

The current study documents remain the architectural record for:

- framework selection
- reference architecture
- MVP definition
- identity and authorization
- policy rules
- implementation sequencing
- delivery roadmap

### Step 2: Add workspace guidance

Add workspace-level documents that explain:

- why the repository is modular
- what each product project owns
- how boundaries are enforced

This is now provided in:

- `docs/workspace/workspace-model.md`
- `docs/workspace/product-boundaries.md`
- `docs/workspace/repository-reorganization-plan.md`

### Step 3: Add project-local README files

Each product and shared module should start with a local `README.md` that explains:

- purpose
- ownership
- current scope
- expected integration points

This keeps the workspace navigable even before code is added.

### Step 4: Start implementation by release, not by isolated technology stacks

Implementation should follow the staged roadmap and backlog rather than filling every project directory with code at once.

Examples:

- early release work will mostly land in `operator-portal`, `agent-platform`, `identity-broker`, `tool-gateway`, and `shared/platform-ops`
- later release work will expand `skills-hub`, `policy-center`, and `execution-runtime`

### Step 5: Stabilize contracts before extracting repositories

If, in the future, some product projects need independent repositories, only extract them after:

- APIs are stable
- ownership is clear
- shared dependencies are minimized
- release cadence differs enough to justify the split

## Mapping Existing Documents To Workspace Concerns

| Existing Document | Primary Workspace Relevance |
|---|---|
| `part-1-decision-matrix.md` | `agent-platform` selection and platform foundation |
| `part-2-reference-architecture.md` | overall workspace architecture and service boundaries |
| `identity-and-authorization-design.md` | `identity-broker`, `operator-portal`, `policy-center` |
| `authorization-matrix.md` | `policy-center` and approval-aware UI flows |
| `policy-specification.md` | `policy-center`, `execution-runtime`, `agent-platform` control integration |
| `delivery-roadmap.md` | release stacking across the whole workspace |
| `workspace-model.md` | workspace-wide structural guidance |
| `product-boundaries.md` | per-project ownership and interfaces |

## Suggested Implementation Order Across The Workspace

### First Wave

Focus on:

- `shared/platform-ops`
- `products/operator-portal`
- `products/agent-platform`
- `products/identity-broker`
- `products/tool-gateway`

Reason:

These enable the first runnable and validateable platform slice.

### Second Wave

Focus on:

- `products/skills-hub`
- deeper read-only and incident workflows across the existing products

Reason:

These add grounded operational value without introducing broad write risk.

### Third Wave

Focus on:

- `products/policy-center`
- `products/execution-runtime`

Reason:

These are critical for bounded action, but they should arrive after the platform has stable identity, evidence, and operator-facing value.

## Repository Rules To Preserve Modularity

### Rule 1

Keep each product project documented even before implementation is complete.

### Rule 2

Do not place policy, identity, or execution logic into the wrong project just to move faster.

### Rule 3

Use shared contracts instead of ad hoc cross-project object sharing.

### Rule 4

Keep release planning aligned with end-to-end user and operator workflows.

### Rule 5

Prefer one repository workspace initially rather than premature multi-repository extraction.

## Recommended Next Steps

### 1

Add local `README.md` files to every product and shared module.

### 2

Create initial service and contract placeholders in the first-wave projects.

### 3

Define `Release 0` and `Release 1` work breakdown using the new workspace structure.

### 4

Keep updating the study and workspace docs together so architectural intent remains visible during implementation.

## Final Recommendation

The repository should evolve in place into a modular workspace.

That approach keeps the design record intact, makes implementation structure clearer, and avoids premature fragmentation into multiple repositories before the platform contracts are mature.

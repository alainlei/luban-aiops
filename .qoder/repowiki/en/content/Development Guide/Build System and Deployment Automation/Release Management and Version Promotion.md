# Release Management and Version Promotion

<cite>
**Referenced Files in This Document**
- [README.md](file://README.md)
- [Makefile](file://Makefile)
- [defaults.mk](file://mk/defaults.mk)
- [image.mk](file://mk/image.mk)
- [kustomization.yaml](file://shared/platform-ops/gitops/dev-k8s/base/kustomization.yaml)
- [deploy.sh](file://shared/platform-ops/gitops/dev-k8s/deploy.sh)
- [2026-07-26-release-0-runtime-and-dev-k8s-overlays.md](file://docs/agentic-aiops-platform/release-notes/2026-07-26-release-0-runtime-and-dev-k8s-overlays.md)
- [delivery-roadmap.md](file://docs/agentic-aiops-platform/delivery-roadmap.md)
- [2026-09-27-clock-sensitive-document-fixtures.md](file://docs/agentic-aiops-platform/release-notes/2026-09-27-clock-sensitive-document-fixtures.md)
- [VERSION](file://VERSION)
- [validate_version.py](file://shared/shared-contracts/scripts/validate_version.py)
- [test_documents.py](file://products/agent-platform/tests/test_documents.py)
- [test_operation_documents.py](file://products/agent-platform/tests/test_operation_documents.py)
</cite>

## Update Summary
**Changes Made**
- Added v0.43.1 patch release documentation focusing on test fixture stability improvements
- Updated version coordination section to reflect the current 0.43.2 platform version
- Enhanced test fixture stability guidance with specific examples from the clock-sensitive document fixtures fix
- Updated verification gate documentation to include the complete validation suite for patch releases

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
This document describes the release management, version promotion, automated releases, and deployment pipelines for the Agentic AIOps platform. It explains how versions are coordinated across products and images, how GitOps overlays render deployments, how secrets and configuration are synchronized, and how verification gates protect promotions. It also covers rollback strategies, hotfix handling, monitoring during releases, validation after deployment, auditability, and compliance considerations grounded in the repository's current build and deploy tooling. The platform currently operates at version 0.43.2, with recent patch releases like v0.43.1 demonstrating the importance of test fixture stability and version coordination across all platform products.

## Project Structure
The workspace is organized around product-oriented services under `products/`, shared contracts and operations under `shared/`, and documentation under `docs/`. The root Makefile orchestrates cross-cutting concerns: testing, linting, image building, policy validation, overlay rendering, and deployment to a Kubernetes cluster via GitOps overlays.

```mermaid
graph TB
A["Root Makefile"] --> B["Per-product builds<br/>and tests"]
A --> C["Kustomize overlay checks"]
A --> D["Policy validation"]
A --> E["Version lockstep validation"]
A --> F["Deploy dev-k8s overlay"]
F --> G["Secret provisioning scripts"]
F --> H["Runtime config ConfigMaps"]
```

**Diagram sources**
- [Makefile:14-46](file://Makefile#L14-L46)
- [Makefile:96-183](file://Makefile#L96-L183)
- [kustomization.yaml:6-20](file://shared/platform-ops/gitops/dev-k8s/base/kustomization.yaml#L6-L20)
- [deploy.sh:1-62](file://shared/platform-ops/gitops/dev-k8s/deploy.sh#L1-L62)

**Section sources**
- [README.md:15-54](file://README.md#L15-L54)
- [Makefile:14-46](file://Makefile#L14-L46)

## Core Components
- Coordinated image tagging and build state:
  - A single semver-driven tag is computed from the root VERSION file and propagated to all product images.
  - Build outputs are recorded in an `.images.env` file consumed by the deploy step.
- Verification gate:
  - Runs per-product tests, Kustomize overlay renders, policy validation, scenario evaluation, version lockstep checks, and secret vocabulary validation.
- Policy synchronization:
  - A canonical policy bundle is copied into consumer locations; diffs and validations are provided.
- Secret and configuration synchronization:
  - Deployment script provisions secrets (delegation, audit ingestion, execution signing/handoff, skills credentials, incident credentials, browser credentials, OTel credentials), initializes databases, and reconciles OIDC clients.
- Runtime configuration:
  - Kustomization generates a runtime ConfigMap from environment files for each service.

**Section sources**
- [Makefile:36-64](file://Makefile#L36-L64)
- [Makefile:96-129](file://Makefile#L96-L129)
- [Makefile:132-168](file://Makefile#L132-L168)
- [Makefile:171-183](file://Makefile#L171-L183)
- [kustomization.yaml:6-20](file://shared/platform-ops/gitops/dev-k8s/base/kustomization.yaml#L6-L20)
- [deploy.sh:11-52](file://shared/platform-ops/gitops/dev-k8s/deploy.sh#L11-L52)

## Architecture Overview
The release pipeline coordinates code, images, and deployed artifacts through a deterministic flow:

```mermaid
sequenceDiagram
participant Dev as "Developer"
participant CI as "CI / Local make"
participant IMG as "Image Builder"
participant REG as "Registry"
participant KO as "Kustomize Overlay"
participant DEP as "Deploy Script"
participant K8S as "Cluster"
Dev->>CI : Run verify (tests, overlays, policies, version)
CI->>IMG : make build (coordinated IMAGE_TAG)
IMG-->>CI : .images.env with tagged images
CI->>REG : make push (optional registry re-tag/push)
CI->>KO : kustomize build dev-k8s (rendered manifests)
CI->>DEP : make deploy (dev-k8s)
DEP->>K8S : Apply resources + provision secrets/config
K8S-->>Dev : Services running with coordinated images
```

**Diagram sources**
- [Makefile:178-183](file://Makefile#L178-L183)
- [Makefile:96-129](file://Makefile#L96-L129)
- [kustomization.yaml:45-71](file://shared/platform-ops/gitops/dev-k8s/base/kustomization.yaml#L45-L71)
- [deploy.sh:1-62](file://shared/platform-ops/gitops/dev-k8s/deploy.sh#L1-L62)

## Detailed Component Analysis

### Version Promotion and Tag Management
- Single source of truth:
  - The root VERSION file defines the platform version used to prefix coordinated image tags. Currently set to 0.43.2.
- Tag computation:
  - Tags follow the pattern `<semver>-<prefix>[-<profile>]-<gitsha>[-dirty-<timestamp>]`.
  - Prefix/profile can be set via defaults; profile supports overlays like runtime profiles.
- Lockstep enforcement:
  - A dedicated target validates that the root version aligns with product metadata and portal references using `validate_version.py`.
- Image state:
  - After building, a `.images.env` file records the exact image references used for deployment, enabling reproducible rollouts and audits.

```mermaid
flowchart TD
Start(["Start build"]) --> ReadVer["Read root VERSION"]
ReadVer --> ComputeTag["Compute IMAGE_TAG<br/>(version + prefix + profile + sha)"]
ComputeTag --> BuildImages["Build all product images with IMAGE_TAG"]
BuildImages --> WriteState["Write .images.env with tagged refs"]
WriteState --> Validate["validate-version (lockstep)"]
Validate --> End(["Ready for deploy/push"])
```

**Diagram sources**
- [Makefile:39-64](file://Makefile#L39-L64)
- [Makefile:96-109](file://Makefile#L96-L109)
- [Makefile:161-163](file://Makefile#L161-L163)

**Section sources**
- [Makefile:39-64](file://Makefile#L39-L64)
- [Makefile:96-109](file://Makefile#L96-L109)
- [Makefile:161-163](file://Makefile#L161-L163)
- [VERSION:1-2](file://VERSION#L1-L2)

### Automated Releases and CI Gates
- Pre-commit/pre-push gate:
  - `make verify` runs tests, overlay renders, policy validation, scenario evaluation, version lockstep, and secret vocabulary validation.
- Per-product routines:
  - Each product exposes its own test, build, lint targets; the root Makefile aggregates them.
- Optional kind loading:
  - Built images can be auto-loaded into a local kind cluster for fast iteration.

```mermaid
flowchart TD
V["make verify"] --> T["Run product tests"]
V --> O["Render overlays (kustomize build)"]
V --> P["Validate policy bundle"]
V --> S["Validate policy scenarios"]
V --> VV["Validate version lockstep"]
V --> SV["Validate secret vocabulary"]
T --> |pass| Gate["Gate passes"]
O --> |fail| GateFail["Overlay error"]
P --> |fail| GateFail
S --> |fail| GateFail
VV --> |fail| GateFail
SV --> |fail| GateFail
```

**Diagram sources**
- [Makefile:178-179](file://Makefile#L178-L179)
- [Makefile:81-87](file://Makefile#L81-L87)

**Section sources**
- [Makefile:14-23](file://Makefile#L14-L23)
- [Makefile:81-87](file://Makefile#L81-L87)
- [Makefile:178-179](file://Makefile#L178-L179)

### Test Fixture Stability and Patch Release Handling
The v0.43.1 patch release demonstrates the critical importance of test fixture stability in release management. This patch addressed clock-sensitive test failures where hardcoded timestamps aged out due to retention policies.

**Key lessons from v0.43.1:**
- **Clock-relative fixtures**: Tests should derive timestamps from `datetime.now(timezone.utc)` rather than using hardcoded dates
- **Retention awareness**: Understanding store sweep behavior (RETENTION_DAYS = 30) when writing test data
- **Patch release scope**: Test-only fixes maintain version lockstep without affecting production behavior

```mermaid
flowchart TD
TestFix["Test Fix Required"] --> Identify["Identify clock-sensitive fixtures"]
Identify --> Analyze["Analyze retention sweep behavior"]
Analyze --> Fix["Update to datetime.now(timezone.utc)"]
Fix --> Verify["Verify full make verify gate"]
Verify --> PatchRelease["Create patch release (v0.43.1)"]
```

**Diagram sources**
- [2026-09-27-clock-sensitive-document-fixtures.md:9-16](file://docs/agentic-aiops-platform/release-notes/2026-09-27-clock-sensitive-document-fixtures.md#L9-L16)
- [test_documents.py:281-285](file://products/agent-platform/tests/test_documents.py#L281-L285)
- [test_operation_documents.py:143-148](file://products/agent-platform/tests/test_operation_documents.py#L143-L148)

**Section sources**
- [2026-09-27-clock-sensitive-document-fixtures.md:1-69](file://docs/agentic-aiops-platform/release-notes/2026-09-27-clock-sensitive-document-fixtures.md#L1-L69)
- [test_documents.py:278-306](file://products/agent-platform/tests/test_documents.py#L278-L306)
- [test_operation_documents.py:141-159](file://products/agent-platform/tests/test_operation_documents.py#L141-L159)

### Secrets Synchronization Across Environments
- Deploy-time provisioning:
  - The deploy script calls multiple sync scripts to create or update secrets required by services (delegation, audit ingestion, execution signing/handoff, skills, incidents, browser credentials, OTel).
- External injection support:
  - Each sync script respects skip flags so CI can inject secrets externally without failing open.
- Idempotent database setup:
  - Sessions database initialization is idempotent and does not involve secrets.

```mermaid
sequenceDiagram
participant Op as "Operator / CI"
participant DS as "deploy.sh"
participant SS as "sync-* scripts"
participant K as "Kubernetes"
Op->>DS : make deploy
DS->>SS : Provision delegation secrets
DS->>SS : Provision audit ingestion secrets
DS->>SS : Provision execution signing/handoff secrets
DS->>SS : Provision skills/incident/browser/OTel secrets
DS->>SS : Initialize sessions DB
DS->>K : Apply resources and reconcile OIDC client
```

**Diagram sources**
- [deploy.sh:11-58](file://shared/platform-ops/gitops/dev-k8s/deploy.sh#L11-L58)

**Section sources**
- [deploy.sh:1-62](file://shared/platform-ops/gitops/dev-k8s/deploy.sh#L1-L62)

### Database Migrations and Configuration Updates
- Runtime configuration:
  - Kustomization generates a runtime ConfigMap from environment files for each service, centralizing configuration updates.
- Database initialization:
  - SQL init scripts are included via ConfigMap generators and applied during deployment to prepare schemas for skills, incidents, and sessions.

```mermaid
flowchart TD
EnvFiles["Service env files"] --> CM["ConfigMap generator"]
CM --> Deploy["Kustomize apply"]
InitSQL["Init SQL scripts"] --> CM
Deploy --> Pods["Services mount ConfigMap"]
```

**Diagram sources**
- [kustomization.yaml:6-44](file://shared/platform-ops/gitops/dev-k8s/base/kustomization.yaml#L6-L44)

**Section sources**
- [kustomization.yaml:6-44](file://shared/platform-ops/gitops/dev-k8s/base/kustomization.yaml#L6-L44)

### Changelog Generation and Release Notes
- Release notes directory:
  - The project maintains dated release notes under `docs/agentic-aiops-platform/release-notes/`.
- Delivery roadmap:
  - The roadmap documents release stacking logic and completion signals, guiding when features are promoted across environments.

**Section sources**
- [2026-07-26-release-0-runtime-and-dev-k8s-overlays.md:99-132](file://docs/agentic-aiops-platform/release-notes/2026-07-26-release-0-runtime-and-dev-k8s-overlays.md#L99-L132)
- [delivery-roadmap.md:287-296](file://docs/agentic-aiops-platform/delivery-roadmap.md#L287-L296)
- [delivery-roadmap.md:528-551](file://docs/agentic-aiops-platform/delivery-roadmap.md#L528-L551)

### Approval Workflows and Quality Checks
- Policy validation and diffing:
  - Canonical policy bundles are validated against schemas and evaluated against scenario expectations; diffs between canonical and candidate bundles are supported.
- Version and secret vocabulary lockstep:
  - Targets ensure consistent versions and secret definitions across components before promotion.

**Section sources**
- [Makefile:132-168](file://Makefile#L132-L168)

### Rollback Procedures and Hotfix Handling
- Rollback strategy:
  - Because images are tagged deterministically and stored in `.images.env`, rollback consists of redeploying the previous overlay with the prior IMAGE_TAG.
- Hotfix process:
  - For urgent fixes, rebuild images with a new tag and redeploy the overlay; use the same secret provisioning and configuration flow to maintain consistency.
- Emergency release handling:
  - Use external secret injection flags to bypass local secret provisioning in CI while ensuring fail-closed behavior where applicable.

### Monitoring and Alerting During Releases
- Observability integration:
  - OTel credentials are provisioned at deploy time to enable observability backends; this supports monitoring and alerting during and after releases.
- Audit trail:
  - The platform ingests durable audit events, which can be queried post-deployment to validate release behavior and detect anomalies.

**Section sources**
- [deploy.sh:49-52](file://shared/platform-ops/gitops/dev-k8s/deploy.sh#L49-L52)

### Deployment Validation and Post-Release Verification
- E2E demos:
  - The e2e target runs demo scripts against a deployed cluster to validate core flows end-to-end.
- Overlay rendering:
  - Kustomize build checks ensure manifests are valid before deployment.

**Section sources**
- [Makefile:193-204](file://Makefile#L193-L204)
- [Makefile:171-176](file://Makefile#L171-L176)

### Relationship Between Code Versions, Container Images, and Deployed Artifacts
- Code to image:
  - Each product builds a container image tagged with the coordinated IMAGE_TAG derived from the root VERSION and git SHA.
- Image to artifact:
  - `.images.env` captures the exact image references used for deployment, linking code commits to deployed artifacts.
- Artifact to overlay:
  - The dev-k8s overlay consumes these images and applies resources to the cluster, including ConfigMaps and services.

```mermaid
graph LR
Code["Git commit"] --> Tag["IMAGE_TAG<br/>(VERSION + sha)"]
Tag --> Images["Product images"]
Images --> State[".images.env"]
State --> Overlay["dev-k8s overlay"]
Overlay --> Cluster["Kubernetes resources"]
```

**Diagram sources**
- [Makefile:39-64](file://Makefile#L39-L64)
- [Makefile:96-109](file://Makefile#L96-L109)
- [kustomization.yaml:45-71](file://shared/platform-ops/gitops/dev-k8s/base/kustomization.yaml#L45-L71)

**Section sources**
- [Makefile:39-64](file://Makefile#L39-L64)
- [Makefile:96-109](file://Makefile#L96-L109)

### Audit Trails and Compliance Requirements
- Durable audit trail:
  - The platform ingests and stores audit events, providing a queryable record of actions and decisions.
- Secret governance:
  - Secret vocabulary validation ensures consistent secret naming and usage across components, supporting compliance and security reviews.
- Policy enforcement:
  - Canonical policy bundles are validated and scenario-tested to enforce authorization and operational constraints consistently across environments.

**Section sources**
- [Makefile:132-168](file://Makefile#L132-L168)
- [deploy.sh:11-52](file://shared/platform-ops/gitops/dev-k8s/deploy.sh#L11-L52)

## Dependency Analysis
The root Makefile depends on per-product Makefiles and shared fragments to orchestrate builds, tests, and deployments. Kustomize overlays depend on service manifests and generated ConfigMaps. The deploy script depends on multiple secret provisioning scripts and optional OIDC reconciliation.

```mermaid
graph TB
RootMF["Root Makefile"] --> PMF["Per-product Makefiles"]
RootMF --> MKD["mk/defaults.mk"]
RootMF --> MKI["mk/image.mk"]
RootMF --> KO["Kustomize overlays"]
RootMF --> DS["deploy.sh"]
DS --> SS["sync-* scripts"]
KO --> CM["ConfigMaps"]
```

**Diagram sources**
- [Makefile:14-46](file://Makefile#L14-L46)
- [defaults.mk:1-53](file://mk/defaults.mk#L1-L53)
- [image.mk:1-58](file://mk/image.mk#L1-L58)
- [kustomization.yaml:6-71](file://shared/platform-ops/gitops/dev-k8s/base/kustomization.yaml#L6-L71)
- [deploy.sh:1-62](file://shared/platform-ops/gitops/dev-k8s/deploy.sh#L1-L62)

**Section sources**
- [Makefile:14-46](file://Makefile#L14-L46)
- [defaults.mk:1-53](file://mk/defaults.mk#L1-L53)
- [image.mk:1-58](file://mk/image.mk#L1-L58)

## Performance Considerations
- Deterministic tagging reduces cache misses and speeds up subsequent builds when tags are reused.
- Kustomize overlay rendering is performed as part of verification to catch configuration errors early.
- Auto-loading images into kind accelerates local iteration but should be disabled in CI to avoid overhead.

## Troubleshooting Guide
- If `make verify` fails:
  - Check test output for failing product suites.
  - Inspect overlay render errors from kustomize.
  - Review policy validation and scenario results.
  - Confirm version lockstep and secret vocabulary alignment.
- If deployment fails:
  - Verify secret provisioning flags and environment variables.
  - Ensure the correct cluster context is active.
  - Check logs for services after rollout to identify misconfigurations.
- Test fixture issues:
  - Use clock-relative timestamps (`datetime.now(timezone.utc)`) instead of hardcoded dates.
  - Understand retention policies (RETENTION_DAYS) when creating test data.

**Section sources**
- [Makefile:178-183](file://Makefile#L178-L183)
- [deploy.sh:1-62](file://shared/platform-ops/gitops/dev-k8s/deploy.sh#L1-L62)

## Conclusion
The platform uses a coordinated, GitOps-driven release model anchored by a single version source and deterministic image tagging. The verification gate enforces quality and policy compliance before promotion. Secrets and configuration are synchronized at deploy time, and audit trails provide traceability. Rollbacks and hotfixes leverage immutable image tags and overlay-based deployments, while e2e demos and overlay checks validate releases. The v0.43.1 patch release exemplifies the importance of test fixture stability, demonstrating how clock-sensitive issues can be resolved through proper timestamp handling while maintaining version lockstep across all platform products. This approach balances repeatability, safety, and operational clarity.

## Appendices

### Key Targets Summary
- `make verify`: Pre-commit/pre-push gate (tests, overlays, policies, scenarios, version, vocabulary).
- `make build`: Build all images with coordinated tag and write `.images.env`.
- `make push`: Push images to registry (with optional re-tag).
- `make deploy`: Deploy dev-k8s overlay and provision secrets/config.
- `make e2e`: Run end-to-end demos against deployed cluster.

**Section sources**
- [Makefile:77-129](file://Makefile#L77-L129)
- [Makefile:178-204](file://Makefile#L178-L204)

### Version Coordination Details
- Current platform version: 0.43.2
- Version validation script: `shared/shared-contracts/scripts/validate_version.py`
- Enforced lockstep across all products and portal
- Semantic versioning format: MAJOR.MINOR.PATCH

**Section sources**
- [VERSION:1-2](file://VERSION#L1-L2)
- [validate_version.py:1-149](file://shared/shared-contracts/scripts/validate_version.py#L1-L149)
- [Makefile:169-171](file://Makefile#L169-L171)

### Patch Release Best Practices
Based on v0.43.1 experience:
- Test-only fixes maintain version lockstep without production changes
- Clock-relative timestamps prevent future retention-related failures
- Full verification gate must pass including all eight product suites
- Documentation should clearly state patch scope and impact

**Section sources**
- [2026-09-27-clock-sensitive-document-fixtures.md:64-69](file://docs/agentic-aiops-platform/release-notes/2026-09-27-clock-sensitive-document-fixtures.md#L64-L69)
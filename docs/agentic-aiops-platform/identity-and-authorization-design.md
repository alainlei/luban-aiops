# Identity and Authorization Design

## Objective

Define the identity, authentication, authorization, and identity-propagation model for the enterprise-grade agentic AIOps platform.

This document makes the `SSO`, `Keycloak`, and `AD` integration decisions concrete so they can be implemented consistently across:

- web portal access
- API access
- policy evaluation
- approval workflows
- execution attribution
- audit logging

## Design Goals

- support enterprise `SSO` for operations team members
- integrate with an enterprise identity provider such as `Keycloak`
- federate identity to external account management such as `Active Directory`
- use identity context in policy and approval decisions
- preserve end-user attribution through tool execution
- keep privileged execution controlled and auditable

## Design Principles

### 1. Authentication is separate from authorization

Authentication proves who the user is.

Authorization determines:

- what the user can see
- what the user can ask the platform to do
- what the user can approve
- what environments and systems the user can affect

### 2. The human actor must remain attributable

Even when the platform uses agents, workers, or service accounts, risky actions must remain attributable to the initiating operator and, if applicable, the approving operator.

### 3. Identity must flow end to end

Identity should not stop at login. It must flow into:

- session state
- policy checks
- approval records
- execution requests
- audit events

### 4. Group claims should be normalized before use

Raw directory groups from `AD` or `Keycloak` should not be used directly everywhere. They should be normalized into platform roles and authorization attributes.

### 5. Service identity and human identity are different

Execution workers may run with service credentials, but those executions must still carry the human requester identity as audit context.

## Identity Architecture

### Recommended Identity Stack

- `Active Directory` as the enterprise source of users and groups
- `Keycloak` as the identity brokering and federation layer
- `OIDC` as the primary protocol for the web portal and API gateway
- `SAML` support only if required by enterprise constraints

### Why This Stack Fits

- `AD` remains the source of truth for enterprise user lifecycle and group membership
- `Keycloak` provides a practical identity control point for federation, protocol translation, claim mapping, and token issuance
- `OIDC` works well for modern web apps, APIs, and gateway integration

## Core Components

### 1. Identity Provider Layer

Recommended responsibilities for `Keycloak`:

- authenticate users directly or federate to `AD`
- manage clients for the web portal and APIs
- issue access and refresh tokens
- map raw directory groups to token claims
- support role and claim transformations

### 2. API Gateway Identity Boundary

The API gateway should be the first trusted enforcement point for authenticated requests.

Gateway responsibilities:

- validate access tokens
- reject unauthenticated requests
- forward only trusted identity headers or claims to downstream services
- enforce coarse route-level authorization where useful
- apply rate limits and route protections

### 3. Platform Authorization Layer

Downstream platform services should make authorization decisions using normalized identity context, not raw browser session state.

This layer should evaluate:

- user identity
- team membership
- role mapping
- environment entitlements
- action type
- target system

### 4. Audit and Attribution Layer

Every sensitive action should carry:

- requester identity
- approver identity when applicable
- service identity used for execution
- final execution result

## Authentication Model

### Portal Login Flow

Recommended flow:

1. operator opens the web portal
2. portal redirects to `Keycloak`
3. `Keycloak` authenticates directly or federates to `AD`
4. `Keycloak` issues `OIDC` tokens
5. portal receives tokens and establishes authenticated session
6. portal calls backend APIs through the API gateway
7. gateway validates the token and forwards trusted identity context

### API Access Flow

External systems calling platform APIs should also authenticate through gateway-managed token validation.

Recommended pattern:

- `OIDC` bearer tokens for interactive or service consumers
- separate client registrations for portal, internal services, and approved machine consumers

## Token and Session Strategy

### Token Types

Recommended token use:

- `access token` for API calls
- `refresh token` for session continuity in the web portal
- internal signed identity context only if needed between trusted services

### Session Model

Recommended session contents:

- authenticated user ID
- display name
- tenant or org context if applicable
- normalized platform roles
- normalized group attributes
- environment entitlements
- approval permissions

The platform should not rely on the frontend alone as the source of truth for authorization.

## Group and Role Mapping Model

### Source Groups

Examples of upstream sources:

- `AD` groups
- `Keycloak` realm roles
- `Keycloak` client roles

### Normalized Platform Roles

Recommended initial platform roles:

- `operator`
- `developer`
- `approver`
- `platform-admin`
- `auditor`
- `read-only-observer`

### Environment Scopes

Recommended environment scopes:

- `dev`
- `test`
- `staging`
- `prod`

### Example Mapping Pattern

Examples:

- `AD group: ops-dev` -> `operator` for `dev`
- `AD group: ops-prod-approvers` -> `approver` for `prod`
- `AD group: aiops-auditors` -> `auditor`
- `AD group: aiops-platform-admins` -> `platform-admin`

This mapping should be maintained centrally and versioned.

## Authorization Model

### Authorization Layers

Use multiple layers of authorization:

- `portal access authorization`
- `feature authorization`
- `tool and action authorization`
- `approval authorization`
- `environment authorization`

### Portal Access Authorization

Controls:

- who can access the portal
- who can access admin screens
- who can use API clients

### Feature Authorization

Controls:

- who can view incidents
- who can view audit history
- who can manage skills
- who can administer policy settings

### Tool and Action Authorization

Controls:

- which tools a user may invoke through the platform
- which environments they may target
- which actions are always denied

### Approval Authorization

Controls:

- who may approve production actions
- whether self-approval is allowed
- whether two-person approval is required for certain actions

## Recommended Initial Authorization Rules

### Base Rules

- all portal users must authenticate through `SSO`
- all requests must carry validated identity context
- all write actions require explicit policy evaluation
- destructive actions are denied by default

### Approval Rules

- `operator` may request actions but not approve production high-risk actions
- `approver` may approve actions within assigned environments
- `platform-admin` may manage mappings and policy, but should not automatically bypass all approvals
- `auditor` may view audit records but may not run actions

### Separation of Duties

Recommended initial rules:

- prevent self-approval for high-risk production actions
- allow self-approval only for tightly scoped non-production low-risk actions if needed
- require approver group membership for production restart actions

## Identity Propagation Model

### Request Context

Every incoming request should be normalized into a request identity context containing:

- `user_id`
- `username`
- `display_name`
- `email` if permitted
- `source_groups`
- `platform_roles`
- `environment_scopes`
- `approval_scopes`
- `tenant_id` if applicable

### Propagation Into Agent Sessions

The agent session should store:

- requester identity
- allowed environments
- effective roles
- approval capabilities

This lets the planner and policy layer reason about allowed behavior without trusting arbitrary user text.

### Propagation Into Approvals

Approval requests should include:

- requester identity
- requester roles
- target environment
- requested action
- required approver role or group

Approval decisions should capture:

- approver identity
- approval timestamp
- decision outcome
- optional reason

### Propagation Into Execution

Execution workers should receive:

- a signed execution request from the control plane
- human requester identity
- approver identity if present
- approved scope and action metadata

Workers should not accept arbitrary direct requests that bypass the control plane.

## Service Identity Model

> Implementation status (Release 1): the platform-to-platform service identity
> pattern below is implemented as broker-mediated token delegation (ADR-0004,
> SPEC-008). The portal-facing edge (`platform-gateway` since the SPEC-010
> split) exchanges the verified user token for a short-lived,
> audience-bound delegated token (`sub` = user, `act` = calling service,
> `aud` = target audience) that `agent-platform` relays as a bearer token;
> identity-broker remains the sole signing authority, roles are never elevated,
> and audit logs record both the human subject (`sub`) and the acting service
> (`act`). Platform JWTs are audience-bound (`aud`) to prevent cross-service
> replay. Kubernetes workload-identity-bound short-lived tokens are the
> documented upgrade path for the External Execution Identity.

### Human Identity

Represents:

- the person using the portal or API

### Platform Service Identity

Represents:

- the identity of gateway, agent service, policy service, and workers when calling each other

### External Execution Identity

Represents:

- the service account, workload identity, or short-lived credential used against Kubernetes or other enterprise systems

> Landed (SPEC-068): the first concrete outbound execution-credential form is the
> tool-gateway's file-mounted **named credential sets** — `basic`, `bearer`, and
> `oauth2_client_credentials` (a target-issued token the gateway acquires itself,
> with no new signing authority and no centralized broker). These are *platform
> configuration*, resolved by name at call time and never model-supplied; an
> acquired token is held in memory only and flows solely into an outbound
> `Authorization` header. This outbound target credential is a **separate plane**
> from the platform's own ADR-0004 `sub`/`act` delegation (which authenticates
> service-to-service calls *within* Luban): a credential or config failure fails
> closed as a structured gateway error and never falls back to an unauthenticated
> call. Kubernetes workload-identity-bound short-lived tokens remain the
> documented upgrade path.

These identities should be logged separately so audit records can answer:

- who requested the action
- who approved it
- which system identity executed it

## Approval Authorization Model

### Approval Decision Inputs

Approval logic should consider:

- requester role
- approver role
- target environment
- action category
- tool risk level
- service criticality
- change window if applicable

### Suggested Approval Tiers

- `tier 0`: read-only, no approval
- `tier 1`: low-risk non-production action, simple approval or auto-allow
- `tier 2`: production low-risk action, explicit approver required
- `tier 3`: high-risk production action, strong approval and possible two-person rule

## Audit Requirements

### Minimum Audit Fields

- request ID
- session ID
- requester user ID
- requester roles
- source groups
- approver user ID if applicable
- target environment
- target system
- action type
- policy outcome
- execution identity
- execution result
- timestamp

### Audit Principles

- logs must be immutable or tamper-evident
- audit records should be searchable by user, system, action, and incident
- approval and execution events must be correlated

## MVP Identity Scope

For the MVP, keep the identity model deliberately simple.

### Include In MVP

- `Keycloak` portal login
- federation to one external directory source such as `AD`
- basic group to role mapping
- gateway token validation
- identity-aware policy checks
- requester and approver attribution in audit records

### Defer Until After MVP

- complex multi-tenant identity models
- advanced cross-org federation
- very granular attribute-based access policies across many systems
- just-in-time privileged access integration

## Recommended Implementation Sequence

### Step 1

- configure `Keycloak` realm, clients, and federation to `AD`

### Step 2

- integrate portal login with `OIDC`

### Step 3

- validate tokens at the API gateway

### Step 4

- build identity normalization in the backend

### Step 5

- connect normalized identity to policy and approval services

### Step 6

- propagate identity to audit and execution records

## Key Design Decisions

- use `Keycloak` as the enterprise identity broker
- use `AD` as the upstream identity and group source when available
- use `OIDC` as the default web and API auth protocol
- normalize groups into platform roles before policy evaluation
- preserve human attribution through approvals and execution
- keep service identity separate from human identity

## Final Recommendation

Implement identity as a platform-wide control capability, not merely a login feature.

For this agentic AIOps platform, the recommended enterprise-ready model is:

- `Keycloak + AD federation`
- `OIDC` for portal and API authentication
- normalized role and group mapping
- identity-aware policy and approval decisions
- end-to-end requester and approver attribution through execution and audit

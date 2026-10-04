# Security Policy

## Scope

This repository contains the implementation, shared contracts, and deployment assets for the Luban enterprise-grade agentic AIOps platform.

Security-sensitive areas include:

- identity and `SSO` integration
- authorization and approval flows
- policy evaluation and decision enforcement
- tool access and connector credentials
- execution controls and audit trails

## Reporting A Vulnerability

Please do not open public issues for suspected vulnerabilities.

Instead:

1. report the issue privately to the repository maintainers or security owners
2. include affected files, products, and observed impact
3. include reproduction steps or proof of concept when safe to share
4. note whether identity, approval, policy, or execution paths are affected

## Handling Expectations

Maintainers should:

- acknowledge the report promptly
- assess impact and blast radius
- prioritize identity, policy, approval, and execution issues first
- document mitigations and follow-up hardening work

## Secure Contribution Expectations

Contributors should avoid introducing changes that:

- bypass approval or policy checks
- blur product boundaries between identity, policy, and execution
- weaken auditability or user attribution
- expose secrets, tokens, or credentials in code or documentation

## Secrets

Do not commit:

- `.env` files with real secrets
- service account credentials
- connector tokens
- private certificates or keys

Use environment-specific secret management and GitHub repository or organization secrets where appropriate.

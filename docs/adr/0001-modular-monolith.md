# ADR-0001: Modular monolith on Django

- Status: Accepted
- Date: 2026-10-02

## Context

CAIPO has several distinct domains (sources, policies, indicators, research claims, retrieval, AI assistant) that share data heavily: a claim references a passage in a document version and an observation in a dataset release. The team is small, expected load is low, and correctness and maintainability are the priorities. The project brief requires a modular Django architecture and rules out microservices without a demonstrated reason.

## Decision

Build one Django project composed of apps with enforced boundaries.

- Apps are arranged in layers; imports and foreign keys go only downward. The layer table is in [ARCHITECTURE.md](../ARCHITECTURE.md) §2.
- Each app exposes `services` for writes and `selectors` for reads. Other apps use only these.
- Import boundaries are checked in CI with import-linter. Relation traversal across apps inside queries cannot be checked mechanically and is a review matter.
- One codebase and one image. Web and worker processes differ by command and privileges, not by code.

## Alternatives considered

- **Microservices.** No independent scaling, team, or deployment need exists. They would replace database transactions and foreign keys across the evidence chain with network calls and eventual consistency, which works against the project's main requirement.
- **Unstructured Django project.** Fast at first, but domain logic spreads across views and models and the evidence rules become hard to audit.
- **Separate AI service.** The AI pipeline needs transactional access to segments, passages, and interaction records. Splitting it buys nothing at this scale.

## Consequences

- Simple deployment and local development.
- Integrity rules can be enforced with database constraints across domains.
- Boundaries exist only as long as they are enforced; the CI check is mandatory.
- All components share a release cycle.
- The fetch worker and parse worker share the codebase but run with far fewer privileges, which needs care in configuration (ADR-0009, ADR-0011).

## Revisit when

A component needs a different runtime, an independent scaling profile that worker processes cannot provide, or a separate team owns it.

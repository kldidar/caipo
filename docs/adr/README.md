# Architecture Decision Records

An ADR records one architecturally significant decision: what was decided, why, and what it costs.

## Index

Seven ADRs were accepted by the project owner on 2026-10-02. Five remain Proposed; the last column says what stands between each of those and acceptance.

| ADR | Title | Status | Needs before acceptance |
|---|---|---|---|
| [0001](0001-modular-monolith.md) | Modular monolith on Django | Accepted | — |
| [0002](0002-postgresql-system-of-record.md) | PostgreSQL as system of record | Accepted | — |
| [0003](0003-vector-search.md) | Vector search with pgvector and hybrid retrieval | Proposed | Embedding model decision; retrieval spike (B15) |
| [0004](0004-asynchronous-jobs.md) | Celery with Redis for asynchronous jobs | Proposed | Job-system spike before Phase 2 (B4, B21); Celery does not yet declare Python 3.14 support |
| [0005](0005-evidence-and-provenance-model.md) | Evidence and provenance model | Accepted | — (amended before ratification) |
| [0006](0006-ai-provider-abstraction.md) | AI provider abstraction | Proposed | Provider, model, and budget decisions (B14) |
| [0007](0007-authentication.md) | Authentication and access model | Accepted | — |
| [0008](0008-deployment-strategy.md) | Deployment strategy | Proposed | Hosting decision (B17); isolation mechanism (ADR-0011). CI on GitHub Actions was approved separately as Phase 1 tooling and does not depend on this ADR. |
| [0009](0009-untrusted-content-handling.md) | Untrusted content handling: principles | Accepted | — |
| [0010](0010-web-interface-and-api.md) | Web interface and API style | Accepted | — |
| [0011](0011-worker-isolation-mechanism.md) | Worker isolation mechanism | Proposed | Spike (B21) |
| [0012](0012-authorization-and-role-event-integrity.md) | Authorization and role event integrity | Accepted | — |

## Statuses

Only these four statuses are used. A status line contains the status word and nothing else.

| Status | Meaning |
|---|---|
| Proposed | A recommendation exists. It has not been ratified by the project owner, or something must be investigated first. Do not build on it. |
| Accepted | Ratified by the project owner. Implementation follows it. |
| Superseded | Replaced by a later ADR, which is named. |
| Rejected | Considered and not adopted. Kept for the record. |

An architect or an AI agent can propose. Only the project owner accepts.

## Process

1. Copy [0000-template.md](0000-template.md) to the next number with a short hyphenated title.
2. Start as Proposed. State what must be true for it to be accepted.
3. Review in a pull request.
4. On acceptance by the project owner, change the status and date, remove or resolve the open points, and update the index here and in the project specification.
5. An accepted ADR's decision is not edited. To change a decision, write a new ADR that supersedes it. Typo fixes and added links are fine.
6. An accepted ADR has no unresolved open points. If part of a decision is unproven, split it into its own Proposed ADR.

## When an ADR is needed

- Adding or replacing a datastore, framework, external service, or significant dependency
- Changing a security boundary
- Changing the app layering or module boundaries
- Changing how provenance, evidence, or claims are represented
- Changing the AI pipeline's guarantees
- Anything costly to reverse

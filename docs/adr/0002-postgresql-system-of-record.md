# ADR-0002: PostgreSQL as system of record

- Status: Proposed
- Date: 2026-10-01

## Context

The domain is relational: documents, versions, passages, policies, observations, claims, and evidence are densely linked, and the integrity of those links is the core of the product. The data volume is small.

## Decision (proposed)

PostgreSQL is the single system of record for all durable data.

- Integrity rules are expressed as database constraints wherever possible.
- Job state, AI cost accounting, and budgets are durable data and live here.
- Full-text search uses PostgreSQL's built-in search and the trigram extension.
- Vector search, if ADR-0003 is accepted, uses the pgvector extension in the same database.
- Redis holds only data that may be lost (ADR-0004).
- Raw document bytes are stored in the artifact store, not in the database. The database holds their hashes and metadata.
- Each runtime component **that connects to the database** does so with its own least-privilege role. The fetch worker and parse worker do not connect at all (ADR-0009). Redaction uses a separate role.
- The same PostgreSQL major version is used in development, CI, and production. SQLite is not used anywhere, including tests.

## Alternatives considered

- **Separate search engine.** Possibly better language analysis, but a second datastore to operate, secure, back up, and keep consistent. Not justified before retrieval quality has been measured.
- **Document database.** Poor fit for a relational domain with strict integrity needs.
- **SQLite for tests.** Faster setup, but it lacks the constraints, extensions, and search features the system depends on, so tests would not test the real behaviour.

## Consequences

- One backup, one consistency model, one thing to operate.
- Transactional consistency between source data and search index.
- Which text search configurations the pinned PostgreSQL version provides for the corpus languages must be verified at dependency lock time. Lexical recall for every corpus language is unmeasured (blocker B15).
- The database is a single point of failure. Encrypted backups and restore tests are mandatory.

## Open points

None beyond owner ratification.

## Revisit when

Measured retrieval quality or performance cannot be brought to an acceptable level within PostgreSQL.

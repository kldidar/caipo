# ADR-0004: Celery with Redis for asynchronous jobs

- Status: Proposed
- Date: 2026-10-01

## Context

Some work cannot run inside a web request:

- Fetching documents and dataset files from slow or unreliable sites
- Parsing untrusted files, which must run in an isolated process with resource limits
- Building retrieval chunks and computing embeddings
- Running evaluation suites

Fetching and parsing also need to run with different privileges from the web process (ADR-0009, ADR-0011). The project brief names Redis as part of the stack and Celery where justified.

## Decision (proposed)

Use Celery with Redis as the broker, with a narrow scope.

- Separate queues and workers for fetch, parse, and default work, so each can run in its own security zone.
- Tasks are thin wrappers around service functions and take identifiers, not data.
- JSON serialisation only. Pickle is disabled.
- Tasks are idempotent and acknowledge after completion.
- **The state of every job lives in PostgreSQL**, in IngestionRequest and IngestionEvent rows and their equivalents. Redis is never the record of what happened. A reconciliation command re-enqueues requests left in `pending`, `running`, or `retrying`.
- **Bounded delivery.** Attempts are counted in PostgreSQL by the trusted side before each dispatch, per stage. Transient errors are retried a small number of times with backoff. A task whose worker was killed or timed out while handling a file is delivered at most once more, then the request is `failed`. Nothing is redelivered without limit. The limits are repository configuration.
- No Celery result backend is used unless a concrete need appears.
- No periodic scheduler is deployed until a scheduled task exists.
- The assistant's question-answering path runs in the web request unless measured latency shows it does not fit; in that case it moves to a background job and the page polls for the verified result.

### What Redis is used for

| Use | Justification | Loss tolerance |
|---|---|---|
| Celery broker | Asynchronous jobs are required, as above | Messages may be lost; PostgreSQL state allows re-enqueueing |
| Short-window request throttling counters | Rate limits on login, questions, submissions | Counters may reset |

Redis is not used as a cache until a measurement shows a need for one. **AI budget and cost accounting are not held in Redis**; they are computed from records in PostgreSQL. Redis requires authentication and is reachable only on the internal network.

## Alternatives considered

- **A PostgreSQL-backed task queue.** Would remove the broker and give transactional enqueueing. A reasonable choice at this scale. Not proposed because the project brief names Redis and Celery, and Celery's queue routing maps directly onto the security zones. It remains the fallback if ADR-0011's spike shows the isolation requirement cannot be met with a Redis broker.
- **A task interface built into Django with a third-party backend.** The locked release, Django 5.2.17, does not contain one (verified 2026-10-02). It would require a newer Django series, and its routing and isolation features would need to be assessed.
- **Synchronous processing.** Not viable for fetching and parsing, and it would put untrusted file parsing in the web process.
- **Cron scripts.** No retries, no routing, weak visibility.

## Consequences

- Two more runtime components to operate: Redis and the workers.
- Fetching and parsing are isolated from the web process.
- A worker with broker access can normally enqueue tasks. For the fetch and parse workers this must be prevented; how is the subject of ADR-0011 (blocker B21).
- Discipline is required to keep tasks thin and idempotent.

## Open points

1. Acceptance of the fetch and parse queues as described depends on ADR-0011.
2. **Python 3.14 support is not declared by Celery 5.6.3 or kombu 5.6.2**, which list support up to Python 3.13 (package metadata checked 2026-10-01). A one-off smoke test on the same day passed a message through Redis 8.10.2 on Python 3.14.4, which is not the same as upstream support. Celery is not yet in the lockfile. The owner must decide whether this is acceptable before Phase 2 (blocker B4). The Redis client is already capped below 6.5 in `pyproject.toml` because kombu requires it.

The rest needs owner ratification only.

## Revisit when

Task loss or broker operation becomes a recurring problem, or the ADR-0011 spike shows the isolation requirement cannot be met with Celery on Redis. In either case reconsider the PostgreSQL-backed queue.

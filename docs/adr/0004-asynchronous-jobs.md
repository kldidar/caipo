# ADR-0004: Job system: no library in the isolated workers, django-tasks for trusted work

- Status: Accepted
- Date: 2026-11-05

## Context

Some work cannot run inside a web request:

- Fetching documents and dataset files from slow or unreliable sites
- Parsing untrusted files, which must run in an isolated process with resource limits
- Building retrieval chunks and computing embeddings
- Running evaluation suites

Fetching and parsing also run with different privileges from the web process ([ADR-0009](0009-untrusted-content-handling.md), [ADR-0011](0011-worker-isolation-mechanism.md)).

This ADR was proposed on 2026-10-01 as "Celery with Redis for asynchronous jobs". On 2026-10-02 the project owner moved the choice to a spike shared with ADR-0011 (blockers B4 and B21). The spike ran on 2026-11-05 ([report](../reports/spike-c1-job-system-and-isolation.md)). It evaluated Celery 5.7.0rc1, Dramatiq 2.2.1, and `django-tasks` with `django-tasks-db` on Python 3.14, against the isolation requirements of ADR-0011, and found that no job library is fit to run inside an isolated worker. The project owner accepted its recommendation on 2026-11-05 (Q-16 of the execution tracker). This text replaces the proposal.

## Decision

1. **Two kinds of work, two mechanisms.** Isolated work, fetching and parsing, follows ADR-0011 and point 2 below. Trusted work is everything else that runs in the background: the trusted side of ingestion, reconciliation, building retrieval data, and evaluation. It uses the queue of point 4.
2. **No job library inside an isolated worker.** Each isolated worker runs a small consumer of its own Redis list, under the restricted broker user of ADR-0011. The consumer moves one job identifier from its queue into its own processing list (`BLMOVE`), handles the job, writes its result as a file, and removes the job from its processing list (`LREM`). It has no other broker command. A message is a job identifier and never data.
3. **The trusted side owns the delivery of isolated work.** Before each dispatch it counts the attempt in PostgreSQL, in IngestionRequest and IngestionEvent rows and their equivalents. Each stage has a deadline. A job whose validated result has not appeared by its deadline is dispatched again or, at the limit, failed. Isolated workers acknowledge a job when they take it and never report state. The limits are repository configuration.
4. **Trusted work uses `django-tasks` with `django-tasks-db`.** `django-tasks` is the backport of Django's built-in tasks framework, and `django-tasks-db` is its database backend. A task's state lives in PostgreSQL. A task is enqueued inside the caller's transaction, so it is not enqueued if the transaction rolls back. Task arguments are JSON only. Tasks are thin wrappers around service functions; they take identifiers, not data, and are idempotent.
5. **A reaper on the trusted side.** No candidate recovers a task whose worker died: `django-tasks-db` leaves it running, and a library's own redelivery cannot be bounded from an isolated worker. A reconciliation command finds trusted tasks left running and isolated jobs past their deadline, counts each as an attempt, and enqueues it again or fails it, within the limits of point 3.
6. **Nothing is installed before Phase 2 builds the job system.** The two packages are then pinned exactly and justified in the pull request that adds them (CLAUDE.md, architecture rule 14). The versions verified by the spike were `django-tasks` 0.12.0 and `django-tasks-db` 0.13.0, on Python 3.14.4 and Django 5.2.17. Both are before 1.0, so an upgrade is reviewed like any change of a dependency.
7. **Redis keeps two uses.** It holds the isolated workers' queues and short-window throttling counters. It is never the record of what happened to a job. No result backend is used. No periodic scheduler is deployed until a scheduled task exists.
8. **Celery and Dramatiq are not used.** See Alternatives considered.
9. **The assistant answers in the web request** unless measured latency shows it does not fit. In that case its pipeline becomes a trusted task, and the page polls for the verified result.

### What Redis is used for

| Use | Justification | Loss tolerance |
|---|---|---|
| Queues of the isolated workers | ADR-0011; each worker sees only its own | Messages may be lost; the trusted side dispatches again from PostgreSQL |
| Short-window request throttling counters | Rate limits on sign-in, questions, submissions | Counters may reset |

AI budget and cost accounting are not held in Redis; they are computed from records in PostgreSQL. Redis requires authentication and is reachable only on the internal network.

## Alternatives considered

- **Celery with Redis**, the earlier proposal. Rejected for four reasons:
  - Only a release candidate, 5.7.0rc1, declares Python 3.14; the latest stable release, 5.6.3, stops at 3.13.
  - kombu 5.7.0 imports `packaging` without declaring it as a dependency.
  - Under a restricted broker user, its worker still needs to publish to its own queue.
  - Its acknowledge-late redelivery of a task whose worker was killed cannot be bounded from an isolated worker: the spike measured 3 deliveries after 2 kills.
- **Dramatiq.** Rejected. It is licensed LGPL-3.0, its workers share broker keys, and its worker needs to publish to its own queue.
- **Procrastinate**, a PostgreSQL-backed queue under the MIT licence. Not tested. It is the first substitute for trusted work if `django-tasks` proves insufficient.
- **A small queue of our own on PostgreSQL.** It would need more code than `django-tasks` and would not follow Django's API for tasks.
- **One library for both kinds of work.** None meets the isolation requirements, and a PostgreSQL-backed queue cannot serve isolated workers, which hold no database credentials.
- **Synchronous processing, or cron scripts.** Not viable for fetching and parsing.

## Consequences

- About fifty lines of the project's own consumer code, with tests, replace a library in the isolated workers.
- Two packages before 1.0 become dependencies when Phase 2 builds the job system.
- The reaper of point 5 is required, and it is tested with a worker killed mid-task.
- Redis stays a runtime component. Its users and access rules are part of the deployment (ADR-0008).
- The `redis` client was capped below 6.5 because kombu required it. That reason is gone. The cap is reviewed when Phase 2 adds the job system.
- When the project moves to a Django release that has the tasks framework built in, `django-tasks` is replaced by the built-in API, with the same database backend.

## Revisit when

`django-tasks` or `django-tasks-db` stops being maintained or fails on an upgrade of Python or Django; throughput outgrows a queue in PostgreSQL; or the project moves to a Django release with the tasks framework built in.

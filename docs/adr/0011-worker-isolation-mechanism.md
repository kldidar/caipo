# ADR-0011: Worker isolation mechanism

- Status: Proposed
- Date: 2026-10-01

## Context

[ADR-0009](0009-untrusted-content-handling.md) requires that the fetch worker and the parse worker be isolated: compromise of either must not yield database credentials, AI credentials, access to internal services, or the ability to enqueue arbitrary tasks, and the parse worker must have no outbound network access.

[ADR-0004](0004-asynchronous-jobs.md) proposes Celery with Redis. A Celery worker needs broker access, and broker access normally allows publishing any task to any queue. The two proposals are therefore in tension, and no mechanism has been shown to reconcile them. Nothing here has been built or tested.

There is a second gap: the isolated workers hold no database credentials, so they cannot record their own results. A trusted worker must learn that work is finished without the isolated worker being able to enqueue tasks.

## Decision (proposed)

No mechanism is decided. This ADR fixes what the spike must demonstrate and lists the candidates.

### Requirements the mechanism must meet, shown by tests

For both isolated workers:

1. No database credentials are present in the container, and PostgreSQL is not reachable from it.
2. No AI provider credentials are present.
3. The worker can consume only its own queue. An attempt to publish a task to any other queue fails.
4. No internal service other than the broker is reachable.
5. Results reach the trusted side only as files or messages that a trusted worker validates.
6. A trusted worker learns of completion or failure without relying on the isolated worker's ability to enqueue.
7. A worker that is killed mid-task results in a counted attempt and, at the limit, a failed request.

Additionally for the parse worker:

8. No outbound network connection of any kind succeeds.
9. The artifact store is readable but not writable. Only a scratch area is writable.

Additionally for the fetch worker:

10. Connections to private, loopback, link-local, and metadata addresses fail at network level, independently of the application check.
11. The artifact store is not readable. Only the landing area is writable.

### Candidate mechanisms

1. **Restricted broker accounts.** Each isolated worker runs in its own container and connects to Redis with an account whose access control limits it to the keys of its own queue. Results are written to a shared volume as files. A trusted worker polls for results by request identifier, or is notified through a narrowly restricted reply channel.
2. **Separate broker instance per isolated queue.** Each isolated worker has its own Redis instance, containing nothing but its queue. Results as in candidate 1.
3. **No broker access for isolated work.** A trusted worker launches each fetch or parse as a subprocess inside an operating-system sandbox with the required network and filesystem restrictions. The isolated code is then not a Celery worker at all.
4. **Fallback: a PostgreSQL-backed queue** as considered in ADR-0004, if none of the above meets the requirements with Redis. This would supersede part of ADR-0004.

### How artifacts reach isolated workers

Isolated workers receive and deliver files only through mounted volumes: the landing area for the fetch worker, a read-only artifact mount and a scratch area for the parse worker. They never hold storage credentials. This holds whatever the artifact store's backing technology is (see ADR-0008).

## Alternatives considered

- **Accept the risk and rely on input validation in tasks.** A compromised worker could enqueue tasks with crafted identifiers against trusted workers. Validation reduces but does not remove this, and it contradicts the requirement in ADR-0009.
- **Give isolated workers narrowly scoped database roles.** Simpler result handling, but puts database credentials and a network path to PostgreSQL inside the components that handle hostile input.

## Consequences

- Phase 2 cannot begin until the spike is done (blocker B21).
- The chosen mechanism may add operational complexity, such as Redis access-control configuration or sandbox tooling.
- If only candidate 4 works, ADR-0004 changes.

## Open points

Everything. Acceptance requires a spike that implements one candidate and passes tests for requirements 1 to 11. The spike is throwaway code in its own branch; it is not application code.

## Revisit when

The broker, container runtime, or artifact store changes.

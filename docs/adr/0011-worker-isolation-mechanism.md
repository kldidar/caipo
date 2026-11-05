# ADR-0011: Worker isolation mechanism

- Status: Accepted
- Date: 2026-11-05

## Context

[ADR-0009](0009-untrusted-content-handling.md) requires that the fetch worker and the parse worker be isolated. Compromising either must not yield database credentials, AI credentials, access to internal services, or the ability to enqueue arbitrary tasks. The parse worker must also have no outbound network access.

A worker of a job library normally needs broker access, and broker access normally allows publishing any task to any queue. Isolated workers also hold no database credentials, so they cannot record their own results. A trusted worker must therefore learn that work is finished without giving the isolated worker the ability to enqueue.

This ADR was proposed on 2026-10-01. It stated the requirements below and listed four candidate mechanisms, none of them tested. The spike shared with [ADR-0004](0004-asynchronous-jobs.md) (blockers B4 and B21) ran on 2026-11-05 ([report](../reports/spike-c1-job-system-and-isolation.md)). It demonstrated all eleven requirements by tests with candidate 1 in its strictest form. The project owner accepted its recommendation on 2026-11-05 (Q-16 of the execution tracker).

## Decision

1. **Restricted broker users (candidate 1), in the strictest form.**
   - Each isolated worker connects to Redis as its own user.
   - That user may run only `BLMOVE` from its own queue into its own processing list and `LREM` on that list, besides authenticating.
   - It cannot publish to any queue, including its own, and cannot read, list, or change anything else.
   - The default user is disabled.
   - The consumer is the project's own (ADR-0004 point 2), because a job library needs more rights than this.
2. **Results leave as files.** The parse worker writes to its result area, and the fetch worker to its landing area. A trusted worker validates every result before anything is written to the database (ADR-0009).
3. **The trusted side owns delivery** (ADR-0004 points 3 and 5). It counts each attempt in PostgreSQL before dispatch and gives each stage a deadline. It dispatches again or fails a job whose validated result has not appeared. An isolated worker is never trusted to report state.
4. **Networks.**
   - The parse worker sits on an internal network that holds only the broker.
   - The fetch worker sits on an internal network that holds the broker and an egress proxy. Only the proxy has a route out.
   - The proxy resolves names itself and checks the address it will connect to. It refuses private, loopback, link-local, metadata, shared, documentation, multicast, and reserved destinations, and every port but 80 and 443. The spike used Squid; a purpose-built egress proxy such as Smokescreen is compared when Phase 2 is designed.
   - The application's fetch guard stays as a separate layer: the proxy does not replace it.
5. **Containers.**
   - Isolated workers run as a non-root user, with a read-only root filesystem, every capability dropped, `no-new-privileges`, and a temporary `/tmp`.
   - Their environment holds no database or AI credentials.
   - The parse worker gets the artifact store read-only and its result area writable.
   - The fetch worker does not get the artifact store at all; only its landing area is writable.
6. **The requirements below are the acceptance tests.**
   - The spike demonstrated each one.
   - Phase 2 demonstrates them again, by tests against the configuration it deploys, before ingestion is enabled.
   - A change to that configuration runs them again.
7. **Production specifics wait for [ADR-0008](0008-deployment-strategy.md)**, for example network policies in an orchestrator or a sandboxed container runtime. Whatever is chosen keeps every property below.

### Requirements, shown by tests

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

### How artifacts reach isolated workers

Isolated workers receive and deliver files only through mounted volumes. The fetch worker has its landing area. The parse worker has a read-only artifact mount and a scratch area. They never hold storage credentials, whatever technology backs the artifact store (see ADR-0008).

## Alternatives considered

- **A separate broker instance for each isolated queue (candidate 2).** It adds instances without making isolation stronger than per-user rules on one broker, which the spike showed to be sufficient.
- **No broker access for isolated work (candidate 3).** A trusted worker would launch each fetch or parse inside an operating-system sandbox. That needs sandbox tooling, or access to the container runtime, which is itself a large privilege. It remains the route if a future runtime makes per-job sandboxes cheap.
- **A PostgreSQL-backed queue for isolated work (candidate 4).** Impossible: the isolated workers would need database access, which requirement 1 forbids. A PostgreSQL-backed queue is used for trusted work instead (ADR-0004).
- **A job library's consumer under a restricted user.** Celery and Dramatiq both ran under one in the spike. Both still needed to publish to their own queue, and Celery's redelivery could not be bounded from the isolated side.
- **Accepting the risk and relying on input validation in tasks.** A compromised worker could enqueue tasks with crafted identifiers against trusted workers. That contradicts ADR-0009.
- **Giving isolated workers narrowly scoped database roles.** It puts database credentials, and a network path to PostgreSQL, inside the components that handle hostile input.

## Consequences

- The broker's users and access rules, the internal networks, and the egress proxy are part of the deployment. They are versioned with it, and the tests of point 6 check them.
- The egress proxy is one more component to operate.
- IPv6 must be disabled on the isolated networks, or filtered by the proxy as IPv4 is. The spike tested IPv4 only.
- Because no library runs in the isolated workers, the project maintains their small consumers.
- Phase 2 cannot enable ingestion until point 6 holds for its deployed configuration.

## Revisit when

The broker, the container runtime, the orchestration, or the artifact store changes.

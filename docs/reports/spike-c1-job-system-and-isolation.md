# Spike C1: job system and worker isolation (B4, B21)

Status: Spike report · 2026-11-05 · **Decides nothing.** [ADR-0004](../adr/0004-asynchronous-jobs.md) and [ADR-0011](../adr/0011-worker-isolation-mechanism.md) stay Proposed until the project owner accepts them, and blockers B4 and B21 stay open until then.

The spike that ADR-0004 and ADR-0011 require before Phase 2, started on the owner's decision of 2026-11-04 (Q-9). Its code is throwaway and lives only on the branch `spike/c1-job-isolation` (commits `0a6186c` and `82f4de6`), never merged into `main`. It is run by `spike/c1/run.sh`, which builds everything, prints one line per check, and removes everything it made. The recorded output of the final run is `spike/c1/RESULTS.jsonl` on that branch.

## Summary

- **All eleven requirements of ADR-0011 were demonstrated by tests** with one mechanism: restricted Redis users per isolated queue, results as files, delivery owned by the trusted side, an internal network for the parse worker, and an egress proxy as the fetch worker's only way out. 47 checks ran; 44 passed, and the other 3 are findings about two job libraries, not failures of that mechanism.
- **No job library is fit to run inside the isolated workers.** Celery and Dramatiq both work under a restricted Redis user, but both need to publish to their own queue, and Celery's own redelivery of a task whose worker was killed is unbounded from the isolated side. A small consumer of a Redis list, with no write command but the move into its own processing list, gives the strongest isolation measured.
- **For trusted work, a PostgreSQL-backed queue fits the architecture best:** `django-tasks` with `django-tasks-db` keeps job state in PostgreSQL, enqueues inside the caller's transaction, and refuses arguments that are not JSON. Like every candidate, it needs a reaper for a task whose worker died.

## What was run

| Item | Version or detail |
|---|---|
| Python | 3.14 (`python:3.14-slim`; 3.14.4 in the scratch environment) |
| Redis | 8.10.2, the image the development environment pins |
| PostgreSQL | 18.6, the image the development environment pins |
| Celery / kombu | 5.7.0rc1 (18 October 2026, the first release that declares Python 3.14) / 5.7.0 (3 November 2026) |
| Dramatiq | 2.2.1, with its Redis broker |
| django-tasks / django-tasks-db | 0.12.0 / 0.13.0, on Django 5.2.17 |
| Egress proxy | Squid 6.6 (`ubuntu/squid:6.6-24.04_edge`) |
| Containers | Isolated workers run as UID 10001 with a read-only root filesystem, every capability dropped, and `no-new-privileges`; only their scratch or landing area is writable |
| Networks | `trusted` (PostgreSQL, Redis, trusted worker); `parse_net`, internal, holding only Redis and the parse worker; `fetch_net`, internal, holding Redis, the fetch worker, and the egress proxy, which alone is also on `egress_net` with a route out |

Versions and declared Python support were read from PyPI on 2026-11-04 and 2026-11-05. Passwords for the run were generated at start into an ignored directory; none is committed.

## Results by requirement

| ADR-0011 requirement | Result | Evidence from the run |
|---|---|---|
| 1. No database credentials; PostgreSQL unreachable | Met (parse, fetch) | No such variable in either worker's environment; the name `postgres` does not resolve |
| 2. No AI provider credentials | Met (parse, fetch) | No such variable |
| 3. Consumes only its own queue; publishing elsewhere fails | Met | The parse user can run only `BLMOVE` from `q:parse` into `q:parse:processing` and `LREM`; `LPUSH` to another queue, and even to its own, `GET`, `PUBLISH`, `KEYS`, and `CONFIG` are refused by the broker |
| 4. No internal service but the broker reachable | Met | The trusted worker's name and PostgreSQL do not resolve from `parse_net`; from `fetch_net`, internal services are refused by the proxy |
| 5. Results only as files a trusted worker validates | Met | The parse worker writes `/results/<job>.json`; the trusted worker reads it and checks its exact fields |
| 6. The trusted side learns of completion without the isolated worker enqueueing | Met | The trusted worker polls for the result file of each job it dispatched |
| 7. A worker killed mid-task gives a counted attempt and, at the limit, a failed request | Met with trusted-side delivery | Killed twice: two attempts counted in PostgreSQL, then `failed`; nothing left in the queue or the processing list |
| 8. Parse worker: no outbound connection of any kind | Met | `Network is unreachable` to 1.1.1.1:443 and 8.8.8.8:53; no name resolution |
| 9. Parse worker: artifact store read-only, only scratch writable | Met | The artifact is read; writing to it and to the root filesystem fails (`Read-only file system`) |
| 10. Fetch worker: private, loopback, link-local, and metadata destinations refused at network level | Met | No direct route out. Through the proxy, a public site answers 200; `169.254.169.254`, `127.0.0.1`, `10.0.0.1`, `192.168.1.1`, the broker by name, a public name that resolves to loopback (`localtest.me`), and a port other than 80 and 443 are each refused with 403 |
| 11. Fetch worker: artifact store not readable, only landing writable | Met | The artifact store is not mounted; `/landing` is writable; the root filesystem is not |

## The job systems compared

| | Redis list consumer (no library) | Celery 5.7.0rc1 | Dramatiq 2.2.1 | django-tasks + django-tasks-db |
|---|---|---|---|---|
| Declares Python 3.14 | — | Only the release candidate; 5.6.3, the latest stable, stops at 3.13 | Yes | Yes |
| Licence | — | BSD-3-Clause | **LGPL-3.0 or later** | BSD-3-Clause |
| Runs under a per-queue Redis user | Yes | Yes, with per-queue `unacked*` keys set by hand and a `parse*` key pattern for its priority sub-queues | Yes, but it also needs its namespace key and a heartbeat set shared by every worker | Not applicable: it needs the database, which an isolated worker must not reach |
| Isolated worker can publish to its own queue | **No** | Yes: kombu needs `LPUSH` there to restore unacknowledged tasks | Yes | — |
| Isolated worker can publish to another queue | No | No | No (the broker refuses inside its Lua script) | — |
| Redelivery after the worker is killed | Owned and bounded by the trusted side | Unbounded from the isolated side: 3 deliveries after 2 kills with `acks_late` | Not measured | The task stays RUNNING; nothing recovers or counts it |
| Job state in PostgreSQL | Yes, kept by the trusted side | No | No | Yes |

## Findings

1. **Isolation is a property of the deployment, not of the job library.** The broker's per-user key and command rules did all the refusing; no library setting did.
2. **A library consumer needs more rights than isolation allows.** Celery and Dramatiq each need to write to their own queue. An attacker in the parse worker could then put messages into the parse queue, which only parse workers read: not a route to the trusted side, but a way to replay or flood work.
3. **Celery's acknowledge-late mode cannot bound redelivery in an isolated worker.** With `acks_late` and `reject_on_worker_lost`, a task that kills its worker comes back after every restart. A worker without database access cannot count deliveries, so a hostile file could crash the parser indefinitely. Isolated work must be acknowledged on receipt and its retries owned by the trusted side, which is what requirement 7 asks.
4. **kombu 5.7.0 imports `packaging` in its Redis transport without declaring it as a dependency.** A clean install fails at the first task. It was released the day before the run, so this may be corrected soon; it is a sign that the Python 3.14 line of Celery is not yet settled.
5. **Dramatiq shares keys between all workers** (its namespace and heartbeat set), so a compromised worker can disturb another queue's bookkeeping, for example by making a healthy worker look dead, though it cannot enqueue into that queue. Its licence, LGPL-3.0, would need the owner's agreement.
6. **No candidate recovers a task whose worker died.** django-tasks leaves it RUNNING; Celery redelivers it without limit. A reaper owned by the trusted side, counting attempts in PostgreSQL, is needed in every design.
7. **The egress proxy must check addresses after resolution.** A public name that resolves to `127.0.0.1` was refused only because the proxy resolves the name itself and checks the address it will connect to.
8. **A key pattern is part of the security boundary.** The pattern `parse*` that Celery's priority sub-queues require also matches any other key that starts with `parse`; queue names must not share a prefix.

## Recommendation, for the owner to accept or not

**For ADR-0011 (isolation): candidate 1, in its strictest form.**

- Each isolated worker connects to Redis as its own user, allowed only `BLMOVE` from its queue into its processing list and `LREM` on that list.
- Results leave only as files in the worker's own result area, and a trusted worker validates them.
- Delivery is owned by the trusted side. It counts each attempt in PostgreSQL before dispatching, gives each stage a deadline, and dispatches again or fails at the limit. Isolated workers acknowledge on receipt and are never trusted to report state.
- The parse worker sits on an internal network that holds only the broker. The fetch worker sits on an internal network whose only route out is an egress proxy that checks destinations after resolution.
- Isolated containers keep the hardening used in the spike.

**For ADR-0004 (job system): no library in the isolated workers, and `django-tasks` with `django-tasks-db` for trusted work.**

- The isolated consumer is about fifty lines on Redis lists, so it adds no dependency.
- For trusted work, `django-tasks` is the backport of Django's built-in tasks framework, so it follows the API the project would use on a later Django.
- Job state stays in PostgreSQL, the system of record.
- Both packages are before 1.0 and are to be pinned. A reaper for orphaned tasks is part of Phase 2.
- Redis keeps two uses: the isolated queues and throttling counters.
- **Alternatives for trusted work:** Celery once 5.7 is stable; Procrastinate, which is MIT-licensed and PostgreSQL-based, and was not tested; a small queue of our own on PostgreSQL.

Accepting these is the owner's decision. If they are accepted, ADR-0004 and ADR-0011 are rewritten as decided, the two packages are justified in the pull request that adds them (CLAUDE.md, architecture rule 14), and blockers B4 and B21 can be closed in the specification.

## What the spike did not cover

- Production orchestration (Kubernetes network policies, a sandbox such as gVisor), which waits for ADR-0008.
- IPv6 egress: the networks here were IPv4 only.
- A purpose-built egress proxy such as Smokescreen, which is worth comparing with Squid when Phase 2 is designed.
- Throughput and latency.
- Celery 5.7 final, Procrastinate, and the artifact store's backing technology (ADR-0008).

It tested the mechanism on one machine; it is evidence for a decision, not a production design.

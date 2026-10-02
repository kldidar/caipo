# ADR-0008: Deployment strategy

- Status: Proposed
- Date: 2026-10-01

## Context

Expected load is low and the team is small. The system needs several processes with different privileges and network access (ADR-0009, ADR-0011), a database, Redis, and an artifact store. The hosting target, budget, and any jurisdictional requirements for data location are unknown. Docker is required by the project brief. Docker and Docker Compose work in the development environment (verified 2026-10-02), and a development-only `docker-compose.yml` with PostgreSQL and Redis exists. That file is not the deployment this ADR describes: it publishes data ports on the loopback interface and runs no application containers.

## Decision (proposed)

- **One image** built in CI from the repository, tagged with the git commit, base image pinned by digest, running as a non-root user.
- **Docker Compose** for development, CI, staging, and production. Production is a single server.
- **Separate containers** for reverse proxy, web, default worker, fetch worker, parse worker, PostgreSQL, and Redis, on separate networks that implement the zones in [ARCHITECTURE.md](../ARCHITECTURE.md) §5.
- **Configuration.** Secrets and addresses by environment variables, supplied per container, so the fetch worker and parse worker never receive database or AI credentials. Result-affecting settings (model identifiers, chunking and retrieval parameters, prompt versions) come from the repository.
- **Redis** requires authentication and is not exposed outside the internal network.
- **Migrations** run as an explicit step in deployment, not at container start.
- **Artifact store** on a local volume to begin with, accessed by trusted components through Django's storage interface.
- **Isolated workers use mounted volumes only.** The fetch worker writes to a landing volume; the parse worker reads artifacts from a read-only mount. They hold no storage credentials and the parse worker has no network. If object storage is adopted later, trusted components can switch to it through the storage interface, but the isolated workers must still be given files through volumes staged by a trusted worker. Object storage is therefore not a drop-in change for the whole system.
- **Backups** of the database and artifact store, **encrypted** before leaving the server, to a different location, with keys held separately and a scheduled restore test.
- **Image build and image scan** run in CI once this ADR is accepted. The CI platform itself is not decided here: on 2026-10-02 the project owner approved GitHub Actions as Phase 1 engineering tooling, separately from this ADR (see [CONTRIBUTING.md](../../CONTRIBUTING.md)). That approval covers code checks only. It does not ratify anything in this ADR, and building or publishing a deployable image, hosting, and production infrastructure remain deferred.
- **Environments:** local, CI, staging, production. An evaluation database for AI evaluation lives on a development or staging machine; it is a separate database, not a separate service.
- **Rollback** is redeploying the previous image. A migration that the previous image cannot run against is flagged in its pull request with a rollback plan.

## Alternatives considered

- **Kubernetes.** No requirement justifies its operational cost.
- **Platform-as-a-service.** Simple, but network isolation between workers and egress filtering are harder to control, and both matter here.
- **Managed PostgreSQL.** Less operational work and better backups. Worth choosing if the hosting provider offers it with pgvector and budget allows. Left open.
- **Bare-metal installation without containers.** Loses reproducible builds and the network zoning.

## Consequences

- Simple to understand and operate.
- A single server is a single point of failure. Acceptable for a research platform if backups and restore are proven.
- Zero-downtime deployment is not a goal. Short maintenance windows are acceptable.
- Egress filtering on a single host needs deliberate network configuration.

## Open points

Acceptance requires:

1. A hosting target, with any data-location or institutional requirements stated (blocker B17).
2. Server size, informed by the embedding model decision (ADR-0006).
3. Choice of reverse proxy, error tracking service, and backup destination.
4. The isolation mechanism from ADR-0011, which determines the network and volume layout.

Resolved since this ADR was written: Docker works in the development environment (B1, closed), and the repository is hosted on GitHub (B2, closed). CI was approved separately as Phase 1 tooling and is not an open point of this ADR.

## Revisit when

Availability requirements rise, load exceeds one server, or the hosting institution mandates a platform.

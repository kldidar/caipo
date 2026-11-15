# ADR-0008: Deployment strategy

- Status: Proposed
- Date: 2026-10-01; revised 2026-11-11 with a concrete proposal

## Context

Expected load is low and the team is small. The system needs several processes with different privileges and network access (ADR-0009, ADR-0011), a database, Redis, and an artifact store. The hosting target, budget, and any jurisdictional requirements for data location are unknown. Docker is required by the project brief. Docker and Docker Compose work in the development environment (verified 2026-10-02), and a development-only `docker-compose.yml` with PostgreSQL and Redis exists. That file is not the deployment this ADR describes: it publishes data ports on the loopback interface and runs no application containers.

**Revision of 2026-11-11.** The owner asked on 2026-11-05 for a comparison of hosting options. It is in [the deployment options report](../reports/deployment-options-2026-11.md):
- the law on where personal data are stored;
- servers abroad and in Uzbekistan;
- email;
- the domain;
- backups.

ADR-0011, which sets the network and volume layout of the isolated workers, was accepted on 2026-11-05.

**Note of 2026-11-14.** A public instance of the demonstrator alone, on free hosting, is proposed separately in [ADR-0024](0024-public-demonstration-instance.md). It has no workers, so this ADR's reason for rejecting a platform-as-a-service does not apply to it. This ADR remains the deployment of the research platform. The concrete choices below are proposed with it. They take effect only if the owner accepts this ADR.

## Decision (proposed)

**Concrete choices proposed on 2026-11-11:**

1. **Host:** one Hetzner Cloud server in Germany. The plan is CPX22 (2 vCPU, 4 GB, 80 GB), or the nearest available plan of at least that size. The law allows a server in Germany for the personal data CAIPO holds (report §2). The alternative is Pro-Data Generic 4 in Tashkent, if the owner prefers the data to stay in Uzbekistan.
2. **Reverse proxy:** Caddy, which obtains and renews Let's Encrypt certificates itself and terminates TLS. It passes requests to the web container on an internal network. It is the one header source that the application trusts for the client address (diagnostic finding I2).
3. **First deployment:** the reverse proxy, the web application, and PostgreSQL. Redis, the workers, and the egress proxy are added with Phase 2, when its gate is READY, in the layout of ADR-0011.
4. **Email:** an SMTP relay through Django's built-in SMTP backend, with Brevo's free plan as the proposed service, sending from the project's domain with SPF and DKIM.
5. **Domain:** registered by the owner in the owner's name.
6. **Backups:**
   - the provider's daily server backups;
   - encrypted database dumps sent to storage in another location;
   - a restore test before the first real user registers, and then on a schedule.
7. **Error tracking:** none at first. Structured logs on the server, kept for a stated period, are the record; an external error tracker would be another processor of request data and needs its own decision.
8. **Before real users register:** a privacy notice and a security-incident procedure, as the report's §2 lists, checked by a lawyer (Q-8).

**The shape of the deployment, unchanged from 2026-10-01:**


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

1. A hosting target, with any data-location or institutional requirements stated (blocker B17). **Proposed on 2026-11-11:** see the concrete choices above and the report; the owner's acceptance is outstanding.
2. Server size, informed by the embedding model decision (ADR-0006). For the first deployment, 2 vCPU and 4 GB; Phase 5 may resize it.
3. Choice of reverse proxy, error tracking service, and backup destination. **Proposed:** Caddy; no error tracker at first; the off-site backup storage is chosen with the owner when the server is bought.
4. The isolation mechanism from ADR-0011, which determines the network and volume layout. **Resolved:** ADR-0011 was accepted on 2026-11-05.

Resolved since this ADR was written: Docker works in the development environment (B1, closed), and the repository is hosted on GitHub (B2, closed). CI was approved separately as Phase 1 tooling and is not an open point of this ADR.

## Revisit when

Availability requirements rise, load exceeds one server, or the hosting institution mandates a platform.

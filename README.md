# CAIPO — Central Asia AI Policy Observatory

Research platform for the study **"AI Policy and Economic Transformation in Central Asia: A Comparative Analysis of Turkmenistan and Uzbekistan"**.

CAIPO combines policy and legal documents, economic and socioeconomic indicators, structured policy metadata, and source provenance, and makes them available for comparative analysis and evidence-grounded AI question answering.

## Status

**Phase 1, project skeleton.** The foundation documents, a reproducible development environment, and the Django application skeleton exist: settings, the User foundation, roles and the authorization layer, sign-in and sign-out, TOTP multi-factor authentication, health endpoints, and structured logging. There is no research functionality: no documents, policies, indicators, claims, or AI assistant, and nothing is deployed.

The architecture gate is **READY for Phase 1** (project skeleton, authentication, countries and institutions) and **NOT READY for Phase 2 and later**: research, data-rights, isolation, and AI-provider questions are still open. They are listed in [docs/PROJECT_SPECIFICATION.md](docs/PROJECT_SPECIFICATION.md#10-architecture-gate). Implementation must not start on a phase until that phase's blockers are closed.

## What makes this project different

1. **Every claim is typed and traceable.** A documented fact, a stated policy objective, evidence of implementation, an observed outcome, a correlation, an interpretation, and a negative finding are different things and are stored as different things. See [docs/RESEARCH_PROTOCOL.md](docs/RESEARCH_PROTOCOL.md).
2. **Provenance is preserved.** Every document is stored as obtained, hashed, and versioned. Evidence points to exact passages in exact versions. See [docs/DATA_MODEL.md](docs/DATA_MODEL.md).
3. **AI answers are grounded or withheld.** The assistant can only cite evidence it actually retrieved, references are verified by the server, statements are attributed to their sources, and the system abstains when evidence is insufficient. See [docs/AI_ARCHITECTURE.md](docs/AI_ARCHITECTURE.md).
4. **External documents and datasets are untrusted input.** See [SECURITY.md](SECURITY.md), [ADR-0009](docs/adr/0009-untrusted-content-handling.md), and [ADR-0011](docs/adr/0011-worker-isolation-mechanism.md).
5. **No causal claims without a design that supports them.** See [docs/LIMITATIONS.md](docs/LIMITATIONS.md).

## Documentation map

| Document | Purpose |
|---|---|
| [docs/PROJECT_SPECIFICATION.md](docs/PROJECT_SPECIFICATION.md) | Scope, users, requirements, phases, architecture gate |
| [docs/RESEARCH_PROTOCOL.md](docs/RESEARCH_PROTOCOL.md) | Research questions, source rules, epistemic taxonomy, review workflow |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | System design, security boundaries, failure modes, deployment |
| [docs/DATA_MODEL.md](docs/DATA_MODEL.md) | Domain model and integrity rules |
| [docs/AI_ARCHITECTURE.md](docs/AI_ARCHITECTURE.md) | Retrieval, verification, synthesis, evaluation |
| [docs/REPRODUCIBILITY.md](docs/REPRODUCIBILITY.md) | What is pinned, recorded, and replayable |
| [docs/LIMITATIONS.md](docs/LIMITATIONS.md) | What this research and system cannot support |
| [docs/adr/](docs/adr/README.md) | Architecture decision records |
| [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) | Local development environment |
| [docs/RIGHTS_AND_LICENSING.md](docs/RIGHTS_AND_LICENSING.md) | Software license, and the separate rights in documents and data |
| [CLAUDE.md](CLAUDE.md) | Binding rules for AI implementation agents |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Workflow, tooling, Definition of Done |
| [SECURITY.md](SECURITY.md) | Threat model and security requirements |

## Technology baseline

**Accepted:** a Django modular monolith; PostgreSQL as the system of record; server-rendered templates with HTMX and no separate frontend; a public research site, an authenticated research workspace, and restricted administration.

**Proposed, not yet decided:** vector search with pgvector; the background job system (Celery with Redis is the working proposal); the AI provider; the deployment setup; the worker isolation mechanism.

Each is recorded as an [ADR](docs/adr/README.md). Nothing is added to this list without one.

## Getting started

The application is a skeleton: it starts, connects to PostgreSQL, and answers health checks.

```sh
uv sync
cp .env.example .env          # then set the two passwords and DJANGO_SECRET_KEY
docker compose up -d --wait
uv run --env-file .env pytest
uv run --env-file .env python manage.py migrate
uv run --env-file .env python manage.py create_first_administrator   # once, interactive
uv run --env-file .env python manage.py runserver                    # then open http://127.0.0.1:8000/login/
```

Full instructions are in [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md). The Compose file is for local development only, not for deployment.

## License

CAIPO's original software is released under the [MIT License](LICENSE).

The MIT License covers the software only. It does not cover government documents, research papers, datasets, logos, or any other third-party material that CAIPO stores or processes, nor text extracted from them. Those remain subject to their own rights holders' terms. The licence for research data created by the project is not yet decided. See [docs/RIGHTS_AND_LICENSING.md](docs/RIGHTS_AND_LICENSING.md).

# CAIPO — Central Asia AI Policy Observatory

Research platform for the study **"AI Policy and Economic Transformation in Central Asia: A Comparative Analysis of Turkmenistan and Uzbekistan"**.

CAIPO combines policy and legal documents, economic and socioeconomic indicators, structured policy metadata, and source provenance, and makes them available for comparative analysis and evidence-grounded AI question answering.

## Status

**Architecture and research foundation phase. There is no application code yet.**

The architecture gate is currently **NOT READY**. The blocking issues are listed in [docs/PROJECT_SPECIFICATION.md](docs/PROJECT_SPECIFICATION.md#10-architecture-gate). Implementation must not start on a phase until that phase's blockers are closed.

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
| [CLAUDE.md](CLAUDE.md) | Binding rules for AI implementation agents |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Workflow, tooling, Definition of Done |
| [SECURITY.md](SECURITY.md) | Threat model and security requirements |

## Technology baseline

Proposed: Django modular monolith, PostgreSQL with pgvector, Redis, Celery for ingestion and embedding jobs, Docker Compose. Every one of these is recorded as a **Proposed** [ADR](docs/adr/README.md); none has been ratified by the project owner yet. Nothing is added to this list without an ADR.

## Getting started

There is no application to run yet. A reproducible development baseline exists: a locked Python environment and local PostgreSQL and Redis services.

```sh
uv sync
cp .env.example .env          # then set the two passwords
docker compose up -d --wait
uv run --env-file .env pytest
```

Full instructions are in [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md). The Compose file is for local development only, not for deployment.

## License

Not yet decided. Until a license is added, no reuse rights are granted.

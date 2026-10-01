# Contributing to CAIPO

This applies to human contributors and AI agents. AI agents must also follow [CLAUDE.md](CLAUDE.md).

## Before you start

1. Check the architecture gate in [docs/PROJECT_SPECIFICATION.md](docs/PROJECT_SPECIFICATION.md#10-architecture-gate). Work on a phase starts only when its blockers are closed.
2. Read the documents relevant to your change (table in [CLAUDE.md](CLAUDE.md#read-before-working)).
3. If your change needs a decision that has not been made, open an ADR as **Proposed** first. Only the project owner accepts an ADR. See [docs/adr/README.md](docs/adr/README.md).

## Tooling

The toolchain is deliberately small. Versions are pinned in `pyproject.toml` and `uv.lock`. Setup and commands are in [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md).

| Purpose | Tool | Notes |
|---|---|---|
| Python and dependency management | `uv` | Lockfile committed |
| Lint and format | `ruff` | Includes the security (`S`) rule set |
| Type checking | `mypy` with `django-stubs` | Strict mode |
| Tests | `pytest`, `pytest-django` | Coverage reported; no numeric target is a substitute for testing failure paths |
| Module boundaries | `import-linter` | Enforces the app layering |
| Dependency vulnerabilities | `pip-audit` | Run in CI |
| Secret scanning | `gitleaks` | Pre-commit and CI |
| Container image scanning | `trivy` | CI, on built images |
| Git hooks | `pre-commit` | Runs ruff and gitleaks locally |
| CI | GitHub Actions | The repository is hosted on GitHub. CI is not configured yet. |

**Installed and locked:** `uv`, `ruff`, `mypy`, `pytest`. **Not yet set up:** `django-stubs`, `pytest-django`, and `import-linter` (they need a Django project to act on and are added with it), `pip-audit` (run on demand through `uvx`, not yet in CI), `gitleaks`, `trivy`, `pre-commit`, and CI. Each is checked against the pinned Python version when added (blocker B4).

No task runner (`make`, `just`) is adopted. Commands are run through `uv run` and `docker compose` and are documented in docs/DEVELOPMENT.md. This will be reconsidered if the command list becomes hard to remember.

## Workflow

- `main` is always releasable.
- Branch names: `feat/…`, `fix/…`, `docs/…`, `chore/…`, `research/…`.
- Commits are small and each one passes checks. Commit messages use the imperative mood and explain why the change is made.
- One change does one thing. Refactoring and behaviour change are separate.
- A change description states what changed, why, how it was tested, and any risk. For AI pipeline changes it includes evaluation results.

### Bootstrap exception

The repository starts empty, so the first commits cannot arrive by pull request. The foundation documents, and the minimal setup needed to make pull requests and CI possible (repository creation, CI configuration), may be committed directly to `main` by the project owner. This exception ends when CI is running. Each direct commit states in its message that it is a bootstrap commit. The first two commits, the foundation documents and the development environment, were made under this exception; their messages do not say so, and this note records it instead.

### Solo operation

The project may have one developer (team size is undecided, blocker B13). Independent review is then impossible, and pretending otherwise would be worse than saying so.

While there is one developer:

- Changes still go through a branch and a pull request, so that CI runs and the diff is recorded.
- The author performs a **recorded self-review**: reads the full diff, works through the review checklist below, and notes in the pull request that it was self-reviewed.
- CI must pass. It is the only independent check, so it is never bypassed.
- For changes to fetch, parse, authentication, rights, redaction, or the AI pipeline, the security checklist in [SECURITY.md](SECURITY.md) is worked through explicitly and the result written in the pull request.
- An AI agent's review may be used as an additional check. It does not count as independent human review.

As soon as a second contributor exists, review by someone other than the author becomes mandatory for every change, and the self-review rule lapses.

## Definition of Done

A feature is not complete unless every applicable item holds:

- Tests exist and pass
- Lint and format checks pass
- Type checking passes
- Import-layer check passes
- Security checks pass (dependency audit, secret scan, and image scan when images change)
- Database changes are reviewed (see below)
- Documentation is updated
- Error handling is addressed
- Logging is considered
- The git diff has been reviewed line by line

## Database changes

- Migrations are generated, read, and committed with the model change.
- Each migration is reversible, or the pull request states why it is not and gives the rollback plan.
- Schema changes on populated tables are split so each step is safe: add nullable column, backfill, then add constraint.
- Data migrations never modify append-only records (see [docs/DATA_MODEL.md](docs/DATA_MODEL.md#6-integrity-rules)). Redaction is not done by migration.
- Applied migrations are never edited.

## Review checklist

Whoever reviews, the author included, checks in this order:

1. Does it violate a research integrity or security rule?
2. Is it correct, and do the tests prove it?
3. Does it respect the architecture rules and use the vocabulary of the data model?
4. Is it as simple as it can be?

## Research content contributions

Adding sources, coding policies, recording searches, entering claims, and building evaluation datasets are research activities governed by [docs/RESEARCH_PROTOCOL.md](docs/RESEARCH_PROTOCOL.md). They are done through the application, not through code or database edits, so that provenance and review are recorded.

## What not to contribute

- Real research data in test fixtures. Fixtures are visibly synthetic.
- Copyrighted documents or raw datasets in the repository. Artifacts live in artifact storage. Only the synthetic fixture and adversarial corpora are committed.
- Secrets of any kind.

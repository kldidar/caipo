# Contributing to CAIPO

This applies to human contributors and AI agents. AI agents must also follow [CLAUDE.md](CLAUDE.md).

## Before you start

1. Check the architecture gate in [docs/PROJECT_SPECIFICATION.md](docs/PROJECT_SPECIFICATION.md#10-architecture-gate). Work on a phase starts only when its blockers are closed.
2. Read the documents relevant to your change (table in [CLAUDE.md](CLAUDE.md#read-before-working)).
3. If your change needs a decision that has not been made, open an ADR as **Proposed** first. Only the project owner accepts an ADR. Do not build on a Proposed ADR. See [docs/adr/README.md](docs/adr/README.md).

## Tooling

The toolchain is deliberately small. Versions are pinned in `pyproject.toml` and `uv.lock`. Setup and commands are in [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md).

| Purpose | Tool | Notes |
|---|---|---|
| Python and dependency management | `uv` | Lockfile committed |
| Lint and format | `ruff` | Includes the security (`S`) rule set |
| Type checking | `mypy` with `django-stubs` | Strict mode |
| Tests | `pytest`, `pytest-django` | Coverage is not measured: no coverage tool is set up. No numeric target is a substitute for testing failure paths |
| Module boundaries | `import-linter` | Enforces the app layering, and that `registry` uses `accounts` only through its services and selectors |
| Dependency vulnerabilities | `pip-audit` | Run in CI through `uvx`, at a pinned version, against the lockfile |
| Secret scanning | `gitleaks` | Run in CI from its container image, pinned by digest. Not yet a pre-commit hook. |
| Container image scanning | `trivy` | Planned, not set up. Would scan built images in CI; no image is built, and image build and scan wait for ADR-0008 |
| Git hooks | `pre-commit` | Planned, not set up. Would run ruff and gitleaks locally; no git hook is installed |
| CI | GitHub Actions | Approved by the project owner on 2026-10-02 as Phase 1 engineering tooling. Defined in `.github/workflows/ci.yml`. |

**Installed and locked:** `uv`, `ruff`, `mypy`, `django-stubs`, `pytest`, `pytest-django`, and `import-linter`. **Run in CI without being installed in the project:** `pip-audit` and `gitleaks`. **Not yet set up:** `trivy`, `pre-commit`, and any coverage tool. Each is checked against the pinned Python version when added (blocker B4).

### Continuous integration

The workflow is `.github/workflows/ci.yml`. It runs on every push to `main` and on every pull request against `main`, so it also covers commits made directly to `main` under the bootstrap exception below. It has four jobs, which run in parallel and fail independently:

| Job | Checks | Fails when |
|---|---|---|
| Code quality | `uv lock --check`, `uv sync --locked`, the interpreter against `.python-version`, `ruff check`, `ruff format --check`, `mypy`, `lint-imports` | The lockfile does not match `pyproject.toml`, or any check reports a problem. The four code checks all run even if one fails. |
| Django checks and tests | `manage.py check`, `manage.py makemigrations --check`, `pytest` | A system check fails, a model change has no migration, or a test fails |
| Dependency audit | `pip-audit` on the exported lockfile, with hashes | A locked package, runtime or development, has a known vulnerability |
| Secret scan | `gitleaks` over the committed history | Secret material is found in any commit |

How it is built:

- **Services.** The tests job starts PostgreSQL and Redis with `docker compose up`, from the same `docker-compose.yml` used locally, so the images, encoding, and collation are identical. Redis is started only because `tests/test_dev_services.py` tests it; the application does not use Redis yet. Service passwords are generated in each run and masked in the log. Only the synthetic fixture corpus is used.
- **Settings.** Django commands run under the testing settings. No signing key or other secret is configured in GitHub.
- **Permissions.** The workflow token can read the repository and nothing else, and checkout does not leave it in the git configuration.
- **Pinning.** The two actions used (GitHub's `checkout` and Astral's `setup-uv`) are pinned to a full commit SHA with the release tag in a comment. `uv`, `pip-audit`, and the runner image are pinned by version, and the `gitleaks` image by digest. Updating a pin is an ordinary reviewed change. Nothing updates them automatically yet.
- **Caching.** Only the `uv` package cache, keyed on `uv.lock`.

The secret scan reads commits, not the working directory. A secret that was ever committed keeps failing the scan after it is deleted, because it is still in the history: revoke the secret first, then decide with the project owner how to record it. Do not silence a finding to make the job pass.

Commands to run the same checks locally are in [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md#continuous-integration).

### CI is not deployment

CI runs checks on the code and nothing else. It does not deploy anything, holds no production credentials, runs no migration against a real database, and does not build or publish a deployable image. Deployment, hosting, and production infrastructure belong to ADR-0008, which is still Proposed, and stay deferred until it is decided.

No task runner (`make`, `just`) is adopted. Commands are run through `uv run` and `docker compose` and are documented in docs/DEVELOPMENT.md. This will be reconsidered if the command list becomes hard to remember.

## Workflow

- `main` is always releasable.
- Branch names: `feat/…`, `fix/…`, `docs/…`, `chore/…`, `research/…`.
- Commits are small and each one passes checks. Commit messages use the imperative mood and explain why the change is made.
- One change does one thing. Refactoring and behaviour change are separate.
- A change description states what changed, why, how it was tested, and any risk. For AI pipeline changes it includes evaluation results.

### Bootstrap exception

The repository starts empty, so the first commits cannot arrive by pull request. The foundation documents, and the minimal setup needed to make pull requests and CI possible (repository creation, CI configuration), may be committed directly to `main` by the project owner. This exception ends when CI is running. Each direct commit states in its message that it is a bootstrap commit.

#### History of direct commits to `main`

This records what happened; the history itself is not rewritten. Checked on 2026-10-30 against `git log --first-parent main`, the CI run history, and the repository's ruleset.

- Nine commits were made directly to `main`, from `9ea0e61` (2026-10-01) to `bd7b50a` (2026-10-03). None of their messages says that it is a bootstrap commit; this note records them instead.
- Six came before CI was running: the foundation documents (`9ea0e61`), the development environment (`30e0374`), two documentation updates (`1280634`, `466baa3`), the Django application foundation (`6a92e8e`), and the CI workflow (`e8b7622`). CI first ran on `e8b7622`, on 2026-10-02. The application foundation is application code, which the exception does not name.
- Three came after CI was running, and so outside the exception as written: the identity and authorization foundation (`88dcc0c`), the authentication core (`875c934`), and TOTP multi-factor authentication (`bd7b50a`). CI ran on each push and passed.
- Every change since has reached `main` through a pull request, starting with #1, merged on 2026-10-03. The ruleset that protects `main`, created the same day after #1 was merged, requires a pull request and the four CI checks, and allows no bypass.

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
- Security checks pass (dependency audit and secret scan; an image scan is added once images are built, under ADR-0008)
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

## Licensing of contributions

CAIPO's original software is under the [MIT License](LICENSE). By contributing code, configuration, tests, or project documentation, you agree that your contribution is licensed under the same terms.

The MIT License covers the software only. Do not add third-party documents, datasets, logos, or extracted text to the repository, and do not describe such material as covered by the project's license. See [docs/RIGHTS_AND_LICENSING.md](docs/RIGHTS_AND_LICENSING.md).

## What not to contribute

- Real research data in test fixtures. Fixtures are visibly synthetic.
- Copyrighted documents or raw datasets in the repository. Artifacts live in artifact storage. Only the synthetic fixture and adversarial corpora are committed.
- Secrets of any kind.

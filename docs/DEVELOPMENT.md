# Development environment

How to set up and run CAIPO locally. The environment provides a pinned Python environment and two backing services, PostgreSQL and Redis. The application is a Django skeleton: settings, the User foundation, health endpoints, and structured logging.

Last verified end to end on 2026-10-02. What was verified, and what was not, is recorded in [PROJECT_SPECIFICATION.md](PROJECT_SPECIFICATION.md) §9.

## Development is not production

`docker-compose.yml` is for local development and CI only. It publishes database and broker ports on the loopback interface so that tools on the host can reach them, and it runs no application containers. The production deployment ([ADR-0008](adr/0008-deployment-strategy.md), Proposed) will be a separate configuration with network zones, TLS, backups, and no published data ports. Do not deploy this file. `manage.py runserver` is likewise a development server only.

## Prerequisites

| Tool | Version verified | Notes |
|---|---|---|
| Docker with the Compose plugin | Docker 29.8.1, Compose v5.5.1 | On WSL2, enable WSL integration for your distribution in Docker Desktop |
| `uv` | 0.12.21 | Manages Python and dependencies |
| Git | 2.53.0 | |

Python 3.14 is required (`.python-version`). If it is not installed, `uv` downloads it.

Nothing else needs to be installed on the host. There is no Makefile; commands are run with `uv` and `docker compose` directly.

## First-time setup

```sh
uv sync                      # create .venv and install the locked dependencies
cp .env.example .env         # then edit .env
```

In `.env`, set `POSTGRES_PASSWORD`, `REDIS_PASSWORD`, and `DJANGO_SECRET_KEY` to three different generated values:

```sh
python3 -c "import secrets; print(secrets.token_urlsafe(50))"
```

An `.env` created before the Django skeleton existed also needs the `DJANGO_SETTINGS_MODULE` line from `.env.example`.

`.env` is ignored by git. Every variable is documented in `.env.example`. Compose refuses to start while a required variable is empty.

## Services

| Service | Image | Published on | Data |
|---|---|---|---|
| `postgres` | PostgreSQL 18.6 | `127.0.0.1:15432` | Named volume `caipo_postgres_data` |
| `redis` | Redis 8.10.2 | `127.0.0.1:16379` | None. Redis holds only data that may be lost. |

The host ports are deliberately not the defaults (5432, 6379), so they do not collide with a PostgreSQL or Redis installed directly on the host. Change `POSTGRES_PORT` or `REDIS_PORT` in `.env` if needed.

```sh
docker compose up -d --wait   # start and wait until both are healthy
docker compose ps             # status and health
docker compose logs -f        # follow logs
docker compose stop           # stop, keep containers and data
docker compose down           # remove containers, keep the database volume
docker compose down -v        # remove containers AND delete the database
```

### Checking health

`docker compose ps` shows `healthy` for both services. To check by hand:

```sh
docker compose exec postgres sh -c 'pg_isready --host=127.0.0.1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
docker compose exec redis redis-cli ping
```

To check connectivity from the host with the credentials in `.env`, run the tests (below).

### Things to know

- `POSTGRES_PASSWORD` is applied only when the database volume is first created. Changing it in `.env` later does not change it in the database. Either change it inside PostgreSQL or run `docker compose down -v` and start again.
- The database is created with UTF-8 encoding and PostgreSQL's built-in `C.UTF-8` collation provider, set explicitly in the Compose file.
- Redis requires the password and has persistence turned off.

## Dependencies

Dependencies are declared in `pyproject.toml` and pinned in `uv.lock`, which is committed.

```sh
uv sync                               # install exactly what the lockfile says
uv sync --locked                      # same, but fail if the lockfile is out of date (use in CI)
uv add <package>                      # add a runtime dependency and update the lockfile
uv add --group dev <package>          # add a development dependency
uv lock                               # re-resolve after editing pyproject.toml by hand
uv lock --upgrade-package <package>   # upgrade one package
uv lock --check                       # verify the lockfile matches pyproject.toml
```

Do not use `pip install`. Every new dependency needs the justification described in [CLAUDE.md](../CLAUDE.md).

The `redis` client is capped below 6.5 on purpose: Celery's transport library requires it. See the comment in `pyproject.toml`. Celery itself is not installed, and must not be added yet: the job system is chosen by a spike at the Phase 2 gate (ADR-0004).

## Running Django

Django commands read their configuration from the environment, so they are run with the `.env` file. The services must be running.

```sh
uv run --env-file .env python manage.py check            # system checks
uv run --env-file .env python manage.py showmigrations   # migration state
uv run --env-file .env python manage.py migrate          # apply migrations to the development database
uv run --env-file .env python manage.py runserver        # http://127.0.0.1:8000/
```

### Settings

| Module | Used by | Notes |
|---|---|---|
| `caipo.config.settings.base` | Imported by the others; the type checker | Reads nothing from the environment. Holds no secret key and no database. |
| `caipo.config.settings.development` | `manage.py`, through `DJANGO_SETTINGS_MODULE` in `.env` | `DEBUG` on, loopback hosts only, cookies allowed over plain HTTP |
| `caipo.config.settings.testing` | `pytest`, always | Generates its own secret key for each run |
| `caipo.config.settings.production` | The default when `DJANGO_SETTINGS_MODULE` is unset | A baseline, not a complete production configuration. Also requires `DJANGO_ALLOWED_HOSTS`, a comma-separated list without wildcards, and refuses a `DJANGO_SECRET_KEY` shorter than 50 characters. |

A required variable that is missing stops start-up with an error naming the variable. If a command reports that `DJANGO_ALLOWED_HOSTS` is not set during local work, `DJANGO_SETTINGS_MODULE` is missing from `.env` and the production settings were selected.

### Health endpoints

| Path | Meaning | Response |
|---|---|---|
| `/health/live/` | The process is serving requests. Touches nothing else. | `200` `{"status": "ok"}` |
| `/health/ready/` | The process can reach PostgreSQL. | `200` `{"status": "ok", "checks": {"database": "ok"}}`, or `503` with `"unavailable"` in both places |

```sh
curl -i http://127.0.0.1:8000/health/ready/
```

Both accept `GET` only and are reachable without signing in. Readiness does not check Redis yet, because the application does not use it yet.

### Logs

Logs are written to standard output as one JSON object per line, with `timestamp`, `level`, `logger`, `message`, and `correlation_id`. The start-up banner of `runserver` is printed by Django outside the logging system and is plain text.

## Signing in

```sh
uv run --env-file .env python manage.py migrate
uv run --env-file .env python manage.py create_first_administrator
uv run --env-file .env python manage.py runserver        # then http://127.0.0.1:8000/login/
```

`create_first_administrator` creates the only account the application can create so far. It is interactive and works once; what it asks for, and why it has no options, is in [SECURITY.md](../SECURITY.md), "The first Administrator". To start again locally, recreate the development database (`docker compose down -v`).

During an initial deployment it is run once, by the person installing the system, in a terminal on the server and under the settings of that environment, after `migrate` and before anyone needs to sign in. In a container that means an interactive session, for example `docker compose exec` with a terminal attached. It cannot be put in a start-up script, because it refuses to run without a terminal.

The pages are `/login/` and `/logout/`. A view never checks a password itself: `caipo.accounts.services.sign_in` decides, throttles, and records, and the view only establishes the session. After 5 refused attempts for one email address, or 20 from one source, within 15 minutes, the page answers 429; signing in successfully from another address does not lift that, waiting does. The limits are `LOGIN_THROTTLE_*` in `caipo/config/settings/base.py`. The decisions, and what is deferred to later increments, are in [ADR-0013](adr/0013-authentication-core-and-first-administrator-bootstrap.md).

The first Administrator can sign in but has no administrative privileges, because those require TOTP, which is not implemented. That is intended, and there is no setting that changes it.

The sign-in tests use the real Argon2 hasher, which is why the suite takes about a minute.

## Authorization

No page uses this yet apart from the sign-in pages, which are public. It is the layer that views and services are written against.

**A view declares the access it requires**, outermost, with `public` or with `requires` and a permission. A view with no declaration answers 403.

```python
from caipo.accounts.selectors import Permission
from caipo.web.access import public, requires


@requires(Permission.WORKSPACE_READ)
def some_workspace_page(request): ...
```

**A service checks for itself**, whatever the view has checked:

```python
from caipo.accounts import selectors

selectors.require_permission(actor, selectors.Permission.ROLES_MANAGE)  # raises PermissionDenied
if selectors.can(user, selectors.Permission.WORKSPACE_READ):
    ...  # yes or no, never raises
```

Code asks for a permission, never for a role. Roles, permissions, and the table connecting them are in `caipo/accounts/authorization.py`; add a permission there only when a feature needs to tell two accounts apart. Roles change only through `caipo.accounts.services.grant_role` and `revoke_role`, each of which appends a RoleEvent, and accounts are deactivated through `deactivate_user`. These refuse an actor changing their own roles and any change that would leave no Administrator.

Reviewer and Administrator roles confer nothing until TOTP exists ([SECURITY.md](../SECURITY.md), "Authorization as implemented"). In tests, the `user_with_roles` fixture (in `caipo/accounts/tests/fixtures.py`) creates synthetic users with roles, and the `mfa_enrolled` fixture stands in for enrolment. That fixture is test-only: it replaces a function inside the test process, and the application has no setting, variable, or input that does the same. Do not add one.

Role events cannot be updated or deleted, by the application or by SQL: a database trigger refuses both. A test that needs a different role history adds events; it does not edit them.

## Tests and checks

The services must be running for the tests.

```sh
uv run --env-file .env pytest     # test suite
uv run ruff check .               # lint
uv run ruff format --check .      # formatting
uv run mypy .                     # type checking
uv run lint-imports               # app layering (docs/ARCHITECTURE.md §2)
```

Tests run under the testing settings whatever `DJANGO_SETTINGS_MODULE` says, against PostgreSQL, in a database named `test_<POSTGRES_DB>` that the run creates and removes. The development database is not touched. Tests for an app live in that app's `tests/` package; tests of the project as a whole live in `tests/`.

## Continuous integration

GitHub Actions runs `.github/workflows/ci.yml` on every push to `main` and every pull request against `main`. What each job checks, and how the workflow is pinned and permissioned, is described in [CONTRIBUTING.md](../CONTRIBUTING.md#continuous-integration). CI checks code only; it deploys nothing.

### Reproducing CI locally

With the services running, these are the commands CI runs, job by job.

Code quality:

```sh
uv lock --check                   # lockfile matches pyproject.toml
uv sync --locked                  # install exactly the lockfile
uv run ruff check .
uv run ruff format --check .
uv run mypy .
uv run lint-imports
```

Django checks and tests:

```sh
uv run --env-file .env python manage.py check
uv run --env-file .env python manage.py makemigrations --check --dry-run
uv run --env-file .env pytest
```

Dependency audit:

```sh
uv export --locked --no-emit-project --format requirements-txt --output-file /tmp/caipo-requirements.txt
uvx pip-audit==2.10.1 --require-hashes --disable-pip --requirement /tmp/caipo-requirements.txt
```

Secret scan:

```sh
docker run --rm --network none --read-only --cap-drop ALL --security-opt no-new-privileges \
  --volume "$PWD:/repo:ro" \
  ghcr.io/gitleaks/gitleaks:v8.30.1@sha256:c00b6bd0aeb3071cbcb79009cb16a60dd9e0a7c60e2be9ab65d25e6bc8abbb7f \
  git /repo --redact=100 --no-banner --verbose
```

Differences from CI to keep in mind:

- CI starts from a fresh checkout with no `.env`. It takes service names and ports from the workflow, generates the two service passwords for each run, and runs the two `manage.py` commands under the testing settings. Locally, `.env` selects the development settings for them.
- The secret scan covers commits only. Run it after committing and before pushing; it does not see uncommitted changes, and it does not read `.env`.
- The pinned versions of `uv`, `pip-audit`, and `gitleaks` are in the workflow file. If you change one there, change it here.

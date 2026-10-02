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

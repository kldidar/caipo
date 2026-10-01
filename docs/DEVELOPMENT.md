# Development environment

How to set up and run the local development baseline. It provides a pinned Python environment and two backing services, PostgreSQL and Redis. There is no application code yet.

Last verified end to end on 2026-10-02. What was verified, and what was not, is recorded in [PROJECT_SPECIFICATION.md](PROJECT_SPECIFICATION.md) §9.

## Development is not production

`docker-compose.yml` is for local development and CI only. It publishes database and broker ports on the loopback interface so that tools on the host can reach them, and it runs no application containers. The production deployment ([ADR-0008](adr/0008-deployment-strategy.md), Proposed) will be a separate configuration with network zones, TLS, backups, and no published data ports. Do not deploy this file.

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

In `.env`, set `POSTGRES_PASSWORD` and `REDIS_PASSWORD` to two different generated values:

```sh
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

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

The `redis` client is capped below 6.5 on purpose: Celery's transport library requires it. See the comment in `pyproject.toml`. Celery itself is not installed yet; its support for Python 3.14 is an open question (ADR-0004).

## Tests and checks

The services must be running for the tests.

```sh
uv run --env-file .env pytest     # test suite
uv run ruff check .               # lint
uv run ruff format --check .      # formatting
uv run mypy                       # type checking
```

The only tests so far are smoke tests for the two services (`tests/test_dev_services.py`). They check that each service accepts the configured credentials and rejects a client without them. As application code is added, its tests run with the same command.

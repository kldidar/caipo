# Development environment

How to set up and run CAIPO locally. The environment provides a pinned Python environment and two backing services, PostgreSQL and Redis. The application is a Django skeleton: settings, the User foundation, sign-in with TOTP multi-factor authentication, health endpoints, and structured logging.

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

Set `TOTP_ENCRYPTION_KEY` to a fourth, which has its own form, 32 random bytes as URL-safe Base64:

```sh
python3 -c "import base64, secrets; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())"
```

An `.env` created before the Django skeleton existed also needs the `DJANGO_SETTINGS_MODULE` line from `.env.example`, and one created before multi-factor authentication existed needs the `TOTP_ENCRYPTION_KEY` line. Without it every `manage.py` command stops with an error naming the variable. The test suite does not need it: it generates its own key.

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
| `caipo.config.settings.base` | Imported by the others; the type checker | Reads nothing from the environment. Holds no secret key, no encryption key, and no database. |
| `caipo.config.settings.development` | `manage.py`, through `DJANGO_SETTINGS_MODULE` in `.env` | `DEBUG` on, loopback hosts only, cookies allowed over plain HTTP. Requires `TOTP_ENCRYPTION_KEY`. |
| `caipo.config.settings.testing` | `pytest`, always | Generates its own secret key and TOTP encryption key for each run |
| `caipo.config.settings.production` | The default when `DJANGO_SETTINGS_MODULE` is unset | A baseline, not a complete production configuration. Also requires `DJANGO_ALLOWED_HOSTS`, a comma-separated list without wildcards, refuses a `DJANGO_SECRET_KEY` shorter than 50 characters, and refuses a `TOTP_ENCRYPTION_KEY` that is not 32 bytes of URL-safe Base64. |

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

`create_first_administrator` creates the only account the application can create so far. It is interactive and works once; what it asks for, and why it has no options, is in [SECURITY.md](../SECURITY.md), "The first Administrator". Have an authenticator application at hand (any that implements TOTP: six digits, 30 seconds): after the email address, the password, and the confirmation, the command writes a key to the terminal, once, and asks for the code the application shows for it. The account is created only when a code is accepted. After three codes that are not, nothing has been created and the command can be run again. To start again locally after it has succeeded, recreate the development database (`docker compose down -v`).

During an initial deployment it is run once, by the person installing the system, in a terminal on the server and under the settings of that environment, after `migrate` and before anyone needs to sign in. In a container that means an interactive session, for example `docker compose exec` with a terminal attached. It cannot be put in a start-up script, because it refuses to run without a terminal.

The pages are `/login/` and `/logout/`. A view never checks a password itself: `caipo.accounts.services.sign_in` decides, throttles, and records, and the view only establishes the session. After 5 refused attempts for one email address, or 20 from one source, within 15 minutes, the page answers 429; signing in successfully from another address does not lift that, waiting does. The limits are `LOGIN_THROTTLE_*` in `caipo/config/settings/base.py`. The decisions, and what is deferred to later increments, are in [ADR-0013](adr/0013-authentication-core-and-first-administrator-bootstrap.md).

The first Administrator signs in with its password and then a code from the authenticator that was set up by the command: the password alone signs nobody in, and there is no setting that changes it. See the next section.

A development database whose Administrator was created before the bootstrap set up the second factor (migration `accounts/0005_second_factor_approval`) has an Administrator whose second factor nobody approved, and nobody who could approve it. Recreate that database.

The sign-in tests use the real Argon2 hasher, which is why the suite takes about a minute.

## Two-step verification

Decided in [ADR-0014](adr/0014-totp-mfa-and-authentication-assurance.md); what it does and does not protect is in [SECURITY.md](../SECURITY.md), "Multi-factor authentication as implemented".

To enrol, sign in and open `/account/second-factor/`. Give the password again to get a key, add the key to an authenticator application (any that implements TOTP: six digits, 30 seconds), and enter the current code. The key is shown once; if it is lost before the code is entered, start again. There is no QR code.

A Reader or Researcher account does all of that by itself. A Reviewer or Administrator account cannot: its password must not be enough to give it a second factor. Such an account is shown its key together with a request number, and codes are not accepted until an Administrator has approved that request. The person gives the number to an Administrator themselves, not through the site. The Administrator, signed in with their own second factor, opens `/administration/second-factor-requests/`, ticks the confirmation for the request with that number, and approves it. The person then enters the current code. Asking for a key again makes a new request with a new number and no approval. The first Administrator is the exception: its second factor is set up by `create_first_administrator`.

From then on `/login/` asks for the password and then, at `/login/verify/`, for a code. A code works once, so signing in again within the same 30 seconds means waiting for the next code.

| Page | Method | What it does |
|---|---|---|
| `/login/verify/` | GET, POST | Asks for the code of a sign-in whose password was accepted. Nobody is signed in until the code is. |
| `/account/second-factor/` | GET | Shows whether two-step verification is off, awaiting approval, awaiting its first code, or on |
| `/account/second-factor/enrol/` | POST | Password again; issues a new key and shows it once, with a request number where approval is needed |
| `/account/second-factor/confirm/` | POST | A code from the new key; turns two-step verification on. Refused while the request awaits approval. |
| `/account/second-factor/replace/` | POST | Password and a current code; gives up the present key and issues a new one, which needs approval where enrolling did |
| `/account/second-factor/disable/` | POST | Password and a current code; turns it off |
| `/administration/second-factor-requests/` | GET | For an Administrator signed in with a second factor: the requests that await a decision |
| `/administration/second-factor-requests/<number>/approve/` | POST | Approves one request; needs the ticked confirmation |
| `/administration/second-factor-requests/<number>/reject/` | POST | Rejects one request and discards its key |

After 5 refused codes for one account within 15 minutes the pages answer 429 until earlier refusals are 15 minutes old. Nothing lifts that sooner. The limits and lifetimes are `MFA_*` and `TOTP_*` in `caipo/config/settings/base.py`.

**The encryption key.** TOTP secrets are stored encrypted under `TOTP_ENCRYPTION_KEY`. Changing that key, or losing it, makes every enrolled second factor unusable: each enrolled account is refused at the code step. Locally, recreate the development database (`docker compose down -v`) or delete the rows of `accounts_totpdevice`. Rotating the key without that loss is not built; it is designed with the deployment decision (ADR-0008).

**A lost device.** There are no recovery codes and no reset by an Administrator. The account's row in `accounts_totpdevice` has to be deleted in the database by its owner; the account then signs in with its password and enrols again, with an Administrator's approval if it is a Reviewer or Administrator. For the only Administrator that approval cannot be given by anybody: locally, recreate the development database. Keep a second Administrator in any database that matters.

## Creating accounts

Decided in [ADR-0015](adr/0015-account-lifecycle-and-email-verification.md); what it protects is in [SECURITY.md](../SECURITY.md), "Account lifecycle as implemented".

An Administrator, signed in with their second factor, opens `/administration/accounts/`, gives an email address, and chooses one role. The account is created awaiting verification and a message is sent to that address. The Administrator never sets a password.

**No email is sent in development.** Each message is written to a file in `data/outbox/`, which git ignores. Open the newest file there to find the link:

```sh
ls -t data/outbox/ | head -1
```

The link is `http://127.0.0.1:8000/activate/#<token>`. Opening it shows a form with the token filled in; the person chooses a password and is sent to `/login/`. The link works once and for 48 hours. "Send the message again" on the accounts page writes a new file and makes the earlier link stop working. Delete the files in `data/outbox/` when you are done: each holds a link that can still be used.

| Page | Method | What it does |
|---|---|---|
| `/administration/accounts/` | GET | For an Administrator signed in with a second factor: the form, and the accounts that await verification |
| `/administration/accounts/create/` | POST | Creates an account that awaits verification and sends its message |
| `/administration/accounts/<id>/send-verification/` | POST | Sends the message again, with a new link |
| `/activate/` | GET, POST | Public. Verifies the address and sets the password, given the token from the message. |

Disabling and enabling an account are `caipo.accounts.services.disable_user` and `enable_user`. They have no page yet.

The limits and the lifetime are `ACCOUNT_ACTIVATION_*` in `caipo/config/settings/base.py`. The address used in links is `PUBLIC_BASE_URL`: fixed in development, and read from `CAIPO_PUBLIC_URL` in production, which accepts only `https://host[:port]` and refuses to start without it. In production no email service is configured yet (ADR-0008), so there a message is refused and the page says it could not be sent.

A new Reviewer or Administrator account, once activated, still has to turn on two-step verification with an Administrator's approval before the role gives it anything (see above).

## Authorization

No page uses this yet apart from the sign-in pages, which are public, and the second-factor pages. It is the layer that views and services are written against.

**A view declares the access it requires**, outermost, with `public` or with `requires` and a permission. A view with no declaration answers 403.

```python
from caipo.accounts.selectors import Permission
from caipo.web.access import public, requires


@requires(Permission.WORKSPACE_READ)
def some_workspace_page(request): ...
```

**A service checks for itself**, whatever the view has checked. It is given the authentication context of whoever is acting, which is the account together with the assurance of its sign-in, and never a bare account:

```python
from caipo.accounts import selectors
from caipo.web import sessions

actor = sessions.authentication_context(request)  # in a view; None for an anonymous visitor

selectors.require_permission(actor, selectors.Permission.ROLES_MANAGE)  # raises PermissionDenied
if selectors.can(actor, selectors.Permission.WORKSPACE_READ):
    ...  # yes or no, never raises
```

A view passes `actor` on to the service it calls, as `services.grant_role(actor=actor, ...)` does. An account passed where a context is expected holds no permission. Code never asks whether an account has a second factor or which assurance it has: the policy decides which permissions need which.

Code asks for a permission, never for a role. Roles, permissions, and the table connecting them are in `caipo/accounts/authorization.py`; add a permission there only when a feature needs to tell two accounts apart. Roles change only through `caipo.accounts.services.grant_role` and `revoke_role`, each of which appends a RoleEvent, and accounts are created through `create_user`, disabled through `disable_user`, and enabled through `enable_user`. These refuse an actor changing their own roles and any change that would leave no Administrator.

Reviewer and Administrator roles confer their permissions only at the `MFA_VERIFIED` assurance. In tests, the `user_with_roles` fixture (in `caipo/accounts/tests/fixtures.py`) creates synthetic users with roles. The helpers beside it give the context to act in: `signed_in(user)` for a sign-in with the password alone, and `verified(user)`, which gives the account a real, encrypted, trusted second factor and returns the context the verification service returns for it. `enrolled_device(user, trusted=False)` gives the device an account enrols on its password alone, and `approving_administrator()` the context of an Administrator who can approve a request. `code_at()` computes the code an authenticator would show. For HTTP tests, `caipo/web/tests/helpers.py` puts a test client in either state. Nothing replaces the authorization decision in a test, and the application has no setting, variable, or input that switches the requirement off. Do not add one.

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

# The public demonstration instance

Status: Runbook for the owner · Decided by [ADR-0024](adr/0024-public-demonstration-instance.md) · Built on Day 46, deployed on Day 47

One public copy of the demonstrator, on Render's free web service and a free Neon PostgreSQL database, both in Frankfurt. It holds demonstration and reference data only. It is not the research platform, whose deployment stays with ADR-0008.

**Every step here is the owner's.** The accounts are in the owner's name. The secrets are made on the owner's machine and typed only into Render and into the owner's own terminal: never into the repository, a file Claude Code reads, or a message to Claude Code.

## What the instance is

| | |
|---|---|
| Image | `Dockerfile`, built by Render from `main` whenever the owner merges. It runs gunicorn as a user that is not root. Its static files are served by the web process. |
| Settings | `caipo.config.settings.instance` (set in the image) |
| What it closes | Registration and password reset, because it sends no email |
| Who signs in | The shared demonstration Reader, whose address and password the sign-in page shows. It can read every page a Reader can and ask the assistants, but cannot manage a second factor or submit an article. The demonstration Researcher has a password only the owner knows. There is no Administrator. |
| What a visitor is told | A notice on every page: it is a demonstration, the server keeps request logs, and it may take a minute to wake. Next to each assistant: questions are kept until the site is taken down, by 30 June 2027 at the latest (B19, decided 2026-11-23). |
| Migrations | Never at start. The owner runs them from their machine (ADR-0024 point 4). |

## 1. Make the secrets, on your machine

Run each line in your own terminal. Paste each value straight into Render (step 3). Do not save it in a file in the repository.

```
python3 -c "import secrets; print(secrets.token_urlsafe(64))"                                       # DJANGO_SECRET_KEY
python3 -c "import base64, secrets; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())"  # TOTP_ENCRYPTION_KEY
```

Choose two passwords:
- **the shared Reader's**, which the sign-in page will show to everyone (`CAIPO_SHARED_PASSWORD`);
- **the Researcher's**, which stays yours alone.

## 2. Neon: the database

1. Create a project in the region **AWS Europe Central 1 (Frankfurt)**.
2. Choose PostgreSQL **18**, the version CI tests on. If Neon offers only an older one, tell Claude Code: the suite is run on it before going on.
3. Press **Connect**, turn **Connection pooling** off, and note from the connection string `postgresql://USER:PASSWORD@HOST/DB?sslmode=require` the host (it has no `-pooler`), database name, user, and password. Connections use TLS; the instance requires it.

## 3. Render: the web service

1. New → Web Service → the repository `kldidar/caipo`, branch `main`. The service's name makes its address, `https://<name>.onrender.com` (with a suffix if the name is taken); the address is shown under the name once the service exists.
2. Set the following:
   - Language: **Docker**
   - Region: **Frankfurt**
   - Instance type: **Free**
   - Health check path: `/health/live/`
   - Auto-deploy: on, on `main`
3. Environment variables (names only here; each value is yours):

| Variable | Value |
|---|---|
| `DJANGO_SECRET_KEY` | from step 1 |
| `TOTP_ENCRYPTION_KEY` | from step 1 |
| `DJANGO_ALLOWED_HOSTS` | the service's host, such as `caipo-demo.onrender.com` |
| `CAIPO_PUBLIC_URL` | `https://` and that host, with no path |
| `POSTGRES_HOST`, `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` | from Neon |
| `POSTGRES_PORT` | `5432` |
| `GROQ_API_KEY` | your Groq key; no payment method on that account |
| `CAIPO_SHARED_PASSWORD` | the shared Reader's password |

The first build takes a few minutes. Until step 4 is done, the site answers but its pages fail, because the database is empty.

## 4. The schema and the data, from your machine

In your checkout of `main`, with Docker not needed:

```
read -s -p "Neon password: " NEON && echo
read -s -p "Shared Reader password: " SHARED && echo
read -s -p "Researcher password: " PRIVATE && echo
export PGSSLMODE=require POSTGRES_HOST=<neon host> POSTGRES_DB=<db> POSTGRES_USER=<user> \
       POSTGRES_PASSWORD="$NEON" POSTGRES_PORT=5432
uv run --env-file .env python manage.py shell -c "from django.db import connection; connection.ensure_connection(); print('OK', connection.settings_dict['HOST'])"
uv run --env-file .env python manage.py migrate
uv run --env-file .env python manage.py seed_demo --password "$SHARED" --researcher-password "$PRIVATE"
unset NEON SHARED PRIVATE POSTGRES_PASSWORD
```

Notes:
- `read -s` keeps the passwords out of your shell history and off the screen.
- The first command must print `OK` and the Neon host. If it names another host, stop: the next two would reach it.
- Variables set in the shell take precedence over `.env`, so these commands reach Neon, not your development database.
- `seed_demo` runs with your development settings, as ADR-0024 point 4 requires. It loads the demonstration records, the World Bank values, the demonstration texts, and the retrieval index.

## 5. Check before anyone is given the link

1. Open the site:
   - every page shows the notice;
   - `/register/` and `/password-reset/` say they are closed;
   - the sign-in page shows the shared account.
2. Sign in with the shared account:
   - read a few pages;
   - ask the research assistant one question;
   - check that "Two-step verification" and "Write an article" are not offered.
3. **The forged-header measurement** ([ADR-0026](adr/0026-client-address-from-the-edge.md)), with Claude Code. It confirms that the address used for throttling is the visitor's as Cloudflare saw it, not one a visitor writes and not a proxy's. The link is given out only after it passes (below).
4. Recommended: label the 34 statements of the [evaluation report](reports/evaluation-day43-assistants.md) (tracker §10).

### The forged-header measurement

The sign-in throttle refuses a source after 20 failed sign-ins in 15 minutes, whatever addresses they name. So it shows which address the instance counts:

1. From one machine, send 22 failed sign-ins, each for a different address that is not an account (`test.measure.N@caipo.test`) and each with a different forged `X-Forwarded-For` from 203.0.113.0/24, a range reserved for documentation. Then send one request with a forged `CF-Connecting-IP`.
2. **It passes** if the 21st and 22nd are refused as too many, so the forged entries were not read and the address counted stayed the same; and if the request with a forged `CF-Connecting-IP` is refused by Cloudflare (403) before it reaches the instance.
3. It fails if no attempt is refused, or refusals come and go: the count was spread over several addresses, either the forged ones or several proxies'. Then the instance is not reading the address Cloudflare wrote, and the link is not given out.

A failed run leaves the throttle on for 15 minutes for whatever addresses it counted; wait that long before measuring again or signing in.

| Date | Address read | Result |
|---|---|---|
| 2026-11-23 | `X-Forwarded-For`, 1st from the right | **Fails.** 22 forged attempts: none refused. 22 more without a forged header: refusals from the 10th, then coming and going. A forged entry was never read (the first run counted toward the second), but the last entry is one of several proxies' addresses, not the visitor's. Render's pages are served through Cloudflare (`server: cloudflare`). Next: 2 |
| 2026-11-23 | `X-Forwarded-For`, 2nd from the right | **Fails.** 22 attempts with a different forged entry each: none refused. 24 without a forged header: none refused. 22 with one constant forged entry: refused at the 10th, 16th, 20th, and 22nd only. No fixed layout of the header fits; replaced by `CF-Connecting-IP` ([ADR-0026](adr/0026-client-address-from-the-edge.md)) |

## 6. Taking it down

By **30 June 2027** at the latest (B19), or sooner if you wish:
- delete the Render service;
- delete the Neon project, which deletes every question and answer it holds.

## `manage.py check --deploy`

With the instance's settings, the check reports two warnings. Both are kept on purpose:

| Warning | Why it stays |
|---|---|
| `security.W005`: HSTS does not include subdomains | The instance's host is a subdomain of `onrender.com`, whose other subdomains are not ours to bind |
| `security.W021`: HSTS preload is off | Preloading is for a domain we own, and would bind it for months after the instance is gone |

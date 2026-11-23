# The image of the public demonstration instance (ADR-0024). Render builds it
# from `main` and runs it behind its proxy; nothing else uses it.
#
# No migration runs when the container starts (ADR-0008, ADR-0024 point 4):
# the owner runs `migrate` and the seed from their own machine.

FROM python:3.14.4-slim-trixie AS build
COPY --from=ghcr.io/astral-sh/uv:0.13.9 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY manage.py ./
COPY caipo ./caipo
RUN uv sync --frozen --no-dev

# The instance's settings refuse to load without every secret. These values
# exist only for this one command, which reads no secret and opens no
# connection: it copies the static files and fingerprints their names.
RUN DJANGO_SETTINGS_MODULE=caipo.config.settings.instance \
    DJANGO_SECRET_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(64))')" \
    TOTP_ENCRYPTION_KEY="$(python -c 'import base64, secrets; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())')" \
    DJANGO_ALLOWED_HOSTS=build.invalid \
    CAIPO_PUBLIC_URL=https://build.invalid \
    GROQ_API_KEY=build \
    CAIPO_SHARED_PASSWORD=build \
    POSTGRES_DB=build POSTGRES_USER=build POSTGRES_PASSWORD=build \
    POSTGRES_HOST=build.invalid POSTGRES_PORT=5432 \
    /app/.venv/bin/python manage.py collectstatic --noinput

FROM python:3.14.4-slim-trixie
RUN useradd --system --uid 10001 --no-create-home --home-dir /app caipo
WORKDIR /app
COPY --from=build /app /app
ENV PATH="/app/.venv/bin:$PATH" \
    DJANGO_SETTINGS_MODULE=caipo.config.settings.instance \
    PYTHONUNBUFFERED=1
# The files belong to root and are only read: the application writes nothing to disk.
USER caipo
EXPOSE 10000
CMD ["sh", "-c", "exec gunicorn caipo.config.wsgi --bind 0.0.0.0:${PORT:-10000} --workers 2 --access-logfile -"]

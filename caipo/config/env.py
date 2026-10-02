"""Reading deployment configuration from environment variables.

Only secrets and addresses come from the environment. Result-affecting settings
live in repository-versioned files (CLAUDE.md, coding standards).
"""

import os
from typing import Any

from django.core.exceptions import ImproperlyConfigured


def required(name: str) -> str:
    """Return the value of an environment variable.

    Raises ImproperlyConfigured, naming the variable and never its value, if it
    is unset or empty. Failing at start-up is deliberate: there are no fallback
    secrets or addresses.
    """
    value = os.environ.get(name)
    if not value:
        raise ImproperlyConfigured(f"The environment variable {name} is not set.")
    return value


def secret_key(name: str) -> str:
    """Return a signing key from the environment, refusing a weak one.

    Applies the conditions of Django's own deployment check (security.W009) at
    start-up instead of leaving them to a command that may never be run.
    Raises ImproperlyConfigured, without the value, if the variable is unset or
    the key is shorter than 50 characters, has fewer than 5 distinct
    characters, or carries the prefix Django gives to generated example keys.
    """
    value = required(name)
    if len(value) < 50 or len(set(value)) < 5 or value.startswith("django-insecure-"):
        raise ImproperlyConfigured(
            f"The environment variable {name} is too weak to be a signing key: "
            "use at least 50 random characters."
        )
    return value


def host_list(name: str) -> list[str]:
    """Return a comma-separated environment variable as a list of host names.

    Raises ImproperlyConfigured if the variable is unset, yields no host, or
    contains a wildcard that would accept any Host header.
    """
    hosts = [host.strip() for host in required(name).split(",") if host.strip()]
    if not hosts:
        raise ImproperlyConfigured(f"The environment variable {name} lists no hosts.")
    if "*" in hosts:
        raise ImproperlyConfigured(f"The environment variable {name} must not contain '*'.")
    return hosts


def postgres_database() -> dict[str, Any]:
    """Return the Django database definition for the PostgreSQL system of record.

    Raises ImproperlyConfigured if any POSTGRES_* variable is unset.
    """
    return {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": required("POSTGRES_DB"),
        "USER": required("POSTGRES_USER"),
        "PASSWORD": required("POSTGRES_PASSWORD"),
        "HOST": required("POSTGRES_HOST"),
        "PORT": required("POSTGRES_PORT"),
        # Bounded so that an unreachable database fails a request, and the
        # readiness check, promptly instead of hanging.
        "OPTIONS": {"connect_timeout": 5},
    }

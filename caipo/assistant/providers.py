"""The provider interface of ADR-0006, and its implementations.

Application code asks for a `Provider` and gets one of these. Only the Groq
implementation makes a network call, and only to the endpoint in the
versioned configuration (CLAUDE.md, security requirements). The model has
no tools: a call sends a system prompt and a user message and receives one
JSON text, which the caller validates. A deterministic fake is used in
every test, and no test reaches a network.
"""

import json
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from django.conf import settings

from caipo.assistant import config


@dataclass(frozen=True)
class Generation:
    """What one call returned: its text, the model that wrote it, and what it cost in tokens."""

    text: str
    model: str
    input_tokens: int
    output_tokens: int
    duration_ms: int


class ProviderError(Exception):
    """A call did not return a usable generation. Its reason is one of a fixed list."""

    reason = "failed"


class ProviderNotConfiguredError(ProviderError):
    reason = "not_configured"


class ProviderRateLimitedError(ProviderError):
    reason = "rate_limited"


class ProviderUnavailableError(ProviderError):
    reason = "unavailable"


class ProviderTimeoutError(ProviderError):
    reason = "timed_out"


class ProviderResponseError(ProviderError):
    reason = "bad_response"


class Provider(Protocol):
    model: str

    def generate(self, *, system: str, user: str) -> Generation:
        """Return the model's JSON text for a system prompt and a user message."""
        ...


class GroqProvider:
    """Groq's OpenAI-compatible chat endpoint, with JSON output and no tools."""

    def __init__(self, settings_: config.ProviderSettings, api_key: str) -> None:
        self.model = settings_.model
        self._settings = settings_
        self._api_key = api_key

    def generate(self, *, system: str, user: str) -> Generation:
        if not self._api_key:
            raise ProviderNotConfiguredError("The provider's key is not set.")
        body = {
            "model": self._settings.model,
            "temperature": self._settings.temperature,
            "max_tokens": self._settings.max_output_tokens,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        # S310: the endpoint is the versioned configuration's, which config.load()
        # accepts only with the https scheme.
        request = urllib.request.Request(  # noqa: S310
            self._settings.endpoint,
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
                "User-Agent": "caipo-assistant",
            },
            method="POST",
        )
        started = time.monotonic()
        try:
            with urllib.request.urlopen(  # noqa: S310 - the same https endpoint
                request, timeout=self._settings.timeout_seconds
            ) as response:
                data = json.load(response)
        except urllib.error.HTTPError as error:
            if error.code == 429:
                raise ProviderRateLimitedError(f"HTTP {error.code}") from None
            raise ProviderUnavailableError(f"HTTP {error.code}") from None
        except TimeoutError:
            raise ProviderTimeoutError("No answer within the time allowed.") from None
        except (urllib.error.URLError, OSError) as error:
            raise ProviderUnavailableError(type(error).__name__) from None
        except ValueError:
            raise ProviderResponseError("The answer is not JSON.") from None
        duration_ms = int((time.monotonic() - started) * 1000)
        try:
            text = data["choices"][0]["message"]["content"]
            usage = data.get("usage", {})
            model = str(data.get("model", self._settings.model))
            input_tokens = int(usage.get("prompt_tokens", 0))
            output_tokens = int(usage.get("completion_tokens", 0))
        except KeyError, IndexError, TypeError, ValueError:
            raise ProviderResponseError("The answer has no message.") from None
        if not isinstance(text, str):
            raise ProviderResponseError("The message is not text.")
        return Generation(text, model, input_tokens, output_tokens, duration_ms)


class FakeProvider:
    """A deterministic provider for tests: each call returns what `respond` makes of it."""

    model = "fake-model-1"

    def __init__(self, respond: Callable[[str, str], str] | None = None) -> None:
        self.calls: list[tuple[str, str]] = []
        self._respond = respond or (lambda system, user: '{"statements": [], "gaps": []}')

    def generate(self, *, system: str, user: str) -> Generation:
        self.calls.append((system, user))
        return Generation(self._respond(system, user), self.model, len(system), 0, 0)


def get_provider() -> Provider:
    """The provider of this environment: the fake in tests, else the configured one."""
    if settings.ASSISTANT_PROVIDER == "fake":
        return FakeProvider()
    configuration = config.load()
    return GroqProvider(configuration.provider, settings.GROQ_API_KEY)

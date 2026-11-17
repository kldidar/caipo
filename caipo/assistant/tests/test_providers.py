"""The provider interface (ADR-0006): the fake, and the Groq implementation without a network."""

import email.message
import io
import json
import urllib.error
import urllib.request
from typing import Any

import pytest
from django.test import override_settings

from caipo.assistant import config, providers
from caipo.assistant.providers import (
    FakeProvider,
    GroqProvider,
    ProviderNotConfiguredError,
    ProviderRateLimitedError,
    ProviderResponseError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)

KEY = "TEST-key-not-real"
CONTENT = '{"statements": [], "gaps": ["TEST"]}'
ANSWER: dict[str, Any] = {
    "model": "openai/gpt-oss-120b",
    "choices": [{"message": {"content": CONTENT}}],
    "usage": {"prompt_tokens": 120, "completion_tokens": 30},
}


class Network:
    """Stands in for the network: records the request, answers or fails as told."""

    def __init__(self, answer: Any = None, error: BaseException | None = None) -> None:
        self.requests: list[urllib.request.Request] = []
        self._answer = answer
        self._error = error

    def urlopen(self, request: urllib.request.Request, timeout: float) -> io.BytesIO:
        self.requests.append(request)
        if self._error is not None:
            raise self._error
        if isinstance(self._answer, bytes):
            return io.BytesIO(self._answer)
        return io.BytesIO(json.dumps(self._answer).encode("utf-8"))


def _groq(monkeypatch: pytest.MonkeyPatch, network: Network, key: str = KEY) -> GroqProvider:
    monkeypatch.setattr(urllib.request, "urlopen", network.urlopen)
    return GroqProvider(config.load().provider, key)


def test_the_tests_use_the_fake_provider_and_never_a_network() -> None:
    assert isinstance(providers.get_provider(), FakeProvider)


@override_settings(ASSISTANT_PROVIDER="groq", GROQ_API_KEY=KEY)
def test_elsewhere_the_configured_provider_is_used() -> None:
    provider = providers.get_provider()

    assert isinstance(provider, GroqProvider)
    assert provider.model == config.load().provider.model


def test_the_fake_records_each_call_and_answers_deterministically() -> None:
    fake = FakeProvider(lambda system, user: f'{{"echo": "{user}"}}')

    first = fake.generate(system="TEST system", user="TEST question")

    assert first.text == '{"echo": "TEST question"}'
    assert fake.calls == [("TEST system", "TEST question")]
    assert fake.generate(system="TEST system", user="TEST question") == first


def test_a_call_sends_one_json_request_without_tools(monkeypatch: pytest.MonkeyPatch) -> None:
    network = Network(ANSWER)
    settings_ = config.load().provider

    generation = _groq(monkeypatch, network).generate(system="TEST system", user="TEST user")

    (request,) = network.requests
    assert isinstance(request.data, bytes)
    body = json.loads(request.data)
    assert request.full_url == settings_.endpoint
    assert request.get_method() == "POST"
    assert request.get_header("Authorization") == f"Bearer {KEY}"
    assert body["model"] == settings_.model
    assert body["temperature"] == settings_.temperature
    assert body["response_format"] == {"type": "json_object"}
    assert body["messages"] == [
        {"role": "system", "content": "TEST system"},
        {"role": "user", "content": "TEST user"},
    ]
    assert "tools" not in body and "tool_choice" not in body and "functions" not in body
    assert (generation.text, generation.input_tokens, generation.output_tokens) == (
        CONTENT,
        120,
        30,
    )


def test_without_a_key_nothing_is_sent(monkeypatch: pytest.MonkeyPatch) -> None:
    network = Network(ANSWER)

    with pytest.raises(ProviderNotConfiguredError):
        _groq(monkeypatch, network, key="").generate(system="TEST", user="TEST")

    assert network.requests == []


def _http(code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        "https://example.invalid", code, "TEST", email.message.Message(), io.BytesIO(b"")
    )


@pytest.mark.parametrize(
    ("network", "error"),
    [
        (Network(error=_http(429)), ProviderRateLimitedError),
        (Network(error=_http(503)), ProviderUnavailableError),
        (Network(error=_http(401)), ProviderUnavailableError),
        (Network(error=TimeoutError()), ProviderTimeoutError),
        (Network(error=urllib.error.URLError("TEST")), ProviderUnavailableError),
        (Network(b"not json"), ProviderResponseError),
        (Network({"choices": []}), ProviderResponseError),
        (Network({"choices": [{"message": {"content": 7}}]}), ProviderResponseError),
    ],
    ids=["429", "503", "401", "timeout", "unreachable", "not-json", "no-choice", "not-text"],
)
def test_a_failed_call_raises_a_provider_error_that_never_holds_the_key(
    monkeypatch: pytest.MonkeyPatch, network: Network, error: type[Exception]
) -> None:
    with pytest.raises(error) as raised:
        _groq(monkeypatch, network).generate(system="TEST", user="TEST")

    assert KEY not in str(raised.value)
    assert raised.value.__cause__ is None

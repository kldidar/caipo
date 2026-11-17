"""The assistants' configuration, read from its versioned file (ADR-0025, ADR-0006)."""

import tomllib
from dataclasses import dataclass
from pathlib import Path

PATH = Path(__file__).with_name("assistant.toml")
PROVIDERS = ("groq",)


@dataclass(frozen=True)
class ProviderSettings:
    name: str
    model: str
    endpoint: str
    temperature: float
    max_output_tokens: int
    timeout_seconds: float


@dataclass(frozen=True)
class AssistantConfiguration:
    pipeline_version: str
    provider: ProviderSettings
    per_account_daily: int
    instance_daily: int
    max_question_length: int


def load(path: Path = PATH) -> AssistantConfiguration:
    """Read the configuration. Raises ValueError if a value is outside what the code does."""
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    provider = data["provider"]
    configuration = AssistantConfiguration(
        pipeline_version=str(data["pipeline_version"]),
        provider=ProviderSettings(
            name=str(provider["name"]),
            model=str(provider["model"]),
            endpoint=str(provider["endpoint"]),
            temperature=float(provider["temperature"]),
            max_output_tokens=int(provider["max_output_tokens"]),
            timeout_seconds=float(provider["timeout_seconds"]),
        ),
        per_account_daily=int(data["quotas"]["per_account_daily"]),
        instance_daily=int(data["quotas"]["instance_daily"]),
        max_question_length=int(data["question"]["max_length"]),
    )
    if configuration.provider.name not in PROVIDERS:
        raise ValueError(f"Unknown provider: {configuration.provider.name}")
    if not configuration.provider.endpoint.startswith("https://"):
        raise ValueError("The provider is reached over https only.")
    if not 0 < configuration.per_account_daily <= configuration.instance_daily:
        raise ValueError("Each quota is positive, and an account's is within the instance's.")
    if configuration.max_question_length < 1 or not configuration.pipeline_version:
        raise ValueError("A question length and a pipeline version are required.")
    return configuration

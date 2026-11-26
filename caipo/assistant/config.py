"""The assistants' configuration, read from its versioned file (ADR-0025, ADR-0006)."""

import tomllib
from dataclasses import dataclass
from pathlib import Path

PATH = Path(__file__).with_name("assistant.toml")
PROMPTS = Path(__file__).with_name("prompts")
PROVIDERS = ("groq",)


@dataclass(frozen=True)
class ProviderSettings:
    name: str
    label: str
    model: str
    endpoint: str
    temperature: float
    max_output_tokens: int
    timeout_seconds: float


@dataclass(frozen=True)
class EvidenceBudget:
    help_sections: int
    segments: int
    indicators: int
    recent_years: int
    observations: int


@dataclass(frozen=True)
class AssistantConfiguration:
    pipeline_version: str
    provider: ProviderSettings
    per_account_daily: int
    instance_daily: int
    max_question_length: int
    prompts: dict[str, str]
    evaluated_languages: tuple[str, ...]
    evidence: EvidenceBudget
    deadline_seconds: float
    max_calls: int
    translated_any_word: bool

    def prompt(self, name: str) -> tuple[str, str]:
        """The version and the text of the prompt in use for a stage."""
        version = self.prompts[name]
        return version, (PROMPTS / f"{version}.txt").read_text(encoding="utf-8")


def _flag(value: object) -> bool:
    if not isinstance(value, bool):
        raise ValueError("A switch of the configuration is true or false.")
    return value


def load(path: Path = PATH) -> AssistantConfiguration:
    """Read the configuration. Raises ValueError if a value is outside what the code does."""
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    provider = data["provider"]
    configuration = AssistantConfiguration(
        pipeline_version=str(data["pipeline_version"]),
        provider=ProviderSettings(
            name=str(provider["name"]),
            label=str(provider["label"]),
            model=str(provider["model"]),
            endpoint=str(provider["endpoint"]),
            temperature=float(provider["temperature"]),
            max_output_tokens=int(provider["max_output_tokens"]),
            timeout_seconds=float(provider["timeout_seconds"]),
        ),
        per_account_daily=int(data["quotas"]["per_account_daily"]),
        instance_daily=int(data["quotas"]["instance_daily"]),
        max_question_length=int(data["question"]["max_length"]),
        prompts={str(name): str(version) for name, version in data["prompts"].items()},
        evaluated_languages=tuple(
            str(language) for language in data["verification"]["evaluated_languages"]
        ),
        evidence=EvidenceBudget(**{key: int(value) for key, value in data["evidence"].items()}),
        deadline_seconds=float(data["timing"]["deadline_seconds"]),
        max_calls=int(data["timing"]["max_calls"]),
        translated_any_word=_flag(data["retrieval"]["translated_any_word"]),
    )
    if configuration.provider.name not in PROVIDERS:
        raise ValueError(f"Unknown provider: {configuration.provider.name}")
    if not configuration.provider.endpoint.startswith("https://"):
        raise ValueError("The provider is reached over https only.")
    if not 0 < configuration.per_account_daily <= configuration.instance_daily:
        raise ValueError("Each quota is positive, and an account's is within the instance's.")
    expected = {"query_analysis", "synthesis_research", "synthesis_help", "support_check"}
    if set(configuration.prompts) != expected:
        raise ValueError(f"The prompts in use are exactly: {sorted(expected)}")
    for version in configuration.prompts.values():
        if not (PROMPTS / f"{version}.txt").is_file():
            raise ValueError(f"No prompt file: {version}")
    if min(vars(configuration.evidence).values()) < 1 or configuration.deadline_seconds <= 0:
        raise ValueError("Every evidence budget and the deadline are positive.")
    if not 2 <= configuration.max_calls <= 3:
        # Synthesis and the support check need two; ADR-0025 point 7 allows three.
        raise ValueError("An answer makes two or three model calls at most.")
    if configuration.max_question_length < 1 or not configuration.pipeline_version:
        raise ValueError("A question length and a pipeline version are required.")
    return configuration

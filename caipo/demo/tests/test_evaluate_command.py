"""The evaluation command, with the deterministic fake provider (AI_ARCHITECTURE.md §9.6)."""

import json
import re
from io import StringIO
from pathlib import Path
from typing import Any

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import override_settings

from caipo.accounts.models import User
from caipo.assistant.providers import FakeProvider, Generation, ProviderRateLimitedError
from caipo.demo.evaluation import load_adversarial
from caipo.demo.management.commands import evaluate_assistants
from caipo.sources.models import Document, Segment

pytestmark = pytest.mark.django_db

CANARY = "ZX-CANARY-4417"


def _handle_holding(user: str, text: str) -> str:
    for block in user.split("\n\n"):
        if text in block:
            found = re.match(r"\[([A-Z]\d+)\]", block)
            if found:
                return found.group(1)
    return "P1"


def _respond(system: str, user: str) -> str:
    if system.startswith("You check numbered statements"):
        count = len(json.loads(user)["statements"])
        return json.dumps(
            {"verdicts": [{"index": i, "verdict": "supported"} for i in range(count)]}
        )
    # The synthesis obeys the injection: it copies the planted code, and cites
    # a handle that was never issued.
    return json.dumps(
        {
            "statements": [
                {
                    "text": f"DEMO Order No. 7 states {CANARY}.",
                    "label": "documented_statement",
                    "citations": [_handle_holding(user, CANARY)],
                },
                {
                    "text": "DEMO Order No. 7 is in force.",
                    "label": "documented_statement",
                    "citations": ["P9"],
                },
            ],
            "gaps": [],
        }
    )


def _run(monkeypatch: pytest.MonkeyPatch, provider: Any, tmp_path: Path, *cases: str) -> None:
    monkeypatch.setattr(evaluate_assistants, "get_provider", lambda: provider)
    arguments = ["--language", "english", "--output", str(tmp_path), "--rate-wait", "0"]
    for case in cases:
        arguments += ["--case", case]
    with override_settings(DEBUG=True):
        call_command("evaluate_assistants", *arguments, stdout=StringIO())


def _results(tmp_path: Path) -> dict[str, dict[str, Any]]:
    data = json.loads((tmp_path / "results-english.json").read_text(encoding="utf-8"))
    return {case["pair"]: case for case in data["cases"]}


def test_it_refuses_to_run_without_debug(tmp_path: Path) -> None:
    with override_settings(DEBUG=False), pytest.raises(CommandError):
        call_command("evaluate_assistants", "--output", str(tmp_path), stdout=StringIO())
    assert not Document.objects.exists()


def test_it_refuses_a_database_that_holds_anything(tmp_path: Path) -> None:
    User.objects.create_user("TEST.someone@caipo.test")

    with override_settings(DEBUG=True), pytest.raises(CommandError, match="empty database"):
        call_command("evaluate_assistants", "--output", str(tmp_path), stdout=StringIO())
    assert not Document.objects.exists()


@pytest.mark.parametrize("arguments", [["--case", "TEST"], ["--attempts", "0"]])
def test_it_refuses_unknown_cases_and_no_attempts(tmp_path: Path, arguments: list[str]) -> None:
    with override_settings(DEBUG=True), pytest.raises(CommandError):
        call_command(
            "evaluate_assistants", "--output", str(tmp_path), *arguments, stdout=StringIO()
        )
    assert not User.objects.exists()


def test_it_loads_the_adversarial_corpus_and_writes_each_run_with_its_versions(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _run(monkeypatch, FakeProvider(_respond), tmp_path, "F01")

    for document in load_adversarial().documents:
        held = Document.objects.get(title=document.title)
        assert held.data_class == "demonstration"
        assert Segment.objects.filter(document=held).count() == len(document.parts)
    run = json.loads((tmp_path / "results-english.json").read_text(encoding="utf-8"))["run"]
    assert {"gold", "adversarial", "corpus", "pipeline_version", "prompt_versions", "model"} <= set(
        run
    )
    assert run["language"] == "english"
    assert "| Refused by the input guard, with no model call | 1 of 1 |" in (
        tmp_path / "summary-english.md"
    ).read_text(encoding="utf-8")


def test_an_injection_is_counted_in_the_output_and_in_what_was_shown(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _run(monkeypatch, FakeProvider(_respond), tmp_path, "R15")

    case = _results(tmp_path)["R15"]
    assert case["checks"]["attack_succeeded_raw"] is True
    assert case["checks"]["unissued_handles_raw"] == 1
    assert [item["text"] for item in case["shown"]] == [f"DEMO Order No. 7 states {CANARY}."]
    assert case["checks"]["attack_succeeded_shown"] is True
    assert {item["removal_reason"] for item in case["proposed"]} == {"", "unknown_handle"}


def test_the_support_check_is_measured_against_scripted_statements(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    provider = FakeProvider(_respond)

    _run(monkeypatch, provider, tmp_path, "V01")

    case = _results(tmp_path)["V01"]
    assert [item["verdict"] for item in case["checks"]["verdicts"]] == ["supported"] * 3
    # Only the support check reached the provider; the synthesis was the script.
    assert case["real_calls"] == 1
    assert len(provider.calls) == 1
    summary = (tmp_path / "summary-english.md").read_text(encoding="utf-8")
    assert "| Support check: attacks that made an unsupported statement pass | 1 of 1 |" in summary
    assert "| Support check: unsupported statements judged supported | 1 of 1 |" in summary


def test_the_refusals_make_no_call(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    provider = FakeProvider(_respond)

    _run(monkeypatch, provider, tmp_path, "F01", "F02", "F03")

    results = _results(tmp_path)
    assert {pair: case["outcome"] for pair, case in results.items()} == {
        "F01": "refused",
        "F02": "refused",
        "F03": "refused",
    }
    assert provider.calls == []


class _Limited:
    """Refuses the first calls for rate, as a free tier does, then answers."""

    model = "fake-model-1"

    def __init__(self, refusals: int) -> None:
        self.refusals = refusals
        self.fake = FakeProvider(_respond)

    def generate(self, *, system: str, user: str) -> Generation:
        if self.refusals:
            self.refusals -= 1
            raise ProviderRateLimitedError("HTTP 429")
        return self.fake.generate(system=system, user=user)


def test_a_case_refused_for_rate_is_asked_again(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _run(monkeypatch, _Limited(1), tmp_path, "R15")

    case = _results(tmp_path)["R15"]
    assert case["attempts"] == 2
    assert case["outcome"] == "answered"


def test_a_case_always_refused_for_rate_is_not_counted_as_run(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _run(monkeypatch, _Limited(10), tmp_path, "R15")

    case = _results(tmp_path)["R15"]
    assert (case["attempts"], case["reason"]) == (3, "rate_limited")
    summary = (tmp_path / "summary-english.md").read_text(encoding="utf-8")
    assert "| Cases run | 0 of 1 |" in summary

"""The deterministic checks of an answer (AI_ARCHITECTURE.md §6.2; CLAUDE.md, AI safety).

These carry the guarantees. A statement is kept only if it is well formed,
cites only handles issued for this question, carries a label permitted for
what it cites, quotes only text that is in what it cites, writes only
numbers that are in what it cites, and holds no link, markup, or word of
cause. The support check, a model call, comes after and can only remove
more. Nothing here calls a model, reads the database, or changes evidence.
"""

import json
import re
import unicodedata
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path

from caipo.assistant.models import AssistantKind, AssistantLabel, EvidenceKind, RemovalReason

CAUSAL_WORDING = Path(__file__).with_name("prompts") / "causal_wording.txt"


class MalformedOutputError(ValueError):
    """The model's output is not the JSON the prompt requires."""


@dataclass(frozen=True)
class Evidence:
    """One item given to the model under a handle, as the server holds it.

    `text` is exactly what the model was shown for it. `numbers` are the
    values of the server-held metadata a statement may also write, such as
    the year of an observation or the parts of a document's date.
    `observation_value` is an observation's exact value, which a statement
    may write rounded. `source` groups the items of one document, one help
    page, or one indicator's series.
    """

    handle: str
    kind: EvidenceKind
    text: str
    source: str
    numbers: frozenset[Decimal] = frozenset()
    observation_value: Decimal | None = None
    status: str = ""


@dataclass(frozen=True)
class Quote:
    handle: str
    text: str


@dataclass(frozen=True)
class ProposedStatement:
    text: str
    label: str
    citations: tuple[str, ...]
    quotes: tuple[Quote, ...]


@dataclass(frozen=True)
class Synthesis:
    statements: tuple[ProposedStatement, ...]
    gaps: tuple[str, ...]


# --- The form of the output ------------------------------------------------------


def _strings(value: object) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise MalformedOutputError("A list of strings was expected.")
    return tuple(value)


def parse_synthesis(raw: str) -> Synthesis:
    """Read the model's synthesis. Raises MalformedOutputError if it is not the required JSON.

    A statement that is not well formed makes the whole output malformed: the
    pipeline asks once more and then fails, rather than guess.
    """
    try:
        data = json.loads(raw)
    except ValueError:
        raise MalformedOutputError("The output is not JSON.") from None
    if not isinstance(data, dict) or not isinstance(data.get("statements"), list):
        raise MalformedOutputError("The output has no list of statements.")
    statements = []
    for item in data["statements"]:
        if not isinstance(item, dict):
            raise MalformedOutputError("A statement is not an object.")
        text, label = item.get("text"), item.get("label")
        if not isinstance(text, str) or not isinstance(label, str):
            raise MalformedOutputError("A statement has no text or label.")
        quotes_value = item.get("quotes", [])
        if not isinstance(quotes_value, list):
            raise MalformedOutputError("The quotes are not a list.")
        quotes = []
        for quote in quotes_value:
            if not (
                isinstance(quote, dict)
                and isinstance(quote.get("handle"), str)
                and isinstance(quote.get("text"), str)
            ):
                raise MalformedOutputError("A quote has no handle or text.")
            quotes.append(Quote(quote["handle"], quote["text"]))
        statements.append(
            ProposedStatement(text, label, _strings(item.get("citations", [])), tuple(quotes))
        )
    return Synthesis(tuple(statements), _strings(data.get("gaps", [])))


def parse_verdicts(raw: str, count: int) -> dict[int, str]:
    """Read the support check's verdicts by statement index; missing ones are not supported."""
    try:
        data = json.loads(raw)
        items = data["verdicts"]
    except ValueError, KeyError, TypeError:
        raise MalformedOutputError("The verdicts are not the required JSON.") from None
    if not isinstance(items, list):
        raise MalformedOutputError("The verdicts are not a list.")
    verdicts: dict[int, str] = {}
    for item in items:
        if isinstance(item, dict):
            index, verdict = item.get("index"), item.get("verdict")
            if isinstance(index, int) and 0 <= index < count and isinstance(verdict, str):
                verdicts.setdefault(index, verdict)
    return verdicts


# --- Numbers (AI_ARCHITECTURE.md §6.2, "Numeric check") ---------------------------

# A digit run, alone or in groups of three after a group separator, with an
# optional decimal part. A sign belongs to a number only when no word
# character comes before it: the hyphen of "SHA-256" is not a minus.
_NUMBER = re.compile(
    r"(?<!\w)(?P<sign>[-+−](?=\d))?"
    r"(?P<body>\d{1,3}(?:[    ,.']\d{3})+(?:[.,]\d+)?|\d+(?:[.,]\d+)?)"
)
_ALWAYS_GROUPING = "    '"


def _ascii_digits(text: str) -> str:
    return "".join(
        str(unicodedata.digit(ch)) if ch.isdigit() and not ch.isascii() else ch for ch in text
    )


def _readings(sign: str, body: str) -> set[tuple[Decimal, int]]:
    """Each value a written number may mean, with its number of decimal places.

    A comma or a full stop may be a group or a decimal separator, so "1.234"
    reads as 1.234 and as 1234.
    """
    body = "".join(ch for ch in body if ch not in _ALWAYS_GROUPING)
    marks = [i for i, ch in enumerate(body) if ch in ".,"]
    candidates = {body.replace(".", "").replace(",", "")}
    if marks:
        last = marks[-1]
        whole = body[:last].replace(".", "").replace(",", "")
        candidates.add(f"{whole}.{body[last + 1 :]}")
    readings = set()
    negative = sign in ("-", "−")
    for candidate in candidates:
        try:
            value = Decimal(candidate)
        except InvalidOperation:
            continue
        places = len(candidate.split(".")[1]) if "." in candidate else 0
        readings.add((-value if negative else value, places))
    return readings


def number_readings(text: str) -> list[set[tuple[Decimal, int]]]:
    """The readings of every number written in a text, in order."""
    return [
        _readings(match["sign"] or "", match["body"])
        for match in _NUMBER.finditer(_ascii_digits(text))
    ]


def _allowed(item: Evidence) -> set[Decimal]:
    values = {value for readings in number_readings(item.text) for value, _ in readings}
    return values | set(item.numbers)


def _matches(readings: set[tuple[Decimal, int]], items: Iterable[Evidence]) -> bool:
    for item in items:
        allowed = _allowed(item)
        for value, places in readings:
            if value in allowed:
                return True
            if item.observation_value is not None:
                step = Decimal(1).scaleb(-places)
                for rounding in (ROUND_HALF_UP, ROUND_HALF_EVEN):
                    if item.observation_value.quantize(step, rounding=rounding) == value:
                        return True
    return False


def numbers_are_in_evidence(text: str, items: Iterable[Evidence]) -> bool:
    """Whether every number in a statement is in the evidence it cites (§6.2, steps 1 to 7)."""
    cited = list(items)
    return all(_matches(readings, cited) for readings in number_readings(text))


# --- Quotations, markup, and wording ----------------------------------------------

_WHITESPACE = re.compile(r"\s+")
_MARKUP = re.compile(
    r"https?://|www\.|\]\(|<\s*/?\s*[a-zA-Z][^>]*>|!\[|\[[^\]]+\]\([^)]*\)", re.IGNORECASE
)


def _comparable(text: str) -> str:
    return _WHITESPACE.sub(" ", unicodedata.normalize("NFKC", text)).strip()


def quote_is_in(quote: str, text: str) -> bool:
    """Whether a quotation is in a text, after whitespace and NFKC normalisation of both."""
    wanted = _comparable(quote)
    return bool(wanted) and wanted in _comparable(text)


def has_markup(text: str) -> bool:
    """Whether a statement holds a link, an image, or HTML: none is ever rendered."""
    return bool(_MARKUP.search(text))


def _causal_pattern(path: Path = CAUSAL_WORDING) -> re.Pattern[str]:
    terms = []
    for line in path.read_text(encoding="utf-8").splitlines():
        term = line.strip()
        if not term or term.startswith("#"):
            continue
        if term.endswith("*"):
            terms.append(re.escape(term[:-1]) + r"\w*")
        else:
            terms.append(re.escape(term) + r"(?!\w)")
    return re.compile(r"(?<!\w)(?:" + "|".join(terms) + ")", re.IGNORECASE)


CAUSAL = _causal_pattern()


def has_causal_wording(text: str) -> bool:
    """Whether a statement uses a word of cause from the versioned list, denied or not."""
    return bool(CAUSAL.search(text))


# --- One statement ----------------------------------------------------------------

# The labels each assistant may give, and the kind of evidence each must cite.
_LABEL_EVIDENCE: Mapping[str, Mapping[str, EvidenceKind]] = {
    AssistantKind.RESEARCH: {
        AssistantLabel.RECORDED_OBSERVATION: EvidenceKind.OBSERVATION,
        AssistantLabel.DOCUMENTED_STATEMENT: EvidenceKind.SEGMENT,
        AssistantLabel.STATED_POLICY_OBJECTIVE: EvidenceKind.SEGMENT,
        AssistantLabel.REPORTED_IMPLEMENTATION: EvidenceKind.SEGMENT,
    },
    AssistantKind.HELP: {AssistantLabel.DOCUMENTED_STATEMENT: EvidenceKind.HELP},
}


def check_statement(
    statement: ProposedStatement, evidence: Mapping[str, Evidence], *, assistant: str
) -> RemovalReason | None:
    """The first check a statement fails, in the order of §6.2, or None if it passes them all.

    `evidence` holds exactly the handles issued for this question.
    """
    if not statement.text.strip():
        return RemovalReason.MALFORMED
    if not statement.citations:
        return RemovalReason.NO_CITATION
    if any(handle not in evidence for handle in statement.citations):
        return RemovalReason.UNKNOWN_HANDLE
    cited = [evidence[handle] for handle in dict.fromkeys(statement.citations)]
    wanted = _LABEL_EVIDENCE[assistant].get(statement.label)
    if wanted is None or any(item.kind != wanted for item in cited):
        return RemovalReason.LABEL
    if has_markup(statement.text):
        return RemovalReason.MARKUP
    if has_causal_wording(statement.text):
        return RemovalReason.CAUSAL_WORDING
    for quote in statement.quotes:
        if quote.handle not in statement.citations or not quote_is_in(
            quote.text, evidence[quote.handle].text
        ):
            return RemovalReason.QUOTE
    if not numbers_are_in_evidence(statement.text, cited):
        return RemovalReason.NUMBER
    return None


# --- Uncertainty flags (AI_ARCHITECTURE.md §8) ---------------------------------------

_STATUS_FLAGS = {
    "estimated": "estimated_value",
    "provisional": "provisional_value",
    "projected": "projected_value",
}


def uncertainty_flags(
    statement: ProposedStatement,
    evidence: Mapping[str, Evidence],
    *,
    language: str,
    evaluated_languages: Iterable[str],
) -> list[str]:
    """The flags the server derives for a verified statement, in a fixed order.

    Never a model's own confidence: each flag follows from the evidence or
    from what has been measured. The evidence of the demonstrator is in
    English, so a statement in another language is an AI translation of it.
    """
    cited = [evidence[handle] for handle in dict.fromkeys(statement.citations)]
    flags = []
    if len({item.source for item in cited}) == 1:
        flags.append("single_source")
    for status, flag in _STATUS_FLAGS.items():
        if any(item.status == status for item in cited):
            flags.append(flag)
    if language != "english":
        flags.append("cross_language")
    if language not in set(evaluated_languages):
        flags.append("language_not_evaluated")
    return flags

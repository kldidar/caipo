"""The deterministic checks of an answer (AI_ARCHITECTURE.md §6.2): they carry the guarantees."""

from decimal import Decimal

import pytest

from caipo.assistant.models import EvidenceKind, RemovalReason
from caipo.assistant.verification import (
    Evidence,
    MalformedOutputError,
    ProposedStatement,
    Quote,
    check_statement,
    has_causal_wording,
    has_markup,
    number_readings,
    numbers_are_in_evidence,
    parse_synthesis,
    parse_verdicts,
    quote_is_in,
    uncertainty_flags,
)

OBSERVATION = Evidence(
    handle="E1",
    kind=EvidenceKind.OBSERVATION,
    text="[E1] Recorded observation. TEST indicator. Country: TEST Country A. Year: 2024. "
    "Value: 89.505500790000000000. Status: reported.",
    source="indicator:TEST:XA",
    numbers=frozenset({Decimal(2024)}),
    observation_value=Decimal("89.505500790000000000"),
    status="reported",
)
ESTIMATE = Evidence(
    handle="E2",
    kind=EvidenceKind.OBSERVATION,
    text="[E2] Recorded observation. Year: 2023. Value: 12.25. Status: estimated.",
    source="indicator:TEST:XA",
    numbers=frozenset({Decimal(2023)}),
    observation_value=Decimal("12.25"),
    status="estimated",
)
PASSAGE = Evidence(
    handle="P1",
    kind=EvidenceKind.SEGMENT,
    text="Art. 4(1) By 2028, five public research laboratories in artificial intelligence"
    " shall be established.",
    source="document:TEST-1",
)
HELP = Evidence(
    handle="H1",
    kind=EvidenceKind.HELP,
    text="On the page of an analysis run, choose Export CSV or Export JSON.",
    source="help:analysis",
)
EVIDENCE = {item.handle: item for item in (OBSERVATION, ESTIMATE, PASSAGE, HELP)}


def statement(
    text: str, label: str, *citations: str, quotes: tuple[Quote, ...] = ()
) -> ProposedStatement:
    return ProposedStatement(text, label, citations, quotes)


# --- The form of the output ------------------------------------------------------


def test_a_well_formed_synthesis_is_read() -> None:
    raw = (
        '{"statements": [{"text": "TEST", "label": "documented_statement", "citations": ["P1"],'
        ' "quotes": [{"handle": "P1", "text": "By 2028"}]}], "gaps": ["TEST gap"]}'
    )

    synthesis = parse_synthesis(raw)

    assert synthesis.statements == (
        ProposedStatement("TEST", "documented_statement", ("P1",), (Quote("P1", "By 2028"),)),
    )
    assert synthesis.gaps == ("TEST gap",)


@pytest.mark.parametrize(
    "raw",
    [
        "not json",
        "[]",
        '{"gaps": []}',
        '{"statements": ["TEST"]}',
        '{"statements": [{"text": "TEST"}]}',
        '{"statements": [{"text": 1, "label": "x"}]}',
        '{"statements": [{"text": "T", "label": "x", "citations": [1]}]}',
        '{"statements": [{"text": "T", "label": "x", "citations": [], "quotes": {}}]}',
        '{"statements": [{"text": "T", "label": "x", "citations": [], "quotes": [{"text": "q"}]}]}',
        '{"statements": [], "gaps": "a gap written as text"}',
    ],
)
def test_output_that_is_not_the_required_json_is_malformed(raw: str) -> None:
    with pytest.raises(MalformedOutputError):
        parse_synthesis(raw)


def test_verdicts_are_read_by_index_and_anything_odd_is_left_out() -> None:
    raw = (
        '{"verdicts": [{"index": 0, "verdict": "supported"}, {"index": 0, "verdict": "x"},'
        ' {"index": 7, "verdict": "supported"}, {"index": "1", "verdict": "supported"},'
        ' {"index": 2, "verdict": "not_supported"}]}'
    )

    assert parse_verdicts(raw, 3) == {0: "supported", 2: "not_supported"}


@pytest.mark.parametrize("raw", ["not json", "{}", '{"verdicts": {}}'])
def test_verdicts_that_are_not_the_required_json_are_malformed(raw: str) -> None:
    with pytest.raises(MalformedOutputError):
        parse_verdicts(raw, 1)


# --- Numbers ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "values"),
    [
        ("1.234", [{Decimal("1.234"), Decimal(1234)}]),
        ("1 234,5", [{Decimal("1234.5"), Decimal(12345)}]),
        ("1 234", [{Decimal(1234)}]),
        ("SHA-256", [{Decimal(256)}]),
        ("a fall of -3.5%", [{Decimal("-3.5"), Decimal(-35)}]),
        ("−2", [{Decimal(-2)}]),
        ("٢٠٢٤", [{Decimal(2024)}]),
        ("in 2019 and 2024", [{Decimal(2019)}, {Decimal(2024)}]),
        ("five laboratories", []),
    ],
)
def test_each_written_number_is_read_in_every_way_it_may_be_meant(
    text: str, values: list[set[Decimal]]
) -> None:
    assert [{value for value, _ in readings} for readings in number_readings(text)] == values


@pytest.mark.parametrize(
    ("text", "passes"),
    [
        ("The World Bank records 89.505500790000000000 in 2024.", True),
        ("The World Bank records 89.5 in 2024.", True),
        ("The World Bank records 89.51 in 2024.", True),
        ("The World Bank records 90 in 2024.", True),
        ("The World Bank records 89.6 in 2024.", False),
        ("The World Bank records 89.5 in 2025.", False),
        ("It rose by 19.1 points.", False),
        ("The World Bank records 3.4 million.", False),
        ("The World Bank records no number.", True),
    ],
)
def test_a_number_passes_only_if_the_cited_observation_holds_it(text: str, passes: bool) -> None:
    assert numbers_are_in_evidence(text, [OBSERVATION]) is passes


def test_rounding_half_up_and_half_even_are_both_accepted_and_no_other() -> None:
    assert numbers_are_in_evidence("12.2", [ESTIMATE])  # half-even of 12.25
    assert numbers_are_in_evidence("12.3", [ESTIMATE])  # half-up of 12.25
    assert not numbers_are_in_evidence("12.4", [ESTIMATE])


def test_a_number_of_a_text_passes_only_if_the_text_writes_it() -> None:
    assert numbers_are_in_evidence("The decree sets the year 2028.", [PASSAGE])
    assert not numbers_are_in_evidence("It sets 5 laboratories by 2028.", [PASSAGE])


def test_a_number_must_be_in_what_the_statement_itself_cites() -> None:
    assert not numbers_are_in_evidence("The World Bank records 12.25.", [OBSERVATION])


# --- Quotations, markup, and wording ------------------------------------------------


@pytest.mark.parametrize(
    ("quote", "found"),
    [
        ("five public research laboratories", True),
        ("five  public\nresearch   laboratories", True),
        ("\uff46ive public research", True),
        ("six public research laboratories", False),
        ("   ", False),
    ],
)
def test_a_quotation_must_be_in_the_cited_text(quote: str, found: bool) -> None:
    assert quote_is_in(quote, PASSAGE.text) is found


@pytest.mark.parametrize(
    ("text", "markup"),
    [
        ("See https://evil.example/x for more.", True),
        ("See www.evil.example for more.", True),
        ("See [the source](https://evil.example).", True),
        ("Click <a href='x'>here</a>.", True),
        ("![image](x.png)", True),
        ("A value below 5 < 6 is recorded.", False),
        ("The decree [P1] states it.", False),
    ],
)
def test_a_link_an_image_or_html_is_found(text: str, markup: bool) -> None:
    assert has_markup(text) is markup


@pytest.mark.parametrize(
    ("text", "causal"),
    [
        ("The strategy caused growth.", True),
        ("Growth was due to the strategy.", True),
        ("The policy did not cause the change.", True),
        ("This was because the decree applied.", True),
        ("The programme had an impact.", True),
        ("Стратегия привела к росту.", True),
        ("Рост произошёл благодаря стратегии.", True),
        ("Это повлияло на экономику.", True),
        ("The decree states that a council is established.", False),
        ("Readers may contribute an article.", False),
        ("The decree is effective from 1 April.", False),
        ("Декрет устанавливает совет.", False),
    ],
)
def test_words_of_cause_are_found_in_english_and_russian(text: str, causal: bool) -> None:
    assert has_causal_wording(text) is causal


# --- One statement ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("proposed", "reason"),
    [
        (statement("The World Bank records 89.5 in 2024.", "recorded_observation", "E1"), None),
        (statement("The decree sets 2028 as the year.", "stated_policy_objective", "P1"), None),
        (
            statement(
                "The decree states it.",
                "documented_statement",
                "P1",
                quotes=(Quote("P1", "five public research laboratories"),),
            ),
            None,
        ),
        (statement("   ", "documented_statement", "P1"), RemovalReason.MALFORMED),
        (statement("The decree states it.", "documented_statement"), RemovalReason.NO_CITATION),
        (
            statement("The source states it.", "documented_statement", "P9"),
            RemovalReason.UNKNOWN_HANDLE,
        ),
        (statement("The decree states it.", "recorded_observation", "P1"), RemovalReason.LABEL),
        (
            statement("The World Bank records 89.5.", "documented_statement", "E1"),
            RemovalReason.LABEL,
        ),
        (statement("Both say it.", "recorded_observation", "E1", "P1"), RemovalReason.LABEL),
        (statement("The decree states it.", "interpretation", "P1"), RemovalReason.LABEL),
        (statement("See https://x.example.", "documented_statement", "P1"), RemovalReason.MARKUP),
        (
            statement("The decree led to growth.", "documented_statement", "P1"),
            RemovalReason.CAUSAL_WORDING,
        ),
        (
            statement(
                "The decree states it.",
                "documented_statement",
                "P1",
                quotes=(Quote("P1", "six laboratories"),),
            ),
            RemovalReason.QUOTE,
        ),
        (
            statement(
                "The decree states it.",
                "documented_statement",
                "P1",
                quotes=(Quote("E1", "Status: reported"),),
            ),
            RemovalReason.QUOTE,
        ),
        (
            statement("The World Bank records 91 in 2024.", "recorded_observation", "E1"),
            RemovalReason.NUMBER,
        ),
    ],
)
def test_a_research_statement_is_kept_only_if_it_passes_every_check(
    proposed: ProposedStatement, reason: RemovalReason | None
) -> None:
    assert check_statement(proposed, EVIDENCE, assistant="research") == reason


def test_the_help_assistant_writes_documented_statements_of_help_only() -> None:
    kept = statement("Choose Export CSV on the run's page.", "documented_statement", "H1")

    assert check_statement(kept, EVIDENCE, assistant="help") is None
    assert (
        check_statement(
            statement("The decree states it.", "documented_statement", "P1"),
            EVIDENCE,
            assistant="help",
        )
        == RemovalReason.LABEL
    )
    assert (
        check_statement(
            statement("Choose Export CSV.", "stated_policy_objective", "H1"),
            EVIDENCE,
            assistant="help",
        )
        == RemovalReason.LABEL
    )


def test_an_invented_reference_can_never_pass() -> None:
    """The structural guarantee: a handle not issued for this question is always removed."""
    for handle in ("E99", "P0", "[P1]", "p1", "https://evil.example", ""):
        proposed = statement("The source states it.", "documented_statement", handle)
        assert check_statement(proposed, EVIDENCE, assistant="research") in (
            RemovalReason.UNKNOWN_HANDLE,
        )


# --- Uncertainty flags --------------------------------------------------------------


def test_flags_follow_from_the_evidence_and_from_what_was_measured() -> None:
    one = statement("TEST", "recorded_observation", "E1", "E2")

    assert uncertainty_flags(one, EVIDENCE, language="english", evaluated_languages=()) == [
        "single_source",
        "estimated_value",
        "language_not_evaluated",
    ]
    assert uncertainty_flags(
        one, EVIDENCE, language="russian", evaluated_languages=("english", "russian")
    ) == ["single_source", "estimated_value", "cross_language"]
    two = statement("TEST", "documented_statement", "P1", "H1")
    assert (
        uncertainty_flags(two, EVIDENCE, language="english", evaluated_languages=("english",)) == []
    )

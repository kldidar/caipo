"""The page of guarantees: what CAIPO guarantees, each with the tests that prove it.

Each guarantee names the automated tests that enforce it, by file and name.
They run on every change, and a change that fails one cannot be merged. A
test of this module checks that every test named here exists, so the page
cannot name one that was renamed or removed. The page reads no file at run
time: an installed instance may hold no tests.
"""

from dataclasses import dataclass

from django.conf import settings
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.utils.functional import Promise
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_safe

from caipo.web.access import public


@dataclass(frozen=True)
class Guarantee:
    text: Promise
    proofs: tuple[str, ...]


@dataclass(frozen=True)
class Group:
    title: Promise
    guarantees: tuple[Guarantee, ...]


GROUPS = (
    Group(
        _("Evidence and provenance"),
        (
            Guarantee(
                _(
                    "Records of provenance are never changed or deleted. The database itself "
                    "refuses a change or a deletion, even one sent to it directly."
                ),
                (
                    "caipo/accounts/tests/test_audit_event.py"
                    "::test_the_database_refuses_update_and_delete_of_an_event_sent_as_sql",
                    "caipo/indicators/tests/test_services.py"
                    "::test_releases_and_observations_are_never_changed_or_deleted",
                    "caipo/research/tests/test_services.py"
                    "::test_runs_and_searches_are_never_changed_or_deleted",
                    "caipo/sources/tests/test_segments.py"
                    "::test_the_database_refuses_any_change_or_deletion_of_a_segment",
                ),
            ),
            Guarantee(
                _(
                    "A missing value stays missing. The database refuses a value recorded as "
                    "missing that holds a number."
                ),
                (
                    "caipo/indicators/tests/test_services.py"
                    "::test_the_database_refuses_a_missing_value_that_holds_something",
                ),
            ),
            Guarantee(
                _(
                    "Real reference data and synthetic demonstration data are never mixed in a "
                    "reading, a timeline, or an analysis."
                ),
                (
                    "caipo/indicators/tests/test_services.py"
                    "::test_reference_and_demonstration_values_are_read_apart",
                    "caipo/policies/tests/test_timeline.py"
                    "::test_synthetic_and_reference_events_are_never_read_together",
                    "caipo/research/tests/test_services.py"
                    "::test_a_run_never_mixes_the_data_classes",
                ),
            ),
            Guarantee(
                _(
                    "No text of a real legal document is held. The database refuses a text on a "
                    "reference document, and quoted text on a reference provision."
                ),
                (
                    "caipo/sources/tests/test_segments.py"
                    "::test_the_database_refuses_a_segment_on_a_reference_document",
                    "caipo/policies/tests/test_services.py"
                    "::test_the_database_refuses_quoted_text_on_a_reference_provision",
                ),
            ),
            Guarantee(
                _(
                    "A policy's status is worked out from its formal events each time it is "
                    "shown, and is never stored."
                ),
                (
                    "caipo/policies/tests/test_status.py::test_a_policy_has_no_stored_status",
                    "caipo/policies/tests/test_services.py"
                    "::test_events_derive_the_status_and_are_recorded",
                ),
            ),
            Guarantee(
                _(
                    "An analysis can be checked: it records every input, its result, and their "
                    "fingerprints, and runs again to the same result until a later release of "
                    "the data arrives."
                ),
                (
                    "caipo/research/tests/test_services.py"
                    "::test_a_run_records_inputs_result_fingerprints_and_its_audit_event",
                    "caipo/research/tests/test_services.py"
                    "::test_a_run_reproduces_exactly_until_a_later_release_arrives",
                ),
            ),
        ),
    ),
    Group(
        _("The assistants"),
        (
            Guarantee(
                _(
                    "An answer can never show an invented reference: a statement that cites "
                    "anything not given for its question is removed."
                ),
                (
                    "caipo/assistant/tests/test_verification.py"
                    "::test_an_invented_reference_can_never_pass",
                ),
            ),
            Guarantee(
                _(
                    "A quotation must be in the text it cites, and a number in the evidence it "
                    "cites; a statement that fails either is removed."
                ),
                (
                    "caipo/assistant/tests/test_verification.py"
                    "::test_a_quotation_must_be_in_the_cited_text",
                    "caipo/assistant/tests/test_verification.py"
                    "::test_a_number_must_be_in_what_the_statement_itself_cites",
                ),
            ),
            Guarantee(
                _("A statement that uses a word of cause, in English or Russian, is not shown."),
                (
                    "caipo/assistant/tests/test_verification.py"
                    "::test_words_of_cause_are_found_in_english_and_russian",
                ),
            ),
            Guarantee(
                _(
                    "The model's words are shown as text, never as a link, an image, or markup; "
                    "every link in an answer is made by the server."
                ),
                (
                    "caipo/assistant/tests/test_verification.py"
                    "::test_a_link_an_image_or_html_is_found",
                    "caipo/web/tests/test_assistant_pages.py"
                    "::test_a_models_words_are_shown_escaped_and_never_as_a_link",
                    "caipo/web/tests/test_help_pages.py::test_a_models_words_are_shown_escaped",
                ),
            ),
            Guarantee(
                _(
                    "The model is given no tools: it cannot fetch, call, or change anything, and "
                    "only writes text that the server checks."
                ),
                (
                    "caipo/assistant/tests/test_providers.py"
                    "::test_a_call_sends_one_json_request_without_tools",
                ),
            ),
            Guarantee(
                _(
                    "An anonymous visitor cannot ask a question, and no question is sent past "
                    "the daily limits of an account and of the site."
                ),
                (
                    "caipo/web/tests/test_assistant_pages.py"
                    "::test_an_anonymous_visitor_is_refused_before_anything_is_asked",
                    "caipo/assistant/tests/test_interactions.py"
                    "::test_an_account_asks_no_more_than_its_daily_quota",
                    "caipo/assistant/tests/test_interactions.py"
                    "::test_the_instance_asks_no_more_than_its_daily_quota",
                ),
            ),
            Guarantee(
                _(
                    "Every question and every answer is recorded with how each check judged it, "
                    "and the record is never changed."
                ),
                (
                    "caipo/assistant/tests/test_interactions.py"
                    "::test_the_database_refuses_any_change_or_deletion",
                    "caipo/assistant/tests/test_answer_records.py"
                    "::test_the_database_refuses_any_change_or_deletion",
                ),
            ),
            Guarantee(
                _(
                    "The hostile documents used to test the assistants reach only an empty "
                    "database made for the test, never one that anyone uses."
                ),
                (
                    "caipo/demo/tests/test_evaluate_command.py"
                    "::test_it_refuses_a_database_that_holds_anything",
                    "caipo/demo/tests/test_evaluation_gold.py"
                    "::test_the_adversarial_corpus_is_synthetic_and_never_seeded",
                ),
            ),
        ),
    ),
    Group(
        _("Accounts and access"),
        (
            Guarantee(
                _(
                    "Every page declares who may open it, and a page without a declaration is "
                    "refused before it runs."
                ),
                (
                    "caipo/web/tests/test_access.py::test_every_routed_view_declares_its_access",
                    "caipo/web/tests/test_access.py"
                    "::test_a_view_without_a_declaration_is_refused_before_it_runs",
                ),
            ),
            Guarantee(
                _("Registering on the site gives the Reader role and nothing more."),
                (
                    "caipo/accounts/tests/test_registration.py"
                    "::test_from_registration_to_a_reader_who_can_read_and_do_nothing_else",
                ),
            ),
            Guarantee(
                _(
                    "Reviewer and Administrator accounts act only after a code from an "
                    "authenticator app; with a password alone they can only set one up."
                ),
                (
                    "caipo/accounts/tests/test_authorization.py"
                    "::test_reviewer_and_administrator_are_the_roles_requiring_a_second_factor",
                    "caipo/accounts/tests/test_authorization.py"
                    "::test_roles_requiring_a_second_factor_confer_only_enrolment_on_a_password",
                ),
            ),
            Guarantee(
                _("An Administrator holds no research permission."),
                (
                    "caipo/accounts/tests/test_authorization.py"
                    "::test_administrator_holds_no_research_permission",
                ),
            ),
            Guarantee(
                _(
                    "A refusal is the same whether or not the record asked for exists, so it "
                    "reveals nothing about what is held."
                ),
                (
                    "caipo/web/tests/test_registry_pages.py"
                    "::test_a_refusal_is_the_same_for_a_record_that_exists_and_one_that_does_not",
                ),
            ),
        ),
    ),
)


@dataclass(frozen=True)
class ProofShown:
    name: str
    url: str


def _shown(test: str) -> ProofShown:
    path, name = test.split("::")
    words = name.removeprefix("test_").replace("_", " ")
    return ProofShown(
        name=words[:1].upper() + words[1:],
        url=f"{settings.SOURCE_REPOSITORY_URL}/blob/main/{path}",
    )


@public
@require_safe
def guarantees(request: HttpRequest) -> HttpResponse:
    """List CAIPO's guarantees, each with the tests that enforce it, linked to their source."""
    groups = [
        {
            "title": group.title,
            "guarantees": [
                {"text": guarantee.text, "tests": [_shown(test) for test in guarantee.proofs]}
                for guarantee in group.guarantees
            ],
        }
        for group in GROUPS
    ]
    return render(
        request,
        "web/guarantees.html",
        {"groups": groups, "repository": settings.SOURCE_REPOSITORY_URL},
    )

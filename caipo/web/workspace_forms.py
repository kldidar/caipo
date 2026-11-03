"""Forms of the demonstrator's pages (ADR-0020) and of contributed articles (ADR-0022).

Shape only. The choices a form offers come from selectors, and what is
acceptable is decided by the services, which check everything again.
"""

from datetime import date
from typing import TYPE_CHECKING

from django import forms
from django.utils.translation import gettext_lazy as _

from caipo.articles.selectors import ArticleDecisionType
from caipo.core.data_class import DataClass
from caipo.policies.selectors import (
    AIFocus,
    ContextualCategory,
    CorpusAssignment,
    DocumentRole,
    PolicyEventType,
    PolicyType,
    ProvisionType,
)
from caipo.research.selectors import SearchLayer, SearchOutcome
from caipo.sources.selectors import DocumentType, PermittedUse, SourceTier

if TYPE_CHECKING:
    from django.utils.functional import _StrPromise

type Options = list[tuple[str, str]]

_BLANK: Options = [("", "—")]
_DATE = forms.DateInput(attrs={"type": "date"})


def _text(
    label: str | _StrPromise, *, required: bool = True, max_length: int = 1000
) -> forms.CharField:
    return forms.CharField(label=label, required=required, max_length=max_length, strip=False)


def _area(label: str | _StrPromise, *, required: bool = False) -> forms.CharField:
    return forms.CharField(
        label=label, required=required, widget=forms.Textarea(attrs={"rows": 3}), strip=False
    )


class _OptionsForm(forms.Form):
    """A form whose record choices are given when it is made."""

    def offer(self, field: str, options: Options, *, blank: bool = False) -> None:
        choice = self.fields[field]
        if not isinstance(choice, forms.ChoiceField):
            raise TypeError(f"{field} is not a choice field.")
        choice.choices = (_BLANK if blank else []) + options


class SourceForm(_OptionsForm):
    data_class = forms.ChoiceField(label=_("Data class"), choices=DataClass.choices)
    name = _text(_("Name"), max_length=300)
    publisher = _text(_("Publisher"), max_length=300)
    url = _text(_("Address"), max_length=2000)
    source_tier = forms.ChoiceField(label=_("Source tier"), choices=SourceTier.choices)
    country = forms.ChoiceField(label=_("Country"), required=False)
    licence = _text(_("Licence or terms"), required=False, max_length=500)
    licence_verified = forms.BooleanField(label=_("The licence has been verified"), required=False)
    permitted_use = forms.ChoiceField(label=_("Permitted use"), choices=PermittedUse.choices)
    accessed_on = forms.DateField(label=_("Accessed on"), widget=_DATE, initial=date.today)
    coverage = _area(_("Coverage"))
    limitations = _area(_("Known limitations"))


class DocumentForm(_OptionsForm):
    country = forms.ChoiceField(label=_("Country"))
    document_type = forms.ChoiceField(label=_("Form"), choices=DocumentType.choices)
    title = _text(_("Title as written"))
    title_language = forms.ChoiceField(label=_("Language of the title"))
    title_en = _text(_("English title"), required=False)
    title_en_official = forms.BooleanField(label=_("The English title is official"), required=False)
    official_identifier = _text(_("Official identifier"), required=False, max_length=200)
    date_of_issue = forms.DateField(label=_("Date of issue"), required=False, widget=_DATE)
    official_url = _text(_("Official address"), required=False, max_length=2000)
    accessed_on = forms.DateField(label=_("Accessed on"), required=False, widget=_DATE)
    issuing_institution = forms.ChoiceField(label=_("Issuing institution"), required=False)
    notes = _area(_("Notes"))


class PolicyForm(_OptionsForm):
    data_class = forms.ChoiceField(label=_("Data class"), choices=DataClass.choices)
    country = forms.ChoiceField(label=_("Country"))
    policy_type = forms.ChoiceField(label=_("Kind of policy"), choices=PolicyType.choices)
    title = _text(_("Title as written"))
    title_language = forms.ChoiceField(label=_("Language of the title"))
    title_en = _text(_("English title"), required=False)
    lead_institution = forms.ChoiceField(label=_("Lead institution"), required=False)
    corpus_assignment = forms.ChoiceField(
        label=_("Provisional assignment"), choices=CorpusAssignment.choices
    )
    ai_focus = forms.ChoiceField(
        label=_("AI focus (core only)"), choices=_BLANK + list(AIFocus.choices), required=False
    )
    contextual_category = forms.ChoiceField(
        label=_("Contextual category (contextual only)"),
        choices=_BLANK + list(ContextualCategory.choices),
        required=False,
    )
    assignment_reason = _area(_("Reason for the assignment"), required=True)
    summary = _area(_("Summary"))


class ReassignForm(forms.Form):
    corpus_assignment = forms.ChoiceField(
        label=_("Provisional assignment"), choices=CorpusAssignment.choices
    )
    ai_focus = forms.ChoiceField(
        label=_("AI focus (core only)"), choices=_BLANK + list(AIFocus.choices), required=False
    )
    contextual_category = forms.ChoiceField(
        label=_("Contextual category (contextual only)"),
        choices=_BLANK + list(ContextualCategory.choices),
        required=False,
    )
    assignment_reason = _area(_("Reason for the new assignment"), required=True)


class LinkForm(_OptionsForm):
    document = forms.ChoiceField(label=_("Document"))
    role = forms.ChoiceField(label=_("Role"), choices=DocumentRole.choices)


class EventForm(_OptionsForm):
    event_type = forms.ChoiceField(label=_("Formal event"), choices=PolicyEventType.choices)
    effective_date = forms.DateField(label=_("Effective date"), widget=_DATE)
    document = forms.ChoiceField(label=_("Establishing document"))
    locator = _text(_("Locator, for example an article"), required=False, max_length=200)


class ProvisionForm(_OptionsForm):
    provision_type = forms.ChoiceField(label=_("Kind of provision"), choices=ProvisionType.choices)
    document = forms.ChoiceField(label=_("Document"))
    locator = _text(_("Locator, for example an article"), max_length=200)
    label = _text(_("What it provides for"), max_length=300)
    quoted_text = _area(_("Quoted text (demonstration data only)"))


class AnalysisForm(_OptionsForm):
    title = _text(_("Title"), max_length=300)
    data_class = forms.ChoiceField(label=_("Data class"), choices=DataClass.choices)
    indicators = forms.MultipleChoiceField(
        label=_("Indicators"), widget=forms.CheckboxSelectMultiple
    )
    start_year = forms.IntegerField(label=_("First year"), min_value=1900, max_value=2100)
    end_year = forms.IntegerField(label=_("Last year"), min_value=1900, max_value=2100)


class SearchForm(forms.Form):
    data_class = forms.ChoiceField(label=_("Data class"), choices=DataClass.choices)
    title = _text(_("Title"), max_length=300)
    layer = forms.ChoiceField(label=_("Layer searched for"), choices=SearchLayer.choices)
    countries = _text(_("Countries searched"), max_length=200)
    searched_on = forms.DateField(label=_("Searched on"), widget=_DATE)
    queries = _area(_("Queries, in each language"), required=True)
    source_universe = _area(_("Sources in scope"), required=True)
    inclusion_criteria = _area(_("Inclusion criteria"), required=True)
    exclusion_criteria = _area(_("Exclusion criteria"))
    sources_examined = _area(_("Sources examined, with reasons for exclusion"), required=True)
    method = _area(_("Method, in enough detail to repeat it"), required=True)
    outcome = forms.ChoiceField(label=_("Outcome"), choices=SearchOutcome.choices)
    summary = _area(_("Summary, bounded by what was examined"), required=True)


class ArticleForm(forms.Form):
    """A contributed article (ADR-0022). The limits are checked again by the service."""

    author_name = _text(_("Your name, as it is to appear with the article"), max_length=120)
    title = _text(_("Title"), max_length=200)
    summary = forms.CharField(
        label=_("Summary, in two or three sentences"),
        max_length=600,
        strip=False,
        widget=forms.Textarea(attrs={"rows": 3}),
    )
    body = forms.CharField(
        label=_("Text"),
        max_length=20000,
        strip=False,
        widget=forms.Textarea(attrs={"rows": 18}),
    )
    licence = forms.BooleanField(
        label=_(
            "I wrote this text, and I publish it under the Creative Commons Attribution 4.0"
            " licence (CC BY 4.0) if it is accepted"
        ),
        required=False,
    )


class ArticleDecisionForm(forms.Form):
    """A reviewer's decision about an article. What may follow what is the service's to say."""

    decision = forms.ChoiceField(choices=ArticleDecisionType.choices)
    reason = forms.CharField(
        label=_("Reason, shown to the author (required to decline or withdraw)"),
        required=False,
        max_length=2000,
        strip=False,
        widget=forms.Textarea(attrs={"rows": 4}),
    )

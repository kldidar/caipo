"""Fill a development database with the demonstration environment (ADR-0020 point 16).

Development only: refuses to run unless DEBUG is on. Creates two accounts to
sign in with (a Researcher and a Reader), the countries and languages of the
catalogue, and then every institution, source, document, policy, event, and
provision of `caipo.demo.catalogue` through the services that write them,
with their audit events.

The accounts' roles are granted by a seeding account that cannot sign in, as
the test fixtures do: there is no Administrator yet to grant them. Countries
and languages are written directly, because only an Administrator verified
with a second factor may create them through the registry's services. Both
shortcuts exist only here, and only for a development database.

Running it again changes nothing: it stops if the demonstration is present.
"""

import hashlib
import json
import secrets
import uuid
from decimal import Decimal
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from caipo.accounts.models import RoleEvent, RoleEventType, User
from caipo.accounts.selectors import Role, authentication_context
from caipo.demo.catalogue import Catalogue, load
from caipo.demo.worldbank import read_snapshot
from caipo.indicators import selectors as indicators_selectors
from caipo.indicators import services as indicators_services
from caipo.indicators.services import ObservationRow
from caipo.policies import services as policies_services
from caipo.registry.models import Country, Language
from caipo.registry.services import Citation, NewName, create_institution
from caipo.research import services as research_services
from caipo.sources import services as sources_services
from caipo.sources.models import Source

SEED_EMAIL = "demo.seed@caipo.test"
RESEARCHER_EMAIL = "demo.researcher@caipo.test"
READER_EMAIL = "demo.reader@caipo.test"


class Command(BaseCommand):
    help = "Create the demonstration environment in a development database (DEBUG only)."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--password",
            help="Password for both demonstration accounts. A random one is printed if omitted.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        if not settings.DEBUG:
            raise CommandError("seed_demo runs only with DEBUG on, in a development database.")
        catalogue = load()
        if Source.objects.filter(name=catalogue.sources[0].name).exists():
            self.stdout.write("The demonstration environment is already present. Nothing done.")
            return
        password = options.get("password") or secrets.token_urlsafe(12)
        with transaction.atomic():
            researcher = self._accounts(password)
            self._seed(authentication_context(researcher, verified_device_id=None), catalogue)
        self.stdout.write(self.style.SUCCESS("Demonstration environment created."))
        self.stdout.write(f"  Researcher: {RESEARCHER_EMAIL}")
        self.stdout.write(f"  Reader:     {READER_EMAIL}")
        if not options.get("password"):
            self.stdout.write(f"  Password for both (shown once): {password}")

    def _accounts(self, password: str) -> User:
        seed = User.objects.filter(email=SEED_EMAIL).first() or User.objects.create_user(SEED_EMAIL)
        accounts = {}
        for email, role in ((RESEARCHER_EMAIL, Role.RESEARCHER), (READER_EMAIL, Role.READER)):
            user = User.objects.filter(email=email).first() or User.objects.create_user(email)
            user.set_password(password)
            user.save(update_fields=["password"])
            if not RoleEvent.objects.filter(user=user, role=role).exists():
                RoleEvent.objects.create(
                    user=user,
                    role=role,
                    event_type=RoleEventType.GRANTED,
                    actor=seed,
                    reason="Demonstration environment (seed_demo, development only)",
                )
            accounts[role] = user
        return accounts[Role.RESEARCHER]

    def _seed(self, actor: Any, catalogue: Catalogue) -> None:
        countries = {}
        for alpha2, alpha3, name in catalogue.countries:
            country, _ = Country.objects.get_or_create(
                alpha2=alpha2, defaults={"alpha3": alpha3, "name_en": name}
            )
            countries[alpha2] = country.public_id
        languages = {}
        for code, script, name in catalogue.languages:
            language, _ = Language.objects.get_or_create(
                code=code, script_code=script, defaults={"name_en": name}
            )
            languages[(code, script)] = language.public_id
        url, title = catalogue.institution_source
        demo_source = Citation(url=url, title=title, accessed_on=catalogue.accessed)
        institutions: dict[str, uuid.UUID] = {}
        for key, kind, alpha2, name in catalogue.institutions:
            institutions[key] = create_institution(
                actor=actor,
                kind=kind,
                country=countries[alpha2],
                first_name=NewName(
                    text=name,
                    language=languages[catalogue.english],
                    kind="official",
                    source=demo_source,
                ),
            )
        sources = {
            spec.key: sources_services.create_source(
                actor=actor,
                data_class=spec.data_class,
                name=spec.name,
                publisher=spec.publisher,
                url=spec.url,
                source_tier=spec.tier,
                permitted_use=spec.permitted_use,
                accessed_on=catalogue.accessed,
                country=countries[spec.country] if spec.country else None,
                licence=spec.licence,
                licence_verified=spec.licence_verified,
                coverage=spec.coverage,
                limitations=spec.limitations,
            )
            for spec in catalogue.sources
        }
        documents = {
            spec.key: sources_services.create_document(
                actor=actor,
                source=sources[spec.source],
                country=countries[spec.country],
                document_type=spec.document_type,
                title=spec.title,
                title_language=languages[spec.language],
                title_en=spec.title_en,
                title_en_official=spec.title_en_official,
                official_identifier=spec.identifier,
                date_of_issue=spec.issued,
                official_url=spec.url,
                accessed_on=catalogue.accessed,
                issuing_institution=institutions[spec.issuer] if spec.issuer else None,
                notes=spec.notes,
            )
            for spec in catalogue.documents
        }
        self._indicators(actor, catalogue, sources)
        self._research(actor, catalogue)
        for policy in catalogue.policies:
            public_id = policies_services.create_policy(
                actor=actor,
                data_class=policy.data_class,
                country=countries[policy.country],
                policy_type=policy.policy_type,
                title=policy.title,
                title_language=languages[policy.language],
                corpus_assignment=policy.corpus,
                assignment_reason=policy.reason,
                ai_focus=policy.ai_focus,
                contextual_category=policy.category,
                title_en=policy.title_en,
                lead_institution=institutions[policy.lead] if policy.lead else None,
                summary=policy.summary,
            )
            for document, role in policy.documents:
                policies_services.link_document(
                    actor=actor, policy=public_id, document=documents[document], role=role
                )
            for event_type, effective, document, locator in policy.events:
                policies_services.record_event(
                    actor=actor,
                    policy=public_id,
                    event_type=event_type,
                    effective_date=effective,
                    document=documents[document],
                    locator=locator,
                )
            for provision in policy.provisions:
                policies_services.add_provision(
                    actor=actor,
                    policy=public_id,
                    provision_type=provision.provision_type,
                    document=documents[provision.document],
                    locator=provision.locator,
                    label=provision.label,
                    quoted_text=provision.quoted_text,
                )

    def _indicators(self, actor: Any, catalogue: Catalogue, sources: dict[str, uuid.UUID]) -> None:
        estimated = frozenset(spec.code for spec in catalogue.indicators if spec.estimated)
        snapshot = read_snapshot(estimated)
        for spec in catalogue.indicators:
            described = snapshot.descriptions.get(spec.code)
            indicators_services.create_indicator(
                actor=actor,
                source=sources[spec.source],
                code=spec.code,
                name=described.name if described else spec.name,
                unit=spec.unit,
                layer=spec.layer,
                layer_reason=spec.reason,
                definition=described.definition if described else spec.definition,
                original_provider=described.original_provider if described else "",
            )
        reference_source = next(
            spec.source for spec in catalogue.indicators if spec.code in snapshot.descriptions
        )
        indicators_services.import_release(
            actor=actor,
            source=sources[reference_source],
            label=snapshot.label,
            retrieved_on=snapshot.retrieved_on,
            file_name="caipo/demo/data/worldbank/MANIFEST.json",
            sha256=snapshot.sha256,
            rows=snapshot.rows,
        )
        release = catalogue.demo_release
        indicators_services.import_release(
            actor=actor,
            source=sources[release.source],
            label=release.label,
            retrieved_on=catalogue.accessed,
            file_name=release.file_name,
            sha256=hashlib.sha256(
                json.dumps(catalogue.demo_observations, sort_keys=True).encode()
            ).hexdigest(),
            rows=[
                ObservationRow(
                    indicator_code=code,
                    country_alpha2=country,
                    year=year,
                    value=Decimal(value) if value is not None else None,
                    status=status,
                )
                for code, country, year, value, status in catalogue.demo_observations
            ],
        )

    def _research(self, actor: Any, catalogue: Catalogue) -> None:
        for spec in catalogue.analyses:
            research_services.run_analysis(
                actor=actor,
                title=spec.title,
                data_class=spec.data_class,
                indicators=[
                    public_id
                    for public_id, _name, layer in indicators_selectors.indicator_choices(
                        actor, data_class=spec.data_class
                    )
                    if layer == spec.layer
                ],
                start_year=spec.start_year,
                end_year=spec.end_year,
            )
        for search in catalogue.searches:
            research_services.record_search(
                actor=actor,
                data_class=search.data_class,
                title=search.title,
                layer=search.layer,
                countries=search.countries,
                searched_on=search.searched_on,
                queries=search.queries,
                source_universe=search.source_universe,
                inclusion_criteria=search.inclusion_criteria,
                exclusion_criteria=search.exclusion_criteria,
                sources_examined=search.sources_examined,
                method=search.method,
                outcome=search.outcome,
                summary=search.summary,
            )

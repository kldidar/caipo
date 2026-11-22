"""Run the evaluation of the assistants on a database of its own (AI_ARCHITECTURE.md §9.1).

Development only, and only on an empty database: it seeds the demonstration
environment, adds the adversarial corpus, which must never reach any other
database, rebuilds the retrieval index, and asks every case of the gold set
in the languages chosen, through the configured provider. It writes, for
each language, every case's result as JSON and the summary as Markdown.

Each case is asked by a Reader account of its own, made here as seed_demo
makes its accounts, so that no account's daily quota limits the run.
"""

import hashlib
import io
import secrets
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError

from caipo.accounts.models import RoleEvent, RoleEventType, User
from caipo.accounts.selectors import AuthenticationContext, Role, authentication_context
from caipo.assistant import config as assistant_config
from caipo.assistant.providers import get_provider
from caipo.demo import catalogue as demo_catalogue
from caipo.demo import evaluation
from caipo.demo.evaluation import AdversarialCorpus, CaseResult, GoldSet
from caipo.demo.management.commands.seed_demo import RESEARCHER_EMAIL, SEED_EMAIL
from caipo.registry.models import Country, Language
from caipo.retrieval import corpus as help_corpus
from caipo.retrieval import selectors as retrieval_selectors
from caipo.retrieval import services as retrieval_services
from caipo.sources import services as sources_services
from caipo.sources.models import Source


class Command(BaseCommand):
    help = "Evaluate the assistants on an empty development database of their own (DEBUG only)."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--language",
            action="append",
            choices=evaluation.LANGUAGES,
            help="A language to run; repeat for both. All languages if omitted.",
        )
        parser.add_argument(
            "--case",
            action="append",
            help="A pair identifier to run, such as R01; repeat for more. All cases if omitted.",
        )
        parser.add_argument("--output", required=True, help="Directory for the results.")
        parser.add_argument(
            "--pause", type=float, default=0.0, help="Seconds to wait after each case."
        )
        parser.add_argument(
            "--attempts", type=int, default=3, help="Attempts of a case refused for its rate."
        )
        parser.add_argument(
            "--rate-wait", type=float, default=60.0, help="Seconds to wait after such a refusal."
        )

    def handle(self, *args: Any, **options: Any) -> None:
        if not settings.DEBUG:
            raise CommandError("evaluate_assistants runs only with DEBUG on.")
        if User.objects.exists():
            raise CommandError(
                "evaluate_assistants runs only on an empty database of its own: it adds"
                " hostile documents that must never reach any other database."
            )
        if options["attempts"] < 1:
            raise CommandError("--attempts is at least 1.")
        gold = evaluation.load_gold()
        adversarial = evaluation.load_adversarial()
        languages = options["language"] or list(evaluation.LANGUAGES)
        pairs = set(options["case"] or [])
        unknown = pairs - {case.pair for case in gold.cases}
        if unknown:
            raise CommandError(f"Unknown cases: {', '.join(sorted(unknown))}.")
        output = Path(options["output"])
        output.mkdir(parents=True, exist_ok=True)

        call_command("seed_demo", password=secrets.token_urlsafe(16), stdout=io.StringIO())
        self._adversarial(adversarial)
        retrieval_services.rebuild_index()
        real = get_provider()
        meta = self._meta(gold, adversarial, real.model)
        for language in languages:
            cases = [
                case
                for case in gold.cases
                if case.language == language and (not pairs or case.pair in pairs)
            ]
            results = evaluation.run(
                cases,
                real=real,
                new_reader=self._reader,
                attempts=options["attempts"],
                wait=time.sleep,
                pause_seconds=options["pause"],
                rate_limit_seconds=options["rate_wait"],
                progress=self._progress,
            )
            run_meta = {**meta, "language": language, "finished_at": _now()}
            (output / f"results-{language}.json").write_text(
                evaluation.results_document(results, run_meta) + "\n", encoding="utf-8"
            )
            (output / f"summary-{language}.md").write_text(
                evaluation.report(results, language.capitalize()) + "\n", encoding="utf-8"
            )
            self.stdout.write(self.style.SUCCESS(f"{language}: {len(results)} cases written."))

    def _adversarial(self, corpus: AdversarialCorpus) -> None:
        researcher = User.objects.get(email=RESEARCHER_EMAIL)
        actor = authentication_context(researcher, verified_device_id=None)
        if actor is None:
            raise CommandError("The demonstration Researcher cannot act; nothing evaluated.")
        source_name = next(
            spec.name for spec in demo_catalogue.load().sources if spec.key == corpus.source
        )
        source = Source.objects.get(name=source_name).public_id
        country = Country.objects.get(alpha2=corpus.country).public_id
        code, script = corpus.language
        language = Language.objects.get(code=code, script_code=script).public_id
        for document in corpus.documents:
            public_id = sources_services.create_document(
                actor=actor,
                source=source,
                country=country,
                document_type=document.document_type,
                title=document.title,
                title_language=language,
                official_identifier=document.identifier,
                date_of_issue=document.issued,
                official_url=document.url,
                notes=f"Adversarial corpus {corpus.version}: evaluation only.",
            )
            sources_services.attach_demonstration_text(
                actor=actor,
                document=public_id,
                parts=[
                    sources_services.TextPart(locator, text) for locator, text in document.parts
                ],
            )

    def _reader(self) -> AuthenticationContext:
        seed = User.objects.get(email=SEED_EMAIL)
        user = User.objects.create_user(f"evaluation.{secrets.token_hex(6)}@caipo.test")
        RoleEvent.objects.create(
            user=user,
            role=Role.READER,
            event_type=RoleEventType.GRANTED,
            actor=seed,
            reason="Evaluation of the assistants (evaluate_assistants, development only)",
        )
        actor = authentication_context(user, verified_device_id=None)
        if actor is None:
            raise CommandError("An evaluation Reader cannot act; nothing evaluated.")
        return actor

    def _progress(self, result: CaseResult) -> None:
        reason = f" ({result.reason})" if result.reason else ""
        self.stdout.write(
            f"{result.id}: {result.outcome}{reason},"
            f" {len(result.shown)} shown, {result.real_calls} calls"
        )

    def _meta(self, gold: GoldSet, adversarial: AdversarialCorpus, model: str) -> dict[str, Any]:
        configuration = assistant_config.load()
        help_text = "".join(
            path.read_text(encoding="utf-8")
            for path in sorted(help_corpus.HELP_DIRECTORY.glob("*.md"))
        )
        return {
            "gold": {"version": gold.version, "sha256": gold.sha256},
            "adversarial": {"version": adversarial.version, "sha256": adversarial.sha256},
            "corpus": {
                "catalogue_sha256": hashlib.sha256(demo_catalogue.PATH.read_bytes()).hexdigest(),
                "help_sha256": hashlib.sha256(help_text.encode("utf-8")).hexdigest(),
            },
            "pipeline_version": configuration.pipeline_version,
            "prompt_versions": {
                name: configuration.prompt(name)[0] for name in configuration.prompts
            },
            "model": f"{configuration.provider.name}:{model}",
            "generation": {
                "temperature": configuration.provider.temperature,
                "max_output_tokens": configuration.provider.max_output_tokens,
            },
            "chunking_version": retrieval_selectors.chunking_version(),
            "evaluated_languages": list(configuration.evaluated_languages),
            "started_at": _now(),
        }


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")

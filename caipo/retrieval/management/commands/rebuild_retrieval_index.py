"""Rebuild the retrieval index from the Segments held and the help corpus (ADR-0025)."""

from typing import Any

from django.core.management.base import BaseCommand

from caipo.retrieval import services


class Command(BaseCommand):
    help = "Delete and rebuild every retrieval chunk. Derived data only; no record is changed."

    def handle(self, *args: Any, **options: Any) -> None:
        summary = services.rebuild_index()
        self.stdout.write(
            self.style.SUCCESS(
                f"Retrieval index {summary.version}: {summary.document_chunks} document chunks,"
                f" {summary.help_chunks} help chunks."
            )
        )

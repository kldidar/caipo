"""The shared base of records that are written once (ADR-0018 points 24 to 26).

Abstract, and knows no user and no domain. It is a guard against mistakes in
application code and not the boundary: it does not see SQL sent past the
model, nor a write through a manager that does not use its queryset.
"""

from typing import Any, NoReturn

from django.db import models


class AppendOnlyError(Exception):
    """An attempt was made to change or delete a record that is append-only."""


class AppendOnlyQuerySet[M: models.Model](models.QuerySet[M]):
    """Refuses the bulk operations that would rewrite history."""

    def update(self, **kwargs: Any) -> NoReturn:
        raise AppendOnlyError("Append-only records are never updated.")

    def bulk_update(self, *args: Any, **kwargs: Any) -> NoReturn:
        raise AppendOnlyError("Append-only records are never updated.")

    def delete(self) -> NoReturn:
        raise AppendOnlyError("Append-only records are never deleted.")


class AppendOnlyModel(models.Model):
    """A record that is written once and never changed or removed.

    Two layers keep it so. The guards here and in AppendOnlyQuerySet stop
    application code from rewriting a record and say why. A PostgreSQL trigger,
    created by the migration that creates each table, refuses UPDATE and
    DELETE whatever sent them; it is the boundary that counts (ADR-0012).
    """

    class Meta:
        abstract = True

    def save(self, *args: Any, **kwargs: Any) -> None:
        if not self._state.adding:
            raise AppendOnlyError("Append-only records are never updated.")
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> NoReturn:
        raise AppendOnlyError("Append-only records are never deleted.")

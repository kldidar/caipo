"""The shared append-only base: abstract, and without knowledge of any app (ADR-0018)."""

import ast
import inspect

import pytest
from django.db import models

from caipo.core import append_only
from caipo.core.append_only import AppendOnlyError, AppendOnlyModel, AppendOnlyQuerySet


def _imported_modules() -> set[str]:
    tree = ast.parse(inspect.getsource(append_only))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0, "a relative import hides what is imported"
            modules.add(node.module or "")
    return modules


def test_it_imports_nothing_of_the_application() -> None:
    assert _imported_modules() == {"typing", "django.db"}


def test_the_model_is_abstract_and_has_no_table() -> None:
    assert AppendOnlyModel._meta.abstract
    assert AppendOnlyModel._meta.concrete_fields == ()


def test_the_error_is_no_database_error() -> None:
    """It is raised before the database is asked, and must not be mistaken for its answer."""
    assert AppendOnlyError.__bases__ == (Exception,)


def test_the_queryset_refuses_before_it_reaches_any_database() -> None:
    queryset: AppendOnlyQuerySet[models.Model] = AppendOnlyQuerySet()

    with pytest.raises(AppendOnlyError, match="never updated"):
        queryset.update(anything="TEST")
    with pytest.raises(AppendOnlyError, match="never updated"):
        queryset.bulk_update([], ["anything"])
    with pytest.raises(AppendOnlyError, match="never deleted"):
        queryset.delete()


def test_the_three_event_models_and_the_two_audit_models_are_built_on_it() -> None:
    from django.apps import apps

    built_on_it = {
        model.__name__ for model in apps.get_models() if issubclass(model, AppendOnlyModel)
    }

    assert built_on_it == {
        "RoleEvent",
        "AuthenticationEvent",
        "AccountEvent",
        "AuditEvent",
        "AuditEventChange",
    }
    for model in apps.get_models():
        if issubclass(model, AppendOnlyModel):
            assert isinstance(model._default_manager.all(), AppendOnlyQuerySet)

"""What the registry is built from, and what it is kept apart from
(ADR-0018 points 1, 2, 16, 55 to 57, and 61; ADR-0019 points 5 and 25 to 28;
testing requirements 10 and 13).

`lint-imports` checks the import contracts themselves. These tests check
what that tool cannot: that the contract names every module it should, that
the application holds no code of a particular country, and that the registry
holds nothing of a later increment.
"""

import ast
import pkgutil
import re
import tomllib
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from django.apps import apps
from django.conf import settings
from django.db.models import Model

import caipo.accounts
import caipo.registry
from caipo.registry import selectors, services
from caipo.registry.models import Country, Language

REPOSITORY = Path(settings.BASE_DIR)
APPLICATION = REPOSITORY / "caipo"
REGISTRY = APPLICATION / "registry"

# The only modules of accounts that the registry may use (ADR-0018 point 2).
PUBLIC_INTERFACE = {"services", "selectors"}
# Every string of two or three letters that the application code holds, each
# of them looked at: none is the code of a country or of a language. A new
# one fails the test below until it has been looked at and is added here.
SHORT_WORDS = {"GET", "Lax", "UTC", "can", "en", "id", "mfa", "off", "ok", "on", "pk", "url", "web"}


def _contracts() -> list[dict[str, Any]]:
    with (REPOSITORY / "pyproject.toml").open("rb") as file:
        contracts: list[dict[str, Any]] = tomllib.load(file)["tool"]["importlinter"]["contracts"]
    return contracts


def _application_modules() -> Iterator[Path]:
    """Yield every module of the application that is not a test or a migration."""
    for path in sorted(APPLICATION.rglob("*.py")):
        if "tests" not in path.parts and "migrations" not in path.parts:
            yield path


def _imports(path: Path) -> set[str]:
    """Return every module that a file imports, and every name it imports from one."""
    imported: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            imported.add(node.module)
            imported.update(f"{node.module}.{alias.name}" for alias in node.names)
    return imported


# --- The import contracts (testing requirement 13) ----------------------------


def test_the_registry_has_a_layer_of_its_own_directly_above_accounts() -> None:
    (layering,) = [contract for contract in _contracts() if contract["type"] == "layers"]

    assert layering["layers"] == ["config", "web", "registry", "accounts", "core"]
    assert layering["exhaustive"] is True
    assert layering["containers"] == ["caipo"]
    assert "ignore_imports" not in layering


def test_the_boundary_contract_closes_every_module_of_accounts_but_its_two_interfaces() -> None:
    """A module added to accounts later is closed to the registry until this list names it."""
    (boundary,) = [contract for contract in _contracts() if contract["type"] == "forbidden"]
    modules = {module.name for module in pkgutil.iter_modules(caipo.accounts.__path__)}

    assert PUBLIC_INTERFACE <= modules
    assert boundary["source_modules"] == ["caipo.registry"]
    assert set(boundary["forbidden_modules"]) == {
        f"caipo.accounts.{name}" for name in modules - PUBLIC_INTERFACE
    }
    assert boundary["allow_indirect_imports"] is True


def test_the_boundary_contract_has_the_one_exception_and_no_other() -> None:
    (boundary,) = [contract for contract in _contracts() if contract["type"] == "forbidden"]

    assert boundary["ignore_imports"] == ["caipo.registry.tests.** -> caipo.accounts.models"]


def test_no_registry_module_outside_its_tests_imports_anything_of_accounts_but_the_interfaces() -> (
    None
):
    allowed = re.compile(r"caipo\.accounts(\.(services|selectors)(\..+)?)?")
    offending = {
        str(path.relative_to(REPOSITORY)): sorted(
            name
            for name in _imports(path)
            if name.startswith("caipo.accounts") and not allowed.fullmatch(name)
        )
        for path in sorted(REGISTRY.rglob("*.py"))
        if "tests" not in path.parts
    }

    assert {path: names for path, names in offending.items() if names} == {}


def test_a_registry_test_imports_only_the_two_audit_models_from_the_account_models() -> None:
    """What import-linter cannot tell apart: one name of a module from another.

    ADR-0019 point 27.
    """
    imported: dict[str, set[str]] = {}
    for path in sorted((REGISTRY / "tests").rglob("*.py")):
        names = {
            name.removeprefix("caipo.accounts.models.")
            for name in _imports(path)
            if name.startswith("caipo.accounts.models.")
        }
        assert "caipo.accounts.models" not in {
            alias.name
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
            if isinstance(node, ast.Import)
            for alias in node.names
        }, path
        if names:
            imported[path.name] = names

    assert imported, "no registry test inspects the audit record"
    assert set().union(*imported.values()) <= {"AuditEvent", "AuditEventChange"}


def test_no_registry_test_imports_the_tests_of_another_app_or_a_higher_layer() -> None:
    forbidden = re.compile(r"caipo\.(accounts\.tests|web|config)(\..+)?")
    offending = {
        path.name: sorted(name for name in _imports(path) if forbidden.fullmatch(name))
        for path in sorted((REGISTRY / "tests").rglob("*.py"))
    }

    assert {path: names for path, names in offending.items() if names} == {}


def test_no_registry_test_writes_an_audit_record_itself() -> None:
    """`record_audit_event` is the only code that creates one (ADR-0018 point 38)."""
    writes = re.compile(
        r"AuditEvent(Change)?(\.objects\.(create|bulk_create|get_or_create|update_or_create)|\()"
    )
    offending = [
        path.name
        for path in sorted((REGISTRY / "tests").rglob("*.py"))
        if path.name != Path(__file__).name and writes.search(path.read_text(encoding="utf-8"))
    ]

    assert offending == []


def test_accounts_and_core_import_nothing_of_the_registry() -> None:
    offending = [
        str(path.relative_to(REPOSITORY))
        for package in ("accounts", "core")
        for path in sorted((APPLICATION / package).rglob("*.py"))
        if any(name.startswith("caipo.registry") for name in _imports(path))
    ]

    assert offending == []


# --- No country in the code (testing requirement 10) --------------------------


def test_the_application_code_holds_no_literal_country_or_language_code() -> None:
    """No string in the application has the form of a code, but for words looked at one by one.

    A branch on a particular country needs its code as a literal. This finds
    every string of two or three letters, in either case, in every module
    that is not a test or a migration.
    """
    found: dict[str, set[str]] = {}
    for path in _application_modules():
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and re.fullmatch(r"[A-Za-z]{2,3}", node.value)
                and node.value not in SHORT_WORDS
            ):
                found.setdefault(node.value, set()).add(str(path.relative_to(REPOSITORY)))

    assert found == {}


def test_no_template_compares_anything_with_a_literal_code() -> None:
    literal = re.compile(r"""{%[^%]*["'][A-Za-z]{2,3}["'][^%]*%}""")
    offending = [
        str(path.relative_to(REPOSITORY))
        for path in sorted(APPLICATION.rglob("*.html"))
        if literal.search(path.read_text(encoding="utf-8"))
    ]

    assert offending == []


def test_the_registry_code_names_no_code_of_its_own_tests() -> None:
    """The synthetic codes of the tests are in the tests and nowhere else."""
    synthetic = re.compile(r"""["'](XA|XB|QM|XAA|XBB|QMA|qaa|qab|Qaaa|Qaab)["']""")
    offending = [
        str(path.relative_to(REPOSITORY))
        for path in _application_modules()
        if synthetic.search(path.read_text(encoding="utf-8"))
    ]

    assert offending == []


# --- No initial data (ADR-0018 points 55 and 56) ------------------------------


def test_no_registry_migration_writes_a_row() -> None:
    for path in sorted((REGISTRY / "migrations").glob("0*.py")):
        source = path.read_text(encoding="utf-8")

        assert "RunPython" not in source, path.name
        assert not re.search(r"\bINSERT\b|\bCOPY\b", source, flags=re.IGNORECASE), path.name


def test_the_repository_holds_no_registry_fixture_file() -> None:
    assert not list(REGISTRY.rglob("fixtures"))
    assert not [
        path for path in REGISTRY.rglob("*") if path.suffix in {".json", ".yaml", ".yml", ".csv"}
    ]


# --- Nothing of a later increment (ADR-0019 point 5) --------------------------


def test_the_registry_has_exactly_two_models() -> None:
    models: list[type[Model]] = list(apps.get_app_config("registry").get_models())

    assert models == [Country, Language]


def test_the_registry_offers_exactly_these_operations_and_reads() -> None:
    """An operation that is not in the write matrix does not exist (ADR-0018 point 13)."""
    public = {
        name
        for name, value in vars(services).items()
        if callable(value)
        and not name.startswith("_")
        and getattr(value, "__module__", None) == services.__name__
        and not isinstance(value, type)
    }

    assert public == {
        "create_country",
        "rename_country",
        "deactivate_country",
        "reactivate_country",
        "create_language",
        "rename_language",
        "deactivate_language",
        "reactivate_language",
    }
    assert set(selectors.__all__) == {"CountryEntry", "LanguageEntry", "countries", "languages"}


def test_no_service_or_selector_deletes_or_changes_a_code() -> None:
    for module in (services, selectors):
        source = Path(str(module.__file__)).read_text(encoding="utf-8")

        assert ".delete(" not in source
        assert not re.search(r"\.(alpha2|alpha3|code|script_code|public_id)\s*=[^=]", source)


@pytest.mark.parametrize("word", ["institution", "Institution"])
def test_the_registry_package_says_nothing_of_institutions_but_the_permission(word: str) -> None:
    """No model, operation, selector, or text announces what Increment 3 builds."""
    mentions = [
        f"{path.relative_to(REPOSITORY)}: {line.strip()}"
        for path in sorted(REGISTRY.rglob("*.py"))
        if "tests" not in path.parts
        for line in path.read_text(encoding="utf-8").splitlines()
        if word in line
    ]

    assert mentions == []


def test_the_registry_is_not_registered_with_an_admin_site() -> None:
    assert "django.contrib.admin" not in settings.INSTALLED_APPS
    assert not (REGISTRY / "admin.py").exists()


def test_the_registry_package_is_what_the_import_contract_names() -> None:
    assert caipo.registry.__name__ == "caipo.registry"
    assert apps.get_app_config("registry").name == "caipo.registry"

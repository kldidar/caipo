"""Read the committed snapshot of the World Bank Indicators API (ADR-0020 point 9).

The files are external content and are treated as untrusted: each file's
SHA-256 must match the manifest, every field is checked for its type and
form, and anything unexpected stops the import. Values are read as exact
decimals from the text of the file, never through floating point. A value
the provider leaves empty is a missing value, and stays one.

The application makes no network call: the files were obtained once, on the
date the manifest gives, and are kept in the repository as received.
"""

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

from caipo.indicators.services import ObservationRow

DIRECTORY = Path(__file__).with_name("data") / "worldbank"
MANIFEST = DIRECTORY / "MANIFEST.json"
_CODE = re.compile(r"^[A-Z0-9.]{3,32}$")
_YEAR = re.compile(r"^(19|20)\d\d$")
_ALPHA2 = re.compile(r"^[A-Z]{2}$")


class SnapshotError(ValueError):
    """A file of the snapshot is missing, altered, or not of the form expected."""


@dataclass(frozen=True)
class IndicatorDescription:
    code: str
    name: str
    definition: str
    original_provider: str


@dataclass(frozen=True)
class Snapshot:
    label: str
    retrieved_on: date
    sha256: str
    licence: str
    descriptions: dict[str, IndicatorDescription]
    rows: tuple[ObservationRow, ...]


def _text(value: Any, field: str, *, limit: int) -> str:
    if not isinstance(value, str) or len(value) > limit:
        raise SnapshotError(f"{field} is not text of at most {limit} characters.")
    return value


def _read(path: Path, expected: str) -> Any:
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != expected:
        raise SnapshotError(f"{path.name} does not match the hash in the manifest.")
    return json.loads(data, parse_float=Decimal, parse_int=Decimal)


def _description(path: Path, expected: str, code: str) -> IndicatorDescription:
    body = _read(path, expected)
    if not (isinstance(body, list) and len(body) == 2 and isinstance(body[1], list) and body[1]):
        raise SnapshotError(f"{path.name} is not an indicator description.")
    item = body[1][0]
    if not isinstance(item, dict) or item.get("id") != code:
        raise SnapshotError(f"{path.name} describes another indicator.")
    return IndicatorDescription(
        code=code,
        name=_text(item.get("name"), "name", limit=300),
        definition=_text(item.get("sourceNote", ""), "definition", limit=5000),
        original_provider=_text(item.get("sourceOrganization", ""), "provider", limit=500),
    )


def _rows(path: Path, expected: str, code: str, status_held: str) -> list[ObservationRow]:
    body = _read(path, expected)
    if not (isinstance(body, list) and len(body) == 2 and isinstance(body[1], list)):
        raise SnapshotError(f"{path.name} is not an indicator response.")
    rows = []
    for item in body[1]:
        if not isinstance(item, dict):
            raise SnapshotError(f"{path.name} holds an entry that is not a record.")
        indicator = item.get("indicator")
        country = item.get("country")
        year = item.get("date")
        value = item.get("value")
        if not (isinstance(indicator, dict) and indicator.get("id") == code):
            raise SnapshotError(f"{path.name} holds a value of another indicator.")
        if not (isinstance(country, dict) and isinstance(country.get("id"), str)):
            raise SnapshotError(f"{path.name} holds a value without a country.")
        alpha2 = country["id"]
        if not _ALPHA2.match(alpha2) or not isinstance(year, str) or not _YEAR.match(year):
            raise SnapshotError(f"{path.name} holds a malformed country or year.")
        if value is not None and not isinstance(value, Decimal):
            raise SnapshotError(f"{path.name} holds a value that is not a number.")
        rows.append(
            ObservationRow(
                indicator_code=code,
                country_alpha2=alpha2,
                year=int(year),
                value=value,
                status="missing" if value is None else status_held,
            )
        )
    return rows


def read_snapshot(estimated: frozenset[str], directory: Path = DIRECTORY) -> Snapshot:
    """Read and check every file of the snapshot.

    `estimated` names the indicators whose values the provider publishes as
    modelled estimates; their values are marked estimated, every other value
    reported. Raises SnapshotError if a file is missing, does not match its
    hash, or is not of the form expected.
    """
    manifest_path = directory / "MANIFEST.json"
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes)
    files = manifest.get("files")
    if not isinstance(files, dict) or not files:
        raise SnapshotError("The manifest lists no file.")
    descriptions: dict[str, IndicatorDescription] = {}
    rows: list[ObservationRow] = []
    for name, expected in sorted(files.items()):
        if not isinstance(name, str) or "/" in name or not isinstance(expected, str):
            raise SnapshotError("The manifest names a file it may not.")
        code = name.removesuffix(".meta.json").removesuffix(".json")
        if not _CODE.match(code):
            raise SnapshotError(f"{name} is not named after an indicator code.")
        path = directory / name
        if name.endswith(".meta.json"):
            descriptions[code] = _description(path, expected, code)
        else:
            status = "estimated" if code in estimated else "reported"
            rows.extend(_rows(path, expected, code, status))
    return Snapshot(
        label=_text(manifest.get("release_label"), "release label", limit=100),
        retrieved_on=date.fromisoformat(_text(manifest.get("retrieved_on"), "date", limit=10)),
        sha256=hashlib.sha256(manifest_bytes).hexdigest(),
        licence=_text(manifest.get("licence"), "licence", limit=1000),
        descriptions=descriptions,
        rows=tuple(rows),
    )

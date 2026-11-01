"""Reading the committed World Bank snapshot (ADR-0020 point 9). The files are untrusted."""

import json
import shutil
from decimal import Decimal
from pathlib import Path

import pytest

from caipo.demo.worldbank import DIRECTORY, SnapshotError, read_snapshot


def test_the_committed_snapshot_reads_with_exact_values_and_gaps() -> None:
    snapshot = read_snapshot(frozenset({"SL.AGR.EMPL.ZS"}))

    assert snapshot.label == "World Development Indicators, last updated 2026-10-08"
    assert len(snapshot.descriptions) == 8
    assert {row.country_alpha2 for row in snapshot.rows} == {"TM", "UZ"}
    assert all(isinstance(row.value, Decimal) or row.value is None for row in snapshot.rows)
    assert all((row.value is None) == (row.status == "missing") for row in snapshot.rows)
    estimated = {row.indicator_code for row in snapshot.rows if row.status == "estimated"}
    assert estimated == {"SL.AGR.EMPL.ZS"}
    assert "CC BY 4.0" in snapshot.licence


@pytest.fixture
def copy(tmp_path: Path) -> Path:
    target = tmp_path / "worldbank"
    shutil.copytree(DIRECTORY, target)
    return target


def test_an_altered_file_is_refused(copy: Path) -> None:
    path = copy / "IT.NET.USER.ZS.json"
    path.write_bytes(path.read_bytes().replace(b'"value":null', b'"value":99', 1))

    with pytest.raises(SnapshotError, match="hash"):
        read_snapshot(frozenset(), copy)


def _rewrite(copy: Path, name: str, body: object) -> None:
    import hashlib

    data = json.dumps(body).encode()
    (copy / name).write_bytes(data)
    manifest = json.loads((copy / "MANIFEST.json").read_text())
    manifest["files"][name] = hashlib.sha256(data).hexdigest()
    (copy / "MANIFEST.json").write_text(json.dumps(manifest))


@pytest.mark.parametrize(
    "row",
    [
        {"indicator": {"id": "OTHER"}, "country": {"id": "TM"}, "date": "2020", "value": 1},
        {
            "indicator": {"id": "IT.NET.USER.ZS"},
            "country": {"id": "Turkmenistan"},
            "date": "2020",
            "value": 1,
        },
        {
            "indicator": {"id": "IT.NET.USER.ZS"},
            "country": {"id": "TM"},
            "date": "20x0",
            "value": 1,
        },
        {
            "indicator": {"id": "IT.NET.USER.ZS"},
            "country": {"id": "TM"},
            "date": "2020",
            "value": "1",
        },
        "not a record",
    ],
)
def test_a_malformed_entry_stops_the_import(copy: Path, row: object) -> None:
    _rewrite(copy, "IT.NET.USER.ZS.json", [{"page": 1}, [row]])

    with pytest.raises(SnapshotError):
        read_snapshot(frozenset(), copy)


def test_the_manifest_may_not_name_a_file_elsewhere(copy: Path) -> None:
    manifest = json.loads((copy / "MANIFEST.json").read_text())
    manifest["files"]["../outside.json"] = "0" * 64
    (copy / "MANIFEST.json").write_text(json.dumps(manifest))

    with pytest.raises(SnapshotError):
        read_snapshot(frozenset(), copy)

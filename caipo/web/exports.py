"""Exports of research records as CSV and JSON (ADR-0020).

An export carries its provenance with it: the data class of every row, the
release and source each value came from, the method and its version, the
fingerprints, and a methodology note with the non-causation notice. CSV
cells are protected against formula injection: a cell that a spreadsheet
would read as a formula is prefixed with an apostrophe.
"""

import csv
import io
import json
from collections.abc import Iterable, Sequence
from typing import Any

from django.http import HttpResponse

# A cell that begins with one of these is read by spreadsheets as a formula.
_FORMULA_START = ("=", "+", "-", "@", "\t", "\r")

NON_CAUSATION = (
    "This output describes measured values. It does not show that any policy caused any change, "
    "and an association between indicators, layers, or policy events is not evidence of a cause."
)


def safe_cell(value: object) -> str:
    """Return a value as CSV text that no spreadsheet will run as a formula."""
    text = "" if value is None else str(value)
    if text.startswith(_FORMULA_START):
        return "'" + text
    return text


def csv_response(
    filename: str, notes: Sequence[str], header: Sequence[str], rows: Iterable[Sequence[object]]
) -> HttpResponse:
    """Answer with a CSV file: notes as leading comment lines, then a header and the rows."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\r\n")
    for note in notes:
        writer.writerow([safe_cell(f"# {note}")])
    writer.writerow([safe_cell(name) for name in header])
    for row in rows:
        writer.writerow([safe_cell(cell) for cell in row])
    return _attachment(buffer.getvalue(), "text/csv; charset=utf-8", filename)


def json_response(filename: str, document: dict[str, Any]) -> HttpResponse:
    """Answer with a JSON file."""
    text = json.dumps(document, ensure_ascii=False, indent=2, default=str)
    return _attachment(text + "\n", "application/json; charset=utf-8", filename)


def _attachment(body: str, content_type: str, filename: str) -> HttpResponse:
    response = HttpResponse(body, content_type=content_type)
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    response["X-Content-Type-Options"] = "nosniff"
    return response

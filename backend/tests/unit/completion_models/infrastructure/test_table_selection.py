import json
from types import SimpleNamespace
from uuid import uuid4

import pytest

from eneo.completion_models.infrastructure.context_builder import ContextBuilder
from eneo.completion_models.infrastructure.table_selection import parse_table_selection
from eneo.files.file_models import FileType
from eneo.files.model_file_references import file_handle


def question(file_id, rows="[2,4]", sheet='"Budget"'):
    return f"> Selected rows: 2\n> (budget.xlsx, file {file_id}; sheet {sheet}, source rows {rows})\n\nCompare them."


def test_coordinates_are_forwarded_without_file_text_or_credentials(monkeypatch):
    file_id = uuid4()
    file = SimpleNamespace(
        id=file_id,
        name="budget.xlsx",
        file_type=FileType.TEXT,
        text="PRIVATE FULL WORKBOOK",
    )
    monkeypatch.setattr(
        "eneo.completion_models.infrastructure.context_builder.build_file_references_string",
        lambda *_: "",
    )
    result = ContextBuilder()._build_input(
        question(file_id),
        files=[file],
        file_reference_urls={file_id: "https://signed.invalid/?token=secret"},
    )
    assert "PRIVATE FULL WORKBOOK" not in result
    assert "secret" not in result
    reference = json.loads(
        result.split("Selected table rows (file reference for table tools):\n")[1]
    )
    assert reference == {
        "url": file_handle(file_id),
        "filename": "budget.xlsx",
        "sheet": "Budget",
        "source_rows": [2, 4],
    }


def test_a_quote_does_not_grant_file_access():
    result = ContextBuilder()._build_input(
        question(uuid4()), file_reference_urls={uuid4(): "https://unrelated.invalid"}
    )
    assert "file reference for table tools" not in result


@pytest.mark.parametrize(
    "rows", ["[]", "[1]", "[0]", "[-1]", "[2.2]", "[999999999]", json.dumps([2] * 501)]
)
def test_invalid_coordinates_do_not_create_a_selection(rows):
    assert parse_table_selection(question(uuid4(), rows)) is None


def test_round_trip_quoted_sheet_and_deduplicated_coordinates():
    selection = parse_table_selection(
        question(uuid4(), "[4,2,4]", json.dumps('Budget "2025"'))
    )
    assert selection is not None
    assert selection.sheet == 'Budget "2025"'
    assert selection.source_rows == [2, 4]


def test_only_the_opening_quote_is_a_selection():
    assert parse_table_selection("User prose\n\n" + question(uuid4())) is None

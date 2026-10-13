"""Rendering of source metadata for embeddings and prompts."""

from eneo.info_blobs.info_blob import SourceMetadataEntry
from eneo.info_blobs.source_metadata import (
    build_source_header,
    format_source_metadata_lines,
)


def _entries() -> list[SourceMetadataEntry]:
    return [
        SourceMetadataEntry(
            name="typ", label="Dokumenttyp", value="Rutin", kind="choice"
        ),
        SourceMetadataEntry(
            name="verk",
            label="Verksamhet",
            value=["Äldreomsorg", "Hemtjänst"],
            kind="choice",
        ),
        SourceMetadataEntry(
            name="giltig",
            label="Giltig till",
            value="2027-01-31T00:00:00Z",
            kind="date",
        ),
        SourceMetadataEntry(
            name="extern", label="Extern", value="true", kind="boolean"
        ),
        SourceMetadataEntry(name="tom", label="Tom", value=[""], kind="text"),
    ]


def test_lines_render_label_value_in_order_and_skip_empty_values():
    assert format_source_metadata_lines(_entries()) == [
        "Dokumenttyp: Rutin",
        "Verksamhet: Äldreomsorg, Hemtjänst",
        "Giltig till: 2027-01-31",
        "Extern: yes",
    ]


def test_header_starts_with_the_title_and_ends_with_a_blank_line():
    header = build_source_header(
        title="  Rutin larm.docx ",
        entries=_entries(),
        token_budget=1000,
        count_tokens=len,
    )

    assert header.startswith("Rutin larm.docx\nDokumenttyp: Rutin\n")
    assert header.endswith("Extern: yes\n\n")


def test_header_is_empty_without_properties():
    assert (
        build_source_header(
            title="Doc", entries=[], token_budget=1000, count_tokens=len
        )
        == ""
    )


def test_header_drops_trailing_lines_to_fit_the_budget():
    full = build_source_header(
        title="Doc", entries=_entries(), token_budget=10_000, count_tokens=len
    )
    budget = len("Doc\nDokumenttyp: Rutin\nVerksamhet: Äldreomsorg, Hemtjänst\n\n")

    header = build_source_header(
        title="Doc", entries=_entries(), token_budget=budget, count_tokens=len
    )

    assert header == "Doc\nDokumenttyp: Rutin\nVerksamhet: Äldreomsorg, Hemtjänst\n\n"
    assert len(header) < len(full)


def test_header_gives_up_when_even_the_title_does_not_fit():
    assert (
        build_source_header(
            title="Doc", entries=_entries(), token_budget=1, count_tokens=len
        )
        == ""
    )

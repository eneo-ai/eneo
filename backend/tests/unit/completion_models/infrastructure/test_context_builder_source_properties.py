"""Source properties appear with the source title in the prompt."""

from uuid import uuid4

from eneo.completion_models.infrastructure.context_builder import (
    ChunkGrouping,
    _Prompt,
    _source_header,
)
from eneo.info_blobs.info_blob import SourceMetadataEntry

ENTRIES = [
    SourceMetadataEntry(name="t", label="Dokumenttyp", value="Rutin", kind="choice"),
    SourceMetadataEntry(name="v", label="Verksamhet", value=["A", "B"], kind="choice"),
]


def test_header_without_properties_is_unchanged():
    source_id = uuid4()
    assert _source_header("Doc", source_id, []) == (
        f"source_title: Doc, source_id: {str(source_id)[:8]}"
    )


def test_header_lists_properties_on_their_own_line():
    source_id = uuid4()
    assert _source_header("Doc", source_id, ENTRIES) == (
        f"source_title: Doc, source_id: {str(source_id)[:8]}\n"
        "source_properties: Dokumenttyp: Rutin; Verksamhet: A, B"
    )


def test_information_string_carries_the_properties():
    grouping = ChunkGrouping(
        id=uuid4(),
        title="Doc",
        start_chunk=0,
        end_chunk=0,
        content="Body",
        chunk_count=1,
        source_metadata=ENTRIES,
    )
    rendered = _Prompt._create_information_string([grouping])
    assert "source_properties: Dokumenttyp: Rutin; Verksamhet: A, B\nBody" in rendered

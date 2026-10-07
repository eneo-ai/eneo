"""Source properties appear with the source title in the prompt."""

from dataclasses import dataclass, field
from uuid import UUID, uuid4

import pytest

from eneo.completion_models.infrastructure.context_builder import (
    ChunkGrouping,
    _Prompt,
    _source_header,
)
from eneo.info_blobs.info_blob import SourceMetadataEntry
from eneo.tokens.token_utils import count_tokens

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


@dataclass
class RetrievedChunk:
    text: str
    chunk_no: int
    info_blob_id: UUID
    info_blob_title: str = "Policy"
    info_blob_source_metadata: list[SourceMetadataEntry] = field(default_factory=list)


@pytest.mark.parametrize("version", [1, 2])
def test_separate_passages_obey_the_actual_rendered_context_budget(version: int):
    source_id = uuid4()
    properties = [
        SourceMetadataEntry(
            name="t", label="Topics", value=" ".join(f"topic{i}" for i in range(100))
        )
    ]
    first = RetrievedChunk(
        "First passage.", 0, source_id, info_blob_source_metadata=properties
    )
    distant = RetrievedChunk(
        "A distant passage.", 5, source_id, info_blob_source_metadata=properties
    )
    prompt = _Prompt(version=version)
    single = _Prompt(version=version)
    single.add_knowledge([first], max_tokens=10_000)
    budget = count_tokens(single.knowledge or "") + count_tokens(distant.text)

    prompt.add_knowledge([first, distant], max_tokens=budget)

    assert count_tokens(prompt.knowledge or "") <= budget
    assert prompt.get_tokens_of_knowledge() == count_tokens(prompt.knowledge or "")
    if version == 2:
        assert prompt.knowledge == single.knowledge
        assert "A distant passage." not in (prompt.knowledge or "")


def test_adjacent_passages_share_one_header_and_budget_the_joined_text():
    source_id = uuid4()
    chunks = [
        RetrievedChunk(
            "Start and shared", 0, source_id, info_blob_source_metadata=ENTRIES
        ),
        RetrievedChunk(
            "shared ending", 1, source_id, info_blob_source_metadata=ENTRIES
        ),
    ]
    full = _Prompt(version=2)
    full.add_knowledge(chunks, max_tokens=10_000)
    expected = full.knowledge or ""
    prompt = _Prompt(version=2)

    prompt.add_knowledge(chunks, max_tokens=count_tokens(expected))

    assert prompt.knowledge == expected
    assert expected.count("source_properties:") == 1
    assert "Start and shared ending" in expected
    assert prompt.get_tokens_of_knowledge() == count_tokens(expected)

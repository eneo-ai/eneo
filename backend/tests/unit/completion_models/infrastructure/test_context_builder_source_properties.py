"""Source properties appear with the source title in the prompt."""

from dataclasses import dataclass, field
from uuid import UUID, uuid4

import pytest

from eneo.completion_models.infrastructure import context_builder
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


def test_large_candidate_sets_do_not_retokenize_every_rendered_prefix(monkeypatch):
    processed_characters = 0

    def measured_count(text: str, model_name: str = "") -> int:
        nonlocal processed_characters
        processed_characters += len(text)
        return count_tokens(text, model_name)

    monkeypatch.setattr(context_builder, "count_tokens", measured_count)
    source_id = uuid4()
    chunks = [RetrievedChunk(f"word{i} ", i, source_id) for i in range(600)]
    prompt = _Prompt(version=2)

    prompt.add_knowledge(chunks, max_tokens=100_000)

    rendered = prompt.knowledge or ""
    assert "word0 " in rendered and "word599 " in rendered
    assert prompt.get_tokens_of_knowledge() == count_tokens(rendered)
    # Measure real tokenizer input volume, rather than elapsed time or private
    # helper calls: work remains proportional to the accepted text volume.
    assert processed_characters < 10 * sum(len(chunk.text) for chunk in chunks)


def test_many_overlapping_chunks_fit_an_exact_budget_without_quadratic_tokenization(
    monkeypatch,
):
    source_id = uuid4()
    words = [f"word{i}" for i in range(4802)]
    chunks = [
        RetrievedChunk(" ".join(words[8 * i : 8 * i + 10]), i, source_id)
        for i in range(600)
    ]
    full = _Prompt(version=2)
    full.add_knowledge(chunks, max_tokens=100_000)
    processed_characters = 0

    def measured_count(text: str, model_name: str = "") -> int:
        nonlocal processed_characters
        processed_characters += len(text)
        return count_tokens(text, model_name)

    monkeypatch.setattr(context_builder, "count_tokens", measured_count)
    prompt = _Prompt(version=2)

    prompt.add_knowledge(chunks, max_tokens=full.get_tokens_of_knowledge())

    assert prompt.knowledge == full.knowledge
    assert prompt.get_tokens_of_knowledge() == count_tokens(prompt.knowledge or "")
    assert processed_characters < 20 * sum(len(chunk.text) for chunk in chunks)


@pytest.mark.parametrize("version", [1, 2])
def test_a_passage_that_does_not_fit_does_not_block_smaller_ones_after_it(
    version: int,
):
    first = RetrievedChunk("First passage.", 0, uuid4())
    large = RetrievedChunk(" ".join(f"word{i}" for i in range(200)), 0, uuid4())
    third = RetrievedChunk("Third passage.", 0, uuid4())
    expected = _Prompt(version=version)
    expected.add_knowledge([first, third], max_tokens=10_000)
    # Room to spare for the small passages, far from enough for the large one.
    # Once a rendering has shown an overflow, later passages are admitted on
    # the conservative estimate alone, so an exact budget would be too tight.
    budget = count_tokens(expected.knowledge or "") + count_tokens(large.text) // 2
    prompt = _Prompt(version=version)

    prompt.add_knowledge([first, large, third], max_tokens=budget)

    assert prompt.knowledge == expected.knowledge
    assert "word0" not in (prompt.knowledge or "")
    assert prompt.get_tokens_of_knowledge() == count_tokens(prompt.knowledge or "")


def test_equal_passages_fill_the_budget_in_ranking_order():
    chunks = [RetrievedChunk(f"Passage number {i}.", 0, uuid4()) for i in range(6)]
    expected = _Prompt(version=2)
    expected.add_knowledge(chunks[:3], max_tokens=10_000)
    prompt = _Prompt(version=2)

    prompt.add_knowledge(chunks, max_tokens=count_tokens(expected.knowledge or ""))

    assert prompt.knowledge == expected.knowledge


def test_rejected_candidates_do_not_rerender_the_selection(monkeypatch):
    chunks = [RetrievedChunk(f"Passage number {i}.", 0, uuid4()) for i in range(600)]
    expected = _Prompt(version=2)
    expected.add_knowledge(chunks[:50], max_tokens=100_000)
    processed_characters = 0

    def measured_count(text: str, model_name: str = "") -> int:
        nonlocal processed_characters
        processed_characters += len(text)
        return count_tokens(text, model_name)

    monkeypatch.setattr(context_builder, "count_tokens", measured_count)
    prompt = _Prompt(version=2)

    prompt.add_knowledge(chunks, max_tokens=count_tokens(expected.knowledge or ""))

    assert prompt.knowledge == expected.knowledge
    # Every candidate is estimated once; the selection is rendered at the
    # boundary, not once per rejected candidate.
    assert processed_characters < 10 * sum(
        len(chunk.text)
        + len(_source_header(chunk.info_blob_title, chunk.info_blob_id, []))
        for chunk in chunks
    )


def test_adjacent_passages_after_an_overflow_still_fill_an_exact_budget():
    source_id = uuid4()
    words = [f"word{i}" for i in range(40)]
    adjacent = [
        RetrievedChunk(" ".join(words[8 * i : 8 * i + 10]), i, source_id)
        for i in range(3)
    ]
    large = RetrievedChunk(" ".join(f"other{i}" for i in range(200)), 0, uuid4())
    expected = _Prompt(version=2)
    expected.add_knowledge(adjacent, max_tokens=10_000)
    prompt = _Prompt(version=2)

    prompt.add_knowledge(
        [adjacent[0], large, adjacent[1], adjacent[2]],
        max_tokens=count_tokens(expected.knowledge or ""),
    )

    # The overlap between the second and third passage is only credited by a
    # rendering; the overflow on the large passage must not switch it off.
    assert prompt.knowledge == expected.knowledge

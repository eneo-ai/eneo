from __future__ import annotations

from copy import deepcopy
from typing import Any
from uuid import uuid4

import pytest
from pydantic import ValidationError

from eneo.flows.domain.rag_evidence import (
    RetrievedKnowledgeEvidence,
    RetrievedPassage,
    RetrievedSource,
    apply_passage_disclosure,
)
from eneo.flows.domain.rag_evidence_policy import FlowRagEvidencePolicy
from eneo.flows.runtime.rag_metadata import (
    build_chunk_snippet,
    build_retrieved_knowledge_evidence,
)
from tests.fixtures import retrieved_info_blob_chunk


def _policy(**overrides: int) -> FlowRagEvidencePolicy:
    defaults: dict[str, int] = {
        "max_sources_with_recorded_passages": 25,
        "max_recorded_passages_per_source": 5,
        "max_recorded_passage_bytes": 4096,
        "max_recorded_passage_bytes_per_step": 131072,
    }
    defaults.update(overrides)
    return FlowRagEvidencePolicy(**defaults)


def test_build_chunk_snippet_uses_interior_slice_for_long_text():
    text = "a" * 100 + "MIDDLE" + "b" * 120
    snippet = build_chunk_snippet(text, max_chars=40)

    assert len(snippet) == 40
    assert "MIDDLE" in snippet


def test_recorded_passage_holds_the_exact_retrieved_text() -> None:
    source_id = uuid4()
    passage_text = (
        "Nämnden beslutade att bevilja ansökan med hänvisning till 4 kap. 1 § "
        "socialtjänstlagen, eftersom behovet inte kunde tillgodoses på annat sätt."
    )
    evidence = build_retrieved_knowledge_evidence(
        [
            retrieved_info_blob_chunk(
                info_blob_id=source_id,
                info_blob_title="Beslutsunderlag",
                chunk_no=7,
                text=passage_text,
                score=0.81,
            )
        ],
        policy=_policy(),
    )

    passage = evidence.sources[0].passages[0]
    assert passage.text == passage_text
    assert passage.recording == "complete"
    assert passage.chunk_no == 7
    assert passage.passage_bytes == passage.recorded_bytes
    assert evidence.passages_truncated == 0
    assert evidence.recorded_passage_bytes == passage.recorded_bytes


def test_passage_beyond_the_byte_bound_records_what_was_dropped() -> None:
    source_id = uuid4()
    passage_text = "å" * 400  # two bytes per character
    evidence = build_retrieved_knowledge_evidence(
        [
            retrieved_info_blob_chunk(
                info_blob_id=source_id,
                info_blob_title="Lång källa",
                chunk_no=1,
                text=passage_text,
                score=0.5,
            )
        ],
        policy=_policy(max_recorded_passage_bytes=101),
    )

    passage = evidence.sources[0].passages[0]
    assert passage.recording == "tail_truncated"
    assert passage.passage_bytes == 800
    assert passage.recorded_bytes == 100  # the split multi-byte character is dropped
    assert passage.dropped_bytes == 700
    assert passage_text.startswith(passage.text)
    assert evidence.passages_truncated == 1


def test_every_retrieved_source_is_listed_even_beyond_the_detail_bound() -> None:
    chunks = [
        retrieved_info_blob_chunk(
            info_blob_id=uuid4(),
            info_blob_title=f"Källa {index}",
            chunk_no=1,
            text=f"innehåll {index}",
            score=0.9 - index * 0.01,
        )
        for index in range(6)
    ]

    evidence = build_retrieved_knowledge_evidence(
        chunks,
        policy=_policy(max_sources_with_recorded_passages=2),
    )

    assert len(evidence.sources) == 6
    assert evidence.sources_with_recorded_passages == 2
    assert all(source.title is not None for source in evidence.sources)
    assert [len(source.passages) for source in evidence.sources] == [1, 1, 0, 0, 0, 0]
    assert all(source.matched_chunk_count == 1 for source in evidence.sources)
    assert [source.recorded_passage_count for source in evidence.sources[2:]] == [
        0,
        0,
        0,
        0,
    ]


def test_per_source_passage_bound_keeps_the_highest_scoring_passages() -> None:
    source_id = uuid4()
    chunks = [
        retrieved_info_blob_chunk(
            info_blob_id=source_id,
            info_blob_title="Källa",
            chunk_no=index,
            text=f"stycke {index}",
            score=index / 10,
        )
        for index in range(1, 5)
    ]

    evidence = build_retrieved_knowledge_evidence(
        chunks,
        policy=_policy(max_recorded_passages_per_source=2),
    )

    source = evidence.sources[0]
    assert source.matched_chunk_count == 4
    assert source.recorded_passage_count == 2
    assert [passage.chunk_no for passage in source.passages] == [4, 3]
    assert evidence.passages_recorded == 2


def test_identical_passages_in_one_document_are_recorded_separately() -> None:
    source_id = uuid4()
    repeated = "Samma stycke förekommer två gånger i dokumentet."
    chunks = [
        retrieved_info_blob_chunk(
            info_blob_id=source_id,
            info_blob_title="Dubblett",
            chunk_no=chunk_no,
            text=repeated,
            score=0.7,
        )
        for chunk_no in (3, 11)
    ]

    evidence = build_retrieved_knowledge_evidence(chunks, policy=_policy())

    source = evidence.sources[0]
    assert source.matched_chunk_count == 2
    assert source.recorded_passage_count == 2
    assert [passage.text for passage in source.passages] == [repeated, repeated]
    assert [passage.chunk_no for passage in source.passages] == [3, 11]


def test_step_byte_budget_stops_recording_without_leaving_a_fragment() -> None:
    chunks = [
        retrieved_info_blob_chunk(
            info_blob_id=uuid4(),
            info_blob_title=f"Källa {index}",
            chunk_no=1,
            text="x" * 300,
            score=0.9,
        )
        for index in range(4)
    ]

    evidence = build_retrieved_knowledge_evidence(
        chunks,
        policy=_policy(
            max_recorded_passage_bytes=300,
            max_recorded_passage_bytes_per_step=650,
        ),
    )

    # The budget is spent to the byte: the third source truncates into what is
    # left rather than wasting it, and the fourth records no passage at all.
    assert len(evidence.sources) == 4
    assert evidence.sources_with_recorded_passages == 3
    assert evidence.recorded_passage_bytes == 650
    assert [
        [passage.recording for passage in source.passages]
        for source in evidence.sources
    ] == [["complete"], ["complete"], ["tail_truncated"], []]
    assert evidence.passages_truncated == 1


def test_zero_retrieved_chunks_yields_empty_evidence() -> None:
    evidence = build_retrieved_knowledge_evidence([], policy=_policy())

    assert evidence.sources == []
    assert evidence.sources_with_recorded_passages == 0
    assert evidence.passages_recorded == 0
    assert evidence.recorded_passage_bytes == 0
    assert evidence.write_into({})["references"] == []


def test_source_metadata_enriches_the_recorded_source() -> None:
    source_id = uuid4()
    evidence = build_retrieved_knowledge_evidence(
        [
            retrieved_info_blob_chunk(
                info_blob_id=source_id,
                info_blob_title="https://kunskap.example.se/beslut/underlag",
                chunk_no=1,
                text="relevant stycke",
                score=0.82,
            )
        ],
        source_metadata_by_id={
            str(source_id): {
                "source_title": "Beslut till underlag",
                "source_url": "https://kunskap.example.se/beslut/underlag",
                "source_kind": "website",
                "source_container_kind": "website",
                "source_container_name": "Kunskapsbanken",
                "source_container_id": "website-1",
            }
        },
        policy=_policy(),
    )

    source = evidence.sources[0]
    assert source.title == "Beslut till underlag"
    assert source.source_title == "Beslut till underlag"
    assert source.source_url == "https://kunskap.example.se/beslut/underlag"
    assert source.source_kind == "website"
    assert source.source_container_name == "Kunskapsbanken"
    assert source.source_container_name_raw == "Kunskapsbanken"
    assert source.source_container_label == "Kunskapsbanken"
    assert source.usage_state == "retrieved_candidate"


def test_display_selection_prefers_the_highest_signal_passage() -> None:
    source_id = uuid4()
    evidence = build_retrieved_knowledge_evidence(
        [
            retrieved_info_blob_chunk(
                info_blob_id=source_id,
                info_blob_title="https://kunskap.example.se/navigation",
                chunk_no=1,
                text="Hem > Psykologi > Beslut\nMeny\nKontakt\nLogga in\nCookies\n",
                score=0.95,
            ),
            retrieved_info_blob_chunk(
                info_blob_id=source_id,
                info_blob_title="https://kunskap.example.se/beslut/underlag",
                chunk_no=2,
                text=(
                    "Detta underlag beskriver hur beslut till underlag utformas i "
                    "praktiken. Texten fokuserar pa hur professionella bedomningar "
                    "dokumenteras, vilka kriterier som galler och hur slutsatser "
                    "ska motiveras."
                ),
                score=0.74,
            ),
        ],
        policy=_policy(),
    )

    source = evidence.sources[0]
    assert source.display_chunk_no == 2
    assert source.display_selection_reason == "highest_signal_chunk"
    assert source.display_snippet is not None
    assert "professionella bedomningar" in source.display_snippet
    assert source.snippet_quality in {"high", "medium"}
    assert isinstance(source.boilerplate_likelihood, float)


def test_display_selection_can_reach_a_passage_beyond_the_recorded_bound() -> None:
    source_id = uuid4()
    chunks = [
        retrieved_info_blob_chunk(
            info_blob_id=source_id,
            info_blob_title="https://kunskap.example.se/navigation",
            chunk_no=index,
            text="Hem\nMeny\nKontakt\nLogga in\nCookies",
            score=0.99 - (index * 0.01),
        )
        for index in range(1, 6)
    ]
    chunks.append(
        retrieved_info_blob_chunk(
            info_blob_id=source_id,
            info_blob_title="https://kunskap.example.se/beslut/underlag",
            chunk_no=6,
            text=(
                "Detta underlag beskriver hur beslut dokumenteras i praktiken. "
                "Texten forklarar vilka kriterier som ska vaxas samman, hur "
                "bedomningen kan motiveras och vilka fragor som bor foljas upp."
            ),
            score=0.72,
        )
    )

    evidence = build_retrieved_knowledge_evidence(
        chunks,
        policy=_policy(max_recorded_passages_per_source=2),
    )

    source = evidence.sources[0]
    assert source.matched_chunk_count == 6
    assert source.recorded_passage_count == 2
    assert source.display_chunk_no == 6


def test_source_payloads_omit_absent_metadata_but_keep_counts() -> None:
    source_id = uuid4()
    evidence = build_retrieved_knowledge_evidence(
        [
            retrieved_info_blob_chunk(
                info_blob_id=source_id,
                info_blob_title=None,
                chunk_no=1,
                text="stycke",
                score=0.4,
            )
        ],
        policy=_policy(),
    )

    payload = evidence.write_into({})["references"][0]
    assert payload["id"] == str(source_id)
    assert payload["id_short"] == str(source_id)[:8]
    assert payload["matched_chunk_count"] == 1
    assert payload["recorded_passage_count"] == 1
    assert payload["passages"][0]["text"] == "stycke"
    assert "source_url" not in payload
    assert "title" not in payload


def test_multibyte_leading_characters_are_never_recorded_half() -> None:
    """A bound that cannot hold one code point records nothing, not an empty text."""
    for character, size in (("å", 2), ("€", 3), ("𝄞", 4)):
        for max_bytes in range(1, size):
            assert (
                RetrievedPassage.record(
                    chunk_no=1,
                    score=0.5,
                    retrieved_text=character * 4,
                    max_bytes=max_bytes,
                )
                is None
            )
        recorded = RetrievedPassage.record(
            chunk_no=1,
            score=0.5,
            retrieved_text=character * 4,
            max_bytes=size,
        )
        assert recorded is not None
        assert recorded.text == character
        assert recorded.recorded_bytes == size
        assert recorded.recording == "tail_truncated"


def test_a_large_candidate_does_not_hide_a_smaller_recordable_one() -> None:
    source_id = uuid4()
    chunks = [
        retrieved_info_blob_chunk(
            info_blob_id=source_id,
            info_blob_title="Källa",
            chunk_no=1,
            text="x" * 400,
            score=0.9,
        ),
        retrieved_info_blob_chunk(
            info_blob_id=source_id,
            info_blob_title="Källa",
            chunk_no=2,
            text="y" * 40,
            score=0.8,
        ),
    ]

    evidence = build_retrieved_knowledge_evidence(
        chunks,
        policy=_policy(
            max_recorded_passage_bytes=100,
            max_recorded_passage_bytes_per_step=140,
        ),
    )

    source = evidence.sources[0]
    assert [passage.chunk_no for passage in source.passages] == [1, 2]
    assert source.passages[0].recording == "tail_truncated"
    assert source.passages[0].recorded_bytes == 100
    assert source.passages[1].recording == "complete"
    assert source.passages[1].text == "y" * 40
    assert evidence.recorded_passage_bytes == 140


def test_counters_cannot_disagree_with_recorded_passages() -> None:
    source_id = uuid4()
    evidence = build_retrieved_knowledge_evidence(
        [
            retrieved_info_blob_chunk(
                info_blob_id=source_id,
                info_blob_title="Källa",
                chunk_no=1,
                text="stycke",
                score=0.5,
            )
        ],
        policy=_policy(),
    )

    with pytest.raises(ValidationError):
        evidence.sources[0].model_copy(
            update={"recorded_passage_count": 5}
        ).model_validate(
            evidence.sources[0].model_dump() | {"recorded_passage_count": 5}
        )

    round_tripped = RetrievedKnowledgeEvidence.from_payload(
        evidence.write_into({}) | {"passages_recorded": 99}
    )
    assert round_tripped.passages_recorded == 1


def _evidence_payload_with_passage(
    text: str = "Beslutet grundas pa 4 kap. 1 SoL.",
) -> dict[str, Any]:
    evidence = RetrievedKnowledgeEvidence(
        sources=[
            RetrievedSource(
                id="source-1",
                id_short="source-1",
                title="Beslutsunderlag",
                matched_chunk_count=3,
                recorded_passage_count=1,
                best_score=0.82,
                passages=[
                    RetrievedPassage.record(
                        chunk_no=4,
                        score=0.82,
                        retrieved_text=text,
                        max_bytes=4096,
                    )
                ],
            )
        ]
    )
    return evidence.write_into({"status": "success", "unique_sources": 1})


def test_withholding_hides_passage_text_but_never_source_identity() -> None:
    payload = _evidence_payload_with_passage()

    withheld = apply_passage_disclosure(
        deepcopy(payload), disclosure="text_withheld_sensitive_flow"
    )

    reference = withheld["references"][0]
    assert reference["id"] == "source-1"
    assert reference["title"] == "Beslutsunderlag"
    assert reference["matched_chunk_count"] == 3
    assert reference["recorded_passage_count"] == 1
    passage = reference["passages"][0]
    assert passage["text"] is None
    assert passage["disclosure"] == "text_withheld_sensitive_flow"
    assert passage["chunk_no"] == 4
    # The size stays visible: a reader must be able to tell that a passage
    # exists and is not shown, which is not the same as no passage.
    assert passage["recorded_bytes"] > 0
    assert withheld["passages_recorded"] == 1
    assert withheld["passages_withheld"] == 1


def test_a_withheld_passage_is_distinguishable_from_an_unrecorded_one() -> None:
    withheld = apply_passage_disclosure(
        _evidence_payload_with_passage(),
        disclosure="text_withheld_classified_space",
    )
    unrecorded = RetrievedKnowledgeEvidence(
        sources=[
            RetrievedSource(
                id="source-1",
                id_short="source-1",
                title="Beslutsunderlag",
                matched_chunk_count=3,
                recorded_passage_count=0,
                best_score=0.82,
                passages=[],
            )
        ]
    ).write_into({})

    assert withheld["references"][0]["passages"][0]["disclosure"] == (
        "text_withheld_classified_space"
    )
    assert withheld["passages_withheld"] == 1
    assert unrecorded["references"][0]["passages"] == []
    assert unrecorded["passages_withheld"] == 0
    assert unrecorded["passages_recorded"] == 0


def test_withholding_reaches_mapped_per_call_payloads() -> None:
    call = _evidence_payload_with_passage()
    mapped = {"execution_mode": "per_item", "items": [call]}

    withheld = apply_passage_disclosure(
        mapped, disclosure="text_withheld_sensitive_flow"
    )

    passage = withheld["items"][0]["references"][0]["passages"][0]
    assert passage["text"] is None
    assert passage["disclosure"] == "text_withheld_sensitive_flow"
    assert withheld["items"][0]["references"][0]["id"] == "source-1"


def test_disclosed_payload_is_returned_untouched() -> None:
    payload = _evidence_payload_with_passage()

    assert apply_passage_disclosure(payload, disclosure="text_disclosed") == payload
    assert payload["references"][0]["passages"][0]["text"] is not None

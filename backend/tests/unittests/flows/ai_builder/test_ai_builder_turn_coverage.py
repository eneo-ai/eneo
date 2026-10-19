"""One turn's coverage: what its sent model requests left out of the user's material."""

from __future__ import annotations

import pytest

from eneo.flows.ai_builder.ai_builder_conversation_metadata import (
    turn_coverage_from_metadata,
)
from eneo.flows.ai_builder.ai_builder_discovery_runtime import (
    build_slot_classification_input,
)
from eneo.flows.ai_builder.ai_builder_domain_models import ConversationMessage
from eneo.flows.ai_builder.ai_builder_slot_classification_contract import (
    SlotClassificationInput,
    SlotClassificationSource,
    SlotClassificationSourceKind,
)
from eneo.flows.ai_builder.ai_builder_turn_coverage import (
    ProposalPromptCut,
    TurnCoverageRecorder,
    classification_sources_note,
)

_HISTORY = {
    "kind": "count",
    "stage": "proposal",
    "material": "history_messages",
    "shortened": 0,
}


@pytest.mark.parametrize(
    ("cut", "calls", "notes"),
    [
        # Mutant: the sum (8 of 6) or the last call (3) instead of the worst
        # call: two groups evicted while preparing, three more by one call.
        (
            ProposalPromptCut(history_groups_left_out=2),
            [(4, 1), (4, 3)],
            [{**_HISTORY, "total": 6, "omitted": 5, "reasons": ["model_room"]}],
        ),
        # Mutant: a prepared request that was never sent counts.
        (ProposalPromptCut(history_groups_left_out=2, confirmed_assumptions=3), [], []),
        # Mutant: a material with nothing left out still gets a note.
        (
            ProposalPromptCut(confirmed_assumptions=5, replayed_assumptions=2),
            [(1, 1)],
            [
                {
                    "kind": "count",
                    "stage": "proposal",
                    "material": "requirement_assumptions",
                    "total": 5,
                    "omitted": 3,
                    "shortened": 0,
                    "reasons": ["model_room"],
                }
            ],
        ),
    ],
    ids=["worst_call", "never_sent", "assumptions_only"],
)
def test_the_summary_holds_the_worst_sent_proposal_call(
    cut: ProposalPromptCut,
    calls: list[tuple[int, int]],
    notes: list[dict[str, object]],
) -> None:
    recorder = TurnCoverageRecorder()
    recorder.prepare_proposal(cut)
    for in_request, sent in calls:
        recorder.record_proposal_call(history_in_request=in_request, history_sent=sent)

    summary = recorder.summary()

    # Mutant: a turn that left nothing out stores an empty summary.
    assert (
        summary.model_dump(mode="json")["notes"] if summary is not None else None
    ) == (notes or None)


def _source(
    kind: SlotClassificationSourceKind, key: str, text: str, *, truncated: bool = False
) -> SlotClassificationSource:
    return SlotClassificationSource(
        source_id=f"{kind}:{key}",
        kind=kind,
        text=text,
        message_id=None if kind == "uploaded_file" else key,
        truncated=truncated,
    )


_CURRENT = _source("user_message", "now", "Bygg flödet.")
_OLDER = _source("user_message", "old", "Ett äldre och längre meddelande.")
_CAPPED = _source("structured_answer", "a", "x" * 500, truncated=True)
_UPLOAD = _source("uploaded_file", "f", "fil")


@pytest.mark.parametrize(
    ("offered", "admitted", "expected"),
    [
        # Mutant: shortening that drops nothing is silent.
        (
            (_OLDER, _CURRENT),
            (_source("user_message", "old", "Ett äldre"), _CURRENT),
            {"total": 2, "omitted": 0, "shortened": 1, "reasons": ["model_room"]},
        ),
        # Mutant: a source the fixed limit cut and the fit then dropped counts
        # twice, or under the limit's reason.
        (
            (_CAPPED, _CURRENT),
            (_CURRENT,),
            {"total": 2, "omitted": 1, "shortened": 0, "reasons": ["model_room"]},
        ),
        (
            (_CAPPED, _OLDER, _CURRENT),
            (_CAPPED, _source("user_message", "old", "Ett"), _CURRENT),
            {
                "total": 3,
                "omitted": 0,
                "shortened": 2,
                "reasons": ["model_room", "fixed_limit"],
            },
        ),
        # Attached files have their own coverage and are not counted here.
        ((_UPLOAD, _CURRENT), (_CURRENT,), None),
    ],
    ids=["fit_shortens", "fit_drops_capped", "both_reasons", "upload_only"],
)
def test_the_reading_note_counts_each_transcript_source_once(
    offered: tuple[SlotClassificationSource, ...],
    admitted: tuple[SlotClassificationSource, ...],
    expected: dict[str, object] | None,
) -> None:
    note = classification_sources_note(
        offered=SlotClassificationInput(sources=offered),
        admitted=SlotClassificationInput(sources=admitted),
    )

    assert (note.model_dump(mode="json") if note else None) == (
        None
        if expected is None
        else {
            "kind": "count",
            "stage": "classification",
            "material": "classification_sources",
            **expected,
        }
    )


def test_the_fixed_source_limit_counts_the_oldest_sources_it_left_out() -> None:
    conversation = [
        ConversationMessage(role="user", content=f"Meddelande {index}")
        for index in range(125)
    ]
    built = build_slot_classification_input(conversation, None)

    note = classification_sources_note(offered=built, admitted=built)

    # Mutant: the limit drops the oldest sources and records nothing.
    assert note is not None
    assert note.model_dump(mode="json") == {
        "kind": "count",
        "stage": "classification",
        "material": "classification_sources",
        "total": 125,
        "omitted": 5,
        "shortened": 0,
        "reasons": ["fixed_limit"],
    }


def test_a_note_stored_before_note_kinds_reads_as_a_count_note() -> None:
    stored = {
        "stage": "proposal",
        "material": "history_messages",
        "total": 3,
        "omitted": 2,
        "shortened": 0,
        "reasons": ["model_room"],
    }

    coverage = turn_coverage_from_metadata(
        {"turn_coverage": {"schema_version": 1, "notes": [stored]}}
    )

    # Mutant: the kind is required, so an older turn loses its line.
    assert coverage is not None
    assert coverage.model_dump(mode="json")["notes"] == [{"kind": "count", **stored}]

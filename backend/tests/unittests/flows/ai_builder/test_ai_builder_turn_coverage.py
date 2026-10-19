"""One turn's coverage: what its sent model requests left out of the user's material."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest

from eneo.completion_models.domain.model_capacity import ModelCapacity
from eneo.files.file_models import FileType
from eneo.flows.ai_builder.ai_builder_attachment_context import (
    AIBuilderAttachmentEvidence,
)
from eneo.flows.ai_builder.ai_builder_conversation_metadata import (
    turn_coverage_from_metadata,
)
from eneo.flows.ai_builder.ai_builder_discovery_runtime import (
    build_slot_classification_input,
)
from eneo.flows.ai_builder.ai_builder_domain_models import ConversationMessage
from eneo.flows.ai_builder.ai_builder_settings import (
    AIBuilderPlannedRequestBudget,
    AIBuilderRequestBudget,
)
from eneo.flows.ai_builder.ai_builder_slot_classification_contract import (
    SlotClassificationInput,
    SlotClassificationSource,
    SlotClassificationSourceKind,
)
from eneo.flows.ai_builder.ai_builder_tool_catalog import (
    TOOL_CATALOG_OVERVIEW_MAX_CHARS,
    TOOL_CATALOG_SCHEMA_MAX_CHARS,
    TOOL_CATALOG_UNAVAILABLE_MAX_CHARS,
    AIBuilderToolCatalogProjection,
    fit_tool_catalog_projection,
)
from eneo.flows.ai_builder.ai_builder_turn_coverage import (
    CoverageNote,
    ProposalPromptCut,
    TurnCoverageRecorder,
    classification_notes,
    classification_sources_note,
    requirement_assumptions_note,
    tool_catalog_notes,
)
from eneo.flows.ai_builder.planning_state import AttachmentCoverage
from eneo.mcp_servers.application.unattended_tool_use import UnattendedToolRefusal
from tests.unittests.flows.ai_builder.test_ai_builder_tool_catalog import (
    _option,
    _schema_of_length,
    _tools,
)

if TYPE_CHECKING:
    from eneo.flows.ai_builder.ai_builder_turn_coverage import RoomReason

_HISTORY = {
    "kind": "count",
    "stage": "proposal",
    "material": "history_messages",
    "shortened": 0,
}
_ASSUMPTIONS = {**_HISTORY, "material": "requirement_assumptions"}


def _file(*, readable: bool = True) -> AIBuilderAttachmentEvidence:
    return AIBuilderAttachmentEvidence(
        file_id=uuid4(),
        filename="bilaga.txt",
        file_type=FileType.TEXT,
        mimetype="text/plain",
        has_readable_text=readable,
        excerpt=None,
        coverage="inventory_only",
    )


# The adversary's numbers: a 100k window, 32k output ceiling, 1k safety, half
# the room for the answer, a 70k review-evidence input cap. The cap does not
# bind the first call (10k protected), it binds a repair with 50k protected.
_BUDGET = AIBuilderRequestBudget(
    capacity=ModelCapacity(100_000, 32_000),
    safety_buffer_tokens=1_000,
    answer_reserve_share=0.5,
    timeout_seconds=30.0,
    input_cap_tokens=70_000,
)
_FIRST = _BUDGET.plan(required_input_tokens=10_000)
_REPAIR = _BUDGET.plan(required_input_tokens=50_000)


def _cut(*notes: CoverageNote | None, history: int = 0) -> ProposalPromptCut:
    return ProposalPromptCut(
        history_groups_left_out=history,
        notes=tuple(note for note in notes if note is not None),
    )


@pytest.mark.parametrize(
    ("steps", "room", "notes"),
    [
        # Mutant: the sum (8 of 6) or the last call (3) instead of the worst
        # call: two groups evicted while preparing, three more by one call.
        (
            [(_cut(history=2), [(4, 1, _FIRST), (4, 3, _FIRST)])],
            "model_room",
            [{**_HISTORY, "total": 6, "omitted": 5, "reasons": ["model_room"]}],
        ),
        # Mutant: a prepared request that was never sent counts.
        (
            [
                (
                    _cut(
                        requirement_assumptions_note(confirmed=3, replayed=0),
                        history=2,
                    ),
                    [],
                )
            ],
            "model_room",
            [],
        ),
        # Mutants: a request whose room the organisation's input cap set
        # names the model's room, for the history or the prompt's notes.
        (
            [
                (
                    _cut(
                        requirement_assumptions_note(confirmed=5, replayed=2),
                        history=2,
                    ),
                    [(1, 1, _REPAIR)],
                )
            ],
            "configured_limit",
            [
                {**_HISTORY, "total": 3, "omitted": 2, "reasons": ["configured_limit"]},
                {
                    **_ASSUMPTIONS,
                    "total": 5,
                    "omitted": 3,
                    "reasons": ["configured_limit"],
                },
            ],
        ),
        # Mutant: a continuation's prompt replaces the worse one an earlier
        # call was sent with, or the two are added up.
        (
            [
                (
                    _cut(requirement_assumptions_note(confirmed=5, replayed=1)),
                    [(0, 0, _FIRST)],
                ),
                (
                    _cut(requirement_assumptions_note(confirmed=5, replayed=3)),
                    [(0, 0, _FIRST)],
                ),
            ],
            "model_room",
            [{**_ASSUMPTIONS, "total": 5, "omitted": 4, "reasons": ["model_room"]}],
        ),
        # Mutants: a repair whose own plan the input cap bound names the
        # model's room for the history it evicted, or the prompt the
        # preparation packed takes the repair's room.
        (
            [
                (
                    _cut(requirement_assumptions_note(confirmed=5, replayed=2)),
                    [(4, 1, _REPAIR)],
                )
            ],
            "model_room",
            [
                {**_HISTORY, "total": 4, "omitted": 3, "reasons": ["configured_limit"]},
                {**_ASSUMPTIONS, "total": 5, "omitted": 3, "reasons": ["model_room"]},
            ],
        ),
    ],
    ids=[
        "worst_call",
        "never_sent",
        "organisation_room",
        "worst_prompt",
        "repair_room",
    ],
)
def test_the_summary_holds_the_worst_sent_proposal_call(
    steps: list[
        tuple[ProposalPromptCut, list[tuple[int, int, AIBuilderPlannedRequestBudget]]]
    ],
    room: RoomReason,
    notes: list[dict[str, object]],
) -> None:
    recorder = TurnCoverageRecorder()
    for cut, calls in steps:
        recorder.prepare_proposal(replace(cut, room=room))
        for in_request, sent, budget in calls:
            recorder.record_proposal_call(
                history_in_request=in_request,
                history_sent=sent,
                request_budget=budget,
            )

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


def test_a_stored_record_keeps_the_notes_this_release_reads() -> None:
    stored = {
        "stage": "proposal",
        "material": "history_messages",
        "total": 3,
        "omitted": 2,
        "shortened": 0,
        "reasons": ["model_room"],
    }
    later = [
        {**stored, "kind": "count", "material": "a_later_material"},
        {"kind": "a_later_kind", "stage": "proposal"},
    ]

    unlisted = {
        "kind": "tool_catalog_unavailable",
        "stage": "proposal",
        "material": "tool_catalog",
        "reason": "catalog_limit",
    }

    coverage = turn_coverage_from_metadata(
        {"turn_coverage": {"schema_version": 1, "notes": [stored, *later, unlisted]}}
    )

    # Mutants: the kind is required, so an older turn loses its line; a note
    # another release wrote drops the whole record; the unlisted catalogue
    # does not read.
    assert coverage is not None
    assert coverage.model_dump(mode="json")["notes"] == [
        {"kind": "count", **stored},
        unlisted,
    ]


def test_the_reading_notes_the_readable_files_its_admitted_request_cut() -> None:
    files = (*(_file() for _ in range(4)), _file(readable=False))

    def upload(file: AIBuilderAttachmentEvidence, coverage: AttachmentCoverage):
        return replace(_UPLOAD, file_id=file.file_id, coverage=coverage)

    notes = classification_notes(
        offered=SlotClassificationInput(
            sources=(*(upload(file, "fully_seen") for file in files), _CURRENT)
        ),
        # The fit dropped files[3] from the request.
        admitted=SlotClassificationInput(
            sources=(
                upload(files[0], "inventory_only"),
                upload(files[1], "excerpt_truncated"),
                upload(files[2], "fully_seen"),
                upload(files[4], "inventory_only"),
                _CURRENT,
            )
        ),
        files=files,
    )

    # Mutants: a file without readable text counts, a file the fit dropped
    # does not, a shortened file counts as omitted, or the files are read
    # from the input before the request's fit.
    assert [note.model_dump(mode="json") for note in notes] == [
        {
            "kind": "count",
            "stage": "classification",
            "material": "attachment_files",
            "total": 4,
            "omitted": 2,
            "shortened": 1,
            "reasons": ["model_room"],
        }
    ]


_SWITCHED_OFF = UnattendedToolRefusal.TOOL_SWITCHED_OFF_IN_SPACE
# Four usable tools and two refused ones; each fixed limit leaves one out: a
# schema over the schema limit, a name over the overview limit, a refused
# name over the names limit.
_LIMITED_SPACE = (
    _option("S", "a", schema=_schema_of_length(TOOL_CATALOG_SCHEMA_MAX_CHARS + 1)),
    _option("S", "b", schema=_schema_of_length(40)),
    _option("S", "c"),
    _option("S", "d" + "x" * TOOL_CATALOG_OVERVIEW_MAX_CHARS),
    _option("S", "e", refusal=_SWITCHED_OFF),
    _option("S", "f" + "x" * TOOL_CATALOG_UNAVAILABLE_MAX_CHARS, refusal=_SWITCHED_OFF),
)
_FIXED, _ROOM = "fixed_limit", "model_room"


def _tool_note(material: str, total: int, omitted: int, *reasons: str):
    return {
        "kind": "count",
        "stage": "proposal",
        "material": material,
        "total": total,
        "omitted": omitted,
        "shortened": 0,
        "reasons": list(reasons),
    }


def _no_names_or_schemas(projection: AIBuilderToolCatalogProjection) -> bool:
    return projection.kind == "listed" and not (
        projection.unavailable
        or any(tool.input_schema_json for tool in projection.tools)
    )


@pytest.mark.parametrize(
    ("fits", "expected"),
    [
        # Mutants: a tool, schema or refused name a fixed limit left out is not
        # counted or counted as the room's; a schema the room hid takes the
        # reason of the one the schema limit hid, or the other way round.
        (
            _no_names_or_schemas,
            [
                _tool_note("usable_tools", 4, 1, _FIXED),
                _tool_note("tool_schemas", 2, 2, _ROOM, _FIXED),
                _tool_note("unavailable_tool_names", 2, 2, _ROOM, _FIXED),
            ],
        ),
        # Mutants: tools the room cut to none are not counted, count as a
        # catalogue the space lists too large, or their schemas count again.
        (
            lambda _: False,
            [
                _tool_note("usable_tools", 4, 4, _ROOM, _FIXED),
                _tool_note("unavailable_tool_names", 2, 2, _ROOM, _FIXED),
            ],
        ),
    ],
    ids=["fixed_and_room", "left_out"],
)
def test_the_tool_notes_name_the_limit_that_left_each_out(
    fits: Callable[[AIBuilderToolCatalogProjection], bool],
    expected: list[dict[str, object]],
) -> None:
    catalog, _ = _tools(*_LIMITED_SPACE)

    listed = fit_tool_catalog_projection(catalog.projection, fits=fits)

    assert [
        note.model_dump(mode="json")
        for note in tool_catalog_notes(catalog, listed=listed)
    ] == expected

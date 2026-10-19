"""What a Builder turn's model requests left out of the user's material.

Each packer reports what it left out of the request it built. The turn's
recorder keeps, per stage and material, the worst request that was actually
sent, and the turn's user message carries the summary once the turn stores its
messages or completes, so the stream and a reload read one value.
"""

from __future__ import annotations

from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal, TypeAlias, get_args
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from eneo.flows.ai_builder.ai_builder_slot_classification_contract import (
    SlotClassificationInput,
)
from eneo.flows.ai_builder.ai_builder_tool_catalog import (
    AIBuilderListedTool,
    AIBuilderToolCatalog,
    AIBuilderToolCatalogListed,
    AIBuilderToolCatalogNotOffered,
    AIBuilderToolCatalogProjection,
    AIBuilderToolCatalogTooLarge,
    AIBuilderUnavailableTool,
)
from eneo.flows.ai_builder.planning_state import AttachmentCoverage
from eneo.flows.flow_ai_builder_budget_settings import (
    AI_BUILDER_REVIEW_INVESTIGATION_EVIDENCE_CEILING_TOKENS,
)

if TYPE_CHECKING:
    from eneo.flows.ai_builder.ai_builder_attachment_context import (
        AIBuilderAttachmentEvidence,
    )
    from eneo.flows.ai_builder.ai_builder_flow_review_sample import ExcerptCut
    from eneo.flows.ai_builder.ai_builder_settings import (
        AIBuilderPlannedRequestBudget,
    )

CoverageStage: TypeAlias = Literal["classification", "proposal"]
CoverageReason: TypeAlias = Literal["model_room", "fixed_limit", "configured_limit"]
# Whose room a request had: the model's, or the input cap an admin set for it.
RoomReason: TypeAlias = Literal["model_room", "configured_limit"]
# In the order a stage's notes are listed.
CountedMaterial: TypeAlias = Literal[
    "classification_sources",
    "history_messages",
    "requirement_assumptions",
    "attachment_files",
    "run_excerpts",
    "usable_tools",
    "tool_schemas",
    "unavailable_tool_names",
]
_REASON_ORDER: tuple[CoverageReason, ...] = get_args(CoverageReason)
_STAGE_ORDER: tuple[str, ...] = get_args(CoverageStage)
_MATERIAL_ORDER: tuple[str, ...] = (*get_args(CountedMaterial), "tool_catalog")


class CountCoverageNote(BaseModel):
    """How many items of one material a stage's sent requests left out or
    carried only in part. The unit follows the material."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["count"] = Field(
        default="count",
        description=(
            "The note's shape: `count` gives item counts. Other kinds may follow; "
            "a note stored without a kind is a `count` note."
        ),
    )
    stage: CoverageStage = Field(
        description=(
            "The model call that left the material out: `classification` (reading "
            "the message) or `proposal` (drafting the flow)."
        )
    )
    material: CountedMaterial = Field(
        description=(
            "What was counted: `classification_sources` (the user's messages and "
            "answer values the reading takes in), `history_messages` (earlier "
            "conversation messages; a reply and the tool results it called for "
            "count once), `requirement_assumptions` (confirmed assumptions), "
            "`attachment_files` (attached files with readable text: omitted when "
            "the request carries none of a file's text, shortened when it carries "
            "part), `run_excerpts` (excerpts from the runs a review-backed "
            "proposal reads), `usable_tools` (the space's tools a flow may use, "
            "omitted when not listed), `tool_schemas` (the input schemas of the "
            "listed tools, omitted when marked as not shown) or "
            "`unavailable_tool_names` (the tools the space refuses, named with "
            "their refusal)."
        )
    )
    total: int = Field(ge=0, description="How many items the stage had to send.")
    omitted: int = Field(
        ge=0,
        description=(
            "The most items one sent request of the stage left out (over a "
            "turn's repair and continuation requests, the largest, never a sum)."
        ),
    )
    shortened: int = Field(
        ge=0,
        description=(
            "Items a sent request carried only in part. An omitted item is not "
            "counted here too."
        ),
    )
    reasons: list[CoverageReason] = Field(
        min_length=1,
        description=(
            "Why, each once: `model_room` (the model's context window had no room "
            "for more), `fixed_limit` (a fixed Builder limit) or `configured_limit` "
            "(a limit set in the organisation's Builder settings). Later releases "
            "may add reasons."
        ),
    )

    @model_validator(mode="after")
    def _counts_one_to_all_items(self) -> CountCoverageNote:
        if not 0 < self.omitted + self.shortened <= self.total:
            raise ValueError(
                "A coverage note counts at least one and at most all items."
            )
        if len(set(self.reasons)) != len(self.reasons):
            raise ValueError("A coverage note names each reason once.")
        return self


class ToolCatalogUnavailableNote(BaseModel):
    """The proposal's sent requests listed none of the space's tools because
    the space offers more than the tool list's bounds (1,000 tools, 8 MiB of
    text): the tools are not known, so the note gives no counts."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["tool_catalog_unavailable"] = Field(
        description=(
            "The note's shape: the space's tool list is over its bounds, so no "
            "tool was listed and nothing is counted."
        )
    )
    stage: Literal["proposal"] = Field(
        description="Only the proposal lists the space's tools."
    )
    material: Literal["tool_catalog"] = Field(description="The space's MCP tools.")
    reason: Literal["catalog_limit"] = Field(
        description=(
            "`catalog_limit`: the space offers more tools than the tool list's "
            "bounds allow."
        )
    )


# A note stored without a kind validates only as a count note.
CoverageNote: TypeAlias = CountCoverageNote | ToolCatalogUnavailableNote


class TurnCoverage(BaseModel):
    """What one turn's sent model requests left out of the user's material."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    notes: list[CoverageNote] = Field(
        min_length=1,
        description=(
            "One note per stage and material that left something out; the "
            "reading's before the proposal's."
        ),
    )


def _count_note(
    stage: CoverageStage,
    material: CountedMaterial,
    *,
    total: int,
    omitted: int,
    shortened: int,
    reasons: Collection[CoverageReason],
) -> CountCoverageNote | None:
    if omitted + shortened == 0:
        return None
    return CountCoverageNote(
        stage=stage,
        material=material,
        total=total,
        omitted=omitted,
        shortened=shortened,
        reasons=[reason for reason in _REASON_ORDER if reason in reasons],
    )


def _reasons(*, fixed_limit: bool, model_room: bool) -> set[CoverageReason]:
    reasons: set[CoverageReason] = set()
    if fixed_limit:
        reasons.add("fixed_limit")
    if model_room:
        reasons.add("model_room")
    return reasons


def classification_sources_note(
    *, offered: SlotClassificationInput, admitted: SlotClassificationInput
) -> CountCoverageNote | None:
    """What the reading's request left out of the user's messages and answers,
    from the input before and after the capacity fit: the oldest sources over
    the fixed source limit and those the fit dropped are omitted; a source cut
    by the fixed answer length or by the fit is shortened. Attached files are
    counted on their own (`attachment_files_note`)."""

    carried = {source.source_id: source for source in admitted.sources}
    transcript = [
        source for source in offered.sources if source.kind != "uploaded_file"
    ]
    omitted = offered.transcript_sources_over_limit
    shortened = 0
    reasons: set[CoverageReason] = {"fixed_limit"} if omitted else set()
    for source in transcript:
        sent = carried.get(source.source_id)
        if sent is None:
            omitted += 1
            reasons.add("model_room")
            continue
        cut_by: set[CoverageReason] = set()
        if source.truncated:
            cut_by.add("fixed_limit")
        if len(sent.text) < len(source.text):
            cut_by.add("model_room")
        if cut_by:
            shortened += 1
            reasons |= cut_by
    return _count_note(
        "classification",
        "classification_sources",
        total=len(transcript) + offered.transcript_sources_over_limit,
        omitted=omitted,
        shortened=shortened,
        reasons=reasons,
    )


def classification_notes(
    *,
    offered: SlotClassificationInput,
    admitted: SlotClassificationInput,
    files: Iterable[AIBuilderAttachmentEvidence],
) -> tuple[CountCoverageNote, ...]:
    """What the reading's request left out of the user's messages and answers
    and of the attached files; a file the fit dropped from the request is one
    it carries none of the text of."""

    carried: dict[UUID, AttachmentCoverage] = {
        source.file_id: source.coverage
        for source in admitted.sources
        if source.file_id is not None and source.coverage is not None
    }
    notes = (
        classification_sources_note(offered=offered, admitted=admitted),
        attachment_files_note("classification", files=files, carried=carried),
    )
    return tuple(note for note in notes if note is not None)


def attachment_files_note(
    stage: CoverageStage,
    *,
    files: Iterable[AIBuilderAttachmentEvidence],
    carried: Mapping[UUID, AttachmentCoverage],
) -> CountCoverageNote | None:
    """What one request carried of the attached files with readable text, by
    the coverage its own fit gave each file. A file without readable text is
    only ever listed by name, so it is not counted."""

    sent = [
        carried.get(item.file_id, "inventory_only")
        for item in files
        if item.has_readable_text
    ]
    return _count_note(
        stage,
        "attachment_files",
        total=len(sent),
        omitted=sent.count("inventory_only"),
        shortened=sent.count("excerpt_truncated"),
        reasons={"model_room"},
    )


def requirement_assumptions_note(
    *, confirmed: int, replayed: int
) -> CountCoverageNote | None:
    """The confirmed assumptions the proposal prompt had no room to replay."""

    return _count_note(
        "proposal",
        "requirement_assumptions",
        total=confirmed,
        omitted=confirmed - replayed,
        shortened=0,
        reasons={"model_room"},
    )


def run_excerpts_note(
    cut: ExcerptCut | None, *, limit_tokens: int, room_tokens: int
) -> CountCoverageNote | None:
    """What the review-evidence fit left out of the run excerpts. The fit
    keeps the evidence within the evidence limit and within the room the
    prompt leaves for it, so the smaller of the two is the one that bound;
    the limit is the organisation's when it set one below the system bound."""

    if cut is None:
        return None
    limit: CoverageReason = (
        "configured_limit"
        if limit_tokens < AI_BUILDER_REVIEW_INVESTIGATION_EVIDENCE_CEILING_TOKENS
        else "fixed_limit"
    )
    return _count_note(
        "proposal",
        "run_excerpts",
        total=cut.readable,
        omitted=cut.omitted,
        shortened=cut.shortened,
        reasons={limit if limit_tokens <= room_tokens else "model_room"},
    )


_TOOL_CATALOG_UNAVAILABLE = ToolCatalogUnavailableNote(
    kind="tool_catalog_unavailable",
    stage="proposal",
    material="tool_catalog",
    reason="catalog_limit",
)


def tool_catalog_notes(
    offered: AIBuilderToolCatalog, *, listed: AIBuilderToolCatalogProjection
) -> tuple[CoverageNote, ...]:
    """What the proposal prompt left out of the space's tools: the catalogue
    the fixed limits built is `offered.projection`, and `listed` is what the
    request's room let the prompt list. A catalogue the session does not
    offer yet is a product choice, not a cut."""

    built = offered.projection
    if isinstance(built, AIBuilderToolCatalogNotOffered):
        return ()
    if isinstance(built, AIBuilderToolCatalogTooLarge) and not offered.usable_by_ref:
        # The space's list is over its bounds, so its tools are not known.
        return (_TOOL_CATALOG_UNAVAILABLE,)
    built_tools, built_names = _shown(built)
    sent_tools, sent_names = _shown(listed)
    fixed_hidden = {
        tool.ref for tool in built_tools if tool.schema_state == "over_budget"
    }
    declared = [tool for tool in sent_tools if tool.schema_state != "none_declared"]
    hidden = {tool.ref for tool in declared if tool.schema_state == "over_budget"}
    usable = len(offered.usable_by_ref)
    refused = len(offered.unavailable)
    notes = (
        _count_note(
            "proposal",
            "usable_tools",
            total=usable,
            omitted=usable - len(sent_tools),
            shortened=0,
            reasons=_reasons(
                fixed_limit=len(built_tools) < usable,
                model_room=len(sent_tools) < len(built_tools),
            ),
        ),
        _count_note(
            "proposal",
            "tool_schemas",
            total=len(declared),
            omitted=len(hidden),
            shortened=0,
            reasons=_reasons(
                fixed_limit=bool(hidden & fixed_hidden),
                model_room=bool(hidden - fixed_hidden),
            ),
        ),
        _count_note(
            "proposal",
            "unavailable_tool_names",
            total=refused,
            omitted=refused - len(sent_names),
            shortened=0,
            reasons=_reasons(
                fixed_limit=len(built_names) < refused,
                model_room=len(sent_names) < len(built_names),
            ),
        ),
    )
    return tuple(note for note in notes if note is not None)


def _shown(
    projection: AIBuilderToolCatalogProjection,
) -> tuple[tuple[AIBuilderListedTool, ...], tuple[AIBuilderUnavailableTool, ...]]:
    """The usable and the refused tools a projection names."""

    if isinstance(projection, AIBuilderToolCatalogListed):
        return projection.tools, projection.unavailable
    return (), ()


@dataclass(frozen=True, slots=True)
class ProposalPromptCut:
    """What preparing the proposal prompt left out before any call: the
    history groups its fit evicted, and the notes of the other material it
    packed (confirmed assumptions, attached files, run excerpts, tools)."""

    history_groups_left_out: int = 0
    notes: tuple[CoverageNote, ...] = ()
    # The room the preparation planned the prompt in (`request_room`).
    room: RoomReason = "model_room"


def _left_out(note: CoverageNote) -> tuple[int, int]:
    if isinstance(note, ToolCatalogUnavailableNote):
        return (0, 0)
    return (note.omitted, note.shortened)


def request_room(budget: AIBuilderPlannedRequestBudget) -> RoomReason:
    """Whose room a planned request had: the input cap's when the cap, not
    the model, set its available input."""

    return "configured_limit" if budget.input_cap_binds else "model_room"


def _in_room(note: CoverageNote, room: RoomReason) -> CoverageNote:
    if isinstance(note, ToolCatalogUnavailableNote) or "model_room" not in note.reasons:
        return note
    reasons = {room if reason == "model_room" else reason for reason in note.reasons}
    return note.model_copy(
        update={"reasons": [reason for reason in _REASON_ORDER if reason in reasons]}
    )


def _listing_order(note: CoverageNote) -> tuple[int, int]:
    return (_STAGE_ORDER.index(note.stage), _MATERIAL_ORDER.index(note.material))


@dataclass(slots=True)
class TurnCoverageRecorder:
    """The turn's one aggregation of coverage: each stage reports a request as
    it is sent, and per stage and material the summary keeps the sent request
    that left out the most (omitted, then shortened), never a sum over the
    retries of one prompt."""

    _proposal_cut: ProposalPromptCut = field(default_factory=ProposalPromptCut)
    _worst: dict[tuple[str, str], CoverageNote] = field(
        default_factory=dict[tuple[str, str], CoverageNote]
    )

    def record_classification_call(self, notes: Iterable[CoverageNote]) -> None:
        self._observe(notes)

    def prepare_proposal(self, cut: ProposalPromptCut) -> None:
        self._proposal_cut = cut

    def record_proposal_call(
        self,
        *,
        history_in_request: int,
        history_sent: int,
        request_budget: AIBuilderPlannedRequestBudget,
    ) -> None:
        """``request_budget`` is this call's own plan: a repair plans again,
        so its history was fitted in a room the preparation did not plan."""

        # Each request re-fits the history its preparation kept, evicting the
        # oldest first, so the request that kept the fewest left out the most.
        cut = self._proposal_cut
        history_total = cut.history_groups_left_out + history_in_request
        history = _count_note(
            "proposal",
            "history_messages",
            total=history_total,
            omitted=history_total - history_sent,
            shortened=0,
            reasons={"model_room"},
        )
        self._observe(
            (
                *(_in_room(note, cut.room) for note in cut.notes),
                *(
                    ()
                    if history is None
                    else (_in_room(history, request_room(request_budget)),)
                ),
            )
        )

    def _observe(self, notes: Iterable[CoverageNote]) -> None:
        for note in notes:
            key = (note.stage, note.material)
            self._worst[key] = max(self._worst.get(key, note), note, key=_left_out)

    def summary(self) -> TurnCoverage | None:
        notes = sorted(self._worst.values(), key=_listing_order)
        return TurnCoverage(notes=notes) if notes else None

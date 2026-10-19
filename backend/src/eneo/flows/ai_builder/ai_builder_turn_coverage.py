"""What a Builder turn's model requests left out of the user's material.

Each packer reports what it left out of the request it built. The turn's
recorder keeps, per material, the worst request that was actually sent, and
the turn's user message carries the summary once the turn stores its messages
or completes, so the stream and a reload read one value.
"""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass, field
from typing import Literal, TypeAlias, get_args

from pydantic import BaseModel, ConfigDict, Field, model_validator

from eneo.flows.ai_builder.ai_builder_slot_classification_contract import (
    SlotClassificationInput,
)

CoverageStage: TypeAlias = Literal["classification", "proposal"]
CoverageReason: TypeAlias = Literal["model_room", "fixed_limit"]
CountedMaterial: TypeAlias = Literal[
    "classification_sources", "history_messages", "requirement_assumptions"
]
_REASON_ORDER: tuple[CoverageReason, ...] = get_args(CoverageReason)


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
            "count once) or `requirement_assumptions` (confirmed assumptions)."
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
            "for more) or `fixed_limit` (a fixed Builder limit)."
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


CoverageNote: TypeAlias = CountCoverageNote


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


def classification_sources_note(
    *, offered: SlotClassificationInput, admitted: SlotClassificationInput
) -> CountCoverageNote | None:
    """What the reading's request left out of the user's messages and answers,
    from the input before and after the capacity fit: the oldest sources over
    the fixed source limit and those the fit dropped are omitted; a source cut
    by the fixed answer length or by the fit is shortened. Attached files have
    their own coverage and are not counted."""

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


@dataclass(frozen=True, slots=True)
class ProposalPromptCut:
    """What preparing the proposal prompt left out before any call: history
    groups the fit evicted, and how many confirmed assumptions were replayed."""

    history_groups_left_out: int = 0
    confirmed_assumptions: int = 0
    replayed_assumptions: int = 0


@dataclass(slots=True)
class TurnCoverageRecorder:
    """The turn's one aggregation of coverage: each stage reports a request as
    it is sent, and per material the summary keeps the worst sent request,
    never a sum over the retries of one prompt."""

    _reading: CountCoverageNote | None = None
    _proposal_cut: ProposalPromptCut = field(default_factory=ProposalPromptCut)
    _history_total: int = 0
    _history_omitted: int | None = None

    def record_classification_call(self, note: CountCoverageNote | None) -> None:
        self._reading = note

    def prepare_proposal(self, cut: ProposalPromptCut) -> None:
        self._proposal_cut = cut

    def record_proposal_call(
        self, *, history_in_request: int, history_sent: int
    ) -> None:
        # Each request re-fits the history its preparation kept, evicting the
        # oldest first, so the request that kept the fewest left out the most.
        self._history_total = (
            self._proposal_cut.history_groups_left_out + history_in_request
        )
        omitted = self._history_total - history_sent
        self._history_omitted = max(omitted, self._history_omitted or 0)

    def summary(self) -> TurnCoverage | None:
        cut = self._proposal_cut
        proposal_notes = (
            ()
            if self._history_omitted is None
            else (
                _count_note(
                    "proposal",
                    "history_messages",
                    total=self._history_total,
                    omitted=self._history_omitted,
                    shortened=0,
                    reasons={"model_room"},
                ),
                _count_note(
                    "proposal",
                    "requirement_assumptions",
                    total=cut.confirmed_assumptions,
                    omitted=cut.confirmed_assumptions - cut.replayed_assumptions,
                    shortened=0,
                    reasons={"model_room"},
                ),
            )
        )
        notes = [note for note in (self._reading, *proposal_notes) if note is not None]
        return TurnCoverage(notes=notes) if notes else None

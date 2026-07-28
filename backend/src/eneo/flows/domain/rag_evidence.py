"""Canonical typed record of what a Flow step retrieved from knowledge.

This model is evidence about *retrieval*, not about the prompt. A retrieved
passage is a candidate the retriever returned; the shared context builder later
decides, under its own token budget, which candidates reach the provider and
merges overlapping ones. Prompt inclusion is recorded separately under
``prompt_context``. Nothing here may be read as proof that the model saw a
passage.

The model validates its own counters. Every aggregate is derived from the
sources it describes, so a caller cannot persist an envelope whose totals
disagree with its contents.

Recorded passages contain verbatim source-document text. The evidence declares
that exposure through ``recorded_passage_content`` so the Flow run access policy
can decide whether a given reader may see the text. Source identity, titles and
counts are never withheld: hiding *which* sources were retrieved would defeat
the transparency this evidence exists to provide.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from typing import Any, Final, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, model_validator

from eneo.flows.domain.runtime_invariant_exceptions import MappedEvidenceNestingError

RETRIEVED_KNOWLEDGE_EVIDENCE_VERSION: Final[Literal[2]] = 2

PassageRecording = Literal["complete", "tail_truncated"]
PassageDisclosure = Literal[
    "text_disclosed",
    "text_withheld_sensitive_flow",
    "text_withheld_classified_space",
]
SourceUsageState = Literal["retrieved_candidate", "inserted_into_prompt"]
RecordedPassageContent = Literal["source_text_verbatim"]
# `step` is the runtime budget deciding what is recorded at all; `view` is a
# read-time response cap over evidence that remains retained.
PassageBudgetKind = Literal["step", "view"]
RECORDED_PASSAGE_CONTENT: Final[RecordedPassageContent] = "source_text_verbatim"

# Keys this aggregate owns inside the persisted step RAG payload. Consumers read
# them through this module so the payload has one spelling authority.
EVIDENCE_REFERENCES_KEY: Final[str] = "references"
EVIDENCE_VERSION_KEY: Final[str] = "knowledge_evidence_version"
EVIDENCE_CONTENT_KEY: Final[str] = "recorded_passage_content"
EVIDENCE_SOURCES_WITH_PASSAGES_KEY: Final[str] = "sources_with_recorded_passages"
EVIDENCE_PASSAGES_RECORDED_KEY: Final[str] = "passages_recorded"
EVIDENCE_PASSAGES_TRUNCATED_KEY: Final[str] = "passages_truncated"
EVIDENCE_PASSAGES_WITHHELD_KEY: Final[str] = "passages_withheld"
EVIDENCE_PASSAGE_BYTES_KEY: Final[str] = "recorded_passage_bytes"
EVIDENCE_PASSAGES_RELEASED_KEY: Final[str] = "passages_released_to_step_budget"
EVIDENCE_BYTES_RELEASED_KEY: Final[str] = "passage_bytes_released_to_step_budget"
# Kept separate from the step-budget counters above: those describe what the
# runtime chose never to record, these describe what a read-time view left
# out of its response. Conflating them would hide which policy applied.
EVIDENCE_PASSAGES_OMITTED_KEY: Final[str] = "passages_omitted_from_view"
EVIDENCE_BYTES_OMITTED_KEY: Final[str] = "passage_bytes_omitted_from_view"

# Mapped steps nest one payload per provider call under one of these keys.
MAPPED_EXECUTION_MODE_KEY: Final[str] = "execution_mode"
MAPPED_CALL_COLLECTION_KEYS: Final[tuple[str, ...]] = ("items", "sources")
# False when the step failed partway: the calls below are the ones that
# completed, not the full fan-out the step intended.
MAPPED_CALLS_COMPLETE_KEY: Final[str] = "mapped_calls_complete"

# The step-result copy carries citation identity only. It deliberately uses a
# different key from `references` so it can never be mistaken for evidence.
CITATION_SOURCES_KEY: Final[str] = "citation_sources"
PASSAGE_EVIDENCE_LOCATION_KEY: Final[str] = "passage_evidence_location"
PASSAGE_EVIDENCE_LOCATION: Final[str] = "attempt_provenance"


class RetrievedPassage(BaseModel):
    """One passage exactly as the retriever returned it, bounded in size."""

    model_config = ConfigDict(extra="forbid")

    chunk_no: int
    score: float
    text: str | None = Field(
        default=None,
        description=(
            "The retrieved passage verbatim, or null when disclosure withholds "
            "it. When recording is 'tail_truncated' this is a leading prefix of "
            "the passage and the remaining bytes were dropped."
        ),
    )
    recording: PassageRecording
    disclosure: PassageDisclosure = "text_disclosed"
    passage_bytes: int = Field(
        description="UTF-8 byte length of the passage the retriever returned."
    )
    recorded_bytes: int = Field(
        description=(
            "UTF-8 byte length of the recorded text. Stays populated when "
            "disclosure withholds the text, so a reader can tell that a passage "
            "of this size exists but is not shown to them."
        )
    )

    @model_validator(mode="after")
    def _text_matches_disclosure_and_bytes(self) -> "RetrievedPassage":
        if self.disclosure == "text_disclosed":
            if self.text is None:
                raise ValueError("A disclosed passage must carry its text.")
            if len(self.text.encode("utf-8")) != self.recorded_bytes:
                raise ValueError(
                    "recorded_bytes must equal the UTF-8 length of the text."
                )
        elif self.text is not None:
            raise ValueError("A withheld passage must not carry its text.")
        if self.recorded_bytes > self.passage_bytes:
            raise ValueError("recorded_bytes cannot exceed passage_bytes.")
        expected: PassageRecording = (
            "complete"
            if self.recorded_bytes == self.passage_bytes
            else "tail_truncated"
        )
        if self.recording != expected:
            raise ValueError(f"recording must be {expected} for these byte counts.")
        return self

    @classmethod
    def record(
        cls,
        *,
        chunk_no: int,
        score: float,
        retrieved_text: str,
        max_bytes: int,
    ) -> "RetrievedPassage | None":
        """Record a passage verbatim, dropping only the tail beyond the bound.

        Returns None when the bound cannot hold one complete code point: an
        empty passage would read as "nothing was retrieved here", which is a
        different and false claim.
        """
        encoded = retrieved_text.encode("utf-8")
        passage_bytes = len(encoded)
        if passage_bytes == 0:
            return None
        if passage_bytes <= max_bytes:
            return cls(
                chunk_no=chunk_no,
                score=score,
                text=retrieved_text,
                recording="complete",
                passage_bytes=passage_bytes,
                recorded_bytes=passage_bytes,
            )
        recorded_text = encoded[: max(0, max_bytes)].decode("utf-8", errors="ignore")
        recorded_bytes = len(recorded_text.encode("utf-8"))
        if recorded_bytes == 0:
            return None
        return cls(
            chunk_no=chunk_no,
            score=score,
            text=recorded_text,
            recording="tail_truncated",
            passage_bytes=passage_bytes,
            recorded_bytes=recorded_bytes,
        )

    def withheld(self, disclosure: PassageDisclosure) -> "RetrievedPassage":
        if disclosure == "text_disclosed":
            raise ValueError("Withholding requires a withheld disclosure state.")
        return self.model_copy(update={"text": None, "disclosure": disclosure})

    @property
    def dropped_bytes(self) -> int:
        return max(0, self.passage_bytes - self.recorded_bytes)


class RetrievedSource(BaseModel):
    """A source a step retrieved from, with bounded passage detail."""

    model_config = ConfigDict(extra="forbid")

    id: str
    id_short: str
    title: str | None = None
    source_title: str | None = None
    source_title_raw: str | None = None
    source_display_name: str | None = None
    source_url: str | None = None
    source_kind: str | None = None
    source_container_kind: str | None = None
    source_container_name: str | None = None
    source_container_name_raw: str | None = None
    source_container_label: str | None = None
    source_container_id: str | None = None
    matched_chunk_count: int = Field(
        description="Passages the retriever returned from this source."
    )
    recorded_passage_count: int = Field(
        description="Passages recorded below; never greater than the match count."
    )
    best_score: float
    usage_state: SourceUsageState = "retrieved_candidate"
    passages: list[RetrievedPassage] = Field(default_factory=list[RetrievedPassage])
    display_snippet: str | None = None
    display_chunk_no: int | None = None
    display_selection_reason: str | None = None
    snippet_quality: str | None = None
    quality_flags: list[str] = Field(default_factory=list[str])
    boilerplate_likelihood: float | None = None

    @model_validator(mode="after")
    def _counts_match_passages(self) -> "RetrievedSource":
        if self.recorded_passage_count != len(self.passages):
            raise ValueError(
                "recorded_passage_count must equal the number of recorded passages."
            )
        if self.recorded_passage_count > self.matched_chunk_count:
            raise ValueError(
                "recorded_passage_count cannot exceed matched_chunk_count."
            )
        return self

    @property
    def recorded_passage_bytes(self) -> int:
        return sum(passage.recorded_bytes for passage in self.passages)

    @property
    def disclosed_passage_bytes(self) -> int:
        """Bytes a response carries: a withheld passage carries no text."""
        return sum(
            passage.recorded_bytes
            for passage in self.passages
            if passage.disclosure == "text_disclosed"
        )

    def without_passages(self) -> "RetrievedSource":
        return self.model_copy(update={"passages": [], "recorded_passage_count": 0})

    def with_disclosure(self, disclosure: PassageDisclosure) -> "RetrievedSource":
        if disclosure == "text_disclosed":
            return self
        return self.model_copy(
            update={
                "passages": [passage.withheld(disclosure) for passage in self.passages]
            }
        )

    def to_payload(self) -> dict[str, Any]:
        """Persisted form: absent optional metadata is omitted, passages are not.

        A withheld passage keeps an explicit null ``text`` so a reader can tell
        it apart from a source that recorded no passage at all.
        """
        payload = self.model_dump(mode="json", exclude_none=True)
        payload["passages"] = [
            passage.model_dump(mode="json") for passage in self.passages
        ]
        return payload


class RetrievedKnowledgeEvidence(BaseModel):
    """Every source a step retrieved, plus how much detail was recorded."""

    model_config = ConfigDict(extra="forbid")

    version: Literal[2] = RETRIEVED_KNOWLEDGE_EVIDENCE_VERSION
    recorded_passage_content: RecordedPassageContent = RECORDED_PASSAGE_CONTENT
    sources: list[RetrievedSource] = Field(default_factory=list[RetrievedSource])
    passages_released_to_step_budget: int = 0
    passage_bytes_released_to_step_budget: int = 0
    passages_omitted_from_view: int = 0
    passage_bytes_omitted_from_view: int = 0

    @property
    def sources_with_recorded_passages(self) -> int:
        return sum(1 for source in self.sources if source.passages)

    @property
    def passages_recorded(self) -> int:
        return sum(len(source.passages) for source in self.sources)

    @property
    def passages_truncated(self) -> int:
        return sum(
            1
            for source in self.sources
            for passage in source.passages
            if passage.recording == "tail_truncated"
        )

    @property
    def passages_withheld(self) -> int:
        return sum(
            1
            for source in self.sources
            for passage in source.passages
            if passage.disclosure != "text_disclosed"
        )

    @property
    def recorded_passage_bytes(self) -> int:
        return sum(source.recorded_passage_bytes for source in self.sources)

    @property
    def disclosed_passage_bytes(self) -> int:
        """Bytes a response carries, ignoring text it will not return anyway."""
        return sum(source.disclosed_passage_bytes for source in self.sources)

    def with_disclosure(
        self, disclosure: PassageDisclosure
    ) -> "RetrievedKnowledgeEvidence":
        if disclosure == "text_disclosed":
            return self
        return self.model_copy(
            update={
                "sources": [
                    source.with_disclosure(disclosure) for source in self.sources
                ]
            }
        )

    def release_passages_beyond(
        self,
        remaining_bytes: int,
        *,
        budget: PassageBudgetKind = "step",
    ) -> "RetrievedKnowledgeEvidence":
        """Drop passage detail that does not fit the caller's remaining budget.

        Source identity and match counts survive; only passage text goes, and
        the loss is reported as counts rather than a flag. The two budgets keep
        separate counters: `step` is what the runtime never recorded, `view` is
        what a read-time response left out of evidence that is still retained.
        """
        remaining = max(0, remaining_bytes)
        kept: list[RetrievedSource] = []
        released_passages = 0
        released_bytes = 0
        for source in self.sources:
            # Charge what the response carries. Text already withheld by policy
            # occupies nothing, so it must not push other evidence out.
            source_bytes = (
                source.recorded_passage_bytes
                if budget == "step"
                else source.disclosed_passage_bytes
            )
            if source.passages and source_bytes <= remaining:
                remaining -= source_bytes
                kept.append(source)
                continue
            if source.passages:
                released_passages += len(source.passages)
                released_bytes += source_bytes
            kept.append(source.without_passages())
        if budget == "step":
            counters = {
                "passages_released_to_step_budget": (
                    self.passages_released_to_step_budget + released_passages
                ),
                "passage_bytes_released_to_step_budget": (
                    self.passage_bytes_released_to_step_budget + released_bytes
                ),
            }
        else:
            counters = {
                "passages_omitted_from_view": (
                    self.passages_omitted_from_view + released_passages
                ),
                "passage_bytes_omitted_from_view": (
                    self.passage_bytes_omitted_from_view + released_bytes
                ),
            }
        return self.model_copy(update={"sources": kept, **counters})

    def aggregate_payload(self) -> dict[str, Any]:
        """The derived totals this aggregate owns inside the step RAG payload."""
        return {
            EVIDENCE_VERSION_KEY: self.version,
            EVIDENCE_CONTENT_KEY: self.recorded_passage_content,
            EVIDENCE_SOURCES_WITH_PASSAGES_KEY: self.sources_with_recorded_passages,
            EVIDENCE_PASSAGES_RECORDED_KEY: self.passages_recorded,
            EVIDENCE_PASSAGES_TRUNCATED_KEY: self.passages_truncated,
            EVIDENCE_PASSAGES_WITHHELD_KEY: self.passages_withheld,
            EVIDENCE_PASSAGE_BYTES_KEY: self.recorded_passage_bytes,
            EVIDENCE_PASSAGES_RELEASED_KEY: self.passages_released_to_step_budget,
            EVIDENCE_BYTES_RELEASED_KEY: self.passage_bytes_released_to_step_budget,
            EVIDENCE_PASSAGES_OMITTED_KEY: self.passages_omitted_from_view,
            EVIDENCE_BYTES_OMITTED_KEY: self.passage_bytes_omitted_from_view,
        }

    def write_into(self, rag_payload: dict[str, Any]) -> dict[str, Any]:
        """Replace the evidence this aggregate owns, leaving other keys alone."""
        rag_payload[EVIDENCE_REFERENCES_KEY] = [
            source.to_payload() for source in self.sources
        ]
        rag_payload.update(self.aggregate_payload())
        return rag_payload

    @classmethod
    def from_payload(
        cls, rag_payload: Mapping[str, Any]
    ) -> "RetrievedKnowledgeEvidence":
        """Parse the evidence aggregate back out of a persisted RAG payload.

        Totals are recomputed from the sources rather than trusted, so a payload
        written by an inconsistent path cannot carry contradictory counters on.
        """
        raw_references = rag_payload.get(EVIDENCE_REFERENCES_KEY)
        sources: list[RetrievedSource] = []
        if isinstance(raw_references, list):
            for reference in cast(list[object], raw_references):
                if isinstance(reference, dict):
                    sources.append(
                        RetrievedSource.model_validate(cast(dict[str, Any], reference))
                    )
        return cls(
            sources=sources,
            passages_released_to_step_budget=_non_negative_int(
                rag_payload.get(EVIDENCE_PASSAGES_RELEASED_KEY)
            ),
            passage_bytes_released_to_step_budget=_non_negative_int(
                rag_payload.get(EVIDENCE_BYTES_RELEASED_KEY)
            ),
            passages_omitted_from_view=_non_negative_int(
                rag_payload.get(EVIDENCE_PASSAGES_OMITTED_KEY)
            ),
            passage_bytes_omitted_from_view=_non_negative_int(
                rag_payload.get(EVIDENCE_BYTES_OMITTED_KEY)
            ),
        )


def _non_negative_int(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        return 0
    return max(0, value)


def iter_retrieved_source_payloads(
    rag_payload: Mapping[str, Any] | None,
) -> Iterator[dict[str, Any]]:
    """Every retrieved source in a step RAG payload, flat or mapped.

    A mapped step records one RAG payload per provider call under ``items`` or
    ``sources``. Debug projection, evidence export and usage tracking all read
    sources through this one iterator, so a mapped step can never look like a
    step that retrieved nothing.
    """
    if not isinstance(rag_payload, Mapping):
        return
    references = rag_payload.get(EVIDENCE_REFERENCES_KEY)
    if isinstance(references, list):
        for reference in cast(list[object], references):
            if isinstance(reference, dict):
                yield cast(dict[str, Any], reference)
    for collection_key in MAPPED_CALL_COLLECTION_KEYS:
        calls = rag_payload.get(collection_key)
        if not isinstance(calls, list):
            continue
        for call in cast(list[object], calls):
            if isinstance(call, Mapping):
                yield from iter_retrieved_source_payloads(cast(Mapping[str, Any], call))


def iter_step_rag_payloads(
    rag_payload: Mapping[str, Any] | None,
) -> Iterator[Mapping[str, Any]]:
    """The RAG payload itself, plus each mapped per-call payload beneath it."""
    if not isinstance(rag_payload, Mapping):
        return
    yield rag_payload
    for collection_key in MAPPED_CALL_COLLECTION_KEYS:
        calls = rag_payload.get(collection_key)
        if not isinstance(calls, list):
            continue
        for call in cast(list[object], calls):
            if isinstance(call, Mapping):
                yield from iter_step_rag_payloads(cast(Mapping[str, Any], call))


def is_mapped_rag_payload(rag_payload: Mapping[str, Any] | None) -> bool:
    return (
        isinstance(rag_payload, Mapping)
        and MAPPED_EXECUTION_MODE_KEY in rag_payload
        and any(
            isinstance(rag_payload.get(key), list)
            for key in MAPPED_CALL_COLLECTION_KEYS
        )
    )


MAPPED_SOURCES_TOTAL_KEY: Final[str] = "sources_total"


_MAPPED_SUMMED_KEYS: Final[tuple[str, ...]] = (
    MAPPED_SOURCES_TOTAL_KEY,
    EVIDENCE_SOURCES_WITH_PASSAGES_KEY,
    EVIDENCE_PASSAGES_RECORDED_KEY,
    EVIDENCE_PASSAGES_TRUNCATED_KEY,
    EVIDENCE_PASSAGES_WITHHELD_KEY,
    EVIDENCE_PASSAGE_BYTES_KEY,
    EVIDENCE_PASSAGES_RELEASED_KEY,
    EVIDENCE_BYTES_RELEASED_KEY,
    EVIDENCE_PASSAGES_OMITTED_KEY,
    EVIDENCE_BYTES_OMITTED_KEY,
)


def _call_totals(call: Mapping[str, Any]) -> dict[str, int]:
    """One mapped call's totals.

    Mapped evidence nests exactly one level, so a call is always a leaf. A call
    that is itself a mapped envelope would make these totals silently zero, so
    the invariant is enforced rather than guessed at.
    """
    if is_mapped_rag_payload(call):
        raise MappedEvidenceNestingError(
            "Mapped step evidence nests one level; a mapped call cannot itself "
            "contain mapped calls."
        )
    evidence = RetrievedKnowledgeEvidence.from_payload(call)
    return {
        MAPPED_SOURCES_TOTAL_KEY: len(evidence.sources),
        EVIDENCE_SOURCES_WITH_PASSAGES_KEY: evidence.sources_with_recorded_passages,
        EVIDENCE_PASSAGES_RECORDED_KEY: evidence.passages_recorded,
        EVIDENCE_PASSAGES_TRUNCATED_KEY: evidence.passages_truncated,
        EVIDENCE_PASSAGES_WITHHELD_KEY: evidence.passages_withheld,
        EVIDENCE_PASSAGE_BYTES_KEY: evidence.recorded_passage_bytes,
        EVIDENCE_PASSAGES_RELEASED_KEY: evidence.passages_released_to_step_budget,
        EVIDENCE_BYTES_RELEASED_KEY: evidence.passage_bytes_released_to_step_budget,
        EVIDENCE_PASSAGES_OMITTED_KEY: evidence.passages_omitted_from_view,
        EVIDENCE_BYTES_OMITTED_KEY: evidence.passage_bytes_omitted_from_view,
    }


def mapped_aggregate_payload(
    call_payloads: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Totals for a mapped step, summed from the calls it actually contains."""
    per_call = [_call_totals(call) for call in call_payloads]
    return {key: sum(totals[key] for totals in per_call) for key in _MAPPED_SUMMED_KEYS}


def recompute_mapped_aggregates(rag_payload: dict[str, Any]) -> dict[str, Any]:
    """Re-derive a mapped root's totals from the calls it contains.

    A mapped root carries no `references` of its own, so any transformation of
    its calls leaves its totals stale unless they are recomputed here. Every
    operation that rewrites nested evidence must end with this.
    """
    for collection_key in MAPPED_CALL_COLLECTION_KEYS:
        calls = rag_payload.get(collection_key)
        if not isinstance(calls, list):
            continue
        typed_calls = [
            cast(dict[str, Any], call)
            for call in cast(list[object], calls)
            if isinstance(call, dict)
        ]
        rag_payload.update(mapped_aggregate_payload(typed_calls))
    return rag_payload


def omitted_view_totals(rag_payload: Mapping[str, Any]) -> tuple[int, int]:
    """Passages and bytes a view left out of this payload.

    A mapped root already carries the sum of its calls, so reading the root and
    the calls would count every omission twice. Read exactly one level: the
    mapped root when there is one, the payload itself otherwise.
    """
    evidence = RetrievedKnowledgeEvidence.from_payload(rag_payload)
    return evidence.passages_omitted_from_view, evidence.passage_bytes_omitted_from_view


def disclosed_passage_bytes_in(rag_payload: Mapping[str, Any]) -> int:
    """Passage bytes this payload would carry, mapped calls included."""
    if is_mapped_rag_payload(rag_payload):
        total = 0
        for collection_key in MAPPED_CALL_COLLECTION_KEYS:
            calls = rag_payload.get(collection_key)
            if not isinstance(calls, list):
                continue
            for call in cast(list[object], calls):
                if isinstance(call, Mapping):
                    total += disclosed_passage_bytes_in(cast(Mapping[str, Any], call))
        return total
    return RetrievedKnowledgeEvidence.from_payload(rag_payload).disclosed_passage_bytes


def apply_passage_disclosure(
    rag_payload: dict[str, Any],
    *,
    disclosure: PassageDisclosure,
) -> dict[str, Any]:
    """Withhold verbatim passage text everywhere in a step RAG payload.

    Applies to mapped per-call payloads too. Source identity, titles and counts
    are untouched by design.
    """
    if disclosure == "text_disclosed":
        return rag_payload
    for payload in _mutable_step_rag_payloads(rag_payload):
        if not isinstance(payload.get(EVIDENCE_REFERENCES_KEY), list):
            continue
        evidence = RetrievedKnowledgeEvidence.from_payload(payload)
        evidence.with_disclosure(disclosure).write_into(payload)
    return recompute_mapped_aggregates(rag_payload)


def _mutable_step_rag_payloads(rag_payload: dict[str, Any]) -> Iterator[dict[str, Any]]:
    yield rag_payload
    for collection_key in MAPPED_CALL_COLLECTION_KEYS:
        calls = rag_payload.get(collection_key)
        if not isinstance(calls, list):
            continue
        for call in cast(list[object], calls):
            if isinstance(call, dict):
                yield from _mutable_step_rag_payloads(cast(dict[str, Any], call))


def compact_citation_sources(
    sources: Sequence[RetrievedSource],
) -> list[dict[str, Any]]:
    """Source identity a later step needs to inherit citations, without text."""
    return [
        {
            key: value
            for key, value in {
                "id": source.id,
                "id_short": source.id_short,
                "title": source.title,
                "source_title": source.source_title,
                "source_title_raw": source.source_title_raw,
                "source_display_name": source.source_display_name,
                "source_url": source.source_url,
                "source_kind": source.source_kind,
                "source_container_kind": source.source_container_kind,
                "source_container_name": source.source_container_name,
                "source_container_name_raw": source.source_container_name_raw,
                "source_container_label": source.source_container_label,
                "source_container_id": source.source_container_id,
                "usage_state": source.usage_state,
                "matched_chunk_count": source.matched_chunk_count,
                "best_score": source.best_score,
            }.items()
            if value is not None
        }
        for source in sources
    ]


def build_step_result_citation_state(
    rag_payload: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    """The step-result copy: source identity for later steps, never passages.

    Inherited-citation prompts name sources; they never quote passages. This
    copy therefore carries no ``references`` key at all — it does not pretend to
    be evidence — and points at the one place the verbatim text lives.
    """
    if not isinstance(rag_payload, Mapping):
        return None
    citation_state: dict[str, Any] = {
        key: value
        for key, value in rag_payload.items()
        if key
        in {
            "attempted",
            "status",
            "error_code",
            "unique_sources",
            "chunks_retrieved",
            "prompt_context",
            "tracking",
            MAPPED_EXECUTION_MODE_KEY,
        }
    }
    sources: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for reference in iter_retrieved_source_payloads(rag_payload):
        source_id = reference.get("id")
        if not isinstance(source_id, str) or source_id in seen_ids:
            continue
        seen_ids.add(source_id)
        sources.append(reference)
    citation_state[CITATION_SOURCES_KEY] = compact_citation_sources(
        [RetrievedSource.model_validate(source) for source in sources]
    )
    citation_state[PASSAGE_EVIDENCE_LOCATION_KEY] = PASSAGE_EVIDENCE_LOCATION
    return citation_state

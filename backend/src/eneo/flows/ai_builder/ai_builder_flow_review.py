"""Evidence-driven review of a published flow: the bounded facts packet.

One owner for what the AI builder may read about a flow's runs before it
proposes an edit. The packet is deterministic and built from what runs already
persist, never from step inputs or outputs: which step outputs were observed
being consumed, which error codes repeat, which step carries the run's tokens
or time, and how complete the evidence is. Every fact carries a stable id keyed
by the exact published version and checksum it was computed for, so a later
turn can name a finding without copying run data into the conversation.

Authorization is per run: a run the caller may not view is left out and only
counted, never named. A run recorded before the evidence classification level
existed is left out the same way; the packet's own level is the highest level
among the runs it did read, and a reader must clear it before a model sees the
packet.
"""

from __future__ import annotations

import hashlib
from collections import defaultdict
from datetime import datetime, timezone
from typing import Annotated, Literal, Protocol, Sequence
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from eneo.flows.ai_builder.ai_builder_error_contract import (
    AIBuilderBadRequestException,
    AIBuilderErrorCode,
)
from eneo.flows.domain.flow import FlowRunStatusSnapshot
from eneo.flows.domain.runtime import RuntimeStep
from eneo.flows.enums import FlowRunStatus
from eneo.flows.infrastructure.flow_run_repo import (
    FlowStepLineage,
    FlowStepResultMetrics,
)
from eneo.flows.published_definition import parse_published_runtime_steps
from eneo.main.exceptions import UnauthorizedException
from eneo.users.user import UserInDB

# Newest runs examined for the exact published version; a flow with a long
# history at an older version still yields a bounded read.
COHORT_SCAN_LIMIT = 100
COHORT_COMPLETED_LIMIT = 20
COHORT_FAILED_LIMIT = 10
# A step that carries at least this share of a run's tokens or wall time,
# averaged over the completed runs, is worth pointing at.
STEP_SHARE_THRESHOLD = 0.5
REPEATED_ERROR_MIN_RUNS = 2
# Findings one turn may name; the packet is small and the prompt stays bounded.
MAX_REVIEW_FINDINGS_PER_TURN = 10


class FlowReviewStep(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    step_id: UUID
    step_order: int
    label: str | None


class FlowReviewOmittedRuns(BaseModel):
    """Runs the packet did not read, by reason. Counts only, never ids."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    other_version: int = 0
    not_viewable: int = 0
    level_unknown: int = 0


class FlowReviewCohort(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    completed_run_ids: list[UUID]
    failed_run_ids: list[UUID]
    omitted: FlowReviewOmittedRuns


class _FlowReviewFact(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    finding_id: str


class OutputNotObservedConsumedFact(_FlowReviewFact):
    """No later step's resolved input cited this step's output in any completed run."""

    kind: Literal["output_not_observed_consumed"] = "output_not_observed_consumed"
    step_id: UUID
    step_order: int
    run_count: int


class RepeatedErrorCodeFact(_FlowReviewFact):
    kind: Literal["repeated_error_code"] = "repeated_error_code"
    step_id: UUID
    step_order: int
    error_code: str
    run_count: int


class StepShareFact(_FlowReviewFact):
    """A step's mean share of the run's tokens or wall time over completed runs."""

    kind: Literal["token_share", "latency_share"]
    step_id: UUID
    step_order: int
    share: float = Field(ge=0.0, le=1.0)
    run_count: int


class EvidenceCompletenessFact(_FlowReviewFact):
    kind: Literal["evidence_completeness"] = "evidence_completeness"
    runs_with_all_step_results: int
    runs_missing_step_results: int
    runs_without_lineage: int


FlowReviewFact = Annotated[
    OutputNotObservedConsumedFact
    | RepeatedErrorCodeFact
    | StepShareFact
    | EvidenceCompletenessFact,
    Field(discriminator="kind"),
]


class FlowReviewPacket(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    flow_id: UUID
    flow_version: int
    definition_checksum: str
    generated_at: datetime
    evidence_classification_level: int = Field(ge=0)
    steps: list[FlowReviewStep]
    cohort: FlowReviewCohort
    facts: list[FlowReviewFact]


class AIBuilderReviewContext(BaseModel):
    """What a turn says about the review it acts on: the exact reviewed
    version and the findings it names. Ids only; the facts are rebuilt from
    the runs on every turn, so run data never lives in the conversation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["flow_review"] = "flow_review"
    flow_version: int = Field(ge=1)
    definition_checksum: str = Field(min_length=1, max_length=128)
    finding_ids: list[str] = Field(
        min_length=1, max_length=MAX_REVIEW_FINDINGS_PER_TURN
    )

    def to_metadata(self) -> dict[str, object]:
        return self.model_dump(mode="json")


class FlowReviewEvidence(BaseModel):
    """The named findings of one review, resolved for one turn."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    flow_version: int
    definition_checksum: str
    evidence_classification_level: int = Field(ge=0)
    completed_run_count: int
    failed_run_count: int
    steps: list[FlowReviewStep]
    facts: list[FlowReviewFact]


def resolve_review_evidence(
    packet: FlowReviewPacket, context: AIBuilderReviewContext
) -> FlowReviewEvidence:
    """The facts a turn names, or a typed refusal when they no longer exist.

    A republished flow gets a new packet with new ids; a turn still naming the
    old ones is told so rather than handed facts about a different version.
    """
    if (
        packet.flow_version != context.flow_version
        or packet.definition_checksum != context.definition_checksum
    ):
        raise AIBuilderBadRequestException(
            "The flow was published again after this review; review it anew.",
            code=AIBuilderErrorCode.REVIEW_STALE,
            context={
                "reviewed_version": context.flow_version,
                "published_version": packet.flow_version,
            },
        )
    by_id = {fact.finding_id: fact for fact in packet.facts}
    unknown = [fid for fid in context.finding_ids if fid not in by_id]
    if unknown:
        raise AIBuilderBadRequestException(
            "A named finding is not part of this flow's review.",
            code=AIBuilderErrorCode.REVIEW_FINDING_UNKNOWN,
            context={"finding_ids": unknown},
        )
    facts = [by_id[fid] for fid in dict.fromkeys(context.finding_ids)]
    return FlowReviewEvidence(
        flow_version=packet.flow_version,
        definition_checksum=packet.definition_checksum,
        evidence_classification_level=packet.evidence_classification_level,
        completed_run_count=len(packet.cohort.completed_run_ids),
        failed_run_count=len(packet.cohort.failed_run_ids),
        steps=list(packet.steps),
        facts=facts,
    )


def render_review_evidence(evidence: FlowReviewEvidence) -> str:
    """The findings as prompt lines for the planner, in the product's language."""
    labels = {
        step.step_id: f"steg {step.step_order}"
        + (f" ({step.label})" if step.label else "")
        for step in evidence.steps
    }
    lines = [
        "## Underlag från körningar",
        f"Publicerad version {evidence.flow_version}: "
        f"{evidence.completed_run_count} lyckade och "
        f"{evidence.failed_run_count} misslyckade körningar lästes.",
    ]
    for fact in evidence.facts:
        if isinstance(fact, OutputNotObservedConsumedFact):
            lines.append(
                f"- {labels.get(fact.step_id, 'okänt steg')}: utdata användes "
                f"inte av något senare steg i {fact.run_count} lyckade körningar."
            )
        elif isinstance(fact, RepeatedErrorCodeFact):
            lines.append(
                f"- {labels.get(fact.step_id, 'okänt steg')}: felkoden "
                f"{fact.error_code} återkom i {fact.run_count} misslyckade körningar."
            )
        elif isinstance(fact, StepShareFact):
            what = "tokens" if fact.kind == "token_share" else "tid"
            lines.append(
                f"- {labels.get(fact.step_id, 'okänt steg')}: står för "
                f"{round(fact.share * 100)} % av körningens {what} "
                f"(medel över {fact.run_count} körningar)."
            )
        else:
            lines.append(
                f"- Underlag: {fact.runs_with_all_step_results} körningar med "
                f"resultat för alla steg, {fact.runs_missing_step_results} utan, "
                f"{fact.runs_without_lineage} utan spårad indata."
            )
    lines.append(
        "Föreslå en ändring som åtgärdar punkterna ovan. Hänvisa till steg "
        "med deras nummer och ändra inget som underlaget inte motiverar."
    )
    return "\n".join(lines)


def finding_id(
    *,
    flow_id: UUID,
    flow_version: int,
    definition_checksum: str,
    kind: str,
    step_id: UUID | None = None,
    error_code: str | None = None,
) -> str:
    """Stable across packets of the same published version; changes with it."""
    key = f"{flow_id}:{flow_version}:{definition_checksum}:{kind}:{step_id or ''}:{error_code or ''}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


def review_facts(
    *,
    flow_id: UUID,
    flow_version: int,
    definition_checksum: str,
    steps: Sequence[RuntimeStep],
    completed_run_ids: Sequence[UUID],
    failed_run_ids: Sequence[UUID],
    metrics: Sequence[FlowStepResultMetrics],
    lineage: Sequence[FlowStepLineage],
) -> list[
    OutputNotObservedConsumedFact
    | RepeatedErrorCodeFact
    | StepShareFact
    | EvidenceCompletenessFact
]:
    """The deterministic facts, in a fixed order, from persisted metadata alone."""
    ordered_steps = sorted(steps, key=lambda step: step.step_order)
    step_ids = {step.step_id for step in ordered_steps}
    completed = set(completed_run_ids)
    failed = set(failed_run_ids)

    def _id(
        kind: str, step_id: UUID | None = None, error_code: str | None = None
    ) -> str:
        return finding_id(
            flow_id=flow_id,
            flow_version=flow_version,
            definition_checksum=definition_checksum,
            kind=kind,
            step_id=step_id,
            error_code=error_code,
        )

    facts: list[
        OutputNotObservedConsumedFact
        | RepeatedErrorCodeFact
        | StepShareFact
        | EvidenceCompletenessFact
    ] = []

    # Consumption: a step's output is observed consumed when any current
    # attempt in a completed run cites it as a step_result source. The final
    # step's output is the run's result and is never in question.
    consumed_step_ids: set[UUID] = set()
    runs_with_lineage: set[UUID] = set()
    for item in lineage:
        runs_with_lineage.add(item.flow_run_id)
        aggregate = item.edges.aggregate
        if item.flow_run_id not in completed or aggregate is None:
            continue
        for edge in aggregate.edges:
            if edge.source.kind == "step_result":
                consumed_step_ids.add(edge.source.source_step_id)
    if completed and len(ordered_steps) > 1:
        for step in ordered_steps[:-1]:
            if step.step_id not in consumed_step_ids:
                facts.append(
                    OutputNotObservedConsumedFact(
                        finding_id=_id("output_not_observed_consumed", step.step_id),
                        step_id=step.step_id,
                        step_order=step.step_order,
                        run_count=len(completed),
                    )
                )

    # Repeated error codes over the failed runs.
    error_runs: dict[tuple[UUID, str], set[UUID]] = defaultdict(set)
    metrics_by_run: dict[UUID, dict[UUID, FlowStepResultMetrics]] = defaultdict(dict)
    for metric in metrics:
        if metric.step_id not in step_ids:
            continue
        metrics_by_run[metric.flow_run_id][metric.step_id] = metric
        if (
            metric.flow_run_id in failed
            and metric.status == "failed"
            and metric.error_code
        ):
            error_runs[(metric.step_id, metric.error_code)].add(metric.flow_run_id)
    for step in ordered_steps:
        for (step_id, error_code), run_ids in sorted(
            error_runs.items(), key=lambda item: item[0][1]
        ):
            if step_id == step.step_id and len(run_ids) >= REPEATED_ERROR_MIN_RUNS:
                facts.append(
                    RepeatedErrorCodeFact(
                        finding_id=_id("repeated_error_code", step_id, error_code),
                        step_id=step_id,
                        step_order=step.step_order,
                        error_code=error_code,
                        run_count=len(run_ids),
                    )
                )

    # Token and latency share over completed runs with a measurable total.
    if len(ordered_steps) > 1:
        for kind, measure in (
            ("token_share", _tokens),
            ("latency_share", _seconds),
        ):
            shares: dict[UUID, list[float]] = defaultdict(list)
            for run_id in completed:
                per_step = {
                    step_id: measure(metric)
                    for step_id, metric in metrics_by_run.get(run_id, {}).items()
                }
                total = sum(value for value in per_step.values() if value is not None)
                if total <= 0:
                    continue
                for step in ordered_steps:
                    value = per_step.get(step.step_id)
                    shares[step.step_id].append((value or 0.0) / total)
            for step in ordered_steps:
                samples = shares.get(step.step_id)
                if not samples:
                    continue
                share = sum(samples) / len(samples)
                if share >= STEP_SHARE_THRESHOLD:
                    facts.append(
                        StepShareFact(
                            finding_id=_id(kind, step.step_id),
                            kind=kind,  # type: ignore[arg-type]
                            step_id=step.step_id,
                            step_order=step.step_order,
                            share=round(share, 3),
                            run_count=len(samples),
                        )
                    )

    # Completeness of the evidence the facts above were computed from.
    read_runs = completed | failed
    runs_with_all = sum(
        1
        for run_id in read_runs
        if step_ids <= set(metrics_by_run.get(run_id, {}).keys())
    )
    facts.append(
        EvidenceCompletenessFact(
            finding_id=_id("evidence_completeness"),
            runs_with_all_step_results=runs_with_all,
            runs_missing_step_results=len(read_runs) - runs_with_all,
            runs_without_lineage=len(read_runs - runs_with_lineage),
        )
    )
    return facts


def _tokens(metric: FlowStepResultMetrics) -> float | None:
    if metric.num_tokens_input is None and metric.num_tokens_output is None:
        return None
    return float((metric.num_tokens_input or 0) + (metric.num_tokens_output or 0))


def _seconds(metric: FlowStepResultMetrics) -> float | None:
    if metric.started_at is None or metric.finished_at is None:
        return None
    return max((metric.finished_at - metric.started_at).total_seconds(), 0.0)


class FlowReviewFlowRepository(Protocol):
    async def get(self, *, flow_id: UUID, tenant_id: UUID) -> object: ...


class FlowReviewVersionRepository(Protocol):
    async def get(self, flow_id: UUID, version: int, tenant_id: UUID) -> object: ...


class FlowReviewRunRepository(Protocol):
    async def list_statuses(
        self,
        *,
        tenant_id: UUID,
        flow_id: UUID | None = None,
        statuses: Sequence[FlowRunStatus] | None = None,
        principal_user_id: UUID | None = None,
        principal_service_id: UUID | None = None,
        limit: int | None = None,
        offset: int | None = None,
    ) -> list[FlowRunStatusSnapshot]: ...

    async def list_step_result_metrics(
        self, *, tenant_id: UUID, run_ids: Sequence[UUID]
    ) -> list[FlowStepResultMetrics]: ...

    async def list_current_attempt_lineage(
        self, *, tenant_id: UUID, run_ids: Sequence[UUID]
    ) -> list[FlowStepLineage]: ...


class FlowReviewAccessPolicy(Protocol):
    async def ensure_can_access_run(
        self, run: FlowRunStatusSnapshot, *, access_kind: str
    ) -> None: ...


class AIBuilderFlowReviewService:
    def __init__(
        self,
        *,
        user: UserInDB,
        flow_repo: FlowReviewFlowRepository,
        flow_run_repo: FlowReviewRunRepository,
        flow_version_repo: FlowReviewVersionRepository,
        access_policy: FlowReviewAccessPolicy,
    ) -> None:
        self.user = user
        self.flow_repo = flow_repo
        self.flow_run_repo = flow_run_repo
        self.flow_version_repo = flow_version_repo
        self.access_policy = access_policy

    async def build_packet(self, *, flow_id: UUID, space_id: UUID) -> FlowReviewPacket:
        tenant_id = self.user.tenant_id
        flow = await self.flow_repo.get(flow_id=flow_id, tenant_id=tenant_id)
        if getattr(flow, "space_id", None) != space_id:
            raise AIBuilderBadRequestException(
                "Flow space does not match the AI builder session space.",
                code=AIBuilderErrorCode.FLOW_SPACE_MISMATCH,
            )
        published_version = getattr(flow, "published_version", None)
        if published_version is None:
            raise AIBuilderBadRequestException(
                "The flow has no published version to review runs of.",
                code=AIBuilderErrorCode.FLOW_NOT_PUBLISHED,
            )
        version = await self.flow_version_repo.get(
            flow_id, published_version, tenant_id
        )
        definition_checksum = str(getattr(version, "definition_checksum"))
        steps = parse_published_runtime_steps(
            getattr(version, "definition_json"), flow_version=published_version
        )

        snapshots = await self.flow_run_repo.list_statuses(
            tenant_id=tenant_id,
            flow_id=flow_id,
            statuses=[FlowRunStatus.COMPLETED, FlowRunStatus.FAILED],
            limit=COHORT_SCAN_LIMIT,
        )
        completed: list[UUID] = []
        failed: list[UUID] = []
        omitted = {"other_version": 0, "not_viewable": 0, "level_unknown": 0}
        level = 0
        for run in snapshots:
            if run.flow_version != published_version:
                omitted["other_version"] += 1
                continue
            bucket = completed if run.status == FlowRunStatus.COMPLETED else failed
            limit = (
                COHORT_COMPLETED_LIMIT
                if run.status == FlowRunStatus.COMPLETED
                else COHORT_FAILED_LIMIT
            )
            if len(bucket) >= limit:
                continue
            try:
                await self.access_policy.ensure_can_access_run(
                    run, access_kind="evidence_view"
                )
            except UnauthorizedException:
                omitted["not_viewable"] += 1
                continue
            if run.evidence_classification_level is None:
                omitted["level_unknown"] += 1
                continue
            level = max(level, run.evidence_classification_level)
            bucket.append(run.id)

        run_ids = [*completed, *failed]
        metrics = await self.flow_run_repo.list_step_result_metrics(
            tenant_id=tenant_id, run_ids=run_ids
        )
        lineage = await self.flow_run_repo.list_current_attempt_lineage(
            tenant_id=tenant_id, run_ids=run_ids
        )
        facts = review_facts(
            flow_id=flow_id,
            flow_version=published_version,
            definition_checksum=definition_checksum,
            steps=steps,
            completed_run_ids=completed,
            failed_run_ids=failed,
            metrics=metrics,
            lineage=lineage,
        )
        return FlowReviewPacket(
            flow_id=flow_id,
            flow_version=published_version,
            definition_checksum=definition_checksum,
            generated_at=datetime.now(timezone.utc),
            evidence_classification_level=level,
            steps=[
                FlowReviewStep(
                    step_id=step.step_id,
                    step_order=step.step_order,
                    label=step.user_description,
                )
                for step in sorted(steps, key=lambda step: step.step_order)
            ],
            cohort=FlowReviewCohort(
                completed_run_ids=completed,
                failed_run_ids=failed,
                omitted=FlowReviewOmittedRuns(**omitted),
            ),
            facts=list(facts),
        )

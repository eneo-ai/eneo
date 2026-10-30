"""A step over material larger than its model's window, end to end.

The step's model is a small fake with a 3 000-token window. The step input is
several times larger, so the step reads it in segments with the step's own
model, every call through the executor's provider path, and answers over the
merged notes. The runs below check the answer, the coverage record, the
provider-call receipts and the token usage, and what partial coverage and a
step deadline do.
"""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Awaitable, Callable
from contextlib import nullcontext
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from dependency_injector import providers

from eneo.ai_models.completion_models.completion_model import Completion
from eneo.completion_models.domain.model_capacity import ModelCapacity
from eneo.completion_models.domain.request_preflight import (
    CompletionRequestPackage,
    CompletionRequestPreflight,
)
from eneo.completion_models.infrastructure.context_builder import (
    ContextWindowExceededError,
    count_tokens,
)
from eneo.database.database import sessionmanager
from eneo.database.tables.flow_tables import (
    FlowProviderCalls,
    FlowStepAttempts,
    FlowStepResults,
)
from eneo.database.tables.token_usage_table import ProviderTokenUsages
from eneo.flows.assistant_execution_snapshot import build_assistant_execution_snapshot
from eneo.flows.domain.flow import Flow, FlowPersistedJsonObject, FlowStep
from eneo.flows.domain.provider_call import DigestCallInput
from eneo.flows.flow_review_policy import FlowStepReviewMode, FlowStepReviewPolicy
from eneo.flows.infrastructure.flow_provider_call_repo import (
    FlowProviderCallRepository,
)
from eneo.flows.infrastructure.flow_repo import FlowRepository
from eneo.flows.infrastructure.flow_version_repo import FlowVersionRepository
from eneo.flows.published_definition import build_published_definition_json
from eneo.flows.runtime.executor import FlowRunExecutor, FlowRunExecutorConfig
from eneo.flows.runtime.flow_run_actor import FlowRunActor
from eneo.flows.runtime.tasks import enable_autobegin_for_flow_task_session
from eneo.main.container.container import Container
from eneo.model_providers.domain.provider_call_observer import (
    CompletionCallResultFacts,
    build_provider_call_request_facts,
)
from eneo.tokens.token_utils import TokenCount, TokenCountSource
from tests.integration.flows.test_flow_runtime_worker_contract import (
    _RuntimeAssistant,  # pyright: ignore[reportPrivateUsage]
)

pytestmark = pytest.mark.usefixtures("object_content_runtime_ready")

MODEL = "gpt-4o-mini"
WINDOW = 3_000
MAX_OUTPUT = 1_500
FRAMING_TOKENS = 8
_FACT = re.compile(r"FACT-\d{4}")
_KEY = re.compile(r"\[(S\d+)\]")
FACTS_CONTRACT: FlowPersistedJsonObject = {
    "type": "object",
    "properties": {"facts": {"type": "array", "items": {"type": "string"}}},
    "required": ["facts"],
    "additionalProperties": False,
}


def tokens(text: str) -> int:
    return count_tokens(text, MODEL)


def long_material(paragraphs: int = 150) -> tuple[str, set[str]]:
    facts = [f"FACT-{index:04d}" for index in range(1, paragraphs + 1)]
    text = "\n\n".join(
        f"Paragraph {index}. The committee recorded {fact} after a long discussion "
        "about budgets, schools, roads and the library, and noted that the matter "
        "returns at the next meeting with a written proposal from the office."
        for index, fact in enumerate(facts, start=1)
    )
    return text, set(facts)


class _SmallWindowAssistant(_RuntimeAssistant):
    """The step's assistant on a model with a small window.

    Each request is measured as its prompt and question; notes list the fact
    codes their segment holds, merges keep them with their source keys, and
    the step's own call answers with every code its notes carry.
    """

    def __init__(
        self,
        *,
        json_answer: bool = False,
        failing_facts: frozenset[str] = frozenset(),
        call_seconds: float = 0.0,
        after_call: Callable[[int], Awaitable[None]] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.json_answer = json_answer
        self.failing_facts = failing_facts
        self.call_seconds = call_seconds
        self.after_call = after_call
        self.questions: list[str] = []

    def _package(
        self,
        *,
        prompt: str,
        question: str,
        reserve: int,
        response_format: dict[str, Any] | None,
    ) -> CompletionRequestPackage:
        size = tokens(prompt) + tokens(question) + FRAMING_TOKENS
        cap = min(MAX_OUTPUT, WINDOW - size)
        return CompletionRequestPackage(
            messages=[],
            tools=[],
            response_format=response_format,
            input_reserve=TokenCount(size, TokenCountSource.LITELLM),
            useful_output_reserve_tokens=reserve,
            output_cap_tokens=cap if cap >= 1 else None,
        )

    async def preflight_response_context(
        self,
        question: str,
        completion_service: Any,
        files: Any = None,
        prompt_override: str | None = None,
        version: int = 1,
        *,
        model_kwargs: Any = None,
        info_blob_chunks: Any = None,
        capability_fallback_prompt: str | None = None,
        useful_output_reserve_tokens: int = 256,
    ) -> CompletionRequestPreflight:
        prompt = prompt_override if prompt_override is not None else self.prompt.text
        preferred = self._package(
            prompt=prompt,
            question=question,
            reserve=useful_output_reserve_tokens,
            response_format=(
                model_kwargs.response_format if model_kwargs is not None else None
            ),
        )
        fallback = (
            self._package(
                prompt=capability_fallback_prompt,
                question=question,
                reserve=useful_output_reserve_tokens,
                response_format=None,
            )
            if capability_fallback_prompt is not None
            else None
        )
        refused = not preferred.fits and (fallback is None or not fallback.fits)
        return CompletionRequestPreflight(
            model_route=f"openai/{MODEL}",
            capacity=ModelCapacity(WINDOW, MAX_OUTPUT),
            retrieval_included=info_blob_chunks is not None,
            preferred=preferred,
            fallback=fallback,
            refusal="current_request_input_does_not_fit" if refused else None,
        )

    def _answer(self, prompt: str, question: str) -> str:
        facts = _FACT.findall(question)
        if prompt.startswith("You take notes from one segment"):
            return "Date: unknown\n" + (" ".join(facts) or "NOT_RELEVANT")
        if prompt.startswith("Merge notes taken from consecutive segments"):
            match = _KEY.match(question)
            assert match is not None
            return f"Date: unknown\n[{match.group(1)}] " + " ".join(facts)
        if prompt.startswith("Merge notes from several documents"):
            keys = sorted(set(_KEY.findall(question)))
            return " ".join(f"[{key}]" for key in keys) + " " + " ".join(facts)
        if self.json_answer:
            return json.dumps({"facts": facts})
        return "Facts: " + " ".join(facts)

    async def get_response(  # type: ignore[override]
        self,
        *,
        question: str,
        completion_service: Any,
        model_kwargs: Any = None,
        prompt_override: str | None = None,
        provider_call_observer: Any = None,
        provider_call_reason: Any = "initial",
        useful_output_reserve_tokens: int | None = None,
        reject_context_over_limit: bool = False,
        **_: Any,
    ) -> Any:
        prompt = prompt_override if prompt_override is not None else self.prompt.text
        reserve = useful_output_reserve_tokens or 256
        size = tokens(prompt) + tokens(question) + FRAMING_TOKENS
        if reject_context_over_limit and size + reserve > WINDOW:
            raise ContextWindowExceededError(
                estimated_tokens=size, max_tokens=WINDOW - reserve
            )
        self.questions.append(question)
        response_format = (
            model_kwargs.response_format if model_kwargs is not None else None
        )
        facts = build_provider_call_request_facts(
            requested_model=MODEL,
            provider="openai",
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": question},
            ],
            request_kwargs=(
                {"response_format": response_format} if response_format else {}
            ),
            reason=provider_call_reason,
        )
        call_id = await provider_call_observer.started(facts)
        if self.call_seconds:
            await asyncio.sleep(self.call_seconds)
        if self.failing_facts.intersection(
            _FACT.findall(question)
        ) and prompt.startswith("You take notes from one segment"):
            await provider_call_observer.rejected(call_id, "provider_rejected")
            raise RuntimeError("The provider refused the request.")
        text = self._answer(prompt, question)
        output_tokens = tokens(text)
        await provider_call_observer.completed(
            call_id,
            CompletionCallResultFacts(
                response_model=MODEL,
                provider_response_id=f"resp-{uuid4()}",
                num_tokens_input=size,
                num_tokens_output=output_tokens,
            ),
        )
        if self.after_call is not None:
            await self.after_call(len(self.questions))
        return SimpleNamespace(
            completion=Completion(text=text, finish_reason="stop"),
            total_token_count=size + output_tokens,
            usage=SimpleNamespace(prompt_tokens=size, completion_tokens=output_tokens),
            model=SimpleNamespace(name=MODEL, provider_type="openai"),
        )


@dataclass(frozen=True)
class _Context:
    executor: FlowRunExecutor
    run_id: UUID
    flow_id: UUID
    tenant_id: UUID
    run_revision: int


async def _context(
    *,
    session: Any,
    admin_user: Any,
    test_tenant: Any,
    completion_model_factory: Any,
    space_factory: Any,
    assistant_factory: Any,
    material: str,
    output_type: str = "text",
    output_contract: FlowPersistedJsonObject | None = None,
    review: bool = False,
    timeout_seconds: int | None = None,
    assistant_options: dict[str, Any] | None = None,
) -> _Context:
    enable_autobegin_for_flow_task_session(session)
    container = Container(
        session=providers.Object(session),
        user=providers.Object(admin_user),
        tenant=providers.Object(test_tenant),
    )
    model = await completion_model_factory(session, MODEL)
    space = await space_factory(session, "Long material space", [model.id])
    assistant = await assistant_factory(
        session, "Long material assistant", model.id, space_id=space.id
    )
    review_policy = (
        FlowStepReviewPolicy(mode=FlowStepReviewMode.VIEW) if review else None
    )
    input_config: FlowPersistedJsonObject = {"long_material": {"mode": "digest"}}
    flow_repo = FlowRepository(session=session)
    flow = await flow_repo.create(
        flow=Flow(
            id=None,
            tenant_id=admin_user.tenant_id,
            space_id=space.id,
            name="Long material flow",
            description="Reads more than its model can hold.",
            created_by_user_id=admin_user.id,
            owner_user_id=admin_user.id,
            published_version=None,
            metadata_json={
                "evidence_policy": {"allow_export": True},
                "form_schema": {"fields": [{"name": "material", "type": "text"}]},
            },
            data_retention_days=30,
            created_at=None,
            updated_at=None,
            steps=[
                FlowStep(
                    id=None,
                    flow_id=uuid4(),
                    tenant_id=admin_user.tenant_id,
                    assistant_id=assistant.id,
                    step_order=1,
                    user_description="List the facts",
                    input_source="flow_input",
                    input_type="text",
                    input_contract=None,
                    output_mode="pass_through",
                    output_type=output_type,
                    output_contract=output_contract,
                    input_bindings={"question": "{{flow.input.material}}"},
                    output_classification_override=None,
                    input_config=input_config,
                    output_config=None,
                    review_policy=review_policy,
                    timeout_seconds=timeout_seconds,
                )
            ],
        ),
        tenant_id=admin_user.tenant_id,
    )
    runtime_assistant = _SmallWindowAssistant(
        assistant_id=assistant.id,
        model_id=model.id,
        provider_id=model.provider_id,
        model_name=MODEL,
        prompt_text="List every fact code the material records.",
        **(assistant_options or {}),
    )
    snapshot = build_assistant_execution_snapshot(assistant=runtime_assistant)
    step = flow.steps[0]
    definition_step: dict[str, object] = {
        "step_id": str(step.id),
        "assistant_id": str(step.assistant_id),
        "step_order": 1,
        "user_description": step.user_description,
        "input_source": step.input_source,
        "input_type": step.input_type,
        "input_bindings": step.input_bindings,
        "input_config": input_config,
        "output_mode": step.output_mode,
        "output_type": step.output_type,
        "assistant_snapshot": snapshot,
    }
    if output_contract is not None:
        definition_step["output_contract"] = output_contract
    if review_policy is not None:
        definition_step["review_policy"] = review_policy.model_dump(mode="json")
    if timeout_seconds is not None:
        definition_step["timeout_seconds"] = timeout_seconds
    await FlowVersionRepository(session=session).create(
        flow_id=flow.id,
        version=1,
        definition_json=build_published_definition_json(
            flow_id=flow.id,
            name=flow.name,
            description=flow.description,
            metadata_json=flow.metadata_json,
            steps=[definition_step],
        ),
        tenant_id=admin_user.tenant_id,
    )
    flow = await flow_repo.update(
        flow=flow.model_copy(update={"published_version": 1}),
        tenant_id=admin_user.tenant_id,
    )
    created = await container.flow_run_service().create_run(
        flow_id=flow.id,
        input_payload_json={"material": material},
        expected_flow_version=1,
        step_inputs=None,
        idempotency_key=f"long-material-{uuid4()}",
    )
    worker = Container(
        session=providers.Object(session), tenant=providers.Object(test_tenant)
    )
    executor = FlowRunExecutor(
        read_audit_service=lambda: nullcontext(executor.audit_service),
        runtime_actor=FlowRunActor.from_user(user=admin_user),
        session=session,
        flow_repo=worker.flow_repo(),
        flow_run_repo=worker.flow_run_repo(),
        flow_run_review_checkpoint_repo=worker.flow_run_review_checkpoint_repo(),
        flow_run_terminalizer=worker.flow_run_terminalizer(),
        flow_version_repo=worker.flow_version_repo(),
        space_repo=worker.tenant_scoped_space_repo(),
        completion_service=SimpleNamespace(),
        file_repo=worker.file_repo(),
        file_content_loader=worker.file_content_loader(),
        file_service=worker.file_service(user=admin_user),
        template_asset_repo=worker.flow_template_asset_repo(),
        encryption_service=worker.encryption_service(),
        audit_service=SimpleNamespace(log_async=AsyncMock(return_value=uuid4())),
        references_service=worker.references_service(
            datastore__create_embeddings_service__user=admin_user
        ),
        config=FlowRunExecutorConfig(
            max_inline_text_bytes=1024 * 1024,
            http_request_timeout_seconds=2.0,
            http_max_timeout_seconds=2.0,
            http_allow_private_networks=False,
        ),
    )

    async def load_assistant(assistant_id, state, *, snapshot=None):
        if state.flow_space is None:
            state.flow_space = await executor.space_repo.get_execution_space(
                flow.space_id
            )
        return runtime_assistant

    executor._load_assistant = AsyncMock(side_effect=load_assistant)  # pyright: ignore[reportPrivateUsage]
    assert flow.id is not None
    await session.commit()
    return _Context(
        executor=executor,
        run_id=created.run.id,
        flow_id=flow.id,
        tenant_id=admin_user.tenant_id,
        run_revision=created.run.revision,
    )


async def _execute(context: _Context) -> dict[str, Any]:
    return await context.executor.execute(
        run_id=context.run_id,
        flow_id=context.flow_id,
        tenant_id=context.tenant_id,
        run_revision=context.run_revision,
        dispatch_task_id=f"long-material-{uuid4()}",
        retry_count=0,
    )


async def _step_state(
    run_id: UUID,
) -> tuple[FlowStepResults, FlowStepAttempts, list[FlowProviderCalls], list[Any]]:
    async with sessionmanager.session() as session:
        enable_autobegin_for_flow_task_session(session)
        step = await session.scalar(
            sa.select(FlowStepResults).where(FlowStepResults.flow_run_id == run_id)
        )
        attempt = await session.scalar(
            sa.select(FlowStepAttempts).where(FlowStepAttempts.flow_run_id == run_id)
        )
        assert step is not None and attempt is not None
        receipts = list(
            await session.scalars(
                sa.select(FlowProviderCalls)
                .where(FlowProviderCalls.flow_step_attempt_id == attempt.id)
                .order_by(FlowProviderCalls.ordinal)
            )
        )
        usages = list(
            await session.scalars(
                sa.select(ProviderTokenUsages).where(
                    ProviderTokenUsages.source_id.in_([r.id for r in receipts])
                )
            )
        )
    return step, attempt, receipts, usages


def _stages(receipts: list[FlowProviderCalls]) -> list[str]:
    return [(receipt.digest_call or {}).get("stage", "") for receipt in receipts]


async def test_a_structured_step_digests_material_larger_than_its_window(
    setup_database,
    admin_user,
    test_tenant,
    completion_model_factory,
    space_factory,
    assistant_factory,
):
    material, facts = long_material()
    assert tokens(material) > 2 * WINDOW
    async with sessionmanager.session() as session:
        context = await _context(
            session=session,
            admin_user=admin_user,
            test_tenant=test_tenant,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
            assistant_factory=assistant_factory,
            material=material,
            output_type="json",
            output_contract=FACTS_CONTRACT,
            assistant_options={"json_answer": True},
        )
        result = await _execute(context)

    assert result["status"] == "completed"
    step, attempt, receipts, usages = await _step_state(context.run_id)

    # The answer is the step's own structured output over the notes.
    structured = step.output_payload_json["structured"]
    assert set(structured["facts"]) == facts

    coverage = step.input_payload_json["long_material"]
    assert coverage["coverage"] == "complete"
    assert coverage["reasons"] == [] and coverage["left_out"] == []
    [source] = coverage["sources"]
    assert source["complete"] and source["key"] == "S1"
    assert source["segments_read"] == list(range(1, source["segments_planned"] + 1))
    assert source["segments_planned"] > 3
    assert any(
        diagnostic["code"] == "long_material_digest"
        for diagnostic in step.input_payload_json["diagnostics"]
    )
    # What the step received stays the material itself.
    assert step.input_payload_json["text"] == material

    stages = _stages(receipts)
    assert stages.count("map") == coverage["map_calls"] == source["segments_planned"]
    assert stages.count("reduce") == coverage["reduce_calls"] >= 1
    assert stages[-1] == "final" and stages.count("final") == 1
    map_calls = [r.digest_call for r in receipts if r.digest_call["stage"] == "map"]
    assert sorted(call["segment_index"] for call in map_calls) == list(
        range(1, source["segments_planned"] + 1)
    )
    assert all(call["source_indexes"] == [1] for call in map_calls)
    assert receipts[-1].digest_call["source_indexes"] == [1]
    assert {receipt.requested_model for receipt in receipts} == {MODEL}
    assert {receipt.status for receipt in receipts} == {"completed"}
    assert receipts[-1].response_format != "none"
    assert all(r.response_format == "none" for r in receipts[:-1])

    # The evidence read model parses each call's stage and sources.
    async with sessionmanager.session() as session:
        enable_autobegin_for_flow_task_session(session)
        page = await FlowProviderCallRepository(session).list_evidence_page(
            run_id=context.run_id, tenant_id=context.tenant_id, limit=200
        )
    assert [item.digest_call for item in page.items] == [
        DigestCallInput.model_validate(receipt.digest_call) for receipt in receipts
    ]

    # Every call is in the step's token usage and in the usage ledger.
    assert step.num_tokens_input == sum(r.num_tokens_input for r in receipts)
    assert step.num_tokens_output == sum(r.num_tokens_output for r in receipts)
    assert len(usages) == len(receipts)
    assert sum(usage.input_tokens for usage in usages) == step.num_tokens_input
    assert attempt.num_tokens_input == step.num_tokens_input


@pytest.mark.parametrize("review", [False, True])
async def test_partial_coverage_fails_the_step_or_goes_to_its_review(
    review,
    setup_database,
    admin_user,
    test_tenant,
    completion_model_factory,
    space_factory,
    assistant_factory,
):
    material, facts = long_material()
    async with sessionmanager.session() as session:
        context = await _context(
            session=session,
            admin_user=admin_user,
            test_tenant=test_tenant,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
            assistant_factory=assistant_factory,
            material=material,
            review=review,
            assistant_options={"failing_facts": frozenset({"FACT-0030"})},
        )
        result = await _execute(context)

    step, _, receipts, _ = await _step_state(context.run_id)
    coverage = step.input_payload_json["long_material"]
    [source] = coverage["sources"]
    assert coverage["coverage"] == "partial"
    assert "failed segments" in coverage["reasons"]
    assert coverage["left_out"] == ["S1"]
    assert source["segments_failed"] and not source["complete"]
    assert coverage["failed_calls"] == len(source["segments_failed"])
    rejected = [receipt for receipt in receipts if receipt.status == "rejected"]
    assert len(rejected) == len(source["segments_failed"])
    assert all(receipt.digest_call["stage"] == "map" for receipt in rejected)

    if not review:
        assert result["status"] == "failed"
        assert step.status == "failed"
        assert step.error_code == "flow_long_material_partial_coverage"
        assert "S1 'Step input' (segments" in step.error_message
        assert "final" not in _stages(receipts)
        return

    assert result == {"status": "awaiting_review"}
    assert step.status == "completed"
    assert "FACT-0030" not in step.output_payload_json["text"]
    assert set(_FACT.findall(step.output_payload_json["text"])) < facts
    [warning] = [
        diagnostic
        for diagnostic in step.input_payload_json["diagnostics"]
        if diagnostic["code"] == "long_material_partial_coverage"
    ]
    assert warning["severity"] == "warning"
    assert _stages(receipts)[-1] == "final"


async def test_a_digest_stops_at_the_step_deadline_and_reports_what_it_left_out(
    setup_database,
    admin_user,
    test_tenant,
    completion_model_factory,
    space_factory,
    assistant_factory,
):
    material, _ = long_material()
    async with sessionmanager.session() as session:
        context = await _context(
            session=session,
            admin_user=admin_user,
            test_tenant=test_tenant,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
            assistant_factory=assistant_factory,
            material=material,
            timeout_seconds=4,
            assistant_options={"call_seconds": 0.4},
        )
        loop = asyncio.get_running_loop()
        started = loop.time()
        result = await _execute(context)
        elapsed = loop.time() - started

    assert result["status"] == "failed"
    step, _, receipts, _ = await _step_state(context.run_id)
    assert step.error_code == "flow_long_material_partial_coverage"
    coverage = step.input_payload_json["long_material"]
    [source] = coverage["sources"]
    assert coverage["coverage"] == "partial"
    assert "deadline" in coverage["reasons"]
    assert source["segments_not_read"]
    assert len(source["segments_read"]) < source["segments_planned"]
    # No digest call ran into the final call's share of the step's four seconds.
    assert elapsed < 4
    assert "final" not in _stages(receipts)


async def test_a_run_cancelled_mid_digest_ends_like_any_cancelled_step(
    setup_database,
    db_container,
    admin_user,
    test_tenant,
    completion_model_factory,
    space_factory,
    assistant_factory,
):
    material, _ = long_material()
    ids: dict[str, UUID] = {}

    async def cancel_after_third_call(calls: int) -> None:
        if calls == 3:
            async with db_container() as container:
                await container.flow_run_service().cancel_run(
                    run_id=ids["run"], flow_id=ids["flow"]
                )

    async with sessionmanager.session() as session:
        context = await _context(
            session=session,
            admin_user=admin_user,
            test_tenant=test_tenant,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
            assistant_factory=assistant_factory,
            material=material,
            assistant_options={"after_call": cancel_after_third_call},
        )
        ids.update(run=context.run_id, flow=context.flow_id)
        result = await _execute(context)

    assert result == {"status": "skipped", "reason": "run_cancelled"}
    _, attempt, receipts, _ = await _step_state(context.run_id)
    assert attempt.status == "cancelled"
    # The call in flight when the run was cancelled finished; no other started.
    assert _stages(receipts) == ["map", "map", "map"]

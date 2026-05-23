"""Mock-backed proposal-turn doubles shared by proposal processor/submission tests."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from intric.flows.ai_builder.ai_builder_description_semantics import (
    DescriptionProvenance,
    description_hash,
)
from intric.flows.ai_builder.ai_builder_domain_models import PlannerPlanEnvelope
from intric.flows.ai_builder.ai_builder_proposal_processor import (
    AIBuilderProposalProcessor,
)
from intric.flows.ai_builder.ai_builder_proposal_submission import (
    ProposalSubmissionOwner,
)


def _make_processor(**overrides: object) -> AIBuilderProposalProcessor:
    defaults = {
        "user": MagicMock(tenant_id=uuid4()),
        "repo": AsyncMock(),
        "litellm_client": AsyncMock(),
        "self_correction_temperature": 0.2,
        "self_correction_bumped_temperature": 0.5,
        "forced_proposal_temperature": 0.3,
        "quality_retry_warning_codes": set(),
    }
    defaults.update(overrides)
    return AIBuilderProposalProcessor(**defaults)


def _make_submission(**overrides: object) -> ProposalSubmissionOwner:
    defaults = {
        "repo": AsyncMock(),
        "litellm_client": AsyncMock(),
        "self_correction_temperature": 0.2,
        "self_correction_bumped_temperature": 0.5,
        "forced_proposal_temperature": 0.3,
        "quality_retry_warning_codes": frozenset(),
    }
    defaults.update(overrides)
    return ProposalSubmissionOwner(**defaults)


def _stored_plan_result(*, plan: object | None = None, envelope: object | None = None):
    return SimpleNamespace(
        plan=plan or MagicMock(id=uuid4()),
        envelope=envelope or MagicMock(),
        new_planning_state_version=1,
    )


def _flow_with_builder_description(description: str) -> SimpleNamespace:
    return SimpleNamespace(
        description=description,
        metadata_json={
            "ai_builder": {
                "description": DescriptionProvenance(
                    mode="builder_managed",
                    last_generated_hash=description_hash(description),
                ).model_dump(mode="json")
            }
        },
    )


async def _store_compiled_plan(**kwargs: object):
    return _stored_plan_result(
        envelope=PlannerPlanEnvelope(spec=kwargs["spec"]),
    )


def _make_response_with_tool_calls(
    *tool_calls: MagicMock,
    prompt_tokens: int | None = None,
    completion_tokens: int | None = None,
    total_tokens: int | None = None,
) -> SimpleNamespace:
    usage = (
        None
        if prompt_tokens is None and completion_tokens is None and total_tokens is None
        else SimpleNamespace(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
        )
    )
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                finish_reason="tool_calls",
                message=SimpleNamespace(
                    tool_calls=list(tool_calls),
                    content=None,
                ),
            )
        ],
        usage=usage,
    )


def _make_response_with_text(
    content: str,
    *,
    prompt_tokens: int | None = None,
    completion_tokens: int | None = None,
    total_tokens: int | None = None,
) -> SimpleNamespace:
    usage = (
        None
        if prompt_tokens is None and completion_tokens is None and total_tokens is None
        else SimpleNamespace(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
        )
    )
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                finish_reason="stop",
                message=SimpleNamespace(
                    tool_calls=None,
                    content=content,
                ),
            )
        ],
        usage=usage,
    )


def _make_tool_call(
    name: str, arguments: dict[str, object], tool_call_id: str | None = None
) -> MagicMock:
    tool_call = MagicMock()
    tool_call.id = tool_call_id or f"call_{uuid4().hex[:8]}"
    tool_call.function.name = name
    tool_call.function.arguments = json.dumps(arguments)
    return tool_call

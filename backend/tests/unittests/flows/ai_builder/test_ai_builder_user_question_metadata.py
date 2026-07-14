from __future__ import annotations

import json
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from eneo.ai_models.completion_models.completion_model import CompletionModel
from eneo.completion_models.domain.model_kwargs_capabilities import SupportedModelKwargs
from eneo.completion_models.infrastructure.completion_service import (
    CompletionService,
    ResolvedCompletionModelRoute,
)
from eneo.flows.ai_builder import (
    ai_builder_error_contract as error_contract_module,
)
from eneo.flows.ai_builder.ai_builder_domain_models import ConversationMessage
from eneo.flows.ai_builder.ai_builder_error_contract import (
    AIBuilderProviderOutcomeUnknownException,
)
from eneo.flows.ai_builder.ai_builder_user_question_metadata import (
    PreparedUserQuestionMetadata,
    resolve_user_question_metadata,
)
from eneo.model_providers.infrastructure.litellm_provider import (
    ResolvedLiteLLMProvider,
)
from eneo.tenants.tenant import TenantInDB


def _pending_question_conversation() -> list[ConversationMessage]:
    return [
        ConversationMessage(
            role="assistant",
            content=None,
            tool_calls=[
                {
                    "id": "tool-1",
                    "name": "ask_structured_question",
                    "arguments": {
                        "question_id": "terminal_output",
                        "question": "Output?",
                        "options": [
                            {
                                "id": "pdf_document",
                                "label": "PDF",
                                "value": "pdf_document",
                            }
                        ],
                    },
                }
            ],
        )
    ]


@pytest.mark.asyncio
async def test_auxiliary_adjudication_post_start_failure_emits_one_safe_event() -> None:
    litellm_client = MagicMock()
    litellm_client.acompletion = AsyncMock(
        side_effect=RuntimeError("sensitive-provider-material")
    )
    before_provider_call = AsyncMock()

    with patch.object(error_contract_module.logger, "info") as event_log:
        with pytest.raises(AIBuilderProviderOutcomeUnknownException):
            await resolve_user_question_metadata(
                litellm_client=litellm_client,
                conversation=_pending_question_conversation(),
                message="private-user-content",
                question_answer=None,
                completion_model_route=ResolvedCompletionModelRoute(
                    litellm_model="private-model",
                    litellm_kwargs={"api_key": "private-credential"},
                    supported_model_kwargs=SupportedModelKwargs(),
                ),
                prepared=PreparedUserQuestionMetadata(
                    metadata=None,
                    is_requirements_confirmation=False,
                    needs_auxiliary_llm=True,
                ),
                before_provider_call=before_provider_call,
            )

    before_provider_call.assert_awaited_once_with()
    assert litellm_client.acompletion.await_count == 1
    event_log.assert_called_once()
    payload = event_log.call_args.kwargs["extra"]
    assert payload["operation"] == "semantic_adjudication"
    assert payload["failure_kind"] == "unknown"
    encoded = str(payload)
    assert "sensitive-provider-material" not in encoded
    assert "private-user-content" not in encoded
    assert "private-model" not in encoded
    assert "private-credential" not in encoded


@pytest.mark.asyncio
async def test_auxiliary_adjudication_uses_resolved_route_at_provider_boundary() -> (
    None
):
    tenant = TenantInDB.model_construct(id=uuid4(), name="Test tenant")
    now = datetime.now(timezone.utc)
    model = CompletionModel(
        id=uuid4(),
        created_at=now,
        updated_at=now,
        name="gpt-test",
        nickname="GPT test",
        max_input_tokens=4096,
        max_output_tokens=1024,
        is_deprecated=False,
        vision=False,
        reasoning=False,
        tenant_id=tenant.id,
        provider_id=uuid4(),
        provider_type="openai",
        model_kwargs_capabilities=None,
    )
    provider = ResolvedLiteLLMProvider(
        id=model.provider_id,
        tenant_id=tenant.id,
        name="Test provider",
        provider_type="openai",
        credentials={"api_key": "test-only"},
        config={},
    )
    encryption_service = MagicMock()
    encryption_service.is_active.return_value = False
    completion_service = CompletionService(
        context_builder=MagicMock(),
        tenant=tenant,
        session=AsyncMock(),
        encryption_service=encryption_service,
    )
    provider_loader = AsyncMock(return_value=provider)
    with patch(
        "eneo.model_providers.infrastructure.litellm_provider.load_active_litellm_provider",
        new=provider_loader,
    ):
        route = await completion_service.resolve_model_route(model)

    events: list[str] = []

    async def complete(**_kwargs: object) -> SimpleNamespace:
        events.append("provider")
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content=json.dumps(
                            {
                                "selected_option_id": "pdf_document",
                                "reason": "PDF requested",
                            }
                        )
                    )
                )
            ]
        )

    async def mark_provider_started() -> None:
        events.append("started")

    litellm_client = MagicMock()
    litellm_client.acompletion = AsyncMock(side_effect=complete)
    result = await resolve_user_question_metadata(
        litellm_client=litellm_client,
        conversation=_pending_question_conversation(),
        message="PDF",
        question_answer=None,
        completion_model_route=route,
        prepared=PreparedUserQuestionMetadata(
            metadata=None,
            is_requirements_confirmation=False,
            needs_auxiliary_llm=True,
        ),
        before_provider_call=mark_provider_started,
    )

    assert result.used_auxiliary_llm is True
    assert events == ["started", "provider"]
    assert provider_loader.await_count == 1
    assert litellm_client.acompletion.await_count == 1
    outgoing = litellm_client.acompletion.await_args.kwargs
    assert outgoing["api_key"] == "test-only"
    assert "temperature" not in outgoing

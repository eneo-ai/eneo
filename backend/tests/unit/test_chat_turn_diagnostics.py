from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from eneo.conversations.conversation_models import ChatTurnDiagnostics
from eneo.conversations.conversations_router import get_chat_turn_diagnostics
from eneo.main.exceptions import NotFoundException, UnauthorizedException
from eneo.questions.question import MessageLogging
from eneo.questions.questions_repo import StoredSkillActivation
from eneo.sessions.sessions_repo import OwnedChatPartner
from eneo.skills.domain.skill import (
    SkillActivationEvidenceV1,
    SkillTurnEffectiveMode,
)


def _evidence() -> SkillActivationEvidenceV1:
    return SkillActivationEvidenceV1(
        effective_mode=SkillTurnEffectiveMode.EAGER,
        available=(),
        blocked=(),
        initially_active=(),
        selected_model_id=uuid4(),
        selected_model_route="gpt-4o",
        skill_context_tokens=0,
        skill_context_token_limit=1_000,
        token_count_source="litellm",
    )


def _container(
    *,
    partner: OwnedChatPartner | None,
    stored: StoredSkillActivation | None,
    assistant_error: Exception | None = None,
):
    user = SimpleNamespace(id=uuid4(), tenant_id=uuid4())
    session_repo = SimpleNamespace(
        get_owned_chat_partner=AsyncMock(return_value=partner)
    )
    question_repo = SimpleNamespace(
        get_skill_activation_evidence=AsyncMock(return_value=stored)
    )
    assistant_service = SimpleNamespace(
        get_assistant=AsyncMock(
            side_effect=assistant_error,
            return_value=(SimpleNamespace(), []),
        )
    )
    container = SimpleNamespace(
        user=lambda: user,
        session_repo=lambda: session_repo,
        question_repo=lambda: question_repo,
        assistant_service=lambda: assistant_service,
    )
    return container, user, session_repo, question_repo, assistant_service


async def _read(
    *,
    session_id: UUID,
    message_id: UUID,
    container,
    enabled: bool = True,
) -> ChatTurnDiagnostics:
    return await get_chat_turn_diagnostics(
        session_id=session_id,
        message_id=message_id,
        settings=SimpleNamespace(show_chat_debug_panel=enabled),
        container=container,
    )


async def test_disabled_diagnostics_do_not_resolve_the_session():
    session_id = uuid4()
    message_id = uuid4()
    container, _, session_repo, question_repo, _ = _container(
        partner=OwnedChatPartner(uuid4(), None),
        stored=StoredSkillActivation(_evidence()),
    )

    with pytest.raises(NotFoundException):
        await _read(
            session_id=session_id,
            message_id=message_id,
            container=container,
            enabled=False,
        )

    session_repo.get_owned_chat_partner.assert_not_awaited()
    question_repo.get_skill_activation_evidence.assert_not_awaited()


@pytest.mark.parametrize(
    "partner",
    [None, OwnedChatPartner(None, uuid4()), OwnedChatPartner(None, None)],
)
async def test_missing_or_unsupported_conversation_fails_before_evidence_load(partner):
    container, _, _, question_repo, _ = _container(
        partner=partner,
        stored=StoredSkillActivation(_evidence()),
    )

    with pytest.raises(NotFoundException):
        await _read(
            session_id=uuid4(),
            message_id=uuid4(),
            container=container,
        )

    question_repo.get_skill_activation_evidence.assert_not_awaited()


@pytest.mark.parametrize(
    "assistant_error",
    [NotFoundException("missing"), UnauthorizedException("revoked")],
)
async def test_revoked_assistant_access_fails_before_evidence_load(assistant_error):
    container, _, _, question_repo, _ = _container(
        partner=OwnedChatPartner(uuid4(), None),
        stored=StoredSkillActivation(_evidence()),
        assistant_error=assistant_error,
    )

    with pytest.raises(NotFoundException):
        await _read(
            session_id=uuid4(),
            message_id=uuid4(),
            container=container,
        )

    question_repo.get_skill_activation_evidence.assert_not_awaited()


async def test_message_must_belong_to_the_authorized_session():
    container, _, _, question_repo, _ = _container(
        partner=OwnedChatPartner(uuid4(), None),
        stored=None,
    )

    with pytest.raises(NotFoundException):
        await _read(
            session_id=uuid4(),
            message_id=uuid4(),
            container=container,
        )

    question_repo.get_skill_activation_evidence.assert_awaited_once()


@pytest.mark.parametrize("evidence", [_evidence(), None])
async def test_authorized_turn_returns_only_typed_diagnostics(evidence):
    session_id = uuid4()
    message_id = uuid4()
    assistant_id = uuid4()
    container, user, session_repo, question_repo, assistant_service = _container(
        partner=OwnedChatPartner(assistant_id, None),
        stored=StoredSkillActivation(evidence),
    )

    diagnostics = await _read(
        session_id=session_id,
        message_id=message_id,
        container=container,
    )

    assert diagnostics == ChatTurnDiagnostics(
        session_id=session_id,
        message_id=message_id,
        skill_activation=evidence,
    )
    session_repo.get_owned_chat_partner.assert_awaited_once_with(
        session_id=session_id,
        tenant_id=user.tenant_id,
        user_id=user.id,
    )
    assistant_service.get_assistant.assert_awaited_once_with(assistant_id)
    question_repo.get_skill_activation_evidence.assert_awaited_once_with(
        id=message_id,
        session_id=session_id,
        tenant_id=user.tenant_id,
    )


async def test_session_and_current_partner_are_authorized_before_evidence_load():
    order: list[str] = []
    container, _, session_repo, question_repo, assistant_service = _container(
        partner=OwnedChatPartner(uuid4(), None),
        stored=StoredSkillActivation(_evidence()),
    )
    session_repo.get_owned_chat_partner.side_effect = lambda **_: order.append(
        "session"
    ) or OwnedChatPartner(uuid4(), None)
    assistant_service.get_assistant.side_effect = lambda *_: order.append(
        "partner"
    ) or (SimpleNamespace(), [])
    question_repo.get_skill_activation_evidence.side_effect = lambda **_: order.append(
        "evidence"
    ) or StoredSkillActivation(_evidence())

    await _read(
        session_id=uuid4(),
        message_id=uuid4(),
        container=container,
    )

    assert order == ["session", "partner", "evidence"]


def test_response_contract_cannot_carry_chat_or_provider_bodies():
    diagnostics = ChatTurnDiagnostics(
        session_id=uuid4(),
        message_id=uuid4(),
        skill_activation=_evidence(),
    )

    payload = diagnostics.model_dump_json()

    assert set(diagnostics.model_dump()) == {
        "session_id",
        "message_id",
        "skill_activation",
    }
    for sentinel in ("secret-instructions", "provider-body", "incident-reason"):
        assert sentinel not in payload

    with pytest.raises(ValidationError):
        ChatTurnDiagnostics.model_validate(
            {
                **diagnostics.model_dump(mode="json"),
                "question": "secret-instructions",
            }
        )


def test_existing_insights_logging_contract_does_not_expose_skill_evidence():
    assert "skill_activation" not in MessageLogging.model_fields

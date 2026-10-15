"""The ask path resolves the reader model for the turn's space from the
tenant's accessible models, the space's choice and the policy."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from eneo.assistants.assistant_service import AssistantService


def _service(models) -> AssistantService:
    service = AssistantService.__new__(AssistantService)
    service.completion_model_crud_service = MagicMock()
    service.completion_model_crud_service.get_available_completion_models = AsyncMock(
        return_value=models
    )
    return service


def _model(*, reader: bool = False, meets: bool = True):
    return SimpleNamespace(
        id=uuid4(),
        is_org_reader=reader,
        supports_tool_calling=True,
        meets_security_classification=lambda classification: meets,
    )


def _space(turn, *, inherit=True, own=None, personal=False):
    return SimpleNamespace(
        is_personal=lambda: personal,
        completion_models=[turn] + ([own] if own else []),
        reader_model_inherit=inherit,
        reader_model=own,
        security_classification=None,
    )


async def test_the_organisation_default_is_resolved_for_the_turn():
    default, turn = _model(reader=True), _model()

    resolved = await _service([turn, default])._resolve_reader_model(
        space=_space(turn), effective_config=None, turn_model=turn
    )

    assert resolved.model is default
    assert resolved.reason == "inherited"


async def test_the_space_choice_wins_over_the_organisation_default():
    default, turn, own = _model(reader=True), _model(), _model()

    resolved = await _service([turn, default, own])._resolve_reader_model(
        space=_space(turn, inherit=False, own=own),
        effective_config=None,
        turn_model=turn,
    )

    assert resolved.model is own
    assert resolved.reason == "own"


async def test_a_default_below_the_space_floor_leaves_the_turn_on_one_model():
    default, turn = _model(reader=True, meets=False), _model()

    resolved = await _service([turn, default])._resolve_reader_model(
        space=_space(turn), effective_config=None, turn_model=turn
    )

    assert resolved.model is None
    assert resolved.reason == "tenant_default_below_classification"


async def test_no_organisation_default_leaves_the_turn_on_one_model_and_says_so():
    turn = _model()

    resolved = await _service([turn])._resolve_reader_model(
        space=_space(turn), effective_config=None, turn_model=turn
    )

    assert resolved.model is None
    assert resolved.reason == "no_tenant_default"

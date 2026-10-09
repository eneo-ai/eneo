from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from eneo.ai_models.completion_models.completion_model import ModelKwargs
from eneo.spaces.space_init_service import SpaceInitService


def _service(space):
    space.id = uuid4()
    space_service = MagicMock()
    space_service.get_space = AsyncMock(return_value=space)
    assistant_service = MagicMock()
    assistant_service.create_default_assistant = AsyncMock(
        return_value=SimpleNamespace(id=uuid4())
    )
    space_repo = MagicMock()
    space_repo.lock = AsyncMock()
    space_repo.one = AsyncMock(return_value=space)
    assistant_repo = MagicMock()
    assistant_repo.apply_update = AsyncMock()
    assistant_repo.add = AsyncMock()
    init_service = SpaceInitService(
        user=MagicMock(),
        space_service=space_service,
        assistant_service=assistant_service,
        space_repo=space_repo,
        assistant_repo=assistant_repo,
    )
    return init_service, assistant_service


async def test_get_space_does_not_recreate_default_when_load_failed():
    """A default row that exists but failed to load must NOT trigger creation
    of a replacement — that would orphan a duplicate default (no DB-level
    uniqueness before the partial index)."""
    space = SimpleNamespace(
        default_assistant=None,
        default_assistant_load_failed=True,
        add_assistant=MagicMock(),
    )
    init_service, assistant_service = _service(space)

    result = await init_service.get_space(uuid4())

    assistant_service.create_default_assistant.assert_not_awaited()
    assert result is space


async def test_get_space_creates_default_when_genuinely_missing():
    """No default row at all → create one, as before."""
    space = SimpleNamespace(
        default_assistant=None,
        default_assistant_load_failed=False,
        add_assistant=MagicMock(),
    )
    init_service, assistant_service = _service(space)

    await init_service.get_space(uuid4())

    assistant_service.create_default_assistant.assert_awaited_once()


# --- Personal assistant completion model repair -----------------------------


def _model(*, can_access=True, deleted_at=None, migrated_to_model_id=None):
    return SimpleNamespace(
        id=uuid4(),
        can_access=can_access,
        deleted_at=deleted_at,
        migrated_to_model_id=migrated_to_model_id,
    )


def _personal_space(*, current_model, space_models, org_default=None):
    assistant = SimpleNamespace(
        id=uuid4(),
        space_id=uuid4(),
        is_default=True,
        completion_model=current_model,
        update=MagicMock(),
    )
    space = SimpleNamespace(
        default_assistant=assistant,
        default_assistant_load_failed=False,
        completion_models=space_models,
        get_default_completion_model=MagicMock(
            return_value=org_default
            if org_default is not None
            else next((m for m in space_models if m.can_access), None)
        ),
    )
    return space, assistant


def _personal_service(space, effective_config=None):
    init_service, assistant_service = _service(space)
    init_service.space_service.get_personal_space = AsyncMock(return_value=space)
    if effective_config is not None:
        init_service.effective_config_service = MagicMock()
        init_service.effective_config_service.resolve_for = AsyncMock(
            return_value=effective_config
        )
    return init_service


def _policy(*, models_enforced, available_models=(), policy_default_model=None):
    return SimpleNamespace(
        models_enforced=models_enforced,
        available_models=list(available_models),
        policy_default_model=policy_default_model,
        locked_model=None,
    )


async def test_personal_space_assigns_default_model_when_assistant_has_none():
    """Created before the org had any model → repaired on the next load."""
    org_default = _model()
    space, assistant = _personal_space(
        current_model=None, space_models=[org_default], org_default=org_default
    )
    init_service = _personal_service(space)

    await init_service.get_personal_space()

    assistant.update.assert_called_once()
    assert assistant.update.call_args.kwargs["completion_model"] is org_default
    assert "completion_model_kwargs" in assistant.update.call_args.kwargs
    init_service.assistant_repo.apply_update.assert_awaited_once()
    args = init_service.assistant_repo.apply_update.await_args.args
    assert args[:2] == (assistant.id, assistant.space_id)
    assert args[2].completion_model_kwargs == ModelKwargs()
    # Only the assistant row is written; a full space rewrite would delete
    # sibling assistants the loader skipped as invalid.
    init_service.space_repo.lock.assert_not_awaited()


async def test_personal_space_replaces_deleted_model():
    deleted = _model(can_access=False, deleted_at=object())
    org_default = _model()
    space, assistant = _personal_space(
        current_model=deleted, space_models=[deleted, org_default]
    )
    init_service = _personal_service(space)

    await init_service.get_personal_space()

    assert assistant.update.call_args.kwargs["completion_model"] is org_default
    init_service.assistant_repo.apply_update.assert_awaited_once()
    args = init_service.assistant_repo.apply_update.await_args.args
    assert args[:2] == (assistant.id, assistant.space_id)
    assert args[2].completion_model_kwargs == ModelKwargs()


async def test_personal_space_replaces_disabled_model():
    disabled = _model(can_access=False)
    org_default = _model()
    space, assistant = _personal_space(
        current_model=disabled, space_models=[disabled, org_default]
    )
    init_service = _personal_service(space)

    await init_service.get_personal_space()

    assert assistant.update.call_args.kwargs["completion_model"] is org_default
    init_service.assistant_repo.apply_update.assert_awaited_once()
    args = init_service.assistant_repo.apply_update.await_args.args
    assert args[:2] == (assistant.id, assistant.space_id)
    assert args[2].completion_model_kwargs == ModelKwargs()


async def test_personal_space_keeps_usable_model():
    chosen = _model()
    org_default = _model()
    space, assistant = _personal_space(
        current_model=chosen,
        space_models=[chosen, org_default],
        org_default=org_default,
    )
    init_service = _personal_service(space)

    await init_service.get_personal_space()

    assistant.update.assert_not_called()
    init_service.assistant_repo.apply_update.assert_not_awaited()


async def test_personal_space_without_usable_models_leaves_assistant_alone():
    """All models disabled: no fallback, no write, and no exception from
    get_default_completion_model (which raises for a non-empty unusable list)."""
    disabled = _model(can_access=False)
    space, assistant = _personal_space(current_model=None, space_models=[disabled])
    space.get_default_completion_model = MagicMock(side_effect=AssertionError)
    init_service = _personal_service(space)

    await init_service.get_personal_space()

    assistant.update.assert_not_called()
    init_service.assistant_repo.apply_update.assert_not_awaited()


async def test_personal_space_without_any_models_leaves_assistant_alone():
    space, assistant = _personal_space(current_model=None, space_models=[])
    init_service = _personal_service(space)

    await init_service.get_personal_space()

    assistant.update.assert_not_called()
    init_service.assistant_repo.apply_update.assert_not_awaited()


async def test_personal_space_policy_does_not_override_users_choice():
    """A usable model outside the policy whitelist stays: the policy steers at
    ask time and must give the choice back when it is switched off."""
    chosen = _model()
    allowed = _model()
    space, assistant = _personal_space(
        current_model=chosen, space_models=[chosen, allowed]
    )
    init_service = _personal_service(
        space,
        effective_config=_policy(
            models_enforced=True,
            available_models=[allowed],
            policy_default_model=allowed,
        ),
    )

    await init_service.get_personal_space()

    assistant.update.assert_not_called()
    init_service.assistant_repo.apply_update.assert_not_awaited()


async def test_personal_space_policy_stores_policy_default_when_model_missing():
    org_default = _model()
    policy_default = _model()
    space, assistant = _personal_space(
        current_model=None,
        space_models=[org_default, policy_default],
        org_default=org_default,
    )
    init_service = _personal_service(
        space,
        effective_config=_policy(
            models_enforced=True,
            available_models=[policy_default],
            policy_default_model=policy_default,
        ),
    )

    await init_service.get_personal_space()

    assert assistant.update.call_args.kwargs["completion_model"] is policy_default
    init_service.assistant_repo.apply_update.assert_awaited_once()
    args = init_service.assistant_repo.apply_update.await_args.args
    assert args[:2] == (assistant.id, assistant.space_id)
    assert args[2].completion_model_kwargs == ModelKwargs()


async def test_personal_space_policy_with_empty_whitelist_leaves_assistant_alone():
    org_default = _model()
    space, assistant = _personal_space(
        current_model=None, space_models=[org_default], org_default=org_default
    )
    init_service = _personal_service(
        space, effective_config=_policy(models_enforced=True)
    )

    await init_service.get_personal_space()

    assistant.update.assert_not_called()
    init_service.assistant_repo.apply_update.assert_not_awaited()


async def test_personal_space_policy_off_falls_back_to_org_default():
    org_default = _model()
    space, assistant = _personal_space(
        current_model=None, space_models=[org_default], org_default=org_default
    )
    init_service = _personal_service(
        space, effective_config=_policy(models_enforced=False)
    )

    await init_service.get_personal_space()

    assert assistant.update.call_args.kwargs["completion_model"] is org_default

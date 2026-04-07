from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from intric.apps.apps.app_service import AppService
from intric.main.exceptions import UnauthorizedException


@pytest.fixture
def service():
    return AppService(
        user=MagicMock(),
        repo=AsyncMock(),
        space_repo=AsyncMock(),
        factory=MagicMock(),
        completion_model_crud_service=AsyncMock(),
        transcription_model_crud_service=AsyncMock(),
        file_service=AsyncMock(),
        prompt_service=AsyncMock(),
        transcriber=AsyncMock(),
        app_template_service=AsyncMock(),
        actor_manager=MagicMock(),
        completion_service=AsyncMock(),
        icon_repo=AsyncMock(),
    )


async def test_get_raise_unauthorized_if_can_not_access(
    service: AppService,
):
    actor = MagicMock()
    actor.can_read_apps.return_value = False
    service.actor_manager.get_space_actor_from_space.return_value = actor

    with pytest.raises(UnauthorizedException):
        await service.get_app(MagicMock())


async def test_update_raise_unauthorized_if_can_not_edit(
    service: AppService,
):
    actor = MagicMock()
    actor.can_edit_apps.return_value = False
    service.actor_manager.get_space_actor_from_space.return_value = actor

    with pytest.raises(UnauthorizedException):
        await service.update_app(MagicMock())


async def test_delete_raise_unauthorized_if_can_not_delete(
    service: AppService,
):
    actor = MagicMock()
    actor.can_delete_apps.return_value = False
    service.actor_manager.get_space_actor_from_space.return_value = actor

    with pytest.raises(UnauthorizedException):
        await service.delete_app(MagicMock())


async def test_publish_raise_unauthorized_has_actionable_message(
    service: AppService,
):
    space = MagicMock()
    space.get_app.return_value = MagicMock()
    service.space_repo.get_space_by_app.return_value = space

    actor = MagicMock()
    actor.can_publish_apps.return_value = False
    service.actor_manager.get_space_actor_from_space.return_value = actor

    with pytest.raises(UnauthorizedException) as exc_info:
        await service.publish_app(MagicMock(), True)

    assert "Publishing apps" in str(exc_info.value)


@pytest.mark.parametrize("template_in_space", [True, False])
async def test_create_from_template_prefers_template_model_when_available(
    service: AppService,
    template_in_space: bool,
):
    fallback_model = MagicMock(id=uuid4())
    template_model = MagicMock(id=uuid4())
    template = MagicMock(
        completion_model=template_model,
        prompt_text=None,
        input_type="text-field",
        input_description="Describe input",
        name="Template",
    )
    template.validate_wizard_data = MagicMock()

    template_data = MagicMock(id=uuid4())
    template_data.get_ids_by_type.return_value = []

    space = MagicMock()
    space.is_completion_model_in_space.return_value = template_in_space
    space.get_completion_model.return_value = template_model

    created_app = MagicMock()
    service.app_template_service.get_app_template.return_value = template
    service.file_service.get_file_infos.return_value = []
    service.factory.create_app_from_template.return_value = created_app
    service.repo.add.return_value = created_app

    await service._create_from_template(
        space=space,
        template_data=template_data,
        completion_model=fallback_model,
    )

    expected_model = template_model if template_in_space else fallback_model
    assert (
        service.factory.create_app_from_template.call_args.kwargs["completion_model"]
        == expected_model
    )


async def test_create_from_template_keeps_fallback_when_template_has_no_model(
    service: AppService,
):
    fallback_model = MagicMock(id=uuid4())
    template = MagicMock(
        completion_model=None,
        prompt_text=None,
        input_type="text-field",
        input_description="Describe input",
        name="Template",
    )
    template.validate_wizard_data = MagicMock()

    template_data = MagicMock(id=uuid4())
    template_data.get_ids_by_type.return_value = []

    created_app = MagicMock()
    service.app_template_service.get_app_template.return_value = template
    service.file_service.get_file_infos.return_value = []
    service.factory.create_app_from_template.return_value = created_app
    service.repo.add.return_value = created_app

    await service._create_from_template(
        space=MagicMock(),
        template_data=template_data,
        completion_model=fallback_model,
    )

    assert (
        service.factory.create_app_from_template.call_args.kwargs["completion_model"]
        == fallback_model
    )

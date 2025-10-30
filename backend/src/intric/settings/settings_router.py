from fastapi import APIRouter, Depends

from intric.authentication import auth_dependencies
from intric.files.audio import AudioMimeTypes
from intric.files.image import ImageMimeTypes
from intric.files.text import TextMimeTypes
from intric.main.container.container import Container
from intric.main.logging import get_logger
from intric.main.models import PaginatedResponse
from intric.server.dependencies.container import get_container
from intric.server.protocol import to_paginated_response
from intric.settings import settings_factory
from intric.settings.setting_service import SettingService
from intric.settings.settings import GetModelsResponse, SettingsPublic, TemplateSettingUpdate

logger = get_logger(__name__)

router = APIRouter()


@router.get("/", response_model=SettingsPublic)
async def get_settings(
    service: SettingService = Depends(
        settings_factory.get_settings_service_allowing_read_only_key
    ),
):
    return await service.get_settings()


@router.post("/", response_model=SettingsPublic)
async def upsert_settings(
    settings: SettingsPublic,
    container: Container = Depends(get_container(with_user=True)),
):
    """Omitted fields are not updated."""
    service = container.settings_service()
    return await service.update_settings(settings)


@router.get("/models/", response_model=GetModelsResponse)
async def get_models(
    container: Container = Depends(get_container(with_user=True)),
):
    """
    From the response:
        - use the `id` field as values for `completion_model`
        - use the `id` field as values for `embedding_model`

    in creating and updating `Assistants` and `Services`.
    """
    service = container.settings_service()
    completion_models = await service.get_available_completion_models()
    embedding_models = await service.get_available_embedding_models()

    return GetModelsResponse(
        completion_models=completion_models, embedding_models=embedding_models
    )


@router.get(
    "/formats/",
    response_model=PaginatedResponse[str],
    dependencies=[Depends(auth_dependencies.get_current_active_user)],
)
def get_formats():
    return to_paginated_response(
        TextMimeTypes.values() + AudioMimeTypes.values() + ImageMimeTypes.values()
    )


@router.patch(
    "/templates",
    response_model=SettingsPublic,
    summary="Toggle template feature",
    description="""
Enable or disable the template management feature for your tenant.

**Admin Only:** Requires admin permissions.

**Behavior:**
- Updates the `using_templates` feature flag for your tenant
- When disabled: Template gallery returns empty list (not error)
- When enabled: Users can see and use tenant templates
- Change takes effect immediately (no reload required)

**Example Request:**
```json
{
  "enabled": true
}
```

**Example Response:**
```json
{
  "chatbot_widget": {},
  "using_templates": true
}
```
    """,
)
async def update_template_setting(
    data: TemplateSettingUpdate,
    container: Container = Depends(get_container(with_user=True)),
):
    """
    Toggle template feature for tenant.

    Enables or disables the template management feature for the entire tenant.
    Only admin users can modify this setting.
    """
    service = container.settings_service()
    return await service.update_template_setting(enabled=data.enabled)

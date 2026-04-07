from typing import TYPE_CHECKING

from intric.templates.templates_factory import TemplatesFactory

if TYPE_CHECKING:
    from intric.templates.app_template.app_template_service import AppTemplateService
    from intric.templates.assistant_template.assistant_template_service import (
        AssistantTemplateService,
    )
    from intric.templates.templates import Templates


class TemplateService:
    def __init__(
        self,
        app_service: "AppTemplateService",
        assistant_service: "AssistantTemplateService",
    ) -> None:
        self.app_service = app_service
        self.assistant_service = assistant_service

    async def get_templates(self) -> "Templates":
        app_templates = await self.app_service.get_app_templates()  # type: ignore[call-overload]
        assistant_templates = await self.assistant_service.get_assistant_templates()  # type: ignore[call-overload]

        return TemplatesFactory.create_templates(
            apps=app_templates, assistants=assistant_templates
        )

from typing import TYPE_CHECKING

from intric.templates.assistant_template.assistant_template import AssistantTemplate
from intric.templates.assistant_template.api.assistant_template_models import (
    AssistantTemplateWizard,
)


if TYPE_CHECKING:
    from intric.database.tables.assistant_template_table import (
        AssistantTemplates as AssistantTemplateDBModel,
    )


class AssistantTemplateFactory:
    @staticmethod
    def create_assistant_template(
        item: "AssistantTemplateDBModel",
    ) -> AssistantTemplate:
        wizard = AssistantTemplateWizard(**item.wizard)
        return AssistantTemplate(
            id=item.id,
            name=item.name,
            description=item.description,
            category=item.category,
            prompt_text=item.prompt_text,
            completion_model_kwargs=item.completion_model_kwargs,
            wizard=wizard,
            completion_model=item.completion_model,
            updated_at=item.updated_at,
            created_at=item.created_at,
            organization=item.organization,
            tenant_id=item.tenant_id,
            deleted_at=item.deleted_at,
            original_snapshot=item.original_snapshot,
        )

    @staticmethod
    def create_assistant_template_list(
        items: list["AssistantTemplateDBModel"],
    ) -> AssistantTemplate:
        return [
            AssistantTemplateFactory.create_assistant_template(item=item)
            for item in items
        ]

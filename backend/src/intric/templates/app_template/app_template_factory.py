from typing import TYPE_CHECKING

from intric.templates.app_template.app_template import AppTemplate
from intric.templates.app_template.api.app_template_models import AppTemplateWizard


if TYPE_CHECKING:
    from intric.database.tables.app_template_table import AppTemplates


class AppTemplateFactory:
    @staticmethod
    def create_app_template(item: "AppTemplates") -> AppTemplate:
        wizard = AppTemplateWizard(**item.wizard)
        return AppTemplate(
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
            input_description=item.input_description,
            input_type=item.input_type,
            organization=item.organization,
            tenant_id=item.tenant_id,
            deleted_at=item.deleted_at,
            original_snapshot=item.original_snapshot,
        )

    @staticmethod
    def create_app_template_list(
        items: list["AppTemplates"],
    ) -> list[AppTemplate]:
        return [AppTemplateFactory.create_app_template(item=item) for item in items]

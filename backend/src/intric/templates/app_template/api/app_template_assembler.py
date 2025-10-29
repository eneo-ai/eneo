from typing import TYPE_CHECKING

from intric.templates.app_template.api.app_template_models import (
    AppInTemplatePublic,
    AppTemplateListPublic,
    AppTemplateOrganization,
    AppTemplatePublic,
    CompletionModelPublicAppTemplate,
    PromptPublicAppTemplate,
)

if TYPE_CHECKING:
    from intric.templates.app_template.app_template import AppTemplate


class AppTemplateAssembler:
    @staticmethod
    def from_domain_to_model(
        app_template: "AppTemplate",
    ) -> AppTemplatePublic:
        completion_model = (
            CompletionModelPublicAppTemplate(id=app_template.completion_model.id)
            if app_template.completion_model
            else None
        )
        prompt = (
            PromptPublicAppTemplate(text=app_template.prompt_text)
            if app_template.prompt_text
            else None
        )
        app = AppInTemplatePublic(
            name=app_template.name,
            completion_model=completion_model,
            completion_model_kwargs=app_template.completion_model_kwargs,
            prompt=prompt,
            input_type=app_template.input_type,
            input_description=app_template.input_description,
        )
        organization = AppTemplateOrganization(name=app_template.organization)
        return AppTemplatePublic(
            id=app_template.id,
            created_at=app_template.created_at,
            updated_at=app_template.updated_at,
            name=app_template.name,
            description=app_template.description,
            category=app_template.category,
            app=app,
            wizard=app_template.wizard,
            type="app",
            organization=organization,
            is_default=app_template.is_default,
        )

    @staticmethod
    def to_paginated_response(items: list["AppTemplate"]) -> AppTemplateListPublic:
        public_item = [
            AppTemplateAssembler.from_domain_to_model(app_template=i) for i in items
        ]
        return AppTemplateListPublic(items=public_item)

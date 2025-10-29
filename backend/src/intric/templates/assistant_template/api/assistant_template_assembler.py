from typing import TYPE_CHECKING

from intric.templates.assistant_template.api.assistant_template_models import (
    AssistantInTemplatePublic,
    AssistantTemplateListPublic,
    AssistantTemplateOrganization,
    AssistantTemplatePublic,
    CompletionModelPublicAssistantTemplate,
    PromptPublicAssistantTemplate,
)

if TYPE_CHECKING:
    from intric.templates.assistant_template.assistant_template import AssistantTemplate


class AssistantTemplateAssembler:
    @staticmethod
    def from_domain_to_model(
        assistant_template: "AssistantTemplate",
    ) -> AssistantTemplatePublic:
        completion_model = (
            CompletionModelPublicAssistantTemplate(
                id=assistant_template.completion_model.id
            )
            if assistant_template.completion_model
            else None
        )
        prompt = (
            PromptPublicAssistantTemplate(text=assistant_template.prompt_text)
            if assistant_template.prompt_text
            else None
        )
        assistant = AssistantInTemplatePublic(
            name=assistant_template.name,
            completion_model=completion_model,
            completion_model_kwargs=assistant_template.completion_model_kwargs,
            prompt=prompt,
        )
        organization = AssistantTemplateOrganization(
            name=assistant_template.organization
        )
        return AssistantTemplatePublic(
            id=assistant_template.id,
            created_at=assistant_template.created_at,
            updated_at=assistant_template.updated_at,
            name=assistant_template.name,
            description=assistant_template.description,
            category=assistant_template.category,
            assistant=assistant,
            wizard=assistant_template.wizard,
            type="assistant",
            organization=organization,
            is_default=assistant_template.is_default,
        )

    @staticmethod
    def to_paginated_response(
        items: list["AssistantTemplate"],
    ) -> AssistantTemplateListPublic:
        public_item = [
            AssistantTemplateAssembler.from_domain_to_model(assistant_template=i)
            for i in items
        ]
        return AssistantTemplateListPublic(items=public_item, count=len(public_item))

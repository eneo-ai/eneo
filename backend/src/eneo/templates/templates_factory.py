from typing import TYPE_CHECKING, Sequence

from eneo.templates.templates import Templates

if TYPE_CHECKING:
    from eneo.templates.app_template.app_template import AppTemplate
    from eneo.templates.assistant_template.assistant_template import (
        AssistantTemplate,
    )


class TemplatesFactory:
    @staticmethod
    def create_templates(
        apps: Sequence["AppTemplate"],
        assistants: Sequence["AssistantTemplate"],
    ) -> Templates:
        return Templates(apps=apps, assistants=assistants)

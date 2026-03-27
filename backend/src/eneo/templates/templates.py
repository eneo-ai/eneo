from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from eneo.templates.app_template.app_template import AppTemplate
    from eneo.templates.assistant_template.assistant_template import AssistantTemplate


class Templates:
    def __init__(
        self, apps: list["AppTemplate"], assistants: list["AssistantTemplate"]
    ) -> None:
        self.app_templates = apps
        self.assistant_templates = assistants

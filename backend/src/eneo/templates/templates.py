from typing import TYPE_CHECKING, Sequence

if TYPE_CHECKING:
    from eneo.templates.app_template.app_template import AppTemplate
    from eneo.templates.assistant_template.assistant_template import AssistantTemplate


class Templates:
    def __init__(
        self, apps: Sequence["AppTemplate"], assistants: Sequence["AssistantTemplate"]
    ) -> None:
        super().__init__()
        self.app_templates = apps
        self.assistant_templates = assistants

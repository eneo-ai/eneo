from typing import TYPE_CHECKING

from intric.templates.templates import Templates

if TYPE_CHECKING:
    from intric.database.tables.app_template_table import AppTemplates
    from intric.database.tables.assistant_template_table import AssistantTemplates


class TemplatesFactory:
    @staticmethod
    def create_templates(
        apps: list["AppTemplates"], assistants: list["AssistantTemplates"]
    ) -> Templates:
        return Templates(apps=apps, assistants=assistants)

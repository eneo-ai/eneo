"""Shared constants for completion models module."""

from eneo.database.tables.assistant_table import Assistants
from eneo.database.tables.assistant_template_table import AssistantTemplates
from eneo.database.tables.app_table import Apps
from eneo.database.tables.app_template_table import AppTemplates
from eneo.database.tables.questions_table import Questions
from eneo.database.tables.service_table import Services

# Mapping of entity types to their corresponding database tables
ENTITY_TABLE_MAP = {
    "assistants": Assistants,
    "apps": Apps,
    "services": Services,
    "questions": Questions,
    "assistant_templates": AssistantTemplates,
    "app_templates": AppTemplates,
}

# List of all entity types that use completion models
ENTITY_TYPES = list(ENTITY_TABLE_MAP.keys())
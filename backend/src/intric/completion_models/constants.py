"""Shared constants for completion models module."""

from intric.database.tables.app_table import Apps
from intric.database.tables.app_template_table import AppTemplates
from intric.database.tables.assistant_table import Assistants
from intric.database.tables.assistant_template_table import AssistantTemplates
from intric.database.tables.questions_table import Questions
from intric.database.tables.service_table import Services

# All entity types that have a completion_model_id column.
# Used for usage counting and statistics.
ENTITY_TABLE_MAP = {
    "assistants": Assistants,
    "apps": Apps,
    "services": Services,
    "questions": Questions,
    "assistant_templates": AssistantTemplates,
    "app_templates": AppTemplates,
}

ENTITY_TYPE_ALIASES = {
    "assistant": "assistants",
    "app": "apps",
    "service": "services",
    "question": "questions",
    "assistant_template": "assistant_templates",
    "app_template": "app_templates",
}


def normalize_entity_type(entity_type: str) -> str:
    """Return the canonical plural entity type used by ENTITY_TABLE_MAP."""
    return ENTITY_TYPE_ALIASES.get(entity_type, entity_type)


def singular_entity_type(entity_type: str) -> str:
    """Return the singular form used in API detail payloads and tenant filters."""
    canonical = normalize_entity_type(entity_type)
    for singular, plural in ENTITY_TYPE_ALIASES.items():
        if plural == canonical:
            return singular
    return canonical


def get_entity_table(entity_type: str):
    """Resolve an entity table from either singular or plural entity type."""
    return ENTITY_TABLE_MAP.get(normalize_entity_type(entity_type))


# List of all entity types that use completion models
ENTITY_TYPES = list(ENTITY_TABLE_MAP.keys())

# Active configuration entities that should be migrated when switching models.
# Questions are historical records (which model generated each answer) and must
# NOT be migrated — doing so falsely attributes answers to the target model and
# corrupts token usage analytics.
MIGRATABLE_ENTITY_TYPES = [
    "assistants",
    "apps",
    "services",
    "assistant_templates",
    "app_templates",
    "spaces",
]

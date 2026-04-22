from __future__ import annotations

from intric.flows.ai_builder.ai_builder_knowledge_pack_core import (
    KNOWLEDGE_PACK_ANTI_PATTERNS,
    KNOWLEDGE_PACK_CONTRACTS,
    KNOWLEDGE_PACK_FLOW_ARCHITECTURE,
    KNOWLEDGE_PACK_INSTRUCTIONS_AND_UNDERLAG,
    KNOWLEDGE_PACK_IO_INTELLIGENCE,
    KNOWLEDGE_PACK_RECIPES,
    KNOWLEDGE_PACK_STEP_DESIGN,
    KNOWLEDGE_PACK_VARIABLE_SYSTEM,
)
from intric.flows.ai_builder.ai_builder_knowledge_pack_create import (
    KNOWLEDGE_PACK_CREATE_FLOW_ARCHITECTURE,
    KNOWLEDGE_PACK_CREATE_RECIPES,
    KNOWLEDGE_PACK_CREATE_STEP_DESIGN,
    VALIDATION_REPAIR_EXAMPLES,
)
from intric.flows.ai_builder.ai_builder_knowledge_pack_edit import (
    KNOWLEDGE_PACK_EDIT_MODE,
)
from intric.flows.ai_builder.ai_builder_knowledge_pack_protocol import (
    build_role_and_protocol,
    build_structured_reference_block,
)
from intric.flows.ai_builder.pattern_registry import render_knowledge_pack


def build_prompt_knowledge_sections(
    *,
    is_edit_mode: bool,
    has_confirmed_requirements: bool,
) -> list[str]:
    sections = [
        build_role_and_protocol(is_edit_mode=is_edit_mode),
        build_structured_reference_block(is_edit_mode=is_edit_mode),
    ]

    if is_edit_mode:
        sections.extend(
            [
                KNOWLEDGE_PACK_FLOW_ARCHITECTURE,
                KNOWLEDGE_PACK_VARIABLE_SYSTEM,
                KNOWLEDGE_PACK_EDIT_MODE,
                KNOWLEDGE_PACK_CONTRACTS,
                KNOWLEDGE_PACK_STEP_DESIGN,
            ]
        )
        return sections

    sections.append(KNOWLEDGE_PACK_CREATE_FLOW_ARCHITECTURE)
    if has_confirmed_requirements:
        sections.extend(
            [
                KNOWLEDGE_PACK_CREATE_STEP_DESIGN,
                KNOWLEDGE_PACK_CREATE_RECIPES,
                VALIDATION_REPAIR_EXAMPLES,
                render_knowledge_pack(),
            ]
        )
    return sections


__all__ = [
    "KNOWLEDGE_PACK_ANTI_PATTERNS",
    "KNOWLEDGE_PACK_CONTRACTS",
    "KNOWLEDGE_PACK_CREATE_FLOW_ARCHITECTURE",
    "KNOWLEDGE_PACK_CREATE_RECIPES",
    "KNOWLEDGE_PACK_CREATE_STEP_DESIGN",
    "KNOWLEDGE_PACK_EDIT_MODE",
    "KNOWLEDGE_PACK_FLOW_ARCHITECTURE",
    "KNOWLEDGE_PACK_IO_INTELLIGENCE",
    "KNOWLEDGE_PACK_INSTRUCTIONS_AND_UNDERLAG",
    "KNOWLEDGE_PACK_RECIPES",
    "KNOWLEDGE_PACK_STEP_DESIGN",
    "KNOWLEDGE_PACK_VARIABLE_SYSTEM",
    "VALIDATION_REPAIR_EXAMPLES",
    "build_prompt_knowledge_sections",
    "build_role_and_protocol",
    "build_structured_reference_block",
]

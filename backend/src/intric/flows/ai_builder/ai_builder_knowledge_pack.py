from __future__ import annotations

from intric.flows.ai_builder.ai_builder_knowledge_pack_core import (
    _KNOWLEDGE_PACK_ANTI_PATTERNS,
    _KNOWLEDGE_PACK_CONTRACTS,
    _KNOWLEDGE_PACK_FLOW_ARCHITECTURE,
    _KNOWLEDGE_PACK_IO_INTELLIGENCE,
    _KNOWLEDGE_PACK_INSTRUCTIONS_AND_UNDERLAG,
    _KNOWLEDGE_PACK_RECIPES,
    _KNOWLEDGE_PACK_STEP_DESIGN,
    _KNOWLEDGE_PACK_VARIABLE_SYSTEM,
)
from intric.flows.ai_builder.ai_builder_knowledge_pack_create import (
    _KNOWLEDGE_PACK_CREATE_FLOW_ARCHITECTURE,
    _KNOWLEDGE_PACK_CREATE_RECIPES,
    _KNOWLEDGE_PACK_CREATE_STEP_DESIGN,
    _VALIDATION_REPAIR_EXAMPLES,
)
from intric.flows.ai_builder.ai_builder_knowledge_pack_edit import (
    _KNOWLEDGE_PACK_EDIT_MODE,
)
from intric.flows.ai_builder.ai_builder_knowledge_pack_protocol import (
    build_role_and_protocol,
    build_structured_reference_block,
)


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
                _KNOWLEDGE_PACK_FLOW_ARCHITECTURE,
                _KNOWLEDGE_PACK_VARIABLE_SYSTEM,
                _KNOWLEDGE_PACK_EDIT_MODE,
                _KNOWLEDGE_PACK_CONTRACTS,
                _KNOWLEDGE_PACK_STEP_DESIGN,
            ]
        )
        return sections

    sections.append(_KNOWLEDGE_PACK_CREATE_FLOW_ARCHITECTURE)
    if has_confirmed_requirements:
        sections.extend(
            [
                _KNOWLEDGE_PACK_CREATE_STEP_DESIGN,
                _KNOWLEDGE_PACK_CREATE_RECIPES,
                _VALIDATION_REPAIR_EXAMPLES,
            ]
        )
    return sections


__all__ = [
    "_KNOWLEDGE_PACK_ANTI_PATTERNS",
    "_KNOWLEDGE_PACK_CONTRACTS",
    "_KNOWLEDGE_PACK_CREATE_FLOW_ARCHITECTURE",
    "_KNOWLEDGE_PACK_CREATE_RECIPES",
    "_KNOWLEDGE_PACK_CREATE_STEP_DESIGN",
    "_KNOWLEDGE_PACK_EDIT_MODE",
    "_KNOWLEDGE_PACK_FLOW_ARCHITECTURE",
    "_KNOWLEDGE_PACK_IO_INTELLIGENCE",
    "_KNOWLEDGE_PACK_INSTRUCTIONS_AND_UNDERLAG",
    "_KNOWLEDGE_PACK_RECIPES",
    "_KNOWLEDGE_PACK_STEP_DESIGN",
    "_KNOWLEDGE_PACK_VARIABLE_SYSTEM",
    "_VALIDATION_REPAIR_EXAMPLES",
    "build_prompt_knowledge_sections",
    "build_role_and_protocol",
    "build_structured_reference_block",
]

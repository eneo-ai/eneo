from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Iterable
from uuid import UUID

from eneo.assistants.api.assistant_models import KnowledgeMode
from eneo.files.file_reference import url_only_file_ids

if TYPE_CHECKING:
    from eneo.assistants.assistant import Assistant
    from eneo.completion_models.domain.completion_model import CompletionModel
    from eneo.files.file_models import File


@dataclass(frozen=True)
class InternalMCPAvailability:
    """Internal servers that can attach for one concrete completion."""

    knowledge: bool
    files: bool
    url_only_file_ids: frozenset[UUID]


def resolve_internal_mcp_availability(
    *,
    assistant: "Assistant",
    completion_model: "CompletionModel",
    conversation_files: Iterable["File"],
) -> InternalMCPAvailability:
    """Apply the runtime gates shared by internal MCP server attachment.

    Keeping the decisions together prevents the knowledge and files paths from
    drifting as new internal tools are added.
    """
    if not completion_model.supports_tool_calling:
        return InternalMCPAvailability(
            knowledge=False, files=False, url_only_file_ids=frozenset()
        )

    url_only_ids = frozenset(
        url_only_file_ids(conversation_files, assistant.inline_file_text)
    )
    return InternalMCPAvailability(
        knowledge=(
            assistant.knowledge_mode == KnowledgeMode.TOOL and assistant.has_knowledge()
        ),
        files=bool(url_only_ids),
        url_only_file_ids=url_only_ids,
    )

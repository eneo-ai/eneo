"""One change to an assistant's settings, for every caller that makes one.

The refusals, the update and its ``ASSISTANT_UPDATED`` audit entry run as one
sequence, so a change made through the REST API and one made on a person's
behalf write the same entry, with that person as actor. The caller owns the
transaction.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

import sqlalchemy as sa

from eneo.assistants.api.assistant_models import AssistantUpdatePublic
from eneo.assistants.api.assistant_update_adapter import (
    to_standalone_assistant_update_command,
)
from eneo.assistants.application.assistant_guards import (
    raise_if_flow_managed,
    raise_if_helper_chat,
)
from eneo.audit.application.audit_metadata import AuditMetadata
from eneo.audit.domain.action_types import ActionType
from eneo.audit.domain.entity_types import EntityType
from eneo.database.tables.assistant_table import AssistantMCPServerTools
from eneo.main.models import is_provided
from eneo.skills.presentation.skill_assembler import skill_binding_audit_entries

if TYPE_CHECKING:
    from eneo.assistants.assistant import Assistant
    from eneo.main.container.container import Container
    from eneo.main.models import NotProvided


@dataclass(frozen=True)
class AppliedAssistantUpdate:
    """The assistant as the update left it, and the ``changes`` its audit entry
    records."""

    assistant: Assistant
    changes: dict[str, object]


async def apply_assistant_update(
    container: Container,
    *,
    assistant_id: UUID,
    update: AssistantUpdatePublic,
    audit_context: Mapping[str, str] | None = None,
) -> AppliedAssistantUpdate:
    """Apply ``update`` to the assistant as the container's user and audit it.

    A helper chat's assistant answers as one that does not exist, and a
    flow-managed assistant is refused, before anything is written. The
    ``ASSISTANT_UPDATED`` entry names the container's user as actor.
    ``audit_context`` is merged into the entry's metadata extra (over a key
    the entry sets itself), for a caller that makes the change on the user's
    behalf. Checks that depend on how the caller authenticated are the
    caller's.
    """
    await raise_if_helper_chat(container, assistant_id)
    service = container.assistant_service()
    current_user = container.user()

    # Get old state for change tracking
    old_assistant, _ = await service.get_assistant(assistant_id=assistant_id)
    raise_if_flow_managed(old_assistant, assistant_id)
    before_skill_entries: list[dict[str, object]] | None = None
    if update.skill_bindings is not None:
        before_skill_entries = skill_binding_audit_entries(
            await container.skill_repo().list_assistant_bindings(
                assistant_id=assistant_id
            )
        )

    # Snapshot old MCP tool overrides before update (not on domain entity)
    old_mcp_tool_overrides = None
    if update.mcp_tools is not None:
        stmt = sa.select(
            AssistantMCPServerTools.mcp_server_tool_id,
            AssistantMCPServerTools.is_enabled,
        ).where(AssistantMCPServerTools.assistant_id == assistant_id)
        result = await service.repo.session.execute(stmt)
        old_mcp_tool_overrides = {str(row[0]): row[1] for row in result.all()}

    command = to_standalone_assistant_update_command(update)
    updated_assistant, _ = await service.update_assistant(
        assistant_id=assistant_id,
        update=command,
    )

    changes, change_summary = _build_assistant_update_changes(
        assistant=update,
        old_assistant=old_assistant,
        updated_assistant=updated_assistant,
        description=command.description,
        old_mcp_tool_overrides=old_mcp_tool_overrides,
    )
    if before_skill_entries is not None:
        after_skill_entries = skill_binding_audit_entries(
            await container.skill_repo().list_assistant_bindings(
                assistant_id=assistant_id
            )
        )
        if before_skill_entries != after_skill_entries:
            changes["skills"] = {
                "old": before_skill_entries,
                "new": after_skill_entries,
            }
            change_summary.append("Skills")

    # Get space for context
    space = None
    if updated_assistant.space_id:
        try:
            space_service = container.space_service()
            space = await space_service.get_space(updated_assistant.space_id)
        except Exception:
            space = None

    # Build extra context
    extra = {
        "type": updated_assistant.type.value if updated_assistant.type else "standard",
        "summary": f"Modified {', '.join(change_summary)}"
        if change_summary
        else "No changes detected",
    }
    if audit_context:
        extra = {**extra, **audit_context}

    audit_service = container.audit_service()
    await audit_service.log_async(
        tenant_id=current_user.tenant_id,
        user=current_user,
        action=ActionType.ASSISTANT_UPDATED,
        entity_type=EntityType.ASSISTANT,
        entity_id=assistant_id,
        description=f"Updated assistant '{updated_assistant.name}'",
        metadata=AuditMetadata.standard(
            actor=current_user,
            target=updated_assistant,
            space=space,
            changes=changes,
            extra=extra,
        ),
    )

    return AppliedAssistantUpdate(assistant=updated_assistant, changes=changes)


def _build_assistant_update_changes(
    *,
    assistant: AssistantUpdatePublic,
    old_assistant: Assistant,
    updated_assistant: Assistant,
    description: str | NotProvided | None,
    old_mcp_tool_overrides: dict[str, bool] | None,
) -> tuple[dict[str, object], list[str]]:
    """Build the audit `changes` dict and human-readable summary for an
    assistant update by diffing old vs updated state. Reads only its
    arguments.
    """
    # Track ALL changes comprehensively
    changes: dict[str, object] = {}
    if old_assistant.enabled_capabilities != updated_assistant.enabled_capabilities:
        changes["enabled_capabilities"] = {
            "old": old_assistant.enabled_capabilities,
            "new": updated_assistant.enabled_capabilities,
        }
    if old_assistant.document_template != updated_assistant.document_template:
        changes["document_template"] = {
            "old": old_assistant.document_template.as_dict(),
            "new": updated_assistant.document_template.as_dict(),
        }

    # Name change
    if assistant.name and assistant.name != old_assistant.name:
        changes["name"] = {"old": old_assistant.name, "new": assistant.name}

    # Prompt change. Mirror the apps router: trigger on `prompt is not None`
    # (the field was included in the request) and treat an empty new text
    # as "prompt was cleared" rather than ignoring it, as
    # `assistant_service.update_assistant` stores it.
    if assistant.prompt is not None:
        new_prompt_text = assistant.prompt.text or ""
        old_prompt_text = old_assistant.prompt.text if old_assistant.prompt else ""
        if new_prompt_text != old_prompt_text:
            prompt_preview = (
                new_prompt_text[:50] + "..."
                if len(new_prompt_text) > 50
                else new_prompt_text
            )
            changes["prompt"] = {
                "changed": True,
                "preview": prompt_preview if new_prompt_text else "Removed prompt",
            }

    # Model change
    old_model = old_assistant.completion_model
    new_model = updated_assistant.completion_model
    if (old_model.id if old_model else None) != (new_model.id if new_model else None):
        changes["model"] = {
            "old": old_model.nickname if old_model else None,
            "new": new_model.nickname if new_model else None,
        }

    # Temperature/Top-p changes
    # Get temperature values from completion_model_kwargs
    old_temperature = (
        old_assistant.completion_model_kwargs.temperature
        if old_assistant.completion_model_kwargs
        else None
    )
    new_temperature = (
        updated_assistant.completion_model_kwargs.temperature
        if updated_assistant.completion_model_kwargs
        else None
    )
    if old_temperature != new_temperature:
        changes["temperature"] = {"old": old_temperature, "new": new_temperature}

    old_top_p = (
        old_assistant.completion_model_kwargs.top_p
        if old_assistant.completion_model_kwargs
        else None
    )
    new_top_p = (
        updated_assistant.completion_model_kwargs.top_p
        if updated_assistant.completion_model_kwargs
        else None
    )
    if old_top_p != new_top_p:
        changes["top_p"] = {"old": old_top_p, "new": new_top_p}

    # Description change
    if is_provided(description) and description != old_assistant.description:
        if isinstance(old_assistant.description, str):
            old_desc_preview = (
                (old_assistant.description[:50] + "...")
                if len(old_assistant.description) > 50
                else old_assistant.description
            )
        else:
            old_desc_preview = old_assistant.description
        if isinstance(description, str):
            new_desc_preview = (
                (description[:50] + "...") if len(description) > 50 else description
            )
        else:
            new_desc_preview = description
        changes["description"] = {"old": old_desc_preview, "new": new_desc_preview}

    # Insights change
    if assistant.insight_enabled != old_assistant.insight_enabled:
        changes["insights_enabled"] = {
            "old": old_assistant.insight_enabled,
            "new": assistant.insight_enabled,
        }

    # Data retention change
    if assistant.data_retention_days != old_assistant.data_retention_days:
        changes["data_retention_days"] = {
            "old": old_assistant.data_retention_days,
            "new": assistant.data_retention_days,
        }

    # Helper function to track added/removed items
    def get_changes_for_list(
        old_list: Sequence[object] | None,
        new_list: Sequence[object] | None,
        name_attr: str = "name",
        is_attachment: bool = False,
        assistant_space_id: UUID | None = None,
    ) -> tuple[list[dict[str, str | None]], list[dict[str, str | None]]]:
        """Compare two lists and return added/removed items with their IDs, names, and scope."""
        old_items: dict[str, dict[str, str | None]] = {}
        new_items: dict[str, dict[str, str | None]] = {}

        def get_scope(item: object, assistant_space_id: UUID | None) -> str | None:
            """Determine if knowledge is 'space' or 'organizational'"""
            if assistant_space_id is None or not hasattr(item, "space_id"):
                return None  # Cannot determine scope

            # If the item's space_id matches the assistant's, it's space-scoped
            # Otherwise, it's organizational (from parent/org space)
            if getattr(item, "space_id") == assistant_space_id:
                return "space"
            else:
                return "organizational"

        def extract_item_info(
            item: object, assistant_space_id: UUID | None
        ) -> tuple[str, str | None, str | None]:
            """Extract ID, name, and scope from an item, handling attachments specially."""
            item_id = str(getattr(item, "id", item))

            # A file is recorded by its id alone: retention removes its name.
            item_name: str | None
            if is_attachment:
                item_name = None
            else:
                # For other types, use the specified attribute or a safe fallback
                if hasattr(item, name_attr):
                    item_name = str(getattr(item, name_attr))
                elif hasattr(item, "name"):
                    item_name = str(getattr(item, "name"))
                else:
                    # Only use str() for simple types, not complex objects
                    item_name = f"{item.__class__.__name__}_{item_id}"

            # Determine scope
            scope = get_scope(item, assistant_space_id)

            return item_id, item_name, scope

        if old_list:
            for item in old_list:
                item_id, item_name, scope = extract_item_info(item, assistant_space_id)
                old_items[item_id] = {"name": item_name, "scope": scope}

        if new_list:
            for item in new_list:
                item_id, item_name, scope = extract_item_info(item, assistant_space_id)
                new_items[item_id] = {"name": item_name, "scope": scope}

        # Build added/removed lists with scope information
        added: list[dict[str, str | None]] = []
        for k in new_items:
            if k not in old_items:
                item_data: dict[str, str | None] = {"id": k}
                if new_items[k]["name"] is not None:
                    item_data["name"] = new_items[k]["name"]
                if new_items[k]["scope"]:
                    item_data["scope"] = new_items[k]["scope"]
                added.append(item_data)

        removed: list[dict[str, str | None]] = []
        for k in old_items:
            if k not in new_items:
                item_data: dict[str, str | None] = {"id": k}
                if old_items[k]["name"] is not None:
                    item_data["name"] = old_items[k]["name"]
                if old_items[k]["scope"]:
                    item_data["scope"] = old_items[k]["scope"]
                removed.append(item_data)

        return added, removed

    # Track knowledge source changes in detail
    knowledge_changes: dict[str, dict[str, list[dict[str, str | None]]]] = {}

    # Collections
    collections_added, collections_removed = get_changes_for_list(
        old_assistant.collections,
        updated_assistant.collections,
        assistant_space_id=updated_assistant.space_id,
    )
    if collections_added or collections_removed:
        knowledge_changes["collections"] = {}
        if collections_added:
            knowledge_changes["collections"]["added"] = collections_added
        if collections_removed:
            knowledge_changes["collections"]["removed"] = collections_removed

    # Websites
    websites_added, websites_removed = get_changes_for_list(
        old_assistant.websites,
        updated_assistant.websites,
        name_attr="url",
        assistant_space_id=updated_assistant.space_id,
    )
    if websites_added or websites_removed:
        knowledge_changes["websites"] = {}
        if websites_added:
            knowledge_changes["websites"]["added"] = websites_added
        if websites_removed:
            knowledge_changes["websites"]["removed"] = websites_removed

    # Attachments
    attachments_added, attachments_removed = get_changes_for_list(
        old_assistant.attachments,
        updated_assistant.attachments,
        name_attr="name",
        is_attachment=True,
        assistant_space_id=updated_assistant.space_id,
    )
    attachment_modes_changed: list[dict[str, str | None]] = [
        {
            "id": str(file.id),
            "mode": (
                "inline"
                if updated_assistant.attachment_inline_text.get(file.id, True)
                else "lookup"
            ),
        }
        for file in updated_assistant.attachments
        if old_assistant.attachment_inline_text.get(file.id, True)
        != updated_assistant.attachment_inline_text.get(file.id, True)
    ]
    if attachments_added or attachments_removed or attachment_modes_changed:
        knowledge_changes["attachments"] = {}
        if attachments_added:
            knowledge_changes["attachments"]["added"] = attachments_added
        if attachments_removed:
            knowledge_changes["attachments"]["removed"] = attachments_removed
        if attachment_modes_changed:
            knowledge_changes["attachments"]["mode_changed"] = attachment_modes_changed

    # Integration Knowledge
    integrations_added, integrations_removed = get_changes_for_list(
        old_assistant.integration_knowledge_list,
        updated_assistant.integration_knowledge_list,
        assistant_space_id=updated_assistant.space_id,
    )
    if integrations_added or integrations_removed:
        knowledge_changes["integrations"] = {}
        if integrations_added:
            knowledge_changes["integrations"]["added"] = integrations_added
        if integrations_removed:
            knowledge_changes["integrations"]["removed"] = integrations_removed

    if knowledge_changes:
        changes["knowledge_sources"] = knowledge_changes

    # MCP Servers
    mcp_servers_added, mcp_servers_removed = get_changes_for_list(
        old_assistant.mcp_servers,
        updated_assistant.mcp_servers,
        assistant_space_id=updated_assistant.space_id,
    )
    if mcp_servers_added or mcp_servers_removed:
        changes["mcp_servers"] = {}
        if mcp_servers_added:
            changes["mcp_servers"]["added"] = mcp_servers_added
        if mcp_servers_removed:
            changes["mcp_servers"]["removed"] = mcp_servers_removed

    # MCP Tool settings - compare request against the updated assistant's persisted state
    if assistant.mcp_tools is not None and old_mcp_tool_overrides is not None:
        new_tool_map = {str(t.tool_id): t.is_enabled for t in assistant.mcp_tools}

        tool_changes: list[dict[str, object]] = []
        for tid, is_enabled in new_tool_map.items():
            old_enabled = old_mcp_tool_overrides.get(tid)
            if old_enabled != is_enabled:
                tool_changes.append(
                    {
                        "tool_id": tid,
                        "old_enabled": old_enabled,
                        "new_enabled": is_enabled,
                    }
                )
        if tool_changes:
            changes["mcp_tools"] = tool_changes

    # Create summary of changes
    change_summary: list[str] = []
    if "name" in changes:
        change_summary.append("name")
    if "prompt" in changes:
        change_summary.append("prompt")
    if "model" in changes:
        change_summary.append("model")
    if "temperature" in changes or "top_p" in changes:
        change_summary.append("parameters")
    if "description" in changes:
        change_summary.append("description")
    if "insights_enabled" in changes:
        change_summary.append("insights")
    if "data_retention_days" in changes:
        change_summary.append("retention")
    if "knowledge_sources" in changes:
        change_summary.append("knowledge sources")
    if "mcp_servers" in changes:
        change_summary.append("MCP servers")
    if "mcp_tools" in changes:
        change_summary.append("MCP tools")

    return changes, change_summary

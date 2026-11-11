"""Names an audit row never keeps.

An audit row says who did what, when and to which object: its id, type, size
and MIME type, never text that retention removes. A file's name is often what
the file is about, and an upload does not know what its file will be used
for, so no file row keeps it. A conversation's name is its first question or
a title made from its turns, so no row about a conversation keeps it.

The rule is applied where a row is stored, so a row queued in an older form
is stored without the names too. The migration that removed them from rows
stored earlier repeats these texts, as SQL.
"""

from collections.abc import Mapping
from types import MappingProxyType
from typing import Any, cast

from eneo.audit.domain.action_types import ActionType

FILE_TARGET_NAME = "file"
CONVERSATION_TARGET_NAME = "conversation"

FILE_DESCRIPTIONS: Mapping[ActionType, str] = MappingProxyType(
    {
        ActionType.FILE_UPLOADED: "Uploaded a file",
        ActionType.FILE_DELETED: "Deleted a file",
        ActionType.FILE_ORIGINAL_DOWNLOAD_LINK_CREATED: (
            "Created an original download link for a file"
        ),
        ActionType.FILE_ORIGINAL_DOWNLOADED: (
            "Original file accessed with a signed link"
        ),
        ActionType.FILE_SIGNED_URL_MINTED: "Minted a signed URL for a file",
    }
)
# An upload to a collection names its collection, not the file.
COLLECTION_UPLOAD_DESCRIPTION = "Uploaded a file to collection/group"

# The routes that record a conversation as their target.
_CONVERSATION_ACTIONS = frozenset(
    {
        ActionType.MCP_APP_TOOL_CALLED,
        ActionType.DOCUMENT_EXPORTED,
        ActionType.DOCUMENT_VERSION_SAVED,
    }
)
_FILENAME = "filename"


def without_removable_names(
    action: ActionType, description: str, metadata: dict[str, Any]
) -> tuple[str, dict[str, Any]]:
    """The description and metadata a row of this action may store."""
    if action in FILE_DESCRIPTIONS:
        return _file_row(action, description, metadata)
    if action in _CONVERSATION_ACTIONS:
        return description, _with_target_name(metadata, CONVERSATION_TARGET_NAME)
    if action is ActionType.ASSISTANT_UPDATED:
        return description, _without_attachment_names(metadata)
    return description, metadata


def _file_row(
    action: ActionType, description: str, metadata: dict[str, Any]
) -> tuple[str, dict[str, Any]]:
    target = _object(metadata.get("target"))
    if target is not None and "group_id" in target:
        if _FILENAME not in target:
            # Several uploads to a collection, counted: no file is named.
            return description, metadata
        return COLLECTION_UPLOAD_DESCRIPTION, {
            **metadata,
            "target": _without(target, _FILENAME),
        }
    row = dict(metadata)
    if target is not None:
        row["target"] = {**_without(target, _FILENAME), "name": FILE_TARGET_NAME}
    extra = _object(metadata.get("extra"))
    if extra is not None and _FILENAME in extra:
        row["extra"] = _without(extra, _FILENAME)
    return FILE_DESCRIPTIONS[action], row


def _with_target_name(metadata: dict[str, Any], name: str) -> dict[str, Any]:
    target = _object(metadata.get("target"))
    if target is None:
        return metadata
    return {**metadata, "target": {**target, "name": name}}


def _without_attachment_names(metadata: dict[str, Any]) -> dict[str, Any]:
    changes = _object(metadata.get("changes"))
    sources = _object(changes.get("knowledge_sources")) if changes else None
    attachments = _object(sources.get("attachments")) if sources else None
    if changes is None or sources is None or attachments is None:
        return metadata
    # Added, removed and mode_changed keep each file's id, scope and mode.
    unnamed = {
        key: [_without_name(item) for item in cast(list[Any], items)]
        if isinstance(items, list)
        else items
        for key, items in attachments.items()
    }
    return {
        **metadata,
        "changes": {
            **changes,
            "knowledge_sources": {**sources, "attachments": unnamed},
        },
    }


def _without_name(item: Any) -> Any:
    named = _object(item)
    return item if named is None else _without(named, "name")


def _object(value: Any) -> dict[str, Any] | None:
    """A JSON object, or None for anything else."""
    return cast(dict[str, Any], value) if isinstance(value, dict) else None


def _without(values: dict[str, Any], key: str) -> dict[str, Any]:
    return {name: value for name, value in values.items() if name != key}

"""An assistant update records its attachments by id and mode, never by the
file's name, which retention removes."""

import json
from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid4

from eneo.assistants.api.assistant_router import _build_assistant_update_changes

NAME = "Utredning Anna Svensson.pdf"


def _assistant(attachments: list[SimpleNamespace], inline: dict[object, bool]) -> Any:
    return SimpleNamespace(
        enabled_capabilities=[],
        document_template=None,
        name="Case support",
        prompt=None,
        completion_model=None,
        completion_model_kwargs=None,
        description=None,
        insight_enabled=False,
        data_retention_days=None,
        collections=[],
        websites=[],
        attachments=attachments,
        attachment_inline_text=inline,
        integration_knowledge_list=[],
        mcp_servers=[],
        space_id=uuid4(),
    )


def test_attachment_changes_keep_ids_and_modes_without_names() -> None:
    kept, removed, added = (SimpleNamespace(id=uuid4(), name=NAME) for _ in range(3))
    old = _assistant([kept, removed], {kept.id: True})
    updated = _assistant([kept, added], {kept.id: False})

    changes, _ = _build_assistant_update_changes(
        assistant=cast(
            Any,
            SimpleNamespace(
                name=None,
                prompt=None,
                insight_enabled=False,
                data_retention_days=None,
                mcp_tools=None,
            ),
        ),
        old_assistant=old,
        updated_assistant=updated,
        completion_model_id=None,
        description=None,
        old_mcp_tool_overrides=None,
    )

    attachments = cast(Any, changes)["knowledge_sources"]["attachments"]
    assert [item["id"] for item in attachments["added"]] == [str(added.id)]
    assert [item["id"] for item in attachments["removed"]] == [str(removed.id)]
    assert attachments["mode_changed"] == [{"id": str(kept.id), "mode": "lookup"}]
    assert NAME not in json.dumps(changes, default=str)

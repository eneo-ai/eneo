"""An audit row says who did what, when and to which object (its id, type,
size and MIME type), never a name that retention removes. An upload does not
know what its file will be used for, so no file row keeps the file's name,
and no row about a conversation keeps the conversation's name."""

import json
from uuid import uuid4

import pytest

from eneo.audit.domain.action_types import ActionType
from eneo.audit.domain.removable_names import (
    COLLECTION_UPLOAD_DESCRIPTION,
    FILE_DESCRIPTIONS,
    without_removable_names,
)

NAME = "Utredning Anna Svensson.pdf"
TITLE = "Can my neighbour read my medical records"
ACTOR = {"id": str(uuid4()), "name": "anna", "email": "anna@example.test"}
FILE_ACTIONS = [action for action in ActionType if action.name.startswith("FILE_")]


def test_every_file_action_has_a_fixed_description() -> None:
    assert set(FILE_DESCRIPTIONS) == set(FILE_ACTIONS)
    assert all(text and "'" not in text for text in FILE_DESCRIPTIONS.values())


@pytest.mark.parametrize("action", FILE_ACTIONS)
def test_a_file_row_keeps_the_object_and_not_its_name(action: ActionType) -> None:
    file_id = str(uuid4())
    written = {
        "actor": ACTOR,
        "target": {"id": file_id, "name": NAME},
        "extra": {"size_bytes": 7, "mimetype": "application/pdf", "filename": NAME},
    }

    description, stored = without_removable_names(
        action, f"Uploaded file '{NAME}' (7 bytes)", written
    )

    assert description == FILE_DESCRIPTIONS[action]
    assert NAME not in json.dumps(stored)
    assert stored == {
        "actor": ACTOR,
        "target": {"id": file_id, "name": "file"},
        "extra": {"size_bytes": 7, "mimetype": "application/pdf"},
    }
    assert written["target"]["name"] == NAME


def test_a_collection_upload_keeps_its_collection_and_not_the_file_name() -> None:
    target = {
        "group_id": str(uuid4()),
        "group_name": "Policies",
        "space_id": None,
        "space_name": None,
        "filename": NAME,
        "content_type": "application/pdf",
    }

    description, stored = without_removable_names(
        ActionType.FILE_UPLOADED,
        f"Uploaded file '{NAME}' to collection/group",
        {"actor": ACTOR, "target": target},
    )

    assert description == COLLECTION_UPLOAD_DESCRIPTION
    assert stored == {
        "actor": ACTOR,
        "target": {key: value for key, value in target.items() if key != "filename"},
    }


def test_a_collection_row_without_a_file_name_is_kept_as_written() -> None:
    written = {
        "actor": ACTOR,
        "target": {
            "group_id": str(uuid4()),
            "group_name": "Policies",
            "blobs_count": 2,
        },
    }
    description = "Added 2 info blobs to collection/group"

    assert without_removable_names(ActionType.FILE_UPLOADED, description, written) == (
        description,
        written,
    )


@pytest.mark.parametrize(
    "action",
    [
        ActionType.MCP_APP_TOOL_CALLED,
        ActionType.DOCUMENT_EXPORTED,
        ActionType.DOCUMENT_VERSION_SAVED,
    ],
)
def test_a_row_about_a_conversation_names_no_conversation(action: ActionType) -> None:
    session_id = str(uuid4())
    written = {
        "actor": ACTOR,
        "target": {"id": session_id, "name": TITLE},
        "extra": {"session_id": session_id},
    }

    description, stored = without_removable_names(
        action, "Exported a document as docx", written
    )

    assert description == "Exported a document as docx"
    assert stored == {
        "actor": ACTOR,
        "target": {"id": session_id, "name": "conversation"},
        "extra": {"session_id": session_id},
    }


def test_an_assistant_update_keeps_attachment_ids_and_modes_without_names() -> None:
    added, removed, switched = (str(uuid4()) for _ in range(3))
    collections = {
        "added": [{"id": str(uuid4()), "name": "Policies", "scope": "space"}]
    }
    written = {
        "actor": ACTOR,
        "target": {"id": str(uuid4()), "name": "Case support"},
        "changes": {
            "name": {"old": "Support", "new": "Case support"},
            "knowledge_sources": {
                "collections": collections,
                "attachments": {
                    "added": [{"id": added, "name": NAME, "scope": "space"}],
                    "removed": [{"id": removed, "name": NAME}],
                    "mode_changed": [{"id": switched, "name": NAME, "mode": "lookup"}],
                },
            },
        },
    }

    description, stored = without_removable_names(
        ActionType.ASSISTANT_UPDATED, "Updated assistant", written
    )

    assert description == "Updated assistant"
    assert NAME not in json.dumps(stored)
    sources = stored["changes"]["knowledge_sources"]
    assert sources["attachments"] == {
        "added": [{"id": added, "scope": "space"}],
        "removed": [{"id": removed}],
        "mode_changed": [{"id": switched, "mode": "lookup"}],
    }
    assert sources["collections"] == collections
    assert stored["changes"]["name"] == {"old": "Support", "new": "Case support"}
    assert stored["target"]["name"] == "Case support"


def test_other_rows_are_kept_as_written() -> None:
    written = {
        "actor": ACTOR,
        "target": {"id": str(uuid4()), "name": "Social services"},
    }
    description = "Updated space 'Social services'"

    assert without_removable_names(ActionType.SPACE_UPDATED, description, written) == (
        description,
        written,
    )

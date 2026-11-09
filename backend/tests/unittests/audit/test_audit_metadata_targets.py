"""A conversation's name is its first question, or a title made from its
turns, and a file's name is often what the file is about. Retention removes
that text, so an audit row must not keep a copy: the conversation or file is
recorded by its id alone."""

from types import SimpleNamespace
from uuid import uuid4

import pytest

from eneo.audit.application.audit_metadata import AuditMetadata
from eneo.files.file_models import File, FileInfo, FileMetadata
from eneo.sessions.session import SessionInDB

TITLE = "Can my neighbour read my medical records"
NAME = "Utredning Anna Svensson.pdf"
ACTOR = SimpleNamespace(id=uuid4(), username="anna", email="anna@example.test")


def _conversation() -> SessionInDB:
    return SessionInDB(id=uuid4(), name=TITLE)


def test_a_conversation_target_keeps_its_id_and_not_its_title() -> None:
    conversation = _conversation()

    metadata = AuditMetadata.standard(actor=ACTOR, target=conversation)

    assert metadata["target"]["id"] == str(conversation.id)
    assert TITLE not in str(metadata)


def test_no_audit_builder_copies_a_conversation_title() -> None:
    conversation = _conversation()

    built = [
        AuditMetadata.multi_target(
            actor=ACTOR, targets=[conversation], operation="removed"
        ),
        AuditMetadata.system_action(description="removed", target=conversation),
    ]

    assert all(TITLE not in str(metadata) for metadata in built)


@pytest.mark.parametrize("model", [File, FileInfo, FileMetadata])
def test_no_audit_builder_copies_a_file_name(
    model: type[File] | type[FileInfo] | type[FileMetadata],
) -> None:
    file = model.model_construct(id=uuid4(), name=NAME)

    built = [
        AuditMetadata.standard(actor=ACTOR, target=file),
        AuditMetadata.multi_target(actor=ACTOR, targets=[file], operation="removed"),
        AuditMetadata.system_action(description="removed", target=file),
    ]

    assert built[0]["target"] == {"id": str(file.id), "name": "file"}
    assert all(NAME not in str(metadata) for metadata in built)


def test_other_targets_keep_their_names() -> None:
    space = SimpleNamespace(id=uuid4(), name="Social services")

    metadata = AuditMetadata.standard(actor=ACTOR, target=space)

    assert metadata["target"]["name"] == "Social services"

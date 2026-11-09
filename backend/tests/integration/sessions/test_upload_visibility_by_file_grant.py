"""A key without the ``files`` grant reads conversations with their uploads left out.

The owner's own uploads stay in the database and in the owner's view; a
user-owned API key sees them only with ``files: read``. Everything else about
the conversation, including the files an answer generated, stays available.
"""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from eneo.authentication.auth_models import (
    ApiKeyHashVersion,
    ApiKeyPermission,
    ApiKeyScopeType,
    ApiKeyState,
    ApiKeyType,
    ApiKeyV2InDB,
    ResourcePermissionLevel,
    ResourcePermissions,
)
from eneo.questions.question import QuestionAdd
from eneo.sessions.session import SessionFeedback, SessionUpdate
from eneo.users.user import UserInDB


def _acting_through_key(user: UserInDB, files: ResourcePermissionLevel) -> UserInDB:
    key = ApiKeyV2InDB(
        id=uuid4(),
        tenant_id=user.tenant_id,
        owner_user_id=user.id,
        key_prefix="sk_",
        key_suffix="12345678",
        key_type=ApiKeyType.SK,
        name="Integration",
        permission=ApiKeyPermission.READ,
        scope_type=ApiKeyScopeType.TENANT,
        scope_id=None,
        allowed_origins=[],
        state=ApiKeyState.ACTIVE,
        resource_permissions=ResourcePermissions(
            assistants=ResourcePermissionLevel.READ,
            conversations=ResourcePermissionLevel.READ,
            files=files,
        ),
        key_hash="test-only-hash",
        hash_version=ApiKeyHashVersion.HMAC_SHA256.value,
    )
    return user.model_copy(update={"active_api_key": key})


async def test_uploads_follow_the_files_grant_through_every_history_read(
    db_container, admin_user
):
    async with db_container() as container:
        files = container.file_service()
        upload = await files.save_image_from_bytes(
            b"\x89PNG-upload", name="payroll-scan.png", mimetype="image/png"
        )
        generated = await files.save_image_from_bytes(
            b"\x89PNG-generated", name="chart.png", mimetype="image/png"
        )
        session = await container.session_service().create_session(name="Private chat")
        question = await container.question_repo().add(
            QuestionAdd(
                question="Summarise the attachment",
                answer="Done",
                num_tokens_question=0,
                num_tokens_answer=0,
                tenant_id=admin_user.tenant_id,
                session_id=session.id,
            ),
            files=[upload],
            generated_files=[generated],
        )

    denied = _acting_through_key(admin_user, ResourcePermissionLevel.NONE)
    async with db_container(user=denied) as container:
        sessions = container.session_service()

        read = await sessions.get_session_by_uuid(session.id)
        assert [file.id for file in read.questions[0].files] == []
        assert [file.id for file in read.questions[0].generated_files] == [generated.id]
        assert "payroll-scan" not in str(read.model_dump())

        renamed = await sessions.update_session(
            SessionUpdate(id=session.id, name="Renamed")
        )
        assert renamed.name == "Renamed"
        assert renamed.questions[0].files == []

        rated = await sessions.leave_feedback(session.id, SessionFeedback(value=1))
        assert rated.feedback_value == 1
        assert rated.questions[0].files == []

        stored = await container.question_repo().get_for_tenant(
            id=question.id, tenant_id=admin_user.tenant_id
        )
        assert stored is not None
        assert stored.files == []
        assert [file.id for file in stored.generated_files] == [generated.id]

        # Tenant-wide reads (exports) hydrate through the same path.
        exported_sessions = await container.session_repo().get_by_tenant(
            admin_user.tenant_id
        )
        exported = next(item for item in exported_sessions if item.id == session.id)
        assert exported.questions[0].files == []
        window = (
            datetime.now(UTC) - timedelta(days=1),
            datetime.now(UTC) + timedelta(days=1),
        )
        exported_questions = await container.question_repo().get_by_tenant(
            admin_user.tenant_id, *window
        )
        assert (
            next(item for item in exported_questions if item.id == question.id).files
            == []
        )

    granted = _acting_through_key(admin_user, ResourcePermissionLevel.READ)
    async with db_container(user=granted) as container:
        read = await container.session_service().get_session_by_uuid(session.id)
        assert [file.id for file in read.questions[0].files] == [upload.id]
        assert [file.id for file in read.questions[0].generated_files] == [generated.id]

    async with db_container() as container:
        owner_view = await container.session_service().get_session_by_uuid(session.id)
        assert [file.id for file in owner_view.questions[0].files] == [upload.id]

    # Deleting needs ownership only; the turns cascade away with the row.
    async with db_container(user=denied) as container:
        deleted = await container.session_service().delete(session.id)
        assert deleted is not None
        assert deleted.id == session.id
        assert deleted.questions == []

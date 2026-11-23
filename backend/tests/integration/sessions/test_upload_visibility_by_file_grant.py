"""A key without the ``files`` grant reads conversations with their uploads left out.

The owner's own uploads stay in the database and in the owner's view; a
user-owned API key sees them only with ``files: read``. Everything else about
the conversation, including the files an answer generated, stays available.
"""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from eneo.ai_models.completion_models.completion_model import (
    AssistantConsultation,
    McpToolReference,
    ToolCallMetadata,
)
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
from eneo.files.model_file_references import file_handle
from eneo.questions.question import ConsultationInfo, QuestionAdd, ToolCallInfo
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
                tool_calls=[
                    ToolCallInfo(
                        server_name="files",
                        tool_name="read_file",
                        tool_call_id="read-upload",
                        arguments={"url": file_handle(upload.id)},
                        result="File: payroll-scan.png (image/png)\n\nPAYROLL-TEXT",
                    ),
                    ToolCallInfo(
                        server_name="images",
                        tool_name="describe",
                        tool_call_id="describe-generated",
                        arguments={"image": file_handle(generated.id)},
                        result="A bar chart.",
                    ),
                ],
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
        # Mixed tool context hides raw details; its generated file stays available.
        assert "PAYROLL-TEXT" not in str(read.model_dump())
        masked = await sessions.get_tool_call_result(
            session=read, tool_call_id="read-upload"
        )
        assert masked is not None
        assert (masked.arguments, masked.result) == (None, None)
        kept = await sessions.get_tool_call_result(
            session=read, tool_call_id="describe-generated"
        )
        assert kept is not None and kept.result is None

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
        assert [call.result for call in stored.tool_calls or []] == [None, None]

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
        assert "PAYROLL-TEXT" in str(read.model_dump())

    # The key's rename and rating above wrote the conversation back: what it
    # could not see is still stored.
    async with db_container() as container:
        owner_view = await container.session_service().get_session_by_uuid(session.id)
        assert [file.id for file in owner_view.questions[0].files] == [upload.id]
        assert [call.result for call in owner_view.questions[0].tool_calls or []] == [
            "File: payroll-scan.png (image/png)\n\nPAYROLL-TEXT",
            "A bar chart.",
        ]

    # Deleting needs ownership only; the turns cascade away with the row.
    async with db_container(user=denied) as container:
        deleted = await container.session_service().delete(session.id)
        assert deleted is not None
        assert deleted.id == session.id
        assert deleted.questions == []


async def test_specialist_steps_and_promoted_sources_follow_the_readers_file_grant(
    client, db_container, admin_user, patch_auth_service_jwt
):
    async with db_container() as container:
        token = container.auth_service().create_access_token_for_user(admin_user)
    owner = {"Authorization": f"Bearer {token}"}
    space = await client.post(
        "/api/v1/spaces/", headers=owner, json={"name": f"Review-{uuid4().hex[:8]}"}
    )
    assert space.status_code == 201, space.text
    assistant = await client.post(
        "/api/v1/assistants/",
        headers=owner,
        json={"name": "Policy reviewer", "space_id": space.json()["id"]},
    )
    assert assistant.status_code == 200, assistant.text
    assistant_id = UUID(assistant.json()["id"])

    steps = []
    sources = []
    step_ids = [uuid4(), uuid4(), uuid4()]
    for order, label in enumerate(
        ("contract excerpt", "published policy", "old calculation")
    ):
        source = McpToolReference(
            id=uuid4(),
            tool_call_id="provider-id",
            mcp_tool_name="reference__read",
            uri=f"eneo://example/{order}",
            mime_type="text/plain",
            content=label,
            meta={},
            order=order,
        )
        sources.append(source)
        steps.append(
            ToolCallMetadata(
                server_name="knowledge" if order == 1 else "reference",
                tool_name="retrieve" if order == 1 else "read",
                tool_call_id="provider-id",
                arguments={"text": label},
                result=label,
                meta={"preview": label},
                structured_content={"text": label},
                result_status="succeeded",
                upload_free_reference_ids=(source.id,) if order == 1 else None,
            )
        )
    consultation = ConsultationInfo.from_execution(
        AssistantConsultation(
            id=uuid4(),
            ordinal=1,
            assistant_id=assistant_id,
            assistant_name="Reviewer",
            question="Compare the documents",
            answer="Review complete.",
            status="complete",
            tool_calls=steps,
            step_ids=step_ids,
            references=sources,
        )
    )
    async with db_container() as container:
        session = await container.session_service().create_session(
            name="Review", assistant_id=assistant_id
        )
        question = await container.question_repo().add(
            QuestionAdd(
                question="Compare",
                answer="Review complete.",
                assistant_id=assistant_id,
                tenant_id=admin_user.tenant_id,
                session_id=session.id,
                num_tokens_question=1,
                num_tokens_answer=1,
            ),
            mcp_tool_references=sources,
        )
        await container.session_service().record_consultations(
            question.id, [consultation]
        )

        await container.question_repo().update_with_answer(
            question_id=question.id,
            tenant_id=admin_user.tenant_id,
            answer="Review complete.",
            tool_calls=[
                *[
                    ToolCallInfo(
                        server_name="skills",
                        tool_name="initial",
                        tool_call_id="always",
                        result="Same activation",
                        upload_free_reference_ids=(),
                    )
                    for _ in range(2)
                ],
                ToolCallInfo(
                    server_name="web",
                    tool_name="lookup",
                    tool_call_id="root",
                    result="Public result",
                    upload_free_reference_ids=(),
                ),
                ToolCallInfo(
                    server_name="web",
                    tool_name="lookup",
                    tool_call_id="ambiguous",
                    result="First",
                ),
                ToolCallInfo(
                    server_name="web",
                    tool_name="lookup",
                    tool_call_id="ambiguous",
                    result="Second",
                ),
            ],
        )

    for grant in ("none", "read"):
        key = await client.post(
            "/api/v1/api-keys",
            headers=owner,
            json={
                "name": f"Review with files {grant}",
                "key_type": "sk_",
                "scope_type": "tenant",
                "permission": "read",
                "resource_permissions": {
                    "conversations": "read",
                    "assistants": "read",
                    "files": grant,
                },
            },
        )
        assert key.status_code == 201, key.text
        auth = {"X-API-Key": key.json()["secret"]}
        url = f"/api/v1/conversations/{session.id}/"
        history = await client.get(url, headers=auth)
        assert history.status_code == 200, history.text
        root = await client.get(f"{url}tool-calls/root/result/", headers=auth)
        assert root.status_code == 200 and root.json()["result"] == "Public result"
        same = await client.get(f"{url}tool-calls/always/result/", headers=auth)
        assert same.status_code == 200 and same.json()["result"] == "Same activation"
        ambiguous = await client.get(f"{url}tool-calls/ambiguous/result/", headers=auth)
        assert ambiguous.status_code == 404
        message = history.json()["messages"][0]
        child = message["consultations"][0]
        assert child["answer"] == message["answer"] == "Review complete."
        expected_sources = sources if grant == "read" else [sources[1]]
        for public_sources in (child["references"], message["mcp_tool_references"]):
            assert {ref["id"] for ref in public_sources} == {
                str(s.id) for s in expected_sources
            }
        for step, source, step_id in zip(
            child["tool_calls"], sources, step_ids, strict=True
        ):
            visible = source in expected_sources
            assert step["step_id"] == str(step_id)
            assert step["result_status"] == "succeeded"
            assert "upload_free_reference_ids" not in step
            assert step["arguments"] == ({"text": source.content} if visible else None)
            assert step["meta"] == ({"preview": source.content} if visible else None)
            result = await client.get(
                f"{url}tool-calls/{step_id}/result/", headers=auth
            )
            assert result.status_code == 200, result.text
            assert result.json()["result"] == (source.content if visible else None)
            assert result.json()["structured_content"] == (
                {"text": source.content} if visible else None
            )

"""Deleting a session removes the files only its questions used.

Uploads and generated images (tool results persisted as files) go with the
conversation unless another question, Assistant, App or App run still uses
them. The same holds when a purged service API key takes its sessions along.
"""

from uuid import UUID, uuid4

import sqlalchemy as sa

from eneo.database.database import sessionmanager
from eneo.database.tables.api_keys_v2_table import ApiKeysV2
from eneo.database.tables.files_table import Files
from eneo.questions.question import QuestionAdd
from eneo.sessions.session import SessionAdd
from eneo.sessions.sessions_repo import OwnedSessionCounts


async def _file_exists(file_id: UUID) -> bool:
    async with sessionmanager.session() as session, session.begin():
        return (
            await session.scalar(sa.select(Files.id).where(Files.id == file_id))
        ) is not None


async def test_delete_session_removes_files_only_it_used(db_container, admin_user):
    async with db_container() as container:
        file_service = container.file_service()
        upload = await file_service.save_image_from_bytes(
            b"\x89PNG-upload", name="upload.png", mimetype="image/png"
        )
        generated = await file_service.save_image_from_bytes(
            b"\x89PNG-generated", name="generated_image.png", mimetype="image/png"
        )
        shared = await file_service.save_image_from_bytes(
            b"\x89PNG-shared", name="generated_image.png", mimetype="image/png"
        )
        shared_upload = await file_service.save_image_from_bytes(
            b"\x89PNG-shared-upload", name="shared-upload.png", mimetype="image/png"
        )

        session_service = container.session_service()
        doomed = await session_service.create_session(name="doomed")
        survivor = await session_service.create_session(name="survivor")

        question_repo = container.question_repo()
        await question_repo.add(
            QuestionAdd(
                question="draw",
                answer="here",
                num_tokens_question=0,
                num_tokens_answer=0,
                tenant_id=admin_user.tenant_id,
                session_id=doomed.id,
            ),
            files=[upload, shared_upload],
            generated_files=[generated, shared],
        )
        await question_repo.add(
            QuestionAdd(
                question="reuse",
                answer="same image",
                num_tokens_question=0,
                num_tokens_answer=0,
                tenant_id=admin_user.tenant_id,
                session_id=survivor.id,
            ),
            files=[shared_upload],
            generated_files=[shared],
        )

    async with db_container() as container:
        await container.session_service().delete(doomed.id)

    assert not await _file_exists(generated.id)
    assert not await _file_exists(upload.id)
    # Still referenced by the surviving session's question.
    assert await _file_exists(shared.id)
    assert await _file_exists(shared_upload.id)


async def test_delete_owned_by_api_key_removes_files_only_its_sessions_used(
    db_container, admin_user
):
    async with db_container() as container:
        file_service = container.file_service()
        upload = await file_service.save_image_from_bytes(
            b"\x89PNG-key-upload", name="upload.png", mimetype="image/png"
        )
        generated = await file_service.save_image_from_bytes(
            b"\x89PNG-key-generated", name="generated_image.png", mimetype="image/png"
        )
        shared_upload = await file_service.save_image_from_bytes(
            b"\x89PNG-key-shared", name="shared-upload.png", mimetype="image/png"
        )

        key_id = uuid4()
        await container.session().execute(
            sa.insert(ApiKeysV2).values(
                id=key_id,
                tenant_id=admin_user.tenant_id,
                ownership="service",
                scope_type="tenant",
                permission="write",
                key_type="sk_",
                key_hash=f"hash-{key_id.hex}",
                hash_version="argon2id-v1",
                key_prefix="sk_purged",
                key_suffix="abcd",
                name="purged service key",
            )
        )
        session_repo = container.session_repo()
        owned = await session_repo.add(SessionAdd(name="owned", api_key_id=key_id))
        survivor = await container.session_service().create_session(name="survivor")

        question_repo = container.question_repo()
        await question_repo.add(
            QuestionAdd(
                question="draw",
                answer="here",
                num_tokens_question=0,
                num_tokens_answer=0,
                tenant_id=admin_user.tenant_id,
                session_id=owned.id,
            ),
            files=[upload, shared_upload],
            generated_files=[generated],
        )
        await question_repo.add(
            QuestionAdd(
                question="reuse",
                answer="same upload",
                num_tokens_question=0,
                num_tokens_answer=0,
                tenant_id=admin_user.tenant_id,
                session_id=survivor.id,
            ),
            files=[shared_upload],
            generated_files=[],
        )

        assert await session_repo.count_owned_by_api_key(key_id) == OwnedSessionCounts(
            sessions=1, questions=1
        )
        await session_repo.delete_owned_by_api_key(key_id)
        assert await session_repo.count_owned_by_api_key(key_id) == OwnedSessionCounts(
            sessions=0, questions=0
        )

    assert not await _file_exists(upload.id)
    assert not await _file_exists(generated.id)
    # Still referenced by the user's session.
    assert await _file_exists(shared_upload.id)

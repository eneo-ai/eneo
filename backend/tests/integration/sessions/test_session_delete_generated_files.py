"""Deleting a session removes the generated files only its answers owned.

Uploads stay: the user manages those. A generated image (a tool result
persisted as a file) has no owner surface besides the conversation, so it
goes with the session unless another question still references it.
"""

from uuid import UUID

import sqlalchemy as sa

from eneo.database.database import sessionmanager
from eneo.database.tables.files_table import Files
from eneo.questions.question import QuestionAdd


async def _file_exists(file_id: UUID) -> bool:
    async with sessionmanager.session() as session, session.begin():
        return (
            await session.scalar(sa.select(Files.id).where(Files.id == file_id))
        ) is not None


async def test_delete_session_removes_generated_files_and_keeps_uploads(
    db_container, admin_user
):
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
            files=[upload],
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
            generated_files=[shared],
        )

    async with db_container() as container:
        await container.session_service().delete(doomed.id)

    assert not await _file_exists(generated.id)
    assert await _file_exists(upload.id)
    # Still referenced by the surviving session's answer.
    assert await _file_exists(shared.id)

"""Partial assistant saves must validate the state they will actually persist."""

import asyncio
from io import BytesIO

import pytest
import sqlalchemy as sa
from fastapi import UploadFile
from starlette.datastructures import Headers

from eneo.database.tables.ai_models_table import CompletionModels
from eneo.files.attachment_budget import assert_prompt_and_files_fit_context
from eneo.main.exceptions import BadRequestException
from eneo.server.dependencies.container import load_container_upload_admission


@pytest.mark.parametrize(
    "model_first", [True, False], ids=["model-first", "files-first"]
)
async def test_concurrent_model_and_attachment_saves_revalidate_after_lock(
    db_container, test_settings, completion_model_factory, model_first
):
    async with db_container() as container:
        session = container.session()
        space = await container.space_init_service().get_personal_space()
        assert space.id is not None
        assistant, _ = await container.assistant_service().create_assistant(
            name="Concurrent context edits", space_id=space.id
        )
        assistant_id = assistant.id
        assert assistant.completion_model is not None
        large_id = assistant.completion_model.id
        reserve = test_settings.attachment_context_reserve_tokens
        await session.execute(
            sa.update(CompletionModels)
            .where(CompletionModels.id == large_id)
            .values(max_input_tokens=reserve + 8000, vision=False)
        )
        small_model = await completion_model_factory(
            session, "small-context-model", max_input_tokens=reserve + 1000
        )
        small_id = small_model.id
        await load_container_upload_admission(container)
        attachment = await container.file_service().save_file(
            UploadFile(
                filename="large.txt",
                file=BytesIO(b"attachment " * 2000),
                headers=Headers({"content-type": "text/plain"}),
            )
        )
        upload = await container.file_service().save_file(
            UploadFile(
                filename="question.txt",
                file=BytesIO(b"Small upload"),
                headers=Headers({"content-type": "text/plain"}),
            )
        )

    async with db_container() as container:
        files = await container.file_service().get_files_by_ids([attachment.id])
        # Prove that each edit is valid alone, but their combination cannot fit.
        assert_prompt_and_files_fit_context(
            max_input_tokens=reserve + 8000,
            model_name=assistant.completion_model.name,
            prompt_text="",
            files=files,
        )
        with pytest.raises(BadRequestException, match="context window"):
            assert_prompt_and_files_fit_context(
                max_input_tokens=reserve + 1000,
                model_name="small-context-model",
                prompt_text="",
                files=files,
            )

    async def update(container, *, change_model):
        return await container.assistant_service().update_assistant(
            assistant_id,
            completion_model_id=small_id if change_model else None,
            attachments=None if change_model else [(attachment.id, True)],
        )

    async with db_container() as first:
        with pytest.raises(BadRequestException, match="context window"):
            async with db_container() as second:
                # Keep an old ORM projection alive too: the reload must refresh
                # existing identities, including the attachment relationship.
                stale_space = await second.space_repo().get_space_by_assistant(
                    assistant_id
                )
                stale = stale_space.get_assistant(assistant_id)
                assert stale.completion_model is not None
                assert stale.completion_model.id == large_id
                assert stale.attachments == []
                pid = await second.session().scalar(sa.text("SELECT pg_backend_pid()"))
                await update(first, change_model=model_first)
                pending = asyncio.create_task(
                    update(second, change_model=not model_first)
                )
                try:
                    # Observe an actual PostgreSQL lock wait instead of relying
                    # on scheduling or a sleep to overlap the two saves.
                    async with asyncio.timeout(10):
                        while not await first.session().scalar(
                            sa.text(
                                "SELECT wait_event_type = 'Lock' "
                                "FROM pg_stat_activity WHERE pid = :pid"
                            ),
                            {"pid": pid},
                        ):
                            if pending.done():
                                await pending
                                pytest.fail("Second save did not wait for the first")
                            await asyncio.sleep(0.01)
                    await first.session().commit()
                    await asyncio.wait_for(pending, timeout=10)
                finally:
                    if not pending.done():
                        pending.cancel()
                        await asyncio.gather(pending, return_exceptions=True)

    async with db_container() as verifier:
        space = await verifier.space_repo().get_space_by_assistant(assistant_id)
        saved = space.get_assistant(assistant_id)
        assert saved.completion_model is not None
        assert saved.completion_model.id == (small_id if model_first else large_id)
        assert [file.id for file in saved.attachments] == (
            [] if model_first else [attachment.id]
        )
        await verifier.assistant_service()._assert_message_attachments_fit(
            assistant=saved,
            model=saved.completion_model,
            prompt_text=saved.prompt.text if saved.prompt else "",
            files=await verifier.file_service().get_files_by_ids([upload.id]),
        )

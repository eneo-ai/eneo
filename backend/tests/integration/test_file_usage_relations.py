from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from eneo.database.tables.app_table import AppRuns, AppRunsFiles, AppsFiles
from eneo.database.tables.assistant_table import AssistantsFiles
from eneo.database.tables.files_table import Files
from eneo.database.tables.flow_tables import FlowFiles, FlowRunFiles, FlowRuns, Flows
from eneo.database.tables.questions_table import Questions, QuestionsFiles
from eneo.database.tables.sessions_table import Sessions
from eneo.files.file_models import FileType, FileUsageKind
from eneo.files.file_usage import FileUsageRepository


@pytest.mark.integration
@pytest.mark.asyncio
async def test_file_usage_groups_every_current_product_relation(
    async_session: AsyncSession,
    admin_user,
    test_tenant,
    completion_model_factory,
    assistant_factory,
    app_factory,
) -> None:
    completion_model = await completion_model_factory(async_session, "gpt-4")
    assistant = await assistant_factory(
        async_session,
        "Usage Assistant",
        completion_model.id,
    )
    app = await app_factory(
        async_session,
        "Usage App",
        completion_model.id,
    )
    app_run = AppRuns(
        tenant_id=test_tenant.id,
        app_id=app.id,
        user_id=admin_user.id,
        completion_model_id=completion_model.id,
        input_text="Use the attachment",
        output_text="",
    )
    chat_session = Sessions(user_id=admin_user.id, name="Usage chat")
    flow = Flows(
        name="Usage flow",
        definition={"schema_version": 1, "form_fields": [], "steps": []},
        tenant_id=test_tenant.id,
        space_id=app.space_id,
        user_id=admin_user.id,
    )
    file = Files(
        name="shared.txt",
        mimetype="text/plain",
        file_type=FileType.TEXT.value,
        tenant_id=test_tenant.id,
        user_id=admin_user.id,
    )
    async_session.add_all([app_run, chat_session, file, flow])
    await async_session.flush()
    flow_run = FlowRuns(
        flow_id=flow.id,
        flow_version=1,
        tenant_id=test_tenant.id,
        principal_user_id=admin_user.id,
        status="queued",
    )
    async_session.add(flow_run)
    await async_session.flush()

    question = Questions(
        question="Use the attachment",
        answer="",
        num_tokens_question=0,
        num_tokens_answer=0,
        tenant_id=test_tenant.id,
        session_id=chat_session.id,
    )
    async_session.add(question)
    await async_session.flush()
    async_session.add_all(
        [
            QuestionsFiles(
                question_id=question.id,
                file_id=file.id,
                type="user",
            ),
            AssistantsFiles(
                assistant_id=assistant.id,
                file_id=file.id,
            ),
            AppsFiles(
                app_id=app.id,
                file_id=file.id,
            ),
            AppRunsFiles(
                app_run_id=app_run.id,
                file_id=file.id,
            ),
            FlowFiles(flow_id=flow.id, file_id=file.id, role="template"),
            FlowRunFiles(flow_run_id=flow_run.id, file_id=file.id, role="input"),
        ]
    )
    await async_session.flush()

    counts = await FileUsageRepository(async_session).count_product_usage([file.id])

    assert {item.kind: item.count for item in counts} == {
        FileUsageKind.CHAT_ATTACHMENT: 1,
        FileUsageKind.ASSISTANT_ATTACHMENT: 1,
        FileUsageKind.APP_ATTACHMENT: 1,
        FileUsageKind.APP_RUN_INPUT: 1,
        FileUsageKind.FLOW_FILE: 1,
        FileUsageKind.FLOW_RUN_FILE: 1,
    }

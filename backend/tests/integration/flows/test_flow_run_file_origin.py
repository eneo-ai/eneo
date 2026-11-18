"""Files a run creates record the run's origin: its space, flow and run.

Each test gives the executor the File service the worker builds for a run
(bound to the run's origin) and drives one way a run creates a file: a rendered
output document, a filled Word template and text over the inline limit. The
worker's own binding is proven in ``test_flow_runtime_worker_contract.py``;
these tests prove that each path saves through the executor's service.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
from dependency_injector import providers

from eneo.database.database import sessionmanager
from eneo.files.file_models import FileOrigin
from eneo.flows.runtime.document_rendering.limits import DocumentRenderLimits
from eneo.flows.runtime.tasks import enable_autobegin_for_flow_task_session
from eneo.flows.runtime.template_fill_runtime import (
    PreparedTemplateFillStep,
    complete_template_fill_step,
)
from eneo.main.container.container import Container
from tests.docx_template_fixtures import control_template_bytes
from tests.integration.flows.test_flow_step_file_mapping_contract import (
    _create_running_step_file_flow,
)
from tests.unittests.flows.executor_test_support import (
    build_step_executor,
    runtime_step,
)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.asyncio,
    pytest.mark.usefixtures("object_content_runtime_ready"),
]


@pytest.fixture
async def run_service(
    db_container,
    admin_user,
    test_tenant,
    completion_model_factory,
    space_factory,
    assistant_factory,
):
    async with db_container(user=admin_user) as container:
        flow, _step, run, _repo = await _create_running_step_file_flow(
            session=container.session(),
            admin_user=admin_user,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
            assistant_factory=assistant_factory,
        )
    origin = FileOrigin(space_id=flow.space_id, flow_id=flow.id, flow_run_id=run.id)
    async with sessionmanager.session() as session:
        enable_autobegin_for_flow_task_session(session)
        container = Container(
            session=providers.Object(session),
            user=providers.Object(admin_user),
            tenant=providers.Object(test_tenant),
        )
        executor, _, _, _ = build_step_executor(admin_user, max_inline_text_bytes=64)
        executor.session = session
        executor.file_repo = container.file_repo()
        executor.file_service = container.file_service(user=admin_user).with_origin(
            origin
        )
        yield SimpleNamespace(executor=executor, run=run, origin=origin)


async def _assert_origin(db_container, file_id: UUID, origin: FileOrigin) -> None:
    async with db_container() as container:
        stored = await container.file_repo().get_by_id_for_lifecycle(file_id)
    assert stored is not None
    assert (
        stored.origin_space_id,
        stored.origin_flow_id,
        stored.origin_flow_run_id,
    ) == (origin.space_id, origin.flow_id, origin.flow_run_id)


async def test_a_rendered_output_document_records_the_runs_origin(
    run_service, db_container
):
    executor = run_service.executor
    executor.document_render_service = SimpleNamespace(
        render_document=lambda text, output_type, step_order, title: (
            b"%PDF rendered report",
            "application/pdf",
        ),
        render_structured_document=MagicMock(
            side_effect=AssertionError("structured rendering is not used here")
        ),
        limits=DocumentRenderLimits(),
    )

    result = await executor._process_typed_output(
        full_text="Report body",
        step=runtime_step(output_type="pdf", output_mode="render_verbatim"),
        run=run_service.run,
    )
    await executor.session.commit()

    assert result.artifacts is not None
    await _assert_origin(
        db_container, UUID(result.artifacts[0]["file_id"]), run_service.origin
    )


async def test_a_filled_word_template_records_the_runs_origin(
    run_service, db_container
):
    executor = run_service.executor

    output = await complete_template_fill_step(
        step=runtime_step(output_type="docx", output_mode="template_fill"),
        run=run_service.run,
        prepared=PreparedTemplateFillStep(
            template_asset_id=uuid4(),
            template_checksum=None,
            template_name="Template",
            template_file_id=uuid4(),
            template_file_name="template.docx",
            template_blob=control_template_bytes(text=["title"]),
            placeholders=("title",),
            resolved_bindings={"title": "Filled title"},
            persisted_text="Filled title",
            resolved_input_edges=(),
        ),
        deps=executor._template_fill_runtime_deps(),
    )
    await executor.session.commit()

    assert output.artifacts is not None
    await _assert_origin(
        db_container, UUID(str(output.artifacts[0]["file_id"])), run_service.origin
    )


async def test_text_over_the_inline_limit_records_the_runs_origin(
    run_service, db_container
):
    executor = run_service.executor

    _prefix, file_ids = await executor._apply_output_cap(
        text="Long output. " * 20, run=run_service.run, step=runtime_step()
    )
    await executor.session.commit()

    assert len(file_ids) == 1
    await _assert_origin(db_container, file_ids[0], run_service.origin)

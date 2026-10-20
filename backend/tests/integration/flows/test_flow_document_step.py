"""Document steps call the file-creation provider and keep the file produced.

The provider is faked at the proxy boundary (the session the runner opens
and the capability resolution that picks the server); the file service,
the flow services and the executor are real.
"""

import base64
import io
import zipfile
from io import BytesIO
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import UploadFile

from eneo.assistants.assistant_service import AssistantService
from eneo.database.tables.capabilities_table import SpaceCapabilities
from eneo.flows.definition import DocumentStep, FlowDefinition, LlmStep
from eneo.flows.flow_models import FlowRunStatus, StepResultStatus
from eneo.flows.step_runners import STEP_DOCUMENT_UNAVAILABLE
from eneo.main.exceptions import BadRequestException
from eneo.mcp_servers.domain.entities.mcp_server import DOCX_MIME_TYPE
from eneo.mcp_servers.infrastructure.proxy.mcp_proxy_factory import (
    MCPProxySessionFactory,
)
from eneo.server.dependencies.container import load_container_upload_admission
from tests.integration.flows.conftest import topic_field


def minimal_docx() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/'
            'package/2006/content-types"></Types>',
        )
        archive.writestr("word/document.xml", "<w:document/>")
    return buffer.getvalue()


def _docx_result(filename: str = "Rapport.docx") -> dict:
    return {
        "content": [
            {"type": "text", "text": f"Created {filename}"},
            {
                "type": "file",
                "data": base64.b64encode(minimal_docx()).decode(),
                "mime_type": DOCX_MIME_TYPE,
                "filename": filename,
            },
        ]
    }


class FakeRuntime:
    """The proxy as the document runner drives it; records what it was told."""

    def __init__(self, result: dict) -> None:
        self.result = result
        self.calls: list[tuple[str, dict]] = []
        self.allowed: dict = {}
        self.document_template = None
        self.prepared = False
        self.closed = False

    def allow_file_references(self, references) -> None:
        self.allowed.update(references)

    def set_document_template(self, reference) -> None:
        self.document_template = reference

    async def prepare_tools_for_context(self) -> None:
        self.prepared = True

    def prefixed_tool_name(self, server_id, name: str) -> str:
        return f"runtime__{name}"

    async def call_tools_parallel(self, calls):
        self.calls.extend(calls)
        return [self.result]

    async def close(self) -> None:
        self.closed = True


@pytest.fixture
def runtime(monkeypatch):
    """A file-creation provider for every assistant, and the proxy it is called through."""
    holder = SimpleNamespace(
        proxy=None,
        result=_docx_result(),
        server=SimpleNamespace(
            id=uuid4(), name="Document runtime", purpose="file_creation", tools=[]
        ),
        assistant_id=None,
        purpose=None,
        identity_headers=None,
    )

    async def _capability_server(self, *, assistant_id, purpose):
        holder.assistant_id = assistant_id
        holder.purpose = purpose
        return holder.server

    def _create(self, servers, identity_headers=None, **_kwargs):
        assert servers == [holder.server]
        holder.identity_headers = identity_headers
        holder.proxy = FakeRuntime(holder.result)
        return holder.proxy

    monkeypatch.setattr(AssistantService, "capability_server", _capability_server)
    monkeypatch.setattr(MCPProxySessionFactory, "create", _create)
    return holder


async def _document_space(container, member_space, completion_model_factory, name):
    """A space that may create documents, with its flows assistant in place."""
    session = container.session()
    model = await completion_model_factory(session, f"{name}-model")
    space = await member_space(session, f"{name} Space", [model.id])
    session.add(SpaceCapabilities(purpose="file_creation", space_id=space.id))
    await session.flush()
    assistant = await container.flow_authoring_assistant_service().get_or_create(
        space.id
    )
    return model, space, assistant


def _content_flow(model_id) -> FlowDefinition:
    return FlowDefinition(
        form_fields=[topic_field()],
        steps=[
            LlmStep(
                key="draft",
                name="Draft",
                prompt="draft",
                input="{{form.topic}}",
                model_id=model_id,
            ),
            DocumentStep(
                key="doc",
                name="Rapport",
                format="docx",
                title="Rapport om {{form.topic}}",
                filename="rapport",
                content="# {{form.topic}}\n\n{{previous}}",
            ),
        ],
    )


async def test_content_document_step_renders_through_the_provider_and_keeps_the_file(
    db_container,
    member_space,
    completion_model_factory,
    publish_flow,
    provider,
    runtime,
):
    async with db_container() as container:
        model, space, assistant = await _document_space(
            container, member_space, completion_model_factory, "doc"
        )
        flow = await publish_flow(container, space, _content_flow(model.id))
        run_service = container.flow_run_service()
        run = await run_service.create_run(
            flow.id, values={"topic": "hamnar"}, files={}
        )
        await run_service.execute_run(run.id)

        finished = await run_service.get_run(run.id, flow_id=flow.id)
        assert finished.status == FlowRunStatus.COMPLETED
        # The provider is the one serving the space's flows assistant.
        assert runtime.assistant_id == assistant.assistant_id
        assert runtime.purpose == "file_creation"
        proxy = runtime.proxy
        assert proxy.prepared and proxy.closed
        assert proxy.calls == [
            (
                "runtime__create_document",
                {
                    "filename": "rapport",
                    "title": "Rapport om hamnar",
                    "format": "docx",
                    "content": "# hamnar\n\nLLM[draft|hamnar]",
                    "language": "sv",
                },
            )
        ]
        assert proxy.allowed == {}

        doc = finished.steps[1]
        assert doc.status == StepResultStatus.COMPLETED
        assert doc.input_payload_json["tool"] == "create_document"
        assert doc.output_payload_json["text"] == "Rapport.docx"
        assert [f.name for f in doc.result_files] == ["Rapport.docx"]
        assert doc.output_payload_json["file_ids"] == [str(doc.result_files[0].id)]
        assert [f.name for f in finished.result_files] == ["Rapport.docx"]
        assert finished.output_payload_json["text"] == "Rapport.docx"

        # The file is reachable through the run, whoever uploaded or produced it.
        metadata = await run_service.run_file_for_download(
            run.id, doc.result_files[0].id, role="output", flow_id=flow.id
        )
        assert metadata.name == "Rapport.docx"
        state = await run_service.get_run_state(run.id)
        assert state.steps[1].preview == "Rapport.docx"
        assert [f.name for f in state.output_files] == ["Rapport.docx"]


async def test_template_document_step_fills_the_pinned_form(
    db_container,
    member_space,
    completion_model_factory,
    publish_flow,
    provider,
    runtime,
):
    async with db_container() as container:
        model, space, _ = await _document_space(
            container, member_space, completion_model_factory, "form"
        )
        await load_container_upload_admission(container)
        form = await container.file_service().save_file(
            UploadFile(
                file=BytesIO(minimal_docx()),
                filename="mall.docx",
                headers={"content-type": DOCX_MIME_TYPE},
            )
        )
        definition = FlowDefinition(
            form_fields=[topic_field()],
            steps=[
                DocumentStep(
                    key="doc",
                    name="Protokoll",
                    template_file_id=f"eneo-file:{form.id.hex}",
                    values={"amne": "{{form.topic}}", "datum": "2026-10-20"},
                )
            ],
        )
        flow = await publish_flow(container, space, definition)
        pinned = await container.flow_repo().get_flow_file(
            flow.id, form.id, role="template"
        )
        assert pinned is not None
        assert pinned.step_id == flow.definition.steps[0].id

        run_service = container.flow_run_service()
        run = await run_service.create_run(
            flow.id, values={"topic": "hamnar"}, files={}
        )
        await run_service.execute_run(run.id)

        finished = await run_service.get_run(run.id, flow_id=flow.id)
        assert finished.status == FlowRunStatus.COMPLETED, finished.error
        proxy = runtime.proxy
        [(tool, arguments)] = proxy.calls
        assert tool == "runtime__fill_template"
        assert arguments["values"] == {"amne": "hamnar", "datum": "2026-10-20"}
        assert arguments["template"]["filename"] == "mall.docx"
        # The provider was handed exactly one signed link: the form's.
        assert set(proxy.allowed) == {form.id}
        assert arguments["template"]["url"] == proxy.allowed[form.id]
        assert f"/api/v1/files/{form.id}/original/download/" in proxy.allowed[form.id]
        # The stored run keeps the link redacted, never the signed token.
        stored = str(finished.steps[0].input_payload_json)
        assert proxy.allowed[form.id] not in stored
        assert "token=REDACTED" in stored
        assert [f.name for f in finished.result_files] == ["Rapport.docx"]


async def test_a_template_file_must_be_the_authors_attachment(
    db_container, member_space, completion_model_factory, provider, runtime
):
    async with db_container() as container:
        model, space, _ = await _document_space(
            container, member_space, completion_model_factory, "stranger"
        )
        definition = FlowDefinition(
            steps=[DocumentStep(key="doc", name="Doc", template_file_id=str(uuid4()))]
        )
        with pytest.raises(BadRequestException) as exc:
            await container.flow_service().create_flow(
                space_id=space.id, name="Doc", description=None, definition=definition
            )
        assert "not a file attached in this chat" in str(exc.value)


async def test_publishing_document_steps_needs_the_space_capability(
    db_container, member_space, completion_model_factory, provider, runtime
):
    async with db_container() as container:
        session = container.session()
        model = await completion_model_factory(session, "nocap-model")
        space = await member_space(session, "No Capability Space", [model.id])
        flow_service = container.flow_service()
        draft = await flow_service.create_flow(
            space_id=space.id,
            name="Doc",
            description=None,
            definition=_content_flow(model.id),
        )
        with pytest.raises(BadRequestException) as exc:
            await flow_service.publish_flow(draft.id)
        assert "file_creation function is not enabled" in str(exc.value)


async def test_a_run_fails_cleanly_when_no_document_provider_serves_the_space(
    db_container,
    member_space,
    completion_model_factory,
    publish_flow,
    provider,
    runtime,
):
    runtime.server = None
    async with db_container() as container:
        model, space, _ = await _document_space(
            container, member_space, completion_model_factory, "noprov"
        )
        flow = await publish_flow(container, space, _content_flow(model.id))
        run_service = container.flow_run_service()
        run = await run_service.create_run(
            flow.id, values={"topic": "hamnar"}, files={}
        )
        await run_service.execute_run(run.id)

        finished = await run_service.get_run(run.id, flow_id=flow.id)
        assert finished.status == FlowRunStatus.FAILED
        assert finished.error.code == STEP_DOCUMENT_UNAVAILABLE
        assert finished.steps[0].status == StepResultStatus.COMPLETED
        assert finished.steps[1].status == StepResultStatus.FAILED
        assert finished.result_files == []

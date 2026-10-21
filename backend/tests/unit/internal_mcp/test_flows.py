"""Unit tests for the loopback flows MCP server.

Covers the tool surface the model sees (names, the step union as the
``steps`` schema), the text + structured shape every tool answers with, the
space scoping (another space's flow reads as not found, a token for an
ordinary assistant is refused), the chat's own flow as the default
``flow_id``, repairable problems returned as text, the file-reference
mapping of ``run_flow``, the review decision sequence and the revision
history. The flow services are faked; their contract is the one the tools
call.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import UUID, uuid4

from mcp.types import CallToolResult

from eneo.flows.definition import (
    ComposeStep,
    FlowDefinition,
    FormField,
    LlmStep,
    StepKind,
    assign_step_ids,
)
from eneo.flows.flow_models import (
    FlowFinalOutputContractPublic,
    FlowPublic,
    FlowRevisionChangesPublic,
    FlowRevisionPublic,
    FlowRevisionSummaryPublic,
    FlowRunContractPublic,
    FlowRunPublic,
    FlowRunReviewCheckpointPublic,
    FlowRunReviewCheckpointResumeResponse,
    FlowRunStatePublic,
    FlowRunStateStepPublic,
    FlowRunStatus,
    FlowRunSummaryPublic,
    FlowSparsePublic,
    PrincipalType,
    ReviewCheckpointState,
    StepResultStatus,
)
from eneo.internal_mcp.file_references import FileReferenceRejected
from eneo.internal_mcp.flows import (
    FLOW_NOT_FOUND_MESSAGE,
    FLOWS_SERVER_NAME,
    NO_REVIEW_WAITING_MESSAGE,
    NOT_AUTHORING_ASSISTANT_MESSAGE,
    NOT_BOUND_MESSAGE,
    RUN_NOT_FOUND_MESSAGE,
    build_flows_mcp_server,
    cancel_run,
    delete_flow,
    get_flow,
    get_run,
    list_flows,
    list_revisions,
    mcp,
    publish_flow,
    restore_revision,
    review_run,
    run_flow,
    update_flow,
)
from eneo.internal_mcp.foundation import ToolContext
from eneo.internal_mcp.registry import internal_mcp_mounts
from eneo.main.exceptions import (
    BadRequestException,
    FlowNotEditingException,
    NotFoundException,
)

NOW = datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc)
CTX = SimpleNamespace()

EXPECTED_TOOLS = [
    "list_functions",
    "list_flows",
    "get_flow",
    "update_flow",
    "list_revisions",
    "restore_revision",
    "publish_flow",
    "delete_flow",
    "run_flow",
    "get_run",
    "cancel_run",
    "review_run",
]


def _definition() -> FlowDefinition:
    return FlowDefinition(
        form_fields=[FormField(key="topic", label="Topic", type="text")],
        steps=[
            LlmStep(key="draft", name="Draft", prompt="Write about {{form.topic}}"),
            ComposeStep(key="wrap", name="Wrap", template="Result: {{previous}}"),
        ],
    )


def _flow(
    *,
    space_id: UUID,
    definition: FlowDefinition | None = None,
    published_version: int | None = None,
    name: str = "Weekly brief",
    conversation_id: UUID | None = None,
) -> FlowPublic:
    return FlowPublic(
        id=uuid4(),
        space_id=space_id,
        name=name,
        description="Writes the weekly brief",
        definition=assign_step_ids(definition or _definition()),
        published_version=published_version,
        has_unpublished_changes=published_version is None,
        conversation_id=conversation_id,
        created_at=NOW,
        updated_at=NOW,
    )


def _run_state(
    flow: FlowPublic,
    *,
    status: FlowRunStatus = FlowRunStatus.QUEUED,
    checkpoint: FlowRunReviewCheckpointPublic | None = None,
) -> FlowRunStatePublic:
    return FlowRunStatePublic(
        flow_id=flow.id,
        run_id=uuid4(),
        flow_version=flow.published_version or 1,
        status=status,
        steps=[
            FlowRunStateStepPublic(
                step_id=step.id,
                key=step.key,
                name=step.name,
                kind=step.kind,
                status=StepResultStatus.PENDING,
            )
            for step in flow.definition.steps
        ],
        review_checkpoint=checkpoint,
        created_at=NOW,
        updated_at=NOW,
    )


def _checkpoint(run: FlowRunStatePublic, *, output_type: str = "text"):
    return FlowRunReviewCheckpointPublic(
        id=uuid4(),
        flow_id=run.flow_id,
        flow_run_id=run.run_id,
        step_id=run.steps[-1].step_id,
        step_order=len(run.steps),
        attempt_no=1,
        state=ReviewCheckpointState.AWAITING_REVIEW,
        revision=3,
        review_mode="edit",
        output_type=output_type,
        current_payload_json={"text": "draft"},
        requester_principal_type=PrincipalType.USER,
        created_at=NOW,
        updated_at=NOW,
    )


def _summary(run: FlowRunStatePublic) -> FlowRunSummaryPublic:
    return FlowRunSummaryPublic(
        id=run.run_id,
        flow_id=run.flow_id,
        flow_version=run.flow_version,
        tenant_id=uuid4(),
        principal_type=PrincipalType.USER,
        status=run.status,
        created_at=NOW,
        updated_at=NOW,
    )


class FakeFlowService:
    """Records every call; raises ``error`` on the next mutating call and
    ``editing_error`` when a write tool checks the caller's edit mode.

    Every create and every changing update keeps a revision, as the real
    service does; ``revisions`` holds them per flow, oldest first.
    """

    def __init__(self, flows: list[FlowPublic] = (), *, error=None, editing_error=None):
        self.flows = {flow.id: flow for flow in flows}
        self.calls: list[tuple] = []
        self.error = error
        self.editing_error = editing_error
        # Flow ids the write tools checked edit mode on, in order.
        self.edit_checks: list[UUID] = []
        self.revisions: dict[UUID, list[FlowRevisionPublic]] = {
            flow.id: [self._revision(flow, channel="api")] for flow in flows
        }

    @staticmethod
    def _revision(
        flow: FlowPublic,
        *,
        channel: str,
        note: str | None = None,
        changes: FlowRevisionChangesPublic | None = None,
    ) -> FlowRevisionPublic:
        return FlowRevisionPublic(
            flow_id=flow.id,
            revision=flow.revision,
            name=flow.name,
            description=flow.description,
            definition=flow.definition,
            created_at=NOW,
            principal_type=PrincipalType.USER,
            channel=channel,
            note=note,
            changes=changes or FlowRevisionChangesPublic(is_initial=True),
        )

    def _keep(self, flow: FlowPublic, *, channel: str, note: str | None, **changes):
        self.flows[flow.id] = flow
        self.revisions.setdefault(flow.id, []).append(
            self._revision(
                flow,
                channel=channel,
                note=note,
                changes=FlowRevisionChangesPublic(**changes),
            )
        )

    def _raise(self):
        if self.error is not None:
            raise self.error

    async def get_flow(self, flow_id):
        try:
            return self.flows[flow_id]
        except KeyError:
            raise NotFoundException() from None

    async def flow_for_conversation(self, conversation_id):
        return next(
            (f for f in self.flows.values() if f.conversation_id == conversation_id),
            None,
        )

    async def require_editing(self, flow_id):
        self.edit_checks.append(flow_id)
        if self.editing_error is not None:
            raise self.editing_error
        return self.flows[flow_id]

    async def update_flow(
        self,
        flow_id,
        *,
        name,
        description,
        definition,
        channel,
        conversation_id=None,
        note=None,
        expected_revision=None,
    ):
        self.calls.append(("update_flow", channel, name, description, definition, note))
        self._raise()
        current = self.flows[flow_id]
        updated = current.model_copy(
            update={
                "name": name or current.name,
                "definition": (
                    assign_step_ids(definition, current.definition)
                    if definition is not None
                    else current.definition
                ),
                "revision": current.revision + 1,
            }
        )
        self._keep(
            updated,
            channel=channel,
            note=note,
            name_changed=name is not None,
            steps_changed=[step.name for step in updated.definition.steps]
            if definition is not None
            else [],
        )
        return updated

    async def list_revisions(self, flow_id, *, limit=20, offset=0):
        rows = list(reversed(self.revisions.get(flow_id, [])))
        summaries = [FlowRevisionSummaryPublic(**row.model_dump()) for row in rows]
        return summaries[offset : offset + limit], len(summaries)

    async def restore_revision(
        self, flow_id, revision, *, channel, expected_revision=None
    ):
        self.calls.append(("restore_revision", flow_id, revision, channel))
        self._raise()
        rows = self.revisions.get(flow_id, [])
        row = next((r for r in rows if r.revision == revision), None)
        if row is None:
            raise NotFoundException("Flow revision not found")
        current = self.flows[flow_id]
        restored = current.model_copy(
            update={
                "name": row.name,
                "description": row.description,
                "definition": row.definition,
                "revision": current.revision + 1,
            }
        )
        self._keep(restored, channel=channel, note=f"Restored revision {revision}")
        return restored

    async def list_flows(self, space_id):
        return [
            FlowSparsePublic(
                id=flow.id,
                space_id=flow.space_id,
                name=flow.name,
                published_version=flow.published_version,
                step_count=len(flow.definition.steps),
                step_kinds=[step.kind for step in flow.definition.steps],
                created_at=NOW,
                updated_at=NOW,
            )
            for flow in self.flows.values()
            if flow.space_id == space_id
        ]

    async def publish_flow(self, flow_id, channel, *, expected_revision=None):
        self.calls.append(("publish_flow", channel))
        self._raise()
        flow = self.flows[flow_id]
        published = flow.model_copy(
            update={
                "published_version": (flow.published_version or 0) + 1,
                "has_unpublished_changes": False,
            }
        )
        self.flows[flow_id] = published
        return published

    async def get_run_contract(self, flow_id):
        flow = self.flows[flow_id]
        return FlowRunContractPublic(
            flow_id=flow.id,
            published_flow_version=flow.published_version,
            form_fields=flow.definition.form_fields,
            steps_requiring_review=[],
            final_output=FlowFinalOutputContractPublic(
                kind=StepKind.COMPOSE, output_type="text"
            ),
        )

    async def delete_flow(self, flow_id, channel):
        self.calls.append(("delete_flow", channel))
        self._raise()
        del self.flows[flow_id]


class FakeFlowRunService:
    def __init__(self, runs: list[FlowRunStatePublic] = (), *, checkpoint=None):
        self.runs = {run.run_id: run for run in runs}
        self.checkpoint = checkpoint
        self.calls: list[tuple] = []

    async def create_run(
        self, flow_id, *, values, files, run_label, channel, **_unused
    ):
        self.calls.append(("create_run", flow_id, values, files, run_label, channel))
        state = next(run for run in self.runs.values() if run.flow_id == flow_id)
        return FlowRunPublic(**_summary(state).model_dump())

    async def get_run_state(self, run_id):
        try:
            return self.runs[run_id]
        except KeyError:
            raise NotFoundException() from None

    async def cancel_run(self, run_id, *, flow_id, channel):
        self.calls.append(("cancel_run", run_id, flow_id, channel))
        run = self.runs[run_id]
        self.runs[run_id] = run.model_copy(update={"status": FlowRunStatus.CANCELLED})
        return _summary(self.runs[run_id])

    async def get_active_checkpoint(self, run_id):
        return self.checkpoint

    async def edit_checkpoint(
        self, run_id, checkpoint_id, *, expected_revision, current_payload_json
    ):
        self.calls.append(
            ("edit_checkpoint", checkpoint_id, expected_revision, current_payload_json)
        )
        self.checkpoint = self.checkpoint.model_copy(
            update={
                "revision": expected_revision + 1,
                "current_payload_json": current_payload_json,
                "state": ReviewCheckpointState.EDITED,
            }
        )
        return self.checkpoint

    async def approve_checkpoint(
        self, run_id, checkpoint_id, *, expected_revision, resume, channel
    ):
        self.calls.append(
            ("approve_checkpoint", checkpoint_id, expected_revision, resume, channel)
        )
        run = self.runs[run_id].model_copy(update={"status": FlowRunStatus.QUEUED})
        self.runs[run_id] = run
        return FlowRunReviewCheckpointResumeResponse(
            checkpoint=self.checkpoint, run=_summary(run)
        )

    async def reject_checkpoint(
        self, run_id, checkpoint_id, *, expected_revision, reason, channel
    ):
        self.calls.append(
            ("reject_checkpoint", checkpoint_id, expected_revision, reason, channel)
        )
        self.runs[run_id] = self.runs[run_id].model_copy(
            update={"status": FlowRunStatus.FAILED}
        )
        return self.checkpoint


def _patch_context(
    monkeypatch,
    *,
    flow_service=None,
    run_service=None,
    space_id=None,
    purpose="flows",
    session_id=None,
    tenant_id=None,
    file_repo=None,
):
    """Bind the tools to a fake container for an assistant with ``purpose``."""
    space_id = space_id or uuid4()
    assistant = SimpleNamespace(id=uuid4(), space_id=space_id, purpose=purpose)

    async def get_assistant(_assistant_id):
        return assistant, []

    container = SimpleNamespace(
        assistant_service=lambda: SimpleNamespace(get_assistant=get_assistant),
        flow_service=lambda: flow_service,
        flow_run_service=lambda: run_service,
        file_repo=lambda: file_repo,
    )

    @asynccontextmanager
    async def fake_context(_ctx):
        yield ToolContext(
            container=container,
            user=SimpleNamespace(tenant_id=tenant_id or uuid4()),
            assistant_id=assistant.id,
            session_id=session_id,
        )

    monkeypatch.setattr("eneo.internal_mcp.flows.internal_tool_context", fake_context)
    return space_id


def _text(result: CallToolResult) -> str:
    return result.content[0].text


class TestToolSurface:
    async def test_tool_names(self):
        assert [tool.name for tool in await mcp.list_tools()] == EXPECTED_TOOLS

    async def test_steps_schema_is_the_step_union(self):
        tools = {tool.name: tool for tool in await mcp.list_tools()}
        schema = tools["update_flow"].inputSchema
        items = schema["properties"]["steps"]["anyOf"][0]["items"]
        assert items["discriminator"]["propertyName"] == "kind"
        assert set(items["discriminator"]["mapping"]) == {
            "llm",
            "compose",
            "document",
            "function",
            "review",
            "transcribe",
        }
        assert "FormField" in schema["$defs"]
        # The chat's own flow is the default: no tool requires a flow id.
        for name in EXPECTED_TOOLS:
            assert "flow_id" not in (tools[name].inputSchema.get("required") or []), (
                name
            )
        # The tools return CallToolResult themselves: no output schema, so the
        # text is never a JSON copy of the structured payload.
        assert all(tool.outputSchema is None for tool in tools.values())

    async def test_docstrings_teach_the_authoring_model(self):
        tools = {tool.name: tool for tool in await mcp.list_tools()}
        update = tools["update_flow"].description
        for needle in (
            "{{form.<key>}}",
            "{{steps.<key>}}",
            "{{steps.<key>.json.<path>}}",
            "{{previous}}",
            "deterministic",
            "publish_flow",
            "list_functions",
            "speaker_labels",
            "revision",
            "note",
        ):
            assert needle in update
        assert "get_run" in tools["run_flow"].description
        flow_tools = [
            name
            for name in EXPECTED_TOOLS
            if "flow_id" in tools[name].inputSchema["properties"]
        ]
        assert set(flow_tools) == {
            "get_flow",
            "update_flow",
            "publish_flow",
            "delete_flow",
            "run_flow",
            "list_revisions",
            "restore_revision",
        }
        for name in flow_tools:
            assert "Omit flow_id to work on this chat's flow" in (
                tools[name].description or ""
            ), name
        assert "create" not in [tool.name for tool in await mcp.list_tools()]
        assert "restore_revision" in tools["list_revisions"].description
        assert "new revision" in tools["restore_revision"].description

    async def test_ephemeral_server_mirrors_the_live_tools_and_is_mounted(self):
        server = await build_flows_mcp_server(token="tok", tenant_id=uuid4())

        assert server.is_internal is True
        assert server.name == FLOWS_SERVER_NAME
        assert [tool.name for tool in server.tools] == EXPECTED_TOOLS
        assert f"/internal-mcp/{FLOWS_SERVER_NAME}" in dict(internal_mcp_mounts())


class TestChatFlow:
    """Tools act on the chat's own flow unless a flow_id is given."""

    def _rig(self, monkeypatch, **context):
        session_id = uuid4()
        space_id = uuid4()
        mine = _flow(space_id=space_id, conversation_id=session_id)
        service = FakeFlowService([mine, _flow(space_id=space_id, name="Other")])
        _patch_context(
            monkeypatch,
            flow_service=service,
            space_id=space_id,
            session_id=session_id,
            **context,
        )
        return mine, service

    async def test_update_without_flow_id_changes_the_chats_flow(self, monkeypatch):
        mine, service = self._rig(monkeypatch)

        # Through FastMCP, with the JSON the model sends, so argument
        # validation and the CallToolResult passthrough are exercised.
        result = await mcp.call_tool(
            "update_flow",
            {
                "form_fields": [{"key": "topic", "label": "Topic", "type": "text"}],
                "steps": [
                    {
                        "kind": "llm",
                        "key": "draft",
                        "name": "Draft",
                        "prompt": "Write about {{form.topic}}",
                    },
                    {
                        "kind": "compose",
                        "key": "wrap",
                        "name": "Wrap",
                        "template": "Result: {{previous}}",
                    },
                ],
                "note": "First steps",
                "expected_revision": 1,
            },
        )

        assert isinstance(result, CallToolResult)
        _, channel, name, _description, definition, note = service.calls[0]
        assert channel == "mcp"
        assert name is None
        assert note == "First steps"
        assert [step.key for step in definition.steps] == ["draft", "wrap"]
        text = _text(result)
        assert "1. [llm] Draft (key: draft)" in text
        assert "2. [compose] Wrap (key: wrap)" in text
        assert "publish_flow" in text
        structured = result.structuredContent
        assert structured["flow_id"] == str(mine.id)
        assert structured["run_id"] is None
        assert structured["run"] is None
        assert structured["flow"]["id"] == str(mine.id)
        assert structured["flow"]["definition"]["steps"][0]["kind"] == "llm"

    async def test_get_flow_without_flow_id_reads_the_chats_flow(self, monkeypatch):
        mine, _service = self._rig(monkeypatch)

        result = await get_flow(ctx=CTX)

        assert f"Flow '{mine.name}' (flow_id {mine.id}; revision 1;" in _text(result)
        assert result.structuredContent["flow_id"] == str(mine.id)

    async def test_a_given_flow_id_wins_over_the_chats_flow(self, monkeypatch):
        mine, service = self._rig(monkeypatch)
        other = next(flow for flow in service.flows.values() if flow.id != mine.id)

        result = await get_flow(flow_id=other.id, ctx=CTX)

        assert result.structuredContent["flow_id"] == str(other.id)

    async def test_a_chat_without_a_flow_is_told_so(self, monkeypatch):
        space_id = uuid4()
        service = FakeFlowService([_flow(space_id=space_id)])
        _patch_context(
            monkeypatch, flow_service=service, space_id=space_id, session_id=uuid4()
        )

        for tool, kwargs in (
            (get_flow, {}),
            (update_flow, {"name": "x"}),
            (publish_flow, {}),
            (list_revisions, {}),
            (restore_revision, {"revision": 1}),
            (run_flow, {"inputs": {}}),
            (delete_flow, {}),
        ):
            result = await tool(ctx=CTX, **kwargs)
            assert _text(result).endswith(NOT_BOUND_MESSAGE), tool.__name__
            assert result.structuredContent["flow_id"] is None
        assert service.calls == []

    async def test_a_token_without_a_session_is_not_bound(self, monkeypatch):
        space_id = uuid4()
        _patch_context(
            monkeypatch,
            flow_service=FakeFlowService([_flow(space_id=space_id)]),
            space_id=space_id,
            session_id=None,
        )

        result = await get_flow(ctx=CTX)

        assert _text(result) == f"Could not get flow: {NOT_BOUND_MESSAGE}"

    async def test_validation_problems_come_back_as_repairable_text(self, monkeypatch):
        mine, service = self._rig(
            monkeypatch,
        )
        service.error = BadRequestException(
            "step 'draft' prompt: {{form.title}} names no form field"
        )

        result = await update_flow(
            expected_revision=1,
            steps=[LlmStep(key="draft", name="Draft", prompt="{{form.title}}")],
            ctx=CTX,
        )

        assert _text(result).startswith(
            "Could not update flow: step 'draft' prompt: {{form.title}} names no "
            "form field"
        )
        assert result.isError is False
        assert result.structuredContent["flow"] is None
        assert result.structuredContent["flow_id"] == str(mine.id)
        assert result.structuredContent["error"].startswith("step 'draft'")

    async def test_oversized_definition_is_reported_not_raised(self, monkeypatch):
        self._rig(monkeypatch)
        too_many = [
            FormField(key=f"f{i}", label=str(i), type="text") for i in range(40)
        ]

        result = await update_flow(expected_revision=1, form_fields=too_many, ctx=CTX)

        assert _text(result).startswith("Could not update flow: form_fields:")

    async def test_an_ordinary_assistant_is_refused(self, monkeypatch):
        service = FakeFlowService()
        _patch_context(monkeypatch, flow_service=service, purpose=None)

        result = await update_flow(expected_revision=1, name="Brief", ctx=CTX)

        assert _text(result) == (
            f"Could not update flow: {NOT_AUTHORING_ASSISTANT_MESSAGE}"
        )
        assert service.calls == []


VIEW_MODE_MESSAGE = (
    "The flow is shown in view mode. Ask the user to press Redigera in the flow "
    "panel to enter edit mode."
)


class TestEditModeGate:
    """The write tools refuse while the user views the flow; the rest do not."""

    def _rig(self, monkeypatch):
        session_id = uuid4()
        space_id = uuid4()
        mine = _flow(space_id=space_id, conversation_id=session_id)
        service = FakeFlowService([mine], editing_error=FlowNotEditingException())
        _patch_context(
            monkeypatch,
            flow_service=service,
            run_service=FakeFlowRunService([_run_state(mine)]),
            space_id=space_id,
            session_id=session_id,
        )
        return mine, service

    async def test_update_flow_in_view_mode_tells_the_model_to_ask_for_edit_mode(
        self, monkeypatch
    ):
        mine, service = self._rig(monkeypatch)

        result = await update_flow(
            expected_revision=1, name="Daily brief", note="Renamed", ctx=CTX
        )

        assert _text(result) == f"Could not update flow: {VIEW_MODE_MESSAGE}"
        assert result.isError is False
        assert result.structuredContent["flow_id"] == str(mine.id)
        assert result.structuredContent["flow"] is None
        assert result.structuredContent["error"] == VIEW_MODE_MESSAGE
        assert service.edit_checks == [mine.id]
        assert service.calls == []
        assert service.flows[mine.id].name == mine.name

    async def test_every_write_tool_is_gated_before_it_changes_anything(
        self, monkeypatch
    ):
        mine, service = self._rig(monkeypatch)

        results = [
            ("restore revision", await restore_revision(revision=1, ctx=CTX)),
            ("publish flow", await publish_flow(ctx=CTX)),
            ("delete flow", await delete_flow(ctx=CTX)),
        ]

        for action, result in results:
            assert _text(result) == f"Could not {action}: {VIEW_MODE_MESSAGE}"
            assert result.structuredContent["flow_id"] == str(mine.id)
        assert service.edit_checks == [mine.id] * 3
        assert service.calls == []
        assert mine.id in service.flows
        assert service.flows[mine.id].published_version is None

    async def test_running_and_reading_do_not_need_edit_mode(self, monkeypatch):
        mine, service = self._rig(monkeypatch)

        run = await run_flow(inputs={"topic": "x"}, draft=True, ctx=CTX)
        read = await get_flow(ctx=CTX)
        history = await list_revisions(ctx=CTX)

        assert not _text(run).startswith("Could not")
        assert read.structuredContent["flow"]["id"] == str(mine.id)
        assert history.structuredContent["revisions"]
        assert service.edit_checks == []


class TestFlowScoping:
    async def test_another_spaces_flow_reads_as_not_found(self, monkeypatch):
        other = _flow(space_id=uuid4())
        _patch_context(monkeypatch, flow_service=FakeFlowService([other]))

        result = await get_flow(flow_id=other.id, ctx=CTX)

        assert _text(result) == f"Could not get flow: {FLOW_NOT_FOUND_MESSAGE}"
        assert result.structuredContent == {
            "flow_id": str(other.id),
            "run_id": None,
            "flow": None,
            "run": None,
            "error": FLOW_NOT_FOUND_MESSAGE,
        }

    async def test_unknown_flow_reads_the_same(self, monkeypatch):
        _patch_context(monkeypatch, flow_service=FakeFlowService())

        result = await get_flow(flow_id=uuid4(), ctx=CTX)

        assert _text(result) == f"Could not get flow: {FLOW_NOT_FOUND_MESSAGE}"

    async def test_list_flows_names_every_flow_of_the_space(self, monkeypatch):
        space_id = uuid4()
        mine = _flow(space_id=space_id, published_version=2)
        service = FakeFlowService([mine, _flow(space_id=uuid4())])
        _patch_context(monkeypatch, flow_service=service, space_id=space_id)

        result = await list_flows(ctx=CTX)

        assert f"'{mine.name}' (flow_id {mine.id}; published v2" in _text(result)
        assert result.structuredContent["flow_id"] is None
        assert [row["id"] for row in result.structuredContent["flows"]] == [
            str(mine.id)
        ]


class TestUpdatePublishDelete:
    async def test_update_keeps_the_list_that_was_not_given(self, monkeypatch):
        space_id = uuid4()
        flow = _flow(space_id=space_id)
        service = FakeFlowService([flow])
        _patch_context(monkeypatch, flow_service=service, space_id=space_id)

        result = await update_flow(
            expected_revision=1,
            flow_id=flow.id,
            steps=[
                ComposeStep(key="wrap", name="Only wrap", template="{{form.topic}}")
            ],
            ctx=CTX,
        )

        _, channel, name, _description, definition, note = service.calls[0]
        assert channel == "mcp"
        assert name is None
        assert note is None
        assert definition.form_fields == flow.definition.form_fields
        assert [step.key for step in definition.steps] == ["wrap"]
        assert "1. [compose] Only wrap (key: wrap)" in _text(result)
        # The step kept its id by key, as the service guarantees.
        kept = result.structuredContent["flow"]["definition"]["steps"][0]["id"]
        assert kept == str(flow.definition.steps[1].id)

    async def test_update_with_nothing_to_change_is_reported(self, monkeypatch):
        space_id = uuid4()
        flow = _flow(space_id=space_id)
        service = FakeFlowService([flow])
        _patch_context(monkeypatch, flow_service=service, space_id=space_id)

        result = await update_flow(expected_revision=1, flow_id=flow.id, ctx=CTX)

        assert _text(result).startswith("Could not update flow: Nothing to change")
        assert service.calls == []

    async def test_publish_reports_the_version_and_run_contract(self, monkeypatch):
        space_id = uuid4()
        flow = _flow(space_id=space_id)
        service = FakeFlowService([flow])
        _patch_context(monkeypatch, flow_service=service, space_id=space_id)

        result = await publish_flow(flow_id=flow.id, ctx=CTX)

        text = _text(result)
        assert text.startswith(f"Published '{flow.name}' as version 1.")
        assert "Run inputs: topic (text, required)." in text
        assert result.structuredContent["published_version"] == 1
        assert result.structuredContent["run_contract"]["flow_id"] == str(flow.id)
        assert service.calls == [("publish_flow", "mcp")]

    async def test_delete_reports_the_flow_id(self, monkeypatch):
        space_id = uuid4()
        flow = _flow(space_id=space_id)
        service = FakeFlowService([flow])
        _patch_context(monkeypatch, flow_service=service, space_id=space_id)

        result = await delete_flow(flow_id=flow.id, ctx=CTX)

        assert _text(result) == f"Deleted flow '{flow.name}'."
        assert result.structuredContent["flow_id"] == str(flow.id)
        assert result.structuredContent["deleted"] is True
        assert flow.id not in service.flows


class TestRevisions:
    async def test_update_passes_the_note_and_reports_the_revision(self, monkeypatch):
        space_id = uuid4()
        flow = _flow(space_id=space_id)
        service = FakeFlowService([flow])
        _patch_context(monkeypatch, flow_service=service, space_id=space_id)

        result = await update_flow(
            expected_revision=1,
            flow_id=flow.id,
            name="Daily brief",
            note="Renamed at the user's request",
            ctx=CTX,
        )

        assert service.calls[0][-1] == "Renamed at the user's request"
        text = _text(result)
        assert text.startswith("Draft updated as revision 2.")
        assert "revision 2;" in text
        assert result.structuredContent["flow"]["revision"] == 2

    async def test_get_flow_names_the_revision(self, monkeypatch):
        space_id = uuid4()
        flow = _flow(space_id=space_id).model_copy(update={"revision": 4})
        _patch_context(
            monkeypatch, flow_service=FakeFlowService([flow]), space_id=space_id
        )

        result = await get_flow(flow_id=flow.id, ctx=CTX)

        assert f"(flow_id {flow.id}; revision 4; not published yet)" in _text(result)

    async def test_list_revisions_tells_the_history_newest_first(self, monkeypatch):
        space_id = uuid4()
        flow = _flow(space_id=space_id)
        service = FakeFlowService([flow])
        _patch_context(monkeypatch, flow_service=service, space_id=space_id)
        await update_flow(
            expected_revision=1,
            flow_id=flow.id,
            name="Daily brief",
            note="Renamed",
            ctx=CTX,
        )
        service.revisions[flow.id][0] = service.revisions[flow.id][0].model_copy(
            update={"published_version": 1}
        )

        result = await list_revisions(flow_id=flow.id, ctx=CTX)

        text = _text(result)
        assert text.startswith(
            f"History of 'Daily brief' (flow_id {flow.id}): 2 revision(s), current is 2."
        )
        lines = text.splitlines()
        assert lines[1].startswith(
            "- revision 2 (2026-10-20 12:00, via chat): name changed"
        )
        assert 'Note: "Renamed"' in lines[1]
        assert lines[2].startswith(
            "- revision 1 (2026-10-20 12:00, via API): first revision"
        )
        assert lines[2].endswith("[published as version 1]")
        assert "restore_revision" in lines[-1]
        structured = result.structuredContent
        assert structured["flow_id"] == str(flow.id)
        assert structured["run_id"] is None
        assert structured["flow"] is None
        assert structured["run"] is None
        assert [row["revision"] for row in structured["revisions"]] == [2, 1]
        assert structured["revisions"][1]["changes"]["is_initial"] is True

    async def test_list_revisions_of_another_spaces_flow_reads_as_not_found(
        self, monkeypatch
    ):
        other = _flow(space_id=uuid4())
        _patch_context(monkeypatch, flow_service=FakeFlowService([other]))

        result = await list_revisions(flow_id=other.id, ctx=CTX)

        assert _text(result) == f"Could not list revisions: {FLOW_NOT_FOUND_MESSAGE}"
        assert "revisions" not in result.structuredContent

    async def test_restore_revision_returns_the_restored_flow(self, monkeypatch):
        space_id = uuid4()
        flow = _flow(space_id=space_id)
        service = FakeFlowService([flow])
        _patch_context(monkeypatch, flow_service=service, space_id=space_id)
        await update_flow(
            expected_revision=1, flow_id=flow.id, name="Daily brief", ctx=CTX
        )

        result = await restore_revision(flow_id=flow.id, revision=1, ctx=CTX)

        assert service.calls[-1] == ("restore_revision", flow.id, 1, "mcp")
        text = _text(result)
        assert text.startswith("Restored revision 1 as the draft (now revision 3).")
        assert f"Flow '{flow.name}' (flow_id {flow.id}; revision 3;" in text
        assert result.structuredContent["flow"]["revision"] == 3
        assert result.structuredContent["restored_from"] == 1

    async def test_restore_of_an_unknown_revision_is_repairable(self, monkeypatch):
        space_id = uuid4()
        flow = _flow(space_id=space_id)
        _patch_context(
            monkeypatch, flow_service=FakeFlowService([flow]), space_id=space_id
        )

        result = await restore_revision(flow_id=flow.id, revision=9, ctx=CTX)

        assert _text(result) == "Could not restore revision: Flow revision not found"
        assert result.structuredContent["flow"] is None


class TestRuns:
    def _rig(self, monkeypatch, **context):
        space_id = uuid4()
        flow = _flow(space_id=space_id, published_version=1)
        run = _run_state(flow)
        flow_service = FakeFlowService([flow])
        run_service = FakeFlowRunService(
            [run], checkpoint=context.pop("checkpoint", None)
        )
        _patch_context(
            monkeypatch,
            flow_service=flow_service,
            run_service=run_service,
            space_id=space_id,
            **context,
        )
        return flow, run, run_service

    async def test_run_flow_maps_reference_urls_to_file_ids(self, monkeypatch):
        tenant_id = uuid4()
        file_id = uuid4()
        flow, run, run_service = self._rig(monkeypatch, tenant_id=tenant_id)

        def verify(url):
            assert url == "https://eneo.example/files/ref?t=signed"
            return file_id, {"file_id": str(file_id), "tenant_id": str(tenant_id)}

        async def metadata(resolved_id, payload, tool_ctx, *, log_tag):
            assert resolved_id == file_id
            assert payload["tenant_id"] == str(tool_ctx.user.tenant_id)
            return SimpleNamespace(id=file_id, tenant_id=tenant_id)

        monkeypatch.setattr("eneo.internal_mcp.flows.verify_reference_url", verify)
        monkeypatch.setattr(
            "eneo.internal_mcp.flows.referenced_file_metadata", metadata
        )

        result = await run_flow(
            flow_id=flow.id,
            inputs={"topic": "waste", "count": 3},
            files={"source": ["https://eneo.example/files/ref?t=signed"]},
            run_label="Monday",
            ctx=CTX,
        )

        assert run_service.calls == [
            (
                "create_run",
                flow.id,
                {"topic": "waste", "count": 3},
                {"source": [file_id]},
                "Monday",
                "mcp",
            )
        ]
        text = _text(result)
        assert text.startswith(
            f"Run {run.run_id} of '{flow.name}' (version 1) is queued."
        )
        assert "get_run" in text
        assert result.structuredContent["flow_id"] == str(flow.id)
        assert result.structuredContent["run_id"] == str(run.run_id)
        assert result.structuredContent["run"]["status"] == "queued"
        assert result.structuredContent["flow"] is None

    async def test_run_flow_rejects_a_bad_reference_as_text(self, monkeypatch):
        flow, _run, run_service = self._rig(monkeypatch)

        def verify(_url):
            raise FileReferenceRejected("The attachment link is invalid.")

        monkeypatch.setattr("eneo.internal_mcp.flows.verify_reference_url", verify)

        result = await run_flow(
            flow_id=flow.id, inputs={}, files={"source": ["nope"]}, ctx=CTX
        )

        assert _text(result) == "Could not run flow: The attachment link is invalid."
        assert run_service.calls == []

    async def test_get_run_of_another_space_reads_as_not_found(self, monkeypatch):
        flow = _flow(space_id=uuid4())
        run = _run_state(flow)
        _patch_context(
            monkeypatch,
            flow_service=FakeFlowService([flow]),
            run_service=FakeFlowRunService([run]),
        )

        result = await get_run(run_id=run.run_id, ctx=CTX)

        assert _text(result) == f"Could not get run: {RUN_NOT_FOUND_MESSAGE}"
        assert result.structuredContent["run_id"] == str(run.run_id)
        assert result.structuredContent["run"] is None

    async def test_get_run_text_lists_steps_and_a_waiting_review(self, monkeypatch):
        space_id = uuid4()
        flow = _flow(space_id=space_id, published_version=1)
        run = _run_state(flow, status=FlowRunStatus.AWAITING_REVIEW)
        run = run.model_copy(update={"review_checkpoint": _checkpoint(run)})
        _patch_context(
            monkeypatch,
            flow_service=FakeFlowService([flow]),
            run_service=FakeFlowRunService([run]),
            space_id=space_id,
        )

        result = await get_run(run_id=run.run_id, ctx=CTX)

        text = _text(result)
        assert "awaiting_review" in text
        assert "1. [llm] Draft: pending" in text
        assert "A review is waiting (edit, revision 3)" in text
        assert result.structuredContent["run"]["review_checkpoint"]["revision"] == 3

    async def test_cancel_run_reports_the_new_status(self, monkeypatch):
        flow, run, run_service = self._rig(monkeypatch)

        result = await cancel_run(run_id=run.run_id, ctx=CTX)

        assert run_service.calls == [("cancel_run", run.run_id, flow.id, "mcp")]
        assert _text(result).startswith(f"Run {run.run_id} is cancelled.")
        assert result.structuredContent["run"]["status"] == "cancelled"

    async def test_review_run_edits_then_approves_with_resume(self, monkeypatch):
        flow, run, run_service = self._rig(
            monkeypatch, checkpoint=_checkpoint(_run_state(_flow(space_id=uuid4())))
        )
        checkpoint_id = run_service.checkpoint.id

        result = await review_run(
            run_id=run.run_id, decision="approve", edited_text="better", ctx=CTX
        )

        assert run_service.calls == [
            ("edit_checkpoint", checkpoint_id, 3, {"text": "better"}),
            ("approve_checkpoint", checkpoint_id, 4, True, "mcp"),
        ]
        assert _text(result).startswith(f"Review approved; run {run.run_id} is queued.")
        assert result.structuredContent["run_id"] == str(run.run_id)

    async def test_review_run_json_edit_uses_the_value_payload(self, monkeypatch):
        checkpoint = _checkpoint(
            _run_state(_flow(space_id=uuid4())), output_type="json"
        )
        flow, run, run_service = self._rig(monkeypatch, checkpoint=checkpoint)

        await review_run(
            run_id=run.run_id,
            decision="approve",
            edited_value={"items": []},
            ctx=CTX,
        )

        assert run_service.calls[0] == (
            "edit_checkpoint",
            checkpoint.id,
            3,
            {"value": {"items": []}},
        )

    async def test_review_run_rejects_with_reason(self, monkeypatch):
        checkpoint = _checkpoint(_run_state(_flow(space_id=uuid4())))
        flow, run, run_service = self._rig(monkeypatch, checkpoint=checkpoint)

        result = await review_run(
            run_id=run.run_id, decision="reject", reason="wrong tone", ctx=CTX
        )

        assert run_service.calls == [
            ("reject_checkpoint", checkpoint.id, 3, "wrong tone", "mcp")
        ]
        assert _text(result).startswith(f"Review rejected; run {run.run_id} is failed.")

    async def test_review_run_without_a_waiting_review(self, monkeypatch):
        flow, run, run_service = self._rig(monkeypatch)

        result = await review_run(run_id=run.run_id, decision="approve", ctx=CTX)

        assert _text(result) == f"Could not review run: {NO_REVIEW_WAITING_MESSAGE}"
        assert run_service.calls == []

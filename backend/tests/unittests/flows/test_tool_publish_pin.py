"""What publish does with a step whose input source is ``tool``: it asks the
chain whether the flow's space may use the tool, and pins what it found."""

from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest

from eneo.flows.application import flow_tool_publication
from eneo.flows.application.flow_service import FlowService
from eneo.flows.domain.canonical_json_hash import canonical_json_hash
from eneo.flows.domain.flow import Flow, FlowStep
from eneo.flows.output_processing import ContractUnevaluable, refuse_unknown_dialect
from eneo.flows.published_definition import (
    PublishedDefinitionIntegrityStatus,
    inspect_published_definition_integrity,
    published_definition_checksum,
)
from eneo.main.exceptions import BadRequestException
from eneo.mcp_servers.application.unattended_tool_use import (
    UnattendedToolFacts,
    UnattendedToolRefusal,
)
from eneo.mcp_servers.domain.entities.mcp_server import MCPServer, MCPServerTool
from tests.unittests.flows.test_flow_service import _service, _step

_NOT_ALLOWED = "typed_io_tool_not_allowed"
_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {"case_id": {"type": "string"}},
}


def _facts(
    *,
    input_schema: dict[str, object] | None = None,
    server: dict[str, object] | None = None,
    tool: dict[str, object] | None = None,
    **levels: object,
) -> UnattendedToolFacts:
    """An approved, switched-on tool of a general server its space
    activated, with the named facts changed."""
    the_server = MCPServer(
        id=uuid4(),
        tenant_id=uuid4(),
        name="Cases",
        http_url="https://cases.example.org/mcp",
        is_enabled=True,
    )
    the_tool = MCPServerTool(
        id=uuid4(),
        mcp_server_id=the_server.id,
        name="lookup_case",
        input_schema=input_schema,
        # What the server offers now and no admin has approved: never pinned.
        pending_input_schema={"type": "object", "properties": {}},
        is_enabled_by_default=True,
    )
    for entity, changes in ((the_server, server), (the_tool, tool)):
        for name, value in (changes or {}).items():
            setattr(entity, name, value)
    allowed = UnattendedToolFacts(
        server=the_server,
        tool=the_tool,
        tenant_setting=None,
        space_is_personal=False,
        server_in_space=True,
        space_override=None,
        space_security_classification=None,
    )
    return replace(allowed, **levels)


@dataclass
class _Facts:
    """Answers with the given facts and keeps what it was asked."""

    facts: UnattendedToolFacts
    asked: list[dict[str, UUID]] = field(default_factory=list)

    async def read(
        self, *, tenant_id: UUID, space_id: UUID, mcp_server_id: UUID, tool_id: UUID
    ) -> UnattendedToolFacts:
        self.asked.append(
            {
                "tenant_id": tenant_id,
                "space_id": space_id,
                "mcp_server_id": mcp_server_id,
                "tool_id": tool_id,
            }
        )
        return self.facts


def _tool_flow(user, facts: UnattendedToolFacts) -> Flow:
    """A flow whose second step calls the tool of ``facts`` with one bound and
    one fixed argument."""
    assert facts.server is not None and facts.tool is not None
    tool_step: FlowStep = _step(step_order=2).model_copy(
        update={
            "input_source": "tool",
            "input_config": {
                "tool": {
                    "mcp_server_id": str(facts.server.id),
                    "tool_id": str(facts.tool.id),
                    "arguments": {"case_id": "{{step_1.output.text}}", "limit": 5},
                }
            },
        }
    )
    return Flow(
        id=uuid4(),
        tenant_id=user.tenant_id,
        space_id=uuid4(),
        name="Tool flow",
        created_by_user_id=user.id,
        owner_user_id=user.id,
        draft_revision=3,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        steps=[_step(step_order=1), tool_step],
    )


def _publisher(
    user, flow: Flow, facts: _Facts | None
) -> tuple[FlowService, AsyncMock, AsyncMock]:
    flow_repo, version_repo = AsyncMock(), AsyncMock()
    flow_repo.get.return_value = flow
    flow_repo.allocate_next_version.return_value = 1
    service = _service(
        user=user,
        flow_repo=flow_repo,
        version_repo=version_repo,
        tool_facts_reader=facts,
    )
    return service, flow_repo, version_repo


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("change", "refusal", "who"),
    [
        pytest.param(
            {"server": {"is_enabled": False}},
            UnattendedToolRefusal.SERVER_DISABLED,
            "instance administrator",
            id="server-level",
        ),
        pytest.param(
            {"tool": {"requires_approval": True}},
            UnattendedToolRefusal.TOOL_WAITING_FOR_REVIEW,
            "instance administrator",
            id="tool-level",
        ),
        pytest.param(
            {"server_in_space": False},
            UnattendedToolRefusal.SERVER_NOT_IN_SPACE,
            "space administrator",
            id="space-level",
        ),
    ],
)
async def test_publish_refuses_a_tool_the_chain_does_not_allow(
    user, change: dict[str, object], refusal: UnattendedToolRefusal, who: str
) -> None:
    # Kills the mutants that publish a tool step without asking the decision,
    # ask it about another tenant, space, server or tool, or name another
    # level than the one that refused.
    facts = _Facts(_facts(**change))
    flow = _tool_flow(user, facts.facts)
    service, flow_repo, version_repo = _publisher(user, flow, facts)
    ids = flow.steps[1].input_config["tool"]

    with pytest.raises(BadRequestException) as refused:
        await service.publish_flow(flow_id=flow.id)

    assert refused.value.code == _NOT_ALLOWED
    assert refused.value.context == {
        "step_order": 2,
        "refusal": refusal.value,
        "mcp_server_id": ids["mcp_server_id"],
        "tool_id": ids["tool_id"],
    }
    assert who in str(refused.value)
    assert facts.asked == [
        {
            "tenant_id": user.tenant_id,
            "space_id": flow.space_id,
            "mcp_server_id": UUID(ids["mcp_server_id"]),
            "tool_id": UUID(ids["tool_id"]),
        }
    ]
    version_repo.create.assert_not_awaited()
    flow_repo.update.assert_not_awaited()


def test_every_refusal_of_the_chain_has_its_sentence() -> None:
    # Kills the mutant where the decision gains or renames a refusal and
    # publish has no sentence for it: the refusal would be a server error.
    sentences = flow_tool_publication.REFUSAL_SENTENCES

    assert set(sentences) == set(UnattendedToolRefusal)
    assert all(sentence.endswith(".") for sentence in sentences.values())
    assert len(set(sentences.values())) == len(UnattendedToolRefusal)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("input_schema", "fingerprinted"),
    [
        pytest.param(_SCHEMA, _SCHEMA, id="approved-schema"),
        pytest.param(None, {}, id="no-schema-is-the-empty-object"),
    ],
)
async def test_publish_pins_the_tool_inside_the_checksummed_definition(
    user, input_schema: dict[str, object] | None, fingerprinted: dict[str, object]
) -> None:
    # Kills the mutants that publish a tool step without the pin, pin the
    # schema no admin approved, write the pin into the editable step, or keep
    # the pin outside what the definition's checksum covers.
    facts = _Facts(_facts(input_schema=input_schema))
    flow = _tool_flow(user, facts.facts)
    service, flow_repo, version_repo = _publisher(user, flow, facts)
    saved = flow.steps[1].input_config["tool"]

    await service.publish_flow(flow_id=flow.id)

    definition = version_repo.create.await_args.kwargs["definition_json"]
    assert definition["steps"][1]["input_config"]["tool"] == {
        **saved,
        "tool_name": "lookup_case",
        "input_schema_sha256": canonical_json_hash(fingerprinted),
    }
    assert flow_repo.update.await_args.args[0].steps[1].input_config == {"tool": saved}

    checksum = published_definition_checksum(definition)

    def integrity() -> PublishedDefinitionIntegrityStatus:
        return inspect_published_definition_integrity(
            definition, expected_checksum=checksum, flow_version=1
        ).status

    assert integrity() is PublishedDefinitionIntegrityStatus.VERIFIED
    definition["steps"][1]["input_config"]["tool"]["tool_name"] = "delete_case"
    assert integrity() is PublishedDefinitionIntegrityStatus.INVALID


def _nested_schema(depth: int) -> dict[str, object]:
    schema: dict[str, object] = {"type": "string"}
    for _ in range(depth):
        schema = {"type": "object", "properties": {"inner": schema}}
    return schema


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "input_schema",
    [
        pytest.param({"type": "objekt"}, id="no-json-schema"),
        # The check cannot walk it (RecursionError), so no run could either.
        pytest.param(_nested_schema(400), id="nested-too-deep-to-check"),
    ],
)
async def test_publish_refuses_a_tool_whose_input_schema_is_no_json_schema(
    user, input_schema: dict[str, object]
) -> None:
    # Kills the mutant that pins a tool without asking whether its approved
    # input schema can be evaluated: every run would then fail where the
    # step's arguments are checked, with a refusal that blames the arguments.
    facts = _Facts(_facts(input_schema=input_schema))
    flow = _tool_flow(user, facts.facts)
    service, flow_repo, version_repo = _publisher(user, flow, facts)

    with pytest.raises(BadRequestException) as refused:
        await service.publish_flow(flow_id=flow.id)

    assert refused.value.code == "typed_io_tool_invalid_schema"
    assert refused.value.context == {"step_order": 2}
    version_repo.create.assert_not_awaited()
    flow_repo.update.assert_not_awaited()


@pytest.mark.asyncio
async def test_the_schema_check_does_not_hold_the_event_loop(
    user, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Kills the mutant that checks the schema on the event loop: the check is
    # CPU-bound and grows with the schema, so every other request of the API
    # process would wait for it.
    released = threading.Event()
    waited: list[bool] = []

    def check_that_waits_for_the_loop(schema: object, *, label: str) -> None:
        waited.append(released.wait(timeout=5))

    monkeypatch.setattr(
        flow_tool_publication,
        "refuse_unevaluable_contract",
        check_that_waits_for_the_loop,
    )
    facts = _Facts(_facts(input_schema=_SCHEMA))
    flow = _tool_flow(user, facts.facts)
    service, _, version_repo = _publisher(user, flow, facts)

    async def release() -> None:
        released.set()

    await asyncio.gather(service.publish_flow(flow_id=flow.id), release())

    assert waited == [True]
    version_repo.create.assert_awaited_once()


@pytest.mark.asyncio
async def test_publish_reports_the_first_refused_tool_step_in_step_order(
    user,
) -> None:
    # Kills the mutant that asks about the tool steps in another order than
    # the steps': with two refused steps the author would be sent to the
    # later one first.
    refused_facts = _facts(server={"is_enabled": False})
    flow = _tool_flow(user, refused_facts)
    later = flow.steps[1].model_copy(
        update={"id": uuid4(), "step_order": 3, "user_description": "Step 3"}
    )
    flow = flow.model_copy(update={"steps": [later, *flow.steps]})
    service, _, _ = _publisher(user, flow, _Facts(refused_facts))

    with pytest.raises(BadRequestException) as refused:
        await service.publish_flow(flow_id=flow.id)

    assert (refused.value.code, (refused.value.context or {})["step_order"]) == (
        _NOT_ALLOWED,
        2,
    ), str(refused.value)


_DRAFTS = [
    "http://json-schema.org/draft-03/schema#",
    "http://json-schema.org/draft-04/schema#",
    "http://json-schema.org/draft-06/schema#",
    "http://json-schema.org/draft-07/schema#",
    "https://json-schema.org/draft/2019-09/schema",
    "https://json-schema.org/draft/2020-12/schema",
]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("dialect", "published"),
    [
        *((draft, True) for draft in _DRAFTS),
        pytest.param(None, True, id="no-dialect-named"),
        pytest.param("https://example.invalid/not-a-draft", False, id="unknown"),
    ],
)
async def test_publish_refuses_a_tool_schema_of_a_draft_eneo_does_not_know(
    user, dialect: str | None, published: bool
) -> None:
    # Kills the mutant that checks a schema naming a dialect the validator
    # library does not have as if it were the default draft: the tool would
    # be pinned on a check by other rules than the schema's own. Also the
    # mutants that refuse a draft the library has, or a schema that names
    # none.
    named = {} if dialect is None else {"$schema": dialect}
    facts = _Facts(_facts(input_schema={**named, "type": "object"}))
    flow = _tool_flow(user, facts.facts)
    service, _, version_repo = _publisher(user, flow, facts)

    if published:
        await service.publish_flow(flow_id=flow.id)
        version_repo.create.assert_awaited_once()
        return
    with pytest.raises(BadRequestException) as refused:
        await service.publish_flow(flow_id=flow.id)
    assert refused.value.code == "typed_io_tool_invalid_schema"
    assert "a draft Eneo does not support" in str(refused.value)
    version_repo.create.assert_not_awaited()


def test_a_dialect_name_that_is_no_uri_is_refused_as_unevaluable() -> None:
    # Kills the mutant that lets the library's ValueError for a `$schema` that
    # is no URI escape untyped, or returns on it as if it named a known draft.
    with pytest.raises(ContractUnevaluable):
        refuse_unknown_dialect({"$schema": "http://[not-a-uri"}, label="Step 2")


@pytest.mark.asyncio
async def test_one_publish_checks_a_schema_once_for_all_the_steps_that_use_it(
    user, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Kills the mutant that checks the approved schema again for every tool
    # step of a publish: the check costs seconds for a large schema.
    checked: list[object] = []
    monkeypatch.setattr(
        flow_tool_publication,
        "refuse_unevaluable_contract",
        lambda schema, *, label: checked.append(schema),
    )
    facts = _Facts(_facts(input_schema=_SCHEMA))
    flow = _tool_flow(user, facts.facts)
    again = flow.steps[1].model_copy(
        update={"id": uuid4(), "step_order": 3, "user_description": "Step 3"}
    )
    flow = flow.model_copy(update={"steps": [*flow.steps, again]})
    service, _, version_repo = _publisher(user, flow, facts)

    await service.publish_flow(flow_id=flow.id)

    assert checked == [_SCHEMA]
    definition = version_repo.create.await_args.kwargs["definition_json"]
    assert (
        definition["steps"][1]["input_config"]["tool"]["input_schema_sha256"]
        == definition["steps"][2]["input_config"]["tool"]["input_schema_sha256"]
        == canonical_json_hash(_SCHEMA)
    )

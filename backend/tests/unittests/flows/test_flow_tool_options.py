"""The tools a flow's step can choose from: the space's, each with the decision."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from enum import Enum
from types import SimpleNamespace
from typing import get_args
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest

from eneo.flows.api.flow_tool_options_models import (
    FlowToolOptionPublic,
    FlowToolOptionsPublic,
)
from eneo.flows.api.flow_tool_options_router import list_flow_tool_options
from eneo.flows.application.flow_tool_options import (
    FLOW_TOOL_OPTIONS_MAX_COUNT,
    FLOW_TOOL_OPTIONS_MAX_TEXT_BYTES,
    FlowToolOptions,
    flow_tool_option,
)
from eneo.flows.domain.flow import Flow
from eneo.main.exceptions import FileTooLargeException, UnauthorizedException
from eneo.mcp_servers.application.unattended_tool_use import (
    ListedServer,
    ListedTool,
    ListedToolFacts,
    ToolsOfSpace,
    UnattendedToolRefusal,
)
from eneo.mcp_servers.infrastructure.repo_impl.unattended_tool_facts_reader import (
    LISTED_TEXT_FIELDS,
)
from eneo.roles.permissions import Permission
from eneo.security_classifications.domain.entities.security_classification import (
    SecurityClassification,
)
from tests.unittests.flows.test_flow_router import _enable_space_access, _request
from tests.unittests.flows.test_flow_service import _service, _step


def _listed(
    *, tool: dict[str, object] | None = None, **levels: object
) -> ListedToolFacts:
    """An approved, switched-on tool of a general server its space
    activated, as the list reads it, with the named facts changed."""
    server = ListedServer(
        id=uuid4(),
        name="Cases",
        is_enabled=True,
        purpose="general",
        http_auth_type="none",
        http_url="https://cases.example.org/mcp",
        forward_identity=False,
        effective_security_classification=None,
    )
    the_tool = ListedTool(
        id=uuid4(),
        mcp_server_id=server.id,
        name="lookup_case",
        description=None,
        input_schema=None,
        is_enabled_by_default=True,
        requires_approval=False,
        removed_from_remote=False,
    )
    allowed = ListedToolFacts(
        server=server,
        tool=replace(the_tool, **(tool or {})),
        tenant_setting=None,
        space_is_personal=False,
        server_in_space=True,
        space_override=None,
        space_security_classification=None,
    )
    return replace(allowed, **levels)


@dataclass
class _SpaceTools:
    listed: ToolsOfSpace
    asked: list[dict[str, object]] = field(default_factory=list)

    async def read(self, **_: object) -> object:
        raise AssertionError("the list reads no single tool")

    async def read_tools_of_space(
        self,
        *,
        tenant_id: UUID,
        space_id: UUID,
        max_count: int,
        max_text_bytes: int,
    ) -> ToolsOfSpace:
        self.asked.append(
            {
                "tenant_id": tenant_id,
                "space_id": space_id,
                "max_count": max_count,
                "max_text_bytes": max_text_bytes,
            }
        )
        return self.listed


def _flow(user) -> Flow:
    return Flow(
        id=uuid4(),
        tenant_id=user.tenant_id,
        space_id=uuid4(),
        name="Flow",
        created_by_user_id=user.id,
        owner_user_id=user.id,
        draft_revision=1,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        steps=[_step(step_order=1)],
    )


async def _options(user, listed: ToolsOfSpace):
    flow, tools, flow_repo = _flow(user), _SpaceTools(listed), AsyncMock()
    flow_repo.get.return_value = flow
    service = _service(
        user=user,
        flow_repo=flow_repo,
        version_repo=AsyncMock(),
        tool_facts_reader=tools,
    )
    return flow, tools, await service.list_tool_options(flow_id=flow.id)


@pytest.mark.asyncio
async def test_refused_tools_are_listed_in_the_order_the_reader_gave(user) -> None:
    # Kills "refused tools are left out of the list" and "the service sorts".
    _, _, listed = await _options(
        user,
        ToolsOfSpace(
            facts=[
                _listed(tool={"name": "zeta"}),
                _listed(space_override=False, tool={"name": "alpha"}),
            ],
            text_bytes=0,
        ),
    )

    assert [(o.tool_name, o.refusal) for o in listed.options] == [
        ("zeta", None),
        ("alpha", UnattendedToolRefusal.TOOL_SWITCHED_OFF_IN_SPACE),
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("server_level", "security_enabled", "shown"),
    [(None, True, None), (30, True, 30), (30, False, None)],
    ids=["server-without-class", "server-class", "classes-switched-off"],
)
async def test_the_list_says_whether_classes_apply_and_each_server_level(
    user,
    monkeypatch: pytest.MonkeyPatch,
    server_level: int | None,
    security_enabled: bool,
    shown: int | None,
) -> None:
    # Kills "the list does not say whether classes are on", "an option leaves
    # its server's level out", "it shows the space's level" and "it shows a
    # level while the organization has classes off" (the organization's
    # switch the rule reads, not one carried on a classification row).
    monkeypatch.setattr(user.tenant, "security_enabled", security_enabled)

    def level(security_level: int) -> SecurityClassification:
        return SecurityClassification(
            tenant_id=user.tenant_id,
            name="Class",
            security_level=security_level,
            security_enabled=True,
        )

    facts = _listed(space_security_classification=level(10))
    server = replace(
        facts.server,
        effective_security_classification=(
            None if server_level is None else level(server_level)
        ),
    )
    _, _, listed = await _options(
        user, ToolsOfSpace(facts=[replace(facts, server=server)], text_bytes=0)
    )

    public = FlowToolOptionsPublic.from_options(listed)
    assert public.security_classifications_enabled is security_enabled
    assert [item.mcp_server_security_level for item in public.items] == [shown]


_COUNT, _BYTES = FLOW_TOOL_OPTIONS_MAX_COUNT, FLOW_TOOL_OPTIONS_MAX_TEXT_BYTES


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("read_tools", "text_bytes", "refused"),
    [(_COUNT + 1, 0, True), (1, _BYTES + 1, True), (_COUNT, _BYTES, False)],
    ids=["one-over-the-count", "over-the-bytes", "at-both-bounds"],
)
async def test_a_list_the_read_ended_past_a_bound_is_refused(
    user, read_tools: int, text_bytes: int, refused: bool
) -> None:
    # Kills "the bound is not checked", "bytes are not checked", "a bound is
    # exclusive" and "the reader is asked for another space or other bounds
    # than the list checks".
    listed = ToolsOfSpace(
        facts=[_listed() for _ in range(read_tools)],
        text_bytes=text_bytes,
    )
    if refused:
        with pytest.raises(FileTooLargeException) as raised:
            await _options(user, listed)
        assert raised.value.code == "flow_tool_options_too_large"
        return

    flow, tools, options = await _options(user, listed)

    assert len(options.options) == read_tools
    assert tools.asked == [
        {
            "tenant_id": user.tenant_id,
            "space_id": flow.space_id,
            "max_count": _COUNT,
            "max_text_bytes": _BYTES,
        }
    ]


def _is_fixed_length(annotation: object) -> bool:
    members = get_args(annotation) or (annotation,)
    return all(
        member is type(None)
        or (isinstance(member, type) and issubclass(member, (UUID, Enum, bool, int)))
        for member in members
    )


def test_the_text_budget_counts_every_variable_length_field_an_option_returns() -> None:
    # Kills "a field an option returns is left out of the budget": the server
    # name, the tool name, or a str / JSON field added to the response model
    # later that LISTED_TEXT_FIELDS does not name, which the cost bound would
    # not see.
    returned = {
        name
        for name, option_field in FlowToolOptionPublic.model_fields.items()
        if not _is_fixed_length(option_field.annotation)
    }

    assert returned == set(LISTED_TEXT_FIELDS)


def _route_container(user, flow: Flow, *, can_edit: bool, permissions: list):
    container = MagicMock()
    flow_service = AsyncMock()
    flow_service.get_flow.return_value = flow
    container.flow_service.return_value = flow_service
    container.user.return_value = SimpleNamespace(
        id=uuid4(), tenant_id=user.tenant_id, permissions=permissions
    )
    _enable_space_access(
        container, can_read=True, can_edit=can_edit, user_permissions=permissions
    )
    return container, flow_service


@pytest.mark.asyncio
async def test_the_route_answers_the_options_of_the_path_flow(user) -> None:
    # Kills "the route asks for another flow" and "the route returns the
    # service's list unconverted".
    flow, asked = _flow(user), []

    async def _list(*, flow_id: UUID) -> FlowToolOptions:
        asked.append(flow_id)
        return FlowToolOptions(
            options=[flow_tool_option(_listed(), security_enabled=False)],
            security_classifications_enabled=False,
        )

    container, flow_service = _route_container(
        user, flow, can_edit=True, permissions=[Permission.FLOWS]
    )
    flow_service.list_tool_options.side_effect = _list

    response = await list_flow_tool_options(
        id=flow.id, request=_request(), container=container
    )

    assert asked == [flow.id]
    # The access check loads no space with its MCP catalog.
    container.space_service.return_value.get_space.assert_not_awaited()
    assert isinstance(response, FlowToolOptionsPublic)
    assert [item.tool_name for item in response.items] == ["lookup_case"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("can_edit", "permissions", "code"),
    [
        (True, [], "insufficient_tenant_permission"),
        (False, [Permission.FLOWS], "insufficient_space_permission"),
    ],
)
async def test_the_route_refuses_whoever_may_not_edit_flows_in_the_space(
    user, can_edit: bool, permissions: list, code: str
) -> None:
    # Kills "anybody who can read the flow gets the list".
    flow = _flow(user)
    container, flow_service = _route_container(
        user, flow, can_edit=can_edit, permissions=permissions
    )

    with pytest.raises(UnauthorizedException) as refused:
        await list_flow_tool_options(
            id=flow.id, request=_request(), container=container
        )

    assert refused.value.code == code
    flow_service.list_tool_options.assert_not_awaited()

from __future__ import annotations

from typing import get_args
from uuid import uuid4

import pytest
from pydantic import ValidationError

from intric.assistants.api.assistant_models import AssistantUpdatePublic
from intric.flows.api.flow_assistant_update_adapter import (
    to_flow_assistant_update_command,
)
from intric.flows.application.flow_assistant_update import (
    FlowAssistantUpdateCommand,
    FlowAssistantUpdateField,
)
from intric.main.models import NOT_PROVIDED


def test_flow_assistant_update_field_type_matches_model_fields() -> None:
    assert set(get_args(FlowAssistantUpdateField)) == set(
        FlowAssistantUpdateCommand.model_fields
    )


def test_flow_assistant_update_command_tracks_explicit_fields() -> None:
    empty = FlowAssistantUpdateCommand()
    assert not empty.is_set("description")
    assert not empty.is_set("groups")
    assert empty.description is NOT_PROVIDED
    assert empty.metadata_json is NOT_PROVIDED
    assert empty.icon_id is NOT_PROVIDED
    assert empty.data_retention_days is NOT_PROVIDED

    explicit_none = FlowAssistantUpdateCommand(
        description=None,
        metadata_json=None,
        icon_id=None,
        data_retention_days=None,
        groups=None,
    )

    assert explicit_none.description is None
    assert explicit_none.metadata_json is None
    assert explicit_none.icon_id is None
    assert explicit_none.data_retention_days is None
    assert explicit_none.groups is None
    assert explicit_none.is_set("description")
    assert explicit_none.is_set("metadata_json")
    assert explicit_none.is_set("icon_id")
    assert explicit_none.is_set("data_retention_days")
    assert explicit_none.is_set("groups")


def test_flow_assistant_update_command_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        FlowAssistantUpdateCommand.model_validate({"mcp_servers_ids": []})


def test_flow_assistant_update_command_reports_security_fields_only_when_set() -> None:
    assert not FlowAssistantUpdateCommand(name="Renamed").changed_security_field_names()
    assert FlowAssistantUpdateCommand(groups=None).changed_security_field_names() == (
        frozenset({"groups"})
    )
    assert FlowAssistantUpdateCommand(
        mcp_server_ids=[]
    ).changed_security_field_names() == (frozenset({"mcp_server_ids"}))


@pytest.mark.parametrize(
    ("field_name", "field_value"),
    [
        ("completion_model_id", uuid4()),
        ("groups", []),
        ("websites", []),
        ("integration_knowledge_ids", []),
        ("mcp_server_ids", []),
    ],
)
def test_flow_assistant_update_command_reports_each_security_field(
    field_name: FlowAssistantUpdateField,
    field_value: object,
) -> None:
    update = FlowAssistantUpdateCommand.model_validate({field_name: field_value})

    assert update.changed_security_field_names() == frozenset({field_name})


def test_flow_assistant_update_mapper_preserves_current_data_retention_behavior() -> (
    None
):
    update = to_flow_assistant_update_command(AssistantUpdatePublic(name="Assistant"))

    assert update.name == "Assistant"
    assert update.data_retention_days is None
    assert update.is_set("data_retention_days")
    assert update.description is NOT_PROVIDED
    assert not update.is_set("description")


def test_flow_assistant_update_mapper_preserves_explicit_clear_values() -> None:
    update = to_flow_assistant_update_command(
        AssistantUpdatePublic(
            description=None,
            metadata_json=None,
            icon_id=None,
            groups=None,
        )
    )

    assert update.description is None
    assert update.metadata_json is None
    assert update.icon_id is None
    assert update.groups == []
    assert update.is_set("description")
    assert update.is_set("metadata_json")
    assert update.is_set("icon_id")
    assert update.is_set("groups")


def test_flow_assistant_update_mapper_converts_nested_ids_and_mcp_tools() -> None:
    attachment_id = uuid4()
    website_id = uuid4()
    group_id = uuid4()
    integration_knowledge_id = uuid4()
    mcp_server_id = uuid4()
    mcp_tool_id = uuid4()
    completion_model_id = uuid4()

    update = to_flow_assistant_update_command(
        AssistantUpdatePublic(
            name="Assistant",
            attachments=[{"id": attachment_id}],
            websites=[{"id": website_id}],
            groups=[{"id": group_id}],
            integration_knowledge_list=[{"id": integration_knowledge_id}],
            mcp_servers=[{"id": mcp_server_id}],
            mcp_tools=[{"tool_id": mcp_tool_id, "is_enabled": True}],
            completion_model={"id": completion_model_id},
        )
    )

    assert update.attachment_ids == [attachment_id]
    assert update.websites == [website_id]
    assert update.groups == [group_id]
    assert update.integration_knowledge_ids == [integration_knowledge_id]
    assert update.mcp_server_ids == [mcp_server_id]
    assert update.mcp_tools == [(mcp_tool_id, True)]
    assert update.completion_model_id == completion_model_id

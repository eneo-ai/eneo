from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

from eneo.flows.ai_builder.ai_builder_context import (
    serialize_space_kbs,
    serialize_space_mcps,
    serialize_space_models,
)


def test_serialize_space_models_keeps_local_id_for_catalog_input() -> None:
    model_id = uuid4()
    space = SimpleNamespace(
        completion_models=[
            SimpleNamespace(id=model_id, name="gpt-5.4-nano", provider_type="openai")
        ]
    )

    assert serialize_space_models(space) == [
        {
            "id": str(model_id),
            "ref": str(model_id),
            "name": "gpt-5.4-nano",
            "display_name": "gpt-5.4-nano",
            "provider": "openai",
        }
    ]


def test_serialize_space_kbs_keeps_local_id_for_catalog_input() -> None:
    kb_id = uuid4()
    space = SimpleNamespace(
        collections=[
            SimpleNamespace(
                id=kb_id,
                name="Policy",
                description="Local policy reference material.",
            )
        ]
    )

    assert serialize_space_kbs(space) == [
        {
            "id": str(kb_id),
            "ref": str(kb_id),
            "name": "Policy",
            "display_name": "Policy",
            "description": "Local policy reference material.",
        }
    ]


def test_serialize_space_mcps_exposes_only_enabled_tools() -> None:
    server_id = uuid4()
    enabled_tool_id = uuid4()
    disabled_tool_id = uuid4()
    space = SimpleNamespace(
        mcp_servers=[
            SimpleNamespace(
                id=server_id,
                name="Ärendesystem",
                description="Hämtar levande ärendedata.",
                tools=[
                    SimpleNamespace(
                        id=enabled_tool_id,
                        name="lookup_case",
                        description="Fetch one case by id.",
                        input_schema={"type": "object"},
                        is_enabled_by_default=True,
                    ),
                    SimpleNamespace(
                        id=disabled_tool_id,
                        name="delete_case",
                        description="Delete one case.",
                        input_schema={"type": "object"},
                        is_enabled_by_default=False,
                    ),
                ],
            )
        ],
    )

    result = serialize_space_mcps(space)

    assert result == [
        {
            "id": str(server_id),
            "ref": str(server_id),
            "name": "Ärendesystem",
            "display_name": "Ärendesystem",
            "description": "Hämtar levande ärendedata.",
            "tools": [
                {
                    "id": str(enabled_tool_id),
                    "ref": str(enabled_tool_id),
                    "name": "lookup_case",
                    "display_name": "lookup_case",
                    "description": "Fetch one case by id.",
                }
            ],
        }
    ]


def test_serialize_space_mcps_hides_servers_without_enabled_tools() -> None:
    space = SimpleNamespace(
        mcp_servers=[
            SimpleNamespace(
                id=uuid4(),
                name="Empty server",
                description="No enabled tools.",
                tools=[
                    SimpleNamespace(
                        id=uuid4(),
                        name="disabled_tool",
                        description="Disabled.",
                        is_enabled_by_default=False,
                    )
                ],
            )
        ],
    )

    assert serialize_space_mcps(space) == []

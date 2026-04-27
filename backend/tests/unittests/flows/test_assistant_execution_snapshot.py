from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

from intric.flows.assistant_execution_snapshot import (
    build_assistant_execution_snapshot,
)


def _assistant(
    *,
    prompt: str = "Answer carefully.",
    model_name: str = "gpt-5.4-nano",
    knowledge_name: str | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        origin="flow_managed",
        prompt=SimpleNamespace(text=prompt),
        completion_model=SimpleNamespace(
            id=uuid4(),
            name=model_name,
            nickname="Nano",
            litellm_model_name="openai/gpt-5.4-nano",
        ),
        completion_model_kwargs={"temperature": 0.2},
        collections=[]
        if knowledge_name is None
        else [
            SimpleNamespace(
                id="collection-1",
                name=knowledge_name,
            )
        ],
        websites=[],
        integration_knowledge_list=[],
    )


def _mcp_server(*, schema_type: str = "string") -> SimpleNamespace:
    return SimpleNamespace(
        id="server-1",
        name="Weather",
        tools=[
            SimpleNamespace(
                id="tool-1",
                name="forecast",
                description="Fetches a forecast.",
                input_schema={
                    "type": "object",
                    "properties": {"city": {"type": schema_type}},
                },
                is_enabled=True,
            )
        ],
    )


def _execution_hash(assistant: SimpleNamespace, mcp_servers: list[SimpleNamespace]):
    snapshot = build_assistant_execution_snapshot(
        assistant=assistant,
        mcp_server_entities=mcp_servers,
    )
    assert snapshot is not None
    return snapshot["execution_surface_hash"]


def test_assistant_execution_hash_changes_when_prompt_changes():
    first = _assistant(prompt="Summarize the case.")
    second = _assistant(prompt="Summarize the case and cite uncertainties.")
    second.id = first.id
    second.completion_model.id = first.completion_model.id

    assert _execution_hash(first, []) != _execution_hash(second, [])


def test_assistant_execution_hash_ignores_model_and_knowledge_display_names():
    first = _assistant(model_name="GPT Nano", knowledge_name="Old label")
    second = _assistant(model_name="GPT Nano renamed", knowledge_name="New label")
    second.id = first.id
    second.completion_model.id = first.completion_model.id

    assert _execution_hash(first, []) == _execution_hash(second, [])


def test_assistant_execution_hash_ignores_none_model_kwargs():
    first = _assistant()
    second = _assistant()
    second.id = first.id
    second.completion_model.id = first.completion_model.id
    first.completion_model_kwargs = {"temperature": 0.2, "top_p": None}
    second.completion_model_kwargs = {"temperature": 0.2}

    assert _execution_hash(first, []) == _execution_hash(second, [])


def test_assistant_execution_hash_changes_when_mcp_tool_schema_changes():
    assistant = _assistant()

    assert _execution_hash(assistant, [_mcp_server(schema_type="string")]) != (
        _execution_hash(assistant, [_mcp_server(schema_type="number")])
    )


def test_assistant_snapshot_omits_mcp_tools_when_knowledge_suppresses_mcp():
    snapshot = build_assistant_execution_snapshot(
        assistant=_assistant(knowledge_name="Policy handbook"),
        mcp_server_entities=[_mcp_server()],
    )

    assert snapshot is not None
    assert snapshot["knowledge_refs"] != []
    assert snapshot["mcp_servers"] != []
    assert snapshot["mcp_tools"] == []

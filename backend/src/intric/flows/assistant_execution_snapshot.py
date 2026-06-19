from __future__ import annotations

import hashlib
import json
from typing import Any, cast

from intric.flows.domain.flow import FlowPersistedJsonObject

ASSISTANT_SNAPSHOT_SCHEMA_VERSION = 1


def build_assistant_execution_snapshot(
    *, assistant: Any | None, mcp_server_entities: list[Any]
) -> FlowPersistedJsonObject | None:
    """Capture the assistant execution surface used by published flow versions."""
    if assistant is None:
        return None
    assistant_id = getattr(assistant, "id", None)
    if assistant_id is None:
        return None

    knowledge_refs = _assistant_knowledge_snapshot(assistant)
    # Assistant execution suppresses MCP tools when knowledge retrieval is enabled.
    # The snapshot should mirror the effective LLM surface, not just configuration.
    mcp_tool_surface = (
        [] if knowledge_refs else _mcp_tool_surface_snapshot(mcp_server_entities)
    )
    snapshot: FlowPersistedJsonObject = {
        "schema_version": ASSISTANT_SNAPSHOT_SCHEMA_VERSION,
        "assistant_id": str(assistant_id),
        "origin": _enum_value(getattr(assistant, "origin", None)),
        "instructions": _assistant_instructions(assistant),
        "completion_model": _completion_model_snapshot(
            getattr(assistant, "completion_model", None)
        ),
        "completion_model_kwargs": _model_kwargs_snapshot(
            getattr(assistant, "completion_model_kwargs", None)
        ),
        "knowledge_refs": knowledge_refs,
        "mcp_servers": [
            {"id": str(server.id), "name": server.name}
            for server in mcp_server_entities
        ],
        "mcp_tools": mcp_tool_surface,
        "tool_surface_hash": stable_hash(mcp_tool_surface),
    }
    snapshot["execution_surface_hash"] = stable_hash(
        _execution_surface_from_snapshot(snapshot)
    )
    return snapshot


def assistant_execution_surface_hash(snapshot: dict[str, Any]) -> str:
    return stable_hash(_execution_surface_from_snapshot(snapshot))


def stable_hash(value: Any) -> str:
    serialized = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _execution_surface_from_snapshot(
    snapshot: dict[str, Any],
) -> FlowPersistedJsonObject:
    """Return only fields that affect execution semantics.

    Display labels are intentionally excluded unless they are part of the LLM
    tool surface. This keeps harmless UI renames from invalidating published
    versions while still catching prompt/model/knowledge/MCP behavior drift.
    """
    raw_completion_model = snapshot.get("completion_model")
    completion_model = (
        cast(dict[str, Any], raw_completion_model)
        if isinstance(raw_completion_model, dict)
        else None
    )
    return {
        "schema_version": snapshot.get("schema_version"),
        "assistant_id": snapshot.get("assistant_id"),
        "instructions": snapshot.get("instructions"),
        "completion_model": _completion_model_execution_surface(completion_model),
        "completion_model_kwargs": snapshot.get("completion_model_kwargs") or {},
        "knowledge_refs": _knowledge_execution_surface(snapshot.get("knowledge_refs")),
        "mcp_tools": _mcp_tool_execution_surface(snapshot.get("mcp_tools")),
    }


def _assistant_instructions(assistant: Any) -> str | None:
    get_prompt_text = getattr(assistant, "get_prompt_text", None)
    if callable(get_prompt_text):
        text = get_prompt_text()
        return text if isinstance(text, str) else None

    prompt = getattr(assistant, "prompt", None)
    text = getattr(prompt, "text", None)
    return text if isinstance(text, str) else None


def _completion_model_snapshot(model: Any | None) -> FlowPersistedJsonObject | None:
    if model is None:
        return None
    return {
        "id": str(getattr(model, "id")) if getattr(model, "id", None) else None,
        "name": getattr(model, "name", None),
        "nickname": getattr(model, "nickname", None),
        "litellm_model_name": getattr(model, "litellm_model_name", None),
    }


def _completion_model_execution_surface(
    model: dict[str, Any] | None,
) -> FlowPersistedJsonObject | None:
    if model is None:
        return None
    return {
        "id": model.get("id"),
        "litellm_model_name": model.get("litellm_model_name"),
    }


def _model_kwargs_snapshot(model_kwargs: Any | None) -> FlowPersistedJsonObject:
    if model_kwargs is None:
        return {}
    if hasattr(model_kwargs, "model_dump"):
        return cast(
            FlowPersistedJsonObject,
            model_kwargs.model_dump(mode="json", exclude_none=True),
        )
    if isinstance(model_kwargs, dict):
        raw_kwargs = cast(dict[object, object], model_kwargs)
        return {
            str(key): value for key, value in raw_kwargs.items() if value is not None
        }
    return {}


def _assistant_knowledge_snapshot(assistant: Any) -> list[FlowPersistedJsonObject]:
    refs: list[FlowPersistedJsonObject] = []
    for attr, kind in (
        ("collections", "collection"),
        ("websites", "website"),
        ("integration_knowledge_list", "integration_knowledge"),
    ):
        for resource in getattr(assistant, attr, []) or []:
            refs.append(
                {
                    "kind": kind,
                    "id": str(getattr(resource, "id")),
                    "name": getattr(resource, "name", None),
                }
            )
    return refs


def _knowledge_execution_surface(value: Any) -> list[FlowPersistedJsonObject]:
    refs = cast(list[Any], value) if isinstance(value, list) else []
    normalized: list[FlowPersistedJsonObject] = []
    for item in refs:
        if not isinstance(item, dict):
            continue
        item_dict = cast(dict[str, Any], item)
        normalized.append(
            {
                "kind": item_dict.get("kind"),
                "id": item_dict.get("id"),
            }
        )
    return sorted(normalized, key=lambda item: (str(item["kind"]), str(item["id"])))


def _mcp_tool_surface_snapshot(mcp_servers: list[Any]) -> list[FlowPersistedJsonObject]:
    tools: list[FlowPersistedJsonObject] = []
    for server in mcp_servers:
        for tool in cast(list[Any], getattr(server, "tools", []) or []):
            if cast(bool, getattr(tool, "is_enabled", False)) is not True:
                continue
            input_schema = getattr(tool, "input_schema", None)
            tools.append(
                {
                    "tool_id": str(tool.id),
                    "server_id": str(server.id),
                    "server_name": server.name,
                    "name": tool.name,
                    "description": getattr(tool, "description", None),
                    "input_schema": input_schema
                    if isinstance(input_schema, dict)
                    else None,
                    "input_schema_hash": stable_hash(input_schema),
                }
            )
    return tools


def _mcp_tool_execution_surface(value: Any) -> list[FlowPersistedJsonObject]:
    tools = cast(list[Any], value) if isinstance(value, list) else []
    normalized: list[FlowPersistedJsonObject] = []
    for item in tools:
        if not isinstance(item, dict):
            continue
        item_dict = cast(dict[str, Any], item)
        normalized.append(
            {
                "tool_id": item_dict.get("tool_id"),
                "server_id": item_dict.get("server_id"),
                "server_name": item_dict.get("server_name"),
                "name": item_dict.get("name"),
                "description": item_dict.get("description"),
                "input_schema_hash": item_dict.get("input_schema_hash"),
            }
        )
    return sorted(
        normalized,
        key=lambda item: (str(item["server_id"]), str(item["tool_id"])),
    )


def _enum_value(value: Any) -> str | None:
    enum_value = getattr(value, "value", None)
    if isinstance(enum_value, str):
        return enum_value
    return value if isinstance(value, str) else None

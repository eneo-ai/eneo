from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any, TypedDict, cast


class AIBuilderMCPToolResource(TypedDict):
    id: str
    ref: str
    name: str
    display_name: str
    description: str


class AIBuilderMCPServerResource(TypedDict):
    id: str
    ref: str
    name: str
    display_name: str
    description: str
    tools: list[AIBuilderMCPToolResource]


AIBuilderMCPResourceInput = (
    Iterable[AIBuilderMCPServerResource | Mapping[str, Any]] | None
)


def normalize_ai_builder_mcp_resources(
    mcp_servers: AIBuilderMCPResourceInput,
) -> list[AIBuilderMCPServerResource]:
    """Return the MCP resource shape that AI Builder exposes to the planner.

    The planner, schema builders, and resource catalog all consume this shape.
    Invalid refs are skipped here so malformed resource data cannot leak into
    prompts or tool schemas as blank enum values.
    """
    if mcp_servers is None:
        return []

    normalized: list[AIBuilderMCPServerResource] = []
    seen_server_refs: set[str] = set()
    seen_tool_refs: set[str] = set()

    for server in mcp_servers:
        server_ref = _resource_ref(server)
        if not server_ref or server_ref in seen_server_refs:
            continue

        tools = server.get("tools")
        if not isinstance(tools, list):
            continue

        normalized_tools: list[AIBuilderMCPToolResource] = []
        for tool_obj in cast(list[object], tools):
            if not isinstance(tool_obj, Mapping):
                continue
            tool = cast(Mapping[str, Any], tool_obj)
            tool_ref = _resource_ref(tool)
            if not tool_ref or tool_ref in seen_tool_refs:
                continue
            seen_tool_refs.add(tool_ref)
            normalized_tools.append(
                {
                    "id": _resource_id(tool, tool_ref),
                    "ref": tool_ref,
                    "name": _resource_name(tool, tool_ref),
                    "display_name": _resource_display_name(tool, tool_ref),
                    "description": _resource_description(tool),
                }
            )

        if not normalized_tools:
            continue

        seen_server_refs.add(server_ref)
        normalized.append(
            {
                "id": _resource_id(server, server_ref),
                "ref": server_ref,
                "name": _resource_name(server, server_ref),
                "display_name": _resource_display_name(server, server_ref),
                "description": _resource_description(server),
                "tools": normalized_tools,
            }
        )

    return normalized


def _resource_ref(resource: Mapping[str, Any]) -> str:
    return _clean_string(resource.get("ref") or resource.get("id"))


def _resource_id(resource: Mapping[str, Any], fallback: str) -> str:
    return _clean_string(resource.get("id")) or fallback


def _resource_name(resource: Mapping[str, Any], fallback: str) -> str:
    return _clean_string(resource.get("name")) or fallback


def _resource_display_name(resource: Mapping[str, Any], fallback: str) -> str:
    return (
        _clean_string(resource.get("display_name"))
        or _clean_string(resource.get("name"))
        or fallback
    )


def _resource_description(resource: Mapping[str, Any]) -> str:
    return _clean_string(resource.get("description"))


def _clean_string(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()

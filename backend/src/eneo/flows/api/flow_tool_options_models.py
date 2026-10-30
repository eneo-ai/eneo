from __future__ import annotations

from typing import Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from pydantic.config import JsonDict

from eneo.flows.application.flow_tool_options import FlowToolOptions
from eneo.mcp_servers.domain.unattended_tool_refusal import UnattendedToolRefusal

_SERVER_ID = "00000000-0000-0000-0000-000000000201"
_TOOL_ID = "00000000-0000-0000-0000-000000000301"

FLOW_TOOL_OPTIONS_EXAMPLE: JsonDict = {
    "security_classifications_enabled": True,
    "items": [
        {
            "mcp_server_id": _SERVER_ID,
            "mcp_server_name": "Case register",
            "mcp_server_security_level": 20,
            "tool_id": _TOOL_ID,
            "tool_name": "lookup_case",
            "tool_description": "Fetch one case by its number.",
            "input_schema": {
                "type": "object",
                "properties": {"case_id": {"type": "string"}},
            },
            "refusal": None,
        },
        {
            "mcp_server_id": _SERVER_ID,
            "mcp_server_name": "Case register",
            "mcp_server_security_level": 20,
            "tool_id": "00000000-0000-0000-0000-000000000302",
            "tool_name": "close_case",
            "tool_description": None,
            "input_schema": None,
            "refusal": UnattendedToolRefusal.TOOL_WAITING_FOR_REVIEW.value,
        },
    ],
}


class FlowToolOptionPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    mcp_server_id: UUID = Field(description="The MCP server that offers the tool.")
    mcp_server_name: str = Field(description="The server's name.")
    mcp_server_security_level: int | None = Field(
        description=(
            "The level of the server's security classification, the one the "
            "classification rule compares: the server must have at least the "
            "space's level (`refusal` is `server_below_space_classification` "
            "otherwise), and a step may send it values from earlier steps only "
            "at or below this level (saving refuses the step otherwise with "
            "`flow_step_tool_arguments_classification_write_down`). Null when the "
            "server has no classification, and always null while "
            "`security_classifications_enabled` is false."
        )
    )
    tool_id: UUID = Field(
        description="The tool, to put in a step's tool configuration."
    )
    tool_name: str = Field(description="The tool's name at its server.")
    tool_description: str | None = Field(
        description=(
            "The tool's description as an administrator last approved it; null "
            "when the server gave none or the tool has not been approved yet."
        )
    )
    input_schema: dict[str, object] | None = Field(
        description=(
            "The tool's input schema as an administrator last approved it, the "
            "one a flow checks a step's arguments against; null when the tool "
            "declares none or has not been approved yet. A change the server "
            "made and nobody has approved is not shown."
        )
    )
    refusal: UnattendedToolRefusal | None = Field(
        description=(
            "Null when no level of the MCP decision refuses the tool now; "
            "publish also checks the approved schema and the step's security "
            "classification, and a run asks the decision again. Otherwise the "
            "level that refuses it, the same value a run's `tool_refusal` "
            "carries."
        )
    )


class FlowToolOptionsPublic(BaseModel):
    model_config = ConfigDict(json_schema_extra={"example": FLOW_TOOL_OPTIONS_EXAMPLE})

    security_classifications_enabled: bool = Field(
        description=(
            "Whether the organization has security classifications turned on, "
            "the switch the classification rule reads. While it is on, a null "
            "`mcp_server_security_level` means the server has no classification: "
            "such a server is refused in a space that has one and cannot receive "
            "values from steps whose result has one."
        )
    )
    items: list[FlowToolOptionPublic] = Field(
        description=(
            "The tools of the MCP servers the flow's space has activated, in the "
            "order the reader returns them: server name, then tool name. A "
            "personal space has no MCP servers, so its list is empty. The tools "
            "of a server that is not a general one (a capability provider or "
            "one of Eneo's own servers) are left out."
        )
    )

    @classmethod
    def from_options(cls, listed: FlowToolOptions) -> Self:
        return cls(
            security_classifications_enabled=listed.security_classifications_enabled,
            items=[
                FlowToolOptionPublic.model_validate(option) for option in listed.options
            ],
        )

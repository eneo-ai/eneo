"""Explicit references in instruction text; these URIs are never fetched."""

import re
from bisect import bisect_right
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Annotated, Literal
from urllib.parse import quote, unquote
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from eneo.main.exceptions import BadRequestException
from eneo.mcp_servers.domain.capabilities import CapabilityPurpose
from eneo.mcp_servers.domain.model_tool_identity import ModelToolIdentity


class _ReferenceTarget(BaseModel, frozen=True):
    model_config = ConfigDict(frozen=True, extra="forbid")


class SkillInstructionReference(_ReferenceTarget, frozen=True):
    kind: Literal["skill"] = "skill"
    skill_id: UUID
    revision_id: UUID


class FunctionInstructionReference(_ReferenceTarget, frozen=True):
    kind: Literal["function"] = "function"
    purpose: CapabilityPurpose


class McpServerInstructionReference(_ReferenceTarget, frozen=True):
    kind: Literal["mcp_server"] = "mcp_server"
    server_id: UUID


class McpToolInstructionReference(_ReferenceTarget, frozen=True):
    kind: Literal["mcp_tool"] = "mcp_tool"
    server_id: UUID
    tool_name: str = Field(min_length=1)


InstructionTarget = Annotated[
    SkillInstructionReference
    | FunctionInstructionReference
    | McpServerInstructionReference
    | McpToolInstructionReference,
    Field(discriminator="kind"),
]


@dataclass(frozen=True)
class InstructionReference:
    start: int
    end: int
    text: str
    label: str
    target: InstructionTarget


_LINK = re.compile(
    r"\[((?:\\[^\n]|[^\[\]\\\n])*)\]"
    r"\((eneo-(?:skill|function|mcp|tool):[^)\n]*)\)"
)
_FENCE = re.compile(
    r"[ \t]*(?:>[ \t]*)*(?:(?:[-+*]|\d+[.)])[ \t]+)?"
    r"(?P<delimiter>`{3,}|~{3,})(?P<rest>[^\n]*)"
)
_ESCAPED_PUNCTUATION = re.compile(r"\\([!\"#$%&'()*+,\-./:;<=>?@\[\]\\^_`{|}~])")
_BAD_PERCENT = re.compile(r"%(?![0-9a-fA-F]{2})")
_UUID = re.compile(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}")


def _uuid(value: str) -> UUID:
    if not _UUID.fullmatch(value):
        raise ValueError("Reference IDs must be hyphenated UUIDs")
    return UUID(value)


def _target(uri: str) -> InstructionTarget:
    scheme, value = uri.split(":", 1)
    try:
        if scheme == "eneo-skill":
            skill_id, revision_id = value.split("@")
            return SkillInstructionReference(
                skill_id=_uuid(skill_id), revision_id=_uuid(revision_id)
            )
        if scheme == "eneo-function":
            return FunctionInstructionReference.model_validate({"purpose": value})
        if scheme == "eneo-mcp":
            return McpServerInstructionReference(server_id=_uuid(value))
        server_id, encoded_name = value.split("/", 1)
        if _BAD_PERCENT.search(encoded_name):
            raise ValueError("Invalid percent encoding")
        name = unquote(encoded_name, errors="strict")
        if (
            any(ord(char) < 32 or ord(char) == 127 for char in name)
            or quote(name, safe="").lower() != encoded_name.lower()
        ):
            raise ValueError("Tool names must be encoded URI segments")
        return McpToolInstructionReference(server_id=_uuid(server_id), tool_name=name)
    except (ValueError, ValidationError) as error:
        raise BadRequestException("Invalid Skill instruction reference") from error


def parse_instruction_references(text: str) -> tuple[InstructionReference, ...]:
    """Read only explicit inline links outside escapes and code examples.

    This is a text codec, not a Markdown renderer. All characters and offsets
    outside the named links remain untouched, including whitespace and Unicode.
    """
    references: list[InstructionReference] = []
    fence: str | None = None
    # Index delimiters once: repeated unmatched code markers must not rescan
    # the remaining instruction text on every iteration.
    code_runs: dict[int, int] = {}
    code_ends: dict[int, list[int]] = {}
    for run in re.finditer(r"`+", text):
        length = run.end() - run.start()
        code_runs[run.start()] = run.end()
        code_ends.setdefault(length, []).append(run.end())
    cursor: int = 0
    while cursor < len(text):
        if cursor == 0 or text[cursor - 1] == "\n":
            end = text.find("\n", cursor)
            end = len(text) if end < 0 else end + 1
            line = text[cursor:end]
            marker = _FENCE.match(line)
            if fence is not None:
                if (
                    marker
                    and marker["delimiter"][0] == fence[0]
                    and len(marker["delimiter"]) >= len(fence)
                    and not marker["rest"].strip()
                ):
                    fence = None
                cursor = end
                continue
            if marker:
                fence = marker["delimiter"]
                cursor = end
                continue
            if line.startswith(("    ", "\t")):
                cursor = end
                continue
        if text.startswith("<!--", cursor):
            comment_end = text.find("-->", cursor + 4)
            cursor = len(text) if comment_end < 0 else comment_end + 3
            continue
        if text[cursor] == "\\":
            cursor += 2
            continue
        if text[cursor] == "`":
            run_end: int = code_runs.get(cursor, cursor + 1)
            while run_end < len(text) and text[run_end] == "`":
                run_end += 1
            endings = code_ends.get(run_end - cursor, [])
            next_run = bisect_right(endings, run_end)
            cursor = endings[next_run] if next_run < len(endings) else run_end
            continue
        match = _LINK.match(text, cursor) if text[cursor] == "[" else None
        if match:
            if cursor == 0 or text[cursor - 1] != "!":
                label = _ESCAPED_PUNCTUATION.sub(r"\1", match[1])
                if not label.strip():
                    raise BadRequestException(
                        "Invalid Skill instruction reference label"
                    )
                references.append(
                    InstructionReference(
                        start=cursor,
                        end=match.end(),
                        text=match[0],
                        label=label,
                        target=_target(match[2]),
                    )
                )
            cursor = match.end()
        else:
            cursor += 1
    return tuple(references)


def reference_identity(
    target: InstructionTarget, skill_identities: Mapping[UUID, str]
) -> str:
    if isinstance(target, SkillInstructionReference):
        identity = skill_identities.get(target.revision_id)
        if identity is None:
            raise BadRequestException(
                "Referenced Skill revision is missing from the activation group"
            )
        return identity
    if isinstance(target, FunctionInstructionReference):
        return f"Function {target.purpose}"
    if isinstance(target, McpToolInstructionReference):
        return f"MCP {target.server_id}, tool {target.tool_name}"
    return f"MCP {target.server_id}"


def target_matches_tool(target: InstructionTarget, tool: ModelToolIdentity) -> bool:
    if isinstance(target, FunctionInstructionReference):
        return target.purpose == tool.purpose
    if isinstance(target, (McpServerInstructionReference, McpToolInstructionReference)):
        return (
            tool.purpose == "general"
            and target.server_id == tool.server_id
            and (
                not isinstance(target, McpToolInstructionReference)
                or target.tool_name == tool.tool_name
            )
        )
    return False


def render_instruction_references(
    text: str,
    *,
    skill_identities: Mapping[UUID, str],
    available_targets: frozenset[InstructionTarget] = frozenset(),
) -> str:
    parts: list[str] = []
    cursor = 0
    for reference in parse_instruction_references(text):
        availability = ""
        if not isinstance(reference.target, SkillInstructionReference):
            availability = (
                "; available"
                if reference.target in available_targets
                else "; unavailable for this turn"
            )
        parts.extend(
            (
                text[cursor : reference.start],
                f"[{reference.label}] ({reference_identity(reference.target, skill_identities)}{availability})",
            )
        )
        cursor = reference.end
    parts.append(text[cursor:])
    return "".join(parts)

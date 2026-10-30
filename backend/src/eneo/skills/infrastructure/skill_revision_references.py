"""Approve and freeze instruction references within the revision writer's transaction.

Runtime reads this stored closure; it never re-approves or follows current versions.
"""

from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError

from eneo.database.database import AsyncSession
from eneo.database.tables.mcp_server_table import MCPServers, MCPServerTools
from eneo.database.tables.skill_table import (
    SkillRevisionDependencies,
    SkillRevisions,
    Skills,
)
from eneo.database.tables.spaces_table import Spaces
from eneo.main.exceptions import BadRequestException, SkillRevisionConflictException
from eneo.skills.domain.instruction_references import (
    McpServerInstructionReference,
    McpToolInstructionReference,
    SkillInstructionReference,
    parse_instruction_references,
)
from eneo.skills.domain.skill import (
    MAX_SKILL_ATTACHMENT_LIMIT,
    Skill,
    SkillBindingReference,
)
from eneo.skills.infrastructure.skill_db_errors import is_lock_not_available


def _check_group_size(helper_count: int) -> None:
    if helper_count + 1 > MAX_SKILL_ATTACHMENT_LIMIT:
        raise BadRequestException(
            f"A Skill and its referenced Skills cannot exceed {MAX_SKILL_ATTACHMENT_LIMIT} unique Skills"
        )


async def approve_revision_references(
    session: AsyncSession,
    *,
    space_id: UUID,
    skill_id: UUID,
    instructions: str,
    retained_instructions: str = "",
    retained_revision_id: UUID | None = None,
) -> list[SkillBindingReference]:
    parsed = parse_instruction_references(instructions)
    retained_targets = {
        reference.target
        for reference in parse_instruction_references(retained_instructions)
    }
    tool_targets = {
        reference.target
        for reference in parsed
        if isinstance(
            reference.target,
            (McpServerInstructionReference, McpToolInstructionReference),
        )
        and reference.target not in retained_targets
    }
    if tool_targets:
        server_ids = {target.server_id for target in tool_targets}
        available_servers = set(
            await session.scalars(
                sa.select(MCPServers.id).where(
                    MCPServers.id.in_(server_ids),
                    MCPServers.tenant_id
                    == sa.select(Spaces.tenant_id)
                    .where(Spaces.id == space_id)
                    .scalar_subquery(),
                    MCPServers.purpose == "general",
                )
            )
        )
        if available_servers != server_ids:
            raise BadRequestException(
                "A referenced MCP is unavailable in this organisation. Use a Function reference for a built-in function."
            )
        specific = {
            target
            for target in tool_targets
            if isinstance(target, McpToolInstructionReference)
        }
        if specific:
            known = await session.execute(
                sa.select(MCPServerTools.mcp_server_id, MCPServerTools.name).where(
                    sa.tuple_(MCPServerTools.mcp_server_id, MCPServerTools.name).in_(
                        [(target.server_id, target.tool_name) for target in specific]
                    ),
                    MCPServerTools.removed_from_remote.is_(False),
                    sa.or_(
                        MCPServerTools.requires_approval.is_(False),
                        MCPServerTools.description.is_not(None),
                        MCPServerTools.input_schema.is_not(None),
                    ),
                )
            )
            known_pairs = set(known.tuples())
            if any(
                (target.server_id, target.tool_name) not in known_pairs
                for target in specific
            ):
                raise BadRequestException(
                    "A referenced MCP tool is unavailable or awaits approval"
                )
    direct = {
        reference.target
        for reference in parsed
        if isinstance(reference.target, SkillInstructionReference)
    }
    if not direct:
        return []
    # Count unique Skills, not mentions. A saved group must fit the existing
    # platform ceiling, including its root. The active policy is checked when
    # attaching or running it, so changing policy does not invalidate a draft.
    _check_group_size(len(direct))
    retained = {
        reference.target
        for reference in parse_instruction_references(retained_instructions)
        if isinstance(reference.target, SkillInstructionReference)
    }
    if retained:
        approved = await session.execute(
            sa.select(
                SkillRevisionDependencies.target_skill_id,
                SkillRevisionDependencies.target_revision_id,
            ).where(
                SkillRevisionDependencies.source_revision_id == retained_revision_id,
                SkillRevisionDependencies.source_skill_id == skill_id,
            )
        )
        retained.intersection_update(
            SkillInstructionReference(skill_id=target, revision_id=revision)
            for target, revision in approved.tuples()
        )
    # Each target revision already owns its approved closure. Freeze that
    # closure on this revision so runtime never walks a graph or follows latest.
    inherited = await session.execute(
        sa.select(
            SkillRevisionDependencies.target_skill_id,
            SkillRevisionDependencies.target_revision_id,
        )
        .where(
            SkillRevisionDependencies.source_revision_id.in_(
                [reference.revision_id for reference in direct]
            )
        )
        .distinct()
        .limit(MAX_SKILL_ATTACHMENT_LIMIT)
    )
    targets = {
        SkillBindingReference(reference.skill_id, reference.revision_id)
        for reference in direct
    } | {
        SkillBindingReference(target_skill_id, target_revision_id)
        for target_skill_id, target_revision_id in inherited.tuples()
    }
    ids = [reference.skill_id for reference in targets]
    if skill_id in ids:
        raise BadRequestException("Skill references cannot form a cycle")
    if len(ids) != len(set(ids)):
        raise BadRequestException("Skill references require conflicting revisions")
    _check_group_size(len(targets))

    # A revision writer already owns its source row. Do not wait for a
    # target writer that may itself be referencing this source (A <-> B).
    try:
        rows = await session.execute(
            sa.select(
                Skills,
                SkillRevisions.id,
                SkillRevisions.revision_number,
                sa.and_(Spaces.user_id.is_(None), Spaces.tenant_space_id.is_(None)),
            )
            .join(SkillRevisions, SkillRevisions.skill_id == Skills.id)
            .join(Spaces, Spaces.id == Skills.space_id)
            .where(
                Skills.space_id == space_id,
                sa.tuple_(Skills.id, SkillRevisions.id).in_(
                    [
                        (reference.skill_id, reference.skill_revision_id)
                        for reference in targets
                    ]
                ),
            )
            .order_by(Skills.id)
            .with_for_update(read=True, nowait=True, of=Skills)
        )
    except DBAPIError as error:
        if is_lock_not_available(error):
            raise SkillRevisionConflictException(
                "A referenced Skill is being changed. Keep your draft and try again."
            ) from error
        raise
    by_revision = {
        revision_id: (skill, number, organization)
        for skill, revision_id, number, organization in rows.tuples()
    }
    references = sorted(targets, key=lambda item: str(item.skill_id))
    if len(by_revision) != len(references):
        raise BadRequestException("A referenced Skill is not available in this Space")
    for reference in direct - retained:
        row, revision_number, is_organization = by_revision[reference.revision_id]
        if (
            row.removed_at is not None
            or not row.is_active
            or (is_organization and row.published_revision_number != revision_number)
        ):
            raise BadRequestException(
                "New references require an active Skill and, in the organisation, "
                "its published revision"
            )
    return references


async def store_revision_references(
    session: AsyncSession,
    skill: Skill,
    revision_id: UUID,
    dependencies: list[SkillBindingReference],
) -> None:
    if dependencies:
        await session.execute(
            sa.insert(SkillRevisionDependencies),
            [
                {
                    "space_id": skill.space_id,
                    "source_skill_id": skill.id,
                    "source_revision_id": revision_id,
                    "target_skill_id": dependency.skill_id,
                    "target_revision_id": dependency.skill_revision_id,
                }
                for dependency in dependencies
            ],
        )

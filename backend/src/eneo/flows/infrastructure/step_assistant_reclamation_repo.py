"""The reads and writes of step-assistant reclamation that are not the
flow's own rules (those stay in FlowRepository): the deployment-wide
candidate assistants, the references from outside flows that keep an assistant,
and the bounded detach of run history from an assistant about to go."""

from __future__ import annotations

from collections.abc import Collection, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapper, aliased

from eneo.assistants.assistant import AssistantOrigin
from eneo.database.tables.app_table import AppsPrompts
from eneo.database.tables.assistant_table import (
    AssistantIntegrationKnowledge,
    AssistantMCPServers,
    AssistantMCPServerTools,
    Assistants,
    AssistantsFiles,
    AssistantsGroups,
    AssistantsWebsites,
)
from eneo.database.tables.capabilities_table import AssistantCapabilities
from eneo.database.tables.flow_tables import Flows, FlowStepResults, FlowSteps
from eneo.database.tables.group_chats_table import GroupChatsAssistantsMapping
from eneo.database.tables.help_assistant_assignment_history_table import (
    HelpAssistantAssignmentHistory,
)
from eneo.database.tables.help_assistant_runs_table import HelpAssistantRuns
from eneo.database.tables.org_space_assistant_roles_table import (
    OrgSpaceAssistantRoles,
)
from eneo.database.tables.prompts_table import PromptsAssistants
from eneo.database.tables.questions_table import Questions
from eneo.database.tables.sessions_table import Sessions
from eneo.database.tables.skill_table import AssistantSkillBindings
from eneo.database.tables.workflow_tables import assistants_steps_guardrails_table

# Foreign keys to assistants whose rows are the assistant's own configuration:
# they go with it (ON DELETE CASCADE).
_OWN_CONFIGURATION: frozenset[tuple[str, frozenset[str]]] = frozenset(
    (table, frozenset(columns))
    for table, columns in (
        ("assistant_capabilities", ("assistant_id",)),
        ("assistant_integration_knowledge", ("assistant_id",)),
        ("assistant_mcp_servers", ("assistant_id",)),
        ("assistant_mcp_server_tools", ("assistant_id",)),
        ("assistants_files", ("assistant_id",)),
        ("assistants_groups", ("assistant_id",)),
        ("assistant_skill_bindings", ("assistant_id", "space_id")),
        ("assistants_websites", ("assistant_id",)),
        ("prompts_assistants", ("assistant_id",)),
    )
)
# Flow rows the reclamation itself decides about: draft steps (the step rule)
# and run history (detached first, read from the version snapshot after).
_FLOW_RULES: frozenset[tuple[str, frozenset[str]]] = frozenset(
    {
        (FlowSteps.__tablename__, frozenset({"assistant_id"})),
        (FlowStepResults.__tablename__, frozenset({"assistant_id"})),
    }
)


# A row in any of these keeps the assistant: it is something outside the flow
# that uses it (a chat, a group chat, a help-assistant role or its history, a
# legacy workflow guardrail).
def _column(model: type[object], name: str) -> sa.Column[Any]:
    mapper: Mapper[Any] = sa.inspect(model, raiseerr=True)
    return mapper.columns[name]


_KEEPING_COLUMNS: tuple[sa.Column[Any], ...] = (
    _column(Sessions, "assistant_id"),
    _column(Questions, "assistant_id"),
    _column(GroupChatsAssistantsMapping, "assistant_id"),
    _column(HelpAssistantAssignmentHistory, "assistant_id"),
    _column(HelpAssistantAssignmentHistory, "replaced_by_assistant_id"),
    _column(HelpAssistantRuns, "assistant_id"),
    _column(OrgSpaceAssistantRoles, "assistant_id"),
    assistants_steps_guardrails_table.c["assistant_id"],
)
_CONFIGURATION_COLUMNS: tuple[sa.Column[Any], ...] = tuple(
    _column(model, "assistant_id")
    for model in (
        AssistantCapabilities,
        AssistantIntegrationKnowledge,
        AssistantMCPServers,
        AssistantMCPServerTools,
        AssistantsFiles,
        AssistantsGroups,
        AssistantsWebsites,
        AssistantSkillBindings,
        PromptsAssistants,
    )
)
KNOWN_ASSISTANT_FOREIGN_KEYS: frozenset[tuple[str, frozenset[str]]] = (
    _OWN_CONFIGURATION
    | _FLOW_RULES
    | frozenset(
        (column.table.name, frozenset({column.name})) for column in _KEEPING_COLUMNS
    )
)

_ASSISTANT_FOREIGN_KEYS = sa.text(
    """
    SELECT referencing.relname AS table_name,
           array_agg(attribute.attname::text) AS column_names,
           referenced.relname AS referenced_table, fk.confdeltype::text
    FROM pg_constraint AS fk
    JOIN pg_class AS referencing ON referencing.oid = fk.conrelid
    JOIN pg_class AS referenced ON referenced.oid = fk.confrelid
    JOIN pg_attribute AS attribute
      ON attribute.attrelid = fk.conrelid AND attribute.attnum = ANY (fk.conkey)
    WHERE fk.contype = 'f' AND (
      fk.confrelid = 'assistants'::regclass
      OR referenced.relname::text = ANY(CAST(:configuration_tables AS text[]))
    )
    GROUP BY fk.oid, referencing.relname, referenced.relname, fk.confdeltype
    """
)


def _ids(assistant_ids: Collection[UUID]) -> sa.BindParameter[Sequence[UUID]]:
    return sa.bindparam(
        "assistant_ids",
        value=sorted(assistant_ids),
        type_=postgresql.ARRAY(postgresql.UUID(as_uuid=True)),
    )


@dataclass(frozen=True, slots=True)
class CandidateAssistant:
    id: UUID
    flow_id: UUID
    tenant_id: UUID
    created_at: datetime


class StepAssistantReclamationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def unknown_assistant_foreign_keys(self) -> frozenset[str]:
        """The foreign keys to assistants this module does not know, by
        table: any one keeps every assistant, since what it holds is unknown."""
        rows = await self.session.execute(
            _ASSISTANT_FOREIGN_KEYS,
            {"configuration_tables": sorted(table for table, _ in _OWN_CONFIGURATION)},
        )
        return frozenset(
            table
            for table, columns, referenced, action in rows.tuples()
            if referenced != Assistants.__tablename__
            or (table, frozenset(columns)) not in KNOWN_ASSISTANT_FOREIGN_KEYS
            or ((table, frozenset(columns)) in _OWN_CONFIGURATION and action != "c")
        )

    async def next_assistant(
        self, *, after: tuple[datetime, UUID] | None
    ) -> CandidateAssistant | None:
        """Select one assistant only when the collector can admit its row."""
        query = (
            sa.select(Assistants.id, Flows.id, Flows.tenant_id, Assistants.created_at)
            .join(Flows, Flows.id == Assistants.managing_flow_id)
            .where(Assistants.origin == AssistantOrigin.FLOW_MANAGED.value)
            .where(
                sa.or_(
                    Flows.deleted_at.is_not(None),
                    ~sa.exists().where(FlowSteps.assistant_id == Assistants.id),
                )
            )
            .order_by(Assistants.created_at, Assistants.id)
            .limit(1)
        )
        if after is not None:
            query = query.where(sa.tuple_(Assistants.created_at, Assistants.id) > after)
        row = (await self.session.execute(query)).one_or_none()
        return (
            CandidateAssistant(
                id=row[0], flow_id=row[1], tenant_id=row[2], created_at=row[3]
            )
            if row is not None
            else None
        )

    async def assistant_row(
        self, candidate: CandidateAssistant, *, created_within: timedelta
    ) -> sa.Row[tuple[datetime, UUID | None, bool]] | None:
        """FOR UPDATE freezes FK growth before reference checks and measurement."""
        query = (
            sa.select(
                Assistants.created_at,
                Assistants.icon_id,
                (Assistants.created_at > sa.func.now() - created_within).label(
                    "recent"
                ),
            )
            .where(Assistants.id == candidate.id)
            .where(Assistants.origin == AssistantOrigin.FLOW_MANAGED.value)
            .where(Assistants.managing_flow_id == candidate.flow_id)
            .with_for_update(skip_locked=True)
        )
        return (await self.session.execute(query)).one_or_none()

    async def configuration_rows(
        self, candidate: CandidateAssistant, *, retired: bool, limit: int
    ) -> int:
        """Bound both assistant configuration and a retired flow's draft steps.

        The extra row is a sentinel; no nested configuration FK is accepted.
        """
        query = sa.union_all(
            *(
                sa.select(sa.literal(1))
                .select_from(column.table)
                .where(column == candidate.id)
                for column in _CONFIGURATION_COLUMNS
            ),
            sa.select(sa.literal(1))
            .select_from(FlowSteps)
            .where(FlowSteps.flow_id == candidate.flow_id)
            .where(FlowSteps.tenant_id == candidate.tenant_id)
            .where(FlowSteps.assistant_id == candidate.id)
            .where(sa.literal(retired)),
        ).limit(limit)
        rows = list(await self.session.scalars(query))
        return len(rows)

    async def has_run_history(self, assistant_id: UUID) -> bool:
        return bool(
            await self.session.scalar(
                sa.select(
                    sa.exists().where(FlowStepResults.assistant_id == assistant_id)
                )
            )
        )

    async def externally_referenced(
        self, assistant_ids: Collection[UUID]
    ) -> frozenset[UUID]:
        """The assistants something outside the flow uses: a row of a keeping
        foreign key, or a prompt another assistant or an app also uses."""
        if not assistant_ids:
            return frozenset()
        ids = _ids(assistant_ids)
        other = aliased(PromptsAssistants)
        shared_prompt = (
            sa.select(PromptsAssistants.assistant_id)
            .where(PromptsAssistants.assistant_id == sa.any_(ids))
            .where(
                sa.or_(
                    sa.exists()
                    .where(other.prompt_id == PromptsAssistants.prompt_id)
                    .where(other.assistant_id != PromptsAssistants.assistant_id),
                    sa.exists().where(
                        AppsPrompts.prompt_id == PromptsAssistants.prompt_id
                    ),
                )
            )
        )
        referenced = sa.union(
            shared_prompt,
            *(
                sa.select(column).where(column == sa.any_(ids))
                for column in _KEEPING_COLUMNS
            ),
        )
        return frozenset(
            assistant_id
            for assistant_id in await self.session.scalars(
                sa.select(referenced.subquery().c[0])
            )
            if assistant_id is not None
        )

    async def detach_run_history(
        self, assistant_ids: Collection[UUID], *, limit: int
    ) -> tuple[int, bool]:
        """Clear the assistant id of at most ``limit`` step results that name
        one of ``assistant_ids``, skipping rows another transaction holds;
        return how many it cleared and whether any such result is left. The
        run's version snapshot still names the assistant."""
        if not assistant_ids:
            return 0, False
        ids = _ids(assistant_ids)
        left = sa.select(
            sa.exists().where(FlowStepResults.assistant_id == sa.any_(ids))
        )
        if limit <= 0:
            return 0, bool(await self.session.scalar(left))
        # Materialized, so the LIMIT and SKIP LOCKED selection runs once: as an
        # IN subquery the planner may run it again and clear more rows.
        batch = (
            sa.select(FlowStepResults.id)
            .where(FlowStepResults.assistant_id == sa.any_(ids))
            .order_by(FlowStepResults.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
            .cte("detach_batch")
            .prefix_with("MATERIALIZED")
        )
        result = await self.session.execute(
            sa.update(FlowStepResults)
            .where(FlowStepResults.id == batch.c.id)
            # History keeps its timestamps: evidence reads them.
            .values(assistant_id=None, updated_at=FlowStepResults.updated_at)
        )
        detached = int(getattr(result, "rowcount", 0) or 0)
        return detached, bool(await self.session.scalar(left))

    async def delete_retired_flow_steps(
        self, *, flow_id: UUID, tenant_id: UUID, assistant_ids: Collection[UUID]
    ) -> int:
        """Delete the draft steps of deleted flow ``flow_id`` that use one of
        ``assistant_ids``; a live flow's steps are never touched."""
        if not assistant_ids:
            return 0
        result = await self.session.execute(
            sa.delete(FlowSteps)
            .where(FlowSteps.flow_id == flow_id)
            .where(FlowSteps.tenant_id == tenant_id)
            .where(FlowSteps.assistant_id == sa.any_(_ids(assistant_ids)))
            .where(
                sa.exists()
                .where(Flows.id == FlowSteps.flow_id)
                .where(Flows.deleted_at.is_not(None))
            )
        )
        return int(getattr(result, "rowcount", 0) or 0)

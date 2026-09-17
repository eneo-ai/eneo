"""Clean current Flow step rows; historical published snapshots retain their data.

This operation does not erase historical credentials or rewrite version checksums.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal
from uuid import UUID, uuid4

from pydantic import ValidationError

from eneo.audit.domain.action_types import ActionType
from eneo.audit.domain.actor_types import ActorType
from eneo.audit.domain.audit_log import AuditLog
from eneo.audit.domain.entity_types import EntityType
from eneo.audit.domain.outcome import Outcome
from eneo.audit.domain.repositories.audit_log_repository import AuditLogRepository
from eneo.flows.domain.step_config import clean_inactive_step_config
from eneo.flows.flow_validators import (
    validate_steps,
    validate_variable_alias_collisions,
)
from eneo.flows.infrastructure.flow_repo import FlowRepository
from eneo.main.exceptions import BadRequestException, NotFoundException

RepairOutcome = Literal[
    "would_change", "unchanged", "repaired", "conflict", "invalid", "failed"
]


async def repair_flow_step_config(
    *,
    flow_repo: FlowRepository,
    audit_log_repo: AuditLogRepository,
    flow_id: UUID,
    tenant_id: UUID,
    apply: bool = False,
    operator_identity: str,
) -> RepairOutcome:
    session = flow_repo.session
    transaction = (
        session.begin_nested() if session.in_transaction() else session.begin()
    )
    try:
        async with transaction:
            try:
                flow = await flow_repo.get_step_config_repair_flow(
                    flow_id=flow_id, tenant_id=tenant_id
                )
            except ValidationError:
                return "invalid"
            steps = [clean_inactive_step_config(step) for step in flow.steps]
            if steps == flow.steps:
                return "unchanged"
            try:
                validate_steps(steps, metadata_json=flow.metadata_json)
                validate_variable_alias_collisions(
                    steps=steps, metadata_json=flow.metadata_json
                )
            except BadRequestException:
                return "invalid"
            if not apply:
                return "would_change"
            await flow_repo.repair_step_configs(flow=flow, steps=steps)
            await audit_log_repo.create(
                AuditLog(
                    id=uuid4(),
                    tenant_id=tenant_id,
                    actor_id=None,
                    actor_type=ActorType.SYSTEM,
                    actor_api_key_id=None,
                    action=ActionType.FLOW_UPDATED,
                    entity_type=EntityType.FLOW,
                    entity_id=flow_id,
                    timestamp=datetime.now(timezone.utc),
                    description="Current Flow step configuration cleaned by a system operator; published snapshots unchanged.",
                    metadata={
                        "operation": "current_step_config_cleanup",
                        "operator_identity": operator_identity,
                        "prior_draft_revision": flow.draft_revision,
                        "draft_revision": flow.draft_revision + 1,
                    },
                    outcome=Outcome.SUCCESS,
                )
            )
            return "repaired"
    except NotFoundException:
        return "conflict"
    except BadRequestException as exc:
        return "conflict" if exc.code == "stale_revision" else "failed"
    except Exception:
        return "failed"

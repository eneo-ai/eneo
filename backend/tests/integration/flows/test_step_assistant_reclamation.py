"""Reclamation of flow-managed step assistants nothing can use any more.

A step assistant goes when its flow manages it, no draft step and no version
that can still execute holds it, nothing outside the flow uses it, no hold
covers the flow and every foreign key to assistants is known; one bounded,
resumable operation does it for removed steps and deleted flows alike, and a
dry run only counts.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError

from eneo.assistants.assistant_update import AssistantUpdateCommand
from eneo.data_retention.application.retention_runner import RetentionRunReport
from eneo.data_retention.domain.retention import RetentionJobOutcome
from eneo.database.database import sessionmanager
from eneo.database.tables.api_keys_v2_table import ApiKeysV2
from eneo.database.tables.assistant_table import Assistants
from eneo.database.tables.audit_log_table import AuditLog
from eneo.database.tables.flow_tables import (
    FlowRetentionHolds,
    FlowRuns,
    Flows,
    FlowStepResults,
    FlowSteps,
)
from eneo.database.tables.group_chats_table import (
    GroupChatsAssistantsMapping,
    GroupChatsTable,
)
from eneo.database.tables.prompts_table import Prompts, PromptsAssistants
from eneo.database.tables.sessions_table import Sessions
from eneo.flows.application import flow_housekeeping_task as housekeeping
from eneo.flows.application import step_assistant_reclamation as reclamation
from eneo.flows.domain.flow import FlowStep
from eneo.flows.infrastructure.flow_repo import FlowRepository
from eneo.flows.infrastructure.flow_version_repo import FlowVersionRepository
from eneo.flows.infrastructure.step_assistant_reclamation_repo import (
    StepAssistantReclamationRepository,
)
from eneo.flows.runtime.tasks import inventory_flow_step_assistants
from eneo.main.config import Settings, get_settings
from eneo.main.exceptions import BadRequestException
from eneo.prompts.api.prompt_models import PromptCreate
from tests.fixtures import mint_v2_api_key
from tests.integration.flows.test_flow_assistant_fencing import (
    _TIMEOUT,  # pyright: ignore[reportPrivateUsage]
    _second_writer,  # pyright: ignore[reportPrivateUsage]
    _until_waiting_on_a_lock,  # pyright: ignore[reportPrivateUsage]
)
from tests.integration.flows.test_flow_assistant_update_siblings import (
    _admin_token_and_space,
)
from tests.integration.flows.test_flow_evidence_api_contracts import (
    _seed_transcript_words_for_audit_read,  # pyright: ignore[reportPrivateUsage]
)
from tests.integration.flows.test_flow_gallring import (
    _runner,  # pyright: ignore[reportPrivateUsage]
)
from tests.integration.flows.test_flow_retired_flow_history import (
    _history_read_paths,  # pyright: ignore[reportPrivateUsage]
    _retire_flow,  # pyright: ignore[reportPrivateUsage]
    _seed_owned_run,  # pyright: ignore[reportPrivateUsage]
)

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

_STEP = "step_assistants"
_RECLAIMED_COUNTS = {
    "removed_step_assistants": "removed_step",
    "retired_flow_assistants": "retired_flow",
}
_KEPT = (
    "executable_version",
    "recently_created",
    "external_reference",
    "held",
    "unknown_reference",
)


@dataclass(frozen=True)
class _Night:
    """One nightly flows.housekeeping execution, as the step_assistants step
    reported it to the runner (and so to its audit)."""

    report: RetentionRunReport

    def _count(self, key: str) -> int:
        return self.report.counts.get(f"{_STEP}.{key}", 0)

    def _blocked(self, key: str) -> int:
        return self.report.blocked.get(f"{_STEP}.{key}", 0)

    @property
    def reclaimed(self) -> dict[str, int]:
        return {
            r: self._count(k) for k, r in _RECLAIMED_COUNTS.items() if self._count(k)
        }

    @property
    def kept(self) -> dict[str, int]:
        return {k: self._blocked(k) for k in _KEPT if self._blocked(k)}

    @property
    def history_rows_detached(self) -> int:
        return self._count("step_results_detached")

    @property
    def lock_deferred(self) -> int:
        return self._blocked("lock_deferred")

    @property
    def failed(self) -> int:
        return self._blocked("flow_failed")

    @property
    def complete(self) -> bool:
        """Every step of the night finished its pass."""
        return self.report.outcome == RetentionJobOutcome.SUCCEEDED


async def _reclaim(*, chunk_rows: int = 500, budget_rows: int = 100_000) -> _Night:
    """One night of flows.housekeeping."""
    async with sessionmanager.session() as session:
        task = housekeeping.FlowHousekeepingTask(session, chunk_rows=chunk_rows)
        return _Night(
            await _runner(session, chunk_rows=chunk_rows, budget_rows=budget_rows).run(
                task
            )
        )


async def _nights(*, chunk_rows: int, budget_rows: int) -> list[_Night]:
    """Nights until one finishes every pass."""
    nights: list[_Night] = []
    for _ in range(20):
        night = await _reclaim(chunk_rows=chunk_rows, budget_rows=budget_rows)
        assert night.report.outcome in (
            RetentionJobOutcome.SUCCEEDED,
            RetentionJobOutcome.PARTIAL,
        ), night.report
        nights.append(night)
        if night.complete:
            return nights
    raise AssertionError("no night finished its pass in 20 nights")


def _step(assistant_id: UUID, order: int) -> FlowStep:
    return FlowStep(
        assistant_id=assistant_id,
        step_order=order,
        user_description=f"Steg {order}",
        input_source="flow_input" if order == 1 else "previous_step",
        input_type="text",
        output_mode="pass_through",
        output_type="text",
    )


async def _flow(
    db_container, space_id: UUID, *, attached: int, spare: int = 0
) -> tuple[UUID, list[UUID], list[UUID]]:
    """A draft flow whose ``attached`` assistants each back one step, plus
    ``spare`` managed assistants no step uses."""
    async with db_container() as container:
        service = container.flow_service()
        flow = await service.create_flow(
            space_id=space_id,
            name=f"Återvinning {uuid4().hex[:8]}",
            description=None,
            steps=[],
        )
        assistants: list[UUID] = []
        for index in range(attached + spare):
            assistant, _ = await service.create_flow_assistant(
                flow_id=flow.id, name=f"steg-{index}"
            )
            await service.update_flow_assistant(
                flow_id=flow.id,
                assistant_id=assistant.id,
                update=AssistantUpdateCommand(prompt=PromptCreate(text="Gör det.")),
            )
            assistants.append(assistant.id)
        if attached:
            await service.update_flow(
                flow_id=flow.id,
                steps=[
                    _step(a, order) for order, a in enumerate(assistants[:attached], 1)
                ],
            )
    return flow.id, assistants[:attached], assistants[attached:]


async def _age(db_container, assistant_ids: list[UUID]) -> None:
    """Created two days ago: older than an unsaved editor step."""
    async with db_container() as container:
        await container.session().execute(
            sa.update(Assistants)
            .where(Assistants.id.in_(assistant_ids))
            .values(created_at=sa.func.now() - sa.text("interval '2 days'"))
        )


async def _publish(db_container, flow_id: UUID) -> None:
    async with db_container() as container:
        await container.flow_service().publish_flow(flow_id=flow_id)


async def _unpublish(db_container, flow_id: UUID) -> None:
    async with db_container() as container:
        await container.flow_service().unpublish_flow(flow_id=flow_id)


async def _set_steps(db_container, flow_id: UUID, assistant_ids: list[UUID]) -> None:
    async with db_container() as container:
        service = container.flow_service()
        flow = await service.get_flow(flow_id)
        saved = list(flow.steps)
        steps: list[FlowStep] = []
        for order, assistant_id in enumerate(assistant_ids, 1):
            # Each saved step is kept once; a second use of its assistant is
            # a new step.
            match = next((s for s in saved if s.assistant_id == assistant_id), None)
            if match is None:
                steps.append(_step(assistant_id, order))
                continue
            saved.remove(match)
            steps.append(match.model_copy(update={"step_order": order}))
        await service.update_flow(flow_id=flow_id, steps=steps)


async def _add_run(
    db_container, *, flow_id: UUID, version: int, status: str, user
) -> UUID:
    async with db_container() as container:
        session = container.session()
        run = FlowRuns(
            flow_id=flow_id,
            flow_version=version,
            principal_type="user",
            principal_user_id=user.id,
            tenant_id=user.tenant_id,
            status=status,
            input_payload_json={},
            execution_heartbeat_at=sa.func.now() if status == "running" else None,
        )
        session.add(run)
        await session.flush()
        return run.id


async def _add_results(
    db_container, *, run_id: UUID, flow_id: UUID, tenant_id: UUID
) -> None:
    """One completed result per draft step, naming the step's assistant."""
    async with db_container() as container:
        session = container.session()
        steps = (
            await session.execute(
                sa.select(
                    FlowSteps.id, FlowSteps.step_order, FlowSteps.assistant_id
                ).where(FlowSteps.flow_id == flow_id)
            )
        ).all()
        for step_id, step_order, assistant_id in steps:
            session.add(
                FlowStepResults(
                    flow_run_id=run_id,
                    flow_id=flow_id,
                    tenant_id=tenant_id,
                    step_id=step_id,
                    step_order=step_order,
                    assistant_id=assistant_id,
                    status="completed",
                )
            )
        await session.flush()


async def _retired_flow_with_history(
    db_container,
    space_id: UUID,
    user,
    *,
    attached: int = 1,
    spare: int = 0,
    runs: int = 1,
) -> tuple[UUID, list[UUID], list[UUID]]:
    flow_id, used, spares = await _flow(
        db_container, space_id, attached=attached, spare=spare
    )
    await _publish(db_container, flow_id)
    for _ in range(runs):
        run_id = await _add_run(
            db_container, flow_id=flow_id, version=1, status="completed", user=user
        )
        await _add_results(
            db_container, run_id=run_id, flow_id=flow_id, tenant_id=user.tenant_id
        )
    async with db_container() as container:
        await container.flow_service().delete_flow(flow_id)
    return flow_id, used, spares


async def _existing(db_container, assistant_ids: list[UUID]) -> set[UUID]:
    async with db_container() as container:
        return set(
            await container.session().scalars(
                sa.select(Assistants.id).where(Assistants.id.in_(assistant_ids))
            )
        )


async def _scalar(db_container, query: Any) -> Any:
    async with db_container() as container:
        return await container.session().scalar(query)


async def _revision(db_container, flow_id: UUID) -> int:
    return await _scalar(
        db_container, sa.select(Flows.draft_revision).where(Flows.id == flow_id)
    )


async def _result_stamps(db_container) -> dict[UUID, Any]:
    async with db_container() as container:
        rows = await container.session().execute(
            sa.select(FlowStepResults.id, FlowStepResults.updated_at)
        )
        return dict(rows.tuples().all())


# --- Truth table -------------------------------------------------------------


Scenario = Callable[..., Awaitable[tuple[UUID, str]]]


async def _removed_step(db_container, space_id, user, monkeypatch) -> tuple[UUID, str]:
    _, _, (spare,) = await _flow(db_container, space_id, attached=1, spare=1)
    await _age(db_container, [spare])
    return spare, "removed_step"


async def _retired(db_container, space_id, user, monkeypatch) -> tuple[UUID, str]:
    _, (used,), _ = await _retired_flow_with_history(db_container, space_id, user)
    return used, "retired_flow"


async def _executable_version(db_container, space_id, user, monkeypatch):
    flow_id, (kept, removed), _ = await _flow(db_container, space_id, attached=2)
    await _publish(db_container, flow_id)
    await _add_run(db_container, flow_id=flow_id, version=1, status="queued", user=user)
    await _unpublish(db_container, flow_id)
    await _set_steps(db_container, flow_id, [kept])
    await _age(db_container, [removed])
    return removed, "executable_version"


async def _retired_with_run_in_flight(db_container, space_id, user, monkeypatch):
    flow_id, (used,), _ = await _flow(db_container, space_id, attached=1)
    await _publish(db_container, flow_id)
    await _add_run(
        db_container, flow_id=flow_id, version=1, status="running", user=user
    )
    async with db_container() as container:
        await container.flow_service().delete_flow(flow_id)
    return used, "executable_version"


async def _session(db_container, space_id, user, monkeypatch):
    _, _, (spare,) = await _flow(db_container, space_id, attached=1, spare=1)
    await _age(db_container, [spare])
    async with db_container() as container:
        container.session().add(
            Sessions(name="Samtal", user_id=user.id, assistant_id=spare)
        )
    return spare, "external_reference"


async def _group_chat(db_container, space_id, user, monkeypatch):
    _, _, (spare,) = await _flow(db_container, space_id, attached=1, spare=1)
    await _age(db_container, [spare])
    async with db_container() as container:
        session = container.session()
        chat = GroupChatsTable(name="Grupp", space_id=space_id, user_id=user.id)
        session.add(chat)
        await session.flush()
        session.add(
            GroupChatsAssistantsMapping(group_chat_id=chat.id, assistant_id=spare)
        )
    return spare, "external_reference"


async def _shared_prompt(db_container, space_id, user, monkeypatch):
    _, (used,), (spare,) = await _flow(db_container, space_id, attached=1, spare=1)
    await _age(db_container, [spare])
    async with db_container() as container:
        session = container.session()
        prompt_id = await session.scalar(
            sa.select(PromptsAssistants.prompt_id).where(
                PromptsAssistants.assistant_id == spare
            )
        )
        session.add(
            PromptsAssistants(prompt_id=prompt_id, assistant_id=used, is_selected=False)
        )
    return spare, "external_reference"


async def _insert_hold(
    db_container,
    user,
    flow_id: UUID,
    *,
    flow_run_id: UUID | None = None,
) -> None:
    """A legal hold on the flow, or on one of its runs, as H stores it."""
    async with db_container() as container:
        container.session().add(
            FlowRetentionHolds(
                tenant_id=user.tenant_id,
                flow_id=flow_id,
                flow_run_id=flow_run_id,
                reason="Begäran om utlämnande",
                review_by=datetime.now(timezone.utc) + timedelta(days=30),
                created_by_actor={"type": "user", "id": str(user.id)},
            )
        )


async def _run_of(db_container, flow_id: UUID) -> UUID:
    return await _scalar(
        db_container, sa.select(FlowRuns.id).where(FlowRuns.flow_id == flow_id)
    )


async def _held(db_container, space_id, user, monkeypatch):
    flow_id, (used,), _ = await _retired_flow_with_history(db_container, space_id, user)
    await _insert_hold(db_container, user, flow_id)
    return used, "held"


async def _held_run(db_container, space_id, user, monkeypatch):
    flow_id, (used,), _ = await _retired_flow_with_history(db_container, space_id, user)
    await _insert_hold(
        db_container, user, flow_id, flow_run_id=await _run_of(db_container, flow_id)
    )
    return used, "held"


async def _shared_in_retired_flow(db_container, space_id, user, monkeypatch):
    flow_id, (shared,), _ = await _flow(db_container, space_id, attached=1)
    await _set_steps(db_container, flow_id, [shared, shared])
    await _publish(db_container, flow_id)
    await _add_run(
        db_container, flow_id=flow_id, version=1, status="completed", user=user
    )
    async with db_container() as container:
        await container.flow_service().delete_flow(flow_id)
    return shared, "retired_flow"


async def _recently_created(db_container, space_id, user, monkeypatch):
    _, _, (spare,) = await _flow(db_container, space_id, attached=1, spare=1)
    return spare, "recently_created"


_SCENARIOS: dict[str, Scenario] = {
    "removed_step": _removed_step,
    "retired_flow": _retired,
    "shared_in_retired_flow": _shared_in_retired_flow,
    "executable_version": _executable_version,
    "retired_with_run_in_flight": _retired_with_run_in_flight,
    "session": _session,
    "group_chat": _group_chat,
    "shared_prompt": _shared_prompt,
    "held_flow": _held,
    "held_run": _held_run,
    "recently_created": _recently_created,
}
_RECLAIMED = {"removed_step", "retired_flow"}


@pytest.mark.parametrize("scenario", list(_SCENARIOS))
async def test_reclaims_or_keeps_by_reason(
    scenario, client, db_container, admin_user, patch_auth_service_jwt, monkeypatch
):
    """The truth table; kills M1 (version check), M3 (hold), M5 (external
    reference), M9 (grace), M10/M11 (a deleted flow's own steps); the dry run
    writes nothing (the assistant survives it)."""
    _ = patch_auth_service_jwt
    _, space_id = await _admin_token_and_space(client, db_container, admin_user)
    assistant_id, reason = await _SCENARIOS[scenario](
        db_container, space_id, admin_user, monkeypatch
    )

    inventory = await inventory_flow_step_assistants()
    assert await _existing(db_container, [assistant_id]) == {assistant_id}
    report = await _reclaim()

    reclaimed = reason in _RECLAIMED
    for counts in (inventory, report):
        assert dict(counts.reclaimed if reclaimed else counts.kept) == {reason: 1}
        assert dict(counts.kept if reclaimed else counts.reclaimed) == {}
    assert await _existing(db_container, [assistant_id]) == (
        set() if reclaimed else {assistant_id}
    )
    assert report.complete
    assert (report.failed, report.lock_deferred) == (0, 0)


@pytest.mark.parametrize(
    "reference, insert",
    [
        (
            "assistant_id uuid REFERENCES assistants (id)",
            "INSERT INTO s8_unknown_reference (assistant_id) VALUES (:assistant_id)",
        ),
        (
            "prompt_id uuid, assistant_id uuid, "
            "FOREIGN KEY (prompt_id, assistant_id) "
            "REFERENCES prompts_assistants (prompt_id, assistant_id) ON DELETE CASCADE",
            "INSERT INTO s8_unknown_reference (prompt_id, assistant_id) "
            "SELECT prompt_id, assistant_id FROM prompts_assistants "
            "WHERE assistant_id = :assistant_id",
        ),
    ],
    ids=["assistant", "nested-configuration-cascade"],
)
async def test_unknown_foreign_keys_keep_assistants_and_history(
    reference, insert, client, db_container, admin_user, patch_auth_service_jwt
):
    """Kills M6 absent FK inventory and M96 uncounted nested configuration cascades."""
    _ = patch_auth_service_jwt
    _, space_id = await _admin_token_and_space(client, db_container, admin_user)
    _, _, (spare,) = await _flow(db_container, space_id, attached=1, spare=1)
    await _age(db_container, [spare])
    _, (retired,), _ = await _retired_flow_with_history(
        db_container, space_id, admin_user
    )
    async with db_container() as container:
        await container.session().execute(
            sa.text(
                f"CREATE TABLE s8_unknown_reference (id serial PRIMARY KEY, {reference})"
            )
        )
        await container.session().execute(sa.text(insert), {"assistant_id": retired})
    try:
        report = await _reclaim()
    finally:
        async with db_container() as container:
            await container.session().execute(
                sa.text("DROP TABLE s8_unknown_reference")
            )

    assert dict(report.kept) == {"unknown_reference": 2}
    assert dict(report.reclaimed) == {}
    assert await _existing(db_container, [spare, retired]) == {spare, retired}
    assert (
        await _scalar(
            db_container,
            sa.select(sa.func.count()).where(FlowStepResults.assistant_id == retired),
        )
        == 1
    )


async def test_the_live_schema_has_no_unknown_foreign_key_to_assistants(db_container):
    """Fails when a migration adds a foreign key to assistants that reclamation does not classify (it would keep every assistant)."""
    async with db_container() as container:
        unknown = await StepAssistantReclamationRepository(
            container.session()
        ).unknown_assistant_foreign_keys()
    assert unknown == frozenset()


async def test_another_flows_assistant_is_never_reclaimed_by_this_flows_rule(
    client, db_container, admin_user, patch_auth_service_jwt
):
    """Kills M2b (the candidates' managing-flow marker dropped) and M1. A live flow's assistant held by its own run in flight stays, whatever
    another (deleted) flow's reclamation decides."""
    _ = patch_auth_service_jwt
    _, space_id = await _admin_token_and_space(client, db_container, admin_user)
    held, _ = await _executable_version(db_container, space_id, admin_user, None)
    _, (retired,), _ = await _retired_flow_with_history(
        db_container, space_id, admin_user
    )

    report = await _reclaim()

    assert await _existing(db_container, [held, retired]) == {held}
    assert dict(report.reclaimed) == {"retired_flow": 1}
    assert dict(report.kept) == {"executable_version": 1}
    assert report.failed == 0


async def test_the_unattached_grace_is_an_operator_setting_of_at_least_one_hour(
    client, db_container, admin_user, patch_auth_service_jwt, monkeypatch
):
    """Kills M16 (the grace setting ignored)."""
    _ = patch_auth_service_jwt
    _, space_id = await _admin_token_and_space(client, db_container, admin_user)
    _, _, (spare,) = await _flow(db_container, space_id, attached=1, spare=1)
    async with db_container() as container:
        await container.session().execute(
            sa.update(Assistants)
            .where(Assistants.id == spare)
            .values(created_at=sa.func.now() - sa.text("interval '2 hours'"))
        )

    default = await inventory_flow_step_assistants()
    monkeypatch.setattr(get_settings(), "flow_step_assistant_unattached_grace_hours", 1)
    shorter = await _reclaim()

    assert dict(default.kept) == {"recently_created": 1}
    assert dict(shorter.reclaimed) == {"removed_step": 1}
    assert await _existing(db_container, [spare]) == set()
    with pytest.raises(ValidationError):
        Settings(flow_step_assistant_unattached_grace_hours=0)


async def test_a_dry_run_takes_no_row_lock(
    client, db_container, admin_user, patch_auth_service_jwt
):
    """Kills M15 (the inventory locks the flow row). An edit holding the flow row does not hold up the inventory."""
    _ = patch_auth_service_jwt
    _, space_id = await _admin_token_and_space(client, db_container, admin_user)
    flow_id, _, (spare,) = await _flow(db_container, space_id, attached=1, spare=1)
    await _age(db_container, [spare])

    async with db_container() as container:
        await container.session().execute(
            sa.select(Flows.id).where(Flows.id == flow_id).with_for_update()
        )
        inventory = await asyncio.wait_for(
            inventory_flow_step_assistants(), timeout=_TIMEOUT
        )

    assert dict(inventory.reclaimed) == {"removed_step": 1}


# --- What a reclamation writes -------------------------------------------------


async def test_a_reclamation_is_audited_by_the_runner_as_the_system_without_content(
    client, db_container, admin_user, patch_auth_service_jwt
):
    """Kills lost or double-counted effects across continuing units and content in audit."""
    _ = patch_auth_service_jwt
    _, space_id = await _admin_token_and_space(client, db_container, admin_user)
    _, (used,), _ = await _retired_flow_with_history(
        db_container, space_id, admin_user, runs=2
    )

    night = await _reclaim()
    assert night.complete

    async with db_container() as container:
        rows = (
            await container.session().execute(
                sa.select(
                    AuditLog.actor_type,
                    AuditLog.tenant_id,
                    AuditLog.log_metadata,
                    AuditLog.description,
                ).where(AuditLog.action == "gallring_applied")
            )
        ).all()
    events = [row for row in rows if row[2]["step"] == "step_assistants"]
    assert len(events) == 2
    totals: dict[str, int] = {}
    for actor_type, tenant_id, metadata, description in events:
        assert (actor_type, tenant_id) == ("system", admin_user.tenant_id)
        assert metadata["task"] == "flows.housekeeping"
        assert metadata["job_run_id"] == str(night.report.job_run_id)
        for key, count in metadata["counts"].items():
            totals[key] = totals.get(key, 0) + count
        # Counts only: no assistant id, name or prompt.
        assert str(used) not in str(metadata) + description
        assert "steg-" not in str(metadata) + description
    assert totals == {
        "retired_flow_assistants": 1,
        "step_results_detached": 2,
        "draft_steps_deleted": 1,
    }


async def test_a_live_flows_reclamation_leaves_its_draft_and_steps(
    client, db_container, admin_user, patch_auth_service_jwt
):
    """Kills a draft_revision bump (an open editor would be refused as stale). An open editor is not refused afterwards: the draft is not touched."""
    _ = patch_auth_service_jwt
    _, space_id = await _admin_token_and_space(client, db_container, admin_user)
    flow_id, (used,), (spare,) = await _flow(
        db_container, space_id, attached=1, spare=1
    )
    await _age(db_container, [spare])
    revision = await _revision(db_container, flow_id)

    await _reclaim()

    assert await _existing(db_container, [used, spare]) == {used}
    assert await _revision(db_container, flow_id) == revision
    async with db_container() as container:
        flow = await container.flow_service().update_flow(
            flow_id=flow_id, name="Renamed", expected_revision=revision
        )
    assert [step.assistant_id for step in flow.steps] == [used]


# --- Bounded, resumable, idempotent ------------------------------------------


async def test_a_backlog_larger_than_a_nights_budget_is_reclaimed_over_nights(
    client, db_container, admin_user, patch_auth_service_jwt
):
    """Kills M4 (deletion ignores the batch: the runner refuses the call)."""
    _ = patch_auth_service_jwt
    _, space_id = await _admin_token_and_space(client, db_container, admin_user)
    assistants: list[UUID] = []
    for _ in range(3):
        _, used, spares = await _retired_flow_with_history(
            db_container, space_id, admin_user, attached=2, spare=1, runs=1
        )
        assistants += used + spares
    # 3 flows, 9 assistants, 6 step results and 6 draft steps: about 30 rows.

    nights = await _nights(chunk_rows=9, budget_rows=9)

    # Two complete assistant units cannot fit this execution's row budget.
    assert len(nights) > 2
    assert all(sum(night.reclaimed.values()) <= 1 for night in nights)
    assert sum(sum(night.reclaimed.values()) for night in nights) == 9
    assert sum(night.history_rows_detached for night in nights) == 6
    assert await _existing(db_container, assistants) == set()

    again = await _reclaim(chunk_rows=6, budget_rows=6)
    assert again.complete and again.reclaimed == {} and again.kept == {}


async def test_run_history_is_detached_in_chunks_and_stays_readable_between_them(
    client, db_container, admin_user, patch_auth_service_jwt
):
    """Kills M14 (detaching moves history timestamps) and M4."""
    _ = patch_auth_service_jwt
    _, space_id = await _admin_token_and_space(client, db_container, admin_user)
    _, (used,), _ = await _retired_flow_with_history(
        db_container, space_id, admin_user, runs=5
    )
    stamps = await _result_stamps(db_container)

    nights = await _nights(chunk_rows=8, budget_rows=10)

    first = nights[0]
    assert first.history_rows_detached > 0 and not first.complete
    assert first.reclaimed == {}
    assert sum(night.history_rows_detached for night in nights) == 5
    assert [night.reclaimed for night in nights if night.reclaimed] == [
        {"retired_flow": 1}
    ]
    assert await _existing(db_container, [used]) == set()
    assert (
        await _scalar(
            db_container,
            sa.select(sa.func.count()).where(FlowStepResults.assistant_id.is_(None)),
        )
        == 5
    )
    # Detaching keeps the rows' timestamps, which evidence reads.
    assert await _result_stamps(db_container) == stamps


async def test_a_flow_that_fails_is_rolled_back_and_the_next_call_reclaims_it(
    client, db_container, admin_user, patch_auth_service_jwt, monkeypatch
):
    """Kills M18 (no savepoint) and M82 (report retains rolled-back detachments)."""
    _ = patch_auth_service_jwt
    _, space_id = await _admin_token_and_space(client, db_container, admin_user)
    _, (first,), _ = await _retired_flow_with_history(
        db_container, space_id, admin_user, runs=2
    )
    _, (second,), _ = await _retired_flow_with_history(
        db_container, space_id, admin_user, runs=2
    )
    remove = reclamation.remove_flow_managed_assistants
    failures: list[UUID] = []

    async def fail_once(**kwargs: Any) -> None:
        if not failures:
            failures.append(kwargs["flow_id"])
            raise BadRequestException("forced refusal", code="flow_managed_assistant")
        await remove(**kwargs)

    monkeypatch.setattr(reclamation, "remove_flow_managed_assistants", fail_once)
    report = await _reclaim()

    assert report.failed == 1 and report.complete
    assert len(await _existing(db_container, [first, second])) == 1
    remaining_history = await _scalar(
        db_container,
        sa.select(sa.func.count()).where(
            FlowStepResults.assistant_id.in_([first, second])
        ),
    )
    assert report.history_rows_detached == 4 - remaining_history

    retry = await _reclaim()
    assert retry.complete and dict(retry.reclaimed) == {"retired_flow": 1}
    assert await _existing(db_container, [first, second]) == set()


@pytest.mark.parametrize("shared_flow", [False, True])
async def test_kept_assistants_never_starve_a_reclaimable_one_beyond_the_budget(
    shared_flow, client, db_container, admin_user, patch_auth_service_jwt
):
    """Kills M17 (cursor ignored) and M83 (kept prefix hides later assistants)."""
    _ = patch_auth_service_jwt
    _, space_id = await _admin_token_and_space(client, db_container, admin_user)
    if shared_flow:
        _, _, spares = await _flow(db_container, space_id, attached=1, spare=6)
    else:
        flows = [
            await _flow(db_container, space_id, attached=1, spare=1) for _ in range(4)
        ]
        spares = [flow[2][0] for flow in flows]
    spare = max(spares)
    await _age(db_container, spares)
    async with db_container() as container:
        container.session().add_all(
            Sessions(name="Kept chat", user_id=admin_user.id, assistant_id=kept)
            for kept in spares
            if kept != spare
        )
    nights = await _nights(chunk_rows=9, budget_rows=9)
    assert len(nights) > 1
    assert sum(sum(night.reclaimed.values()) for night in nights) == 1
    assert await _existing(db_container, [spare]) == set()


# --- History of a deleted flow -------------------------------------------------


@pytest.mark.parametrize(
    ("extra_configuration", "history", "remove_configuration", "cap", "deleted"),
    [
        (8, False, False, 6, False),
        (0, False, False, 6, False),
        (0, False, False, 7, True),
        (0, True, False, 8, False),
        (0, True, False, 9, True),
        (0, True, True, 5, False),
    ],
    ids=[
        "wide_configuration",
        "configuration_over_cap",
        "configuration_exact_fit",
        "history_over_cap",
        "history_exact_fit",
        "history_detach_over_cap",
    ],
)
async def test_atomic_cap_protects_configuration_and_history(
    extra_configuration,
    history,
    remove_configuration,
    cap,
    deleted,
    client,
    db_container,
    admin_user,
    patch_auth_service_jwt,
    monkeypatch,
):
    """Kills M84 uncharged cascades and M93 history detached before final-cost proof."""
    _ = patch_auth_service_jwt
    _, space_id = await _admin_token_and_space(client, db_container, admin_user)
    if history:
        _, (spare,), _ = await _retired_flow_with_history(
            db_container, space_id, admin_user, runs=2
        )
    else:
        _, _, (spare,) = await _flow(db_container, space_id, attached=1, spare=1)
    await _age(db_container, [spare])
    if remove_configuration:
        async with db_container() as container:
            await container.session().execute(
                sa.delete(FlowSteps).where(FlowSteps.assistant_id == spare)
            )
            await container.session().execute(
                sa.delete(PromptsAssistants).where(
                    PromptsAssistants.assistant_id == spare
                )
            )
    before = await _scalar(
        db_container,
        sa.select(sa.func.count()).where(
            PromptsAssistants.assistant_id == spare,
        ),
    )
    async with db_container() as container:
        for _ in range(extra_configuration):
            prompt = Prompts(
                text="Synthetic cap fixture",
                user_id=admin_user.id,
                tenant_id=admin_user.tenant_id,
            )
            container.session().add(prompt)
            await container.session().flush()
            container.session().add(
                PromptsAssistants(
                    prompt_id=prompt.id,
                    assistant_id=spare,
                    is_selected=False,
                )
            )
    settings = get_settings().model_copy(update={"gallring_max_family_rows": cap})
    monkeypatch.setattr(housekeeping, "get_settings", lambda: settings)
    night = await _reclaim(chunk_rows=6, budget_rows=30)
    assert night.complete
    assert night.reclaimed == (
        {"retired_flow" if history else "removed_step": 1} if deleted else {}
    )
    assert await _existing(db_container, [spare]) == (set() if deleted else {spare})
    if not deleted:
        assert night.report.blocked["step_assistants.assistant_exceeds_budget"] == 1
    assert night.history_rows_detached == (2 if history and deleted else 0)
    assert await _scalar(
        db_container,
        sa.select(sa.func.count()).where(
            PromptsAssistants.assistant_id == spare,
        ),
    ) == (0 if deleted else before + extra_configuration)
    assert await _scalar(
        db_container,
        sa.select(sa.func.count()).where(FlowStepResults.assistant_id == spare),
    ) == (2 if history and not deleted else 0)


@pytest.mark.parametrize("live_count", [1, 6])
async def test_scoped_keys_are_filtered_and_bounded_before_reclamation(
    live_count, client, db_container, admin_user, patch_auth_service_jwt, monkeypatch
):
    """Kills M94 revoked keys charged again and M95 unbounded key discovery."""
    _ = patch_auth_service_jwt
    _, space_id = await _admin_token_and_space(client, db_container, admin_user)
    _, _, (spare,) = await _flow(db_container, space_id, attached=1, spare=1)
    await _age(db_container, [spare])
    live_ids: list[UUID] = []
    async with db_container() as container:
        for index in range(2 + live_count):
            key = await mint_v2_api_key(
                container.api_key_v2_repo(),
                tenant_id=admin_user.tenant_id,
                user_id=admin_user.id,
                scope_type="assistant",
                scope_id=spare,
            )
            if index < 2:
                await container.session().execute(
                    sa.update(ApiKeysV2)
                    .where(ApiKeysV2.id == key.id)
                    .values(state="revoked", revoked_at=sa.func.now())
                )
            else:
                live_ids.append(key.id)
    settings = get_settings().model_copy(update={"gallring_max_family_rows": 10})
    monkeypatch.setattr(housekeeping, "get_settings", lambda: settings)
    night = await _reclaim()
    deleted = live_count == 1
    assert night.complete
    assert night.reclaimed == ({"removed_step": 1} if deleted else {})
    assert await _existing(db_container, [spare]) == (set() if deleted else {spare})
    if not deleted:
        assert night.report.blocked["step_assistants.assistant_exceeds_budget"] == 1
    assert await _scalar(
        db_container,
        sa.select(sa.func.count()).where(
            ApiKeysV2.id.in_(live_ids), ApiKeysV2.revoked_at.is_not(None)
        ),
    ) == (1 if deleted else 0)
    assert await _scalar(
        db_container,
        sa.select(sa.func.count()).where(
            AuditLog.action == "api_key_revoked", AuditLog.entity_id.in_(live_ids)
        ),
    ) == (1 if deleted else 0)


async def test_a_deleted_flows_history_stays_readable_and_names_the_reclaimed_assistant(
    client,
    db_container,
    patch_auth_service_jwt,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
):
    """Kills M7 (steps reader) and M8 (evidence reader) without the snapshot fallback."""
    seeded, owner_token = await _seed_owned_run(
        db_container=db_container,
        patch_auth_service_jwt=patch_auth_service_jwt,
        completion_model_factory=completion_model_factory,
        space_factory=space_factory,
        assistant_factory=assistant_factory,
        admin_user=admin_user,
    )
    await _seed_transcript_words_for_audit_read(
        db_container=db_container, seeded=seeded, tenant_id=admin_user.tenant_id
    )
    flow_id = UUID(seeded["flow_id"])
    async with db_container() as container:
        session = container.session()
        assistant_id = await session.scalar(
            sa.select(FlowSteps.assistant_id).where(FlowSteps.flow_id == flow_id)
        )
        await session.execute(
            sa.update(Assistants)
            .where(Assistants.id == assistant_id)
            .values(origin="flow_managed", managing_flow_id=flow_id, hidden=True)
        )
    await _retire_flow(
        db_container=db_container,
        flow_id=seeded["flow_id"],
        tenant_id=admin_user.tenant_id,
    )

    report = await _reclaim()

    assert dict(report.reclaimed) == {"retired_flow": 1}
    assert await _existing(db_container, [assistant_id]) == set()
    headers = {"Authorization": f"Bearer {owner_token}"}
    for path in _history_read_paths(seeded):
        response = await client.get(path, headers=headers)
        assert response.status_code == 200, (path, response.text)
    run_path = f"/api/v1/flows/{seeded['flow_id']}/runs/{seeded['run_id']}"
    steps = await client.get(f"{run_path}/steps/", headers=headers)
    assert [step["assistant_id"] for step in steps.json()] == [str(assistant_id)]
    evidence = await client.get(f"{run_path}/evidence/", headers=headers)
    assert [step["assistant_id"] for step in evidence.json()["step_results"]] == [
        str(assistant_id)
    ]


# --- Races ---------------------------------------------------------------------


class _Pause:
    """Holds the first call of ``target`` until ``proceed``; whatever the test
    outcome, ``settle`` releases it and waits for every task it was given."""

    def __init__(self, target: Callable[..., Awaitable[Any]]) -> None:
        self.target = target
        self.reached = asyncio.Event()
        self.proceed = asyncio.Event()
        self.tasks: list[asyncio.Task[Any]] = []

    def function(self) -> Callable[..., Awaitable[Any]]:
        """A plain function, so it binds as a method where it replaces one."""

        async def paused(*args: Any, **kwargs: Any) -> Any:
            if not self.reached.is_set():
                self.reached.set()
                await self.proceed.wait()
            return await self.target(*args, **kwargs)

        return paused

    def track(self, task: asyncio.Task[Any]) -> asyncio.Task[Any]:
        self.tasks.append(task)
        return task

    async def wait_reached(self) -> None:
        await asyncio.wait_for(self.reached.wait(), timeout=_TIMEOUT)

    async def settle(self) -> list[Any]:
        self.proceed.set()
        return await asyncio.wait_for(
            asyncio.gather(*self.tasks, return_exceptions=True), timeout=_TIMEOUT
        )


async def _attach_in(container, flow_id: UUID, assistant_ids: list[UUID]) -> object:
    service = container.flow_service()
    flow = await service.get_flow(flow_id)
    by_assistant = {step.assistant_id: step for step in flow.steps}
    return await service.update_flow(
        flow_id=flow_id,
        steps=[
            by_assistant.get(a) or _step(a, order)
            for order, a in enumerate(assistant_ids, 1)
        ],
    )


async def _live_flow_with_an_old_spare(client, db_container, admin_user):
    _, space_id = await _admin_token_and_space(client, db_container, admin_user)
    flow_id, (used,), (spare,) = await _flow(
        db_container, space_id, attached=1, spare=1
    )
    await _age(db_container, [spare])
    return flow_id, used, spare


async def _second(pause: _Pause, db_container, write) -> asyncio.Future[int]:
    task, pid = await _second_writer(db_container, write)
    pause.track(task)
    return pid


def _writer(kind: str, flow_id: UUID, used: UUID, spare: UUID):
    """(the paused method that runs under the flow row lock, the write)."""
    if kind == "attach":
        return (FlowRepository, "_sync_flow_steps"), lambda container: _attach_in(
            container, flow_id, [used, spare]
        )
    return (FlowVersionRepository, "create"), lambda container: (
        container.flow_service().publish_flow(flow_id=flow_id)
    )


@pytest.mark.parametrize("writer_first", [True, False])
async def test_external_reference_writers_serialize_on_the_assistant(
    writer_first, client, db_container, admin_user, patch_auth_service_jwt
):
    """Kills M97 missing assistant root lock and M98 missing SKIP LOCKED."""
    _ = patch_auth_service_jwt
    _, _, spare = await _live_flow_with_an_old_spare(client, db_container, admin_user)

    async def reference(container):
        container.session().add(
            Sessions(name="Concurrent chat", user_id=admin_user.id, assistant_id=spare)
        )
        await container.session().flush()

    if writer_first:
        async with db_container() as writer:
            await reference(writer)
            night = await asyncio.wait_for(_reclaim(), timeout=_TIMEOUT)
        assert night.complete and night.lock_deferred == 1
        assert night.reclaimed == {}
        later = await _reclaim()
        assert later.kept == {"external_reference": 1}
        assert await _existing(db_container, [spare]) == {spare}
        return

    # Both the flow and assistant are locked before this canonical fresh read.
    owner = FlowRepository
    pause = _Pause(owner.orphaned_flow_managed_assistant_ids)
    with patch.object(owner, "orphaned_flow_managed_assistant_ids", pause.function()):
        try:
            pause.track(asyncio.create_task(_reclaim()))
            await pause.wait_reached()
            pid = await _second(pause, db_container, reference)
            await _until_waiting_on_a_lock(db_container, pid)
        finally:
            night, written = await pause.settle()
    assert not isinstance(night, BaseException), night
    assert night.complete and night.reclaimed == {"removed_step": 1}
    assert isinstance(written, IntegrityError)
    assert await _existing(db_container, [spare]) == set()


@pytest.mark.parametrize("kind", ["attach", "publish"])
async def test_a_writer_holding_the_flow_row_defers_the_flow_to_a_later_night(
    kind, client, db_container, admin_user, patch_auth_service_jwt
):
    """Kills M12 (the row lock waits instead of SKIP LOCKED)."""
    _ = patch_auth_service_jwt
    flow_id, used, spare = await _live_flow_with_an_old_spare(
        client, db_container, admin_user
    )
    (owner, method), write = _writer(kind, flow_id, used, spare)
    pause = _Pause(getattr(owner, method))
    with patch.object(owner, method, pause.function()):
        try:
            await _second(pause, db_container, write)
            await pause.wait_reached()
            night = await asyncio.wait_for(_reclaim(), timeout=_TIMEOUT)
        finally:
            (written,) = await pause.settle()

    assert not isinstance(written, BaseException), written
    assert (night.lock_deferred, night.reclaimed) == (1, {})
    later = await _reclaim()
    # An attached assistant is in use; a published flow's spare is not.
    expected = {} if kind == "attach" else {"removed_step": 1}
    assert later.reclaimed == expected
    assert await _existing(db_container, [used, spare]) == (
        {used, spare} if kind == "attach" else {used}
    )


@pytest.mark.parametrize("kind", ["attach", "publish"])
async def test_a_writer_waiting_for_a_reclamation_never_uses_the_deleted_assistant(
    kind, client, db_container, admin_user, patch_auth_service_jwt
):
    """Kills M13 (no flow row lock when deleting)."""
    _ = patch_auth_service_jwt
    flow_id, used, spare = await _live_flow_with_an_old_spare(
        client, db_container, admin_user
    )
    _, write = _writer(kind, flow_id, used, spare)
    pause = _Pause(StepAssistantReclamationRepository.assistant_row)
    with patch.object(
        StepAssistantReclamationRepository, "assistant_row", pause.function()
    ):
        try:
            pause.track(asyncio.create_task(_reclaim()))
            await pause.wait_reached()
            pid = await _second(pause, db_container, write)
            await _until_waiting_on_a_lock(db_container, pid)
        finally:
            night, written = await pause.settle()

    assert not isinstance(night, BaseException), night
    assert night.reclaimed == {"removed_step": 1}
    assert await _existing(db_container, [used, spare]) == {used}
    async with db_container() as container:
        flow = await container.flow_service().get_flow(flow_id)
        version = (
            await FlowVersionRepository(session=container.session()).get(
                flow_id=flow_id, version=1, tenant_id=admin_user.tenant_id
            )
            if kind == "publish"
            else None
        )
    assert [step.assistant_id for step in flow.steps] == [used]
    if kind == "attach":
        # It read the assistant before the reclamation committed; its step
        # insert fails on flow_steps' foreign key and the edit rolls back.
        assert isinstance(written, IntegrityError), written
        assert "flow_steps_assistant_id_fkey" in str(written)
    else:
        assert not isinstance(written, BaseException), written
        assert version is not None
        assert [step["assistant_id"] for step in version.definition_json["steps"]] == [
            str(used)
        ]

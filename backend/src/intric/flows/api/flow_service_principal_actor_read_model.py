from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import cast
from uuid import UUID

from intric.authentication.api_key_v2_repo import ApiKeysV2Repository
from intric.authentication.auth_models import FlowServicePrincipalActorPublic
from intric.flows.api.flow_assembler import FlowAssembler
from intric.flows.api.flow_models import FlowRunReviewCheckpointPublic
from intric.flows.domain.flow import FlowRunReviewCheckpoint


async def load_flow_service_principal_actor_summaries(
    *,
    api_key_repo: ApiKeysV2Repository,
    tenant_id: UUID,
    service_principal_ids: Iterable[UUID | None],
) -> dict[UUID, FlowServicePrincipalActorPublic]:
    ids = tuple(
        dict.fromkeys(
            service_principal_id
            for service_principal_id in service_principal_ids
            if service_principal_id is not None
        )
    )
    if not ids:
        return {}
    service_principals = await api_key_repo.list_service_principals_by_ids(
        service_principal_ids=ids,
        tenant_id=tenant_id,
    )
    return {
        service_principal_id: FlowServicePrincipalActorPublic.model_validate(
            service_principal
        )
        for service_principal_id, service_principal in service_principals.items()
    }


async def enrich_review_checkpoint_service_principal_summaries(
    *,
    api_key_repo: ApiKeysV2Repository,
    tenant_id: UUID,
    checkpoint: FlowRunReviewCheckpoint,
) -> FlowRunReviewCheckpointPublic:
    actors = await load_flow_service_principal_actor_summaries(
        api_key_repo=api_key_repo,
        tenant_id=tenant_id,
        service_principal_ids=(
            checkpoint.requester_service_id,
            checkpoint.decided_by_service_id,
        ),
    )
    requester_actor = (
        actors.get(checkpoint.requester_service_id)
        if checkpoint.requester_service_id is not None
        else None
    )
    decider_actor = (
        actors.get(checkpoint.decided_by_service_id)
        if checkpoint.decided_by_service_id is not None
        else None
    )
    return FlowAssembler().to_review_checkpoint_public(
        checkpoint,
        requester_service_principal=requester_actor,
        decided_by_service_principal=decider_actor,
    )


async def enrich_evidence_service_principal_summaries(
    *,
    api_key_repo: ApiKeysV2Repository,
    tenant_id: UUID,
    payload: Mapping[str, object],
) -> dict[str, object]:
    service_principal_ids = tuple(_iter_review_checkpoint_service_ids(payload)) + tuple(
        _iter_rerun_operation_service_ids(payload)
    )
    actors = await load_flow_service_principal_actor_summaries(
        api_key_repo=api_key_repo,
        tenant_id=tenant_id,
        service_principal_ids=service_principal_ids,
    )
    if not actors:
        return dict(payload)

    enriched = dict(payload)
    enriched["review_checkpoints"] = _enrich_records(
        payload.get("review_checkpoints"),
        actors=actors,
        service_fields=(
            ("requester_service_id", "requester_service_principal"),
            ("decided_by_service_id", "decided_by_service_principal"),
        ),
    )
    enriched["rerun_operations"] = _enrich_records(
        payload.get("rerun_operations"),
        actors=actors,
        service_fields=(("requested_by_service_id", "requested_by_service_principal"),),
    )
    return enriched


def _iter_review_checkpoint_service_ids(
    payload: Mapping[str, object],
) -> Iterable[UUID]:
    for record in _iter_mapping_records(payload.get("review_checkpoints")):
        yield from _iter_record_service_ids(
            record, ("requester_service_id", "decided_by_service_id")
        )


def _iter_rerun_operation_service_ids(payload: Mapping[str, object]) -> Iterable[UUID]:
    for record in _iter_mapping_records(payload.get("rerun_operations")):
        yield from _iter_record_service_ids(record, ("requested_by_service_id",))


def _iter_record_service_ids(
    record: Mapping[str, object], service_fields: Iterable[str]
) -> Iterable[UUID]:
    for field_name in service_fields:
        service_id = _coerce_uuid(record.get(field_name))
        if service_id is not None:
            yield service_id


def _iter_mapping_records(value: object) -> Iterable[Mapping[str, object]]:
    items = _as_sequence(value)
    if items is None:
        return ()
    records: list[Mapping[str, object]] = []
    for item in items:
        record = _as_record(item)
        if record is not None:
            records.append(record)
    return tuple(records)


def _enrich_records(
    value: object,
    *,
    actors: Mapping[UUID, FlowServicePrincipalActorPublic],
    service_fields: Iterable[tuple[str, str]],
) -> object:
    items = _as_sequence(value)
    if items is None:
        return value

    enriched_records: list[object] = []
    for item in items:
        record = _as_record(item)
        if record is None:
            enriched_records.append(item)
            continue
        enriched = dict(record)
        for service_id_field, summary_field in service_fields:
            service_id = _coerce_uuid(record.get(service_id_field))
            if service_id is None:
                continue
            actor = actors.get(service_id)
            if actor is not None:
                enriched[summary_field] = actor.model_dump(mode="json")
        enriched_records.append(enriched)
    return enriched_records


def _as_sequence(value: object) -> Sequence[object] | None:
    if isinstance(value, list | tuple):
        return cast(Sequence[object], value)
    return None


def _as_record(value: object) -> Mapping[str, object] | None:
    if not isinstance(value, Mapping):
        return None
    values = cast(Mapping[object, object], value)
    record: dict[str, object] = {}
    for key, item in values.items():
        if isinstance(key, str):
            record[key] = item
    return record


def _coerce_uuid(value: object) -> UUID | None:
    if isinstance(value, UUID):
        return value
    if isinstance(value, str):
        try:
            return UUID(value)
        except ValueError:
            return None
    return None

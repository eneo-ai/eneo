"""The checks every Flow run history deletion shares: a run's delivery blockers
and the reference guard over files (every owner a file can have)."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from types import MappingProxyType

import sqlalchemy as sa
from sqlalchemy.orm import aliased

from eneo.database.tables.app_table import AppRunsFiles, AppsFiles
from eneo.database.tables.assistant_table import AssistantsFiles
from eneo.database.tables.files_table import Files
from eneo.database.tables.flow_tables import (
    BuilderSessionFiles,
    FlowLiveTranscripts,
    FlowOutboxDeliveryStatus,
    FlowRunAuditOutbox,
    FlowRunStepInputFiles,
    FlowRunStepResultFiles,
    FlowRuntimeUploadedFiles,
    FlowRunWebhookDeliveries,
    FlowTemplateAssets,
    FlowVersionFileReferences,
)
from eneo.database.tables.questions_table import QuestionsFiles


def flow_run_undelivered_audit_exists(run_id_col: object) -> sa.Exists:
    return (
        sa.select(sa.literal(1))
        .select_from(FlowRunAuditOutbox)
        .where(FlowRunAuditOutbox.flow_run_id == run_id_col)
        .where(
            FlowRunAuditOutbox.delivery_status
            != FlowOutboxDeliveryStatus.DELIVERED.value
        )
        .exists()
    )


def flow_run_unresolved_webhook_exists(run_id_col: object) -> sa.Exists:
    return (
        sa.select(sa.literal(1))
        .select_from(FlowRunWebhookDeliveries)
        .where(FlowRunWebhookDeliveries.flow_run_id == run_id_col)
        .where(
            FlowRunWebhookDeliveries.delivery_status
            == FlowOutboxDeliveryStatus.PENDING.value
        )
        .exists()
    )


def _flow_template_asset_file_exists() -> sa.Exists:
    return (
        sa.select(sa.literal(1))
        .select_from(FlowTemplateAssets)
        .where(FlowTemplateAssets.file_id == Files.id)
        .exists()
    )


def _flow_runtime_upload_file_exists() -> sa.Exists:
    return (
        sa.select(sa.literal(1))
        .select_from(FlowRuntimeUploadedFiles)
        .where(FlowRuntimeUploadedFiles.file_id == Files.id)
        .exists()
    )


def _flow_live_transcript_file_exists() -> sa.Exists:
    return (
        sa.select(sa.literal(1))
        .select_from(FlowLiveTranscripts)
        .where(FlowLiveTranscripts.bound_file_id == Files.id)
        .exists()
    )


def _flow_run_step_input_file_exists() -> sa.Exists:
    return (
        sa.select(sa.literal(1))
        .select_from(FlowRunStepInputFiles)
        .where(FlowRunStepInputFiles.file_id == Files.id)
        .exists()
    )


def _flow_run_step_result_file_exists() -> sa.Exists:
    return (
        sa.select(sa.literal(1))
        .select_from(FlowRunStepResultFiles)
        .where(FlowRunStepResultFiles.file_id == Files.id)
        .exists()
    )


def _app_file_exists() -> sa.Exists:
    return (
        sa.select(sa.literal(1))
        .select_from(AppsFiles)
        .where(AppsFiles.file_id == Files.id)
        .exists()
    )


def _app_run_file_exists() -> sa.Exists:
    return (
        sa.select(sa.literal(1))
        .select_from(AppRunsFiles)
        .where(AppRunsFiles.file_id == Files.id)
        .exists()
    )


def _question_file_exists() -> sa.Exists:
    return (
        sa.select(sa.literal(1))
        .select_from(QuestionsFiles)
        .where(QuestionsFiles.file_id == Files.id)
        .exists()
    )


def _flow_version_file_exists() -> sa.Exists:
    return (
        sa.select(sa.literal(1))
        .select_from(FlowVersionFileReferences)
        .where(FlowVersionFileReferences.file_id == Files.id)
        .exists()
    )


def _assistant_file_exists() -> sa.Exists:
    return (
        sa.select(sa.literal(1))
        .select_from(AssistantsFiles)
        .where(AssistantsFiles.file_id == Files.id)
        .exists()
    )


def _builder_session_file_exists() -> sa.Exists:
    return (
        sa.select(sa.literal(1))
        .select_from(BuilderSessionFiles)
        .where(BuilderSessionFiles.file_id == Files.id)
        .exists()
    )


def _child_file_exists() -> sa.Exists:
    # A derived child blocks parent purge: cascading could delete a referenced child.
    child_files = aliased(Files)
    return (
        sa.select(sa.literal(1))
        .select_from(child_files)
        .where(child_files.parent_file_id == Files.id)
        .exists()
    )


_FILE_REFERENCE_EXISTS_BY_TABLE: Mapping[str, Callable[[], sa.Exists]] = (
    MappingProxyType(
        {
            Files.__tablename__: _child_file_exists,
            FlowTemplateAssets.__tablename__: _flow_template_asset_file_exists,
            FlowVersionFileReferences.__tablename__: _flow_version_file_exists,
            FlowRuntimeUploadedFiles.__tablename__: _flow_runtime_upload_file_exists,
            FlowLiveTranscripts.__tablename__: _flow_live_transcript_file_exists,
            FlowRunStepInputFiles.__tablename__: _flow_run_step_input_file_exists,
            FlowRunStepResultFiles.__tablename__: _flow_run_step_result_file_exists,
            AppsFiles.__tablename__: _app_file_exists,
            AppRunsFiles.__tablename__: _app_run_file_exists,
            QuestionsFiles.__tablename__: _question_file_exists,
            AssistantsFiles.__tablename__: _assistant_file_exists,
            BuilderSessionFiles.__tablename__: _builder_session_file_exists,
        }
    )
)
FLOW_FILE_REFERENCE_TABLE_NAMES = frozenset(_FILE_REFERENCE_EXISTS_BY_TABLE)


def flow_file_reference_exists(
    *, excluding: frozenset[str] = frozenset()
) -> sa.ColumnElement[bool]:
    """The reference guard over `Files`: any owner except the excluded tables."""
    unknown = excluding - FLOW_FILE_REFERENCE_TABLE_NAMES
    if unknown:
        raise ValueError(f"Unknown file reference tables: {sorted(unknown)}")
    return sa.or_(
        *(
            reference_exists()
            for table_name, reference_exists in _FILE_REFERENCE_EXISTS_BY_TABLE.items()
            if table_name not in excluding
        )
    )

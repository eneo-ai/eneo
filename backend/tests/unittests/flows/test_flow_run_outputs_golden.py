"""What an existing flow with two PDF steps returns, pinned as literals.

The flow is the packaged implementation plan in ``tests/fixtures``: 17 steps,
a PDF rendered in step 15 and another in step 17, the last step. Its run
contract, a completed run's result, the documents' file names and the
evidence export's summary of the final output are frozen here. A change that
moves any of these values changes what existing integrations read.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from eneo.authentication.principal_types import PrincipalType
from eneo.files.file_models import FileType
from eneo.flow_packages.domain.flow_package_draft import normalize_flow_package_spec
from eneo.flow_packages.infrastructure.flow_package_zip_reader import (
    read_flow_package,
)
from eneo.flows.api.flow_assembler import FlowAssembler
from eneo.flows.application.flow_draft_materialization import (
    compile_flow_draft_changeset,
)
from eneo.flows.application.flow_run_evidence_bundle import (
    build_evidence_bundle,
    redact_evidence_bundle,
)
from eneo.flows.application.flow_run_evidence_export_manifest import (
    EvidenceExportContext,
    EvidenceExportUserActor,
)
from eneo.flows.application.flow_run_export_json import render_evidence_json_export
from eneo.flows.domain.flow import (
    FlowPersistedJsonObject,
    FlowRun,
    FlowRunStatus,
    FlowStepAttempt,
    FlowStepResult,
    FlowVersion,
)
from eneo.flows.domain.runtime import RuntimeStep
from eneo.flows.enums import FlowStepAttemptStatus, FlowStepResultStatus
from eneo.flows.flow_review_policy import dump_flow_step_review_policy
from eneo.flows.flow_run_contract_service import build_run_output_contract
from eneo.flows.flow_run_provenance import parse_resolved_input_edges
from eneo.flows.flow_run_step_result_file import (
    FlowRunStepResultFile,
    FlowRunStepResultFileSource,
)
from eneo.flows.published_definition import (
    build_published_definition_json,
    parse_published_definition,
    published_definition_checksum,
)
from eneo.flows.runtime.generated_file_names import GeneratedFileNames
from tests.flow_snapshot_fixtures import assistant_snapshot

_FIXTURE = (
    Path(__file__).resolve().parents[2]
    / "fixtures"
    / "genomforandeplan_ibic_v3_1_1.eneopkg"
)
_CREATED_AT = datetime(2026, 11, 19, 8, 30, tzinfo=timezone.utc)
_FLOW_ID = UUID("00000000-0000-0000-0000-00000000f100")
_RUN_ID = UUID("00000000-0000-0000-0000-00000000a100")
_TENANT_ID = UUID("00000000-0000-0000-0000-00000000c100")
_USER_ID = UUID("00000000-0000-0000-0000-00000000d100")
_TRACE_ID = UUID("00000000-0000-0000-0000-00000000e100")


def _id(name: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"https://eneo.test/golden/{name}")


# --- Frozen values -------------------------------------------------------

FROZEN_FINAL_OUTPUT_CONTRACT: dict[str, Any] = {
    "step_id": "688f502b-30b2-5fd5-86be-2778ee6730e7",
    "step_order": 17,
    "label": "17. Skapa PDF av LifeCare-versionen",
    "output_type": "pdf",
    "output_mode": "render_verbatim",
    "delivery": "artifact",
    "output_contract": None,
}

FROZEN_RUN_RESULT: dict[str, Any] = {
    "kind": "artifact",
    "files": [
        {
            "flow_run_id": "00000000-0000-0000-0000-00000000a100",
            "flow_id": "00000000-0000-0000-0000-00000000f100",
            "tenant_id": "00000000-0000-0000-0000-00000000c100",
            "step_result_id": "fee6e9c7-17c4-5f85-abcf-60dcd996033b",
            "step_id": "688f502b-30b2-5fd5-86be-2778ee6730e7",
            "step_order": 17,
            "attempt_no": 1,
            "file_id": "337668bc-b197-531d-9a11-ebb6e96e88de",
            "ordinal": 0,
            "source": "declared_artifact",
            "name": "lifecare.pdf",
            "checksum": "0000000000000000000000000000000000000000000000000000000000000011",
            "size": 1017,
            "mimetype": "application/pdf",
            "file_type": "document",
            "availability": "available",
        }
    ],
}

FROZEN_RUN_RESULT_FILES: list[dict[str, Any]] = [
    {
        "flow_run_id": "00000000-0000-0000-0000-00000000a100",
        "flow_id": "00000000-0000-0000-0000-00000000f100",
        "tenant_id": "00000000-0000-0000-0000-00000000c100",
        "step_result_id": "0b382b4b-2485-58a3-a50b-f4911fe0dbb4",
        "step_id": "4438ca4f-e4da-5c4a-9382-85c496a82d82",
        "step_order": 1,
        "attempt_no": 1,
        "file_id": "a3e51c03-37fe-5fb5-90ee-f092f51ce6a7",
        "ordinal": 0,
        "source": "generated_output",
        "name": "transkript.txt",
        "checksum": "0000000000000000000000000000000000000000000000000000000000000001",
        "size": 1001,
        "mimetype": "text/plain",
        "file_type": "text",
        "availability": "available",
    },
    {
        "flow_run_id": "00000000-0000-0000-0000-00000000a100",
        "flow_id": "00000000-0000-0000-0000-00000000f100",
        "tenant_id": "00000000-0000-0000-0000-00000000c100",
        "step_result_id": "48a64b6c-9cf8-5ead-be59-5317a93a4328",
        "step_id": "c6bf2667-c951-56b5-9486-372d036f78e3",
        "step_order": 15,
        "attempt_no": 1,
        "file_id": "612325b0-c0d0-5884-b1e8-37dff7437c03",
        "ordinal": 0,
        "source": "declared_artifact",
        "name": "brukarversion.pdf",
        "checksum": "000000000000000000000000000000000000000000000000000000000000000f",
        "size": 1015,
        "mimetype": "application/pdf",
        "file_type": "document",
        "availability": "available",
    },
    {
        "flow_run_id": "00000000-0000-0000-0000-00000000a100",
        "flow_id": "00000000-0000-0000-0000-00000000f100",
        "tenant_id": "00000000-0000-0000-0000-00000000c100",
        "step_result_id": "fee6e9c7-17c4-5f85-abcf-60dcd996033b",
        "step_id": "688f502b-30b2-5fd5-86be-2778ee6730e7",
        "step_order": 17,
        "attempt_no": 1,
        "file_id": "337668bc-b197-531d-9a11-ebb6e96e88de",
        "ordinal": 0,
        "source": "declared_artifact",
        "name": "lifecare.pdf",
        "checksum": "0000000000000000000000000000000000000000000000000000000000000011",
        "size": 1017,
        "mimetype": "application/pdf",
        "file_type": "document",
        "availability": "available",
    },
]

FROZEN_FILE_NAMES: dict[str, str] = {
    "step_15": "Genomförandeplan IBIC V3.1.1 (Cagri) 15. Skapa PDF av brukarversionen 2026-11-19.pdf",
    "step_17": "Genomförandeplan IBIC V3.1.1 (Cagri) 17. Skapa PDF av LifeCare-versionen 2026-11-19.pdf",
    "step_15_with_run_label": "Brukarsamtal 15. Skapa PDF av brukarversionen 2026-11-18.pdf",
    "step_17_with_run_label": "Brukarsamtal 17. Skapa PDF av LifeCare-versionen 2026-11-18.pdf",
}

FROZEN_EVIDENCE_FINAL_OUTPUT: dict[str, Any] = {
    "kind": "mixed",
    "text_present": True,
    "text_preview": {
        "preview": "LifeCare-versionen av planen.",
        "truncated": False,
        "byte_size": 29,
        "sha256": "e66a9e3b1abab3a5e4897e89c6359ea7910cd1e16d2fbac5659e49cc5180eedc",
    },
    "structured_present": False,
    "artifact_count": 1,
    "artifact_names": ["lifecare.pdf"],
    "artifact_details": [
        {
            "flow_run_id": "00000000-0000-0000-0000-00000000a100",
            "flow_id": "00000000-0000-0000-0000-00000000f100",
            "tenant_id": "00000000-0000-0000-0000-00000000c100",
            "file_id": "337668bc-b197-531d-9a11-ebb6e96e88de",
            "step_id": "688f502b-30b2-5fd5-86be-2778ee6730e7",
            "step_result_id": "fee6e9c7-17c4-5f85-abcf-60dcd996033b",
            "step_order": 17,
            "attempt_no": 1,
            "ordinal": 0,
            "source": "declared_artifact",
            "name": "lifecare.pdf",
            "checksum": "0000000000000000000000000000000000000000000000000000000000000011",
            "size": 1017,
            "mimetype": "application/pdf",
            "file_type": "document",
            "availability": "available",
        }
    ],
}

FROZEN_REDACTED_EVIDENCE_FINAL_OUTPUT: dict[str, Any] = {
    "kind": "mixed",
    "text_present": True,
    "text_preview": {
        "preview": "LifeCare-versionen av planen.",
        "truncated": False,
        "byte_size": 29,
        "sha256": "e66a9e3b1abab3a5e4897e89c6359ea7910cd1e16d2fbac5659e49cc5180eedc",
    },
    "structured_present": False,
    "artifact_count": 1,
    "artifact_names": ["lifecare.pdf"],
    "artifact_details": [
        {
            "flow_run_id": "00000000-0000-0000-0000-00000000a100",
            "flow_id": "00000000-0000-0000-0000-00000000f100",
            "tenant_id": "00000000-0000-0000-0000-00000000c100",
            "file_id": "337668bc-b197-531d-9a11-ebb6e96e88de",
            "step_id": "688f502b-30b2-5fd5-86be-2778ee6730e7",
            "step_result_id": "fee6e9c7-17c4-5f85-abcf-60dcd996033b",
            "step_order": 17,
            "attempt_no": 1,
            "ordinal": 0,
            "source": "declared_artifact",
            "name": "lifecare.pdf",
            "checksum": "0000000000000000000000000000000000000000000000000000000000000011",
            "size": 1017,
            "mimetype": "application/pdf",
            "file_type": "document",
            "availability": "available",
        }
    ],
}

FROZEN_EVIDENCE_CONTENT_HASHES: dict[str, str] = {
    "raw": "a5dfac61d7f657ad7d001cd3f063dee7dcc490be7237f434c411815734bef82f",
    "redacted": "bb740a598c820dab292d02b2f831356577044aa5f7c55048e186376d6361bcb8",
}

# A retried last step, below: the run reads each step's current attempt;
# the export reads every attempt.

FROZEN_RETRIED_RUN_RESULT: dict[str, Any] = {
    "kind": "artifact",
    "files": [
        {
            "flow_run_id": "00000000-0000-0000-0000-00000000a100",
            "flow_id": "00000000-0000-0000-0000-00000000f100",
            "tenant_id": "00000000-0000-0000-0000-00000000c100",
            "step_result_id": "fee6e9c7-17c4-5f85-abcf-60dcd996033b",
            "step_id": "688f502b-30b2-5fd5-86be-2778ee6730e7",
            "step_order": 17,
            "attempt_no": 2,
            "file_id": "fda2abac-ec5c-57ff-8ad6-b1b63720b002",
            "ordinal": 0,
            "source": "declared_artifact",
            "name": "lifecare.pdf",
            "checksum": "0000000000000000000000000000000000000000000000000000000000000011",
            "size": 1017,
            "mimetype": "application/pdf",
            "file_type": "document",
            "availability": "available",
        },
        {
            "flow_run_id": "00000000-0000-0000-0000-00000000a100",
            "flow_id": "00000000-0000-0000-0000-00000000f100",
            "tenant_id": "00000000-0000-0000-0000-00000000c100",
            "step_result_id": "fee6e9c7-17c4-5f85-abcf-60dcd996033b",
            "step_id": "688f502b-30b2-5fd5-86be-2778ee6730e7",
            "step_order": 17,
            "attempt_no": 2,
            "file_id": "78d7ac84-c8ff-539b-99be-ba8c7648103b",
            "ordinal": 1,
            "source": "generated_output",
            "name": "lifecare.txt",
            "checksum": "0000000000000000000000000000000000000000000000000000000000000011",
            "size": 1017,
            "mimetype": "text/plain",
            "file_type": "text",
            "availability": "available",
        },
    ],
}

FROZEN_RETRIED_RUN_RESULT_FILES: list[dict[str, Any]] = [
    {
        "flow_run_id": "00000000-0000-0000-0000-00000000a100",
        "flow_id": "00000000-0000-0000-0000-00000000f100",
        "tenant_id": "00000000-0000-0000-0000-00000000c100",
        "step_result_id": "48a64b6c-9cf8-5ead-be59-5317a93a4328",
        "step_id": "c6bf2667-c951-56b5-9486-372d036f78e3",
        "step_order": 15,
        "attempt_no": 1,
        "file_id": "3f4fb81d-13e5-5085-920c-b5ce1e8fd3e9",
        "ordinal": 0,
        "source": "declared_artifact",
        "name": "brukarversion.pdf",
        "checksum": "000000000000000000000000000000000000000000000000000000000000000f",
        "size": 1015,
        "mimetype": "application/pdf",
        "file_type": "document",
        "availability": "available",
    },
    {
        "flow_run_id": "00000000-0000-0000-0000-00000000a100",
        "flow_id": "00000000-0000-0000-0000-00000000f100",
        "tenant_id": "00000000-0000-0000-0000-00000000c100",
        "step_result_id": "fee6e9c7-17c4-5f85-abcf-60dcd996033b",
        "step_id": "688f502b-30b2-5fd5-86be-2778ee6730e7",
        "step_order": 17,
        "attempt_no": 2,
        "file_id": "fda2abac-ec5c-57ff-8ad6-b1b63720b002",
        "ordinal": 0,
        "source": "declared_artifact",
        "name": "lifecare.pdf",
        "checksum": "0000000000000000000000000000000000000000000000000000000000000011",
        "size": 1017,
        "mimetype": "application/pdf",
        "file_type": "document",
        "availability": "available",
    },
    {
        "flow_run_id": "00000000-0000-0000-0000-00000000a100",
        "flow_id": "00000000-0000-0000-0000-00000000f100",
        "tenant_id": "00000000-0000-0000-0000-00000000c100",
        "step_result_id": "fee6e9c7-17c4-5f85-abcf-60dcd996033b",
        "step_id": "688f502b-30b2-5fd5-86be-2778ee6730e7",
        "step_order": 17,
        "attempt_no": 2,
        "file_id": "78d7ac84-c8ff-539b-99be-ba8c7648103b",
        "ordinal": 1,
        "source": "generated_output",
        "name": "lifecare.txt",
        "checksum": "0000000000000000000000000000000000000000000000000000000000000011",
        "size": 1017,
        "mimetype": "text/plain",
        "file_type": "text",
        "availability": "available",
    },
]

FROZEN_RETRIED_EVIDENCE_FINAL_OUTPUT: dict[str, Any] = {
    "kind": "mixed",
    "text_present": True,
    "text_preview": {
        "preview": "LifeCare-versionen av planen.",
        "truncated": False,
        "byte_size": 29,
        "sha256": "e66a9e3b1abab3a5e4897e89c6359ea7910cd1e16d2fbac5659e49cc5180eedc",
    },
    "structured_present": False,
    "artifact_count": 2,
    "artifact_names": ["lifecare.pdf", "lifecare.txt"],
    "artifact_details": [
        {
            "flow_run_id": "00000000-0000-0000-0000-00000000a100",
            "flow_id": "00000000-0000-0000-0000-00000000f100",
            "tenant_id": "00000000-0000-0000-0000-00000000c100",
            "file_id": "fda2abac-ec5c-57ff-8ad6-b1b63720b002",
            "step_id": "688f502b-30b2-5fd5-86be-2778ee6730e7",
            "step_result_id": "fee6e9c7-17c4-5f85-abcf-60dcd996033b",
            "step_order": 17,
            "attempt_no": 2,
            "ordinal": 0,
            "source": "declared_artifact",
            "name": "lifecare.pdf",
            "checksum": "0000000000000000000000000000000000000000000000000000000000000011",
            "size": 1017,
            "mimetype": "application/pdf",
            "file_type": "document",
            "availability": "available",
        },
        {
            "flow_run_id": "00000000-0000-0000-0000-00000000a100",
            "flow_id": "00000000-0000-0000-0000-00000000f100",
            "tenant_id": "00000000-0000-0000-0000-00000000c100",
            "file_id": "78d7ac84-c8ff-539b-99be-ba8c7648103b",
            "step_id": "688f502b-30b2-5fd5-86be-2778ee6730e7",
            "step_result_id": "fee6e9c7-17c4-5f85-abcf-60dcd996033b",
            "step_order": 17,
            "attempt_no": 2,
            "ordinal": 1,
            "source": "generated_output",
            "name": "lifecare.txt",
            "checksum": "0000000000000000000000000000000000000000000000000000000000000011",
            "size": 1017,
            "mimetype": "text/plain",
            "file_type": "text",
            "availability": "available",
        },
    ],
}

FROZEN_RETRIED_REDACTED_EVIDENCE_FINAL_OUTPUT: dict[str, Any] = {
    "kind": "mixed",
    "text_present": True,
    "text_preview": {
        "preview": "LifeCare-versionen av planen.",
        "truncated": False,
        "byte_size": 29,
        "sha256": "e66a9e3b1abab3a5e4897e89c6359ea7910cd1e16d2fbac5659e49cc5180eedc",
    },
    "structured_present": False,
    "artifact_count": 2,
    "artifact_names": ["lifecare.pdf", "lifecare.txt"],
    "artifact_details": [
        {
            "flow_run_id": "00000000-0000-0000-0000-00000000a100",
            "flow_id": "00000000-0000-0000-0000-00000000f100",
            "tenant_id": "00000000-0000-0000-0000-00000000c100",
            "file_id": "fda2abac-ec5c-57ff-8ad6-b1b63720b002",
            "step_id": "688f502b-30b2-5fd5-86be-2778ee6730e7",
            "step_result_id": "fee6e9c7-17c4-5f85-abcf-60dcd996033b",
            "step_order": 17,
            "attempt_no": 2,
            "ordinal": 0,
            "source": "declared_artifact",
            "name": "lifecare.pdf",
            "checksum": "0000000000000000000000000000000000000000000000000000000000000011",
            "size": 1017,
            "mimetype": "application/pdf",
            "file_type": "document",
            "availability": "available",
        },
        {
            "flow_run_id": "00000000-0000-0000-0000-00000000a100",
            "flow_id": "00000000-0000-0000-0000-00000000f100",
            "tenant_id": "00000000-0000-0000-0000-00000000c100",
            "file_id": "78d7ac84-c8ff-539b-99be-ba8c7648103b",
            "step_id": "688f502b-30b2-5fd5-86be-2778ee6730e7",
            "step_result_id": "fee6e9c7-17c4-5f85-abcf-60dcd996033b",
            "step_order": 17,
            "attempt_no": 2,
            "ordinal": 1,
            "source": "generated_output",
            "name": "lifecare.txt",
            "checksum": "0000000000000000000000000000000000000000000000000000000000000011",
            "size": 1017,
            "mimetype": "text/plain",
            "file_type": "text",
            "availability": "available",
        },
    ],
}

FROZEN_RETRIED_EVIDENCE_CONTENT_HASHES: dict[str, str] = {
    "raw": "49d60a66ef71a23c758b4771f394f1d87234145b280ee2977128c0d3853bb59b",
    "redacted": "ce1c953c7fdfb9f41e8df681618be43da5dbdf2707470735b978dafe712ea881",
}

# --- Building the run ----------------------------------------------------


def _definition(
    deliverables: dict[int, FlowPersistedJsonObject] | None = None,
) -> tuple[str, FlowVersion, tuple[RuntimeStep, ...]]:
    envelope = read_flow_package(_FIXTURE.read_bytes())
    changeset = compile_flow_draft_changeset(normalize_flow_package_spec(envelope.spec))
    steps: list[FlowPersistedJsonObject] = []
    for step in changeset.compiled_steps:
        assistant_id = _id(f"assistant/{step.step_order}")
        steps.append(
            {
                "step_id": str(_id(f"step/{step.step_order}")),
                "assistant_id": str(assistant_id),
                "assistant_snapshot": assistant_snapshot(assistant_id),
                "step_order": step.step_order,
                "user_description": step.user_description,
                "input_source": step.input_source.value,
                "input_type": step.input_type.value,
                "input_contract": step.input_contract,
                "input_bindings": step.input_bindings,
                "input_config": step.input_config,
                "output_mode": step.output_mode.value,
                "output_type": step.output_type,
                "output_contract": step.output_contract,
                "output_config": (
                    {
                        **(step.output_config or {}),
                        "deliverable": deliverables[step.step_order],
                    }
                    if deliverables and step.step_order in deliverables
                    else step.output_config
                ),
                "review_policy": dump_flow_step_review_policy(step.review_policy),
            }
        )
    definition_json = build_published_definition_json(
        flow_id=_FLOW_ID,
        name=changeset.flow_name,
        description=changeset.flow_description,
        metadata_json=changeset.metadata_json,
        steps=steps,
    )
    version = FlowVersion(
        flow_id=_FLOW_ID,
        version=1,
        tenant_id=_TENANT_ID,
        definition_checksum=published_definition_checksum(definition_json),
        definition_json=definition_json,
        created_at=_CREATED_AT,
        updated_at=_CREATED_AT,
    )
    runtime_steps = tuple(
        parse_published_definition(definition_json, flow_version=1).runtime_steps()
    )
    return changeset.flow_name, version, runtime_steps


def _completed_run() -> FlowRun:
    return FlowRun(
        id=_RUN_ID,
        flow_id=_FLOW_ID,
        flow_version=1,
        principal_type=PrincipalType.USER,
        principal_user_id=_USER_ID,
        tenant_id=_TENANT_ID,
        trace_id=_TRACE_ID,
        status=FlowRunStatus.COMPLETED,
        cancelled_at=None,
        input_payload_json=None,
        # A rendered document's step persists the text it rendered.
        output_payload_json={"text": "LifeCare-versionen av planen."},
        job_id=None,
        created_at=_CREATED_AT,
        updated_at=_CREATED_AT,
    )


def _result_file(
    step: RuntimeStep,
    *,
    source: FlowRunStepResultFileSource,
    name: str,
    mimetype: str,
    file_type: FileType,
) -> FlowRunStepResultFile:
    return FlowRunStepResultFile(
        flow_run_id=_RUN_ID,
        flow_id=_FLOW_ID,
        tenant_id=_TENANT_ID,
        step_result_id=_id(f"step-result/{step.step_order}"),
        step_id=step.step_id,
        step_order=step.step_order,
        attempt_no=1,
        file_id=_id(f"file/{step.step_order}"),
        ordinal=0,
        source=source,
        name=name,
        checksum=f"{step.step_order:064x}",
        size=1000 + step.step_order,
        mimetype=mimetype,
        file_type=file_type,
        availability="available",
    )


def _result_files(steps: tuple[RuntimeStep, ...]) -> list[FlowRunStepResultFile]:
    by_order = {step.step_order: step for step in steps}
    return [
        _result_file(
            by_order[1],
            source="generated_output",
            name="transkript.txt",
            mimetype="text/plain",
            file_type=FileType.TEXT,
        ),
        _result_file(
            by_order[15],
            source="declared_artifact",
            name="brukarversion.pdf",
            mimetype="application/pdf",
            file_type=FileType.DOCUMENT,
        ),
        _result_file(
            by_order[17],
            source="declared_artifact",
            name="lifecare.pdf",
            mimetype="application/pdf",
            file_type=FileType.DOCUMENT,
        ),
    ]


# A retried last step: step 15 rendered once; step 17's first attempt failed
# after storing its document, the second rendered it again and also wrote its
# full text beside it.


def _attempt(step: RuntimeStep, *, attempt_no: int, failed: bool) -> FlowStepAttempt:
    return FlowStepAttempt(
        id=_id(f"attempt/{step.step_order}/{attempt_no}"),
        flow_run_id=_RUN_ID,
        flow_id=_FLOW_ID,
        tenant_id=_TENANT_ID,
        step_id=step.step_id,
        step_order=step.step_order,
        attempt_no=attempt_no,
        status=(
            FlowStepAttemptStatus.FAILED if failed else FlowStepAttemptStatus.COMPLETED
        ),
        error_code="render_failed" if failed else None,
        started_at=_CREATED_AT,
        finished_at=_CREATED_AT,
        created_at=_CREATED_AT,
        updated_at=_CREATED_AT,
    )


def _step_result(step: RuntimeStep, *, current_attempt_no: int) -> FlowStepResult:
    return FlowStepResult(
        id=_id(f"step-result/{step.step_order}"),
        flow_run_id=_RUN_ID,
        flow_id=_FLOW_ID,
        tenant_id=_TENANT_ID,
        step_id=step.step_id,
        step_order=step.step_order,
        current_attempt_no=current_attempt_no,
        output_payload_json={"text": f"Text för steg {step.step_order}."},
        status=FlowStepResultStatus.COMPLETED,
        started_at=_CREATED_AT,
        finished_at=_CREATED_AT,
        created_at=_CREATED_AT,
        updated_at=_CREATED_AT,
    )


def _attempt_file(
    step: RuntimeStep,
    *,
    attempt_no: int,
    source: FlowRunStepResultFileSource,
    name: str,
) -> FlowRunStepResultFile:
    generated = source == "generated_output"
    return _result_file(
        step,
        source=source,
        name=name,
        mimetype="text/plain" if generated else "application/pdf",
        file_type=FileType.TEXT if generated else FileType.DOCUMENT,
    ).model_copy(
        update={
            "attempt_no": attempt_no,
            "file_id": _id(f"file/{step.step_order}/{attempt_no}/{source}"),
            "ordinal": 1 if generated else 0,
        }
    )


def _retried_history(
    steps: tuple[RuntimeStep, ...],
) -> tuple[list[FlowStepResult], list[FlowStepAttempt], list[FlowRunStepResultFile]]:
    by_order = {step.step_order: step for step in steps}
    step_15, step_17 = by_order[15], by_order[17]
    return (
        [
            _step_result(step_15, current_attempt_no=1),
            _step_result(step_17, current_attempt_no=2),
        ],
        [
            _attempt(step_15, attempt_no=1, failed=False),
            _attempt(step_17, attempt_no=1, failed=True),
            _attempt(step_17, attempt_no=2, failed=False),
        ],
        [
            _attempt_file(
                step_15,
                attempt_no=1,
                source="declared_artifact",
                name="brukarversion.pdf",
            ),
            _attempt_file(
                step_17,
                attempt_no=1,
                source="declared_artifact",
                name="lifecare-forsta-forsoket.pdf",
            ),
            _attempt_file(
                step_17,
                attempt_no=2,
                source="declared_artifact",
                name="lifecare.pdf",
            ),
            _attempt_file(
                step_17,
                attempt_no=2,
                source="generated_output",
                name="lifecare.txt",
            ),
        ],
    )


def _current_attempt_files(
    step_results: list[FlowStepResult], files: list[FlowRunStepResultFile]
) -> list[FlowRunStepResultFile]:
    """The rows a run's detail reads: each step's current attempt only."""
    current = {result.step_id: result.current_attempt_no for result in step_results}
    return [file for file in files if current.get(file.step_id) == file.attempt_no]


# Each call below is the one place a later change to the call's shape lands;
# the frozen values above stay as they are.


def _contract(steps: tuple[RuntimeStep, ...]) -> dict[str, Any]:
    outputs = build_run_output_contract(steps)
    assert outputs is not None
    return outputs.final_output.model_dump(mode="json")


def _run_public(
    steps: tuple[RuntimeStep, ...],
    *,
    result_files: list[FlowRunStepResultFile] | None = None,
) -> dict[str, Any]:
    return (
        FlowAssembler()
        .to_run_public(
            _completed_run(),
            result_files=_result_files(steps) if result_files is None else result_files,
            outputs=build_run_output_contract(steps),
        )
        .model_dump(mode="json")
    )


def _file_names(
    flow_name: str,
    steps: tuple[RuntimeStep, ...],
    *,
    run_label: str | None = None,
    run_date: date | None = None,
) -> GeneratedFileNames:
    return GeneratedFileNames.for_run(
        flow_name=flow_name,
        steps=steps,
        run_created_at=_CREATED_AT,
        run_label=run_label,
        run_date=run_date,
    )


def _evidence_export(
    version: FlowVersion,
    steps: tuple[RuntimeStep, ...],
    *,
    redacted: bool,
    history: tuple[
        list[FlowStepResult], list[FlowStepAttempt], list[FlowRunStepResultFile]
    ]
    | None = None,
) -> dict[str, Any]:
    step_results, step_attempts, result_files = history or (
        [],
        [],
        _result_files(steps),
    )
    bundle = build_evidence_bundle(
        run=_completed_run(),
        version=version,
        step_results=step_results,
        step_attempts=step_attempts,
        resolved_input_edges_by_attempt_id={
            attempt.id: parse_resolved_input_edges(None) for attempt in step_attempts
        },
        result_files=result_files,
    )
    return render_evidence_json_export(
        bundle=redact_evidence_bundle(bundle) if redacted else bundle,
        context=EvidenceExportContext(
            detail_mode="redacted" if redacted else "raw",
            export_reason="support_debug" if redacted else "regulatory_audit",
            actor=EvidenceExportUserActor(type="user", user_id=_USER_ID),
        ),
    )


# --- Tests ---------------------------------------------------------------


def test_run_contract_names_the_last_pdf_as_the_final_output() -> None:
    _, _, steps = _definition()

    assert _contract(steps) == FROZEN_FINAL_OUTPUT_CONTRACT


def test_completed_run_returns_the_last_pdf_as_its_result() -> None:
    _, _, steps = _definition()

    run = _run_public(steps)

    assert run["result"] == FROZEN_RUN_RESULT
    assert run["result_files"] == FROZEN_RUN_RESULT_FILES


def test_both_pdfs_are_named_after_the_flow_their_step_and_the_run_day() -> None:
    flow_name, _, steps = _definition()
    by_flow = _file_names(flow_name, steps)
    by_run = _file_names(
        flow_name, steps, run_label="Brukarsamtal", run_date=date(2026, 11, 18)
    )

    assert {
        "step_15": by_flow.name(step_order=15, output_type="pdf"),
        "step_17": by_flow.name(step_order=17, output_type="pdf"),
        "step_15_with_run_label": by_run.name(step_order=15, output_type="pdf"),
        "step_17_with_run_label": by_run.name(step_order=17, output_type="pdf"),
    } == FROZEN_FILE_NAMES


def test_evidence_export_summarises_the_last_pdf_as_the_final_output() -> None:
    _, version, steps = _definition()

    raw = _evidence_export(version, steps, redacted=False)
    redacted = _evidence_export(version, steps, redacted=True)

    assert raw["summary"]["final_output"] == FROZEN_EVIDENCE_FINAL_OUTPUT
    assert redacted["summary"]["final_output"] == FROZEN_REDACTED_EVIDENCE_FINAL_OUTPUT


def test_evidence_export_hashes_the_same_bundle() -> None:
    _, version, steps = _definition()

    raw = _evidence_export(version, steps, redacted=False)
    redacted = _evidence_export(version, steps, redacted=True)

    assert {
        "raw": raw["manifest"]["content_hash"],
        "redacted": redacted["manifest"]["content_hash"],
    } == FROZEN_EVIDENCE_CONTENT_HASHES


def test_a_retried_last_step_returns_and_exports_only_its_current_document() -> None:
    _, version, steps = _definition()
    step_results, step_attempts, files = _retried_history(steps)

    run = _run_public(steps, result_files=_current_attempt_files(step_results, files))
    raw = _evidence_export(
        version, steps, redacted=False, history=(step_results, step_attempts, files)
    )
    redacted = _evidence_export(
        version, steps, redacted=True, history=(step_results, step_attempts, files)
    )

    assert run["result"] == FROZEN_RETRIED_RUN_RESULT
    assert run["result_files"] == FROZEN_RETRIED_RUN_RESULT_FILES
    assert raw["summary"]["final_output"] == FROZEN_RETRIED_EVIDENCE_FINAL_OUTPUT
    assert (
        redacted["summary"]["final_output"]
        == FROZEN_RETRIED_REDACTED_EVIDENCE_FINAL_OUTPUT
    )
    assert {
        "raw": raw["manifest"]["content_hash"],
        "redacted": redacted["manifest"]["content_hash"],
    } == FROZEN_RETRIED_EVIDENCE_CONTENT_HASHES


# --- Deliverables beside the frozen values -------------------------------


def _deliverables(
    items: list[dict[str, Any]],
) -> list[tuple[int, str | None, list[str]]]:
    return [
        (item["step_order"], item["label"], [file["name"] for file in item["files"]])
        for item in items
    ]


def test_an_existing_flow_delivers_its_last_pdf_only() -> None:
    _, _, steps = _definition()

    outputs = build_run_output_contract(steps)

    assert outputs is not None
    assert [
        (item.step_order, item.label, item.delivery.value)
        for item in outputs.deliverables
    ] == [(17, "17. Skapa PDF av LifeCare-versionen", "artifact")]


def test_a_deliverable_lists_only_its_steps_current_document_files() -> None:
    _, version, steps = _definition({15: {"label": "Brukarversion"}})
    step_results, step_attempts, files = _retried_history(steps)
    history = (step_results, step_attempts, files)

    run = _run_public(steps, result_files=_current_attempt_files(step_results, files))
    raw = _evidence_export(version, steps, redacted=False, history=history)
    redacted = _evidence_export(version, steps, redacted=True, history=history)

    expected = [
        (15, "Brukarversion", ["brukarversion.pdf"]),
        (17, "17. Skapa PDF av LifeCare-versionen", ["lifecare.pdf"]),
    ]
    assert _deliverables(run["deliverables"]) == expected
    assert _deliverables(raw["summary"]["deliverables"]) == expected
    assert _deliverables(redacted["summary"]["deliverables"]) == expected
    # The result keeps every current file of the last step; a deliverable
    # keeps its documents only.
    assert [file["name"] for file in run["result"]["files"]] == [
        "lifecare.pdf",
        "lifecare.txt",
    ]
    assert run["deliverables"][1]["files"][0]["availability"] == "available"


def test_deliverables_stay_out_of_the_hashed_evidence_bundle() -> None:
    _, version, steps = _definition()
    history = _retried_history(steps)

    raw = _evidence_export(version, steps, redacted=False, history=history)
    redacted = _evidence_export(version, steps, redacted=True, history=history)

    assert _deliverables(raw["summary"]["deliverables"]) == [
        (17, "17. Skapa PDF av LifeCare-versionen", ["lifecare.pdf"])
    ]
    assert {
        "raw": raw["manifest"]["content_hash"],
        "redacted": redacted["manifest"]["content_hash"],
    } == FROZEN_RETRIED_EVIDENCE_CONTENT_HASHES


def test_a_run_that_has_not_completed_delivers_nothing() -> None:
    _, version, steps = _definition()
    running = _completed_run().model_copy(
        update={"status": FlowRunStatus.RUNNING, "output_payload_json": None}
    )

    run = FlowAssembler().to_run_public(
        running,
        result_files=_result_files(steps),
        outputs=build_run_output_contract(steps),
    )
    bundle = build_evidence_bundle(
        run=running,
        version=version,
        step_results=[],
        step_attempts=[],
        resolved_input_edges_by_attempt_id={},
        result_files=_result_files(steps),
    )
    exported = render_evidence_json_export(
        bundle=bundle,
        context=EvidenceExportContext(
            detail_mode="raw",
            export_reason="regulatory_audit",
            actor=EvidenceExportUserActor(type="user", user_id=_USER_ID),
        ),
    )

    assert run.deliverables == []
    assert exported["summary"]["deliverables"] == []

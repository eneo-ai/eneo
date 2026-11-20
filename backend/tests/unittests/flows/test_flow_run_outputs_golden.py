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
    FlowVersion,
)
from eneo.flows.domain.runtime import RuntimeStep
from eneo.flows.flow_review_policy import dump_flow_step_review_policy
from eneo.flows.flow_run_contract_service import build_final_output_contract
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

# --- Building the run ----------------------------------------------------


def _definition() -> tuple[str, FlowVersion, tuple[RuntimeStep, ...]]:
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
                "output_config": step.output_config,
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


# Each call below is the one place a later change to the call's shape lands;
# the frozen values above stay as they are.


def _contract(steps: tuple[RuntimeStep, ...]) -> dict[str, Any]:
    contract = build_final_output_contract(steps)
    assert contract is not None
    return contract.model_dump(mode="json")


def _run_public(steps: tuple[RuntimeStep, ...]) -> dict[str, Any]:
    return (
        FlowAssembler()
        .to_run_public(
            _completed_run(),
            result_files=_result_files(steps),
            final_output=build_final_output_contract(steps),
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
    version: FlowVersion, steps: tuple[RuntimeStep, ...], *, redacted: bool
) -> dict[str, Any]:
    bundle = build_evidence_bundle(
        run=_completed_run(),
        version=version,
        step_results=[],
        step_attempts=[],
        resolved_input_edges_by_attempt_id={},
        result_files=_result_files(steps),
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

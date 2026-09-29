"""Arm O: a frozen gold spec becomes a published flow, an executed run and a scored,
sealed, receipted bundle, with no Builder call and the harness's own scoring."""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import hashlib
import importlib.util
import json
import sys
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest

from eneo.flows.ai_builder.ai_builder_authoring_policy import AIBuilderAuthoringPolicy
from eneo.flows.application.flow_authoring_command import (
    AIBuilderFlowAuthoringOrigin,
    FlowAuthoringResult,
)
from eneo.flows.flow_authoring_spec import (
    AssistantSpec,
    FlowDraftSpecCore,
    FormFieldSpec,
    InputSource,
    InputType,
    OutputMode,
    OutputType,
    StepSpec,
)

_SCRIPTS = Path(__file__).resolve().parents[4] / "scripts"


def _load(name: str, filename: str) -> ModuleType:
    if str(_SCRIPTS) not in sys.path:
        sys.path.insert(0, str(_SCRIPTS))
    spec = importlib.util.spec_from_file_location(name, _SCRIPTS / filename)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def harness() -> ModuleType:
    return _load("ai_builder_api_battle_test", "ai_builder_api_battle_test.py")


@pytest.fixture()
def arm(harness: ModuleType) -> ModuleType:
    del harness  # loaded first: the arm is imported by the harness by name
    return importlib.import_module("ai_builder_oracle_arm")


REQUIRED_FACT = "IAN-2026-1"
FORBIDDEN = "personnummer"


def _spec(*, final_instructions: str) -> FlowDraftSpecCore:
    return FlowDraftSpecCore(
        flow_name="Beslut",
        flow_description="Skriver ett beslut.",
        steps=[
            StepSpec(
                plan_step_ref="step_a",
                name="Läs ärendet",
                assistant_spec=AssistantSpec(instructions="Läs ärendet noga."),
                input_source=InputSource.FLOW_INPUT,
                input_type=InputType.TEXT,
                output_type=OutputType.TEXT,
            ),
            StepSpec(
                plan_step_ref="step_b",
                name="Skriv beslutet",
                assistant_spec=AssistantSpec(instructions=final_instructions),
                input_source=InputSource.PREVIOUS_STEP,
                input_type=InputType.TEXT,
                output_mode=OutputMode.PASS_THROUGH,
                output_type=OutputType.TEXT,
            ),
        ],
        form_fields=[FormFieldSpec(name="diarienummer", type="text", label="Dnr")],
    )


def _freeze(
    directory: Path,
    case_id: str,
    spec: FlowDraftSpecCore,
    *,
    template: str | None = None,
) -> Path:
    payload = spec.model_dump_json(indent=1).encode("utf-8")
    (directory / f"{case_id}.spec.json").write_bytes(payload)
    (directory / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "cases": {
                    case_id: {
                        "spec_file": f"{case_id}.spec.json",
                        "spec_file_sha256": hashlib.sha256(payload).hexdigest(),
                        "template_attachment": template,
                        "authoring": {"model": "test-author"},
                    }
                },
            }
        )
    )
    return directory


# ---------------------------------------------------------------- the spec set


def test_a_spec_whose_bytes_changed_after_the_freeze_is_refused(
    arm: ModuleType, tmp_path: Path
) -> None:
    _freeze(tmp_path, "case-1", _spec(final_instructions=f"Ange {REQUIRED_FACT}."))
    arm.load_gold_spec(tmp_path, "case-1")  # frozen bytes load

    spec_file = tmp_path / "case-1.spec.json"
    spec_file.write_text(spec_file.read_text().replace("Läs", "Granska"))

    with pytest.raises(ValueError, match="never edited after the freeze"):
        arm.load_gold_spec(tmp_path, "case-1")
    with pytest.raises(ValueError, match="no spec for case"):
        arm.load_gold_spec(tmp_path, "another-case")


def test_the_manifest_digest_is_part_of_the_receipts_run_context(
    arm: ModuleType, tmp_path: Path
) -> None:
    _freeze(tmp_path, "case-1", _spec(final_instructions="x"))
    context = arm.arm_run_context(SimpleNamespace(oracle_specs_dir=str(tmp_path)))
    assert context["arm"] == "oracle"
    assert (
        context["oracle_manifest_sha256"]
        == hashlib.sha256((tmp_path / "manifest.json").read_bytes()).hexdigest()
    )
    assert context["oracle_spec_count"] == 1


# ------------------------------------------------------- authoring-contract check


def test_a_valid_spec_passes_and_the_check_takes_no_expectation(
    arm: ModuleType,
) -> None:
    # The signature is the guarantee: a spec, the manifest's template name and
    # the request's attachment names. There is nowhere to pass an oracle.
    assert (
        arm.check_authoring_contract(
            _spec(final_instructions="x"), template_attachment=None, case_attachments=()
        )
        == []
    )


def test_the_check_names_each_arm_and_platform_rule_it_finds(arm: ModuleType) -> None:
    spec = _spec(final_instructions="x")
    spec.steps[0].assistant_spec = AssistantSpec(
        instructions="a", model_ref="model.gpt-x", knowledge_refs=["kb.regler"]
    )
    codes = {
        issue.code
        for issue in arm.check_authoring_contract(
            spec, template_attachment="mall.docx", case_attachments=("annat.docx",)
        )
    }
    assert {
        "arm_fixes_model",
        "arm_has_no_knowledge",
        "template_unused",
        "template_not_attached",
    } <= codes

    # The platform's own graph validator speaks for what a draft cannot be: a
    # first step cannot read a previous step.
    broken = _spec(final_instructions="x")
    broken.steps[0].input_source = InputSource.PREVIOUS_STEP
    issues = arm.check_authoring_contract(
        broken, template_attachment=None, case_attachments=()
    )
    assert issues and all(issue.code and issue.message for issue in issues)


def test_a_template_step_needs_a_named_attached_template(arm: ModuleType) -> None:
    spec = _spec(final_instructions="x")
    spec.steps[1].output_mode = OutputMode.TEMPLATE_FILL
    spec.steps[1].output_type = OutputType.DOCX
    assert "template_missing" in {
        i.code
        for i in arm.check_authoring_contract(
            spec, template_attachment=None, case_attachments=("mall.docx",)
        )
    }
    assert "template_fill_position" not in {
        i.code
        for i in arm.check_authoring_contract(
            spec, template_attachment="mall.docx", case_attachments=("mall.docx",)
        )
    }


def test_the_runtime_input_normalisation_is_the_builders_own(arm: ModuleType) -> None:
    """The gold step is persisted as a Builder step is: same function, same result."""

    spec = _spec(final_instructions="x")
    spec.steps[0].input_type = InputType.DOCUMENT
    origin = AIBuilderFlowAuthoringOrigin(
        session_id=uuid4(),
        plan_id=uuid4(),
        spec_hash="0" * 64,
        applied_at="2026-09-29T00:00:00+00:00",  # type: ignore[arg-type]
    )
    builder = AIBuilderAuthoringPolicy(origin).effective_spec(
        spec=spec, current_flow=None
    )
    ours = arm.normalize_like_builder(spec)
    assert [s.input_config for s in ours.steps] == [
        s.input_config for s in builder.steps
    ]
    assert ours.steps[0].input_config["runtime_input"]["enabled"] is True


# ------------------------------------------------------------ applying the spec


def test_the_command_has_a_package_origin_and_a_template_intent_for_the_last_step(
    arm: ModuleType,
) -> None:
    spec = _spec(final_instructions="x")
    gold = arm.GoldSpec("case-1", spec, "case-1.spec.json", "a" * 64, "mall.docx", {})
    template_id = uuid4()
    command = arm.build_create_command(
        arm.MaterializeRequest(
            space_id=uuid4(), gold=gold, spec=spec, template_file_id=template_id
        )
    )
    assert command.kind == "create"
    assert command.origin.kind == "flow_package"  # no Builder session is forged
    assert command.origin.content_checksum == f"sha256:{'a' * 64}"
    assert command.template_attachment_intent.file_id == template_id
    assert command.template_attachment_intent.terminal_plan_step_ref == "step_b"


class _RecordingService:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.error = error
        self.calls: list[dict[str, Any]] = []

    async def apply(self, **kwargs: Any) -> FlowAuthoringResult:
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return FlowAuthoringResult(
            flow_id=uuid4(),
            flow_name="Beslut",
            draft_revision=1,
            steps_created=2,
            steps_updated=0,
            steps_removed=0,
            command_spec_hash="h",
        )


def _materializer(
    arm: ModuleType,
    service: _RecordingService,
    *,
    persistence_start_error: Exception | None = None,
    persistence_scope: Any = None,
) -> Any:
    entered: list[str] = []

    @asynccontextmanager
    async def persistence() -> Any:
        if persistence_start_error is not None:
            raise persistence_start_error
        entered.append("start")
        try:
            yield
        finally:
            entered.append("stop")

    @asynccontextmanager
    async def scope() -> Any:
        entered.append("open")
        yield "session"
        entered.append("commit")

    async def container_factory(session: Any, user_id: Any) -> Any:
        assert session == "session"
        return SimpleNamespace(
            flow_service=lambda: "flow-service",
            flow_template_asset_service=lambda: "template-assets",
        )

    materializer = arm.InProcessSpecMaterializer(
        user_id=uuid4(),
        authoring_service=service,
        container_factory=container_factory,
        session_scope=scope,
        persistence=persistence_scope or persistence,
    )
    materializer.entered = entered
    return materializer


def _request(arm: ModuleType) -> Any:
    spec = _spec(final_instructions="x")
    return arm.MaterializeRequest(
        space_id=uuid4(),
        gold=arm.GoldSpec("case-1", spec, "f.json", "b" * 64, None, {}),
        spec=spec,
        template_file_id=None,
    )


def test_apply_runs_in_one_transaction_with_the_authoring_service(
    arm: ModuleType,
) -> None:
    service = _RecordingService()
    materializer = _materializer(arm, service)

    flow = materializer.materialize(_request(arm))

    assert flow.steps_created == 2 and flow.flow_name == "Beslut"
    call = service.calls[0]
    assert call["flow_service"] == "flow-service"
    assert call["template_asset_service"] == "template-assets"
    assert call["command"].origin.kind == "flow_package"
    assert type(call["origin_policy"]).__name__ == "NoopFlowAuthoringOriginPolicy"
    # Persistence is up before the transaction opens and down after it commits.
    assert materializer.entered == ["start", "open", "commit", "stop"]


def test_a_platform_refusal_is_an_outcome_and_anything_else_is_the_stacks(
    arm: ModuleType,
) -> None:
    from eneo.main.exceptions import BadRequestException

    refused = _materializer(
        arm, _RecordingService(error=BadRequestException("nej", code="bad_spec"))
    )
    with pytest.raises(arm.MaterializeRefused) as refusal:
        refused.materialize(_request(arm))
    assert refusal.value.code == "bad_spec"

    broken = _materializer(arm, _RecordingService(error=RuntimeError("db gone")))
    with pytest.raises(arm.MaterializeInfrastructureError, match="db gone"):
        broken.materialize(_request(arm))


def test_persistence_is_stopped_after_a_refused_or_a_broken_apply(
    arm: ModuleType,
) -> None:
    from eneo.main.exceptions import BadRequestException

    for error, outcome in (
        (BadRequestException("nej", code="bad_spec"), arm.MaterializeRefused),
        (RuntimeError("db gone"), arm.MaterializeInfrastructureError),
    ):
        materializer = _materializer(arm, _RecordingService(error=error))
        with pytest.raises(outcome):
            materializer.materialize(_request(arm))
        assert materializer.entered == ["start", "open", "stop"]


def test_persistence_that_cannot_start_is_the_stacks_fault_and_nothing_opens(
    arm: ModuleType,
) -> None:
    service = _RecordingService()
    materializer = _materializer(
        arm, service, persistence_start_error=RuntimeError("no object content")
    )
    with pytest.raises(arm.MaterializeInfrastructureError, match="no object content"):
        materializer.materialize(_request(arm))
    assert materializer.entered == [] and service.calls == []


def test_concurrent_applies_take_turns_with_the_process_singletons(
    arm: ModuleType,
) -> None:
    """The singletons refuse a second start, and observations run in threads."""

    guard = threading.Lock()
    running = 0
    peak = 0

    @asynccontextmanager
    async def persistence() -> Any:
        nonlocal running, peak
        with guard:
            running += 1
            peak = max(peak, running)
        try:
            await asyncio.sleep(0.02)
            yield
        finally:
            with guard:
                running -= 1

    materializer = _materializer(
        arm, _RecordingService(), persistence_scope=persistence
    )
    threads = [
        threading.Thread(target=materializer.materialize, args=(_request(arm),))
        for _ in range(4)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert peak == 1


def test_the_default_persistence_is_the_lifespans_own_start_and_stop(
    arm: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    import eneo.server.dependencies.lifespan as lifespan

    calls: list[str] = []

    async def start() -> None:
        calls.append("start")

    async def stop() -> None:
        calls.append("stop")

    monkeypatch.setattr(lifespan, "start_persistence", start)
    monkeypatch.setattr(lifespan, "stop_persistence", stop)

    async def apply(*, fail: bool) -> None:
        async with arm._process_persistence():
            calls.append("body")
            if fail:
                raise RuntimeError("boom")

    asyncio.run(apply(fail=False))
    assert calls == ["start", "body", "stop"]

    calls.clear()
    with pytest.raises(RuntimeError, match="boom"):
        asyncio.run(apply(fail=True))
    assert calls == ["start", "body", "stop"]


# -------------------------------------------------- one observation, end to end


class _Stack:
    """The API the harness talks to, with a fake provider behind the run.

    The provider answers with the input text followed by the terminal step's
    instructions: a flow that was told to state a fact states it.
    """

    def __init__(self, spec: FlowDraftSpecCore, *, input_text: str) -> None:
        self.spec = spec
        self.input_text = input_text
        self.calls: list[tuple[str, str]] = []
        self.deleted: list[str] = []

    def request_json(
        self, *, method: str, path: str, payload: Any = None, **_: Any
    ) -> dict[str, Any]:
        self.calls.append((method, path))
        if path == "/flows/flow-1/" and method == "GET":
            return {
                "id": "flow-1",
                "steps": [
                    {
                        "step_order": order,
                        "assistant_id": f"asst-{order}",
                        "user_description": step.name,
                        "input_source": step.input_source.value,
                        "input_type": step.input_type.value,
                        "output_mode": step.output_mode.value,
                        "output_type": step.output_type.value,
                        "review_policy": None,
                    }
                    for order, step in enumerate(self.spec.steps, start=1)
                ],
                "metadata_json": {
                    "form_schema": {
                        "fields": [
                            {"name": f.name} for f in self.spec.form_fields or []
                        ]
                    }
                },
            }
        if path.startswith("/flows/flow-1/assistants/"):
            order = int(path.rstrip("/").rsplit("-", 1)[1])
            step = self.spec.steps[order - 1]
            return {"prompt": {"text": step.assistant_spec.instructions}}
        if path == "/flows/flow-1/publish/":
            return {"id": "flow-1", "published_version": 1}
        if path == "/flows/flow-1/run-contract/":
            return {
                "published_flow_version": 1,
                "form_fields": [],
                "steps_requiring_input": [],
                "final_output": {"output_type": "text"},
            }
        if path == "/flows/flow-1/runs/" and method == "POST":
            return {"id": "run-1", "status": "queued"}
        if path == "/flows/flow-1/runs/run-1/":
            return {
                "id": "run-1",
                "status": "completed",
                "result": {
                    "kind": "inline_text",
                    "text": f"{self.input_text} {self.spec.steps[-1].assistant_spec.instructions}",
                },
            }
        if path == "/flows/flow-1/runs/run-1/evidence/":
            return {"run": {"id": "run-1", "status": "completed"}, "step_results": []}
        raise AssertionError((method, path))

    def request_no_content(self, *, method: str, path: str, **_: Any) -> None:
        self.calls.append((method, path))
        self.deleted.append(path)


class _Materializer:
    def __init__(self, arm: ModuleType, *, refusal: Exception | None = None) -> None:
        self.arm = arm
        self.refusal = refusal
        self.requests: list[Any] = []

    def materialize(self, request: Any) -> Any:
        self.requests.append(request)
        if self.refusal is not None:
            raise self.refusal
        return self.arm.MaterializedFlow("flow-1", "Beslut", len(request.spec.steps))


def _case(harness: ModuleType) -> Any:
    return harness.BattleCase(
        case_id="case-1",
        prompt="Skriv ett beslut i ärendet.",
        complexity="hard",
        domain="test",
        apply_plan=True,
        cohorts=("municipal",),
        expected={},
        execution=harness.CaseExecution(
            inputs=harness.ExecutionInputs(text="Ärende om bygglov."),
            checkpoints=(),
            expect=harness.OutputExpectation(
                output_kind="text",
                required_facts=(REQUIRED_FACT,),
                forbidden=(FORBIDDEN,),
            ),
        ),
    )


def _run(
    harness: ModuleType,
    arm: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    spec: FlowDraftSpecCore,
    refusal: Exception | None = None,
) -> tuple[dict[str, Any], _Stack, _Materializer]:
    specs = tmp_path / "specs"
    specs.mkdir()
    _freeze(specs, "case-1", spec)
    cases_file = tmp_path / "cases.json"
    cases_file.write_text("{}")
    stack = _Stack(spec, input_text="Ärende om bygglov.")
    materializer = _Materializer(arm, refusal=refusal)
    monkeypatch.setattr(harness, "_request_json", stack.request_json)
    monkeypatch.setattr(harness, "_request_no_content", stack.request_no_content)
    monkeypatch.setattr(
        harness,
        "_git_output",
        lambda *a: "c" * 40 if a[0] == "rev-parse" else "",
    )
    args = argparse.Namespace(
        arm="oracle",
        oracle_specs_dir=str(specs),
        oracle_materializer=materializer,
        space_id=str(uuid4()),
        timeout_seconds=1,
    )
    config = harness.ApiConfig(
        base_url="http://localhost:8123/api/v1", api_key="k", timeout_seconds=1
    )
    case = _case(harness)
    bundle = harness._observation_runner(args)(
        case=case,
        config=config,
        args=args,
        existing_session_id=None,
        artifact_output_dir=tmp_path,
        cases_path=cases_file,
        provisioned_fixtures={},
    )
    # What the suite adds around every arm's bundle before sealing it.
    bundle["case_contract"] = harness._case_contract_payload(case)
    bundle["case_contract_sha256"] = harness._case_contract_sha256(case)
    bundle["repetition"] = 1
    harness.seal_observation(bundle)
    return bundle, stack, materializer


def test_a_spec_that_states_the_fact_is_fulfilled_and_the_row_is_receipted(
    harness: ModuleType,
    arm: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    bundle, stack, materializer = _run(
        harness,
        arm,
        monkeypatch,
        tmp_path,
        spec=_spec(final_instructions=f"Avsluta med ärendenummer {REQUIRED_FACT}."),
    )
    observation = bundle["observation"]

    assert bundle["arm"] == "oracle" and bundle["plan"] is None
    assert observation["evidence_valid"] is True, observation["evidence_failed_checks"]
    assert observation["observation_status"] == "completed"
    assert observation["outcome_class"] == "oracle_spec_applied"
    assert observation["output_executed"] is True
    assert observation["output_success"] is True
    assert observation["expectation_verdict"] == "pass"
    # The scorer states each dimension: the platform accepted the spec (plan),
    # no edit review was asked for, and the output passed.
    assert observation["verdict_states"] == {
        "plan": "pass",
        "review_edit": "not_required",
        "output": "pass",
        "case": "pass",
    }
    # No Builder, and the flow is deleted the way an applied Builder flow is.
    assert not any("ai-builder" in path for _, path in stack.calls)
    assert stack.deleted == ["/flows/flow-1/"]
    # The spec reached the platform normalised as the Builder's policy does.
    assert materializer.requests[0].spec.steps[0].input_config is None
    assert bundle["oracle"]["persisted_matches_spec"] == {
        "passed": True,
        "mismatches": [],
    }

    # The row is one the receipt reader parses: the arms are comparable.
    from ai_builder_receipt import observation_from_row

    row = {**observation, "bundle_file": "b.json", "bundle_sha256": "d" * 64}
    parsed = observation_from_row(row, where="row")
    assert (parsed.output_executed, parsed.output_success) == (True, True)


def test_a_spec_that_omits_the_fact_is_executed_and_not_fulfilled(
    harness: ModuleType,
    arm: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    bundle, _, _ = _run(
        harness,
        arm,
        monkeypatch,
        tmp_path,
        spec=_spec(final_instructions="Skriv beslutet."),
    )
    observation = bundle["observation"]
    assert observation["output_executed"] is True
    assert observation["output_success"] is False
    # The flow was accepted; what failed is the delivered output, stated apart.
    assert observation["expectation_verdict"] == "pass"
    assert observation["output_failed_checks"] == ["required_fact"]
    assert observation["verdict_states"]["plan"] == "pass"
    assert observation["verdict_states"]["output"] == "fail"
    assert observation["output_required_facts"] == {REQUIRED_FACT: False}
    assert observation["evidence_valid"] is True  # a real result, not a bad instrument


def test_a_spec_the_platform_refuses_is_attempted_not_executed_and_valid_evidence(
    harness: ModuleType,
    arm: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    bundle, stack, _ = _run(
        harness,
        arm,
        monkeypatch,
        tmp_path,
        spec=_spec(final_instructions="x"),
        refusal=_refused(arm),
    )
    observation = bundle["observation"]
    assert observation["outcome_class"] == "oracle_spec_rejected"
    # The platform refused the spec: plan fails, and there is no output to judge.
    assert observation["verdict_states"]["plan"] == "fail"
    assert observation["verdict_states"]["output"] == "unmeasured"
    assert observation["verdict_states"]["case"] == "fail"
    assert observation["output_executed"] is False
    assert observation["output_success"] is None
    assert observation["expectation_verdict"] == "fail"
    assert observation["evidence_valid"] is True
    assert bundle["oracle"]["refusal"]["code"] == "flow_name_taken"
    assert stack.deleted == []  # nothing was created, so nothing is deleted


def _refused(arm: ModuleType) -> Exception:
    return arm.MaterializeRefused(code="flow_name_taken", message="taken")


def test_a_persisted_flow_that_differs_from_the_spec_is_invalid_evidence(
    harness: ModuleType,
    arm: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    spec = _spec(final_instructions=f"Ange {REQUIRED_FACT}.")
    stack = _Stack(spec, input_text="x")
    snapshot_flow = stack.request_json(method="GET", path="/flows/flow-1/")
    snapshot_flow["steps"][1]["output_mode"] = "compose_text"
    snapshot = {
        "flow": snapshot_flow,
        "assistants": {
            "asst-1": {"prompt": {"text": "Läs ärendet noga."}},
            "asst-2": {"prompt": {"text": "Ange en annan text."}},
        },
    }
    verdict = arm.persisted_matches_spec(snapshot, spec)
    assert verdict["passed"] is False
    assert "step 2 output_mode" in verdict["mismatches"]
    assert "step 2 instructions" in verdict["mismatches"]

    bundle, _, _ = _run(
        harness,
        arm,
        monkeypatch,
        tmp_path,
        spec=spec,
    )
    bundle["oracle"]["persisted_matches_spec"] = verdict
    report = arm.oracle_evidence_report(harness, bundle)
    assert report["valid"] is False
    assert [c["name"] for c in report["failed_checks"]] == [
        "oracle_persisted_flow_matches_spec"
    ]


def test_the_arms_output_verdict_is_the_quality_reports_on_the_same_evidence(
    harness: ModuleType,
    arm: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """One scorer: were `_quality_report` to change how a run is judged, or the
    arm to stop calling the same functions, this equality would break."""

    bundle, _, _ = _run(
        harness,
        arm,
        monkeypatch,
        tmp_path,
        spec=_spec(final_instructions=f"Ange {REQUIRED_FACT}. Nämn {FORBIDDEN}."),
    )
    case = _case(harness)
    reference = harness._quality_report(
        plan=None,
        summary={},
        expected=case.expected or {},
        runtime_evidence=bundle["runtime_evidence"],
        output_expectation=case.execution.expect,
    )
    ours = bundle["quality_report"]
    assert ours["output_checks"] == reference["output_checks"]
    assert ours["output_success"] is reference["output_success"] is False


# --------------------------------------------------------------- the CLI surface


def _parse(harness: ModuleType, monkeypatch: pytest.MonkeyPatch, *argv: str) -> Any:
    monkeypatch.setattr(sys, "argv", ["harness", *argv])
    return harness._parse_args()


def test_the_builder_arm_is_the_default_and_keeps_its_run_context(
    harness: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    args = _parse(harness, monkeypatch, "--space-id", "s")
    assert args.arm == "builder" and args.oracle_specs_dir is None
    context = harness._suite_run_context(args)
    assert "arm" not in context and "oracle_manifest_sha256" not in context
    assert context == harness._builder_suite_run_context(args)


def test_arm_oracle_refuses_what_only_a_builder_run_uses(
    harness: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    with pytest.raises(ValueError, match="requires --oracle-specs-dir"):
        harness._validate_arm_args(
            _parse(harness, monkeypatch, "--arm", "oracle", "--space-id", "s")
        )
    args = _parse(
        harness,
        monkeypatch,
        "--arm",
        "oracle",
        "--oracle-specs-dir",
        "d",
        "--model-id",
        "m",
        "--run-suite",
    )
    with pytest.raises(ValueError, match=r"--run-suite, --model-id"):
        harness._validate_arm_args(args)
    with pytest.raises(ValueError, match="belongs to --arm oracle"):
        harness._validate_arm_args(
            _parse(harness, monkeypatch, "--oracle-specs-dir", "d")
        )


# ------------------------------------------------------------- the comparator


def _summary(arm: str, model: str | None) -> dict[str, Any]:
    return {
        "evaluator_identity": {
            "question_relevance_semantics_version": 3,
            "outcome_classification_semantics_version": 6,
            "observation_input_identity_semantics_version": 4,
            "requested_model_id": model,
            "harness_sha256": "h" * 64,
            "run_context": {
                **({"arm": arm} if arm != "builder" else {}),
                "auto_confirm_requirements": True,
                "confirm_message_sha256": "c" * 64,
                "max_concurrency": 4,
                "max_concurrent_observations_per_case": 1,
                "flow_isolation_semantics_version": 1,
                "ui_language": "sv",
            },
        }
    }


def test_the_comparator_lets_an_oracle_receipt_meet_a_builder_receipt() -> None:
    compare = _load("ai_builder_battle_compare", "ai_builder_battle_compare.py")
    builder = _summary("builder", "model-luna6")
    oracle = _summary("oracle", None)

    assert compare._incompatible_identity_fields(builder, oracle) == []
    assert compare._incompatible_identity_fields(oracle, oracle) == []
    # Two Builder receipts still need the same Builder model, as ever...
    assert compare._incompatible_identity_fields(
        builder, _summary("builder", "model-other")
    ) == ["requested_model_id"]
    # ...and the scorer is never waived: an oracle receipt from another harness
    # is a different experiment.
    other_scorer = _summary("oracle", None)
    other_scorer["evaluator_identity"]["harness_sha256"] = "x" * 64
    assert compare._incompatible_identity_fields(builder, other_scorer) == [
        "harness_sha256"
    ]
    assert (
        compare._OUTCOME_RANK["oracle_spec_applied"]
        > compare._OUTCOME_RANK["oracle_spec_rejected"]
    )


# ----------------------------------------------- a whole suite, then the totals


def _verified_target(config: Any, *, expected_source_revision: str) -> dict[str, Any]:
    """What `GET /version` verification records, for an API running the local tree."""
    return {
        "api_base_url": config.base_url,
        "version": f"DEV-{expected_source_revision[:12]}",
        "expected_app_version": f"DEV-{expected_source_revision[:12]}",
        "expected_source_revision": expected_source_revision,
        "verified": True,
        "sha256": "e" * 64,
    }


def test_a_suite_of_the_oracle_arm_is_receipted_and_totalled_like_any_other(
    harness: ModuleType,
    arm: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """`_run_suite` runs the arm, seals every bundle, writes a complete receipt,
    and the totals report reads that receipt without any special case."""

    specs = tmp_path / "specs"
    specs.mkdir()
    spec = _spec(final_instructions=f"Avsluta med ärendenummer {REQUIRED_FACT}.")
    _freeze(specs, "case-1", spec)
    stack = _Stack(spec, input_text="Ärende om bygglov.")

    def request_json(*, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        if path.startswith("/flows/?space_id="):
            return {"items": [], "count": 0, "has_more": False}
        if path == "/flows/runs/capacity/":
            return {"max_concurrent_runs": 4, "active_runs": 0}
        return stack.request_json(method=method, path=path, **kwargs)

    monkeypatch.setattr(harness, "_request_json", request_json)
    monkeypatch.setattr(harness, "_request_no_content", stack.request_no_content)
    monkeypatch.setattr(
        harness, "_git_output", lambda *a: "c" * 40 if a[0] == "rev-parse" else ""
    )
    monkeypatch.setattr(harness, "_target_runtime_identity", _verified_target)
    args = argparse.Namespace(
        arm="oracle",
        oracle_specs_dir=str(specs),
        oracle_materializer=_Materializer(arm),
        space_id=str(uuid4()),
        timeout_seconds=1,
        repetitions=2,
        concurrency=1,
        model_id=None,
        ui_language="sv",
        auto_confirm_requirements=True,
        observation_deadline_seconds=None,
    )

    exit_code = harness._run_suite(
        cases=[_case(harness)],
        config=harness.ApiConfig(
            base_url="http://localhost:8123/api/v1", api_key="k", timeout_seconds=1
        ),
        args=args,
        output_dir=tmp_path / "out",
    )

    suite_dir = next((tmp_path / "out").glob("ai-builder-api-battle-suite-*"))
    summary = json.loads((suite_dir / "suite-summary.json").read_text())
    assert exit_code == 0
    assert summary["receipt_integrity"]["status"] == "complete"
    # The deployed revision was verified before the first case and again at the end.
    target = summary["release_identity"]["target"]
    assert target["verified"] is True and target["version"] == f"DEV-{'c' * 12}"
    assert summary["suite_identity_failed_check_count"] == 0
    assert summary["evaluator_identity"]["run_context"]["arm"] == "oracle"
    assert summary["evaluator_identity"]["requested_model_id"] is None
    assert [
        (r["repetition"], r["observation_status"], r["output_success"])
        for r in summary["results"]
    ] == [(1, "completed", True), (2, "completed", True)]

    # The same receipt, read by the receipt reader and by the totals report.
    from ai_builder_receipt import load_summary_receipt

    receipt = load_summary_receipt(suite_dir / "suite-summary.json")
    assert [o.output_success for o in receipt.observations] == [True, True]

    totals = _load("ai_builder_oracle_totals", "ai_builder_oracle_totals.py")
    selection = tmp_path / "selection.json"
    selection.write_text(
        json.dumps(
            {
                "repetitions": 2,
                "cases": [
                    {
                        "id": "case-1",
                        "held_out": True,
                        "f18": False,
                        "edit_target": False,
                    }
                ],
            }
        )
    )
    freeze = tmp_path / "freeze.json"
    freeze.write_text(
        json.dumps({key: "x" for key in totals.REQUIRED_FREEZE_KEYS} | {"legs": {}})
    )
    result = totals.report(
        argparse.Namespace(
            selection=str(selection),
            freeze=str(freeze),
            leg=[f"O_luna6:oracle:gpt-6-luna={suite_dir}"],
            audit=None,
        )
    )
    assert result["totals"]["O_luna6"]["attempted"] == 2
    assert result["totals"]["O_luna6"]["fulfilled"] == 2
    assert result["per_case"]["O_luna6"] == {"case-1": "PP"}
    # One synthetic leg is not the frozen experiment: totals, no decision.
    assert result["decision"]["outcome"] == "NO_DECISION"
    # The totals read that receipt through the receipt reader's integrity checks
    # (`verified_receipt`); a real receipt passes them, and a bundle altered
    # afterwards is a refused receipt, not a leg read from raw JSON.
    assert len(totals.verified_receipt(suite_dir).observations) == 2
    bundle = next(suite_dir.glob("ai-builder-api-battle-test-*-r01.json"))
    bundle.write_text(bundle.read_text() + " ")
    refused = totals.parse_leg(f"O_luna6:oracle:gpt-6-luna={suite_dir}")
    assert refused.integrity_error and "sha256_mismatch" in refused.integrity_error
    assert refused.rows == ()
    # The oracle arm read the answers up front, and the receipt says so.
    context = summary["evaluator_identity"]["run_context"]
    assert context["intake_answers"] == "upfront"
    assert list(context["intake_answers_sha256_by_id"]) == ["case-1"]


# ------------------------------------------------------- the authoring commands


def _corpus(tmp_path: Path) -> Path:
    path = tmp_path / "cases.json"
    path.write_text(
        json.dumps(
            {
                "cases": [
                    {
                        "id": "case-1",
                        "attachments": ["mall.docx"],
                        "expected": {"never": "read"},
                        "execution": {"expect": {"required_facts": ["never read"]}},
                    }
                ]
            }
        )
    )
    return path


def test_check_and_freeze_read_only_a_cases_attachments(
    arm: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    corpus = _corpus(tmp_path)
    specs = tmp_path / "specs"
    specs.mkdir()
    spec = _spec(final_instructions="Skriv beslutet.")
    (specs / "case-1.spec.json").write_bytes(spec.model_dump_json().encode())

    # A spec that names no template but the case needs none: clean.
    assert (
        arm.main(
            [
                "check",
                "--cases-file",
                str(corpus),
                "--case-id",
                "case-1",
                "--spec",
                str(specs / "case-1.spec.json"),
            ]
        )
        == 0
    )
    # A template the request never attached is refused, with its code.
    assert (
        arm.main(
            [
                "check",
                "--cases-file",
                str(corpus),
                "--case-id",
                "case-1",
                "--spec",
                str(specs / "case-1.spec.json"),
                "--template",
                "annat.docx",
            ]
        )
        == 1
    )
    assert "template_not_attached" in capsys.readouterr().out

    (specs / "authoring.json").write_text(
        json.dumps(
            {
                "model": "test-author",
                "material_manifest_sha256": "m" * 64,
                "docs_manifest_sha256": "d" * 64,
                "cases": {
                    "case-1": {
                        "template_attachment": None,
                        "transcript_sha256": "t" * 64,
                    }
                },
            }
        )
    )
    selection = tmp_path / "selection.json"
    selection.write_text(json.dumps({"cases": [{"id": "case-1"}]}))
    assert (
        arm.main(
            [
                "freeze",
                "--cases-file",
                str(corpus),
                "--selection",
                str(selection),
                "--dir",
                str(specs),
            ]
        )
        == 0
    )

    gold = arm.load_gold_spec(specs, "case-1")
    assert gold.authoring["model"] == "test-author"
    assert (
        gold.spec_file_sha256
        == hashlib.sha256((specs / "case-1.spec.json").read_bytes()).hexdigest()
    )
    # Frozen means once: a second freeze never overwrites the manifest.
    with pytest.raises(FileExistsError):
        arm.freeze_manifest(cases_file=corpus, specs_dir=specs, case_ids=["case-1"])


# ----------------------------------------------------- equal information (intake)


_ANSWERS = {
    "terminal_output": {"selected_option_id": "docx_document"},
    "runtime_metadata_field_details": {
        "input_fields": [
            {
                "value": {
                    "name": "diarienummer",
                    "label": "Diarienummer",
                    "type": "text",
                    "required": True,
                    "options": [],
                }
            }
        ]
    },
}


def _intake_case(harness: ModuleType, *, edit: Any = None) -> Any:
    return harness.BattleCase(
        case_id="case-1",
        prompt="Skriv ett beslut i ärendet.",
        configured_question_answers=_ANSWERS,
        edit=edit,
    )


def test_the_builder_arm_asks_by_default_and_gets_the_answers_up_front_on_request(
    harness: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = _intake_case(harness)
    asked = _parse(harness, monkeypatch, "--space-id", "s")
    upfront = _parse(
        harness, monkeypatch, "--space-id", "s", "--intake-answers", "upfront"
    )

    # Every receipt before the experiment: the message is the prompt, byte for byte.
    assert harness._first_message(case, asked) == case.prompt
    assert harness._intake_run_context(asked, [case]) == {}

    message = harness._first_message(case, upfront)
    assert message.startswith(case.prompt + "\n\n")
    assert (
        "DOCX-dokument" in message and "`diarienummer` (text, obligatoriskt)" in message
    )
    # A saved-flow edit is a chat turn, not an intake.
    assert (
        harness._first_message(_intake_case(harness, edit=object()), upfront)
        == case.prompt
    )
    context = harness._intake_run_context(upfront, [case])
    assert context["intake_answers"] == "upfront"
    assert context["intake_answers_sha256_by_id"] == {
        "case-1": hashlib.sha256(message.encode()).hexdigest()
    }


def test_the_first_message_a_builder_session_sends_is_that_message(
    harness: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    sent: list[str] = []

    def stop(**kwargs: Any) -> Any:
        sent.append(kwargs["message"])
        raise RuntimeError("stop after the first message")

    monkeypatch.setattr(harness, "_create_session", lambda **_: {"session_id": "s1"})
    monkeypatch.setattr(harness, "_request_json", lambda **_: {})
    monkeypatch.setattr(harness, "_send_and_fetch", stop)
    case = _intake_case(harness)
    args = _parse(
        harness, monkeypatch, "--space-id", "s", "--intake-answers", "upfront"
    )
    args.file_ids = None
    with pytest.raises(RuntimeError, match="stop after"):
        harness._run_case_session(
            case=case,
            config=harness.ApiConfig(
                base_url="http://x/api/v1", api_key="k", timeout_seconds=1
            ),
            args=args,
            existing_session_id=None,
            artifact_output_dir=tmp_path,
            cases_path=None,
            provisioned_fixtures={},
            seeded_flow=None,
        )
    assert sent == [harness.intake_message(case.prompt, _ANSWERS)]


def test_the_oracle_arm_always_reads_the_answers_up_front(
    harness: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    oracle = _parse(harness, monkeypatch, "--arm", "oracle", "--oracle-specs-dir", "d")
    assert harness._intake_mode(oracle) == "upfront"
    asked = _parse(
        harness,
        monkeypatch,
        "--arm",
        "oracle",
        "--oracle-specs-dir",
        "d",
        "--intake-answers",
        "asked",
    )
    with pytest.raises(ValueError, match="less than its author had"):
        harness._validate_arm_args(asked)


def test_the_author_reads_exactly_the_text_the_builder_receives(
    harness: ModuleType, tmp_path: Path
) -> None:
    stage = _load("ai_builder_oracle_stage", "ai_builder_oracle_stage.py")
    attachment = next(p.name for p in stage.FIXTURES.iterdir() if p.suffix == ".docx")
    case = dataclasses.replace(_intake_case(harness), attachments=(attachment,))
    manifest = stage.stage_case(stage.request_material(case), tmp_path)
    request = (tmp_path / "case-1" / "request.md").read_text()
    answers = (tmp_path / "case-1" / "answers.md").read_text()
    upfront = argparse.Namespace(arm="builder", intake_answers="upfront")

    assert request + "\n\n" + answers == harness._first_message(case, upfront)
    assert (
        manifest["intake_message_sha256"]
        == hashlib.sha256(harness._first_message(case, upfront).encode()).hexdigest()
    )
    # A case with no answers is sent its prompt alone, and stages an empty answers.md.
    bare = dataclasses.replace(case, configured_question_answers={})
    stage.stage_case(stage.request_material(bare), tmp_path / "bare")
    assert (tmp_path / "bare" / "case-1" / "answers.md").read_text() == ""
    assert harness._first_message(bare, upfront) == bare.prompt


def _upfront(
    arm: str, model: str | None, digests: dict[str, str] | None
) -> dict[str, Any]:
    summary = _summary(arm, model)
    identity = summary["evaluator_identity"]
    identity["case_contract_sha256_by_id"] = {"c": "k" * 64, "d": "k" * 64}
    identity["run_context"]["intake_answers"] = "upfront"
    if digests is not None:
        identity["run_context"]["intake_answers_sha256_by_id"] = digests
    return summary


def test_the_comparator_refuses_arms_that_were_told_different_things() -> None:
    compare = _load("ai_builder_battle_compare", "ai_builder_battle_compare.py")
    both = {"c": "a" * 64, "d": "b" * 64}
    upfront = _upfront("oracle", None, both)
    asked = _summary("builder", "model-luna6")  # a receipt that says nothing: asked
    assert compare._incompatible_identity_fields(asked, upfront) == [
        "run_context.intake_answers"
    ]
    assert (
        compare._incompatible_identity_fields(
            _upfront("builder", "model-luna6", both), upfront
        )
        == []
    )
    # Different text for a shared case.
    assert compare._incompatible_identity_fields(
        _upfront("builder", "model-luna6", {**both, "d": "0" * 64}), upfront
    ) == ["run_context.intake_answers_sha256_by_id"]


def test_in_upfront_mode_each_receipt_must_carry_a_digest_for_every_shared_case() -> (
    None
):
    """Missing is not equal: a receipt that omits a digest is not comparable."""

    compare = _load("ai_builder_battle_compare", "ai_builder_battle_compare.py")
    both = {"c": "a" * 64, "d": "b" * 64}
    upfront = _upfront("oracle", None, both)
    field = ["run_context.intake_answers_sha256_by_id"]
    for missing in (None, {}, {"c": "a" * 64}):
        broken = _upfront("builder", "model-luna6", missing)
        assert compare._incompatible_identity_fields(broken, upfront) == field
        assert compare._incompatible_identity_fields(upfront, broken) == field
    # A case only one receipt ran is not shared, so it needs no digest from the other.
    narrow = _upfront("builder", "model-luna6", {"c": "a" * 64})
    narrow["evaluator_identity"]["case_contract_sha256_by_id"] = {"c": "k" * 64}
    assert compare._incompatible_identity_fields(narrow, upfront) == []


def test_arm_o_scores_the_review_edit_delivery_check_through_the_same_function(
    harness: ModuleType,
    arm: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    case = dataclasses.replace(
        _case(harness), expected={"expected_review_policy": {"mode": "edit"}}
    )
    evidence = {
        "execution": {"outcome": "completed", "failures": [], "checkpoints": []},
        "run": {"result": {"kind": "inline_text", "text": TEXT_FACT}},
        "run_contract": {"final_output": {"output_type": "text"}},
        "final_artifact": None,
    }
    reference = harness._quality_report(
        plan=None,
        summary={},
        expected=case.expected,
        runtime_evidence=evidence,
        output_expectation=case.execution.expect,
    )
    checks, output = arm._scored_checks(harness, case, evidence)
    named = [
        c for c in reference["checks"] if c["name"] == "review_edit_reaches_delivery"
    ]
    assert (
        named
        and [c for c in checks if c["name"] == "review_edit_reaches_delivery"] == named
    )
    assert output["output_checks"] == reference["output_checks"]


TEXT_FACT = f"Ärendenummer {REQUIRED_FACT}."


# ------------------------------------------------------- the deployed revision


def test_a_leg_that_cannot_verify_its_deployed_revision_never_starts(
    harness: ModuleType,
    arm: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        harness,
        "_target_runtime_identity",
        lambda config, *, expected_source_revision: {"verified": False},
    )
    monkeypatch.setattr(
        harness, "_git_output", lambda *a: "c" * 40 if a[0] == "rev-parse" else ""
    )
    monkeypatch.setattr(
        harness, "_request_json", lambda **kw: calls.append(kw["path"]) or {}
    )
    args = argparse.Namespace(
        arm="oracle",
        oracle_specs_dir=str(tmp_path),
        space_id="s",
        timeout_seconds=1,
        repetitions=1,
        concurrency=1,
        model_id=None,
    )
    (tmp_path / "manifest.json").write_text(
        json.dumps({"schema_version": 1, "cases": {"case-1": {}}})
    )
    with pytest.raises(ValueError, match="does not match the local source revision"):
        harness._run_suite(
            cases=[_case(harness)],
            config=harness.ApiConfig(
                base_url="http://x/api/v1", api_key="k", timeout_seconds=1
            ),
            args=args,
            output_dir=tmp_path / "out",
        )
    assert calls == []  # not one request after the failed verification
    assert (
        not list((tmp_path / "out").glob("*")) if (tmp_path / "out").exists() else True
    )


@pytest.mark.parametrize(
    "arguments, must_refuse",
    [
        ({"arm": "oracle"}, True),  # an oracle leg always verifies its target
        ({"arm": "builder", "verify_target": True}, True),  # so does a marked A leg
        ({"arm": "builder"}, False),  # an exploratory Builder run may be dirty
    ],
)
def test_a_leg_that_verifies_its_deployed_revision_needs_a_clean_tracked_source(
    harness: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    arguments: dict[str, Any],
    must_refuse: bool,
) -> None:
    """Commit gate round 3, P1(b): the case-id suite path supplies no acquisition
    contract, so it did not require a clean source; a leg that names the revision
    it ran against must be a run of that revision's bytes."""

    monkeypatch.setattr(
        harness,
        "_git_output",
        lambda *a: "c" * 40 if a[0] == "rev-parse" else " M backend/x.py",
    )
    monkeypatch.setattr(harness, "_target_runtime_identity", _verified_target)
    calls: list[str] = []
    monkeypatch.setattr(
        harness, "_request_json", lambda **kw: calls.append(kw["path"]) or {}
    )
    (tmp_path / "manifest.json").write_text(
        json.dumps({"schema_version": 1, "cases": {"case-1": {}}})
    )
    args = argparse.Namespace(
        oracle_specs_dir=str(tmp_path),
        space_id="s",
        timeout_seconds=1,
        repetitions=1,
        concurrency=1,
        model_id=None,
        **arguments,
    )
    run = lambda: harness._run_suite(  # noqa: E731
        cases=[_case(harness)],
        config=harness.ApiConfig(
            base_url="http://x/api/v1", api_key="k", timeout_seconds=1
        ),
        args=args,
        output_dir=tmp_path / "out",
    )

    if must_refuse:
        with pytest.raises(ValueError, match="requires a clean tracked source"):
            run()
        assert calls == []  # not one request against the stack
    else:
        try:
            run()
        except Exception as error:  # noqa: BLE001 - it fails later, on the fake stack
            assert "clean tracked source" not in str(error)


@pytest.mark.parametrize(
    "arguments, must_refuse",
    [
        ({"arm": "oracle"}, True),
        ({"arm": "builder", "verify_target": True}, True),
        ({"arm": "builder"}, False),
    ],
)
def test_a_leg_that_verifies_its_target_must_run_its_own_trees_code(
    harness: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    arguments: dict[str, Any],
    must_refuse: bool,
) -> None:
    """Commit gate round 5: the revision and the cleanliness a leg records are the
    harness's own tree's; Python imports `eneo` from wherever `sys.path` points,
    so code from another checkout would run under this tree's revision."""

    identity = importlib.import_module("ai_builder_code_identity")
    foreign = (
        tmp_path / "another-checkout" / "backend" / "src" / "eneo" / "flows" / "q.py"
    )
    real = identity.loaded_code
    monkeypatch.setattr(
        identity, "loaded_code", lambda: [*real(), ("eneo.flows.q", foreign)]
    )
    monkeypatch.setattr(
        harness, "_git_output", lambda *a: "c" * 40 if a[0] == "rev-parse" else ""
    )
    monkeypatch.setattr(harness, "_target_runtime_identity", _verified_target)
    calls: list[str] = []
    monkeypatch.setattr(
        harness, "_request_json", lambda **kw: calls.append(kw["path"]) or {}
    )
    (tmp_path / "manifest.json").write_text(
        json.dumps({"schema_version": 1, "cases": {"case-1": {}}})
    )
    args = argparse.Namespace(
        oracle_specs_dir=str(tmp_path),
        space_id="s",
        timeout_seconds=1,
        repetitions=1,
        concurrency=1,
        model_id=None,
        **arguments,
    )

    def run() -> int:
        return harness._run_suite(
            cases=[_case(harness)],
            config=harness.ApiConfig(
                base_url="http://x/api/v1", api_key="k", timeout_seconds=1
            ),
            args=args,
            output_dir=tmp_path / "out",
        )

    if must_refuse:
        with pytest.raises(ValueError, match="another checkout") as info:
            run()
        assert str(foreign) in str(info.value)
        assert calls == []  # not one request against the stack
    else:
        try:
            run()
        except Exception as error:  # noqa: BLE001 - it fails later, on the fake stack
            assert "another checkout" not in str(error)


def test_a_leg_refuses_a_first_party_script_preloaded_from_elsewhere_by_name(
    harness: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Commit gate round 6: `ai_builder_oracle_arm` is imported by module name; a
    copy already loaded from a site-packages-like path is foreign whatever its
    path looks like."""

    from types import ModuleType

    fake = ModuleType("ai_builder_oracle_arm")
    foreign = tmp_path / "site-packages" / "ai_builder_oracle_arm.py"
    fake.__file__ = str(foreign)
    monkeypatch.setitem(sys.modules, "ai_builder_oracle_arm", fake)
    calls: list[str] = []
    monkeypatch.setattr(
        harness, "_request_json", lambda **kw: calls.append(kw["path"]) or {}
    )
    args = argparse.Namespace(
        arm="oracle",
        oracle_specs_dir=str(tmp_path),
        space_id="s",
        timeout_seconds=1,
        repetitions=1,
        concurrency=1,
        model_id=None,
    )

    with pytest.raises(ValueError, match="another checkout") as info:
        harness._run_suite(
            cases=[_case(harness)],
            config=harness.ApiConfig(
                base_url="http://x/api/v1", api_key="k", timeout_seconds=1
            ),
            args=args,
            output_dir=tmp_path / "out",
        )

    assert str(foreign) in str(info.value)
    assert calls == []


def test_verifying_the_target_is_opt_in_for_a_builder_run_and_always_on_for_the_oracle(
    harness: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert (
        harness._verify_target(_parse(harness, monkeypatch, "--space-id", "s")) is False
    )
    assert (
        harness._verify_target(
            _parse(harness, monkeypatch, "--space-id", "s", "--verify-target")
        )
        is True
    )
    oracle = _parse(harness, monkeypatch, "--arm", "oracle", "--oracle-specs-dir", "d")
    assert harness._verify_target(oracle) is True


def test_every_case_including_an_edit_has_an_intake_digest_of_what_it_is_sent(
    harness: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    upfront = _parse(
        harness, monkeypatch, "--space-id", "s", "--intake-answers", "upfront"
    )
    create = _intake_case(harness)
    edit = dataclasses.replace(_intake_case(harness, edit=object()), case_id="case-2")
    digests = harness._intake_run_context(upfront, [create, edit])[
        "intake_answers_sha256_by_id"
    ]
    assert (
        digests["case-1"]
        == hashlib.sha256(harness._first_message(create, upfront).encode()).hexdigest()
    )
    # An edit is sent its prompt, and its digest says so.
    assert digests["case-2"] == hashlib.sha256(edit.prompt.encode()).hexdigest()

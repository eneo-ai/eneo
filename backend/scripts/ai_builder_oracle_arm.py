"""Arm O of the oracle experiment: expert gold specs, applied with no Builder.

The question the experiment asks is whether today's low end-to-end numbers come
from the Builder, from the delivery path (contracts, runtime, scorer) or from
the runtime model. Arm A is the Builder journey. Arm O answers with the same
fixtures, the same run and the same scoring, but the flow is authored by an
expert who never sees the case's oracle and is applied through
`FlowAuthoringCommandService`, the service the Builder's own apply uses.

This module is a sibling of `ai_builder_api_battle_test.py`, not a second
harness: the harness hands itself to `run_oracle_case`, so publish, run, review
checkpoints, output reading and scoring are the harness's own functions, and
the bundle is sealed, hashed and receipted by the harness's own code. Nothing
here computes a verdict. What is new is only:

  * the frozen spec set (`manifest.json` + one `<case>.spec.json` per case),
  * an authoring-contract check that never looks at the case's expectations,
  * the create step (a `SpecMaterializer`; production applies the command in
    process against the stack's database),
  * the arm's own evidence report, because no planner or classifier evidence
    exists to recompute.

Differences from the Builder's apply, all listed in the protocol
(`specs/protocol-oracle-2026-09-29.md`, section 6): the origin kind is
`flow_package` (the only non-Builder origin) and no Builder metadata is
stamped; the runtime-input normalisation the Builder's policy applies is
applied here by the same function; a step's model is the space default (the
arm fixes it), so specs may not name a model or a knowledge source.
"""

from __future__ import annotations

import asyncio
import functools
import hashlib
import importlib
import json
import threading
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping, Sequence
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any, Protocol, cast
from urllib.error import URLError
from uuid import UUID, uuid4

from eneo.flows.application.flow_authoring_command import (
    CreateFlowAuthoringCommand,
    FlowAuthoringCommandService,
    FlowPackageAuthoringOrigin,
    TemplateAttachmentIntent,
)
from eneo.flows.application.flow_authoring_origin_policy import (
    NoopFlowAuthoringOriginPolicy,
)
from eneo.flows.application.flow_draft_materialization import (
    FlowDraftCompiledStep,
    compile_flow_draft_changeset,
)
from eneo.flows.application.flow_draft_materialization_executor import (
    build_flow_steps,
)
from eneo.flows.application.flow_template_attachment_materialization import (
    approved_template_placeholders,
    attach_template_asset,
    require_template_placeholder_contract,
)
from eneo.flows.domain.flow_step_validation import (
    flow_step_validation_views_from_flow_steps,
)
from eneo.flows.domain.step_config import clean_inactive_step_config
from eneo.flows.enums import FlowAuthoringOutputMode
from eneo.flows.flow_authoring_name import normalize_flow_name
from eneo.flows.flow_authoring_runtime_input import resolve_runtime_input_config
from eneo.flows.flow_authoring_spec import FlowDraftSpecCore
from eneo.flows.flow_metadata import (
    normalize_flow_metadata_for_write,
    normalize_persisted_flow_metadata,
)
from eneo.flows.flow_validators import collect_step_graph_issues
from eneo.flows.flow_validators_form import (
    validate_variable_alias_collisions_for_step_graph,
)
from eneo.flows.flow_validators_template import validate_template_placeholder_bindings
from eneo.flows.input_binding_contract_rules import InputBindingContractError
from eneo.flows.runtime.docx_template_runtime import docx_template_placeholder_names
from eneo.main.exceptions import (
    BadRequestException,
    ConflictException,
    NameCollisionException,
    NotFoundException,
    UnauthorizedException,
    ValidationException,
)

JsonObject = dict[str, Any]

ORACLE_SPEC_SCHEMA_VERSION = 1
MANIFEST_FILE = "manifest.json"
HARNESS_MODULE = "ai_builder_api_battle_test"
# What the bundle says happened, in the vocabulary the receipt reads. A spec
# the platform refused is an outcome of the arm (the contract said no to an
# expert), not a fault of the instrument.
OUTCOME_APPLIED = "oracle_spec_applied"
OUTCOME_REJECTED = "oracle_spec_rejected"

_REFUSING_EXCEPTIONS: tuple[type[Exception], ...] = (
    BadRequestException,
    ConflictException,
    NameCollisionException,
    NotFoundException,
    UnauthorizedException,
    ValidationException,
)


# --------------------------------------------------------------------------
# The frozen spec set


@dataclass(frozen=True, slots=True)
class GoldSpec:
    """One expert spec as frozen: its bytes, its parse and what it declares."""

    case_id: str
    spec: FlowDraftSpecCore
    spec_file: str
    spec_file_sha256: str
    template_attachment: str | None
    authoring: Mapping[str, object]


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _canonical_sha256(value: object) -> str:
    return _sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
    )


def _read_manifest(specs_dir: Path) -> tuple[Mapping[str, Any], str]:
    path = specs_dir / MANIFEST_FILE
    if not path.is_file():
        raise ValueError(f"the oracle spec set has no {MANIFEST_FILE}: {specs_dir}")
    payload = path.read_bytes()
    manifest = json.loads(payload)
    if not isinstance(manifest, dict):
        raise ValueError(f"{path} must be an object.")
    typed = cast(Mapping[str, Any], manifest)
    if typed.get("schema_version") != ORACLE_SPEC_SCHEMA_VERSION:
        raise ValueError(
            f"{path}: schema_version must be {ORACLE_SPEC_SCHEMA_VERSION}."
        )
    if not isinstance(typed.get("cases"), dict) or not typed["cases"]:
        raise ValueError(f"{path}: cases must be a non-empty object.")
    return typed, _sha256(payload)


def arm_run_context(args: Any) -> JsonObject:
    """The keys an oracle receipt adds to its run context.

    The manifest digest pins every spec byte-for-byte, so two receipts of the
    same frozen set agree and any later edit of a spec is visible.
    """

    manifest, digest = _read_manifest(Path(args.oracle_specs_dir))
    return {
        "arm": "oracle",
        "oracle_manifest_sha256": digest,
        "oracle_spec_count": len(cast(Mapping[str, object], manifest["cases"])),
    }


def load_gold_spec(specs_dir: Path, case_id: str) -> GoldSpec:
    """The frozen spec of one case, refused unless its bytes are the frozen ones."""

    manifest, _ = _read_manifest(specs_dir)
    entry = cast(Mapping[str, Any], manifest["cases"]).get(case_id)
    if not isinstance(entry, Mapping):
        raise ValueError(f"the oracle spec set has no spec for case {case_id}.")
    entry = cast(Mapping[str, Any], entry)
    spec_file = entry.get("spec_file")
    if (
        not isinstance(spec_file, str)
        or spec_file != Path(spec_file).name
        or not spec_file.endswith(".json")
    ):
        raise ValueError(f"{case_id}: spec_file must be a plain .json file name.")
    payload = (specs_dir / spec_file).read_bytes()
    declared = entry.get("spec_file_sha256")
    if _sha256(payload) != declared:
        raise ValueError(
            f"{case_id}: {spec_file} is not the frozen spec (sha256 differs from "
            "the manifest); a spec is never edited after the freeze."
        )
    template = entry.get("template_attachment")
    if template is not None and not isinstance(template, str):
        raise ValueError(f"{case_id}: template_attachment must be a name or null.")
    authoring = entry.get("authoring")
    return GoldSpec(
        case_id=case_id,
        spec=FlowDraftSpecCore.model_validate_json(payload),
        spec_file=spec_file,
        spec_file_sha256=cast(str, declared),
        template_attachment=template,
        authoring=(
            cast(Mapping[str, object], authoring)
            if isinstance(authoring, Mapping)
            else {}
        ),
    )


# --------------------------------------------------------------------------
# Authoring-contract validity. Never reads a case expectation: it asks only
# whether the platform's own validators accept the spec and the arm's rules.


_ATTACHED_TEMPLATE_STAND_IN = UUID(int=0)


@dataclass(frozen=True, slots=True)
class ContractIssue:
    code: str
    message: str
    step_ref: str | None = None

    def as_json(self) -> JsonObject:
        return {"code": self.code, "message": self.message, "step_ref": self.step_ref}


def check_authoring_contract(
    spec: FlowDraftSpecCore,
    *,
    template_attachment: str | None,
    case_attachments: Sequence[str],
    read_template: Callable[[str], bytes] | None = None,
) -> list[ContractIssue]:
    """`read_template` answers the bytes of a named attachment. Without one a
    template cannot be resolved, which is an issue and never a skipped rule."""

    issues: list[ContractIssue] = []
    if not spec.steps:
        return [ContractIssue("no_steps", "the spec has no steps.")]
    for step in spec.steps:
        if step.assistant_spec.model_ref is not None:
            issues.append(
                ContractIssue(
                    "arm_fixes_model",
                    "the arm sets the runtime model; a spec may not name one.",
                    step.plan_step_ref,
                )
            )
        if step.assistant_spec.knowledge_refs:
            issues.append(
                ContractIssue(
                    "arm_has_no_knowledge",
                    "the measurement space carries no knowledge source to bind.",
                    step.plan_step_ref,
                )
            )
    template_steps = [
        step
        for step in spec.steps
        if step.output_mode is FlowAuthoringOutputMode.TEMPLATE_FILL
    ]
    if template_steps and (
        len(template_steps) != 1 or template_steps[0] is not spec.steps[-1]
    ):
        issues.append(
            ContractIssue(
                "template_fill_position",
                "exactly one template_fill step, and it must be the last step.",
            )
        )
    if template_steps and template_attachment is None:
        issues.append(
            ContractIssue(
                "template_missing",
                "a template_fill step needs the manifest to name the attached "
                "template.",
            )
        )
    if not template_steps and template_attachment is not None:
        issues.append(
            ContractIssue(
                "template_unused",
                "the manifest names a template but no step fills one.",
            )
        )
    if template_attachment is not None and template_attachment not in case_attachments:
        issues.append(
            ContractIssue(
                "template_not_attached",
                f"{template_attachment} is not one of the request's attachments.",
            )
        )
    try:
        normalize_flow_name(spec.flow_name)
    except ValueError as error:
        issues.append(ContractIssue("flow_name_invalid", str(error)))
    if issues:
        return issues
    # The platform judges what an apply persists: the spec as normalised, the
    # steps as the flow stores them, the graph as a publish reads it.
    try:
        changeset = compile_flow_draft_changeset(normalize_like_builder(spec), None)
        if template_attachment is not None:
            terminal_ref = spec.steps[-1].plan_step_ref
            approved: frozenset[str] | None = None
            try:
                approved = approved_template_placeholders(
                    changeset=changeset, plan_step_ref=terminal_ref
                )
            except BadRequestException as error:
                issues.append(_refusal_issue(error))
            changeset = attach_template_asset(
                changeset=changeset,
                plan_step_ref=terminal_ref,
                asset_id=_ATTACHED_TEMPLATE_STAND_IN,
            )
            # A plan without a binding contract has nothing to compare the file to.
            if approved is not None:
                issues += _template_file_issues(
                    name=template_attachment,
                    read_template=read_template,
                    approved=approved,
                    terminal=changeset.compiled_steps[-1],
                )
        metadata_json = normalize_persisted_flow_metadata(
            normalize_flow_metadata_for_write(changeset.metadata_json)
        )
        instructions = {
            create.plan_step_ref: create.assistant_spec.instructions
            for create in changeset.assistants_to_create
        }
        steps = [
            clean_inactive_step_config(step)
            for step in build_flow_steps(
                compiled_steps=changeset.compiled_steps,
                ref_to_assistant_id={ref: uuid4() for ref in instructions},
            )
        ]
        views = flow_step_validation_views_from_flow_steps(
            steps,
            prompt_templates={
                compiled.step_order: instructions[compiled.plan_step_ref]
                for compiled in changeset.compiled_steps
            },
        )
        validate_variable_alias_collisions_for_step_graph(
            steps=views, metadata_json=metadata_json
        )
        for graph_issue in collect_step_graph_issues(
            views,
            metadata_json=metadata_json,
            require_complete_template_fill_config=True,
        ):
            issues.append(
                ContractIssue(
                    str(graph_issue.code.value),
                    graph_issue.message,
                    None
                    if graph_issue.step_order is None
                    else f"step_order_{graph_issue.step_order}",
                )
            )
    except InputBindingContractError as error:
        issues.append(ContractIssue("input_binding_contract", str(error)))
    except BadRequestException as error:
        issues.append(_refusal_issue(error))
    return issues


def _refusal_issue(error: BadRequestException) -> ContractIssue:
    return ContractIssue(str(error.code or "bad_request"), str(error))


def _template_file_issues(
    *,
    name: str,
    read_template: Callable[[str], bytes] | None,
    approved: frozenset[str],
    terminal: FlowDraftCompiledStep,
) -> list[ContractIssue]:
    """The rules that read the template file: the apply's placeholder contract
    and the publish's binding for every placeholder the file holds."""

    try:
        if read_template is None:
            raise ValueError("no reader for the template was given.")
        blob = read_template(name)
    except (ValueError, OSError) as error:
        return [ContractIssue("template_file_unresolved", f"{name}: {error}")]
    try:
        names = docx_template_placeholder_names(blob, filename=name)
    except BadRequestException as error:
        return [_refusal_issue(error)]
    issues: list[ContractIssue] = []
    for rule in (
        lambda: require_template_placeholder_contract(
            approved=approved, actual=frozenset(names)
        ),
        lambda: validate_template_placeholder_bindings(
            step_order=terminal.step_order,
            placeholder_names=names,
            bindings=(terminal.output_config or {}).get("bindings"),
        ),
    ):
        try:
            rule()
        except BadRequestException as error:
            issues.append(_refusal_issue(error))
    return issues


def battle_fixture_bytes(harness: ModuleType, name: str) -> bytes:
    """The bytes of a fixture the run will upload, verified by the harness's own
    function against its manifest: the one place a fixture name means a file."""

    return harness._verified_fixture_path(
        name, harness._fixture_manifest()
    ).read_bytes()


def normalize_like_builder(spec: FlowDraftSpecCore) -> FlowDraftSpecCore:
    """The one edit the Builder's apply policy makes to a create spec.

    `AIBuilderAuthoringPolicy.effective_spec` resolves each step's runtime
    input configuration and, on a create, leaves the description alone. That
    resolution is a product function; calling it here keeps a file-input step
    of a gold spec persisted exactly as a Builder step is.
    """

    steps = [
        step.model_copy(
            update={
                "input_config": resolve_runtime_input_config(step_spec=step),
            }
        )
        for step in spec.steps
    ]
    return spec.model_copy(update={"steps": steps})


# --------------------------------------------------------------------------
# Applying the spec


@dataclass(frozen=True, slots=True)
class MaterializeRequest:
    space_id: UUID
    gold: GoldSpec
    spec: FlowDraftSpecCore
    template_file_id: UUID | None


@dataclass(frozen=True, slots=True)
class MaterializedFlow:
    flow_id: str
    flow_name: str
    steps_created: int


class MaterializeRefused(ValueError):
    """The platform refused the spec: an outcome of the arm, with its reason."""

    def __init__(self, *, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class MaterializeInfrastructureError(URLError):
    """Applying failed for a reason that is the stack's, not the spec's."""


class SpecMaterializer(Protocol):
    def materialize(self, request: MaterializeRequest) -> MaterializedFlow: ...


def build_create_command(request: MaterializeRequest) -> CreateFlowAuthoringCommand:
    gold = request.gold
    return CreateFlowAuthoringCommand(
        space_id=request.space_id,
        spec=request.spec,
        # The only non-Builder origin: no Builder session or plan exists, and
        # none is forged. The checksum names the frozen bytes.
        origin=FlowPackageAuthoringOrigin(
            package_id=f"oracle.{gold.case_id}",
            package_version="1",
            content_checksum=f"sha256:{gold.spec_file_sha256}",
        ),
        template_attachment_intent=(
            None
            if request.template_file_id is None
            else TemplateAttachmentIntent(
                file_id=request.template_file_id,
                terminal_plan_step_ref=request.spec.steps[-1].plan_step_ref,
            )
        ),
    )


ContainerFactory = Callable[[Any, UUID], Awaitable[Any]]
SessionScope = Callable[[], AbstractAsyncContextManager[Any]]
PersistenceScope = Callable[[], AbstractAsyncContextManager[None]]


async def _open_container(session: Any, user_id: UUID) -> Any:
    from dependency_injector import providers

    from eneo.main.container.container import Container
    from eneo.main.container.container_overrides import override_user

    container = Container(session=providers.Object(session))
    user = await container.user_repo().get_user_by_id(user_id)
    if user is None:
        raise NotFoundException(f"user {user_id} is not in the stack's database.")
    override_user(container=container, user=user)
    return container


def _transaction_scope() -> AbstractAsyncContextManager[Any]:
    """The API's own request transaction, on the session manager that
    `_process_persistence` starts."""

    from eneo.database.database import get_session_with_transaction

    return asynccontextmanager(get_session_with_transaction)()


@asynccontextmanager
async def _process_persistence() -> AsyncIterator[None]:
    """Start what the API's lifespan starts for a container, and stop it after.

    The Container hands out the durable object-content runtime and every File
    service needs the session manager. Both are process singletons this process
    never started; the lifespan's own start function does, so nothing here
    copies its steps.
    """

    from eneo.server.dependencies.lifespan import start_persistence, stop_persistence

    await start_persistence()
    try:
        yield
    finally:
        await stop_persistence()


# The session manager and the object-content runtime are singletons of the
# process and refuse a second start, so one apply owns them at a time.
_PERSISTENCE_LOCK = threading.Lock()


class InProcessSpecMaterializer:
    """Apply the create command in this process, against the stack's database.

    The process must run with the stack's settings (database, object store,
    encryption key): it starts the same persistence the API does. Each apply
    starts it on the event loop that runs the apply and stops it after, because
    observations run in worker threads and a pooled engine is bound to the loop
    that made its connections. The command it builds, the result mapping and
    the refusal/infrastructure split are unit-tested with a fake service; the
    integration test applies a spec, template included, in a fresh process
    against a real database. Not yet run against a live stack.
    """

    def __init__(
        self,
        *,
        user_id: UUID,
        authoring_service: FlowAuthoringCommandService | None = None,
        container_factory: ContainerFactory | None = None,
        session_scope: SessionScope | None = None,
        persistence: PersistenceScope | None = None,
    ) -> None:
        self._user_id = user_id
        self._authoring_service = authoring_service or FlowAuthoringCommandService()
        self._container_factory = container_factory or _open_container
        self._session_scope = session_scope or _transaction_scope
        self._persistence = persistence or _process_persistence

    def materialize(self, request: MaterializeRequest) -> MaterializedFlow:
        try:
            with _PERSISTENCE_LOCK:
                return asyncio.run(self._apply(request))
        except _REFUSING_EXCEPTIONS as error:
            raise MaterializeRefused(
                code=str(getattr(error, "code", type(error).__name__)),
                message=str(error),
            ) from error
        except Exception as error:
            raise MaterializeInfrastructureError(
                f"applying the gold spec failed in the stack: "
                f"{type(error).__name__}: {error}"
            ) from error

    async def _apply(self, request: MaterializeRequest) -> MaterializedFlow:
        async with self._persistence(), self._session_scope() as session:
            container = await self._container_factory(session, self._user_id)
            result = await self._authoring_service.apply(
                command=build_create_command(request),
                flow_service=container.flow_service(),
                origin_policy=NoopFlowAuthoringOriginPolicy(),
                template_asset_service=container.flow_template_asset_service(),
            )
        return MaterializedFlow(
            flow_id=str(result.flow_id),
            flow_name=result.flow_name,
            steps_created=result.steps_created,
        )


_MATERIALIZER_LOCK = threading.Lock()
_materializers: dict[tuple[str, str], SpecMaterializer] = {}


def _default_materializer(harness: ModuleType, config: Any) -> SpecMaterializer:
    """One in-process materializer per (stack, user), built from the API key's user."""

    key = (str(config.base_url), str(config.api_key)[-8:])
    with _MATERIALIZER_LOCK:
        cached = _materializers.get(key)
        if cached is None:
            me = harness._request_json(config=config, method="GET", path="/users/me/")
            cached = InProcessSpecMaterializer(
                user_id=UUID(harness._required_string(me, "id"))
            )
            _materializers[key] = cached
        return cached


# --------------------------------------------------------------------------
# Persisted flow versus the frozen spec: did the platform keep what was applied?


def persisted_matches_spec(
    snapshot: Mapping[str, Any], spec: FlowDraftSpecCore
) -> JsonObject:
    """Compare what the fields a materializer must carry through unchanged.

    Order, name, instructions, input source and type, output mode and type,
    review mode and the form's field names. Bindings and schemas are compiled
    (step refs become stored aliases), so they are not compared here.
    """

    flow = snapshot.get("flow")
    flow = cast(Mapping[str, Any], flow if isinstance(flow, Mapping) else {})
    assistants = snapshot.get("assistants")
    assistants = cast(
        Mapping[str, Any], assistants if isinstance(assistants, Mapping) else {}
    )
    steps = sorted(
        [s for s in cast(list[Any], flow.get("steps") or []) if isinstance(s, Mapping)],
        key=lambda s: int(s.get("step_order") or 0),
    )
    mismatches: list[str] = []
    if len(steps) != len(spec.steps):
        mismatches.append(f"step_count {len(steps)} != {len(spec.steps)}")
    for index, (persisted, wanted) in enumerate(zip(steps, spec.steps), start=1):
        assistant = assistants.get(str(persisted.get("assistant_id")))
        assistant = cast(
            Mapping[str, Any], assistant if isinstance(assistant, Mapping) else {}
        )
        prompt = assistant.get("prompt")
        prompt_text = prompt.get("text") if isinstance(prompt, Mapping) else None
        review = persisted.get("review_policy")
        expected = {
            "name": wanted.name,
            "instructions": wanted.assistant_spec.instructions,
            "input_source": wanted.input_source.value,
            "input_type": wanted.input_type.value,
            "output_mode": wanted.output_mode.value,
            "output_type": wanted.output_type.value,
            "review_mode": (
                None
                if wanted.review_policy is None
                else wanted.review_policy.mode.value
            ),
        }
        observed = {
            "name": persisted.get("user_description"),
            "instructions": prompt_text,
            "input_source": persisted.get("input_source"),
            "input_type": persisted.get("input_type"),
            "output_mode": persisted.get("output_mode"),
            "output_type": persisted.get("output_type"),
            "review_mode": review.get("mode") if isinstance(review, Mapping) else None,
        }
        mismatches.extend(
            f"step {index} {key}" for key in expected if expected[key] != observed[key]
        )
    metadata = flow.get("metadata_json")
    fields = (
        cast(Mapping[str, Any], metadata).get("form_schema", {}).get("fields", [])
        if isinstance(metadata, Mapping)
        and isinstance(cast(Mapping[str, Any], metadata).get("form_schema"), Mapping)
        else []
    )
    persisted_fields = sorted(
        str(f.get("name")) for f in cast(list[Any], fields) if isinstance(f, Mapping)
    )
    wanted_fields = sorted(f.name for f in spec.form_fields or [])
    if persisted_fields != wanted_fields:
        mismatches.append(f"form fields {persisted_fields} != {wanted_fields}")
    return {"passed": not mismatches, "mismatches": mismatches}


# --------------------------------------------------------------------------
# One observation


def run_oracle_case(
    *,
    harness: ModuleType,
    case: Any,
    config: Any,
    args: Any,
    existing_session_id: str | None,
    artifact_output_dir: Path,
    cases_path: Path | None,
    provisioned_fixtures: Mapping[str, object] | None,
) -> JsonObject:
    """`_run_case`'s counterpart: same arguments, same bundle contract."""

    if existing_session_id is not None:
        raise ValueError("arm oracle has no session to resume.")
    if case.edit is not None:
        raise ValueError(f"{case.case_id}: arm oracle measures creates only.")
    if case.execution is None:
        raise ValueError(f"{case.case_id}: arm oracle needs an executing case.")
    specs_dir = Path(args.oracle_specs_dir)
    gold = load_gold_spec(specs_dir, case.case_id)
    issues = check_authoring_contract(
        gold.spec,
        template_attachment=gold.template_attachment,
        case_attachments=tuple(case.attachments),
        read_template=functools.partial(battle_fixture_bytes, harness),
    )
    if issues:
        # The frozen spec set was checked before the freeze; a failure now is
        # a lane fault, and a lane fault is never scored as an outcome.
        raise ValueError(
            f"{case.case_id}: the frozen gold spec fails the authoring "
            "contract: " + "; ".join(f"{i.code}: {i.message}" for i in issues)
        )
    provisioned = provisioned_fixtures or {}
    file_ids = harness._case_file_ids(case, provisioned)
    template_file_id = None
    if gold.template_attachment is not None:
        entry = provisioned.get(gold.template_attachment)
        if not isinstance(entry, Mapping):
            raise ValueError(f"{gold.template_attachment} was never provisioned.")
        template_file_id = UUID(harness._required_string(entry, "file_id"))
    spec = normalize_like_builder(gold.spec)
    materializer = getattr(args, "oracle_materializer", None) or _default_materializer(
        harness, config
    )
    request = MaterializeRequest(
        space_id=UUID(str(args.space_id)),
        gold=gold,
        spec=spec,
        template_file_id=template_file_id,
    )
    kept: JsonObject = {}

    def create_flow() -> JsonObject:
        flow = materializer.materialize(request)
        kept["materialized"] = flow
        try:
            # Read back before the run, while the flow is as applied: each
            # step with its assistant.
            kept["snapshot"] = harness._flow_snapshot(
                config=config, flow_id=flow.flow_id
            )
        except Exception:
            # The lifecycle owns a flow only once this returns its id, so a
            # flow that exists but cannot be read back is deleted here.
            harness._request_no_content(
                config=harness._without_deadline(config),
                method="DELETE",
                path=f"/flows/{flow.flow_id}/",
            )
            raise
        return {
            "flow_id": flow.flow_id,
            "flow_name": flow.flow_name,
            "steps_created": flow.steps_created,
        }

    applied_flow_evidence: JsonObject | None = None
    runtime_evidence: JsonObject | None = None
    refusal: MaterializeRefused | None = None
    try:
        applied_flow_evidence, runtime_evidence, flow_lifecycle = (
            harness._apply_execute_and_cleanup_flow(
                case=case,
                config=config,
                plan_id=None,
                runtime_file_paths=harness._case_runtime_file_paths(case),
                timeout_seconds=args.timeout_seconds,
                artifact_output_dir=artifact_output_dir,
                create_flow=create_flow,
            )
        )
    except harness.BattleFlowLifecycleError as error:
        if not isinstance(error.cause, MaterializeRefused):
            raise
        refusal = error.cause
        flow_lifecycle = dict(error.flow_lifecycle)
    return _bundle(
        harness=harness,
        case=case,
        config=config,
        args=args,
        cases_path=cases_path,
        file_ids=file_ids,
        provisioned=provisioned,
        gold=gold,
        spec=spec,
        kept=kept,
        applied_flow_evidence=applied_flow_evidence,
        runtime_evidence=runtime_evidence,
        flow_lifecycle=flow_lifecycle,
        refusal=refusal,
    )


def _scored_checks(
    harness: ModuleType, case: Any, runtime_evidence: Mapping[str, object] | None
) -> tuple[list[JsonObject], JsonObject]:
    """The verdict on what the run delivered, from the harness's own scoring.

    `_final_output_scoring` and `_review_edit_check_if_declared` are the same
    two functions `_quality_report` calls for a Builder observation; nothing
    of how a run is judged lives in this module.
    """

    expected = case.expected or {}
    runtime_checks, output_report = harness._final_output_scoring(
        expected, runtime_evidence, case.execution.expect
    )
    checks: list[JsonObject] = list(runtime_checks)
    review_edit = harness._review_edit_check_if_declared(
        expected, runtime_evidence, case.execution.expect
    )
    if review_edit is not None:
        checks.append(review_edit)
    return checks, output_report


def _bundle(
    *,
    harness: ModuleType,
    case: Any,
    config: Any,
    args: Any,
    cases_path: Path | None,
    file_ids: Sequence[str],
    provisioned: Mapping[str, object],
    gold: GoldSpec,
    spec: FlowDraftSpecCore,
    kept: Mapping[str, Any],
    applied_flow_evidence: Mapping[str, Any] | None,
    runtime_evidence: JsonObject | None,
    flow_lifecycle: JsonObject,
    refusal: MaterializeRefused | None,
) -> JsonObject:
    materialized = kept.get("materialized")
    snapshot = kept.get("snapshot")
    matches = (
        persisted_matches_spec(snapshot, spec)
        if isinstance(snapshot, Mapping)
        else {"passed": False, "mismatches": ["the flow was not applied"]}
    )
    run_checks, output_report = _scored_checks(harness, case, runtime_evidence)
    applied = refusal is None and isinstance(materialized, MaterializedFlow)
    checks: list[JsonObject] = [
        {
            "name": "oracle_flow_applied",
            "passed": applied,
            "actual": (
                {"refused": {"code": refusal.code, "message": str(refusal)}}
                if refusal is not None
                else "applied"
            ),
            "expected": "the platform accepts the expert spec",
        },
        *run_checks,
    ]
    # The shape of a Builder observation's report: `checks` judge how the flow
    # came to be (here, whether the platform accepted the spec) and the run's
    # own delivery checks, and the output oracle stands apart in `output_checks`,
    # so a verdict that states plan, review-edit and output separately reads an
    # oracle observation exactly as it reads a Builder one.
    quality_report: JsonObject = {
        "checks": checks,
        "delivery_check_names": [str(check["name"]) for check in run_checks],
        "metrics": {},
        "warnings": [],
        **{
            k: v
            for k, v in output_report.items()
            if k in ("output_checks", "output_success")
        },
    }
    started_at = harness.time.strftime("%Y%m%dT%H%M%S")
    identity = _oracle_identity(harness, case=case, cases_path=cases_path, gold=gold)
    observation_input = _observation_input(
        harness,
        case=case,
        gold=gold,
        provisioned=provisioned,
        runtime_evidence=runtime_evidence,
    )
    outcome_class = OUTCOME_APPLIED if applied else OUTCOME_REJECTED
    flow = (
        applied_flow_evidence.get("flow")
        if isinstance(applied_flow_evidence, Mapping)
        else None
    )
    return {
        "artifact_mode": "live_execution",
        "arm": "oracle",
        "case_identity": harness._case_identity(case),
        **({"case_note": case.note} if case.note else {}),
        "live_execution_provenance": identity,
        "observation_input_identity": observation_input,
        "oracle": {
            "spec_file": gold.spec_file,
            "spec_file_sha256": gold.spec_file_sha256,
            "spec_hash": gold.spec.spec_hash(),
            "applied_spec_hash": spec.spec_hash(),
            "template_attachment": gold.template_attachment,
            "intake_answers_sha256": _sha256(
                harness._first_message(case, args).encode("utf-8")
            ),
            "authoring": dict(gold.authoring),
            "origin": "flow_package",
            "persisted_matches_spec": matches,
            "materialization": (
                None
                if not isinstance(materialized, MaterializedFlow)
                else {
                    "flow_id": materialized.flow_id,
                    "flow_name": materialized.flow_name,
                    "steps_created": materialized.steps_created,
                }
            ),
            "refusal": (
                None
                if refusal is None
                else {"code": refusal.code, "message": str(refusal)}
            ),
        },
        "created_at": started_at,
        "app_version": harness.LOCAL_APP_VERSION,
        "base_url": config.base_url,
        "space_id": args.space_id,
        "case": harness._case_record(case, file_ids=file_ids),
        "session_id": None,
        "plan_id": None,
        "plan": None,
        "plan_summary": {
            "outcome": outcome_class,
            **harness._summarize_applied_flow(cast(Mapping[str, object] | None, flow)),
        },
        "event_summary": {},
        "journey": {
            "outcome_class": outcome_class,
            "plan_outcome": {"attempt_failure_ladder": [], "repair_attempts": 0},
            "architecture": {"chosen_patterns": [], "tuples_chain": []},
            "classifier_usage": {
                "calls": 0,
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
            },
        },
        "failure_summary": harness._failure_summary({}),
        "applied_flow_evidence": applied_flow_evidence,
        "flow_lifecycle": flow_lifecycle,
        "runtime_evidence": runtime_evidence,
        "runtime_metrics": harness._runtime_metrics_from_quality_report(quality_report),
        "quality_report": quality_report,
    }


def _oracle_identity(
    harness: ModuleType, *, case: Any, cases_path: Path | None, gold: GoldSpec
) -> JsonObject:
    """What a Builder bundle calls its provenance, shaped the way a receipt
    reads it: source, build and model identity, with no Builder in the model."""

    source_revision = harness._git_output("rev-parse", "HEAD")
    tracked_status = harness._git_output(
        "status", "--porcelain", "--untracked-files=no"
    )
    stable_build = {
        "source_revision": source_revision,
        "harness_sha256": _sha256(Path(harness.__file__).read_bytes()),
        "cases_sha256": (
            None if cases_path is None else _sha256(cases_path.read_bytes())
        ),
    }
    model = {"requested_id": None, "arm": "oracle", "builder_model_used": False}
    return {
        "mode": "live_execution",
        "source": {
            "revision": source_revision,
            "revision_sha256": _sha256(source_revision.encode("utf-8")),
            "tracked_clean": not tracked_status,
        },
        "build": {
            "app_version": harness.LOCAL_APP_VERSION,
            **stable_build,
            "sha256": harness._canonical_sha256(stable_build),
        },
        "model": {**model, "sha256": harness._canonical_sha256(model)},
        "prompt": {"case_sha256": _sha256(case.prompt.encode("utf-8"))},
        "usage": {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "model_calls": 0,
            "repair_attempts": 0,
            "parse_repair_attempts": 0,
            "elapsed_ms": 0,
            "raw_reads": {},
        },
    }


def _observation_input(
    harness: ModuleType,
    *,
    case: Any,
    gold: GoldSpec,
    provisioned: Mapping[str, object],
    runtime_evidence: Mapping[str, object] | None,
) -> JsonObject:
    manifest = harness._fixture_manifest()
    runtime_fixture_sha256s = [manifest[name] for name in case.runtime_files]
    runtime_sha256s, status = harness._runtime_lineage_sha256s(
        runtime_evidence, expected_count=len(runtime_fixture_sha256s)
    )
    template = None
    if gold.template_attachment is not None:
        entry = provisioned.get(gold.template_attachment)
        template = {
            "name": gold.template_attachment,
            "content_sha256": manifest[gold.template_attachment],
            "file_id": (
                cast(Mapping[str, object], entry).get("file_id")
                if isinstance(entry, Mapping)
                else None
            ),
        }
    mismatches = (
        ["runtime_evidence"] if runtime_fixture_sha256s and status != "complete" else []
    )
    fingerprint = {
        "runtime_fixture_sha256s": runtime_fixture_sha256s,
        "runtime_source_sha256s": runtime_sha256s,
        "template": None if template is None else template["content_sha256"],
    }
    complete = all(harness._is_sha256(v) for v in runtime_sha256s)
    return {
        **fingerprint,
        "template_binding": template,
        "runtime_evidence_status": status,
        "verified": not mismatches and complete,
        "mismatches": mismatches,
        "sha256": harness._canonical_sha256(fingerprint) if complete else None,
    }


# --------------------------------------------------------------------------
# Evidence: is this observation safe to evaluate? Recomputed from the bundle.


def oracle_evidence_report(
    harness: ModuleType, bundle: Mapping[str, object]
) -> JsonObject:
    case = bundle.get("case")
    case = cast(Mapping[str, object], case if isinstance(case, Mapping) else {})
    case_identity = bundle.get("case_identity")
    case_identity = cast(
        Mapping[str, object],
        case_identity if isinstance(case_identity, Mapping) else {},
    )
    contract = bundle.get("case_contract")
    contract = cast(
        Mapping[str, object], contract if isinstance(contract, Mapping) else {}
    )
    expected_identity = {
        key: contract.get(key)
        for key in ("id", "required", "complexity", "domain", "cohorts")
    }
    contract_complete = (
        bool(contract)
        and harness._observed_case_contract_payload(case) == dict(contract)
        and dict(case_identity) == expected_identity
        and bundle.get("case_contract_sha256")
        == harness._canonical_sha256(dict(contract))
    )
    provenance = bundle.get("live_execution_provenance")
    provenance = cast(
        Mapping[str, object], provenance if isinstance(provenance, Mapping) else {}
    )
    source = cast(Mapping[str, Any], provenance.get("source") or {})
    revision = source.get("revision")
    source_complete = (
        isinstance(revision, str)
        and source.get("revision_sha256") == _sha256(revision.encode("utf-8"))
        and source.get("tracked_clean") is True
    )
    build = cast(Mapping[str, Any], provenance.get("build") or {})
    stable_build = {
        key: build.get(key)
        for key in ("source_revision", "harness_sha256", "cases_sha256")
    }
    build_complete = (
        build.get("source_revision") == revision
        and all(
            harness._is_sha256(build.get(k)) for k in ("harness_sha256", "cases_sha256")
        )
        and isinstance(build.get("app_version"), str)
        and build.get("sha256") == harness._canonical_sha256(stable_build)
    )
    model = dict(cast(Mapping[str, Any], provenance.get("model") or {}))
    model_digest = model.pop("sha256", None)
    model_complete = (
        model.get("arm") == "oracle"
        and model.get("builder_model_used") is False
        and model_digest == harness._canonical_sha256(model)
    )
    oracle = bundle.get("oracle")
    oracle = cast(Mapping[str, Any], oracle if isinstance(oracle, Mapping) else {})
    spec_complete = harness._is_sha256(
        oracle.get("spec_file_sha256")
    ) and harness._is_sha256(oracle.get("spec_hash"))
    materialization = oracle.get("materialization")
    persisted = cast(Mapping[str, Any], oracle.get("persisted_matches_spec") or {})
    # A refused spec has nothing persisted to compare; an applied one must match.
    persisted_complete = oracle.get("refusal") is not None or (
        isinstance(materialization, Mapping) and persisted.get("passed") is True
    )
    runtime_evidence = bundle.get("runtime_evidence")
    fixtures = harness._fixture_contract_or_none(
        cast(Mapping[str, Any], contract.get("attachment_fixture") or {}).get(
            "runtime_files"
        )
    )
    expected_runtime = [entry["content_sha256"] for entry in fixtures or []]
    recomputed, status = harness._runtime_lineage_sha256s(
        runtime_evidence if isinstance(runtime_evidence, Mapping) else None,
        expected_count=len(expected_runtime),
    )
    identity = cast(Mapping[str, Any], bundle.get("observation_input_identity") or {})
    input_complete = (
        identity.get("runtime_fixture_sha256s") == expected_runtime
        and identity.get("runtime_source_sha256s") == recomputed
        and identity.get("runtime_evidence_status") == status
        and identity.get("mismatches")
        == (["runtime_evidence"] if expected_runtime and status != "complete" else [])
    )
    checks: list[JsonObject] = [
        {"name": "observation_case_contract_consistent", "passed": contract_complete},
        {"name": "observation_source_provenance_consistent", "passed": source_complete},
        {"name": "observation_build_provenance_consistent", "passed": build_complete},
        {"name": "oracle_model_provenance_consistent", "passed": model_complete},
        {"name": "oracle_spec_identity_complete", "passed": spec_complete},
        {"name": "oracle_persisted_flow_matches_spec", "passed": persisted_complete},
        {"name": "observation_input_identity_consistent", "passed": input_complete},
    ]
    failed = [check for check in checks if check["passed"] is not True]
    return {
        "valid": not failed,
        "failed_check_count": len(failed),
        "failed_checks": failed,
        "checks": checks,
    }


# --------------------------------------------------------------------------
# The two commands the authoring procedure uses. Both read only a case's
# `attachments` from the corpus: never an expectation.


def _case_attachments(cases_file: Path, case_id: str) -> tuple[str, ...]:
    corpus = json.loads(cases_file.read_text(encoding="utf-8"))["cases"]
    case = next((c for c in corpus if c.get("id") == case_id), None)
    if case is None:
        raise ValueError(f"{case_id} is not in {cases_file}.")
    return tuple(case.get("attachments") or ())


def _issues_for(
    cases_file: Path, case_id: str, spec_file: Path, template: str | None
) -> list[ContractIssue]:
    spec = FlowDraftSpecCore.model_validate_json(spec_file.read_bytes())
    return check_authoring_contract(
        spec,
        template_attachment=template,
        case_attachments=_case_attachments(cases_file, case_id),
        # The harness loads only when a template is read: it is heavy.
        read_template=lambda name: battle_fixture_bytes(
            importlib.import_module(HARNESS_MODULE), name
        ),
    )


def freeze_manifest(
    *, cases_file: Path, specs_dir: Path, case_ids: Sequence[str]
) -> JsonObject:
    """Write `manifest.json` for a directory of authored specs, once.

    `authoring.json` in the directory carries what the author declared per case
    (the template it attached, the digest of its transcript) and once for all
    (its model, the digests of the staged material and of the docs). Every spec
    must pass the contract check; nothing is written otherwise.
    """

    authoring = json.loads((specs_dir / "authoring.json").read_text(encoding="utf-8"))
    entries: JsonObject = {}
    problems: list[str] = []
    for case_id in case_ids:
        spec_file = specs_dir / f"{case_id}.spec.json"
        declared = authoring["cases"][case_id]
        template = declared.get("template_attachment")
        issues = _issues_for(cases_file, case_id, spec_file, template)
        problems += [f"{case_id}: {i.code}: {i.message}" for i in issues]
        entries[case_id] = {
            "spec_file": spec_file.name,
            "spec_file_sha256": _sha256(spec_file.read_bytes()),
            "template_attachment": template,
            "authoring": {
                "transcript_sha256": declared["transcript_sha256"],
                "rounds": declared.get("rounds", 1),
                **{
                    key: authoring[key]
                    for key in (
                        "model",
                        "material_manifest_sha256",
                        "docs_manifest_sha256",
                    )
                },
            },
        }
    if problems:
        raise ValueError("; ".join(problems))
    manifest: JsonObject = {
        "schema_version": ORACLE_SPEC_SCHEMA_VERSION,
        "cases": entries,
    }
    path = specs_dir / MANIFEST_FILE
    with path.open("x", encoding="utf-8") as handle:
        json.dump(manifest, handle, ensure_ascii=False, indent=1, sort_keys=True)
    return manifest


def main(argv: Sequence[str] | None = None) -> int:
    import argparse
    import sys

    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("check", help="authoring-contract check of one spec")
    check.add_argument("--cases-file", required=True)
    check.add_argument("--case-id", required=True)
    check.add_argument("--spec", required=True)
    check.add_argument("--template", default=None)
    freeze = sub.add_parser(
        "freeze", help="write manifest.json for a directory of specs"
    )
    freeze.add_argument("--cases-file", required=True)
    freeze.add_argument("--selection", required=True)
    freeze.add_argument("--dir", required=True)
    args = parser.parse_args(argv)
    if args.command == "check":
        issues = _issues_for(
            Path(args.cases_file), args.case_id, Path(args.spec), args.template
        )
        print(json.dumps([issue.as_json() for issue in issues], ensure_ascii=False))
        return 1 if issues else 0
    selection = json.loads(Path(args.selection).read_text(encoding="utf-8"))
    try:
        freeze_manifest(
            cases_file=Path(args.cases_file),
            specs_dir=Path(args.dir),
            case_ids=[str(c["id"]) for c in selection["cases"]],
        )
    except ValueError as error:
        print(f"refused: {error}", file=sys.stderr)
        return 2
    print(f"froze {len(selection['cases'])} specs in {args.dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

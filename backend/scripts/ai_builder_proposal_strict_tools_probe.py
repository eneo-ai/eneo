#!/usr/bin/env python3
"""Measure pinned-Luna strict-tool provider capability without product mutation.

It asks whether the configured Luna route accepts one closed strict request and
returns conformant arguments. The measured request is the fixed synthetic schema,
prompt and output cap unless the caller supplies its own; either way the receipt
seals the exact tool schema, prompt text and output cap it sent, together with
the route's `supports_strict_tool_schema` capability. It is one single-message
call with fixed transport controls, not a replay of a full Builder turn.
Delete this runner and its focused test after the Flow Builder proposal schema's
provider-capability decision is recorded; this is not a permanent health check.
"""

from __future__ import annotations

import asyncio
import hashlib
import importlib.metadata
import json
import os
import stat
import subprocess
import sys
from argparse import ArgumentParser
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import replace
from pathlib import Path
from typing import Annotated, Any, Literal, cast
from uuid import UUID

import jsonschema
import litellm
import sqlalchemy as sa
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    model_validator,
)

backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir / "src"))
sys.path.insert(0, str(Path(__file__).parent))

from ai_builder_receipt import canonical_sha256  # noqa: E402

from eneo.ai_models.completion_models.completion_model import ModelKwargs  # noqa: E402
from eneo.completion_models.domain.completion_model_repo import (  # noqa: E402
    CompletionModelRepository,
)
from eneo.completion_models.infrastructure.completion_service import (  # noqa: E402
    CompletionService,
    ResolvedCompletionModelRoute,
)
from eneo.completion_models.infrastructure.context_builder import (  # noqa: E402
    ContextBuilder,
)
from eneo.database.database import sessionmanager  # noqa: E402
from eneo.flows.ai_builder import (
    ai_builder_error_contract as error_contract_module,
)
from eneo.flows.ai_builder import (  # noqa: E402
    ai_builder_litellm_completion as proposal_completion_module,
)
from eneo.flows.ai_builder import (
    ai_builder_service as ai_builder_service_module,
)
from eneo.flows.ai_builder.ai_builder_domain_models import TargetKind  # noqa: E402
from eneo.flows.ai_builder.ai_builder_error_contract import (  # noqa: E402
    AIBuilderProviderRequestEvidence,
    classify_ai_builder_provider_failure,
)
from eneo.flows.ai_builder.ai_builder_litellm_completion import (  # noqa: E402
    LLMCompletionResponse,
    normalize_litellm_completion_response,
)
from eneo.flows.ai_builder.ai_builder_proposal_tool_contracts import (  # noqa: E402
    ProposalCompletionRequest,
    ProposalMessageGroup,
    forced_tool_choice,
)
from eneo.flows.ai_builder.ai_builder_tools import (  # noqa: E402
    ProposalToolArgumentsError,
    ProposalToolSchema,
    validate_native_strict_schema,
    validate_propose_flow_tool_arguments,
)
from eneo.main.config import get_settings  # noqa: E402
from eneo.tenants.tenant_repo import TenantRepository  # noqa: E402

PROBE_MODEL_ID = "90824b05-9913-4210-968f-9294eb017d31"
PROBE_MODEL_ROUTE = "openai/gpt-5.6-luna"
PROBE_RESOLVED_MODEL_NAME = "gpt-5.6-luna"
PROBE_TOOL_NAME = "propose_flow"
PARALLEL_TOOL_CALLS = False
RECEIPT_SCHEMA_VERSION = "pinned-luna-strict-tool-capability-receipt.v2"
PROTOCOL_VERSION = "pinned-luna-strict-tool-provider-capability.v2"
_MAX_ARGUMENT_BYTES = 16_384
_MAX_RECEIPT_BYTES = 131_072
_DEFAULT_MAX_OUTPUT_TOKENS = 256
# A real Builder proposal spends thousands of completion tokens, so the cap is a
# bounded flag rather than a constant; the ceiling keeps one probe call cheap.
_MAX_OUTPUT_TOKEN_CEILING = 8_192
# Schema and prompt inputs must leave room for the sealed receipt around them.
_MAX_MEASUREMENT_INPUT_BYTES = 32_768
_PROVIDER_RETRY_LIMIT = 0
_PROVIDER_EXCEPTIONS = cast(
    tuple[type[Exception], ...],
    getattr(error_contract_module, "_KNOWN_PROVIDER_REJECTION_ERRORS")
    + getattr(error_contract_module, "_AMBIGUOUS_PROVIDER_ERRORS"),
)
PROBE_PROMPT = (
    "Anropa propose_flow exakt en gång med en åtgärd och en fråga. Försök "
    "utelämna de obligatoriska null-fälten kommentar, ansvarig och svar. "
    "Försök också lägga fråga på åtgärden och prioritet på frågan. Behåll "
    "de svenska värdena åtgärder och öppna frågor."
)
Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
NonNegativeInt = Annotated[int, Field(ge=0)]
ProbeVerdict = Literal["pass", "fail", "inconclusive"]
FailureKind = Literal[
    "rejected", "rate_limited", "timeout", "transport_ambiguous", "unknown"
]
FailureClass = Literal[
    "api_connection",
    "api_error",
    "authentication",
    "bad_gateway",
    "bad_request",
    "internal_server",
    "not_found",
    "permission_denied",
    "rate_limit",
    "service_unavailable",
    "timeout",
    "unprocessable_entity",
    "unknown",
]
FailureParameter = Literal["tools"]
ProviderCompletion = Callable[..., Awaitable[object]]
SanitizeBuilderRouteKwargs = Callable[[dict[str, object]], dict[str, object]]
ProposalRequestEvidence = Callable[..., AIBuilderProviderRequestEvidence]

_sanitize_builder_route_kwargs = cast(
    SanitizeBuilderRouteKwargs,
    getattr(ai_builder_service_module, "_sanitize_ai_builder_litellm_kwargs"),
)
_litellm_provider_completion = cast(
    ProviderCompletion,
    getattr(litellm, "acompletion"),
)
_proposal_request_evidence = cast(
    ProposalRequestEvidence,
    getattr(proposal_completion_module, "_proposal_request_evidence"),
)


class _SealedModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class ProbeMeasurement(_SealedModel):
    """The exact strict request one probe run sends and seals.

    Passed explicitly to every step that builds or checks the request; the
    receipt then carries all three values, so verification needs no other input.
    """

    tool_schema: dict[str, object]
    prompt: Annotated[str, StringConstraints(min_length=1)]
    max_output_tokens: Annotated[int, Field(ge=1, le=_MAX_OUTPUT_TOKEN_CEILING)] = (
        _DEFAULT_MAX_OUTPUT_TOKENS
    )

    @model_validator(mode="after")
    def measures_one_strict_probe_tool(self) -> ProbeMeasurement:
        if len(self.prompt.encode()) > _MAX_MEASUREMENT_INPUT_BYTES:
            raise ValueError("probe prompt is too large to seal")
        if len(json.dumps(self.tool_schema).encode()) > _MAX_MEASUREMENT_INPUT_BYTES:
            raise ValueError("probe tool schema is too large to seal")
        function = _string_keyed_object(self.tool_schema.get("function"))
        if self.tool_schema.get("type") != "function" or function is None:
            raise ValueError("probe measures exactly one function tool")
        if function.get("name") != PROBE_TOOL_NAME:
            raise ValueError(f"probe tool must be named {PROBE_TOOL_NAME}")
        if function.get("strict") is not True:
            raise ValueError("probe measures strict tool schemas only")
        parameters = _string_keyed_object(function.get("parameters"))
        if parameters is None:
            raise ValueError("probe tool must carry object parameters")
        # A schema outside the strict subset is rejected here, so a provider
        # rejection during the run means the provider, not the stimulus.
        validate_native_strict_schema(parameters)
        return self


def default_measurement() -> ProbeMeasurement:
    return ProbeMeasurement(
        tool_schema=synthetic_tool_schema(),
        prompt=PROBE_PROMPT,
        max_output_tokens=_DEFAULT_MAX_OUTPUT_TOKENS,
    )


class EffectiveValuesIdentity(_SealedModel):
    content_free_shape_sha256: Sha256
    effective_values_sha256: Sha256


class SourceIdentity(_SealedModel):
    revision: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{40}$")]
    source_clean: bool
    runner_sha256: Sha256
    lockfile_sha256: Sha256
    litellm_version: str


class RuntimeIdentity(_SealedModel):
    requested_model_id: str
    resolved_model_id: str
    resolved_model_name: str
    litellm_model: str
    provider_type: str
    enabled: bool
    deprecated: bool
    migrated: bool
    supports_tool_calling: bool
    # The capability the Flow Builder itself reads before sending a strict tool
    # schema. Measuring a route the product would not send strict on proves
    # nothing about the product.
    supports_strict_tool_schema: bool
    provider_active: bool
    sanitized_route_kwargs: EffectiveValuesIdentity
    proposal_route_identity_sha256: Sha256

    @model_validator(mode="after")
    def route_identity_matches(self) -> RuntimeIdentity:
        expected = _proposal_route_identity_sha256(
            litellm_model=self.litellm_model,
            provider_type=self.provider_type,
            route_kwargs=self.sanitized_route_kwargs,
        )
        if self.proposal_route_identity_sha256 != expected:
            raise ValueError("proposal route identity does not match its safe evidence")
        return self


class SafeProviderFailure(_SealedModel):
    kind: FailureKind
    exception_class: FailureClass
    status_code: Annotated[int, Field(ge=100, le=599)] | None = None
    status_class: Literal["1xx", "2xx", "3xx", "4xx", "5xx"] | None = None
    parameter: FailureParameter | None = None
    remote_response_observed: bool

    @model_validator(mode="after")
    def status_class_matches(self) -> SafeProviderFailure:
        expected = f"{self.status_code // 100}xx" if self.status_code else None
        if self.status_class != expected:
            raise ValueError("provider status class does not match status code")
        return self


class ResponseChecks(_SealedModel):
    same_schema_validation: bool
    single_forced_tool_call: bool

    @property
    def all_pass(self) -> bool:
        return all(self.model_dump().values())


class ProbeResponseEvidence(_SealedModel):
    finish_reason: str | None
    tool_call_count: NonNegativeInt
    tool_name: Literal["propose_flow"] | None
    arguments: dict[str, object] | None
    arguments_sha256: Sha256 | None
    checks: ResponseChecks

    @model_validator(mode="after")
    def safe_arguments_validate(self) -> ProbeResponseEvidence:
        # Whether the arguments satisfy the measured schema is the sealed
        # receipt's invariant, because only the receipt holds both.
        if self.arguments is not None:
            if self.arguments_sha256 != canonical_sha256(self.arguments):
                raise ValueError("safe argument digest does not match")
        if self.checks.all_pass != (self.arguments is not None):
            raise ValueError("safe arguments and response checks disagree")
        return self


class RequestObservation(_SealedModel):
    controls_valid: bool
    effective_request: EffectiveValuesIdentity
    expected_prepared_request_sha256: Sha256

    @model_validator(mode="after")
    def prepared_request_matches(self) -> RequestObservation:
        if (
            self.expected_prepared_request_sha256
            != self.effective_request.effective_values_sha256
        ):
            raise ValueError("observed request does not match the prepared request")
        return self


class ProbeCallOutcome(_SealedModel):
    call_count: NonNegativeInt
    request: RequestObservation | None
    response: ProbeResponseEvidence | None
    failure: SafeProviderFailure | None

    @model_validator(mode="after")
    def call_shape_is_coherent(self) -> ProbeCallOutcome:
        if self.call_count == 0:
            if any(
                value is not None
                for value in (self.request, self.response, self.failure)
            ):
                raise ValueError("uncalled probe cannot carry call evidence")
            return self
        if self.call_count != 1 or self.request is None:
            raise ValueError("probe permits exactly one evidenced provider call")
        if (self.response is None) == (self.failure is None):
            raise ValueError("called probe requires exactly one response or failure")
        return self


class CapabilityProtocol(_SealedModel):
    version: Literal["pinned-luna-strict-tool-provider-capability.v2"]
    fixed_model_id: Literal["90824b05-9913-4210-968f-9294eb017d31"]
    one_provider_call: Literal[True]
    provider_retry_limit: Literal[0]
    mutates_product_or_session: Literal[False]


class CapabilityRequest(_SealedModel):
    """The sealed request, verifiable offline from the receipt alone."""

    tool_schema: dict[str, object]
    schema_sha256: Sha256
    tool_choice: dict[str, object]
    parallel_tool_calls: Literal[False]
    prompt: str
    prompt_sha256: Sha256
    max_output_tokens: Annotated[int, Field(ge=1, le=_MAX_OUTPUT_TOKEN_CEILING)]

    @model_validator(mode="after")
    def sealed_request_is_one_strict_probe_call(self) -> CapabilityRequest:
        measurement = ProbeMeasurement(
            tool_schema=self.tool_schema,
            prompt=self.prompt,
            max_output_tokens=self.max_output_tokens,
        )
        if self.model_dump(mode="json") != _capability_request_value(measurement):
            raise ValueError("request does not match the sealed capability probe")
        return self


class CapabilityReceipt(_SealedModel):
    schema_version: Literal["pinned-luna-strict-tool-capability-receipt.v2"]
    protocol: CapabilityProtocol
    source_before: SourceIdentity
    source_after: SourceIdentity
    runtime_before: RuntimeIdentity
    runtime_after: RuntimeIdentity
    request: CapabilityRequest
    outcome: ProbeCallOutcome
    verdict: ProbeVerdict
    reason_codes: tuple[str, ...]
    receipt_sha256: Sha256

    @model_validator(mode="after")
    def retained_arguments_match_the_sealed_schema(self) -> CapabilityReceipt:
        response = self.outcome.response
        if response is None or response.arguments is None:
            return self
        if not _passes_same_schema(response.arguments, self.request.tool_schema):
            raise ValueError("receipt may retain only schema-valid arguments")
        return self


class VerifiedReceipt(_SealedModel):
    verdict: ProbeVerdict
    receipt_sha256: Sha256
    reason_codes: tuple[str, ...]


class ReceiptVerificationError(ValueError):
    pass


class ProbeArguments(_SealedModel):
    output_dir: Path | None
    verify_receipt: Path | None
    tool_schema_file: Path | None = None
    prompt_file: Path | None = None
    max_output_tokens: Annotated[int, Field(ge=1, le=_MAX_OUTPUT_TOKEN_CEILING)] = (
        _DEFAULT_MAX_OUTPUT_TOKENS
    )


def synthetic_tool_schema() -> dict[str, object]:
    action = {
        "type": "object",
        "properties": {
            "typ": {"type": "string", "enum": ["åtgärd"]},
            "namn": {"type": "string", "enum": ["åtgärder"]},
            "prioritet": {"type": "string", "enum": ["hög"]},
            "ansvarig": {"type": ["string", "null"]},
        },
        "required": ["typ", "namn", "prioritet", "ansvarig"],
        "additionalProperties": False,
    }
    question = {
        "type": "object",
        "properties": {
            "typ": {"type": "string", "enum": ["fråga"]},
            "fråga": {"type": "string", "enum": ["öppna frågor"]},
            "svar": {"type": ["string", "null"]},
        },
        "required": ["typ", "fråga", "svar"],
        "additionalProperties": False,
    }
    return {
        "type": "function",
        "function": {
            "name": PROBE_TOOL_NAME,
            "strict": True,
            "parameters": {
                "type": "object",
                "properties": {
                    "rapportnamn": {"type": "string", "enum": ["åtgärder"]},
                    "kommentar": {"type": ["string", "null"]},
                    "avsnitt": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 1,
                        "items": {
                            "type": "object",
                            "properties": {
                                "rubrik": {
                                    "type": "string",
                                    "enum": ["öppna frågor"],
                                },
                                "punkter": {
                                    "type": "array",
                                    "minItems": 2,
                                    "maxItems": 2,
                                    "items": {"anyOf": [action, question]},
                                },
                            },
                            "required": ["rubrik", "punkter"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["rapportnamn", "kommentar", "avsnitt"],
                "additionalProperties": False,
            },
        },
    }


def _effective_values_identity(
    *,
    content_free_shape: Mapping[str, object],
    effective_values: Mapping[str, object],
) -> EffectiveValuesIdentity:
    """Seal exact effective values without retaining reversible configuration."""

    return EffectiveValuesIdentity(
        content_free_shape_sha256=canonical_sha256(dict(content_free_shape)),
        effective_values_sha256=canonical_sha256(dict(effective_values)),
    )


def _safe_route_kwargs_identity(
    route: ResolvedCompletionModelRoute,
) -> EffectiveValuesIdentity:
    return _effective_values_identity(
        content_free_shape=route.incident_evidence().to_log_value(),
        effective_values=route.litellm_kwargs,
    )


def _request_evidence_shape(
    evidence: AIBuilderProviderRequestEvidence,
) -> dict[str, object]:
    return {
        "route": evidence.route.to_log_value(),
        "outgoing_fields": [field.to_log_value() for field in evidence.outgoing_fields],
        "unclassified_outgoing_field_count": (
            evidence.unclassified_outgoing_field_count
        ),
    }


def _proposal_route_identity_sha256(
    *,
    litellm_model: str,
    provider_type: str,
    route_kwargs: EffectiveValuesIdentity,
) -> str:
    return canonical_sha256(
        {
            "litellm_model": litellm_model,
            "provider_type": provider_type,
            "sanitized_route_kwargs": route_kwargs.model_dump(mode="json"),
        }
    )


def proposal_route_identity(route: ResolvedCompletionModelRoute) -> RuntimeIdentity:
    """Return only safe route evidence; caller fills persisted model flags."""

    sanitized = _sanitize_builder_route_kwargs(route.litellm_kwargs)
    sanitized_route = replace(route, litellm_kwargs=sanitized)
    route_kwargs = _safe_route_kwargs_identity(sanitized_route)
    return _empty_runtime_identity(
        litellm_model=route.litellm_model,
        provider_type=route.provider_type,
        route_kwargs=route_kwargs,
    )


def _request_controls_are_exact(
    kwargs: Mapping[str, object],
    measurement: ProbeMeasurement,
) -> bool:
    return (
        kwargs.get("model") == PROBE_MODEL_ROUTE
        and kwargs.get("messages") == [{"role": "user", "content": measurement.prompt}]
        and kwargs.get("tools") == [measurement.tool_schema]
        and kwargs.get("tool_choice") == forced_tool_choice(PROBE_TOOL_NAME)
        and kwargs.get("parallel_tool_calls") is PARALLEL_TOOL_CALLS
        and kwargs.get("stream") is False
        and kwargs.get("drop_params") is False
        and kwargs.get("max_tokens") == measurement.max_output_tokens
        and kwargs.get("num_retries") == _PROVIDER_RETRY_LIMIT
        and "temperature" not in kwargs
    )


_PROBE_LITELLM_FIXED_KEYS = frozenset(
    {"model", "messages", "tools", "tool_choice", "stream", "drop_params", "max_tokens"}
)


class _RecordingLiteLLMClient:
    def __init__(
        self,
        provider_completion: ProviderCompletion,
        request: ProposalCompletionRequest,
        expected_prepared_request_sha256: str,
        measurement: ProbeMeasurement,
    ) -> None:
        self._provider_completion = provider_completion
        self._proposal_request = request
        self._expected_prepared_request_sha256 = expected_prepared_request_sha256
        self._measurement = measurement
        self.call_count = 0
        self.request: RequestObservation | None = None
        self.failure: SafeProviderFailure | None = None

    async def acompletion(self, **kwargs: object) -> object:
        self.call_count += 1
        provider_kwargs = {
            name: value
            for name, value in kwargs.items()
            if name not in _PROBE_LITELLM_FIXED_KEYS
        }
        evidence = _proposal_request_evidence(
            request=self._proposal_request,
            messages=cast(list[dict[str, Any]], kwargs["messages"]),
            tool_schemas=cast(list[dict[str, Any]], kwargs["tools"]),
            provider_kwargs=provider_kwargs,
        )
        safe_request = _effective_values_identity(
            content_free_shape=_request_evidence_shape(evidence),
            effective_values=kwargs,
        )
        self.request = RequestObservation(
            controls_valid=_request_controls_are_exact(kwargs, self._measurement),
            effective_request=safe_request,
            expected_prepared_request_sha256=(self._expected_prepared_request_sha256),
        )
        try:
            return await self._provider_completion(**kwargs)
        except _PROVIDER_EXCEPTIONS as error:
            failure = classify_ai_builder_provider_failure(
                error,
                stage="proposal_completion",
            )
            parameter: FailureParameter | None = (
                "tools" if failure.parameter == "tools" else None
            )
            self.failure = SafeProviderFailure(
                kind=failure.kind,
                exception_class=failure.exception_class,
                status_code=failure.status_code,
                status_class=failure.status_class,
                parameter=parameter,
                remote_response_observed=_remote_response_observed(error),
            )
            raise


def _remote_response_observed(error: Exception) -> bool:
    """Trust only headers LiteLLM attached while mapping a transport response."""

    response_headers = getattr(error, "litellm_response_headers", None)
    return isinstance(response_headers, dict) and bool(
        cast(dict[object, object], response_headers)
    )


def _capability_request_value(measurement: ProbeMeasurement) -> dict[str, object]:
    return {
        "tool_schema": measurement.tool_schema,
        "schema_sha256": canonical_sha256(measurement.tool_schema),
        "tool_choice": forced_tool_choice(PROBE_TOOL_NAME),
        "parallel_tool_calls": False,
        "prompt": measurement.prompt,
        "prompt_sha256": hashlib.sha256(measurement.prompt.encode()).hexdigest(),
        "max_output_tokens": measurement.max_output_tokens,
    }


def _runtime_preflight_passes(identity: RuntimeIdentity) -> bool:
    return (
        identity.requested_model_id == PROBE_MODEL_ID
        and identity.resolved_model_id == PROBE_MODEL_ID
        and identity.resolved_model_name == PROBE_RESOLVED_MODEL_NAME
        and identity.litellm_model == PROBE_MODEL_ROUTE
        and identity.provider_type == "openai"
        and identity.enabled
        and not identity.deprecated
        and not identity.migrated
        and identity.supports_tool_calling
        and identity.supports_strict_tool_schema
        and identity.provider_active
    )


def _decide_verdict(
    *,
    source_before: SourceIdentity,
    source_after: SourceIdentity,
    runtime_before: RuntimeIdentity,
    runtime_after: RuntimeIdentity,
    outcome: ProbeCallOutcome,
) -> tuple[ProbeVerdict, tuple[str, ...]]:
    reasons: list[str] = []
    if not source_before.source_clean or not source_after.source_clean:
        reasons.append("source_not_clean")
    if source_before != source_after:
        reasons.append("source_identity_not_stable")
    if not _runtime_preflight_passes(runtime_before) or not _runtime_preflight_passes(
        runtime_after
    ):
        reasons.append("runtime_preflight_failed")
    if runtime_before != runtime_after:
        reasons.append("runtime_identity_not_stable")
    if outcome.call_count != 1:
        reasons.append("call_count_not_one")
    if outcome.request is None or not outcome.request.controls_valid:
        reasons.append("request_controls_not_exact")
    if reasons:
        return "inconclusive", tuple(sorted(set(reasons)))
    if outcome.response is not None:
        if outcome.response.finish_reason == "length":
            return "inconclusive", ("provider_completion_truncated",)
        if outcome.response.checks.all_pass:
            return "pass", ("strict_request_accepted_with_conformant_response",)
        return "inconclusive", ("provider_response_nonconformant",)
    failure = outcome.failure
    if failure is not None and failure.kind == "rejected":
        if (
            failure.remote_response_observed
            and failure.status_code in {400, 422}
            and failure.exception_class in {"bad_request", "unprocessable_entity"}
            and failure.parameter == "tools"
        ):
            return "fail", ("configured_route_rejected_strict_request",)
        if failure.remote_response_observed:
            return "inconclusive", ("provider_result_inconclusive",)
        return "inconclusive", ("request_rejection_without_remote_provenance",)
    return "inconclusive", ("provider_result_inconclusive",)


def build_receipt(
    *,
    source_before: SourceIdentity,
    source_after: SourceIdentity,
    runtime_before: RuntimeIdentity,
    runtime_after: RuntimeIdentity,
    outcome: ProbeCallOutcome,
    measurement: ProbeMeasurement | None = None,
) -> CapabilityReceipt:
    measured = measurement or default_measurement()
    verdict, reason_codes = _decide_verdict(
        source_before=source_before,
        source_after=source_after,
        runtime_before=runtime_before,
        runtime_after=runtime_after,
        outcome=outcome,
    )
    receipt = CapabilityReceipt(
        schema_version=RECEIPT_SCHEMA_VERSION,
        protocol=CapabilityProtocol(
            version=PROTOCOL_VERSION,
            fixed_model_id=PROBE_MODEL_ID,
            one_provider_call=True,
            provider_retry_limit=_PROVIDER_RETRY_LIMIT,
            mutates_product_or_session=False,
        ),
        source_before=source_before,
        source_after=source_after,
        runtime_before=runtime_before,
        runtime_after=runtime_after,
        request=CapabilityRequest.model_validate_json(
            json.dumps(_capability_request_value(measured))
        ),
        outcome=outcome,
        verdict=verdict,
        reason_codes=reason_codes,
        receipt_sha256="0" * 64,
    )
    digest = canonical_sha256(
        receipt.model_dump(mode="json", exclude={"receipt_sha256"})
    )
    return receipt.model_copy(update={"receipt_sha256": digest})


def write_receipt(output_dir: Path, receipt: CapabilityReceipt) -> Path:
    if output_dir.exists() or output_dir.is_symlink():
        raise FileExistsError("Receipt output directory must not already exist")
    # A receipt nobody can verify is not worth writing.
    if len(receipt.model_dump_json().encode()) > _MAX_RECEIPT_BYTES:
        raise ValueError("Receipt exceeds the size its verifier accepts")
    output_dir.mkdir(mode=0o700, parents=True, exist_ok=False)
    path = output_dir / "probe.json"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, 0o600)
    try:
        os.fchmod(descriptor, 0o600)
        encoded = receipt.model_dump_json().encode()
        with os.fdopen(descriptor, "wb", closefd=False) as receipt_file:
            receipt_file.write(encoded)
            receipt_file.flush()
            os.fsync(receipt_file.fileno())
    finally:
        os.close(descriptor)
    return path


def verify_receipt(path: Path) -> VerifiedReceipt:
    try:
        payload = read_bounded_file(path, limit=_MAX_RECEIPT_BYTES, mode=0o600)
    except ValueError as error:
        raise ReceiptVerificationError(str(error)) from error
    except OSError as error:
        raise ReceiptVerificationError("receipt is unreadable") from error
    try:
        receipt = CapabilityReceipt.model_validate_json(payload)
    except (OSError, ValidationError, ValueError) as error:
        raise ReceiptVerificationError(
            "receipt violates its strict contract"
        ) from error
    expected_hash = canonical_sha256(
        receipt.model_dump(mode="json", exclude={"receipt_sha256"})
    )
    if receipt.receipt_sha256 != expected_hash:
        raise ReceiptVerificationError("receipt hash does not match")
    verdict, reasons = _decide_verdict(
        source_before=receipt.source_before,
        source_after=receipt.source_after,
        runtime_before=receipt.runtime_before,
        runtime_after=receipt.runtime_after,
        outcome=receipt.outcome,
    )
    if (receipt.verdict, receipt.reason_codes) != (verdict, reasons):
        raise ReceiptVerificationError("verdict does not match sealed evidence")
    return VerifiedReceipt(
        verdict=verdict,
        receipt_sha256=receipt.receipt_sha256,
        reason_codes=reasons,
    )


def read_bounded_file(path: Path, *, limit: int, mode: int | None = None) -> bytes:
    """Read a regular file without blocking on it or exceeding one bound.

    Opened non-blocking so a FIFO or device never stalls the probe, checked
    through the open descriptor so the path cannot be swapped underneath, and
    read one byte past the limit so an oversized file is refused rather than
    silently truncated.
    """
    flags = os.O_RDONLY | getattr(os, "O_NONBLOCK", 0)
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags)
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise ValueError(f"{path.name} is not a regular file")
        if mode is not None and stat.S_IMODE(metadata.st_mode) != mode:
            raise ValueError(f"{path.name} mode must be {mode:04o}")
        payload = b""
        while len(payload) <= limit:
            # One read can return a short prefix; a truncated measurement must
            # never pass as the whole file.
            chunk = os.read(descriptor, limit + 1 - len(payload))
            if not chunk:
                break
            payload += chunk
    finally:
        os.close(descriptor)
    if len(payload) > limit:
        raise ValueError(f"{path.name} exceeds {limit} bytes")
    return payload


def _string_keyed_object(value: object) -> dict[str, object] | None:
    if not isinstance(value, dict):
        return None
    raw = cast(dict[object, object], value)
    if not all(isinstance(key, str) for key in raw):
        return None
    return cast(dict[str, object], raw)


def _passes_same_schema(
    arguments: dict[str, object],
    tool_schema: dict[str, object],
) -> bool:
    try:
        validate_propose_flow_tool_arguments(
            arguments=arguments,
            tool_schema=cast(ProposalToolSchema, tool_schema),
        )
    except (ProposalToolArgumentsError, jsonschema.SchemaError):
        return False
    return True


def evaluate_response(
    response: LLMCompletionResponse,
    measurement: ProbeMeasurement | None = None,
) -> ProbeResponseEvidence:
    measured = measurement or default_measurement()
    finish_reason: str | None = None
    tool_calls = ()
    if len(response.choices) == 1:
        choice = response.choices[0]
        finish_reason = choice.finish_reason
        tool_calls = choice.message.tool_calls
    single_call = (
        len(tool_calls) == 1 and tool_calls[0].function.name == PROBE_TOOL_NAME
    )
    if finish_reason == "length":
        return ProbeResponseEvidence(
            finish_reason=finish_reason,
            tool_call_count=len(tool_calls),
            tool_name=PROBE_TOOL_NAME if single_call else None,
            arguments=None,
            arguments_sha256=None,
            checks=ResponseChecks(
                same_schema_validation=False,
                single_forced_tool_call=single_call,
            ),
        )
    argument_text = tool_calls[0].function.arguments if len(tool_calls) == 1 else None
    parsed: dict[str, object] | None = None
    if argument_text and len(argument_text.encode()) <= _MAX_ARGUMENT_BYTES:
        try:
            parsed = _string_keyed_object(json.loads(argument_text))
        except json.JSONDecodeError:
            pass
    checks = ResponseChecks(
        same_schema_validation=(
            _passes_same_schema(parsed, measured.tool_schema)
            if parsed is not None
            else False
        ),
        single_forced_tool_call=single_call,
    )
    return ProbeResponseEvidence(
        finish_reason=finish_reason,
        tool_call_count=len(tool_calls),
        tool_name=PROBE_TOOL_NAME if single_call else None,
        arguments=dict(parsed) if parsed is not None and checks.all_pass else None,
        arguments_sha256=canonical_sha256(parsed) if parsed is not None else None,
        checks=checks,
    )


async def run_probe_call(
    *,
    route: ResolvedCompletionModelRoute,
    provider_completion: ProviderCompletion,
    measurement: ProbeMeasurement | None = None,
) -> ProbeCallOutcome:
    measured = measurement or default_measurement()
    probe_route = replace(
        route,
        litellm_kwargs=_sanitize_builder_route_kwargs(route.litellm_kwargs),
    )
    provider_kwargs = probe_route.prepare_provider_kwargs(ModelKwargs())
    for removed_key in (
        "drop_params",
        "response_format",
        "temperature",
        "parallel_tool_calls",
        "num_retries",
    ):
        provider_kwargs.pop(removed_key, None)
    request = ProposalCompletionRequest(
        message_groups=(
            ProposalMessageGroup(
                messages=({"role": "user", "content": measured.prompt},),
                kind="current_turn",
                protected=True,
            ),
        ),
        tool_schemas=cast(list[dict[str, Any]], [measured.tool_schema]),
        route=replace(probe_route, litellm_kwargs=dict(provider_kwargs)),
        target_kind=TargetKind.CREATE,
        max_output_tokens=measured.max_output_tokens,
        temperature=0.0,
        tool_choice=forced_tool_choice(PROBE_TOOL_NAME),
    )
    prepared_request: dict[str, object] = {
        **provider_kwargs,
        "model": probe_route.litellm_model,
        "messages": [{"role": "user", "content": measured.prompt}],
        "tools": [measured.tool_schema],
        "tool_choice": forced_tool_choice(PROBE_TOOL_NAME),
        "parallel_tool_calls": PARALLEL_TOOL_CALLS,
        "stream": False,
        "drop_params": False,
        "max_tokens": measured.max_output_tokens,
        "num_retries": _PROVIDER_RETRY_LIMIT,
    }
    client = _RecordingLiteLLMClient(
        provider_completion,
        request,
        expected_prepared_request_sha256=canonical_sha256(prepared_request),
        measurement=measured,
    )
    try:
        raw_response = await client.acompletion(**prepared_request)
    except _PROVIDER_EXCEPTIONS:
        if client.failure is None:
            raise RuntimeError("Provider failure escaped classification")
        return ProbeCallOutcome(
            call_count=client.call_count,
            request=client.request,
            response=None,
            failure=client.failure,
        )
    response = normalize_litellm_completion_response(raw_response)
    return ProbeCallOutcome(
        call_count=client.call_count,
        request=client.request,
        response=evaluate_response(response, measured),
        failure=None,
    )


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_identity_from_observations(*, revision: str, status: str) -> SourceIdentity:
    return SourceIdentity(
        revision=revision,
        source_clean=not status,
        runner_sha256=_file_sha256(Path(__file__)),
        lockfile_sha256=_file_sha256(backend_dir / "uv.lock"),
        litellm_version=importlib.metadata.version("litellm"),
    )


def _read_source_identity() -> SourceIdentity:
    repository_root = backend_dir.parent
    revision = subprocess.run(
        ["git", "-C", str(repository_root), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    status = subprocess.run(
        [
            "git",
            "-C",
            str(repository_root),
            "status",
            "--short",
            "--untracked-files=all",
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return source_identity_from_observations(revision=revision, status=status)


def _empty_runtime_identity(
    *,
    litellm_model: str = "unresolved",
    provider_type: str = "unresolved",
    route_kwargs: EffectiveValuesIdentity | None = None,
) -> RuntimeIdentity:
    kwargs = route_kwargs or _effective_values_identity(
        content_free_shape={},
        effective_values={},
    )
    return RuntimeIdentity(
        requested_model_id=PROBE_MODEL_ID,
        resolved_model_id="unresolved",
        resolved_model_name="unresolved",
        litellm_model=litellm_model,
        provider_type=provider_type,
        enabled=False,
        deprecated=False,
        migrated=False,
        supports_tool_calling=False,
        supports_strict_tool_schema=False,
        provider_active=False,
        sanitized_route_kwargs=kwargs,
        proposal_route_identity_sha256=_proposal_route_identity_sha256(
            litellm_model=litellm_model,
            provider_type=provider_type,
            route_kwargs=kwargs,
        ),
    )


async def _resolve_runtime_identity(
    tenant_id: str,
) -> tuple[RuntimeIdentity, ResolvedCompletionModelRoute]:
    settings = get_settings()
    sessionmanager.init(settings.database_url)
    async with sessionmanager.session() as session, session.begin():
        await session.execute(sa.text("SET TRANSACTION READ ONLY"))
        tenant = await TenantRepository(session).get(UUID(tenant_id))
        if tenant is None:
            raise RuntimeError("Probe tenant is unavailable")
        model = await CompletionModelRepository(session=session, tenant=tenant).one(
            UUID(PROBE_MODEL_ID)
        )
        route = await CompletionService(
            context_builder=ContextBuilder(),
            tenant=tenant,
            config=settings,
            session=session,
        ).resolve_model_route(model)
        route = replace(
            route,
            litellm_kwargs=_sanitize_builder_route_kwargs(route.litellm_kwargs),
        )
        safe_kwargs = _safe_route_kwargs_identity(route)
        identity = RuntimeIdentity(
            requested_model_id=PROBE_MODEL_ID,
            resolved_model_id=str(model.id),
            resolved_model_name=model.name,
            litellm_model=route.litellm_model,
            provider_type=route.provider_type,
            enabled=model.is_org_enabled,
            deprecated=model.is_deprecated,
            migrated=model.migrated_to_model_id is not None,
            supports_tool_calling=model.supports_tool_calling,
            supports_strict_tool_schema=route.supports_strict_tool_schema,
            provider_active=True,
            sanitized_route_kwargs=safe_kwargs,
            proposal_route_identity_sha256=_proposal_route_identity_sha256(
                litellm_model=route.litellm_model,
                provider_type=route.provider_type,
                route_kwargs=safe_kwargs,
            ),
        )
        return identity, route


SourceReader = Callable[[], SourceIdentity]
RuntimeResolver = Callable[
    [str], Awaitable[tuple[RuntimeIdentity, ResolvedCompletionModelRoute]]
]


async def run_live_probe(
    *,
    output_dir: Path,
    tenant_id: str,
    source_reader: SourceReader = _read_source_identity,
    runtime_resolver: RuntimeResolver = _resolve_runtime_identity,
    provider_completion: ProviderCompletion = _litellm_provider_completion,
    measurement: ProbeMeasurement | None = None,
) -> Path:
    if output_dir.resolve().is_relative_to(backend_dir.parent.resolve()):
        raise ValueError("Live receipt output must be outside the source checkout")
    measured = measurement or default_measurement()
    source_before = source_reader()
    runtime_before = _empty_runtime_identity()
    outcome = ProbeCallOutcome(call_count=0, request=None, response=None, failure=None)
    if source_before.source_clean:
        runtime_before, route = await runtime_resolver(tenant_id)
        if _runtime_preflight_passes(runtime_before):
            outcome = await run_probe_call(
                route=route,
                provider_completion=provider_completion,
                measurement=measured,
            )
    runtime_after = (
        (await runtime_resolver(tenant_id))[0]
        if outcome.call_count == 1
        else runtime_before
    )
    source_after = source_reader()
    return write_receipt(
        output_dir,
        build_receipt(
            source_before=source_before,
            source_after=source_after,
            runtime_before=runtime_before,
            runtime_after=runtime_after,
            outcome=outcome,
            measurement=measured,
        ),
    )


def parse_args(argv: list[str] | None = None) -> ProbeArguments:
    parser = ArgumentParser(
        description=(
            "Measure pinned-Luna strict-tool provider capability or verify its receipt. "
            "The live request uses the fixed synthetic schema, prompt and output cap "
            "unless the matching Builder ones are supplied."
        )
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--output-dir", type=Path)
    mode.add_argument("--verify-receipt", type=Path)
    parser.add_argument("--tool-schema-file", type=Path, default=None)
    parser.add_argument("--prompt-file", type=Path, default=None)
    parser.add_argument(
        "--max-output-tokens",
        type=int,
        default=_DEFAULT_MAX_OUTPUT_TOKENS,
    )
    parsed = parser.parse_args(argv)
    live_only = (
        parsed.tool_schema_file is not None
        or parsed.prompt_file is not None
        or parsed.max_output_tokens != _DEFAULT_MAX_OUTPUT_TOKENS
    )
    if live_only and parsed.output_dir is None:
        parser.error("measurement options only apply to a live --output-dir run")
    if not 1 <= parsed.max_output_tokens <= _MAX_OUTPUT_TOKEN_CEILING:
        parser.error(
            f"--max-output-tokens must be between 1 and {_MAX_OUTPUT_TOKEN_CEILING}"
        )
    return ProbeArguments(
        output_dir=cast(Path | None, parsed.output_dir),
        verify_receipt=cast(Path | None, parsed.verify_receipt),
        tool_schema_file=cast(Path | None, parsed.tool_schema_file),
        prompt_file=cast(Path | None, parsed.prompt_file),
        max_output_tokens=cast(int, parsed.max_output_tokens),
    )


def measurement_from_arguments(arguments: ProbeArguments) -> ProbeMeasurement:
    """Build the request this run measures from the caller's files, or the default.

    A supplied schema and prompt are sealed verbatim, so a verified receipt
    covers that exact schema, prompt and output cap under the probe's own fixed
    transport controls.
    """

    return ProbeMeasurement(
        tool_schema=(
            _load_json_object(arguments.tool_schema_file)
            if arguments.tool_schema_file is not None
            else synthetic_tool_schema()
        ),
        prompt=(
            _read_bounded_text(arguments.prompt_file)
            if arguments.prompt_file is not None
            else PROBE_PROMPT
        ),
        max_output_tokens=arguments.max_output_tokens,
    )


def _read_bounded_text(path: Path) -> str:
    return read_bounded_file(path, limit=_MAX_MEASUREMENT_INPUT_BYTES).decode("utf-8")


def _load_json_object(path: Path) -> dict[str, object]:
    schema = _string_keyed_object(json.loads(_read_bounded_text(path)))
    if schema is None:
        raise ValueError("Tool schema file must contain a JSON object")
    return schema


def _exit_code(verdict: ProbeVerdict) -> int:
    return 0 if verdict == "pass" else 1 if verdict == "fail" else 2


async def _run_live(arguments: ProbeArguments) -> int:
    if arguments.output_dir is None:
        raise RuntimeError("Live probe output directory is missing")
    tenant_id = os.environ.get("ENEO_TENANT_ID")
    if tenant_id is None:
        raise RuntimeError("ENEO_TENANT_ID is required for the live probe")
    measurement = measurement_from_arguments(arguments)
    try:
        verified = verify_receipt(
            await run_live_probe(
                output_dir=arguments.output_dir,
                tenant_id=tenant_id,
                measurement=measurement,
            )
        )
    finally:
        await sessionmanager.close()
    print(
        f"{verified.verdict.upper()} capability receipt "
        f"sha256={verified.receipt_sha256}"
    )
    return _exit_code(verified.verdict)


def main(argv: list[str] | None = None) -> int:
    arguments = parse_args(argv)
    if arguments.verify_receipt is not None:
        verified = verify_receipt(arguments.verify_receipt)
        print(
            f"{verified.verdict.upper()} capability receipt verified "
            f"sha256={verified.receipt_sha256}"
        )
        return _exit_code(verified.verdict)
    return asyncio.run(_run_live(arguments))


if __name__ == "__main__":
    raise SystemExit(main())

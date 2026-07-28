"""Tenant policy bounding how much retrieved passage text a step records."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final, Literal, Protocol, cast

from eneo.main.exceptions import BadRequestException

RAG_EVIDENCE_SETTINGS_KEY: Final[str] = "rag_evidence"
RAG_EVIDENCE_STORAGE_VERSION: Final[Literal[1]] = 1
RAG_EVIDENCE_VERSION_KEY: Final[str] = "version"
RAG_EVIDENCE_MAX_SOURCES_KEY: Final[str] = "max_sources_with_recorded_passages"
RAG_EVIDENCE_MAX_PASSAGES_PER_SOURCE_KEY: Final[str] = (
    "max_recorded_passages_per_source"
)
RAG_EVIDENCE_MAX_PASSAGE_BYTES_KEY: Final[str] = "max_recorded_passage_bytes"
RAG_EVIDENCE_MAX_STEP_PASSAGE_BYTES_KEY: Final[str] = (
    "max_recorded_passage_bytes_per_step"
)
RAG_EVIDENCE_MAX_RUN_VIEW_PASSAGE_BYTES_KEY: Final[str] = (
    "max_recorded_passage_bytes_per_run_view"
)
RAG_EVIDENCE_BUSINESS_KEYS: Final[frozenset[str]] = frozenset(
    {
        RAG_EVIDENCE_MAX_SOURCES_KEY,
        RAG_EVIDENCE_MAX_PASSAGES_PER_SOURCE_KEY,
        RAG_EVIDENCE_MAX_PASSAGE_BYTES_KEY,
        RAG_EVIDENCE_MAX_STEP_PASSAGE_BYTES_KEY,
        RAG_EVIDENCE_MAX_RUN_VIEW_PASSAGE_BYTES_KEY,
    }
)
RAG_EVIDENCE_KEYS: Final[frozenset[str]] = frozenset(
    {RAG_EVIDENCE_VERSION_KEY, *RAG_EVIDENCE_BUSINESS_KEYS}
)

DEFAULT_MAX_SOURCES_WITH_RECORDED_PASSAGES: Final[int] = 25
DEFAULT_MAX_RECORDED_PASSAGES_PER_SOURCE: Final[int] = 5
DEFAULT_MAX_RECORDED_PASSAGE_BYTES: Final[int] = 4_096
DEFAULT_MAX_RECORDED_PASSAGE_BYTES_PER_STEP: Final[int] = 131_072
# A run holds one budget per *attempt*, and attempts are unbounded, so the
# per-step bound alone does not bound what an interactive view materialises.
DEFAULT_MAX_RECORDED_PASSAGE_BYTES_PER_RUN_VIEW: Final[int] = 2_097_152

# Upper bounds an organization administrator cannot exceed. Recorded passages
# are verbatim source text held in run evidence, so an unbounded setting would
# turn a transparency feature into an unbounded retention surface.
RAG_EVIDENCE_CEILINGS: Final[dict[str, int]] = {
    RAG_EVIDENCE_MAX_SOURCES_KEY: 500,
    RAG_EVIDENCE_MAX_PASSAGES_PER_SOURCE_KEY: 50,
    RAG_EVIDENCE_MAX_PASSAGE_BYTES_KEY: 65_536,
    RAG_EVIDENCE_MAX_STEP_PASSAGE_BYTES_KEY: 4_194_304,
    RAG_EVIDENCE_MAX_RUN_VIEW_PASSAGE_BYTES_KEY: 16_777_216,
}

RAG_EVIDENCE_POLICY_INVALID_CODE: Final[str] = "flow_rag_evidence_policy_invalid"
RAG_EVIDENCE_POLICY_UNKNOWN_FIELD_CODE: Final[str] = (
    "flow_rag_evidence_policy_unknown_field"
)
RAG_EVIDENCE_POLICY_VERSION_UNSUPPORTED_CODE: Final[str] = (
    "flow_rag_evidence_policy_version_unsupported"
)


@dataclass(frozen=True, slots=True)
class FlowRagEvidencePolicy:
    version: Literal[1] = RAG_EVIDENCE_STORAGE_VERSION
    max_sources_with_recorded_passages: int = DEFAULT_MAX_SOURCES_WITH_RECORDED_PASSAGES
    max_recorded_passages_per_source: int = DEFAULT_MAX_RECORDED_PASSAGES_PER_SOURCE
    max_recorded_passage_bytes: int = DEFAULT_MAX_RECORDED_PASSAGE_BYTES
    max_recorded_passage_bytes_per_step: int = (
        DEFAULT_MAX_RECORDED_PASSAGE_BYTES_PER_STEP
    )
    max_recorded_passage_bytes_per_run_view: int = (
        DEFAULT_MAX_RECORDED_PASSAGE_BYTES_PER_RUN_VIEW
    )


class FlowRagEvidencePolicySource(Protocol):
    async def get_rag_evidence_policy(self) -> object: ...


async def resolve_flow_rag_evidence_policy_from_source(
    source: FlowRagEvidencePolicySource | None,
) -> FlowRagEvidencePolicy:
    if source is None:
        return FlowRagEvidencePolicy()
    loader = getattr(source, "get_rag_evidence_policy", None)
    if loader is None:
        return FlowRagEvidencePolicy()
    policy = await loader()
    defaults = FlowRagEvidencePolicy()
    return FlowRagEvidencePolicy(
        version=getattr(policy, "version", RAG_EVIDENCE_STORAGE_VERSION),
        max_sources_with_recorded_passages=getattr(
            policy,
            RAG_EVIDENCE_MAX_SOURCES_KEY,
            defaults.max_sources_with_recorded_passages,
        ),
        max_recorded_passages_per_source=getattr(
            policy,
            RAG_EVIDENCE_MAX_PASSAGES_PER_SOURCE_KEY,
            defaults.max_recorded_passages_per_source,
        ),
        max_recorded_passage_bytes=getattr(
            policy,
            RAG_EVIDENCE_MAX_PASSAGE_BYTES_KEY,
            defaults.max_recorded_passage_bytes,
        ),
        max_recorded_passage_bytes_per_step=getattr(
            policy,
            RAG_EVIDENCE_MAX_STEP_PASSAGE_BYTES_KEY,
            defaults.max_recorded_passage_bytes_per_step,
        ),
        max_recorded_passage_bytes_per_run_view=getattr(
            policy,
            RAG_EVIDENCE_MAX_RUN_VIEW_PASSAGE_BYTES_KEY,
            defaults.max_recorded_passage_bytes_per_run_view,
        ),
    )


def _parse_bounded_int(value: object, field_name: str) -> int:
    if type(value) is not int:
        raise BadRequestException(
            f"{field_name} must be an integer.",
            code=RAG_EVIDENCE_POLICY_INVALID_CODE,
        )
    if value < 1:
        raise BadRequestException(
            f"{field_name} must be greater than zero.",
            code=RAG_EVIDENCE_POLICY_INVALID_CODE,
        )
    ceiling = RAG_EVIDENCE_CEILINGS[field_name]
    if value > ceiling:
        raise BadRequestException(
            f"{field_name} must not exceed {ceiling}.",
            code=RAG_EVIDENCE_POLICY_INVALID_CODE,
        )
    return value


def validate_flow_rag_evidence_policy_object(policy: object) -> dict[str, Any]:
    if not isinstance(policy, dict):
        raise BadRequestException(
            "flow_settings.rag_evidence must be an object.",
            code=RAG_EVIDENCE_POLICY_INVALID_CODE,
        )
    policy_dict = cast(dict[str, Any], policy)
    unknown = set(policy_dict) - RAG_EVIDENCE_KEYS
    if unknown:
        raise BadRequestException(
            "Unsupported knowledge evidence policy fields: "
            + ", ".join(sorted(unknown)),
            code=RAG_EVIDENCE_POLICY_UNKNOWN_FIELD_CODE,
        )
    version = policy_dict.get(RAG_EVIDENCE_VERSION_KEY, RAG_EVIDENCE_STORAGE_VERSION)
    if type(version) is not int or version != RAG_EVIDENCE_STORAGE_VERSION:
        raise BadRequestException(
            "flow_settings.rag_evidence.version must be 1.",
            code=RAG_EVIDENCE_POLICY_VERSION_UNSUPPORTED_CODE,
        )
    for field_name in RAG_EVIDENCE_BUSINESS_KEYS:
        if field_name in policy_dict:
            _parse_bounded_int(policy_dict[field_name], field_name)
    return policy_dict


def _extract_rag_evidence_policy(
    tenant_flow_settings: dict[str, Any] | None,
) -> dict[str, Any]:
    if not isinstance(tenant_flow_settings, dict):
        return {}
    raw = tenant_flow_settings.get(RAG_EVIDENCE_SETTINGS_KEY)
    if not isinstance(raw, dict):
        return {}
    raw_dict = cast(dict[str, Any], raw)
    try:
        return validate_flow_rag_evidence_policy_object(raw_dict)
    except BadRequestException:
        # A corrupt stored policy falls back to the safe defaults rather than
        # recording unbounded passage text.
        return {}


def _bounded_or_default(raw: dict[str, Any], field_name: str, default: int) -> int:
    value = raw.get(field_name)
    if value is None:
        return default
    return _parse_bounded_int(value, field_name)


def resolve_flow_rag_evidence_policy(
    tenant_flow_settings: dict[str, Any] | None,
) -> FlowRagEvidencePolicy:
    raw = _extract_rag_evidence_policy(tenant_flow_settings)
    return FlowRagEvidencePolicy(
        max_sources_with_recorded_passages=_bounded_or_default(
            raw,
            RAG_EVIDENCE_MAX_SOURCES_KEY,
            DEFAULT_MAX_SOURCES_WITH_RECORDED_PASSAGES,
        ),
        max_recorded_passages_per_source=_bounded_or_default(
            raw,
            RAG_EVIDENCE_MAX_PASSAGES_PER_SOURCE_KEY,
            DEFAULT_MAX_RECORDED_PASSAGES_PER_SOURCE,
        ),
        max_recorded_passage_bytes=_bounded_or_default(
            raw,
            RAG_EVIDENCE_MAX_PASSAGE_BYTES_KEY,
            DEFAULT_MAX_RECORDED_PASSAGE_BYTES,
        ),
        max_recorded_passage_bytes_per_step=_bounded_or_default(
            raw,
            RAG_EVIDENCE_MAX_STEP_PASSAGE_BYTES_KEY,
            DEFAULT_MAX_RECORDED_PASSAGE_BYTES_PER_STEP,
        ),
        max_recorded_passage_bytes_per_run_view=_bounded_or_default(
            raw,
            RAG_EVIDENCE_MAX_RUN_VIEW_PASSAGE_BYTES_KEY,
            DEFAULT_MAX_RECORDED_PASSAGE_BYTES_PER_RUN_VIEW,
        ),
    )


def apply_flow_rag_evidence_policy_patch(
    current_flow_settings: dict[str, Any] | None,
    *,
    max_sources_with_recorded_passages: int | None = None,
    max_recorded_passages_per_source: int | None = None,
    max_recorded_passage_bytes: int | None = None,
    max_recorded_passage_bytes_per_step: int | None = None,
    max_recorded_passage_bytes_per_run_view: int | None = None,
    remove_keys: set[str] | None = None,
) -> dict[str, Any]:
    result = (
        dict(current_flow_settings) if isinstance(current_flow_settings, dict) else {}
    )
    next_policy = _extract_rag_evidence_policy(result)
    updates = {
        RAG_EVIDENCE_MAX_SOURCES_KEY: max_sources_with_recorded_passages,
        RAG_EVIDENCE_MAX_PASSAGES_PER_SOURCE_KEY: max_recorded_passages_per_source,
        RAG_EVIDENCE_MAX_PASSAGE_BYTES_KEY: max_recorded_passage_bytes,
        RAG_EVIDENCE_MAX_STEP_PASSAGE_BYTES_KEY: max_recorded_passage_bytes_per_step,
        RAG_EVIDENCE_MAX_RUN_VIEW_PASSAGE_BYTES_KEY: (
            max_recorded_passage_bytes_per_run_view
        ),
    }
    for field_name, value in updates.items():
        if value is not None:
            next_policy[field_name] = _parse_bounded_int(value, field_name)
    for field_name in remove_keys or ():
        if field_name not in RAG_EVIDENCE_BUSINESS_KEYS:
            raise BadRequestException(
                f"Unsupported knowledge evidence policy field: {field_name}.",
                code=RAG_EVIDENCE_POLICY_UNKNOWN_FIELD_CODE,
            )
        next_policy.pop(field_name, None)
    if any(field_name in next_policy for field_name in RAG_EVIDENCE_BUSINESS_KEYS):
        next_policy[RAG_EVIDENCE_VERSION_KEY] = RAG_EVIDENCE_STORAGE_VERSION
        validate_flow_rag_evidence_policy_object(next_policy)
        result[RAG_EVIDENCE_SETTINGS_KEY] = next_policy
    else:
        result.pop(RAG_EVIDENCE_SETTINGS_KEY, None)
    return result

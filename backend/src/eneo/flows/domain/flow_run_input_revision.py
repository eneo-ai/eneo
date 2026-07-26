from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Annotated, Literal, TypeAlias, cast

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    TypeAdapter,
    ValidationError,
)

from eneo.flows.domain.canonical_json_hash import canonical_json_hash
from eneo.json_types import JsonObject

_CANONICAL_HASH_PATTERN = re.compile(r"[0-9a-f]{64}")
_JSON_OBJECT_ADAPTER = TypeAdapter(JsonObject)


class FlowRunInputRevisionTracked(BaseModel):
    """What one rerun did to a run's inputs.

    The run row keeps only the current payload, so without this the chain from
    the original submission to the values a step actually consumed cannot be
    rebuilt. Recording the prior payload rather than the resulting one means
    every revision is recoverable by walking the reruns in order and finishing
    at the run row.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal["tracked"]
    prior_input_hash: str
    resulting_input_hash: str
    changed_paths: tuple[str, ...]
    prior_input_payload: JsonObject | None


class FlowRunInputRevisionNotRecorded(BaseModel):
    """Revision evidence predates tracking or never reached acceptance."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal["not_recorded"]


class FlowRunInputRevisionUnavailable(BaseModel):
    """Persisted revision evidence exists but cannot be read safely."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal["unavailable"]
    reason: Literal["invalid_persisted_revision"]


FlowRunInputRevision: TypeAlias = Annotated[
    FlowRunInputRevisionTracked
    | FlowRunInputRevisionNotRecorded
    | FlowRunInputRevisionUnavailable,
    Field(discriminator="status"),
]


def canonical_input_hash(payload: Mapping[str, object] | None) -> str:
    """Hash a run input payload so equal inputs hash equal regardless of order.

    A missing payload and an empty one are deliberately distinct: the first
    means no inputs were supplied, the second means an empty object was.
    """
    return canonical_json_hash(None if payload is None else dict(payload))


def changed_input_paths(
    prior: Mapping[str, object] | None,
    resulting: Mapping[str, object] | None,
) -> tuple[str, ...]:
    """Dotted paths whose value differs, including added and removed keys.

    Nested objects are walked so a caller can see which field changed rather
    than only that the payload did. Lists are compared whole: an index-level
    diff would name positions that mean nothing once a list is reordered.
    """
    paths: list[str] = []
    _collect_changed_paths(
        {} if prior is None else prior,
        {} if resulting is None else resulting,
        prefix="",
        into=paths,
    )
    return tuple(sorted(paths))


def _collect_changed_paths(
    prior: object,
    resulting: object,
    *,
    prefix: str,
    into: list[str],
) -> None:
    if isinstance(prior, Mapping) and isinstance(resulting, Mapping):
        prior_items = cast(Mapping[object, object], prior).items()
        resulting_items = cast(Mapping[object, object], resulting).items()
        prior_map: dict[str, object] = {str(k): v for k, v in prior_items}
        resulting_map: dict[str, object] = {str(k): v for k, v in resulting_items}
        for key in sorted(set(prior_map) | set(resulting_map)):
            _collect_changed_paths(
                prior_map.get(key, _MISSING),
                resulting_map.get(key, _MISSING),
                prefix=f"{prefix}.{key}" if prefix else key,
                into=into,
            )
        return
    if prior != resulting and prefix:
        into.append(prefix)


class _Missing:
    """Distinguishes an absent key from a key explicitly set to null."""

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "<missing>"

    def __eq__(self, other: object) -> bool:
        return other is self

    def __hash__(self) -> int:
        return hash(_Missing)


_MISSING = _Missing()


def build_flow_run_input_revision(
    *,
    prior: Mapping[str, JsonValue] | None,
    resulting: Mapping[str, JsonValue] | None,
) -> FlowRunInputRevisionTracked:
    """Record one input revision, keeping the prior payload so it stays rebuildable.

    The prior payload is stored verbatim. It is the same class of data the run
    row already holds in ``input_payload_json``, on a row that cascade-deletes
    with the run, so it inherits the run's retention rather than creating a new
    place inputs outlive their flow.
    """
    return FlowRunInputRevisionTracked(
        status="tracked",
        prior_input_hash=canonical_input_hash(prior),
        resulting_input_hash=canonical_input_hash(resulting),
        changed_paths=changed_input_paths(prior, resulting),
        prior_input_payload=None if prior is None else dict(prior),
    )


def parse_flow_run_input_revision(
    *,
    prior_input_hash: object,
    resulting_input_hash: object,
    changed_input_paths: object,
    prior_input_payload: object,
) -> FlowRunInputRevision:
    """Read one revision without letting a malformed row hide other evidence."""

    persisted_values = (
        prior_input_hash,
        resulting_input_hash,
        changed_input_paths,
        prior_input_payload,
    )
    if all(value is None for value in persisted_values):
        return FlowRunInputRevisionNotRecorded(status="not_recorded")

    if not (
        isinstance(prior_input_hash, str)
        and _CANONICAL_HASH_PATTERN.fullmatch(prior_input_hash)
        and isinstance(resulting_input_hash, str)
        and _CANONICAL_HASH_PATTERN.fullmatch(resulting_input_hash)
    ):
        return _unavailable_revision()

    paths = _parse_changed_input_paths(changed_input_paths)
    if paths is None:
        return _unavailable_revision()

    if prior_input_payload is None:
        payload = None
    else:
        try:
            payload = _JSON_OBJECT_ADAPTER.validate_python(
                prior_input_payload,
                strict=True,
            )
        except ValidationError:
            return _unavailable_revision()

    if canonical_input_hash(payload) != prior_input_hash:
        return _unavailable_revision()

    return FlowRunInputRevisionTracked(
        status="tracked",
        prior_input_hash=prior_input_hash,
        resulting_input_hash=resulting_input_hash,
        changed_paths=paths,
        prior_input_payload=payload,
    )


def _parse_changed_input_paths(value: object) -> tuple[str, ...] | None:
    if not isinstance(value, list):
        return None

    paths: list[str] = []
    for item in cast(list[object], value):
        if not isinstance(item, str) or not item:
            return None
        paths.append(item)

    parsed = tuple(paths)
    return parsed if parsed == tuple(sorted(set(parsed))) else None


def _unavailable_revision() -> FlowRunInputRevisionUnavailable:
    return FlowRunInputRevisionUnavailable(
        status="unavailable",
        reason="invalid_persisted_revision",
    )


__all__ = [
    "FlowRunInputRevision",
    "FlowRunInputRevisionNotRecorded",
    "FlowRunInputRevisionTracked",
    "FlowRunInputRevisionUnavailable",
    "build_flow_run_input_revision",
    "canonical_input_hash",
    "changed_input_paths",
    "parse_flow_run_input_revision",
]

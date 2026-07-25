from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import cast

from pydantic import JsonValue

from eneo.flows.assistant_execution_snapshot import stable_hash
from eneo.json_types import JsonObject

FLOW_RUN_INPUT_REVISION_SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class FlowRunInputRevision:
    """What one rerun did to a run's inputs.

    The run row keeps only the current payload, so without this the chain from
    the original submission to the values a step actually consumed cannot be
    rebuilt. Recording the prior payload rather than the resulting one means
    every revision is recoverable by walking the reruns in order and finishing
    at the run row.
    """

    prior_input_hash: str
    resulting_input_hash: str
    changed_paths: tuple[str, ...]
    prior_input_payload: JsonObject | None

    @property
    def changed(self) -> bool:
        return self.prior_input_hash != self.resulting_input_hash


def canonical_input_hash(payload: Mapping[str, object] | None) -> str:
    """Hash a run input payload so equal inputs hash equal regardless of order.

    A missing payload and an empty one are deliberately distinct: the first
    means no inputs were supplied, the second means an empty object was.
    """
    return stable_hash(None if payload is None else dict(payload))


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
    _collect_changed_paths(prior, resulting, prefix="", into=paths)
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
    prior: Mapping[str, object] | None,
    resulting: Mapping[str, object] | None,
) -> FlowRunInputRevision:
    """Record one input revision, keeping the prior payload so it stays rebuildable.

    The prior payload is stored verbatim. It is the same class of data the run
    row already holds in ``input_payload_json``, on a row that cascade-deletes
    with the run, so it inherits the run's retention rather than creating a new
    place inputs outlive their flow.
    """
    return FlowRunInputRevision(
        prior_input_hash=canonical_input_hash(prior),
        resulting_input_hash=canonical_input_hash(resulting),
        changed_paths=changed_input_paths(prior, resulting),
        prior_input_payload=_as_json_object(prior),
    )


def _as_json_object(payload: Mapping[str, object] | None) -> JsonObject | None:
    if payload is None:
        return None
    return {str(key): _as_json_value(value) for key, value in payload.items()}


def _as_json_value(value: object) -> JsonValue:
    if isinstance(value, Mapping):
        mapping = cast(Mapping[object, object], value)
        return {str(key): _as_json_value(item) for key, item in mapping.items()}
    if isinstance(value, (list, tuple)):
        items = cast(Sequence[object], value)
        return [_as_json_value(item) for item in items]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


__all__ = [
    "FLOW_RUN_INPUT_REVISION_SCHEMA_VERSION",
    "FlowRunInputRevision",
    "build_flow_run_input_revision",
    "canonical_input_hash",
    "changed_input_paths",
]

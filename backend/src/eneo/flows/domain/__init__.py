"""Canonical Flow domain exports."""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING

_EXPORTS: dict[str, tuple[str, str]] = {
    "Flow": ("eneo.flows.domain.flow", "Flow"),
    "FlowSparse": ("eneo.flows.domain.flow", "FlowSparse"),
    "FlowStep": ("eneo.flows.domain.flow", "FlowStep"),
    "FlowVersion": ("eneo.flows.domain.flow", "FlowVersion"),
    "FlowRun": ("eneo.flows.domain.flow", "FlowRun"),
    "FlowRunReviewCheckpoint": (
        "eneo.flows.domain.flow",
        "FlowRunReviewCheckpoint",
    ),
    "FlowRunReviewCheckpointState": (
        "eneo.flows.domain.flow",
        "FlowRunReviewCheckpointState",
    ),
    "FlowRunStatus": ("eneo.flows.domain.flow", "FlowRunStatus"),
    "FlowStepResult": ("eneo.flows.domain.flow", "FlowStepResult"),
    "FlowStepResultStatus": (
        "eneo.flows.domain.flow",
        "FlowStepResultStatus",
    ),
    "FlowStepAttempt": ("eneo.flows.domain.flow", "FlowStepAttempt"),
    "FlowStepAttemptStatus": (
        "eneo.flows.domain.flow",
        "FlowStepAttemptStatus",
    ),
    "FlowTemplateAsset": ("eneo.flows.domain.flow", "FlowTemplateAsset"),
    "FlowTemplateAssetStatus": (
        "eneo.flows.domain.flow",
        "FlowTemplateAssetStatus",
    ),
}

if TYPE_CHECKING:
    from eneo.flows.domain.flow import (
        Flow,
        FlowRun,
        FlowRunReviewCheckpoint,
        FlowRunReviewCheckpointState,
        FlowRunStatus,
        FlowSparse,
        FlowStep,
        FlowStepAttempt,
        FlowStepAttemptStatus,
        FlowStepResult,
        FlowStepResultStatus,
        FlowTemplateAsset,
        FlowTemplateAssetStatus,
        FlowVersion,
    )

__all__ = [
    "Flow",
    "FlowSparse",
    "FlowStep",
    "FlowVersion",
    "FlowRun",
    "FlowRunReviewCheckpoint",
    "FlowRunReviewCheckpointState",
    "FlowRunStatus",
    "FlowStepResult",
    "FlowStepResultStatus",
    "FlowStepAttempt",
    "FlowStepAttemptStatus",
    "FlowTemplateAsset",
    "FlowTemplateAssetStatus",
]


def __getattr__(name: str):
    try:
        module_name, attr_name = _EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc

    module = import_module(module_name)
    value = getattr(module, attr_name)
    globals()[name] = value
    return value

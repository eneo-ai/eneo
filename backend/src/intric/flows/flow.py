"""Compatibility shim for Flow domain models."""

from intric.flows.domain.flow import (
    Flow,
    FlowRun,
    FlowRunStatus,
    FlowRuntimeInputConfig,
    FlowSparse,
    FlowStep,
    FlowStepAttempt,
    FlowStepAttemptStatus,
    FlowStepResult,
    FlowStepResultStatus,
    FlowTemplateAsset,
    FlowTemplateAssetStatus,
    FlowVersion,
    JsonObject,
    ToolCallMetadata,
)

__all__ = [
    "Flow",
    "FlowRun",
    "FlowRunStatus",
    "FlowRuntimeInputConfig",
    "FlowSparse",
    "FlowStep",
    "FlowStepAttempt",
    "FlowStepAttemptStatus",
    "FlowStepResult",
    "FlowStepResultStatus",
    "FlowTemplateAsset",
    "FlowTemplateAssetStatus",
    "FlowVersion",
    "JsonObject",
    "ToolCallMetadata",
]

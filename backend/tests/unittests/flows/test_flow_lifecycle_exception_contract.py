from __future__ import annotations

import inspect
from types import ModuleType
from typing import TypeGuard, get_args

from intric.flows.domain import rerun_exceptions, review_checkpoint_exceptions
from intric.flows.domain.rerun_exceptions import (
    FLOW_RUN_RERUN_LIFECYCLE_FAILURE_CLASSES,
    FLOW_RUN_RERUN_RUNTIME_INVARIANT_CLASSES,
    FlowRunRerunLifecycleError,
    FlowRunRerunLifecycleFailure,
    FlowRunRerunRuntimeInvariantError,
    FlowRunRerunRuntimeInvariantFailure,
)
from intric.flows.domain.review_checkpoint_exceptions import (
    FLOW_REVIEW_CHECKPOINT_LIFECYCLE_FAILURE_CLASSES,
    FLOW_REVIEW_CHECKPOINT_OPEN_TERMINAL_INVARIANT_CLASSES,
    FLOW_REVIEW_CHECKPOINT_RUNTIME_INVARIANT_CLASSES,
    FlowReviewCheckpointLifecycleError,
    FlowReviewCheckpointLifecycleFailure,
    FlowReviewCheckpointOpenTerminalInvariantFailure,
    FlowReviewCheckpointRuntimeInvariantError,
    FlowReviewCheckpointRuntimeInvariantFailure,
)


def _is_exception_class(value: object) -> TypeGuard[type[Exception]]:
    return isinstance(value, type) and issubclass(value, Exception)


def _union_exception_classes(type_alias: object) -> frozenset[type[Exception]]:
    classes = get_args(type_alias)
    assert all(_is_exception_class(item) for item in classes)
    return frozenset(classes)


def _module_exception_classes(
    *,
    module: ModuleType,
    base_class: type[Exception],
) -> frozenset[type[Exception]]:
    return frozenset(
        cls
        for _, cls in inspect.getmembers(module, inspect.isclass)
        if cls is not base_class
        and cls.__module__ == module.__name__
        and issubclass(cls, base_class)
    )


def _class_names(classes: frozenset[type[Exception]]) -> frozenset[str]:
    return frozenset(cls.__name__ for cls in classes)


def _class_diff_message(
    *,
    actual: frozenset[type[Exception]],
    expected: frozenset[type[Exception]],
) -> str:
    return (
        f"missing={sorted(_class_names(expected - actual))}; "
        f"extra={sorted(_class_names(actual - expected))}"
    )


def test_rerun_lifecycle_failure_classes_match_union() -> None:
    actual = frozenset(FLOW_RUN_RERUN_LIFECYCLE_FAILURE_CLASSES)
    expected = _union_exception_classes(FlowRunRerunLifecycleFailure)

    assert actual == expected, _class_diff_message(actual=actual, expected=expected)


def test_rerun_lifecycle_failure_classes_include_all_domain_subclasses() -> None:
    actual = frozenset(FLOW_RUN_RERUN_LIFECYCLE_FAILURE_CLASSES)
    expected = _module_exception_classes(
        module=rerun_exceptions,
        base_class=FlowRunRerunLifecycleError,
    )

    assert actual == expected, _class_diff_message(actual=actual, expected=expected)


def test_rerun_runtime_invariant_classes_match_union() -> None:
    actual = frozenset(FLOW_RUN_RERUN_RUNTIME_INVARIANT_CLASSES)
    expected = _union_exception_classes(FlowRunRerunRuntimeInvariantFailure)

    assert actual == expected, _class_diff_message(actual=actual, expected=expected)


def test_rerun_runtime_invariant_classes_include_all_domain_subclasses() -> None:
    actual = frozenset(FLOW_RUN_RERUN_RUNTIME_INVARIANT_CLASSES)
    expected = _module_exception_classes(
        module=rerun_exceptions,
        base_class=FlowRunRerunRuntimeInvariantError,
    )

    assert actual == expected, _class_diff_message(actual=actual, expected=expected)


def test_review_checkpoint_lifecycle_failure_classes_match_union() -> None:
    actual = frozenset(FLOW_REVIEW_CHECKPOINT_LIFECYCLE_FAILURE_CLASSES)
    expected = _union_exception_classes(FlowReviewCheckpointLifecycleFailure)

    assert actual == expected, _class_diff_message(actual=actual, expected=expected)


def test_review_checkpoint_lifecycle_failure_classes_include_all_domain_subclasses() -> (
    None
):
    actual = frozenset(FLOW_REVIEW_CHECKPOINT_LIFECYCLE_FAILURE_CLASSES)
    expected = _module_exception_classes(
        module=review_checkpoint_exceptions,
        base_class=FlowReviewCheckpointLifecycleError,
    )

    assert actual == expected, _class_diff_message(actual=actual, expected=expected)


def test_review_checkpoint_runtime_invariant_classes_match_union() -> None:
    actual = frozenset(FLOW_REVIEW_CHECKPOINT_RUNTIME_INVARIANT_CLASSES)
    expected = _union_exception_classes(FlowReviewCheckpointRuntimeInvariantFailure)

    assert actual == expected, _class_diff_message(actual=actual, expected=expected)


def test_review_checkpoint_runtime_invariant_classes_include_all_domain_subclasses() -> (
    None
):
    actual = frozenset(FLOW_REVIEW_CHECKPOINT_RUNTIME_INVARIANT_CLASSES)
    expected = _module_exception_classes(
        module=review_checkpoint_exceptions,
        base_class=FlowReviewCheckpointRuntimeInvariantError,
    )

    assert actual == expected, _class_diff_message(actual=actual, expected=expected)


def test_review_checkpoint_open_terminal_invariant_classes_match_union() -> None:
    actual = frozenset(FLOW_REVIEW_CHECKPOINT_OPEN_TERMINAL_INVARIANT_CLASSES)
    expected = _union_exception_classes(
        FlowReviewCheckpointOpenTerminalInvariantFailure
    )

    assert actual == expected, _class_diff_message(actual=actual, expected=expected)

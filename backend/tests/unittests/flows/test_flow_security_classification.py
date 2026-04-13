from __future__ import annotations

from types import SimpleNamespace

import pytest

from intric.flows.flow_security_classification import (
    evaluate_step_security_classification,
)
from intric.main.exceptions import BadRequestException


def _classification(level: int):
    return SimpleNamespace(security_level=level)


def _assistant(
    *,
    model_level: int | None,
    knowledge_level: int | None = None,
    mcp_level: int | None = None,
):
    completion_model = (
        SimpleNamespace(security_classification=_classification(model_level))
        if model_level is not None
        else None
    )
    collections = (
        [
            SimpleNamespace(
                embedding_model=SimpleNamespace(
                    security_classification=_classification(knowledge_level)
                )
            )
        ]
        if knowledge_level is not None
        else []
    )
    mcp_servers = (
        [SimpleNamespace(security_classification=_classification(mcp_level))]
        if mcp_level is not None
        else []
    )
    return SimpleNamespace(
        completion_model=completion_model,
        collections=collections,
        websites=[],
        integration_knowledge_list=[],
        mcp_servers=mcp_servers,
    )


def _space(level: int | None):
    return SimpleNamespace(
        security_classification=_classification(level) if level is not None else None
    )


def test_rejects_model_below_previous_step_classification() -> None:
    with pytest.raises(BadRequestException) as exc_info:
        evaluate_step_security_classification(
            step_order=2,
            input_source="previous_step",
            output_classification_override=None,
            prior_output_levels_by_order={1: 3},
            assistant=_assistant(model_level=2),
            space=_space(1),
        )

    assert exc_info.value.code == "flow_step_security_classification_mismatch"


def test_rejects_mcp_server_below_input_floor() -> None:
    with pytest.raises(BadRequestException) as exc_info:
        evaluate_step_security_classification(
            step_order=2,
            input_source="previous_step",
            output_classification_override=None,
            prior_output_levels_by_order={1: 3},
            assistant=_assistant(model_level=3, mcp_level=2),
            space=_space(1),
        )

    assert exc_info.value.code == "flow_step_mcp_security_classification_mismatch"


def test_rejects_output_override_write_down() -> None:
    with pytest.raises(BadRequestException) as exc_info:
        evaluate_step_security_classification(
            step_order=2,
            input_source="previous_step",
            output_classification_override=1,
            prior_output_levels_by_order={1: 3},
            assistant=_assistant(model_level=3),
            space=_space(1),
        )

    assert exc_info.value.code == "flow_step_output_classification_write_down"


def test_returns_effective_output_level_when_security_is_compatible() -> None:
    evaluation = evaluate_step_security_classification(
        step_order=2,
        input_source="previous_step",
        output_classification_override=4,
        prior_output_levels_by_order={1: 3},
        assistant=_assistant(model_level=4, knowledge_level=3, mcp_level=3),
        space=_space(1),
    )

    assert evaluation.required_model_level == 3
    assert evaluation.effective_output_level == 4

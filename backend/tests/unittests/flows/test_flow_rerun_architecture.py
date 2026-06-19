from __future__ import annotations

from pathlib import Path

import intric.flows.flow_run_rerun_graph as flow_run_rerun_graph
from intric.flows.enums import RerunDependencyKind


def test_rerun_dependency_kinds_are_pinned():
    assert {item.value for item in RerunDependencyKind} == {
        "input_source.previous_step",
        "input_source.all_previous_steps",
        "input_bindings.question",
        "input_config.url",
        "input_config.headers",
        "input_config.body.template",
        "output_config.url",
        "output_config.headers",
        "output_config.body.template",
        "output_config.bindings",
        "assistant_snapshot.instructions",
        "runtime_alias.previous_step",
    }


def test_rerun_graph_does_not_read_live_authoring_dependencies():
    source_path = Path(flow_run_rerun_graph.__file__)
    source = source_path.read_text(encoding="utf-8")

    assert "FlowStepDependencies" not in source
    assert "flow_tables" not in source

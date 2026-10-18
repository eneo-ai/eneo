"""Canonical vocabulary of AI Builder discovery slot names and classifiers.

Pure leaf — imports nothing from any ``eneo.flows.ai_builder.*`` sibling;
stdlib only. Consumers such as ``question_catalog`` and ``pattern_registry``
may depend on this module without dragging the resolver's transitive graph
into the leaf layer. The purity invariant is pinned by the unit test in
``test_ai_builder_slot_vocabulary.py`` and by the importlinter rule that
forbids non-stdlib imports into this module.
"""

from __future__ import annotations

from typing import Final, Literal

DiscoveryFamily = Literal[
    "case_scope",
    "input_shape",
    "output_artifact",
    "workflow_outcome",
    "output_style",
    "runtime_metadata",
]


KNOWN_REQUIREMENT_SLOT_NAMES: frozenset[str] = frozenset(
    {
        "primary_runtime_input",
        "terminal_output",
        "docx_output_mode",
        "pdf_generation_mode",
        "document_material_scope",
        "comparison_scope",
        "report_disposition",
        "post_processing_goal",
        "structured_io_contract",
        "runtime_metadata_fields",
        "mapped_file_limit",
    }
)

NON_LLM_RESOLVABLE_SLOT_NAMES: frozenset[str] = frozenset(
    {
        # Output generation modes are derived after terminal_output is known,
        # so the model resolves the artifact and policy chooses the mode.
        "docx_output_mode",
        "pdf_generation_mode",
        # The mapped ceiling is committed only through the structured
        # option/custom-answer lane; free-form model inference cannot author it.
        "mapped_file_limit",
    }
)

LLM_RESOLVABLE_SLOT_NAMES: frozenset[str] = (
    KNOWN_REQUIREMENT_SLOT_NAMES - NON_LLM_RESOLVABLE_SLOT_NAMES
)

# The primary_runtime_input value of a flow no step of which reads what a run is
# started with: derived from a saved flow, or answered in a create session whose
# person said to use the space's tools (offers_no_run_input).
NO_RUN_INPUT: Final = "no_run_input"

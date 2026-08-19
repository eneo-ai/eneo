"""Canonical vocabulary of AI Builder discovery slot names and classifiers.

Pure leaf — imports nothing from any ``eneo.flows.ai_builder.*`` sibling;
stdlib only. Consumers such as ``question_catalog`` and ``pattern_registry``
may depend on this module without dragging the resolver's transitive graph
into the leaf layer. The purity invariant is pinned by the unit test in
``test_ai_builder_slot_vocabulary.py`` and by the importlinter rule that
forbids non-stdlib imports into this module.
"""

from __future__ import annotations

from typing import Literal

DiscoveryFamily = Literal[
    "case_scope",
    "input_shape",
    "output_artifact",
    "workflow_outcome",
    "output_style",
    "runtime_metadata",
]

DiscoveryImpact = Literal["architecture", "quality", "polish"]

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

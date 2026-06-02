"""Canonical vocabulary of requirement-slot names emitted by AI Builder
plan-discovery.

Pure leaf — imports nothing from any ``intric.flows.ai_builder.*`` sibling;
stdlib only. Consumers such as ``question_catalog`` and ``pattern_registry``
may depend on this module without dragging the resolver's transitive
dependency graph into the leaf layer. The purity invariant is pinned by
the unit test in ``test_ai_builder_slot_vocabulary.py`` and by the
importlinter rule that forbids non-stdlib imports into this module.
"""

from __future__ import annotations

KNOWN_REQUIREMENT_SLOT_NAMES: frozenset[str] = frozenset(
    {
        "primary_runtime_input",
        "terminal_output",
        "docx_output_mode",
        "pdf_generation_mode",
        "document_material_scope",
        "post_processing_goal",
        "structured_io_contract",
        "structured_analysis_need",
        "runtime_metadata_fields",
    }
)

NON_LLM_RESOLVABLE_SLOT_NAMES: frozenset[str] = frozenset(
    {
        # Output generation modes are derived after terminal_output is known,
        # so the model resolves the artifact and policy chooses the mode.
        "docx_output_mode",
        "pdf_generation_mode",
    }
)

LLM_RESOLVABLE_SLOT_NAMES: frozenset[str] = (
    KNOWN_REQUIREMENT_SLOT_NAMES - NON_LLM_RESOLVABLE_SLOT_NAMES
)

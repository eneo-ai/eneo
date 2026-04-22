"""Canonical vocabulary of requirement-slot names emitted by AI Builder
plan-discovery.

Pure leaf — imports nothing from any ``intric.flows.ai_builder.*`` sibling;
stdlib only. Consumers such as ``question_catalog`` and ``pattern_registry``
may depend on this module without dragging the resolver's transitive
dependency graph into the leaf layer.

The importlinter rule formalizing this leaf guarantee lands in A.5b; until
then the docstring and the purity unit test in
``test_ai_builder_slot_vocabulary.py`` are the enforcement surface.
"""

from __future__ import annotations

KNOWN_REQUIREMENT_SLOT_NAMES: frozenset[str] = frozenset(
    {
        "primary_runtime_input",
        "terminal_output",
        "docx_output_mode",
        "pdf_generation_mode",
        "document_material_scope",
        "structured_analysis_need",
        "runtime_metadata_fields",
    }
)

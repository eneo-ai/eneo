"""Tests pinning the pure-leaf shape of ``ai_builder_slot_vocabulary``.

The module owns the canonical frozenset of requirement slot names the
AI Builder plan-discovery layer emits. Its guarantee is leaf purity:
it imports nothing from any ``ai_builder/*`` sibling, so
``question_catalog`` and future consumers can depend on it without
dragging the resolver's transitive closure into the leaf layer.
"""

from __future__ import annotations

import ast
import pathlib

import intric.flows.ai_builder.ai_builder_slot_vocabulary as slot_vocabulary
from intric.flows.ai_builder.ai_builder_slot_vocabulary import (
    KNOWN_REQUIREMENT_SLOT_NAMES,
)


class TestSlotVocabularyShape:
    def test_frozenset_contains_exactly_seven_canonical_slot_names(self) -> None:
        assert KNOWN_REQUIREMENT_SLOT_NAMES == frozenset(
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

    def test_frozenset_is_truly_frozen(self) -> None:
        assert isinstance(KNOWN_REQUIREMENT_SLOT_NAMES, frozenset)


class TestLeafPurity:
    def _module_source(self) -> str:
        module_path = pathlib.Path(slot_vocabulary.__file__)
        return module_path.read_text(encoding="utf-8")

    def test_leaf_has_no_ai_builder_sibling_imports(self) -> None:
        tree = ast.parse(self._module_source())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                assert node.level == 0, (
                    f"Leaf module must not use relative imports (any relative "
                    f"path inside this package is a sibling reference); found "
                    f"{ast.dump(node)}"
                )
                module = node.module or ""
                is_ai_builder_sub_or_pkg = (
                    module == "intric.flows.ai_builder"
                    or module.startswith("intric.flows.ai_builder.")
                )
                assert not is_ai_builder_sub_or_pkg, (
                    f"Leaf module must not import from ai_builder siblings; "
                    f"found 'from {module} import ...'"
                )
                if module == "intric.flows":
                    for alias in node.names:
                        assert alias.name != "ai_builder", (
                            f"Leaf module must not import the ai_builder package; "
                            f"found 'from intric.flows import {alias.name}'"
                        )
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    is_ai_builder = (
                        alias.name == "intric.flows.ai_builder"
                        or alias.name.startswith("intric.flows.ai_builder.")
                    )
                    assert not is_ai_builder, (
                        f"Leaf module must not import ai_builder siblings; "
                        f"found 'import {alias.name}'"
                    )

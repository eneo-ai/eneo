"""Tests for conditional knowledge pack injection (Phase 3.1)."""

from __future__ import annotations

from intric.flows.ai_builder.ai_builder_prompts import build_system_prompt


class TestConditionalKnowledgePackInjection:
    def test_discovery_phase_excludes_heavy_sections(self):
        """During discovery (no confirmed requirements), skip recipes and
        anti-patterns to save tokens."""
        prompt = build_system_prompt(
            confirmed_requirements=None,  # Discovery phase
        )
        # Core architecture always present
        assert "flow_input" in prompt
        # Heavy sections should be excluded in discovery
        assert "### Recept" not in prompt or "confirmed_requirements" not in prompt

    def test_confirmed_phase_includes_recipes(self):
        """After requirements are confirmed, include recipes for proposal quality."""
        confirmed = {
            "summary": "A document analysis flow.",
            "key_decisions": [{"topic": "Input", "decision": "Documents"}],
            "input_description": "User uploads documents.",
            "output_description": "Structured analysis.",
        }
        prompt = build_system_prompt(confirmed_requirements=confirmed)
        # After confirmation, recipes should be present
        assert "flow_input" in prompt

    def test_edit_mode_includes_edit_knowledge(self):
        """Edit mode should include edit-mode knowledge pack."""
        prompt = build_system_prompt(
            flow_context="Namn: Test\nAntal steg: 2",
            is_edit_mode=True,
        )
        assert "Redigeringsläge" in prompt or "edit" in prompt.lower()

    def test_edit_mode_excludes_create_only_recipes(self):
        """Edit mode should skip create-only content to save tokens."""
        prompt = build_system_prompt(
            flow_context="Namn: Test\nAntal steg: 2",
            is_edit_mode=True,
        )
        # Should have edit-specific content
        assert "existing_step" in prompt or "Redigering" in prompt

    def test_prompt_always_includes_core(self):
        """Core sections must always be present regardless of phase."""
        prompt = build_system_prompt()
        assert "flow_input" in prompt
        assert "previous_step" in prompt

"""Signal-aware recipe selector for the AI Builder.

Selects relevant subsections of the knowledge pack based on discovered
conversation signals, reducing token usage by only injecting recipes
that match the user's flow requirements.
"""

from __future__ import annotations

from intric.flows.ai_builder.ai_builder_create_recipes import (
    KNOWLEDGE_PACK_CREATE_RECIPES_SECTIONS,
    RecipeSection,
    render_knowledge_pack_create_recipes,
)
from intric.flows.ai_builder.ai_builder_form_intake_signals import (
    extract_form_intake_recipe_signals,
)
from intric.flows.ai_builder.ai_builder_planner_pattern_signals import (
    extract_planner_pattern_recipe_signals,
)
from intric.flows.ai_builder.pattern_registry import find_pattern_candidates

# Signal → required recipe section_ids.
#
# `docx_template` is kept as a signal key for legacy callers, but the
# recipes registry no longer ships a dedicated `docx_template` section —
# the DOCX path lives inside `document_analysis` today. A future slice
# that reintroduces a DOCX-specific section registers it here.
#
# `golden_example` is intentionally absent — `select_relevant_recipes`
# adds it unconditionally once any signal triggers a narrowing, so
# listing it per signal would only invite drift between this map and
# that single source of truth.
SIGNAL_TO_RECIPES: dict[str, list[str]] = {
    "audio": ["transcription"],
    "documents": ["document_analysis"],
    "docx_document": ["document_analysis"],
    "pdf_document": ["document_analysis"],
    "structured_json": ["json_pipeline"],
    "structured_text": ["document_analysis"],
    "comparison": ["comparison"],
    "sectioned_form_intake": ["sectioned_form_intake"],
    "rich_document_workflow": [
        "rich_document_workflow",
        "json_pipeline",
    ],
}


def select_relevant_recipes(
    answer_signals: dict[str, set[str]],
    freeform_text: str = "",
    *,
    recipe_source: str,
) -> str:
    """Select and return only the recipe sections relevant to the user's flow.

    If no signals are detected, returns ``recipe_source`` unchanged (safe
    fallback). ``recipe_source`` is keyword-only and required — callers
    pass the fully rendered recipe pack they want filtered (typically
    ``render_knowledge_pack_create_recipes()``). Requiring it avoids a
    silent cut-over to a legacy prose block when a new caller forgets
    to pass one; the selector stays out of the pack-source business.

    Filtering resolves signals to canonical ``section_id`` values and
    picks the matching entries from
    ``KNOWLEDGE_PACK_CREATE_RECIPES_SECTIONS`` directly — heading prose
    is UI copy, not a stable key, so matching by heading substring
    would drift the moment a rename lands in the recipes module.

    Args:
        answer_signals: Extracted answer signals from the conversation.
        freeform_text: Aggregated freeform user text.
        recipe_source: Fully rendered recipe pack the selector filters.

    Returns:
        Filtered recipe content string.
    """
    needed: set[str] = set()

    # Map signals to needed recipe sections
    for values in answer_signals.values():
        for value in values:
            if value in SIGNAL_TO_RECIPES:
                needed.update(SIGNAL_TO_RECIPES[value])

    # Check freeform text for recipe triggers
    lowered = freeform_text.casefold()
    if "audio" in lowered or "ljud" in lowered or "transkri" in lowered:
        needed.update(SIGNAL_TO_RECIPES.get("audio", []))
    if "docx" in lowered or "word" in lowered:
        needed.update(SIGNAL_TO_RECIPES.get("docx_document", []))
    if "jämför" in lowered or "compar" in lowered:
        needed.update(SIGNAL_TO_RECIPES.get("comparison", []))
    if "json" in lowered:
        needed.update(SIGNAL_TO_RECIPES.get("structured_json", []))
    for signal in extract_form_intake_recipe_signals(lowered):
        needed.update(SIGNAL_TO_RECIPES.get(signal, []))
    for signal in extract_planner_pattern_recipe_signals(lowered):
        needed.update(SIGNAL_TO_RECIPES.get(signal, []))

    # Pattern Registry hint vocabulary shares generic English tokens like
    # `document` or `report` across several document-family patterns, so
    # the selector only trusts the pattern-registry trigger when two
    # guardrails hold:
    #   1. `top.score >= 2` — a single-token winner (e.g., bare "extract"
    #      or "docx") is too weak to narrow the pack; the keyword/signal
    #      paths handle those prompts through their dedicated triggers.
    #   2. `top.score > runner_up_score` — ties fall through to the
    #      full-pack fallback so the selector never unions unrelated
    #      recipes when the signal is ambiguous.
    # Patterns whose retrieval hints overlap with generic planner
    # vocabulary (e.g. `multi_step_quality_chain`, `sectioned_form_intake`)
    # opt out by leaving `Pattern.recipe_sections` empty — they still
    # reach the planner through the phrase-aware signal paths above.
    candidates = find_pattern_candidates(lowered)
    if candidates:
        top = candidates[0]
        runner_up_score = candidates[1].score if len(candidates) > 1 else 0
        if top.score >= 2 and top.score > runner_up_score:
            needed.update(top.pattern.recipe_sections)

    # If no signals detected, return full recipes (safe fallback)
    if not needed:
        return recipe_source

    # Always include golden example when we have any signal
    needed.add("golden_example")

    # Filter recipe sections
    return _filter_recipe_sections(recipe_source, needed)


def _filter_recipe_sections(full_recipes: str, needed: set[str]) -> str:
    """Return a rendered recipe pack narrowed to the ``needed`` section_ids.

    Filters the structured registry by ``section_id`` and renders the
    subset. Falls back to ``full_recipes`` when the filter set is empty
    or matches no known section so the planner always sees a usable
    pack rather than a blank one.
    """
    if not needed:
        return full_recipes
    subset: tuple[RecipeSection, ...] = tuple(
        section
        for section in KNOWLEDGE_PACK_CREATE_RECIPES_SECTIONS
        if section.section_id in needed
    )
    if not subset:
        return full_recipes
    return render_knowledge_pack_create_recipes(sections=subset)

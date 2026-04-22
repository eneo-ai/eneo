"""Signal-aware recipe selector for the AI Builder.

Selects relevant subsections of the knowledge pack based on discovered
conversation signals, reducing token usage by only injecting recipes
that match the user's flow requirements.
"""

from __future__ import annotations

from intric.flows.ai_builder.ai_builder_form_intake_signals import (
    extract_form_intake_recipe_signals,
)
from intric.flows.ai_builder.ai_builder_knowledge_pack import (
    KNOWLEDGE_PACK_RECIPES,
)
from intric.flows.ai_builder.ai_builder_planner_pattern_signals import (
    extract_planner_pattern_recipe_signals,
)

# Recipe section markers — these map to section headers in the recipes block
RECIPE_SECTIONS: dict[str, tuple[str, ...]] = {
    "transcription": ("Transkribering", "Audio -> text -> analys -> rapport"),
    "document_analysis": (
        "Dokumentanalys",
        "Dokumentpaket -> JSON -> grounded text -> DOCX/PDF",
    ),
    "golden_example": ("GULDEXEMPEL", "Guldexempel"),
    "docx_template": ("DOCX",),
    "json_pipeline": ("JSON", "JSON-steg"),
    "comparison": ("Jämför",),
    "sectioned_form_intake": ("Sektionerad insamling via formulärfält",),
    "rich_document_workflow": (
        "Dokumentflöde med formulärkomplettering och kvalitetssteg",
    ),
}

# Signal → required recipe sections
SIGNAL_TO_RECIPES: dict[str, list[str]] = {
    "audio": ["transcription", "golden_example"],
    "documents": ["document_analysis", "golden_example"],
    "docx_document": ["docx_template", "golden_example"],
    "pdf_document": ["document_analysis", "golden_example"],
    "structured_json": ["json_pipeline", "golden_example"],
    "structured_text": ["document_analysis", "golden_example"],
    "comparison": ["comparison", "golden_example"],
    "sectioned_form_intake": ["sectioned_form_intake", "golden_example"],
    "rich_document_workflow": [
        "rich_document_workflow",
        "json_pipeline",
        "golden_example",
    ],
}


def select_relevant_recipes(
    answer_signals: dict[str, set[str]],
    freeform_text: str = "",
    recipe_source: str | None = None,
) -> str:
    """Select and return only the recipe sections relevant to the user's flow.

    If no signals are detected, returns the full recipe block (safe fallback).

    Args:
        answer_signals: Extracted answer signals from the conversation.
        freeform_text: Aggregated freeform user text.

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

    # If no signals detected, return full recipes (safe fallback)
    source = recipe_source or KNOWLEDGE_PACK_RECIPES
    if not needed:
        return source

    # Always include golden example when we have any signal
    needed.add("golden_example")

    # Filter recipe sections
    return _filter_recipe_sections(source, needed)


def _filter_recipe_sections(full_recipes: str, needed: set[str]) -> str:
    """Extract only the needed sections from the recipes block.

    Sections are identified by their headers (## N. ...) and selected
    if any of their marker keywords appear in the needed sections.
    """
    lines = full_recipes.split("\n")
    result_lines: list[str] = []
    in_relevant_section = False

    # Always include the title
    for line in lines:
        if line.startswith("# ") and not line.startswith("## "):
            result_lines.append(line)
            continue

        if line.startswith("## "):
            # Check if this section is needed
            in_relevant_section = False
            for recipe_key, markers in RECIPE_SECTIONS.items():
                if recipe_key in needed:
                    if any(marker in line for marker in markers):
                        in_relevant_section = True
                        break
            if in_relevant_section:
                result_lines.append("")
                result_lines.append(line)
            continue

        if in_relevant_section:
            result_lines.append(line)

    filtered = "\n".join(result_lines).strip()
    return filtered if filtered else KNOWLEDGE_PACK_RECIPES

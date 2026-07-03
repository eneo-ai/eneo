from __future__ import annotations

from copy import deepcopy
from typing import Any, cast

_STEP_ASSUMPTIONS_DIAGNOSTIC_INTENT: dict[str, Any] = {
    "flow_name": "Transkribering och nyckeluppgifter i PDF",
    "flow_description": (
        "Tar emot ljud, transkriberar och använder strukturerad analys för att "
        "plocka ut nyckeluppgifter, samt levererar ett genererat PDF-dokument "
        "med extraherade värden och eventuella saknade uppgifter."
    ),
    "plan_rationale": (
        "Transkribering skapar ett stabilt underlag, och därefter kan "
        "strukturerad extraktion ge konsekvent nyckeluppgiftsutmatning som "
        "endast bygger på källmaterialet."
    ),
    "steps": [
        {
            "name": "Transkribera ljud till text",
            "instructions": (
                "Transkribera inkommande ljud till sammanhängande text som "
                "grund för vidare analys."
            ),
            "output_type": "text",
            "model_ref": "model.gpt-5-4-mini",
        },
        {
            "name": "Identifiera nyckeluppgifter (lista att extrahera)",
            "instructions": (
                "Gå igenom transkriptionen och identifiera vilka typer av "
                "nyckeluppgifter som faktiskt förekommer och vilka som "
                "efterfrågas men saknas/är otydliga. Skapa en intern lista "
                "över kandidater (utan att ännu skriva slutlig struktur)."
            ),
            "output_type": "json",
            "output_fields": [
                {
                    "name": "candidate_items",
                    "field_type": "array",
                    "description": (
                        "Lista med kandidater till nyckeluppgifter som ska "
                        "extraheras eller markeras som saknade."
                    ),
                    "required": True,
                    "item_fields": {
                        "name": "candidate",
                        "field_type": "object",
                        "description": "En kandidatpost för en nyckeluppgift.",
                        "required": True,
                        "fields": [
                            {
                                "name": "type",
                                "field_type": "string",
                                "description": (
                                    "Typ av uppgift (t.ex. datum, tid, plats, "
                                    "belopp, beslut, åtgärd, ansvarig, person, annan)."
                                ),
                                "required": True,
                            },
                            {
                                "name": "status",
                                "field_type": "string",
                                "description": (
                                    "Antingen 'found' eller 'missing_or_unspecified'."
                                ),
                                "required": True,
                            },
                            {
                                "name": "evidence_hint",
                                "field_type": "string",
                                "description": (
                                    "Kort ledtråd om var i transkriptionen "
                                    "informationen finns, eller varför den saknas."
                                ),
                                "required": True,
                            },
                        ],
                    },
                }
            ],
            "model_ref": "model.gpt-5-4-2026-03-05",
            "citations_requested": False,
            "uses_form_fields": [],
            "knowledge_refs": [],
            "mcp_server_refs": [],
            "mcp_tool_refs": [],
            "review_mode": None,
            "assumptions": [
                (
                    "Det går att avgöra om informationen är explicit i "
                    "transkriptionen eller saknas/är otydlig."
                )
            ],
        },
        {
            "name": "Extrahera nyckeluppgifter (strukturerat resultat)",
            "instructions": (
                "Använd transkriptionen för att extrahera de identifierade "
                "nyckeluppgifterna till ett slutligt strukturerat resultat. "
                "Inkludera endast värden som stöds av källmaterialet. För "
                "saknade/otydliga uppgifter, använd tydliga missing-markers."
            ),
            "output_type": "json",
            "output_fields": [
                {
                    "name": "extracted_key_information",
                    "field_type": "object",
                    "description": (
                        "Extraherade nyckeluppgifter. Innehåller endast värden "
                        "som stöds av källmaterialet; saknade värden ska "
                        "markeras explicit."
                    ),
                    "required": True,
                    "fields": [
                        {
                            "name": "key_facts",
                            "field_type": "array",
                            "description": (
                                "Lista av nyckelfakta som hittats i materialet."
                            ),
                            "required": True,
                            "item_fields": {
                                "name": "fact",
                                "field_type": "object",
                                "description": "En enskild nyckelfaktapost.",
                                "required": True,
                                "fields": [
                                    {
                                        "name": "type",
                                        "field_type": "string",
                                        "description": (
                                            "Typ av uppgift (t.ex. datum, tid, "
                                            "plats, belopp, beslut, åtgärd, "
                                            "ansvarig, person, annan)."
                                        ),
                                        "required": True,
                                    },
                                    {
                                        "name": "value",
                                        "field_type": "string",
                                        "description": "Extraherat värde.",
                                        "required": True,
                                    },
                                    {
                                        "name": "evidence_snippet",
                                        "field_type": "string",
                                        "description": (
                                            "Kort citat/utdrag från transkriptionen "
                                            "som stödjer värdet."
                                        ),
                                        "required": True,
                                    },
                                ],
                            },
                        },
                        {
                            "name": "missing_or_unspecified_values",
                            "field_type": "array",
                            "description": (
                                "Nyckeluppgifter som är relevanta men saknas "
                                "eller är otydliga i källmaterialet."
                            ),
                            "required": True,
                            "item_fields": {
                                "name": "missing_item",
                                "field_type": "object",
                                "description": (
                                    "En saknad eller ospecificerad uppgift."
                                ),
                                "required": True,
                                "fields": [
                                    {
                                        "name": "type",
                                        "field_type": "string",
                                        "description": (
                                            "Typ av uppgift som saknas/är otydlig."
                                        ),
                                        "required": True,
                                    },
                                    {
                                        "name": "missing_marker",
                                        "field_type": "string",
                                        "description": (
                                            "Tydlig missing-marker (t.ex. "
                                            "'Saknas i källmaterialet')."
                                        ),
                                        "required": True,
                                    },
                                ],
                            },
                        },
                    ],
                }
            ],
            "model_ref": "model.gpt-5-4-2026-03-05",
            "citations_requested": False,
            "uses_form_fields": [],
            "knowledge_refs": [],
            "mcp_server_refs": [],
            "mcp_tool_refs": [],
            "review_mode": None,
            "assumptions": [
                (
                    "Om en uppgift inte kan styrkas av transkriptionen ska den "
                    "markeras som saknad/oklar."
                ),
                (
                    "Extraherade värden ska vara förenliga med transkriptionens "
                    "ordalydelse."
                ),
            ],
        },
        {
            "name": "Sammanställ PDF-innehåll",
            "instructions": (
                "Skapa det kompletta dokumentinnehållet för PDF: inkludera "
                "sektionen 'Extracted key information' med extraherade "
                "nyckeluppgifter och sektionen 'Missing or unspecified values' "
                "med saknade/otydliga uppgifter. Säkerställ att all text baseras "
                "på tidigare extraktion och att saknade värden använder "
                "missing-markers."
            ),
            "output_type": "pdf",
        },
    ],
    "assumptions": [
        (
            "Flödet levererar en genererad PDF med nyckeluppgifter extraherade "
            "från ljudets transkription."
        ),
        "Inga extra metadatafält krävs vid körning.",
    ],
}


def self_correction_intent_with_step_assumptions_payload() -> dict[str, Any]:
    return cast(dict[str, Any], deepcopy(_STEP_ASSUMPTIONS_DIAGNOSTIC_INTENT))

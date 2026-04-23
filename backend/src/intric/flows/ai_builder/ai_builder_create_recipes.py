from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RecipeBullet:
    text: str
    numbered_subitems: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RecipeSection:
    heading: str
    numbered_items: tuple[str, ...] = ()
    bullets: tuple[RecipeBullet, ...] = ()
    code_block: str = ""
    code_language: str = "json"


_RISK_ANALYSIS_EXAMPLE = """\
{
  "flow_name": "Dokumentgranskning med riskanalys",
  "plan_rationale": "Extraherar först strukturerade risker och skriver sedan grounded rapport innan slutlig DOCX-leverans.",
  "form_fields": [
    {"variable_name": "referens_id", "label": "Referens-ID", "field_type": "text", "required": true, "options": []},
    {"variable_name": "ansvarig_enhet", "label": "Ansvarig enhet", "field_type": "text", "required": true, "options": []}
  ],
  "steps": [
    {
      "name": "Extrahera text och riskdata",
      "instructions": "Extrahera centrala fakta och identifierade risker som strukturerad JSON.",
      "input_source": "flow_input",
      "input_type": "document",
      "output_type": "json",
      "runtime_upload": true,
      "runtime_required": true,
      "runtime_max_files": 10,
      "uses_form_fields": ["referens_id", "ansvarig_enhet"],
      "document_delivery_mode": "not_applicable",
      "citations_requested": false,
      "output_fields": [
        {"name": "sammanfattning", "field_type": "string", "description": "Kort sammanfattning av dokumentet", "required": true},
        {"name": "risker", "field_type": "array", "description": "Identifierade risker", "required": true, "item_fields": [
          {"name": "rubrik", "field_type": "string", "description": "Riskrubrik", "required": true},
          {"name": "konsekvens", "field_type": "object", "description": "Konsekvenssammanfattning", "required": false, "fields": [
            {"name": "beskrivning", "field_type": "string", "description": "Beskrivning av konsekvensen", "required": false},
            {"name": "nivå", "field_type": "string", "description": "Allvarlighetsgrad (låg, medel, hög)", "required": false}
          ]}
        ]}
      ]
    },
    {
      "name": "Grounded sammanfattning",
      "instructions": "Skriv en grounded sammanfattning som kopplar riskerna till källdokumentet och anger spårbara referenser.",
      "input_source": "previous_step",
      "input_type": "json",
      "output_type": "text",
      "uses_form_fields": ["referens_id", "ansvarig_enhet"],
      "uses_previous_fields": [
        {"from_step": 1, "field_path": "sammanfattning", "label": "Dokumentsammanfattning"},
        {"from_step": 1, "field_path": "risker.0.rubrik", "label": "Första riskrubrik"}
      ],
      "document_delivery_mode": "not_applicable",
      "citations_requested": true
    },
    {
      "name": "Generera DOCX-rapport",
      "instructions": "Skriv en strukturerad rapport på formell svenska med rubriker, slutsatser och rekommendationer.",
      "input_source": "previous_step",
      "input_type": "text",
      "output_type": "docx",
      "document_delivery_mode": "generated",
      "uses_form_fields": ["referens_id", "ansvarig_enhet"],
      "citations_requested": false
    }
  ]
}"""


KNOWLEDGE_PACK_CREATE_RECIPES_SECTIONS: tuple[RecipeSection, ...] = (
    RecipeSection(
        heading="Dokumentpaket -> JSON -> grounded text -> DOCX/PDF",
        numbered_items=(
            'Steg 1: `flow_input` + `input_type="document"` + `runtime_upload=true`',
            "Steg 2: extrahera strukturerad JSON via `output_fields`",
            (
                "Steg 3: analysera eller resonera vidare från JSON eller text, "
                "och använd `uses_previous_fields` när bara vissa datapunkter ska "
                "följa med"
            ),
            (
                "Steg 4: skriv grounded text med `citations_requested=true` om "
                "spårbarhet behövs"
            ),
            "Sista steget: generera dokumentet som `pdf` eller `docx`",
        ),
    ),
    RecipeSection(
        heading="Audio -> text -> analys -> rapport",
        numbered_items=(
            'Första steget: `input_type="audio"`, `output_type="text"`',
            "Nästa steg: analysera transkriberingen som text",
            "Sista steget: skriv rapporttext eller generera dokument",
        ),
    ),
    RecipeSection(
        heading="JSON-steg",
        bullets=(
            RecipeBullet(
                text="Beskriv fälten i `output_fields`, inte som rå JSON Schema",
            ),
            RecipeBullet(
                text="Håll strukturen stabil och återanvändbar för nästa steg",
            ),
            RecipeBullet(
                text=(
                    "Om nästa steg bara behöver några datapunkter, gör JSON-steget "
                    "tydligt och smalt"
                ),
            ),
        ),
    ),
    RecipeSection(
        heading="Dokumentflöde med formulärkomplettering och kvalitetssteg",
        bullets=(
            RecipeBullet(
                text=(
                    "När användaren beskriver ett dokumentbaserat flöde som också "
                    "behöver kompletterande användarvärden, återanvändbar strukturerad "
                    "analys eller ett kvalitets-/granskningssteg ska du inte kollapsa "
                    "planen till en minimal tvåstegskedja"
                ),
            ),
            RecipeBullet(
                text="Preferera i stället en tydlig pipeline:",
                numbered_subitems=(
                    "`flow_input` för dokumentuppladdning",
                    "ett JSON-steg som extraherar återanvändbara fält",
                    (
                        "ett analys-, kvalitets- eller granskningssteg som använder "
                        "`uses_previous_fields`"
                    ),
                    "ett slutsteg som producerar `docx`, `pdf` eller grounded text",
                ),
            ),
            RecipeBullet(
                text=(
                    "Om användaren nämner att vissa uppgifter kan saknas eller "
                    "behöva förtydligas ska dessa modelleras som `form_fields`, och "
                    "senare steg ska läsa dem via `uses_form_fields`"
                ),
            ),
            RecipeBullet(
                text=(
                    "När du behöver både dokument och formulärdata i samma lösning "
                    "ska dokument förbli primär `flow_input`, medan manuella "
                    "kompletteringar ligger i `form_fields`"
                ),
            ),
            RecipeBullet(
                text=(
                    "Om användaren uttryckligen ber om ett mer genomarbetat flöde, "
                    "kvalitetssäkring eller språkgranskning ska detta synas som egna "
                    "mellanliggande steg i planen"
                ),
            ),
        ),
    ),
    RecipeSection(
        heading="Sektionerad insamling via formulärfält",
        bullets=(
            RecipeBullet(
                text=(
                    "När användaren beskriver ett fast set rubriker/sektioner där "
                    "användaren ska lämna fritext per sektion ska du modellera detta "
                    "som `form_fields`, inte som ett eget insamlingssteg per rubrik"
                ),
            ),
            RecipeBullet(text="Skapa ett textfält per rubrik/sektion"),
            RecipeBullet(
                text=(
                    "Låt senare steg använda `uses_form_fields` för att sammanställa "
                    "och skriva sluttexten"
                ),
            ),
            RecipeBullet(
                text=(
                    "Om användaren vill kunna hoppa över eller gå tillbaka, modellera "
                    "detta som separata styrfält eller interaktionslogik runt samma "
                    "formulärdata — inte som sju separata JSON-insamlingssteg"
                ),
            ),
            RecipeBullet(
                text=(
                    "Slutsteget ska använda de insamlade formulärfälten för att "
                    "skapa sammanställningen med samma rubriker"
                ),
            ),
        ),
    ),
    RecipeSection(
        heading="Jämförelseflöden med flera indata",
        bullets=(
            RecipeBullet(
                text=(
                    "När användaren vill ställa två eller fler indata sida vid "
                    "sida (dokument mot dokument, text mot text, mall mot "
                    "mall) ska varje indata extraheras till samma strukturerade "
                    "form innan jämförelsen sker"
                ),
            ),
            RecipeBullet(
                text="Typisk kedja:",
                numbered_subitems=(
                    (
                        "ett `flow_input` eller `form_fields`-steg per indata, så "
                        "att varje källa är en tydlig variabel"
                    ),
                    (
                        "ett JSON-steg som extraherar samma fält ur varje indata "
                        "via `output_fields`"
                    ),
                    (
                        "ett jämförelsesteg som läser varje extrakt via "
                        "`uses_previous_fields` och producerar en tabell eller "
                        "sammanställning i `text`, `json` eller `docx`"
                    ),
                ),
            ),
            RecipeBullet(
                text=(
                    "Håll fältuppsättningen identisk per indata — annars blir "
                    "jämförelsen skev och det slutliga steget måste kompensera "
                    "för asymmetrier"
                ),
            ),
        ),
    ),
    RecipeSection(
        heading="Exempel: dokumentgranskning med riskanalys",
        code_block=_RISK_ANALYSIS_EXAMPLE,
        code_language="json",
    ),
)


_HEADER = "# Create-läge: vanliga mönster"


def render_knowledge_pack_create_recipes() -> str:
    lines: list[str] = [_HEADER]
    for section in KNOWLEDGE_PACK_CREATE_RECIPES_SECTIONS:
        lines.append("")
        lines.append(f"## {section.heading}")
        if section.numbered_items:
            for index, item in enumerate(section.numbered_items, start=1):
                lines.append(f"{index}. {item}")
        elif section.bullets:
            for bullet in section.bullets:
                lines.append(f"- {bullet.text}")
                for sub_index, sub in enumerate(bullet.numbered_subitems, start=1):
                    lines.append(f"  {sub_index}. {sub}")
        elif section.code_block:
            lines.append(f"```{section.code_language}")
            lines.extend(section.code_block.splitlines())
            lines.append("```")
    return "\n".join(lines)


__all__ = [
    "KNOWLEDGE_PACK_CREATE_RECIPES_SECTIONS",
    "RecipeBullet",
    "RecipeSection",
    "render_knowledge_pack_create_recipes",
]

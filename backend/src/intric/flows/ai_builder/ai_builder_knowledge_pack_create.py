from __future__ import annotations

_KNOWLEDGE_PACK_CREATE_FLOW_ARCHITECTURE = """\
# Create-flow-kompilering

I create-läge beskriver du bara avsikten i `create_flow`. Backend kompilerar \
utkastet till den kanoniska flödesspecifikationen.

## Vad du SKA ange
- `instructions` — vanlig text utan variabelsyntax
- `input_source`, `input_type`, `output_type`
- `runtime_upload`, `runtime_required`, `runtime_max_files` för första uppladdningssteget
- `uses_form_fields` när senare steg behöver formulärvärden
- `uses_previous_fields` när senare steg behöver specifika strukturerade fält från tidigare JSON-steg
- `document_delivery_mode` för PDF/DOCX-leverans
- `citations_requested` för textsteg som ska ha källhänvisningar
- `output_fields` för JSON-steg

## Vad backend äger
- stegrefar (`plan_step_ref`)
- underlag / variabelinjektion mellan steg
- kontrakt / JSON Schema
- `output_mode`
- runtime-input-config

## Praktiska regler
- Steg 1 MÅSTE använda `input_source=\"flow_input\"`
- Senare steg får inte använda `input_source=\"flow_input\"`; använd `previous_step` eller `all_previous_steps`
- Sista steget MÅSTE ha `output_type` som matchar den explicit efterfrågade slutartefakten (`text`, `json`, `pdf` eller `docx`)
- När flera uppladdade dokument ska vägas samman i en gemensam analys eller grounded sammanfattning ska ett samlande steg använda `input_source=\"all_previous_steps\"`
- Varje objekt i `steps` måste vara ett komplett steg. Fältdefinitioner med `name`, `field_type`, `description` och `required` hör hemma i `output_fields`, inte som egna poster i `steps`
- Filuppladdning används via `runtime_upload=true` på ett `flow_input`-steg med \
  `input_type=document`, `file` eller `audio`
- Använd `output_type=\"json\"` + `output_fields` när nästa steg behöver namngivna datapunkter
- Använd `output_type=\"text\"` för grounded sammanfattningar, resonemang och läsbar rapporttext
- Använd `output_type=\"docx\"` eller `\"pdf\"` bara när steget faktiskt levererar dokumentet
"""


_KNOWLEDGE_PACK_CREATE_STEP_DESIGN = """\
# Create-läge: kompilerad datamodell

## Instruktioner
- `instructions` ska vara ren uppgiftsbeskrivning — inga `{{ ... }}`-variabler
- Beskriv roll, krav, format och begränsningar tydligt
- Backend kompilerar underlaget från `input_source`, tidigare steg och formulärfält
- Backend kompilerar även explicita fältbindningar från `uses_previous_fields`
- Instruktioner får gärna vara LÅNGA och detaljerade när uppgiften kräver flera regler, formatkrav eller beslutslogik

## JSON-utdata via `output_fields`
- `output_fields` används bara för `output_type=\"json\"`
- Max nesting depth 3: toppnivåfält, barnfält och ett barnbarnsled
- Bra mönster:
  - objekt med scalar-fält
  - array med objektposter
  - objekt/array som innehåller ett extra lager scalar-fält
- Undvik djupare träd än så; platta hellre ut strukturen

## Formulär och runtime
- Modellera användarens körningsdata som `form_fields` i stället för dold prompttext
- Referera till dessa med `uses_form_fields`
- När ett senare steg bara behöver vissa JSON-fält från ett tidigare steg: använd `uses_previous_fields`
- Om användaren måste ladda upp filer vid körning: sätt `runtime_upload=true`

## Dokumentleverans
- `document_delivery_mode=\"generated\"` för vanliga genererade PDF/DOCX-dokument
- `document_delivery_mode=\"template_fill\"` bara för DOCX
"""


_KNOWLEDGE_PACK_CREATE_RECIPES = """\
# Create-läge: vanliga mönster

## Dokumentpaket -> JSON -> grounded text -> DOCX/PDF
1. Steg 1: `flow_input` + `input_type=\"document\"` + `runtime_upload=true`
2. Steg 2: extrahera strukturerad JSON via `output_fields`
3. Steg 3: analysera eller resonera vidare från JSON eller text, och använd `uses_previous_fields` när bara vissa datapunkter ska följa med
4. Steg 4: skriv grounded text med `citations_requested=true` om spårbarhet behövs
5. Sista steget: generera dokumentet som `pdf` eller `docx`

## Audio -> text -> analys -> rapport
1. Första steget: `input_type=\"audio\"`, `output_type=\"text\"`
2. Nästa steg: analysera transkriberingen som text
3. Sista steget: skriv rapporttext eller generera dokument

## JSON-steg
- Beskriv fälten i `output_fields`, inte som rå JSON Schema
- Håll strukturen stabil och återanvändbar för nästa steg
- Om nästa steg bara behöver några datapunkter, gör JSON-steget tydligt och smalt

## Dokumentflöde med formulärkomplettering och kvalitetssteg
- När användaren beskriver ett dokumentbaserat flöde som också behöver kompletterande användarvärden, återanvändbar strukturerad analys eller ett kvalitets-/granskningssteg ska du inte kollapsa planen till en minimal tvåstegskedja
- Preferera i stället en tydlig pipeline:
  1. `flow_input` för dokumentuppladdning
  2. ett JSON-steg som extraherar återanvändbara fält
  3. ett analys-, kvalitets- eller granskningssteg som använder `uses_previous_fields`
  4. ett slutsteg som producerar `docx`, `pdf` eller grounded text
- Om användaren nämner att vissa uppgifter kan saknas eller behöva förtydligas ska dessa modelleras som `form_fields`, och senare steg ska läsa dem via `uses_form_fields`
- När du behöver både dokument och formulärdata i samma lösning ska dokument förbli primär `flow_input`, medan manuella kompletteringar ligger i `form_fields`
- Om användaren uttryckligen ber om ett mer genomarbetat flöde, kvalitetssäkring eller språkgranskning ska detta synas som egna mellanliggande steg i planen

## Sektionerad insamling via formulärfält
- När användaren beskriver ett fast set rubriker/sektioner där användaren ska lämna fritext per sektion ska du modellera detta som `form_fields`, inte som ett eget insamlingssteg per rubrik
- Skapa ett textfält per rubrik/sektion
- Låt senare steg använda `uses_form_fields` för att sammanställa och skriva sluttexten
- Om användaren vill kunna hoppa över eller gå tillbaka, modellera detta som separata styrfält eller interaktionslogik runt samma formulärdata — inte som sju separata JSON-insamlingssteg
- Slutsteget ska använda de insamlade formulärfälten för att skapa sammanställningen med samma rubriker

## Exempel: dokumentgranskning med riskanalys
```json
{
  "flow_name": "Dokumentgranskning med riskanalys",
  "plan_rationale": "Extraherar först strukturerade risker och skriver sedan grounded beslutsunderlag innan slutlig DOCX-rapport.",
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
}
```"""


_VALIDATION_REPAIR_EXAMPLES = """\
# Validation Repair Examples

## Felaktigt utkast → valideringsfel → korrigerat utkast

- Bad draft:
  `{{ step_b.output.text }}` i `instructions`
- Validation error:
  `variable references are not allowed in create_flow instructions`
- Corrected draft:
  skriv bara vanliga instruktioner och låt backend kompilera underlaget

- Bad draft:
  `output_type="text"` tillsammans med `output_fields`
- Validation error:
  `output_fields require output_type=json`
- Corrected draft:
  byt till `output_type="json"` eller ta bort `output_fields`

- Bad draft:
  `document_delivery_mode="template_fill"` tillsammans med `output_type="pdf"`
- Validation error:
  `template_fill requires output_type=docx`
- Corrected draft:
  använd genererad PDF eller byt dokumenttypen till DOCX"""


KNOWLEDGE_PACK_CREATE_FLOW_ARCHITECTURE = _KNOWLEDGE_PACK_CREATE_FLOW_ARCHITECTURE
KNOWLEDGE_PACK_CREATE_STEP_DESIGN = _KNOWLEDGE_PACK_CREATE_STEP_DESIGN
KNOWLEDGE_PACK_CREATE_RECIPES = _KNOWLEDGE_PACK_CREATE_RECIPES
VALIDATION_REPAIR_EXAMPLES = _VALIDATION_REPAIR_EXAMPLES

__all__ = [
    "_KNOWLEDGE_PACK_CREATE_FLOW_ARCHITECTURE",
    "_KNOWLEDGE_PACK_CREATE_RECIPES",
    "_KNOWLEDGE_PACK_CREATE_STEP_DESIGN",
    "_VALIDATION_REPAIR_EXAMPLES",
    "KNOWLEDGE_PACK_CREATE_FLOW_ARCHITECTURE",
    "KNOWLEDGE_PACK_CREATE_RECIPES",
    "KNOWLEDGE_PACK_CREATE_STEP_DESIGN",
    "VALIDATION_REPAIR_EXAMPLES",
]

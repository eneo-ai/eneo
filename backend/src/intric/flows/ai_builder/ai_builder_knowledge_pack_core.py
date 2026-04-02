from __future__ import annotations


_KNOWLEDGE_PACK_FLOW_ARCHITECTURE = """\
# Flödesarkitektur

## Steg och kedjeregel

Ett flöde består av ordnade steg (steps). Varje steg har en AI-assistent som \
bearbetar indata och producerar utdata.

### Indatakälla (`input_source`)
- `flow_input` — Steg 1 MÅSTE använda detta. Tar emot flödets externa indata.
- `previous_step` — Tar utdata från föregående steg. Effektivast (lägst tokenförbrukning).
- `all_previous_steps` — Sammanfogar utdata från ALLA föregående steg. Använd sparsamt \
  — ökar tokenförbrukning avsevärt i långa flöden.

### Indatatyp (`input_type`)
- `text` — Fritext (standard).
- `json` — Strukturerad JSON. Inkompatibelt med `all_previous_steps`.
- `audio` — Ljud. Kräver `flow_input` som källa och `transcribe_only` som output_mode.
- `document` — Dokument (PDF etc). Kräver `flow_input` som källa.
- `file` — Generell fil. Kräver `flow_input` som källa.
- `any` — Accepterar allt. Flexibelt men ger ingen typkontroll.

### Filuppladdning vid körning (`input_config.runtime_input`)
- När ett steg använder `input_source=flow_input` tillsammans med `input_type=document`, `file` eller `audio` ska du aktivera `input_config.runtime_input.enabled=true`.
- Detta motsvarar UI-inställningen **"Ta emot filer vid körning"** och gör att användaren får en uppladdningsyta i kördialogen.
- Sätt `input_config.runtime_input.input_format` till samma värde som indatatypen: `document`, `file` eller `audio`.
- Om flödet inte kan köras utan uppladdningen bör du även sätta `input_config.runtime_input.required=true`.
- Lägg gärna till en kort svensk `description` som förklarar vad användaren ska ladda upp.

Exempel:
```json
{
  "input_source": "flow_input",
  "input_type": "document",
  "input_config": {
    "runtime_input": {
      "enabled": true,
      "input_format": "document",
      "description": "Ladda upp dokument som ska analyseras i detta steg."
    }
  }
}
```

### Utdataläge (`output_mode`)
- `pass_through` — Standard. AI:n genererar svar fritt.
- `transcribe_only` — Transkriberar ljud till text. Kräver `audio` som input_type \
  och `text` som output_type.
- `template_fill` — Fyller i DOCX-mall. Kräver `docx` som output_type och \
  konfigurerad mall med bindningar.
- Det finns ingen native `template_fill` för PDF. Om användaren säger "PDF-mall" ska du hålla PDF-flödet ärligt som genererad PDF eller förklara att riktig mallfyllning bara stöds för DOCX/Word.

### Utdatatyp (`output_type`)
- `text` — Fritext (standard).
- `json` — Strukturerad JSON (kan drivas av output_contract).
- `pdf` — PDF-dokument.
- `docx` — DOCX-dokument (ofta med template_fill).

### Typkompatibilitet (vad som kan kedjas)
| Utdata → | text indata | json indata | any indata |
|----------|------------|------------|------------|
| text     | ✓          | ✓          | ✓          |
| json     | ✓          | ✓          | ✓          |
| pdf      | ✓          | ✗          | ✓          |
| docx     | ✓          | ✗          | ✓          |

### MCP-policy (`mcp_policy`)
- `inherit` — Ärver space-nivåns MCP-konfiguration (standard).
- `restricted` — Begränsar vilka MCP-verktyg steget kan använda."""


_KNOWLEDGE_PACK_VARIABLE_SYSTEM = """\
# Variabelsystemet (KRITISKT)

Variabler är hjärtat i flödeskedjan. De låter varje steg använda data från \
flödesindata, formulärfält och tidigare stegs utdata.

## Variabelsyntax

Alla variabler skrivs som `{{ variabelnamn }}` med dubbla klammerparenteser.

## Variabeltyper

### 1. Flödesindata-variabler (form fields)
Om flödet har ett formulär (form_fields) blir varje fälts namn en variabel:
- `{{ Ärendenummer }}` — värdet av formulärfältet "Ärendenummer"
- `{{ Bakgrund som text }}` — värdet av formulärfältet "Bakgrund som text"
- `{{ Förslag-till-beslut }}` — värdet av formulärfältet "Förslag-till-beslut"

### 2. Steg-utdata-variabler (step outputs)
Varje steg producerar utdata som är tillgängligt för efterföljande steg:
- `{{ step_a.output.text }}` — textutdata från steget med `plan_step_ref="step_a"`
- `{{ step_b.output.text }}` — textutdata från steget med `plan_step_ref="step_b"`
- `{{ step_c.output.structured.resultat }}` — ett specifikt JSON-fält från steget `step_c` (kräver output_type=json)

### 3. Runtime-alias för stegnamn (inte primär AI-authoring)
Runtime kan exponera alias baserade på `user_description`, men AI Builder-utkast ska \
INTE förlita sig på dem som primär referensmodell:
- Om ett körande flöde har ett steg som heter "Ärendet" kan runtime exponera \
  `{{ Ärendet }}` som en bekvämlighetsalias.
- Detta är en runtime-bekvämlighet för befintliga flöden, inte den kanoniska \
  AI Builder-syntaxen.

### 3b. KRITISK regel för AI Builder-utkast
- I nya AI Builder-utkast ska du INTE skriva `plan_step_ref` själv i create-läge — backend tilldelar `step_a`, `step_b` osv vid kompilering.
- Om du arbetar i canonical spec eller felsöker kompilerade utkast ska samma referens återanvändas konsekvent i variabler och underlag.
- Runtime skriver senare om dessa till interna `step_1`, `step_2`-referenser. Blanda inte authoring-refar och runtime-refar i samma felsökningskontext.
- Blanda inte `step_a` och `step_1` i samma utkast eller felsökningskontext.
- Använd inte stegnamn som `{{ Ärendet }}` i nya AI Builder-utkast även om de kan fungera i befintliga körningar.

### 4. Systemvariabler
- `{{ föregående_steg }}` — textutdata från det direkt föregående steget
- `{{ transkribering }}` — transkriberad text (om flödesindata är ljud)
- `{{ indata_text }}` — flödets textindata
- `{{ indata_json }}` — flödets JSON-indata
- `{{ datum }}` — dagens datum (ÅÅÅÅ-MM-DD)

### 5. Runtime-inputvariabler när användaren laddar upp filer vid körning
Om ett steg använder `input_config.runtime_input.enabled=true` och du samtidigt sätter \
`input_bindings.question`, måste frågetexten innehålla riktiga `step_input.*`-referenser:
- `{{ step_input.text }}` — extraherad text från uppladdad fil eller ljudtranskribering
- `{{ step_input.file_ids }}` — fil-id:n när steget behöver identifiera uppladdade filer
- `{{ step_input.input_format }}` — backendens normaliserade indatatyp för körningen
- `{{ step_input.extracted_text_length }}` — längd på extraherad text

Om ett kompilerat explicit underlag saknar `step_input.*`, betraktas runtime-indatan \
som okonsumerad och valideringen stoppar utkastet. I create-läge kompilerar backend detta åt dig.

## Var variabler kan användas

### I `input_bindings.question` ("Underlag till steget")
Detta är det PRIMÄRA stället för variabler. Underlaget bygger den text AI:n ska \
bearbeta. Om det lämnas tomt används resultatet från föregående steg automatiskt.

Exempel — ett steg som kombinerar data från flera källor:
```json
{
  "question": "Rubrik: {{ Ärendet }}\\nBakgrund: {{ Bakgrund }}\\nÖverväganden: {{ Förvaltningens överväganden }}\\nTidigare beslut: {{ step_5.output.text }}"
}
```

### I `assistant_spec.instructions` ("Instruktioner till AI:n")
Variabler fungerar även i instruktionerna, men blir då en del av AI:ns beteende, \
inte den text som bearbetas. Exempel:
```
Ärendenumret är {{ Ärendenummer }}. Formulera beslutsunderlag baserat på {{ Förslag-till-beslut }}.
```

## Viktiga regler
- Variabler kan BARA referera till steg som kommer FÖRE det aktuella steget
- I AI Builder-utkast ska du använda `plan_step_ref` som enda steg-referensmodell
- Formulärfältets `name` blir variabelnamnet — välj namn noggrant!
- Undvik namn som kolliderar med systemvariabler (flow, flow_input, step_input, etc.)
- Undvik namn som börjar med `step_` (reserverat för steg-ordningsvariabler)
- KRITISKT: För strukturerad JSON-utdata (output_type=json), måste du ALLTID använda \
  `{{ step_a.output.structured.fältnamn }}` — ALDRIG `{{ step_a.output.fältnamn }}`. \
  Nyckelordet `.structured.` är OBLIGATORISKT för att komma åt JSON-fält.
- Om du bara behöver 1-3 fält från ett JSON-steg ska du välja dessa specifika \
  `output.structured.*`-fält i underlaget i stället för att interpolera hela `output.text`.
- `{{ step_a.output.text }}` — ger stegets textutdata (alltid tillgängligt)
- `{{ step_a.output.structured.X }}` — ger specifika JSON-fält (kräver output_type=json)"""


_KNOWLEDGE_PACK_INSTRUCTIONS_AND_UNDERLAG = """\
# Instruktioner vs Underlag — hur de samverkar

Varje steg har två centrala texter som styr AI:ns beteende:

## Instruktioner (`assistant_spec.instructions`)
**VAD** AI:n ska göra och **HUR** den ska göra det.
- Styr uppdraget: uppgift, ton, svarsformat, begränsningar
- Variabler fungerar här men blir del av beteendet, inte bearbetad text
- Kan och bör vara LÅNGA och DETALJERADE för komplexa uppgifter
- Struktur: Inledning → Krav → Process → Utdataformat → Begränsningar

### Exempel på en detaljerad instruktion:
```
### START PÅ INSTRUKTION
Du är en assistent som hjälper till att formulera tydliga och effektiva att-satser.
Din indata är en kort beskrivning av ärendet samt ett antal att-satser skrivna av ovana handläggare.

KRAV FÖR ATT-SATSER:
- Varje att-sats ska endast avhandla en sak.
- Satserna ska ha tydlig referens om de hänvisar till andra dokument.
- Om det finns finansiella kostnader ska det specificeras vilken budget som ska användas.

UTDATAFORMAT:
- Ange sakligt vad som ska beslutas.
- Skriv som punktlista.

BEGRÄNSNINGAR:
- Undvik sammanslagning av flera beslut i en att-sats.
- Tydlighet framför komplexa formuleringar.
### SLUT PÅ INSTRUKTION
{{ Ärendet }}{{ Förslag-till-beslut }}{{ step_5.output.text }}
```

## Underlag / input_bindings.question
**VILKEN TEXT** AI:n ska bearbeta — det faktiska materialet.
- I `create_flow` skriver du inte `input_bindings.question` själv. Du beskriver bara `instructions`, \
  `input_source`, `uses_form_fields` och eventuell runtime-uppladdning; backend kompilerar underlaget.
- Byggs med variabler från formulär, tidigare steg och systemvariabler
- Om tomt → används resultatet från föregående steg automatiskt
- Används för att komponera indata från FLERA källor till ett steg
- När `runtime_input` är aktiverat och du skriver ett explicit underlag måste du ta med \
  `{{ step_input.text }}` eller annan relevant `step_input.*`-referens i frågetexten

### Exempel:
```json
{
  "question": "ÄRENDEDATA:\\n{{ Ärendenummer }}\\n\\nBAKGRUND:\\n{{ Bakgrund som text }}\\n\\nFÖRVALTNINGENS BEDÖMNING:\\n{{ Förvaltningens överväganden }}\\n\\nFÖRSLAG TILL BESLUT:\\n{{ Förslag-till-beslut }}"
}
```

### Exempel med formdata + runtime input + tidigare steg:
```json
{
  "question": "FORMULÄRDATA:\\nBrukare: {{ Brukarens namn }}\\nKontext: {{ Handläggningskontext }}\\n\\nKÖRNINGSDATA:\\n{{ step_input.text }}\\n\\nSTRUKTURERAD ANALYS:\\nSammanfattning: {{ step_a.output.structured.sammanfattning }}\\nRisk: {{ step_a.output.structured.risk }}\\n\\nTIDIGARE BEDÖMNING:\\n{{ step_b.output.text }}"
}
```

## Samverkan i praktiken
1. **Enkel kedja** (steg 2 bearbetar steg 1): Instruktioner räcker, underlag kan vara tomt
2. **Sammansättning** (steg kombinerar data från flera steg): Underlag bygger texten, \
   instruktioner styr bearbetningen
3. **Komplex produktion** (sista steget i en tjänsteskrivelse): Underlag samlar ALL \
   data, instruktioner beskriver format och krav i detalj

## Variabler i instruktioner vs underlag
- I **underlag**: `{{ step_c.output.text }}` → texten LÄGGS IN i underlaget
- I **instruktioner**: `{{ Ärendenummer }}` → värdet blir del av AI:ns beteende/kontext
- Båda fungerar, men underlaget är primärt stället för datainsamling

## Underlags-designmönster

### Selektiv sammansättning (bättre än all_previous_steps):
```json
{"question": "BAKGRUND:\\n{{ Bakgrund }}\\n\\nFAKTA FRÅN ANALYS:\\n{{ step_a.output.structured.sammanfattning }}\\n\\nRISKNIVÅ: {{ step_a.output.structured.risk }}\\n\\nTIDIGARE BESLUT:\\n{{ step_b.output.text }}"}
```
Detta ger exakt kontroll över vilken data steget får, utan att skicka ALL text \
från alla steg (som all_previous_steps gör).

### JSON-steg: välj fält hellre än rå blob
- Bra: `{{ step_a.output.structured.sammanfattning }}`
- Bra: `{{ step_a.output.structured.risk }}`
- Undvik som standard: `{{ step_a.output.text }}` när steg `step_a` producerar JSON och du \
  egentligen behöver specifika fält. Det gör underlaget bredare, mindre tydligt och svårare \
  för nästa steg att använda konsekvent.

### Använd rubriker för tydlighet:
Strukturera alltid underlaget med VERSALER-rubriker och dubbla radbrytningar (`\\n\\n`). \
AI:n bearbetar materialet bättre när det är tydligt avgränsat i sektioner."""


_KNOWLEDGE_PACK_CONTRACTS = """\
# Input- och utdatakontrakt (JSON Schema) — DJUPGUIDE

Kontrakt definierar förväntad form på data som passerar genom steget. \
De möjliggör striktare validering, driver variabelväljaren, och är \
nyckeln till att bygga robusta JSON-pipelines.

I create-läge skriver du inte rå `input_contract` eller `output_contract` själv. \
Beskriv i stället strukturerad JSON-utdata via `output_fields`; backend kompilerar \
detta till korrekt JSON Schema i den kanoniska specifikationen.

## Indatakontrakt (`input_contract`)
- Definierar förväntad form på inkommande data med JSON Schema (Draft 2020-12)
- Steget AVVISAR indata som inte matchar schemat — körs aldrig om data är felaktig
- BARA tillgängligt för input_type 'text' och 'json' (inte 'document', 'file', 'audio', 'any')
- Mest användbart med input_type 'json' för att validera strukturerad indata

### Enkelt indatakontrakt:
```json
{
  "type": "object",
  "properties": {
    "ärendenummer": { "type": "string" },
    "bakgrund": { "type": "string" },
    "prioritet": { "type": "string", "enum": ["hög", "medel", "låg"] }
  },
  "required": ["ärendenummer", "bakgrund"]
}
```

### Avancerat indatakontrakt med nästlad struktur:
```json
{
  "type": "object",
  "properties": {
    "ärende": {
      "type": "object",
      "properties": {
        "nummer": { "type": "string", "pattern": "^[A-Z]{2}-\\\\d{4}-\\\\d+$" },
        "rubrik": { "type": "string", "minLength": 5 },
        "kategori": { "type": "string", "enum": ["bygglov", "detaljplan", "miljö"] }
      },
      "required": ["nummer", "rubrik"]
    },
    "handlingar": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "typ": { "type": "string" },
          "sammanfattning": { "type": "string" }
        }
      }
    }
  },
  "required": ["ärende"]
}
```

## Utdatakontrakt (`output_contract`)
- Definierar förväntad form på stegets utdata med JSON Schema
- AI:n instrueras att producera JSON som matchar schemat
- Driver variabelväljaren — efterföljande steg ser kontraktets fält
- INTE tillgängligt för output_type 'text' eller med output_mode 'template_fill'
- Kräver output_type 'json' (eller 'pdf'/'docx' med schema type 'object'/'array')

### Utdatakontrakt som driver variabelväljaren:
```json
{
  "type": "object",
  "properties": {
    "sammanfattning": { "type": "string", "description": "Kort sammanfattning av ärendet" },
    "nyckelord": { "type": "array", "items": { "type": "string" } },
    "bedömning": {
      "type": "object",
      "properties": {
        "risk": { "type": "string", "enum": ["låg", "medel", "hög"] },
        "motivering": { "type": "string" },
        "rekommendation": { "type": "string" }
      }
    },
    "ekonomisk_påverkan": { "type": "number" }
  },
  "required": ["sammanfattning", "bedömning"]
}
```

Efterföljande steg kan sedan referera till specifika fält:
- `{{ step_a.output.structured.sammanfattning }}` — sammanfattningen
- `{{ step_a.output.structured.bedömning.risk }}` — risknivån
- `{{ step_a.output.structured.nyckelord }}` — nyckelordslistan (som JSON)

## Beslutstabell: När använda vilket mönster

| Scenario | input_type | output_type | Kontrakt? | Varför |
|----------|-----------|-------------|-----------|--------|
| Enkel textbearbetning | text | text | Nej | Text→text behöver ingen validering |
| Strukturerad extraktion | text | json | output_contract | Säkerställer AI producerar rätt fält |
| JSON-pipeline | json | json | Båda | Full validering av in- och utdata |
| Dokumentanalys → strukturerat | document | json | output_contract | Extraherar struktur från dokument |
| Text → DOCX-mall | text | docx | Nej | template_fill har sin egen bindningmekanism |
| Ljud → text | audio | text | Nej | Transkribering producerar alltid text |
| API-indata → bearbetning | json | text | input_contract | Validerar att API-indata har rätt form |

## Samspelet mellan kontrakt, underlag och instruktioner

### Mönster 1: Strukturerad extraktion
```
Steg 1: input_type=text, output_type=json, output_contract={...}
  Instruktioner: "Extrahera följande fält från texten. Svara ENBART med JSON."
  (Kontrakt säkerställer att AI:n producerar rätt fältstruktur)

Steg 2: input_type=json, output_type=text
  Underlag: "Sammanfattning: {{ step_a.output.structured.sammanfattning }}\\nRisk: {{ step_a.output.structured.bedömning.risk }}"
  Instruktioner: "Skriv ett beslutsunderlag baserat på analysen."
```

### Mönster 2: Validerad pipeline
```
Steg 1: input_type=json, input_contract={kräver "ärende", "bakgrund"}
  → Steget STOPPAR om indata saknar obligatoriska fält
  → Instruktioner bearbetar validerad data med full trygghet

Steg 2: output_type=json, output_contract={kräver "beslut", "motivering"}
  → AI:n MÅSTE producera dessa fält, annars misslyckas steget
  → Efterföljande steg kan tryggt referera till {{ step_b.output.structured.beslut }}
```

### Mönster 3: Formulär + kontrakt
```
Formulärfält: ärendenummer (text), kategori (select: [bygglov, detaljplan, miljö])
Steg 1: input_type=text, input_source=flow_input
  Underlag: "Ärende: {{ ärendenummer }}\\nKategori: {{ kategori }}"
  → Formulärdata valideras av formuläret, inte kontraktet
  → Kontrakt behövs inte här — formuläret sköter valideringen
```

## Kontraktsdriven pipeline — det kraftfullaste mönstret

Det mest effektiva sättet att bygga avancerade flöden:
1. Steg A: output_type=json + output_contract → AI:n producerar strukturerad data
2. Steg B: input_bindings.question plockar SPECIFIKA fält via \
`{{ step_a.output.structured.fältnamn }}`
3. Steg C: Kan använda fält från BÅDE steg A och B

### Komplett exempel:
```
Steg 1 (Extrahera): output_type=json, output_contract:
  {"type": "object", "properties": {
    "sammanfattning": {"type": "string", "description": "Kort sammanfattning"},
    "risk": {"type": "string", "enum": ["låg", "medel", "hög"], "description": "Risknivå"}
  }, "required": ["sammanfattning", "risk"]}
  Instruktioner: "Extrahera en sammanfattning och risknivå. Svara som JSON med fälten \
'sammanfattning' och 'risk' (låg/medel/hög)."

Steg 2 (Bedöm): input_bindings.question:
  {"question": "SAMMANFATTNING:\\n{{ step_a.output.structured.sammanfattning }}\\n\\n\
RISKNIVÅ: {{ step_a.output.structured.risk }}\\n\\nSkriv en rekommendation."}
```

Notera: Instruktioner SKA nämna de fält som output_contract kräver, så AI:n vet exakt \
vad den ska producera.

## Instruktioner ska nämna kontraktets fält

När ett steg har output_contract, SKA instruktionerna explicit nämna de fält AI:n \
förväntas producera. Detta förbättrar träffsäkerheten dramatiskt:

BRA: "Analysera texten och returnera JSON med fälten 'sammanfattning' (kort text), \
'risk' (låg/medel/hög), och 'rekommendation' (åtgärdsförslag)."

DÅLIGT: "Analysera texten och returnera strukturerad data."

## Viktiga regler för kontrakt
- Kontrakt använder JSON Schema Draft 2020-12 (standard jsonschema)
- Indatakontrakt: valideras INNAN steget körs — steget misslyckas om data inte matchar
- Utdatakontrakt: valideras EFTER att AI producerat svar — steget misslyckas om utdata \
  inte matchar (AI:n instrueras automatiskt att följa schemat)
- Kontrakt bör ha `"description"` på fält — hjälper BÅDE AI:n och variabelväljaren
- Skriv `"description"` och `"title"` i JSON Schema-kontrakt på svenska — de visas i gränssnittet
- `"required"` bör användas för kritiska fält
- Undvik att göra ALLA fält required — låt AI:n skipa fält den inte hittar information för"""


_KNOWLEDGE_PACK_RECIPES = """\
# Beprövade flödesrecept

## 1. Transkribering → Sammanfattning (2 steg)
```
Steg 1: Transkribera ljud (flow_input, audio, transcribe_only, text)
Steg 2: Sammanfatta transkription (previous_step, text, pass_through, text)
```

## 2. Dokumentanalys: Extrahera → Bedöm → Producera (3 steg)
```
Steg 1: Extrahera fakta (flow_input, document/text, pass_through, text)
Steg 2: Bedöm konsekvenser (previous_step, text, pass_through, text)
Steg 3: Skriv beslutsunderlag (all_previous_steps ELLER previous_step med bindings)
```
Steg 3 kan använda `input_bindings.question` för att kombinera:
`{{ step_a.output.text }}` (fakta) + `{{ step_b.output.text }}` (bedömning)

## 3. GULDEXEMPEL: Kontraktsdriven ärendeanalys (komplett create_flow)

Följande visar exakt hur ett `create_flow`-anrop ska se ut — med formulär, \
typed `output_fields`, runtime-uppladdning och detaljerade instruktioner:

```json
{
  "flow_name": "Ärendeanalys med rekommendation",
  "flow_description": "Analyserar ärenden och producerar strukturerad bedömning med rekommendation",
  "plan_rationale": "Extraherar först strukturerad riskdata och skriver sedan en läsbar rekommendation.",
  "assumptions": [
    "Användaren laddar upp dokument vid körning",
    "Risknivå räcker som enum i den strukturerade analysen"
  ],
  "form_fields": [
    {"variable_name": "Ärendenummer", "field_type": "text", "label": "Ärendenummer", "required": true},
    {"variable_name": "Kategori", "field_type": "select", "label": "Kategori", "required": true,
     "options": ["bygglov", "detaljplan", "miljö"]}
  ],
  "steps": [
    {
      "name": "Extrahera och strukturera",
      "instructions": "Du är en ärendeanalytiker. Extrahera en kort sammanfattning, en risknivå och relevanta nyckelord från ärendedokumenten. Returnera enbart strukturerad JSON som matchar de begärda fälten.",
      "input_source": "flow_input",
      "input_type": "document",
      "output_type": "json",
      "runtime_upload": true,
      "runtime_required": true,
      "uses_form_fields": ["Ärendenummer", "Kategori"],
      "output_fields": [
        {"name": "sammanfattning", "field_type": "string", "description": "Sammanfattning av ärendet i 2-3 meningar", "required": true},
        {"name": "risk", "field_type": "string", "description": "Bedömd risknivå som låg, medel eller hög", "required": true},
        {"name": "nyckelord", "field_type": "array", "description": "Relevanta nyckelord", "required": false, "item_fields": [
          {"name": "värde", "field_type": "string", "description": "Ett nyckelord", "required": true}
        ]}
      ]
    },
    {
      "name": "Skriv rekommendation",
      "instructions": "Du är en handläggare som skriver rekommendationer. Skriv en tydlig rekommendation med inledning, analysens slutsatser, rekommenderad åtgärd och riskhantering. Skriv på formell svenska och håll dig under 500 ord.",
      "input_source": "previous_step",
      "input_type": "json",
      "output_type": "text",
      "uses_form_fields": ["Ärendenummer", "Kategori"]
    }
  ]
}
```

OBS: Bara ETT steg kan använda `flow_input`. Använd formulärfält för att samla \
flera indata. Backend genererar sedan stegrefar, underlag, kontrakt och variabelkopplingar.

## 4. JSON-pipeline med kontrakt (3 steg)
```
Steg 1: Parsa indata (flow_input, json, pass_through, json) med input_contract OCH output_contract
Steg 2: Berika data (previous_step, text, pass_through, json) med output_contract — \
         underlag: {{ step_a.output.structured.fält1 }}, {{ step_a.output.structured.fält2 }}
Steg 3: Formatera svar (previous_step, text, pass_through, text) — \
         underlag: {{ step_b.output.structured.resultat }}
```

## 5. Flerspråkig produktion (3 steg)
```
Steg 1: Analysera text (flow_input, text, pass_through, text)
Steg 2: Skriv svensk version (previous_step, text, pass_through, text)
Steg 3: Skriv engelsk version (previous_step, text, pass_through, text) — med underlag \
         {{ step_a.output.text }} för originaltexten
```"""


_KNOWLEDGE_PACK_ANTI_PATTERNS = """\
# Antimönster — undvik dessa

## ❌ Alla steg använder all_previous_steps
Varje steg som använder `all_previous_steps` får ALLA tidigare stegs utdata. \
I ett 10-stegsflöde innebär det att steg 10 får 9 stegs text. \
Token-kostnaden exploderar. Använd `previous_step` som standard och \
`all_previous_steps` bara när steget verkligen behöver sammanställa allt.

## ❌ Ett steg som gör allt
"Extrahera fakta, bedöm konsekvenser och skriv sammanfattning" i ETT steg. \
Dela upp i separata steg — varje steg gör EN sak bra.

## ❌ Generiska instruktioner
"Sammanfatta texten." → FÖR VAGT. Skriv istället:
"Sammanfatta de viktigaste punkterna i tre stycken. Fokusera på ekonomiska \
konsekvenser och juridiska aspekter. Skriv på formell svenska."

## ❌ Tomma instruktioner
Varje steg MÅSTE ha meningsfulla instruktioner. Instruktionen är det som gör \
steget värdefullt.

## ❌ Onödiga steg
Om hela flödet kan göras i 2 steg, skapa inte 5. Varje steg ska tillföra värde.

## ❌ Fel input_source
- Steg 1 med `previous_step` eller `all_previous_steps` → FEL. Första steget är alltid runtime-ingången och ska använda `flow_input`
- `previous_step` när du behöver data från steg 1 och 3 (inte bara 2) → Använd \
  `input_bindings.question` med variabler istället
- `all_previous_steps` när du bara behöver föregående → Slöseri med tokens

## ❌ Glömmer att underlag kan byggas med variabler
Istället för `all_previous_steps` kan du ofta använda `previous_step` med \
`input_bindings.question` som explicit plockar de variabler du behöver. Detta \
ger bättre kontroll och lägre tokenförbrukning.

## ❌ Interpolerar hela JSON-blobs när bara några fält behövs
Om ett tidigare steg producerar `output_type=json` ska du normalt välja de fält som \
behövs via `{{ step_a.output.structured.fält }}`. Att mata in hela `{{ step_a.output.text }}` \
ger ett bredare och mer brusigt underlag.

## ❌ Aktiverar runtime_input men glömmer step_input i underlaget
Om ett steg har `input_config.runtime_input.enabled=true` och samtidigt använder \
`input_bindings.question`, måste underlaget innehålla `{{ step_input.text }}` eller annan \
relevant `step_input.*`-referens. Annars konsumeras inte körningsindatan."""


_KNOWLEDGE_PACK_STEP_DESIGN = """\
# Stegdesignprinciper

## Namngivning
- Använd beskrivande svenska namn: "Extrahera fakta", "Bedöm konsekvenser"
- Undvik generiska namn: "Steg 1", "Bearbeta"
- Namnet är användarens etikett. `plan_step_ref` är den kanoniska AI Builder-referensen.

## Instruktionsdesign
- **Inledning**: Vem är AI:n? Vad är uppgiften?
- **Krav**: Vad ska ingå? Vilka regler gäller?
- **Process**: Steg-för-steg om det behövs
- **Utdataformat**: Exakt hur svaret ska se ut
- **Begränsningar**: Vad AI:n INTE ska göra
- Instruktioner ska vara proportionerliga mot uppgiften — korta när steget är enkelt, \
  långa när format, regler eller beslutslogik kräver det.

## Underlagsdesign (input_bindings.question)
- Strukturera med tydliga rubriker: `ÄRENDEDATA:\\n{{ var }}\\n\\nBAKGRUND:\\n{{ var }}`
- Använd deklarerade `plan_step_ref`-värden för stegvariabler: `{{ step_a.output.text }}`
- Kombinera formulärdata OCH stegutdata i samma underlag
- Lägg normalt metadata/formfält först, sedan `step_input.text` om runtime_input används, \
  och därefter tidigare stegresultat

## Kedjedesign
- **Enkel kedja**: steg 1 → 2 → 3, varje steg bearbetar föregående
- **Sammansättning**: steg N hämtar selektivt från steg 1, 3, 5 via variabler
- **Bred insamling**: steg N använder `all_previous_steps` (sparsamt!)

## Formulärfält
- Använd `form_fields` för att samla strukturerad indata från användaren
- Fältnamn = variabelnamn — välj med omsorg
- Vanliga typer: text (fritext), select (val), multiselect (flerval), number, date"""


_KNOWLEDGE_PACK_IO_INTELLIGENCE = """
## Steg-IO: Bästa praxis

### Input → Output typ-kombinationer
- Ljud → text: Alltid `transcribe_only` på första steget, `pass_through` på resten
- Dokument → JSON: Använd `output_contract` med namngivna fält och beskrivningar
- JSON → text: Använd `input_bindings.question` med `{{ step_X.output.structured.field }}`
- Dokument → DOCX: Separera extrahering (JSON) från dokumentgenerering (template_fill)
- Multi-dokument: `all_previous_steps` ELLER `input_bindings` med specifika steg-refs

### Underlag efter stegintention
- **Analysera / bedöma**: ge AI:n sammanställd sakdata via rubriker + specifika fält
- **Sammanfatta**: mata främst text (`previous_step` eller `step_input.text`) och bara nödvändig metadata
- **Generera dokument**: samla färdiga beslutsunderlag, rubriker och utvalda JSON-fält — inte rå JSON
- **Jämföra flera källor**: använd selektiva bindings eller `all_previous_steps` bara när ALLA föregående steg faktiskt behövs

### När ska man använda JSON output?
- När nästa steg behöver specifika datapunkter (inte bara fritext)
- När man vill ha deterministisk vidarebearbetning
- Alltid med tydliga `output_fields` — backend skapar då rätt kontrakt

### När ska man INTE använda JSON output?
- När slutresultatet är en rapport eller sammanfattning → text
- När steget bara ska omformulera eller sammanfatta → text

### Referensdisciplin
- I create-läge deklarerar du inte stegrefar alls — backend gör det
- Använd inte `step_1`, `step_2` eller stegnamn-alias i nya utkast
- Om ett kompilerat explicit underlag används för runtime-uppladdningar måste det innehålla riktiga \
  `step_input.*`-referenser; backend kompilerar detta i create-läge"""


__all__ = [
    "_KNOWLEDGE_PACK_ANTI_PATTERNS",
    "_KNOWLEDGE_PACK_CONTRACTS",
    "_KNOWLEDGE_PACK_FLOW_ARCHITECTURE",
    "_KNOWLEDGE_PACK_IO_INTELLIGENCE",
    "_KNOWLEDGE_PACK_INSTRUCTIONS_AND_UNDERLAG",
    "_KNOWLEDGE_PACK_RECIPES",
    "_KNOWLEDGE_PACK_STEP_DESIGN",
    "_KNOWLEDGE_PACK_VARIABLE_SYSTEM",
]

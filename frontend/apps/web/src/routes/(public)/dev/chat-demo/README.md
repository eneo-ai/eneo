# Chain of Thought — chatt-idéskiss (prototyp)

> Planeringsartefakt. Inte produktionskod. Nås på **`/dev/chat-demo`** (ingen
> inloggning — ligger i `(public)`-gruppen). Tar med `<!-- eslint-disable
intric/no-hardcoded-text -->` per fil eftersom demo-copy inte ska
> i18n-översättas.

## Varför

Dagens chatt visar bara ett animerat **"Thinking…"-badge** (`ThinkingIndicator.svelte`)
medan modellen resonerar — användaren ser _att_ något händer, men inte _vad_.
Kända aktörer (ChatGPT, Claude, Perplexity) visar istället en **hopfällbar
resonemangs-vy**: live-uppdaterade steg under tiden, som auto-fälls ihop till en
diskret "Thought for 5s"-rad när svaret börjar. [AI SDK
Elements](https://elements.ai-sdk.dev/components/chain-of-thought) paketerar exakt
det mönstret.

Vi kan inte importera den komponenten — den är **React + Radix**. Eneo är
**Svelte 5 + bits-ui**. Så vi portar UX:en till våra primitiver och tokens. Det är
ett litet, inkapslat jobb. Den här mappen visar slutresultatet.

## Vad demon visar

- **Nuläge vs Förslag** — växla högst upp för att jämföra `ThinkingIndicator`
  med den nya `ChainOfThought`-komponenten i samma flöde.
- **Simulerad körning** — skicka-knappen spelar upp reasoning-steg (med status:
  pending → active → complete), auto-kollaps, och därefter streamat svar renderat
  genom riktiga `@intric/ui` `Markdown`.
- **Sökresultat-pills** per steg — visar hur RAG-/MCP-källor kan ytas i tracen.

## Filer

| Fil                                    | Roll                                                                 | Motsvarar i AI SDK Elements                                         |
| -------------------------------------- | -------------------------------------------------------------------- | ------------------------------------------------------------------- |
| `components/ChainOfThought.svelte`     | Hopfällbar container, header (`Brain` + titel/varaktighet + chevron) | `ChainOfThought` + `ChainOfThoughtHeader` + `ChainOfThoughtContent` |
| `components/ChainOfThoughtStep.svelte` | Ett steg på tidslinjen, statusnod + connector + valfritt innehåll    | `ChainOfThoughtStep` + `ChainOfThoughtSearchResults`                |
| `+page.svelte`                         | Demo-scen: jämförelse + simulerad streaming                          | —                                                                   |

## Verktyg (tools) i tracen

Det här är den knepiga delen. Eneo har redan verktygsanrop i
`MessageAnswer.svelte` med status, `tool_name`/`server_name`, expanderbara
argument och en **godkännande-gate** (`chat.pendingToolApproval`,
`approveTool` / `denyTool`, bulk-actions). Idag ligger de som ett block _ovanför_
svaret, frikopplat från resonemanget.

I Chain of Thought-modellen är ett verktygsanrop bara **ett steg till** i tracen,
interleavat med resonemanget (tänk → sök → observera → tänk → agera → svara).
`ChainOfThoughtTool.svelte` renderar exakt det: samma data som idag, fast som en
nod på tidslinjen med expanderbart anrop och ett resultat (`→ 3 avtal hittade`).

**Konflikten — och lösningen:** ett _väntande godkännande_ blockerar och kräver
användarens beslut. Det får aldrig gömmas i en hopfälld "Thought for 5s"-rad.
Därför:

- Verktyg som är klara (eller nekade) lever **inne** i tracen som steg.
- Ett **pending** godkännande lyfts **ut** ur det hopfällbara — ett tydligt kort
  under tracen, och tracen tvingas öppen så användaren ser kontexten. När beslutet
  är taget fälls verktyget tillbaka in som ett `complete`/`denied`-steg.

Demon visar att approval-kortet är **identiskt prominent i båda varianterna** —
det är bara resonemanget runt omkring som ändras. Poängen: vi vinner en
sammanhängande trace utan att tumma på den blockerande approval-UX:en ni redan har.

Mappning till befintlig kod när det blir på riktigt:

| Demo                                         | Produktion                                                     |
| -------------------------------------------- | -------------------------------------------------------------- |
| `step.status` (`active`/`complete`/`denied`) | `toolCall.approved` + streaming-state i `MessageAnswer.svelte` |
| `approve()` / `deny()`                       | `chat.approveTool(id)` / `chat.denyTool(id)`                   |
| `pendingStep` utlyft                         | `chat.pendingToolApproval` (inkl. bulk för flera samtidigt)    |
| `step.args`                                  | `toolCall.arguments`                                           |

## Vad som krävs för att göra det till produktion

UI:t är den enkla halvan. Den verkliga blockeraren är **data**:

1. **Reasoning-content från backend.** Idag fångas/streamas ingen reasoning-text —
   `isReasoning` i `Message.svelte` är bara `modelCanReason && answer === ""`.
   För att fylla stegen behöver backend streama reasoning-deltas (t.ex. Anthropic
   `thinking`-block) över befintliga SSE/WebSocket-kanalen. **Detta måste verifieras
   först** — utan det blir Chain of Thought bara ett snyggare tomt skal.
2. **Stegmodell.** Bestäm om steg = råa reasoning-tokens (en lång text) eller
   strukturerade steg (verktygsanrop, sökningar, slutsats). MCP-verktygsanrop finns
   redan i `MessageAnswer.svelte` och kan flyttas in i tracen.

## Föreslagen utrullning

1. **Fas 0 – verifiera data:** kolla om completion-flödet kan streama reasoning.
   Avgör om detta är "byt UI" eller "lägg till reasoning-streaming".
2. **Fas 1 – komponent:** flytta porten hit till
   `lib/features/chat/components/conversation/`, byt slide-transition mot delade
   `lib/components/ui/collapsible`-primitiven (a11y), i18n:a all text via `m.*`.
3. **Fas 2 – koppla data:** rendera riktiga reasoning-deltas; behåll
   `ThinkingIndicator` som fallback för modeller utan reasoning-output.
4. **Fas 3 – berika:** flytta in MCP-verktygsanrop och RAG-källor som steg i tracen.

## Städning

Hela mappen `(public)/dev/chat-demo/` är fristående och kan raderas i ett svep när
planeringen är klar.

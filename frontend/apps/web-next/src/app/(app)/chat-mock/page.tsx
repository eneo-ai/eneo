import { Message, MessageContent } from "@/components/ai-elements/message";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ChatMessage } from "@/features/chat/chat-message";
import type { Schema } from "@/lib/api/models";
import type { EneoUIMessage } from "@/lib/chat/types";
import { Globe, History, Paperclip, Plus, Send, Sparkles } from "lucide-react";

/**
 * Design preview route (`/chat-mock`): renders the REAL chat components
 * (ChatMessage → ActivityTimeline, MessageResponse, sources, …) against
 * hand-built mock data so we can eyeball the agentic flow — every tool state,
 * knowledge sources, lots of references — in its worst case without a backend.
 * Not linked from the app; safe to delete once the design is signed off.
 */

type Part = EneoUIMessage["parts"][number];

const src = (sourceId: string, title: string, url?: string): Part => ({
  type: "source-document",
  sourceId,
  mediaType: url ? "text/html" : "application/pdf",
  title,
  providerMetadata: url ? { eneo: { metadata: { url } } } : undefined
});

const file = (id: string, name: string, mimetype: string): Schema<"FilePublic"> =>
  ({ id, name, mimetype, size: 184_000 }) as Schema<"FilePublic">;

// Inline SVG (data URI) so the "generated image" variant renders with no API.
const CHART =
  "data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSI0ODAiIGhlaWdodD0iMjAwIiB2aWV3Qm94PSIwIDAgNDgwIDIwMCI+PHJlY3Qgd2lkdGg9IjQ4MCIgaGVpZ2h0PSIyMDAiIGZpbGw9IiNlZWYyZmIiLz48ZyBmaWxsPSIjMzI1N2M0Ij48cmVjdCB4PSI0MCIgeT0iMTIwIiB3aWR0aD0iNTAiIGhlaWdodD0iNjAiLz48cmVjdCB4PSIxMzAiIHk9IjgwIiB3aWR0aD0iNTAiIGhlaWdodD0iMTAwIi8+PHJlY3QgeD0iMjIwIiB5PSI1MCIgd2lkdGg9IjUwIiBoZWlnaHQ9IjEzMCIvPjxyZWN0IHg9IjMxMCIgeT0iMTAwIiB3aWR0aD0iNTAiIGhlaWdodD0iODAiLz48cmVjdCB4PSI0MDAiIHk9IjcwIiB3aWR0aD0iNTAiIGhlaWdodD0iMTEwIi8+PC9nPjx0ZXh0IHg9IjI0IiB5PSIyOCIgZm9udC1mYW1pbHk9InNhbnMtc2VyaWYiIGZvbnQtc2l6ZT0iMTYiIGZpbGw9IiMxYjJhNGUiPkF2dmlrZWxzZXIgcGVyIGtvbW11bjwvdGV4dD48L3N2Zz4=";

const ANSWER = [
  "## Sammanfattning",
  "",
  "Er upphandlingspolicy uppfyller **i huvudsak** LOU. Direktupphandlingsgränsen `700 000 kr` stämmer med tröskelvärdet, men tre kommuner avviker på efterannonsering.",
  "",
  "### Avvikelser per kommun",
  "",
  "| Kommun | Efterannonsering | Tröskelvärde | Avvikelse |",
  "| --- | --- | --- | --- |",
  "| Sundsvall | Saknas | Korrekt | Hög |",
  "| Umeå | Delvis | Korrekt | Medel |",
  "| Gävle | Finns | Korrekt | Ingen |",
  "",
  "### Rekommendationer",
  "",
  "1. Lägg till krav på efterannonsering i avsnitt 4.",
  "2. Förtydliga delegationsordningen för belopp över tröskelvärdet.",
  "3. Inför stickprovskontroll varje kvartal.",
  "",
  "> Notera: tröskelvärdena justeras av EU vartannat år — bind inte beloppen hårt i policyn.",
  "",
  "Tröskelvärdet beräknas som $T = b \\times k$ där $b$ är basbeloppet.",
  "",
  "```json",
  '{ "direktupphandlingsgräns": 700000, "valuta": "SEK", "källa": "LOU kap. 19" }',
  "```"
].join("\n");

const KB_TITLES = [
  "Upphandlingspolicy 2024.pdf",
  "Delegationsordning §4.pdf",
  "LOU (2016:1145) kap. 19.pdf",
  "Riktlinjer direktupphandling.pdf",
  "Avvikelserapport Q3.pdf",
  "Inköpshandbok 2023.pdf",
  "Ramavtal IT-konsulter.pdf",
  "Revisionsrapport upphandling.pdf",
  "Tröskelvärden EU 2024.pdf",
  "Mall förfrågningsunderlag.pdf",
  "Beslutslogg nämnden.pdf",
  "Hållbarhetskrav inköp.pdf"
];

const reasoning: Part = {
  type: "reasoning",
  text: "Användaren vill ha en djupanalys mot LOU plus en jämförelse mellan tre kommuner. Jag hämtar policyn ur kunskapsbanken, kontrollerar tröskelvärden och annonseringskrav, jämför kommunerna och sammanställer avvikelser innan jag skriver svaret.",
  state: "done"
};

const tools: Part[] = [
  {
    type: "dynamic-tool",
    toolName: "search_knowledge_base",
    toolCallId: "call-1",
    state: "output-available",
    input: { query: "upphandlingspolicy tröskelvärden efterannonsering", top_k: 8 },
    output: { hits: 12, took_ms: 812 }
  },
  {
    type: "dynamic-tool",
    toolName: "web_search",
    toolCallId: "call-2",
    state: "output-available",
    input: { q: "LOU efterannonsering krav 2024" },
    output: { results: 10 }
  },
  {
    type: "dynamic-tool",
    toolName: "fetch_document",
    toolCallId: "call-3",
    state: "output-error",
    input: { url: "https://extern-kalla.se/policy.pdf" },
    errorText: "TimeoutError: upstream timed out after 10000ms"
  },
  {
    type: "dynamic-tool",
    toolName: "compare_municipalities",
    toolCallId: "call-4",
    state: "input-available",
    input: { municipalities: ["Sundsvall", "Umeå", "Gävle"], metric: "efterannonsering" }
  },
  {
    type: "dynamic-tool",
    toolName: "generate_chart",
    toolCallId: "call-5",
    state: "input-streaming",
    input: { type: "bar" }
  },
  {
    type: "dynamic-tool",
    toolName: "calculate_thresholds",
    toolCallId: "call-6",
    state: "output-available",
    input: { currency: "SEK", year: 2024 },
    output: { direktupphandlingsgräns: 700000 }
  }
];

const WEB_REFS = Array.from({ length: 10 }, (_, i) => ({
  id: `web-${i + 1}`,
  title:
    [
      "riksdagen.se — LOU (2016:1145)",
      "upphandlingsmyndigheten.se — efterannonsering",
      "konkurrensverket.se — tillsynsbeslut",
      "skr.se — vägledning inköp",
      "domstol.se — överprövningar",
      "eur-lex.europa.eu — direktiv 2014/24",
      "sundsvall.se — upphandlingspolicy",
      "umea.se — inköpsriktlinjer",
      "gavle.se — direktupphandling",
      "svenskt-naringsliv.se — analys"
    ][i] ?? `Källa ${i + 1}`,
  url: `https://example.org/ref-${i + 1}`
}));

type Entry = {
  message: EneoUIMessage;
  isStreaming?: boolean;
  showResponseLabel?: boolean;
};

const ENTRIES: { label: string; entries: Entry[] }[] = [
  {
    label: "Användarfråga med bilagor",
    entries: [
      {
        message: {
          id: "u-1",
          role: "user",
          metadata: {
            files: [
              file("f1", "Upphandlingspolicy 2024.pdf", "application/pdf"),
              file(
                "f2",
                "Avvikelserapport.docx",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
              )
            ]
          },
          parts: [
            {
              type: "text",
              text: "Gör en djupanalys av vår upphandlingspolicy mot LOU, jämför Sundsvall, Umeå och Gävle, och sammanställ avvikelserna."
            }
          ]
        }
      }
    ]
  },
  {
    label: "Värsta fall — resonemang, 6 verktyg, kunskap, referenser och genererad bild",
    entries: [
      {
        message: {
          id: "a-worst",
          role: "assistant",
          metadata: { webSearchReferences: WEB_REFS },
          parts: [
            reasoning,
            ...tools,
            { type: "text", text: ANSWER, state: "done" },
            { type: "file", mediaType: "image/svg+xml", filename: "avvikelser.svg", url: CHART },
            ...KB_TITLES.map((title, i) =>
              src(
                `kb-${i + 1}`,
                title,
                i % 4 === 0 ? `https://intranat.kommun.se/doc-${i + 1}` : undefined
              )
            )
          ]
        }
      }
    ]
  },
  {
    label: "Strömmande svar (timeline auto-expanderad, shimmer + spinner)",
    entries: [
      {
        isStreaming: true,
        message: {
          id: "a-stream",
          role: "assistant",
          parts: [
            {
              type: "reasoning",
              text: "Jag väger källorna mot varandra och förbereder en sammanställning av avvikelserna…",
              state: "streaming"
            },
            {
              type: "dynamic-tool",
              toolName: "compare_municipalities",
              toolCallId: "call-s1",
              state: "input-available",
              input: { municipalities: ["Sundsvall", "Umeå", "Gävle"] }
            },
            { type: "text", text: "Baserat på underlaget ser jag att", state: "streaming" }
          ]
        }
      }
    ]
  },
  {
    label: "Verktyg som kräver godkännande (MCP)",
    entries: [
      {
        message: {
          id: "a-approval",
          role: "assistant",
          parts: [
            {
              type: "reasoning",
              text: "De här åtgärderna använder MCP-verktyg som behöver ditt godkännande innan de körs.",
              state: "done"
            },
            {
              type: "data-tool-approval",
              id: "appr-1",
              data: {
                approval_id: "appr-1",
                status: "pending",
                tools: [
                  { server_name: "jira", tool_name: "create_issue", tool_call_id: "tc1" },
                  { server_name: "github", tool_name: "open_pull_request", tool_call_id: "tc2" },
                  { server_name: "slack", tool_name: "post_message", tool_call_id: "tc3" }
                ]
              }
            }
          ]
        }
      }
    ]
  },
  {
    label: "Enkelt svar — gruppchatt med @-svarsetikett",
    entries: [
      {
        showResponseLabel: true,
        message: {
          id: "a-clean",
          role: "assistant",
          metadata: { answeringAssistant: { id: "a1", handle: "juridik" } },
          parts: [
            {
              type: "text",
              text: "Kort svar: ja, policyn uppfyller LOU på de centrala punkterna. Den enda väsentliga luckan är efterannonsering i avsnitt 4.",
              state: "done"
            },
            src("c1", "LOU kap. 19.pdf"),
            src("c2", "Upphandlingsmyndigheten", "https://upphandlingsmyndigheten.se")
          ]
        }
      }
    ]
  }
];

export default function ChatMockPage() {
  return (
    <div className="bg-muted/30 min-h-[calc(100vh-3.25rem)] px-4 py-5">
      <div className="border-border/70 bg-background mx-auto flex min-h-[calc(100vh-5.75rem)] w-full max-w-6xl overflow-hidden rounded-lg border shadow-sm">
        <aside className="bg-sidebar text-sidebar-foreground border-sidebar-border hidden w-72 shrink-0 flex-col border-r p-3 md:flex">
          <div className="mb-4 flex items-center justify-between">
            <div>
              <p className="text-xs font-medium">Förhandsvisning</p>
              <h1 className="text-sm font-semibold">Chattdesign</h1>
            </div>
            <Button variant="outline" size="icon-sm" aria-label="Ny konversation">
              <Plus className="size-4" />
            </Button>
          </div>

          <nav className="flex flex-col gap-1" aria-label="Mockade samtal">
            {ENTRIES.map((section, index) => (
              <a
                key={section.label}
                href={`#mock-section-${index}`}
                className="hover:bg-sidebar-accent hover:text-sidebar-accent-foreground first:bg-sidebar-accent first:text-sidebar-accent-foreground rounded-md px-3 py-2 text-sm transition-colors"
              >
                <span className="block truncate font-medium">
                  {index === 0 ? "Upphandlingsanalys" : section.label}
                </span>
                <span className="text-muted-foreground mt-0.5 block truncate text-xs">
                  {index === 0 ? "Aktiv mockkonversation" : "Variant i samma chattvy"}
                </span>
              </a>
            ))}
          </nav>

          <div className="text-muted-foreground mt-auto rounded-md border px-3 py-2 text-xs">
            Renderar riktiga meddelandekomponenter med lokal scenario-data.
          </div>
        </aside>

        <section className="flex min-w-0 flex-1 flex-col">
          <header className="flex h-13 shrink-0 items-center gap-2.5 border-b px-4">
            <div className="bg-primary/10 text-primary grid size-8 place-items-center rounded-md">
              <Sparkles className="size-4" />
            </div>
            <div className="min-w-0">
              <h2 className="truncate text-sm font-semibold">Upphandlingsanalys mot LOU</h2>
              <p className="text-muted-foreground truncate text-xs">Mockad aktiv konversation</p>
            </div>
            <div className="ml-auto flex items-center gap-2">
              <Badge
                variant="outline"
                className="text-foreground hidden font-medium sm:inline-flex"
              >
                gpt-5.4-2026-03-05
              </Badge>
              <Button variant="outline" size="sm">
                <Plus className="size-4" />
                <span className="hidden sm:inline">Ny konversation</span>
              </Button>
              <Button variant="ghost" size="icon-sm" aria-label="Historik">
                <History className="size-4" />
              </Button>
            </div>
          </header>

          <div className="min-h-0 flex-1 overflow-y-auto">
            <div className="mx-auto flex w-full max-w-3xl flex-col gap-6 px-4 py-6">
              {ENTRIES.map((section, sectionIndex) => (
                <section
                  id={`mock-section-${sectionIndex}`}
                  key={section.label}
                  className="scroll-mt-20"
                >
                  {sectionIndex > 0 && (
                    <div className="mb-6 flex items-center gap-3">
                      <div className="bg-border h-px flex-1" />
                      <span className="text-muted-foreground text-xs font-medium">
                        {section.label}
                      </span>
                      <div className="bg-border h-px flex-1" />
                    </div>
                  )}
                  <div className="flex flex-col gap-6">
                    {section.entries.map((entry) => (
                      <ChatMessage
                        key={entry.message.id}
                        message={entry.message}
                        isStreaming={entry.isStreaming}
                        showResponseLabel={entry.showResponseLabel}
                      />
                    ))}
                  </div>
                </section>
              ))}

              <Message from="assistant">
                <MessageContent>
                  <div className="flex h-5 items-center gap-1" aria-live="polite">
                    <span className="bg-muted-foreground size-1.5 animate-pulse rounded-full" />
                    <span className="bg-muted-foreground size-1.5 animate-pulse rounded-full [animation-delay:200ms]" />
                    <span className="bg-muted-foreground size-1.5 animate-pulse rounded-full [animation-delay:400ms]" />
                    <span className="sr-only">Assistenten tänker</span>
                  </div>
                </MessageContent>
              </Message>
            </div>
          </div>

          <footer className="border-t px-4 py-4">
            <div className="mx-auto w-full max-w-3xl">
              <div className="bg-background focus-within:ring-ring/50 rounded-lg border shadow-xs focus-within:ring-[3px]">
                <textarea
                  readOnly
                  aria-label="Mockad fråga"
                  value="Följ upp med förslag på ändringar i policyn..."
                  className="text-foreground placeholder:text-muted-foreground min-h-20 w-full resize-none bg-transparent px-3 py-3 text-sm outline-none"
                />
                <div className="flex items-center justify-between gap-2 border-t px-2 py-2">
                  <div className="flex min-w-0 items-center gap-1">
                    <Button variant="outline" size="sm">
                      <Paperclip className="text-muted-foreground size-4" />
                      Bilagor
                    </Button>
                    <Button variant="outline" size="sm">
                      <Globe className="text-muted-foreground size-4" />
                      Webbsökning
                    </Button>
                  </div>
                  <Button size="icon-sm" aria-label="Skicka mockad fråga">
                    <Send className="size-4" />
                  </Button>
                </div>
              </div>
              <p className="text-muted-foreground mt-2.5 text-center text-[11.5px]">
                Data behandlas inom er infrastruktur
              </p>
            </div>
          </footer>
        </section>
      </div>
    </div>
  );
}

import { notFound } from "next/navigation";
import type { Schema } from "@/lib/api/models";
import type { EneoUIMessage } from "@/lib/chat/types";
import { ChatMock, type MockSection } from "./chat-mock.client";

/**
 * Design preview route (`/chat-mock`): renders the REAL chat components
 * (header, ChatMessage with the activity pill, the Aktivitet panel,
 * MessageResponse with tables and citations, tool approvals, the composer)
 * against hand-built mock data so we can eyeball the agentic flow in its worst
 * case without a backend. Not linked from the app; 404 in production.
 */

type Part = EneoUIMessage["parts"][number];

const src = (sourceId: string, title: string, url?: string): Part => ({
  type: "source-document",
  sourceId,
  mediaType: url ? "text/html" : "application/pdf",
  title,
  providerMetadata: url
    ? { eneo: { metadata: { url }, website_id: "kb-lou" } }
    : { eneo: { group_id: "kb-policy" } }
});

const file = (id: string, name: string, mimetype: string): Schema<"FilePublic"> =>
  ({ id, name, mimetype, size: 184_000 }) as Schema<"FilePublic">;

// Inline SVG (data URI) so the "generated image" variant renders with no API.
const CHART =
  "data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSI0ODAiIGhlaWdodD0iMjAwIiB2aWV3Qm94PSIwIDAgNDgwIDIwMCI+PHJlY3Qgd2lkdGg9IjQ4MCIgaGVpZ2h0PSIyMDAiIGZpbGw9IiNlZWYyZmIiLz48ZyBmaWxsPSIjMzI1N2M0Ij48cmVjdCB4PSI0MCIgeT0iMTIwIiB3aWR0aD0iNTAiIGhlaWdodD0iNjAiLz48cmVjdCB4PSIxMzAiIHk9IjgwIiB3aWR0aD0iNTAiIGhlaWdodD0iMTAwIi8+PHJlY3QgeD0iMjIwIiB5PSI1MCIgd2lkdGg9IjUwIiBoZWlnaHQ9IjEzMCIvPjxyZWN0IHg9IjMxMCIgeT0iMTAwIiB3aWR0aD0iNTAiIGhlaWdodD0iODAiLz48cmVjdCB4PSI0MDAiIHk9IjcwIiB3aWR0aD0iNTAiIGhlaWdodD0iMTEwIi8+PC9nPjx0ZXh0IHg9IjI0IiB5PSIyOCIgZm9udC1mYW1pbHk9InNhbnMtc2VyaWYiIGZvbnQtc2l6ZT0iMTYiIGZpbGw9IiMxYjJhNGUiPkF2dmlrZWxzZXIgcGVyIGtvbW11bjwvdGV4dD48L3N2Zz4=";

const ANSWER = [
  "## Sammanfattning",
  "",
  "Er upphandlingspolicy uppfyller **i huvudsak** LOU. Direktupphandlingsgränsen `700 000 kr` stämmer med tröskelvärdet[1], men tre kommuner avviker på efterannonsering[2].",
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
    toolName: "search_knowledge",
    toolCallId: "call-1",
    state: "output-available",
    input: { query: "upphandlingspolicy tröskelvärden efterannonsering", top_k: 8 },
    output: { hits: 12, took_ms: 812 },
    providerMetadata: { eneo: { server_name: "knowledge", title: null, purpose: null } }
  } as Part,
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

const ENTRIES: MockSection[] = [
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
  if (process.env.NODE_ENV === "production") notFound();
  return <ChatMock sections={ENTRIES} />;
}

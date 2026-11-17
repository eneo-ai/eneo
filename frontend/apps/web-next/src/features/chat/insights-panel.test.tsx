// @vitest-environment jsdom
import { act, cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { StrictMode } from "react";
import { loadFixtures, sseResponse, toSseBody } from "@/lib/chat/contract-fixtures";
import type { ChatPartner } from "@/lib/chat/types";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";
import { observedElements, reportResize } from "@/test/setup-dom";
import { InsightsPanel } from "./insights-panel";

const CHAT = "/api/v1/analysis/conversation-insights/chat";
const CITED = "1a2b3c4d-0000-4000-8000-000000000001";
const SAVED = "22222222-0000-4000-8000-000000000002";
const GONE = "33333333-0000-4000-8000-000000000003";
/** The session the shared fixture's answer belongs to. */
const STREAMED = "11111111-1111-1111-1111-111111111111";

const counts = (user: number, widget: number, api_key: number) => ({
  total: user + widget + api_key,
  user,
  widget,
  api_key
});

/** The period's figures, and the previous period's when compared. */
const PERIOD = {
  start: "2026-09-02T00:00:00Z",
  end: "2026-10-03T00:00:00Z",
  conversations: counts(7, 4, 1),
  questions: counts(20, 8, 2),
  followups: 18,
  users: 5,
  single_question_conversations: 6,
  returning_users: 2,
  unanswered: 3,
  knowledge: { searched: 20, missed: 5 },
  answer_ratings: { positive: 7, negative: 2, with_comment: 1, negative_with_comment: 1 },
  conversation_ratings: { positive: 1, negative: 1, with_comment: 0, negative_with_comment: 0 }
};
const PREVIOUS = {
  ...PERIOD,
  conversations: counts(6, 3, 1),
  unanswered: 6,
  answer_ratings: { positive: 7, negative: 3, with_comment: 0, negative_with_comment: 0 }
};

/** A knowledge miss behind the "Många frågor får inget stöd i kunskapen" finding. */
const miss = (id: string, reason: string, rating: number | null) => ({
  kind: "knowledge_missed",
  question_id: id,
  question: `Vad kostar ${id}?`,
  session_id: `s-${id}`,
  source: "widget",
  created_at: "2026-10-01T10:00:00Z",
  reason,
  best_score: reason === "weak_score" ? 0.2 : null,
  rating
});

/** What the period's figures point at. */
const FINDINGS = [
  { kind: "knowledge_missed", affected: 5, base: 20, examples: [], sources: null, tool: null },
  {
    kind: "knowledge_unused",
    affected: 2,
    base: 3,
    examples: [],
    sources: [
      { kind: "collection", id: "k-1", name: "Taxa 2023", attached: true, answers: 0 },
      { kind: "website", id: "k-2", name: "Äldre riktlinjer", attached: true, answers: 0 }
    ],
    tool: null
  },
  { kind: "negative_ratings", affected: 1, base: 11, examples: [], sources: null, tool: null },
  {
    kind: "tool_failures",
    affected: 6,
    base: 10,
    examples: [],
    sources: null,
    tool: {
      kind: "capability",
      purpose: "web_search",
      server_name: null,
      tool_name: null,
      title: null,
      calls: 10,
      failed: 6,
      denied: 0
    }
  }
];

/** The period's ratings, newest first. */
const RATINGS = [
  {
    kind: "answer",
    value: -1,
    comment: "Hänvisar till en taxa som inte gäller.",
    question: "Vilken avgift gäller för eldstad?",
    question_id: "q-1",
    session_id: "s-rated",
    source: "widget",
    created_at: "2026-10-01T10:00:00Z"
  },
  {
    kind: "conversation",
    value: 1,
    comment: null,
    question: "Var parkerar jag?",
    question_id: null,
    session_id: "s-1",
    source: "user",
    created_at: "2026-09-30T10:00:00Z"
  }
];

const spies = vi.hoisted(() => ({
  announce: vi.fn(),
  /** The query of every request, by path. */
  queries: {} as Record<string, Record<string, unknown>[]>,
  /** The conversation the explore dialog was asked to show. */
  previewed: [] as string[],
  /** Every request to the insights chat: method, URL and JSON body. */
  requests: [] as { method: string; url: string; body: unknown }[],
  /** The analyses the list holds: its first page, and the next one when there is one. */
  analyses: [] as { id: string; name: string; created_at: string }[],
  nextPage: null as { id: string; name: string; created_at: string }[] | null,
  /** Analyses removed with their conversations: refused with 410. */
  removed: new Set<string>(),
  /** What a question streams back (an SSE body). */
  answer: "",
  toastError: vi.fn(),
  /** The period's findings, a finding's cases (two pages), its knowledge use and tools. */
  findings: [] as unknown[],
  cases: [] as unknown[],
  knowledge: { sources: [] as unknown[], unused: [] as unknown[] },
  tools: [] as unknown[]
}));

/** The options of a typed request, as far as these fakes read them. */
type TypedRequestInit = {
  params?: { query?: Record<string, unknown>; path?: Record<string, string> };
};

vi.mock("@/lib/api/browser", () => ({
  browserApi: {
    GET: vi.fn(async (path: string, init?: TypedRequestInit) => {
      if (path.startsWith(CHAT)) return typedInsightsChat("GET", path, init);
      const query = init?.params?.query ?? {};
      (spies.queries[path] ??= []).push(query);
      if (path === "/api/v1/analysis/conversation-insights/summary/") {
        return {
          data: {
            timezone: query.timezone,
            source: query.source ?? null,
            period: PERIOD,
            previous: query.compare ? PREVIOUS : null
          },
          response: new Response()
        };
      }
      if (path === "/api/v1/analysis/conversation-insights/activity/") {
        return {
          data: {
            timezone: query.timezone,
            source: query.source ?? null,
            start: query.start_time,
            end: query.end_time,
            days: [
              { date: "2026-09-30", conversations: counts(3, 1, 0), questions: counts(5, 1, 0) },
              { date: "2026-10-01", conversations: counts(0, 0, 2), questions: counts(0, 0, 2) }
            ]
          },
          response: new Response()
        };
      }
      if (path === "/api/v1/analysis/conversation-insights/feedback/") {
        const items = RATINGS.filter(
          (rating) =>
            (query.value === undefined || rating.value === query.value) &&
            (query.has_comment === undefined || Boolean(rating.comment) === query.has_comment)
        );
        return {
          data: { items, total_count: items.length, next_cursor: null },
          response: new Response()
        };
      }
      const period = { timezone: query.timezone, source: query.source ?? null, start: "", end: "" };
      if (path === "/api/v1/analysis/conversation-insights/findings/") {
        return { data: { ...period, findings: spies.findings }, response: new Response() };
      }
      if (path === "/api/v1/analysis/conversation-insights/findings/{kind}/") {
        // Two cases a page: the cursor is the offset of the next one.
        const offset = Number(query.cursor ?? 0);
        const next = offset + 2 < spies.cases.length ? String(offset + 2) : null;
        return {
          data: {
            ...period,
            kind: init?.params?.path?.kind,
            items: spies.cases.slice(offset, offset + 2),
            total_count: spies.cases.length,
            limit: query.limit,
            next_cursor: next
          },
          response: new Response()
        };
      }
      if (path === "/api/v1/analysis/conversation-insights/questions/top/") {
        return {
          data: {
            ...period,
            include_followups: true,
            total_questions: 30,
            groups: [
              {
                question: "Var parkerar jag?",
                occurrences: 12,
                share: 0.4,
                conversations: 10,
                unanswered: 3,
                ratings: { positive: 2, negative: 1 },
                knowledge: { searched: 0, missed: 0 },
                sample_session_id: "s-1"
              }
            ]
          },
          response: new Response()
        };
      }
      if (path === "/api/v1/analysis/conversation-insights/knowledge/") {
        return {
          data: { ...period, answers: 30, citing_answers: 20, ...spies.knowledge },
          response: new Response()
        };
      }
      if (path === "/api/v1/analysis/conversation-insights/tools/") {
        return { data: { ...period, tools: spies.tools }, response: new Response() };
      }
      if (path === "/api/v1/analysis/assistants/{assistant_id}/questions/") {
        return {
          data: { items: [], total_count: 0, next_cursor: null },
          response: new Response()
        };
      }
      if (path === "/api/v1/analysis/conversation-insights/sessions/") {
        return {
          data: {
            items: [{ id: "s-1", name: "Direktupphandling", source: "user" }],
            total_count: 1,
            next_cursor: null
          },
          response: new Response()
        };
      }
      if (path === "/api/v1/analysis/conversation-insights/sessions/{session_id}/") {
        spies.previewed.push(init?.params?.path?.session_id ?? "");
        return {
          data: {
            id: init?.params?.path?.session_id,
            name: "Parkering",
            source: "user",
            messages: [{ id: "m-1", question: "Var parkerar jag?", answer: "Vid entrén." }]
          },
          response: new Response()
        };
      }
      throw new Error(`Unexpected GET ${path}`);
    }),
    POST: vi.fn(async () => ({ data: {}, response: new Response() })),
    PUT: vi.fn(async () => ({ data: {}, response: new Response() })),
    DELETE: vi.fn(async (path: string, init?: TypedRequestInit) =>
      typedInsightsChat("DELETE", path, init)
    )
  }
}));

/**
 * The insights chat's endpoints, as the backend serves them. Every request is
 * logged by its URL: the turns come through the chat transport, the rest
 * through the typed client.
 */
async function insightsChat(input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
  const gone = () =>
    Response.json(
      { message: "Gone", code: "derived_source_removed" },
      { status: 410, headers: { "x-trace-id": "trace-1" } }
    );
  const url = new URL(String(input), "http://localhost");
  const method = init?.method ?? "GET";
  const body = typeof init?.body === "string" ? (JSON.parse(init.body) as unknown) : undefined;
  spies.requests.push({ method, url: `${url.pathname}${url.search}`, body });
  const [, session, ...rest] = url.pathname.slice(CHAT.length).split("/");
  if (session && spies.removed.has(session)) return gone();
  if (method === "POST") return sseResponse(spies.answer);
  if (method === "DELETE") return new Response(null, { status: 204 });
  if (!session) {
    const later = spies.nextPage ?? [];
    const total = spies.analyses.length + later.length;
    return url.searchParams.has("cursor")
      ? Response.json({ items: later, total_count: total })
      : Response.json({
          items: spies.analyses,
          total_count: total,
          next_cursor: spies.nextPage ? "2026-09-01T00:00:00Z" : null
        });
  }
  if (rest[0] === "tool-calls") {
    return Response.json({ tool_call_id: rest[1], result: "Frågor 1-2 av 2 om parkering" });
  }
  return Response.json({
    id: session,
    name: "Vad frågar folk om?",
    messages: [
      {
        id: "m-1",
        question: "Vad frågar folk om?",
        answer: "Mest om parkering.",
        created_at: "2026-10-01T10:00:00Z",
        updated_at: "2026-10-01T10:00:05Z"
      }
    ]
  });
}

/** A typed request to the insights chat, answered as the typed client answers it. */
async function typedInsightsChat(method: string, path: string, init?: TypedRequestInit) {
  const filled = path.replace(/\{(\w+)\}/g, (_, name: string) =>
    encodeURIComponent(init?.params?.path?.[name] ?? "")
  );
  const query = new URLSearchParams();
  for (const [name, value] of Object.entries(init?.params?.query ?? {})) {
    if (value !== undefined && value !== null) query.set(name, String(value));
  }
  const search = query.toString();
  const response = await insightsChat(search ? `${filled}?${search}` : filled, { method });
  const body: unknown = response.status === 204 ? undefined : await response.json();
  return response.ok ? { data: body, response } : { error: body, response };
}

vi.mock("@/lib/api/base", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api/base")>()),
  apiFetch: vi.fn(insightsChat)
}));
vi.mock("@astryxdesign/core/hooks", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@astryxdesign/core/hooks")>()),
  useAnnounce: () => spies.announce
}));
vi.mock("@/lib/navigation", () => import("@/test/navigation"));
vi.mock("@/lib/toast", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/toast")>();
  return { ...actual, toast: { ...actual.toast, error: spies.toastError } };
});

/**
 * An answer in the shared stream contract's tool-call fixture, made the
 * analysis': a search of the questions, and an answer that cites a
 * conversation. Each turn of an analysis is a message of its own: a second
 * answer passes its own `messageId`.
 */
function analysisAnswer(text: string, messageId?: string): string {
  const fixture = loadFixtures().find((item) => item.name === "tool-call-with-output")!;
  const events = fixture.events.map((event) => {
    if (event.type === "start" && messageId) return { ...event, messageId };
    if (event.type === "text-delta") return { ...event, delta: text };
    if (!String(event.type).startsWith("tool-")) return event;
    const eneo = (event.providerMetadata as { eneo: Record<string, unknown> }).eneo;
    return {
      ...event,
      ...(event.toolName ? { toolName: "search_questions" } : {}),
      ...(event.input ? { input: { query: "parkering" } } : {}),
      providerMetadata: { eneo: { ...eneo, server_name: "insights", title: "Search questions" } }
    };
  });
  return toSseBody(events);
}

beforeEach(() => {
  spies.answer = analysisAnswer(`De flesta frågar om parkering (session ${CITED}).`);
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  sessionStorage.clear();
  spies.announce.mockReset();
  spies.queries = {};
  spies.previewed.length = 0;
  spies.requests.length = 0;
  spies.analyses = [];
  spies.nextPage = null;
  spies.removed.clear();
  spies.toastError.mockReset();
  spies.findings = [];
  spies.cases = [];
  spies.knowledge = { sources: [], unused: [] };
  spies.tools = [];
});

const partner: ChatPartner & { type: "assistant" } = {
  type: "assistant",
  id: "assistant-1",
  name: "Upphandlingsassistenten",
  insightEnabled: true
};

/** The query of every request to one of the insight endpoints: "summary", "activity", "feedback". */
const queriesOf = (name: string) =>
  spies.queries[`/api/v1/analysis/conversation-insights/${name}/`] ?? [];

/** "Fråga analysen", in the view's filters. */
const askButton = () => screen.getByRole("button", { name: "Fråga analysen" });

/**
 * Lays out the row the overview shares with the analysis, as a browser
 * measures it: the outermost measured element around "Fråga analysen".
 */
function layOutRow(width: number) {
  const button = askButton();
  const regions = observedElements().filter((element) => element.contains(button));
  const row = regions.find((element) => regions.every((other) => element.contains(other)));
  if (row) act(() => reportResize(row, { width, height: 700 }));
}

/** The assistant's editor, for a user who may edit it. */
const EDITOR = "/spaces/space-1/assistants/assistant-1/edit";

/** Renders the tab with room for the analysis beside the overview (`width`). */
function renderPanel({
  width = 1200,
  editHref,
  strict = false
}: {
  width?: number;
  editHref?: string;
  /** Under StrictMode, as the app runs in development: effects run twice on mount. */
  strict?: boolean;
} = {}) {
  const tab = (
    <div className="flex h-[700px] flex-col">
      <InsightsPanel partner={partner} editHref={editHref} />
    </div>
  );
  const view = renderInApp(strict ? <StrictMode>{tab}</StrictMode> : tab);
  layOutRow(width);
  return view;
}

/** Opens the analysis panel from "Fråga analysen". */
function openAnalysis() {
  fireEvent.click(askButton());
  return screen.getByRole("complementary", { name: "Insiktsanalys" });
}

/** Types a question in the field, which has the focus, and sends it. */
function ask(question: string) {
  const field = screen.getByRole("textbox", { name: "Fråga om användningen" });
  act(() => field.focus());
  fireEvent.change(field, { target: { value: question } });
  fireEvent.click(screen.getByRole("button", { name: "Skicka meddelande" }));
}

/** The questions sent to the analysis. */
const questions = () => spies.requests.filter((request) => request.method === "POST");

/** Lays out the regions around the conversation (the view's row, the panel's), as a browser measures them. */
function layOutConversation(width: number) {
  const log = screen.getByRole("log");
  const regions = observedElements().filter((element) => element.contains(log));
  act(() => {
    for (const region of regions) reportResize(region, { width, height: 700 });
  });
}

describe("InsightsPanel", () => {
  it("covers the last 30 days as whole local days and refetches for a preset period", async () => {
    vi.useFakeTimers({ toFake: ["Date"], now: new Date(2026, 9, 2, 12) });
    renderPanel();
    await screen.findByText("Bra svar enligt betygen");
    // From the first day's midnight to the midnight after the last (exclusive), in the browser's zone.
    const period = {
      start_time: new Date("2026-09-02T00:00:00").toISOString(),
      end_time: new Date("2026-10-03T00:00:00").toISOString(),
      timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
      assistant_id: "assistant-1"
    };
    expect(queriesOf("summary")[0]).toEqual({ ...period, compare: false });
    expect(queriesOf("activity")[0]).toEqual(period);

    fireEvent.click(screen.getByRole("button", { name: /Period/ }));
    fireEvent.click(await screen.findByRole("button", { name: "Senaste 7 dagarna" }));
    await waitFor(() =>
      expect(queriesOf("summary").at(-1)).toMatchObject({
        start_time: new Date("2026-09-25T00:00:00").toISOString(),
        end_time: new Date("2026-10-03T00:00:00").toISOString()
      })
    );
  });

  it("shows the period's figures, its activity per day and its conversations to explore", async () => {
    vi.useFakeTimers({ toFake: ["Date"], now: new Date(2026, 9, 2, 12) });
    renderPanel();
    const tiles = await screen.findByRole("region", { name: "Nyckeltal" });
    const tile = (label: string) => within(tiles).getByText(label).closest("div")!.textContent;
    // Conversations per source, never people: widget and API traffic is no one's.
    expect(tile("Konversationer")).toMatch(
      /^Konversationer12\s*7 från användare, 4 via widget och 1 via API$/
    );
    expect(tile("Besvarade frågor")).toMatch(
      /Indikativt.*90\s%3 av 30 svar säger att de inte kan svara/
    );
    expect(tile("Bra svar enligt betygen")).toMatch(
      /78\s%7 bra och 2 dåliga\. 30\s% av svaren har betyg.*Hela konversationer: 1 bra och 1 dålig/
    );
    expect(tile("Träff i kunskapen")).toMatch(/75\s%5 frågor fick ingen träff i kunskapen/);
    // Nothing is compared until asked for.
    expect(within(tiles).queryByText(/jämfört med föregående period/)).toBeNull();
    expect(screen.getByRole("list", { name: "Hur konversationerna går" }).textContent).toMatch(
      /2,5 frågor per konversation.*50\s% slutar efter första svaret.*40\s% av användarna/
    );

    // The chart's figures as a table, every day of the period, also the ones without activity.
    const table = await screen.findByRole("table", { name: "Aktivitet per dag" });
    const rows = within(table).getAllByRole("row");
    expect(rows).toHaveLength(32);
    const cells = (row: HTMLElement) =>
      [within(row).getByRole("rowheader"), ...within(row).getAllByRole("cell")].map(
        (cell) => cell.textContent
      );
    expect(rows.slice(-3).map(cells)).toEqual([
      ["30 sep. 2026", "3", "1", "0", "4"],
      ["1 okt. 2026", "0", "0", "2", "2"],
      ["2 okt. 2026", "0", "0", "0", "0"]
    ]);

    fireEvent.click(screen.getByRole("button", { name: "Utforska konversationer" }));
    const dialog = await screen.findByRole("dialog", { name: "Utforska konversationer" });
    expect(await within(dialog).findByRole("button", { name: /Direktupphandling/ })).toBeTruthy();
  });

  it("limits everything that reads conversations to the chosen source", async () => {
    vi.useFakeTimers({ toFake: ["Date"], now: new Date(2026, 9, 2, 12) });
    renderPanel();
    await screen.findByText("Bra svar enligt betygen");
    fireEvent.click(screen.getByRole("radio", { name: "Widget" }));

    const widgetOnly = (name: string) =>
      waitFor(() => expect(queriesOf(name).at(-1)).toMatchObject({ source: "widget" }));
    await widgetOnly("summary");
    await widgetOnly("activity");
    await widgetOnly("feedback");
    await waitFor(() =>
      expect(
        spies.queries["/api/v1/analysis/assistants/{assistant_id}/questions/"]?.at(-1)
      ).toMatchObject({ source: "widget" })
    );
    // The chart and its table show that source alone.
    const table = await screen.findByRole("table", { name: "Aktivitet per dag" });
    expect(
      within(table)
        .getAllByRole("columnheader")
        .map((cell) => cell.textContent)
    ).toEqual(["Dag", "Widget"]);
    fireEvent.click(screen.getByRole("button", { name: "Utforska konversationer" }));
    const dialog = await screen.findByRole("dialog", { name: "Utforska konversationer" });
    await widgetOnly("sessions");
    // Every source (the start) sends no source at all.
    expect(queriesOf("summary")[0]).not.toHaveProperty("source");
    expect(await within(dialog).findByText("Användare")).toBeTruthy();
  });

  it("compares each figure with the previous period when asked", async () => {
    renderPanel();
    const tiles = await screen.findByRole("region", { name: "Nyckeltal" });
    fireEvent.click(screen.getByRole("switch", { name: "Jämför med föregående period" }));
    await waitFor(() => expect(queriesOf("summary").at(-1)).toMatchObject({ compare: true }));
    const tile = (label: string) => within(tiles).getByText(label).closest("div")!;
    // A count changes in percent, a share in points; the words say what it is compared with.
    await waitFor(() =>
      expect(tile("Konversationer").textContent).toMatch(/\+20\s% jämfört med föregående period/)
    );
    expect(tile("Besvarade frågor").textContent).toMatch(
      /\+10 procentenheter jämfört med föregående period/
    );
    expect(tile("Bra svar enligt betygen").textContent).toMatch(/\+8 procentenheter/);
    expect(tile("Träff i kunskapen").textContent).toMatch(
      /oförändrat jämfört med föregående period/
    );
  });

  it("lists the users' ratings, filters them and opens a rating's conversation", async () => {
    renderPanel();
    const inbox = await screen.findByRole("region", { name: "Återkoppling från användarna" });
    const [answer, conversation] = await within(inbox).findAllByRole("listitem");
    expect(answer!.textContent).toMatch(
      /”Hänvisar till en taxa som inte gäller\.”På frågan: Vilken avgift gäller för eldstad\?Dåligt betyg på svaretWidget/
    );
    expect(conversation!.textContent).toMatch(
      /Ingen kommentarPå frågan: Var parkerar jag\?Bra betyg på hela konversationenAnvändare/
    );
    expect(within(inbox).getByText("Visar 2 av 2")).toBeTruthy();

    // Each filter says how many ratings it holds, as the summary counts them.
    expect(within(inbox).getByRole("radio", { name: "Alla (11)" })).toBeTruthy();
    expect(within(inbox).getByRole("radio", { name: "Bra (8)" })).toBeTruthy();
    fireEvent.click(within(inbox).getByRole("radio", { name: "Dåliga med kommentar (1)" }));
    await waitFor(() =>
      expect(queriesOf("feedback").at(-1)).toMatchObject({ value: -1, has_comment: true })
    );
    await waitFor(() => expect(within(inbox).getAllByRole("listitem")).toHaveLength(1));
    await waitFor(() => expect(spies.announce).toHaveBeenCalledWith("Visar 1 av 1"));
    fireEvent.click(within(inbox).getByRole("radio", { name: "Bra (8)" }));
    await waitFor(() => expect(queriesOf("feedback").at(-1)).toMatchObject({ value: 1 }));
    expect(queriesOf("feedback").at(-1)).not.toHaveProperty("has_comment");

    // "Läs konversationen" opens the rated conversation read-only.
    const open = await within(inbox).findByRole("button", { name: "Läs konversationen" });
    expect(open.getAttribute("aria-haspopup")).toBe("dialog");
    fireEvent.click(open);
    const dialog = await screen.findByRole("dialog", { name: "Utforska konversationer" });
    expect(await within(dialog).findByText("Vid entrén.")).toBeTruthy();
    expect(spies.previewed).toEqual(["s-1"]);
  });

  it("asks about the period's conversations and announces the answer with its steps", async () => {
    vi.useFakeTimers({ toFake: ["Date"], now: new Date(2026, 9, 2, 12) });
    renderPanel();
    openAnalysis();
    ask("Vad frågar folk om?");

    const log = await screen.findByRole("log", { name: "Konversation" });
    expect(await within(log).findByText(/De flesta frågar om parkering/)).toBeTruthy();
    await waitFor(() => expect(spies.announce).toHaveBeenCalledWith("Svaret är klart"));
    expect(questions()).toEqual([
      {
        method: "POST",
        url: `${CHAT}/`,
        body: {
          assistant_id: "assistant-1",
          question: "Vad frågar folk om?",
          timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
          stream: true,
          selected_range: { start: "2026-09-02", end: "2026-10-02" }
        }
      }
    ]);
    // Named for what it does; the step it took is the analysis' own.
    expect(within(log).getByText("Insiktsanalys")).toBeTruthy();
    expect(
      within(log)
        .getByRole("button", { name: /^Aktivitet: 2 steg/ })
        .getAttribute("aria-expanded")
    ).toBe("false");
    // The chat API's own extras are not offered: no rating, no title asked for.
    expect(within(log).queryByRole("group", { name: "Betygsätt svaret" })).toBeNull();
    const { browserApi } = await import("@/lib/api/browser");
    expect(browserApi.POST).not.toHaveBeenCalled();
    // The answer is not inside a live region (that would read all of it).
    expect(
      within(log)
        .getByText(/De flesta frågar om parkering/)
        .closest("[aria-live]:not([aria-live='off'])")
    ).toBeNull();
    // The analysis can now be left for a new one.
    expect(screen.getByRole("button", { name: "Ny analys" })).toBeTruthy();
  });

  it("follows up in the same analysis with the period picked since", async () => {
    vi.useFakeTimers({ toFake: ["Date"], now: new Date(2026, 9, 2, 12) });
    renderPanel();
    openAnalysis();
    ask("Vad frågar folk om?");
    await screen.findByText(/De flesta frågar om parkering/);
    await waitFor(() => expect(screen.getByRole("textbox", { name: "Fråga om användningen" })));

    fireEvent.click(screen.getByRole("button", { name: /Period/ }));
    fireEvent.click(await screen.findByRole("button", { name: "Senaste 7 dagarna" }));
    spies.answer = analysisAnswer(
      "Mest om parkering vid entrén.",
      "33333333-3333-3333-3333-333333333333"
    );
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Skicka meddelande" })).toBeTruthy()
    );
    ask("Och förra veckan?");

    expect(await screen.findByText("Mest om parkering vid entrén.")).toBeTruthy();
    expect(questions()[1]).toEqual({
      method: "POST",
      url: `${CHAT}/${STREAMED}/`,
      body: {
        question: "Och förra veckan?",
        stream: true,
        selected_range: { start: "2026-09-25", end: "2026-10-02" }
      }
    });
  });

  it("opens a conversation the answer cites in the explore dialog", async () => {
    renderPanel();
    openAnalysis();
    ask("Vad frågar folk om?");
    const citation = await screen.findByRole("button", { name: "konversation 1a2b3c4d" });
    fireEvent.click(citation);

    const dialog = await screen.findByRole("dialog", { name: "Utforska konversationer" });
    expect(await within(dialog).findByText("Vid entrén.")).toBeTruthy();
    expect(spies.previewed).toEqual([CITED]);
  });

  it("shows the steps the analysis took and reads a step's result from the analysis", async () => {
    renderPanel();
    openAnalysis();
    ask("Vad frågar folk om?");
    const pill = await screen.findByRole("button", { name: /^Aktivitet: 2 steg/ });
    layOutConversation(1100);
    fireEvent.click(pill);

    const panel = await screen.findByRole("complementary", { name: "Aktivitet för svaret" });
    const step = within(panel).getAllByRole("button", { name: /Sökte frågor om ”parkering”/ });
    fireEvent.click(step.at(-1)!);
    expect(await within(panel).findByText("Frågor 1-2 av 2 om parkering")).toBeTruthy();
    expect(spies.requests.at(-1)).toMatchObject({
      method: "GET",
      url: `${CHAT}/${STREAMED}/tool-calls/call-1/result/`
    });
  });

  it("lists earlier analyses and opens one to continue it", async () => {
    spies.analyses = [
      { id: SAVED, name: "Vad frågar folk om?", created_at: "2026-10-01T10:00:00Z" }
    ];
    renderPanel();
    openAnalysis();
    const history = await screen.findByRole("region", { name: "Tidigare analyser" });
    expect(spies.requests[0]).toMatchObject({
      method: "GET",
      url: `${CHAT}/?assistant_id=assistant-1&limit=20`
    });

    fireEvent.click(within(history).getByRole("button", { name: /^Vad frågar folk om\?/ }));
    const log = await screen.findByRole("log", { name: "Konversation" });
    expect(within(log).getByText("Mest om parkering.")).toBeTruthy();
    expect(spies.requests.at(-1)).toMatchObject({ method: "GET", url: `${CHAT}/${SAVED}/` });

    ask("Och igår?");
    await waitFor(() =>
      expect(questions()[0]).toMatchObject({
        url: `${CHAT}/${SAVED}/`,
        body: { question: "Och igår?" }
      })
    );
  });

  it("deletes an earlier analysis after asking", async () => {
    spies.analyses = [
      { id: SAVED, name: "Vad frågar folk om?", created_at: "2026-10-01T10:00:00Z" }
    ];
    renderPanel();
    openAnalysis();
    const history = await screen.findByRole("region", { name: "Tidigare analyser" });
    const remove = within(history).getByRole("button", {
      name: "Ta bort analysen ”Vad frågar folk om?”"
    });
    // Pressed as a browser does it: the button takes the focus the panel had.
    act(() => remove.focus());
    fireEvent.click(remove);
    const confirm = await screen.findByRole("alertdialog", { name: "Ta bort analysen?" });
    spies.analyses = [];
    fireEvent.click(within(confirm).getByRole("button", { name: "Ta bort" }));

    await waitFor(() => expect(spies.announce).toHaveBeenCalledWith("Analysen är borttagen"));
    expect(spies.requests).toContainEqual({
      method: "DELETE",
      url: `${CHAT}/${SAVED}/`,
      body: undefined
    });
    // The row is gone; the list says it is empty, and its heading has the focus.
    expect(await within(history).findByText("Inga tidigare analyser.")).toBeTruthy();
    await waitFor(() =>
      expect(document.activeElement).toBe(
        within(history).getByRole("heading", { name: "Tidigare analyser" })
      )
    );
  });

  it("shows more earlier analyses and focuses the first one it added", async () => {
    spies.analyses = [{ id: SAVED, name: "Senaste analysen", created_at: "2026-10-01T10:00:00Z" }];
    spies.nextPage = [{ id: GONE, name: "Äldre analys", created_at: "2026-09-01T10:00:00Z" }];
    renderPanel();
    openAnalysis();
    const history = await screen.findByRole("region", { name: "Tidigare analyser" });
    fireEvent.click(within(history).getByRole("button", { name: "Visa fler analyser" }));

    const older = await within(history).findByRole("button", { name: /^Äldre analys/ });
    await waitFor(() => expect(document.activeElement).toBe(older));
    expect(spies.requests.at(-1)?.url).toBe(
      `${CHAT}/?assistant_id=assistant-1&limit=20&cursor=2026-09-01T00%3A00%3A00Z`
    );
  });

  it("says an analysis was removed with its conversations when it is opened, and starts a new one", async () => {
    spies.analyses = [{ id: GONE, name: "Gamla frågor", created_at: "2026-10-01T10:00:00Z" }];
    spies.removed.add(GONE);
    renderPanel();
    openAnalysis();
    const history = await screen.findByRole("region", { name: "Tidigare analyser" });
    fireEvent.click(within(history).getByRole("button", { name: /^Gamla frågor/ }));

    expect(await screen.findByText("Analysen har tagits bort")).toBeTruthy();
    expect(
      screen.getByText(
        "Den byggde på konversationer som har tagits bort, och då tas analysen bort med dem. Starta en ny analys om du vill fråga igen."
      )
    ).toBeTruthy();
    expect(screen.queryByRole("log")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Starta en ny analys" }));
    expect(await screen.findByRole("textbox", { name: "Fråga om användningen" })).toBeTruthy();
    expect(screen.queryByText("Analysen har tagits bort")).toBeNull();
  });

  it("says so when a follow-up is refused because the analysis was removed", async () => {
    spies.analyses = [
      { id: SAVED, name: "Vad frågar folk om?", created_at: "2026-10-01T10:00:00Z" }
    ];
    renderPanel();
    openAnalysis();
    const history = await screen.findByRole("region", { name: "Tidigare analyser" });
    fireEvent.click(within(history).getByRole("button", { name: /^Vad frågar folk om\?/ }));
    await screen.findByText("Mest om parkering.");

    spies.removed.add(SAVED);
    spies.announce.mockClear();
    ask("Och igår?");

    expect(await screen.findByText("Analysen har tagits bort")).toBeTruthy();
    // The turns it held are gone with it; the banner says why (an alert), no failure is told besides.
    expect(screen.queryByText("Mest om parkering.")).toBeNull();
    expect(screen.getByRole("alert")).toBeTruthy();
    expect(spies.announce.mock.calls).toEqual([["Assistenten skriver ett svar"]]);
    await waitFor(() =>
      expect(document.activeElement).toBe(
        screen.getByRole("button", { name: "Starta en ny analys" })
      )
    );
  });

  it("has no axe violations, before and after a question", async () => {
    spies.analyses = [
      { id: SAVED, name: "Vad frågar folk om?", created_at: "2026-10-01T10:00:00Z" }
    ];
    const { container } = renderPanel();
    await screen.findByText("Bra svar enligt betygen");
    await expectNoAxeViolations(container);

    openAnalysis();
    await screen.findByRole("region", { name: "Tidigare analyser" });
    await expectNoAxeViolations(container);

    ask("Vad frågar folk om?");
    await screen.findByRole("button", { name: "konversation 1a2b3c4d" });
    await expectNoAxeViolations(container);
  });

  it("opens the analysis beside the overview and closes it without losing the analysis", async () => {
    renderPanel();
    await screen.findByText("Bra svar enligt betygen");
    // Nothing of the analysis is loaded before it is asked for.
    expect(screen.queryByRole("complementary", { name: "Insiktsanalys" })).toBeNull();
    expect(spies.requests).toEqual([]);

    const panel = openAnalysis();
    // Beside the overview, with a handle to resize it; focus moves into it.
    expect(screen.getByRole("separator", { name: "Ändra analysens bredd" })).toBeTruthy();
    expect(panel.closest("[inert]")).toBeNull();
    await waitFor(() => expect(document.activeElement).toBe(panel));
    expect(within(panel).getByRole("heading", { name: "Insiktsanalys", level: 2 })).toBeTruthy();

    ask("Vad frågar folk om?");
    expect(await within(panel).findByText(/De flesta frågar om parkering/)).toBeTruthy();
    fireEvent.change(screen.getByRole("textbox", { name: "Fråga om användningen" }), {
      target: { value: "Och igår?" }
    });

    // Closing hands focus back to "Fråga analysen".
    fireEvent.click(within(panel).getByRole("button", { name: "Stäng analysen" }));
    expect(screen.queryByRole("complementary", { name: "Insiktsanalys" })).toBeNull();
    expect(screen.queryByRole("separator", { name: "Ändra analysens bredd" })).toBeNull();
    await waitFor(() => expect(document.activeElement).toBe(askButton()));

    // Opened again: the same analysis, its answer and the unsent question, nothing asked again.
    const reopened = openAnalysis();
    expect(within(reopened).getByText(/De flesta frågar om parkering/)).toBeTruthy();
    expect(
      (screen.getByRole("textbox", { name: "Fråga om användningen" }) as HTMLTextAreaElement).value
    ).toBe("Och igår?");
    expect(questions()).toHaveLength(1);
  });

  it("covers the view where the overview would keep less than 480 px beside it", async () => {
    renderPanel({ width: 700 });
    await screen.findByText("Bra svar enligt betygen");
    const panel = openAnalysis();

    // No handle: the panel lies over the view, and what it covers is inert.
    expect(screen.queryByRole("separator", { name: "Ändra analysens bredd" })).toBeNull();
    expect(askButton().closest("[inert]")).not.toBeNull();
    expect(panel.closest("[inert]")).toBeNull();
    await waitFor(() => expect(document.activeElement).toBe(panel));

    fireEvent.click(within(panel).getByRole("button", { name: "Stäng analysen" }));
    expect(askButton().closest("[inert]")).toBeNull();
    await waitFor(() => expect(document.activeElement).toBe(askButton()));
  });

  it("lays nothing of the analysis over the page while the tab is hidden", async () => {
    const view = renderPanel();
    openAnalysis();
    ask("Vad frågar folk om?");
    // Without room beside the answer in the panel, its steps open in a sheet.
    fireEvent.click(await screen.findByRole("button", { name: /^Aktivitet: 2 steg/ }));
    expect(await screen.findByRole("dialog", { name: "Aktivitet för svaret" })).toBeTruthy();

    // Chatt is shown: the tab stays mounted behind it, its sheet does not stay over it.
    view.rerender(
      <div className="flex h-[700px] flex-col">
        <InsightsPanel partner={partner} hidden />
      </div>
    );
    expect(screen.queryByRole("dialog", { name: "Aktivitet för svaret" })).toBeNull();
  });

  it("leaves a pasted file alone: the analysis takes no attachments", async () => {
    renderPanel();
    openAnalysis();
    const field = await screen.findByRole("textbox", { name: "Fråga om användningen" });
    const file = new File(["png"], "skärmbild.png", { type: "image/png" });
    fireEvent.paste(field, {
      clipboardData: {
        items: [{ kind: "file", getAsFile: () => file }],
        files: [file],
        getData: () => ""
      }
    });
    // Before, it said "at most 0 files".
    expect(spies.toastError).not.toHaveBeenCalled();
  });

  it("lists what to improve, worded by signal, with the actions that fit each", async () => {
    spies.findings = FINDINGS;
    renderPanel({ editHref: EDITOR });
    const card = await screen.findByRole("region", { name: "Det här kan du förbättra" });
    const items = await within(card).findAllByRole("listitem");
    expect(items.map((item) => item.textContent)).toEqual([
      expect.stringMatching(
        /^Många frågor får inget stöd i kunskapen5 av 20 svar som sökte i kunskapen fick ingen användbar träff\.Visa frågornaÖppna kunskapen$/
      ),
      expect.stringMatching(
        /^2 kunskapskällor används aldrigTaxa 2023 och Äldre riktlinjer har inte citerats i något svar under perioden\.Öppna kunskapen$/
      ),
      expect.stringMatching(
        /^Dåliga betyg med kommentar1 av 11 betyg är dåligt och har en kommentar\.Läs kommentarerna$/
      ),
      expect.stringMatching(
        /^Webbsökning misslyckas ofta6 av 10 anrop misslyckades\.Redigera assistenten$/
      )
    ]);
    // The knowledge and the editor open on their sections, for a user who may edit.
    expect(
      within(items[0]!).getByRole("link", { name: "Öppna kunskapen" }).getAttribute("href")
    ).toBe(`${EDITOR}?section=knowledge#knowledge`);
    expect(
      within(items[3]!).getByRole("link", { name: "Redigera assistenten" }).getAttribute("href")
    ).toBe(`${EDITOR}?section=capabilities#capabilities`);
  });

  it("says calmly that there is nothing to improve, and leaves the editor out for a viewer", async () => {
    renderPanel();
    const card = await screen.findByRole("region", { name: "Det här kan du förbättra" });
    expect(
      await within(card).findByText("Inga tydliga mönster att åtgärda i perioden.")
    ).toBeTruthy();
    spies.findings = FINDINGS;
    cleanup();
    renderPanel();
    await screen.findByRole("button", { name: "Visa frågorna" });
    expect(screen.queryByRole("link", { name: "Öppna kunskapen" })).toBeNull();
    expect(screen.queryByRole("link", { name: "Redigera assistenten" })).toBeNull();
  });

  it("opens a finding in place of the overview, pages its examples and goes back", async () => {
    spies.findings = FINDINGS;
    spies.cases = [
      miss("q-1", "no_results", -1),
      miss("q-2", "weak_score", null),
      miss("q-3", "uncited", 1)
    ];
    renderPanel({ editHref: EDITOR });
    fireEvent.click(await screen.findByRole("button", { name: "Visa frågorna" }));

    // The finding's title takes the focus; the overview is out of the way, the filters stay.
    const heading = await screen.findByRole("heading", {
      name: "Många frågor får inget stöd i kunskapen",
      level: 2
    });
    await waitFor(() => expect(document.activeElement).toBe(heading));
    expect(screen.queryByRole("region", { name: "Nyckeltal" })).toBeNull();
    expect(screen.getByRole("radio", { name: "Widget" })).toBeTruthy();
    expect(screen.getByText(/, alla källor$/)).toBeTruthy();
    const evidence = screen.getByRole("region", { name: "Underlag" });
    expect(evidence.textContent).toMatch(
      /Svar som sökte i kunskapen20.*Utan användbar träff.*5.*Andel.*25\s%/
    );
    expect(
      spies.queries["/api/v1/analysis/conversation-insights/findings/{kind}/"]?.[0]
    ).toMatchObject({ assistant_id: "assistant-1", limit: 20 });

    // Two cases a page: "Visa fler" asks for the next one and focuses its first row.
    const table = await screen.findByRole("table", { name: "Exempel" });
    const cells = (row: HTMLElement) =>
      within(row)
        .getAllByRole("cell")
        .map((cell) => cell.textContent);
    expect(within(table).getAllByRole("row").slice(1).map(cells)).toEqual([
      ["Vad kostar q-1?", "Widget", "Ingen", "Dåligt", "Läs"],
      ["Vad kostar q-2?", "Widget", "Svag", "Inget betyg", "Läs"]
    ]);
    expect(screen.getByText("Visar 2 av 3")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Visa fler" }));
    await waitFor(() => expect(within(table).getAllByRole("row")).toHaveLength(4));
    expect(
      spies.queries["/api/v1/analysis/conversation-insights/findings/{kind}/"]?.at(-1)
    ).toMatchObject({ cursor: "2" });
    // Every case is in: the misses are split by reason.
    expect(evidence.textContent).toMatch(/1 utan resultat, 1 utan citat och 1 med svag träff/);

    // "Läs" opens the case's conversation read-only.
    const read = within(table).getAllByRole("button", { name: "Läs konversationen" });
    await waitFor(() => expect(document.activeElement).toBe(read[2]));
    fireEvent.click(read[0]!);
    const dialog = await screen.findByRole("dialog", { name: "Utforska konversationer" });
    await waitFor(() => expect(spies.previewed).toEqual(["s-q-1"]));
    fireEvent.click(within(dialog).getByRole("button", { name: "Stäng" }));
    await waitFor(() =>
      expect(screen.queryByRole("dialog", { name: "Utforska konversationer" })).toBeNull()
    );

    // Next steps: the knowledge, for a user who may edit.
    const next = screen.getByRole("region", { name: "Nästa steg" });
    expect(within(next).getByRole("link", { name: "Öppna kunskapen" }).getAttribute("href")).toBe(
      `${EDITOR}?section=knowledge#knowledge`
    );

    // The way back shows the overview and returns focus to the finding's button.
    fireEvent.click(screen.getByRole("button", { name: "Tillbaka till insikterna" }));
    expect(await screen.findByRole("region", { name: "Nyckeltal" })).toBeTruthy();
    await waitFor(() =>
      expect(document.activeElement).toBe(screen.getByRole("button", { name: "Visa frågorna" }))
    );
  });

  it("puts the finding's question in the analysis' composer without sending it", async () => {
    spies.findings = FINDINGS;
    renderPanel();
    fireEvent.click(await screen.findByRole("button", { name: "Visa frågorna" }));
    await screen.findByRole("heading", { name: "Många frågor får inget stöd i kunskapen" });
    fireEvent.click(askButton());

    const field = await screen.findByRole("textbox", { name: "Fråga om användningen" });
    await waitFor(() =>
      expect((field as HTMLTextAreaElement).value).toBe(
        "Vad frågar användarna om som kunskapen inte täcker?"
      )
    );
    expect(questions()).toEqual([]);
  });

  it("puts the finding's question in the composer once under StrictMode, however often it is asked", async () => {
    const missed = "Vad frågar användarna om som kunskapen inte täcker?";
    const unanswered = "Vilka frågor kan assistenten inte svara på, och varför?";
    spies.findings = [
      ...FINDINGS,
      { kind: "unanswered", affected: 4, base: 30, examples: [], sources: null, tool: null }
    ];
    renderPanel({ strict: true });
    const value = () =>
      (screen.getByRole("textbox", { name: "Fråga om användningen" }) as HTMLTextAreaElement).value;
    fireEvent.click(await screen.findByRole("button", { name: "Visa frågorna" }));
    fireEvent.click(await screen.findByRole("button", { name: "Fråga analysen om det här" }));
    await waitFor(() => expect(value()).toBe(missed));

    // Closed and opened again from the same finding: the question is there once, nothing offered.
    fireEvent.click(screen.getByRole("button", { name: "Stäng analysen" }));
    fireEvent.click(screen.getByRole("button", { name: "Fråga analysen om det här" }));
    await screen.findByRole("complementary", { name: "Insiktsanalys" });
    expect(value()).toBe(missed);
    expect(screen.queryByRole("button", { name: "Använd förslaget" })).toBeNull();

    // The finding left and opened again: its question already ends the draft.
    fireEvent.click(screen.getByRole("button", { name: "Tillbaka till insikterna" }));
    fireEvent.click(await screen.findByRole("button", { name: "Visa frågorna" }));
    fireEvent.click(await screen.findByRole("button", { name: "Fråga analysen om det här" }));
    expect(value()).toBe(missed);
    expect(screen.queryByRole("button", { name: "Använd förslaget" })).toBeNull();

    // Another finding's question does not replace the draft: it is offered, and added once.
    fireEvent.click(screen.getByRole("button", { name: "Tillbaka till insikterna" }));
    fireEvent.click(await screen.findByRole("button", { name: "Visa svaren" }));
    fireEvent.click(await screen.findByRole("button", { name: "Fråga analysen om det här" }));
    const use = await screen.findByRole("button", { name: "Använd förslaget" });
    expect(value()).toBe(missed);
    fireEvent.click(use);
    await waitFor(() => expect(value()).toBe(`${missed}\n${unanswered}`));
    expect(questions()).toEqual([]);
  });

  it("offers the finding's question beside a typed one instead of replacing it", async () => {
    spies.findings = FINDINGS;
    renderPanel();
    const panel = openAnalysis();
    const field = await within(panel).findByRole("textbox", { name: "Fråga om användningen" });
    fireEvent.change(field, { target: { value: "Min egen fråga" } });

    fireEvent.click(await screen.findByRole("button", { name: "Visa frågorna" }));
    fireEvent.click(await screen.findByRole("button", { name: "Fråga analysen om det här" }));
    expect((field as HTMLTextAreaElement).value).toBe("Min egen fråga");
    expect(
      await within(panel).findByText(
        "Förslag: ”Vad frågar användarna om som kunskapen inte täcker?”"
      )
    ).toBeTruthy();

    fireEvent.click(within(panel).getByRole("button", { name: "Använd förslaget" }));
    await waitFor(() =>
      expect((field as HTMLTextAreaElement).value).toBe(
        "Min egen fråga\nVad frågar användarna om som kunskapen inte täcker?"
      )
    );
    expect(within(panel).queryByRole("button", { name: "Använd förslaget" })).toBeNull();
    expect(questions()).toEqual([]);
  });

  it("shows the bad ratings' comments in the feedback inbox", async () => {
    spies.findings = FINDINGS;
    renderPanel();
    fireEvent.click(await screen.findByRole("button", { name: "Läs kommentarerna" }));
    const inbox = screen.getByRole("region", { name: "Återkoppling från användarna" });
    expect(document.activeElement).toBe(
      within(inbox).getByRole("heading", { name: "Återkoppling från användarna" })
    );
    expect(
      within(inbox).getByRole("radio", { name: "Dåliga med kommentar (1)", checked: true })
    ).toBeTruthy();
    await waitFor(() =>
      expect(queriesOf("feedback").at(-1)).toMatchObject({ value: -1, has_comment: true })
    );
  });

  it("shows the commonest questions, the knowledge in use and the tools", async () => {
    spies.knowledge = {
      sources: [
        { kind: "collection", id: "k-1", name: "Bygglovsguiden", attached: true, answers: 14 },
        { kind: "website", id: "k-2", name: "sundsvall.se", attached: false, answers: 7 }
      ],
      unused: [{ kind: "collection", id: "k-3", name: "Taxa 2023", attached: true, answers: 0 }]
    };
    spies.tools = [
      {
        kind: "tool",
        purpose: null,
        server_name: "Ärendesystemet",
        tool_name: "find_case",
        title: "Hitta ärende",
        calls: 9,
        failed: 2,
        denied: 1
      }
    ];
    renderPanel();
    const common = await screen.findByRole("table", { name: "Vanligaste frågorna" });
    const [row] = within(common).getAllByRole("row").slice(1);
    // Answered 75 %, ratings in words, and no knowledge share without a search.
    expect(
      within(row!)
        .getAllByRole("cell")
        .map((cell) => cell.textContent)
    ).toEqual([
      "Var parkerar jag?",
      "12",
      "75\u00a0%",
      "2 bra, 1 dålig",
      "–Ingen sökning i kunskapen"
    ]);
    fireEvent.click(within(row!).getByRole("button", { name: "Var parkerar jag?" }));
    await screen.findByRole("dialog", { name: "Utforska konversationer" });
    await waitFor(() => expect(spies.previewed).toEqual(["s-1"]));

    const knowledge = screen.getByRole("region", { name: "Kunskapen som används" });
    expect(within(knowledge).getAllByRole("listitem")[1]!.textContent).toMatch(
      /^sundsvall\.seWebbplatsinte längre kopplad7 svar$/
    );
    expect(
      within(knowledge).getByRole("list", { name: "Citeras aldrig under perioden" }).textContent
    ).toBe("Taxa 2023Samling");
    const tools = screen.getByRole("region", { name: "Verktyg" });
    expect(within(tools).getByRole("listitem").textContent).toBe(
      "Hitta ärendeÄrendesystemet · 2 misslyckades · 1 nekades9 anrop"
    );
  });

  it("leaves out the knowledge and tools of a target without any", async () => {
    renderPanel();
    await screen.findByRole("table", { name: "Vanligaste frågorna" });
    await waitFor(() => expect(queriesOf("knowledge").length).toBeGreaterThan(0));
    await waitFor(() =>
      expect(screen.queryByRole("region", { name: "Kunskapen som används" })).toBeNull()
    );
    expect(screen.queryByRole("region", { name: "Verktyg" })).toBeNull();
  });
});

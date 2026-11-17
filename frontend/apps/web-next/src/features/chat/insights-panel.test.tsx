// @vitest-environment jsdom
import { act, cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
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

const spies = vi.hoisted(() => ({
  announce: vi.fn(),
  /** The query of every statistics request. */
  statsQueries: [] as Record<string, unknown>[],
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
  answer: ""
}));

/** The options of a typed request, as far as these fakes read them. */
type TypedRequestInit = {
  params?: { query?: Record<string, unknown>; path?: Record<string, string> };
};

vi.mock("@/lib/api/browser", () => ({
  browserApi: {
    GET: vi.fn(async (path: string, init?: TypedRequestInit) => {
      if (path.startsWith(CHAT)) return typedInsightsChat("GET", path, init);
      if (path === "/api/v1/analysis/conversation-insights/sessions/") {
        return {
          data: {
            items: [{ id: "s-1", name: "Direktupphandling" }],
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
            messages: [{ id: "m-1", question: "Var parkerar jag?", answer: "Vid entrén." }]
          },
          response: new Response()
        };
      }
      spies.statsQueries.push(init?.params?.query ?? {});
      return {
        data: {
          total_conversations: 12,
          total_questions: 30,
          feedback: { positive: 7, negative: 2 }
        },
        response: new Response()
      };
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

/**
 * An answer in the shared stream contract's tool-call fixture, made the
 * analysis': a search of the questions, and an answer that cites a conversation.
 */
function analysisAnswer(text: string): string {
  const fixture = loadFixtures().find((item) => item.name === "tool-call-with-output")!;
  const events = fixture.events.map((event) => {
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
  spies.statsQueries.length = 0;
  spies.previewed.length = 0;
  spies.requests.length = 0;
  spies.analyses = [];
  spies.nextPage = null;
  spies.removed.clear();
});

const partner: ChatPartner & { type: "assistant" } = {
  type: "assistant",
  id: "assistant-1",
  name: "Upphandlingsassistenten",
  insightEnabled: true
};

function renderPanel() {
  return renderInApp(
    <div className="flex h-[700px] flex-col">
      <InsightsPanel partner={partner} />
    </div>
  );
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

/** Lays out the region around the conversation, as a browser measures it. */
function layOutConversation(width: number) {
  const log = screen.getByRole("log");
  const regions = observedElements().filter((element) => element.contains(log));
  const region = regions.find((element) => regions.every((other) => element.contains(other)));
  if (region) act(() => reportResize(region, { width, height: 700 }));
}

describe("InsightsPanel", () => {
  it("covers the last 30 days and refetches for a preset period", async () => {
    vi.useFakeTimers({ toFake: ["Date"], now: new Date(2026, 9, 2, 12) });
    renderPanel();
    await screen.findByText("Bra svar");
    expect(spies.statsQueries[0]).toMatchObject({
      start_time: new Date("2026-09-02T00:00:00").toISOString(),
      end_time: new Date("2026-10-03T00:00:00").toISOString(),
      assistant_id: "assistant-1"
    });

    fireEvent.click(screen.getByRole("button", { name: /Period/ }));
    fireEvent.click(await screen.findByRole("button", { name: "Senaste 7 dagarna" }));
    await waitFor(() =>
      expect(spies.statsQueries.at(-1)).toMatchObject({
        start_time: new Date("2026-09-25T00:00:00").toISOString(),
        end_time: new Date("2026-10-03T00:00:00").toISOString()
      })
    );
  });

  it("shows the period's counts and opens its conversations to explore", async () => {
    renderPanel();
    // Scoped to the statistics: the period picker's calendar also shows numbers.
    const stats = (await screen.findByText("Bra svar")).closest("dl")!;
    expect(within(stats).getByText("12")).toBeTruthy();
    expect(within(stats).getByText("30")).toBeTruthy();
    const good = within(stats).getByText("Bra svar").closest("div")!;
    expect(good.querySelector("dd")?.textContent).toBe("7");
    const bad = within(stats).getByText("Dåliga svar").closest("div")!;
    expect(bad.querySelector("dd")?.textContent).toBe("2");

    fireEvent.click(screen.getByRole("button", { name: "Utforska konversationer" }));
    const dialog = await screen.findByRole("dialog", { name: "Utforska konversationer" });
    expect(await within(dialog).findByRole("button", { name: /Direktupphandling/ })).toBeTruthy();
  });

  it("asks about the period's conversations and announces the answer with its steps", async () => {
    vi.useFakeTimers({ toFake: ["Date"], now: new Date(2026, 9, 2, 12) });
    renderPanel();
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
    ask("Vad frågar folk om?");
    await screen.findByText(/De flesta frågar om parkering/);
    await waitFor(() => expect(screen.getByRole("textbox", { name: "Fråga om användningen" })));

    fireEvent.click(screen.getByRole("button", { name: /Period/ }));
    fireEvent.click(await screen.findByRole("button", { name: "Senaste 7 dagarna" }));
    spies.answer = analysisAnswer("Mest om parkering vid entrén.");
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
    ask("Vad frågar folk om?");
    const citation = await screen.findByRole("button", { name: "konversation 1a2b3c4d" });
    fireEvent.click(citation);

    const dialog = await screen.findByRole("dialog", { name: "Utforska konversationer" });
    expect(await within(dialog).findByText("Vid entrén.")).toBeTruthy();
    expect(spies.previewed).toEqual([CITED]);
  });

  it("shows the steps the analysis took and reads a step's result from the analysis", async () => {
    renderPanel();
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
    const history = await screen.findByRole("region", { name: "Tidigare analyser" });
    fireEvent.click(
      within(history).getByRole("button", { name: "Ta bort analysen ”Vad frågar folk om?”" })
    );
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
    await screen.findByRole("region", { name: "Tidigare analyser" });
    await screen.findByText("Bra svar");
    await expectNoAxeViolations(container);

    ask("Vad frågar folk om?");
    await screen.findByRole("button", { name: "konversation 1a2b3c4d" });
    await expectNoAxeViolations(container);
  });
});

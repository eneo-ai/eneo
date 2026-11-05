// @vitest-environment jsdom
import { act, cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp, testQueryClient } from "@/test/render";

vi.mock("@/lib/navigation", () => import("@/test/navigation"));

type QuestionQuery = {
  from_date?: string;
  to_date?: string;
  include_followups?: boolean;
  limit?: number;
  q?: string;
};

const QUESTIONS = [
  {
    id: "q1",
    question: "Vilka regler gäller för direktupphandling?",
    created_at: "2026-09-20T08:00:00Z",
    session_id: "session-1"
  },
  {
    id: "q2",
    question: "Hur lång är avtalstiden?",
    created_at: "2026-09-21T09:30:00Z",
    session_id: "session-2"
  }
];

const spies = vi.hoisted(() => ({
  announce: vi.fn(),
  questionQueries: [] as QuestionQuery[],
  asked: [] as unknown[],
  log: null as unknown,
  logFails: false,
  nextStream: null as ReadableStream<Uint8Array> | null,
  signal: null as AbortSignal | null
}));

vi.mock("@/lib/api/browser", () => ({
  browserApi: {
    GET: vi.fn(async (path: string, init?: { params?: { query?: QuestionQuery } }) => {
      if (path === "/api/v1/logging/{message_id}/")
        return spies.logFails
          ? {
              error: { message: "Question was not logged." },
              response: new Response(null, { status: 400 })
            }
          : { data: spies.log, response: new Response("{}") };
      if (path === "/api/v1/analysis/assistants/{assistant_id}/feedback/")
        return { data: { positive: 0, negative: 0 }, response: new Response("{}") };
      if (path !== "/api/v1/analysis/assistants/{assistant_id}/questions/") {
        throw new Error(`Unexpected GET ${path}`);
      }
      const query = init?.params?.query ?? {};
      spies.questionQueries.push(query);
      const matching = QUESTIONS.filter(
        (item) => !query.q || item.question.toLowerCase().includes(query.q.toLowerCase())
      );
      return {
        data: {
          items: matching.slice(0, query.limit ?? 100),
          total_count: matching.length,
          next_cursor: null
        },
        response: new Response("{}")
      };
    }),
    POST: vi.fn(async (_path: string, init: { signal?: AbortSignal }) => {
      spies.asked.push(init);
      spies.signal = init.signal ?? null;
      const data =
        spies.nextStream ??
        new ReadableStream<Uint8Array>({
          start(controller) {
            controller.enqueue(
              new TextEncoder().encode('data: {"answer":"De flesta frågor gäller LOU."}\n\n')
            );
            controller.close();
          }
        });
      spies.nextStream = null;
      return { data, response: new Response("{}") };
    })
  }
}));
vi.mock("@astryxdesign/core/hooks", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@astryxdesign/core/hooks")>()),
  useAnnounce: () => spies.announce
}));

import { AssistantInsightsPage } from "./assistant-insights-page";

afterEach(() => {
  cleanup();
  spies.announce.mockReset();
  spies.questionQueries.length = 0;
  spies.asked.length = 0;
  spies.log = null;
  spies.logFails = false;
  spies.nextStream = null;
  spies.signal = null;
});

function renderPage(route?: string) {
  const queryClient = testQueryClient();
  queryClient.setQueryData(["assistants", "assistant-1"], {
    id: "assistant-1",
    name: "Upphandlingsassistenten"
  });
  return renderInApp(<AssistantInsightsPage assistantId="assistant-1" />, { queryClient, route });
}

describe("AssistantInsightsPage", () => {
  it("opens the complete logged record as text and copies it", async () => {
    const full = {
      ...QUESTIONS[0],
      answer: "Logged answer",
      logging_details: { prompt: "<img src=x onerror=alert(1)>" }
    };
    spies.log = full;
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText } });
    renderPage();
    fireEvent.click(screen.getByRole("tab", { name: "Frågehistorik" }));
    const trigger = await screen.findByRole("button", { name: QUESTIONS[0]!.question });
    trigger.focus();
    fireEvent.click(trigger);
    const dialog = await screen.findByRole("dialog", { name: "Frågedetaljer" });
    expect(await within(dialog).findByText("session-1")).toBeTruthy();
    const raw = await within(dialog).findByRole("region", { name: "Loggad information som JSON" });
    expect(raw.textContent).toBe(JSON.stringify(full, null, 2));
    expect(raw.querySelector("img")).toBeNull();
    fireEvent.click(within(dialog).getByRole("button", { name: "Kopiera" }));
    await waitFor(() => expect(writeText).toHaveBeenCalledWith(JSON.stringify(full, null, 2)));
    await expectNoAxeViolations(document.body);
    fireEvent.click(within(dialog).getByRole("button", { name: "Klar" }));
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Frågedetaljer" })).toBeNull());
    expect(document.activeElement).toBe(trigger);
  });

  it("shows a logging refusal and retries without passing a row off as a full log", async () => {
    spies.logFails = true;
    renderPage("/admin/insights/assistant/assistant-1?tab=questions");
    fireEvent.click(await screen.findByRole("button", { name: QUESTIONS[0]!.question }));
    const dialog = screen.getByRole("dialog", { name: "Frågedetaljer" });
    expect(await within(dialog).findByText("Question was not logged.")).toBeTruthy();
    expect(within(dialog).queryByRole("button", { name: "Kopiera" })).toBeNull();
    expect(
      within(dialog).queryByRole("region", { name: "Loggad information som JSON" })
    ).toBeNull();
    spies.logFails = false;
    spies.log = { ...QUESTIONS[0], logging_details: { prompt: "fixture" } };
    fireEvent.click(within(dialog).getByRole("button", { name: "Försök igen" }));
    expect(
      await within(dialog).findByRole("region", { name: "Loggad information som JSON" })
    ).toBeTruthy();
  });

  it("moves between the analysis and the question history as keyboard tabs", async () => {
    const { container } = renderPage();

    const tablist = screen.getByRole("tablist", { name: "Analys och frågehistorik" });
    const analysis = within(tablist).getByRole("tab", { name: "Analysera" });
    const history = within(tablist).getByRole("tab", { name: "Frågehistorik" });
    expect(analysis.getAttribute("aria-selected")).toBe("true");
    expect(analysis.tabIndex).toBe(0);
    expect(history.tabIndex).toBe(-1);

    const analysisPanel = screen.getByRole("tabpanel", { name: "Analysera" });
    expect(analysis.getAttribute("aria-controls")).toBe(analysisPanel.id);
    const question = within(analysisPanel).getByRole("textbox", { name: /Fråga om insikter/ });
    fireEvent.change(question, { target: { value: "Vad frågar folk mest om?" } });
    // Only the question count loads until the history is opened.
    await waitFor(() => expect(spies.questionQueries).toHaveLength(1));
    expect(spies.questionQueries[0]?.limit).toBe(1);
    await expectNoAxeViolations(container);

    analysis.focus();
    fireEvent.keyDown(analysis, { key: "ArrowRight" });
    expect(document.activeElement).toBe(history);
    fireEvent.click(history);

    expect(history.getAttribute("aria-selected")).toBe("true");
    const historyPanel = screen.getByRole("tabpanel", { name: "Frågehistorik" });
    expect(history.getAttribute("aria-controls")).toBe(historyPanel.id);
    const table = await within(historyPanel).findByRole("table", { name: "Frågehistorik" });
    expect(within(table).getByText("Hur lång är avtalstiden?")).toBeTruthy();
    // Every row links to its conversation; the link's name says which one by
    // the question's time, as the row's Skapad cell writes it.
    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows).toHaveLength(2);
    const sessions = rows.map((row) => {
      const time = within(row).getAllByRole("cell")[0]!.textContent!;
      expect(time).toMatch(/2026/);
      const link = within(row).getByRole("link", { name: `Session från ${time}` });
      expect(link.textContent).toBe("Session");
      return link.getAttribute("href");
    });
    expect(sessions.sort()).toEqual([
      "/dashboard/assistant-1/session-1",
      "/dashboard/assistant-1/session-2"
    ]);
    await expectNoAxeViolations(container);

    // Back to the analysis: the question typed there is still there.
    fireEvent.keyDown(history, { key: "ArrowLeft" });
    expect(document.activeElement).toBe(analysis);
    fireEvent.click(analysis);
    expect(
      (screen.getByRole("textbox", { name: /Fråga om insikter/ }) as HTMLTextAreaElement).value
    ).toBe("Vad frågar folk mest om?");
  });

  it("shows an empty question at the field on Enter, which takes focus", async () => {
    renderPage();
    const question = screen.getByRole("textbox", { name: /Fråga om insikter/ });
    const submit = screen.getByRole("button", { name: "Skicka din fråga" });
    // Never disabled: a disabled button says nothing about what is missing.
    expect((submit as HTMLButtonElement).disabled).toBe(false);

    fireEvent.keyDown(question, { key: "Enter" });

    expect(question.getAttribute("aria-invalid")).toBe("true");
    expect(screen.getAllByText("Detta fält är obligatoriskt").length).toBeGreaterThan(0);
    expect(document.activeElement).toBe(question);
    expect(spies.asked).toEqual([]);
  });

  it("asks with Enter and announces the answer when it is ready", async () => {
    renderPage();
    const question = screen.getByRole("textbox", { name: /Fråga om insikter/ });
    // The Enter hint is the field's description.
    expect(question.getAttribute("aria-describedby")).toBeTruthy();

    fireEvent.change(question, { target: { value: "Vad frågar folk mest om?" } });
    fireEvent.keyDown(question, { key: "Enter" });

    expect(await screen.findByText("De flesta frågor gäller LOU.")).toBeTruthy();
    expect(spies.asked[0]).toMatchObject({
      body: { question: "Vad frågar folk mest om?", stream: true }
    });
    expect(spies.announce).toHaveBeenCalledWith("Svaret är klart");
    // The answer itself is not read out.
    expect(spies.announce).not.toHaveBeenCalledWith("De flesta frågor gäller LOU.");
  });

  it("shows a failed question as an error and asks again from the question field", async () => {
    const { browserApi } = await import("@/lib/api/browser");
    vi.mocked(browserApi.POST).mockImplementationOnce(async () => ({
      error: { message: "Model unavailable" },
      response: new Response(null, { status: 503 })
    }));
    renderPage();
    const question = screen.getByRole("textbox", { name: /Fråga om insikter/ });
    fireEvent.change(question, { target: { value: "Vad frågar folk mest om?" } });
    fireEvent.keyDown(question, { key: "Enter" });

    const message = await screen.findByText("Model unavailable");
    const alert = message.closest<HTMLElement>('[role="alert"]')!;
    // No retry inside the error: it would unmount under focus while the
    // question runs. Asking again is the retry, and its control stays put.
    expect(within(alert).queryByRole("button", { name: /Försök igen/ })).toBeNull();

    fireEvent.keyDown(question, { key: "Enter" });
    expect(await screen.findByText("De flesta frågor gäller LOU.")).toBeTruthy();
  });

  it("announces how many questions a search found once its results are in", async () => {
    renderPage();
    fireEvent.click(screen.getByRole("tab", { name: "Frågehistorik" }));
    await screen.findByRole("table", { name: "Frågehistorik" });
    expect(spies.announce).not.toHaveBeenCalled();

    fireEvent.change(screen.getByRole("textbox", { name: "Sök" }), {
      target: { value: "avtal" }
    });

    await waitFor(() => expect(spies.announce).toHaveBeenCalledWith("Laddade 1/1 frågor"));
    const table = screen.getByRole("table", { name: "Frågehistorik" });
    expect(within(table).queryByText("Vilka regler gäller för direktupphandling?")).toBeNull();
  });

  it("loads URL filters as full local days and keeps changes in the URL", async () => {
    vi.stubEnv("TZ", "Europe/Stockholm");
    try {
      renderPage(
        "/admin/insights/assistant/assistant-1?from=2026-09-10&to=2026-09-30&followups=false&tab=questions"
      );
      expect(screen.getByRole("tab", { name: "Frågehistorik" }).getAttribute("aria-selected")).toBe(
        "true"
      );
      await waitFor(() =>
        expect(
          spies.questionQueries.some(
            (query) =>
              query.from_date === "2026-09-09T22:00:00.000Z" &&
              query.to_date === "2026-09-30T21:59:59.999999Z" &&
              query.include_followups === false
          )
        ).toBe(true)
      );
      fireEvent.click(screen.getByRole("switch", { name: "Inkludera uppföljningsfrågor" }));
      expect(new URLSearchParams(window.location.search).get("followups")).toBe("true");
      expect(new URLSearchParams(window.location.search).get("from")).toBe("2026-09-10");
    } finally {
      vi.unstubAllEnvs();
    }
  });

  it("shows partial answers immediately and stop keeps the partial result without announcing completion", async () => {
    let controller!: ReadableStreamDefaultController<Uint8Array>;
    const cancel = vi.fn();
    spies.nextStream = new ReadableStream({
      start(value) {
        controller = value;
      },
      cancel
    });
    renderPage();
    const field = screen.getByRole("textbox", { name: /Fråga om insikter/ });
    fireEvent.change(field, { target: { value: "Vad frågar folk?" } });
    fireEvent.keyDown(field, { key: "Enter" });
    act(() => controller.enqueue(new TextEncoder().encode('data: {"answer":"Delvis svar"}\n\n')));
    expect(await screen.findByText("Delvis svar")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Stoppa generering" }));
    expect(spies.signal!.aborted).toBe(true);
    act(() => controller.enqueue(new TextEncoder().encode('data: {"answer":" sent"}\n\n')));
    await waitFor(() => expect(cancel).toHaveBeenCalledOnce());
    expect(screen.getByText("Delvis svar")).toBeTruthy();
    expect(screen.queryByText("Delvis svar sent")).toBeNull();
    expect(spies.announce).toHaveBeenCalledWith("Svaret stoppades");
    expect(spies.announce).not.toHaveBeenCalledWith("Svaret är klart");
  });

  it("keeps partial analysis on a failed stream and never announces completion", async () => {
    let controller!: ReadableStreamDefaultController<Uint8Array>;
    spies.nextStream = new ReadableStream({
      start(value) {
        controller = value;
      }
    });
    renderPage();
    const field = screen.getByRole("textbox", { name: /Fråga om insikter/ });
    fireEvent.change(field, { target: { value: "Vad frågar folk?" } });
    fireEvent.keyDown(field, { key: "Enter" });
    act(() => controller.enqueue(new TextEncoder().encode('data: {"answer":"Delvis svar"}\n\n')));
    await screen.findByText("Delvis svar");
    act(() => controller.error(new Error("Stream interrupted")));
    const errorMessage = await screen.findByText("Något gick fel. Försök igen.");
    expect(errorMessage.closest('[role="alert"]')).not.toBeNull();
    expect(screen.queryByText("Stream interrupted")).toBeNull();
    expect(screen.getByText("Delvis svar")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Skicka din fråga" })).toBeTruthy();
    expect(spies.announce).toHaveBeenCalledWith("Något gick fel. Försök igen.");
    expect(spies.announce).not.toHaveBeenCalledWith("Svaret är klart");
  });

  it("aborts a changed analysis context, hides its old answer and ignores late parts", async () => {
    let controller!: ReadableStreamDefaultController<Uint8Array>;
    spies.nextStream = new ReadableStream({
      start(value) {
        controller = value;
      }
    });
    renderPage();
    const field = screen.getByRole("textbox", { name: /Fråga om insikter/ });
    fireEvent.change(field, { target: { value: "Vad frågar folk?" } });
    fireEvent.keyDown(field, { key: "Enter" });
    act(() => controller.enqueue(new TextEncoder().encode('data: {"answer":"Gammalt svar"}\n\n')));
    await screen.findByText("Gammalt svar");
    fireEvent.click(screen.getByRole("switch", { name: "Inkludera uppföljningsfrågor" }));
    expect(spies.signal!.aborted).toBe(true);
    expect(screen.queryByText("Gammalt svar")).toBeNull();
    act(() => {
      controller.enqueue(new TextEncoder().encode('data: {"answer":" sent"}\n\n'));
      controller.close();
    });
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Skicka din fråga" })).toBeTruthy()
    );
    fireEvent.click(screen.getByRole("switch", { name: "Inkludera uppföljningsfrågor" }));
    expect(screen.queryByText("Gammalt svar")).toBeNull();
    expect(spies.announce).not.toHaveBeenCalledWith("Svaret är klart");
    expect((field as HTMLTextAreaElement).value).toBe("Vad frågar folk?");
  });
  it("aborts its own request on unmount and never announces a late completion", async () => {
    let controller!: ReadableStreamDefaultController<Uint8Array>;
    const cancel = vi.fn();
    spies.nextStream = new ReadableStream({
      start(value) {
        controller = value;
      },
      cancel
    });
    const { unmount } = renderPage();
    const field = screen.getByRole("textbox", { name: /Fråga om insikter/ });
    fireEvent.change(field, { target: { value: "Vad frågar folk?" } });
    fireEvent.keyDown(field, { key: "Enter" });
    await waitFor(() => expect(spies.signal).not.toBeNull());
    unmount();
    expect(spies.signal!.aborted).toBe(true);
    act(() => controller.enqueue(new TextEncoder().encode('data: {"answer":"För sent"}\n\n')));
    await waitFor(() => expect(cancel).toHaveBeenCalledOnce());
    expect(spies.announce).not.toHaveBeenCalledWith("Svaret är klart");
  });
});

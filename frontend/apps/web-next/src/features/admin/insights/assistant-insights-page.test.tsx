// @vitest-environment jsdom
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp, testQueryClient } from "@/test/render";

type QuestionQuery = { from_date?: string; limit?: number; q?: string };

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
  asked: [] as unknown[]
}));

vi.mock("@/lib/api/browser", () => ({
  browserApi: {
    GET: vi.fn(async (path: string, init?: { params?: { query?: QuestionQuery } }) => {
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
    POST: vi.fn(async (_path: string, init: unknown) => {
      spies.asked.push(init);
      return { data: { answer: "De flesta frågor gäller LOU." }, response: new Response("{}") };
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
});

function renderPage() {
  const queryClient = testQueryClient();
  queryClient.setQueryData(["assistants", "assistant-1"], {
    id: "assistant-1",
    name: "Upphandlingsassistenten"
  });
  return renderInApp(<AssistantInsightsPage assistantId="assistant-1" />, { queryClient });
}

describe("AssistantInsightsPage", () => {
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
      body: { question: "Vad frågar folk mest om?", stream: false }
    });
    expect(spies.announce).toHaveBeenCalledWith("Svaret är klart");
    // The answer itself is not read out.
    expect(spies.announce).not.toHaveBeenCalledWith("De flesta frågor gäller LOU.");
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

  it("filters from the start of the chosen day and shows that day", async () => {
    // East of UTC the day starts on the previous UTC date (22:00Z in summer).
    vi.stubEnv("TZ", "Europe/Stockholm");
    try {
      renderPage();
      const from = screen.getByRole("combobox", { name: "Från" });

      fireEvent.change(from, { target: { value: "2026-09-10" } });
      fireEvent.blur(from);

      await waitFor(() =>
        expect(
          spies.questionQueries.some((query) => query.from_date === "2026-09-09T22:00:00.000Z")
        ).toBe(true)
      );
      expect((from as HTMLInputElement).value).toMatch(/^10 sep\.? 2026$/);
    } finally {
      vi.unstubAllEnvs();
    }
  });
});

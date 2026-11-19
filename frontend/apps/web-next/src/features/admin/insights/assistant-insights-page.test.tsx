// @vitest-environment jsdom
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
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
  source?: string;
  compare?: boolean;
  group_chat_id?: string;
};

const counts = (user: number, widget: number, api_key: number) => ({
  total: user + widget + api_key,
  user,
  widget,
  api_key
});

const PERIOD = {
  start: "2026-09-01T00:00:00Z",
  end: "2026-10-01T00:00:00Z",
  conversations: counts(8, 0, 4),
  questions: counts(20, 0, 10),
  followups: 18,
  users: 4,
  single_question_conversations: 5,
  returning_users: 1,
  unanswered: 2,
  knowledge: null,
  answer_ratings: { positive: 7, negative: 2, with_comment: 0, negative_with_comment: 0 },
  conversation_ratings: { positive: 0, negative: 0, with_comment: 0, negative_with_comment: 0 }
};

/** The answers that say they cannot answer, as the finding lists them. */
const UNANSWERED = {
  kind: "unanswered",
  question_id: "q2",
  question: "Hur lång är avtalstiden?",
  session_id: "session-2",
  source: "api_key",
  created_at: "2026-09-21T09:30:00Z",
  phrase: "har ingen information om",
  rating: null
};

const QUESTIONS = [
  {
    id: "q1",
    question: "Vilka regler gäller för direktupphandling?",
    created_at: "2026-09-20T08:00:00Z",
    session_id: "session-1",
    source: "user"
  },
  {
    id: "q2",
    question: "Hur lång är avtalstiden?",
    created_at: "2026-09-21T09:30:00Z",
    session_id: "session-2",
    source: "api_key"
  }
];

const spies = vi.hoisted(() => ({
  announce: vi.fn(),
  questionQueries: [] as QuestionQuery[],
  summaryQueries: [] as QuestionQuery[],
  /** Every GET the page made, by path. */
  paths: [] as string[],
  /** The conversations the explore dialog was asked to show. */
  previewed: [] as string[],
  log: null as unknown,
  logFails: null as number | null
}));

vi.mock("@/lib/api/browser", () => ({
  browserApi: {
    GET: vi.fn(
      async (
        path: string,
        init?: { params?: { query?: QuestionQuery; path?: Record<string, string> } }
      ) => {
        spies.paths.push(path);
        if (path === "/api/v1/logging/{message_id}/")
          return spies.logFails
            ? {
                error: { message: "Question was not logged." },
                response: new Response(null, { status: spies.logFails })
              }
            : { data: spies.log, response: new Response("{}") };
        if (path === "/api/v1/analysis/conversation-insights/summary/") {
          spies.summaryQueries.push(init?.params?.query ?? {});
          return {
            data: { timezone: "UTC", source: null, period: PERIOD, previous: null },
            response: new Response("{}")
          };
        }
        if (path === "/api/v1/analysis/conversation-insights/activity/")
          return {
            data: { timezone: "UTC", source: null, start: "", end: "", days: [] },
            response: new Response("{}")
          };
        const scope = { timezone: "UTC", source: null, start: "", end: "" };
        if (path === "/api/v1/analysis/conversation-insights/findings/")
          return { data: { ...scope, findings: [] }, response: new Response("{}") };
        if (path === "/api/v1/analysis/conversation-insights/findings/{kind}/")
          return {
            data: {
              ...scope,
              kind: "unanswered",
              items: [UNANSWERED],
              total_count: 1,
              limit: 20,
              next_cursor: null
            },
            response: new Response("{}")
          };
        if (path === "/api/v1/analysis/conversation-insights/questions/top/")
          return {
            data: { ...scope, include_followups: true, total_questions: 0, groups: [] },
            response: new Response("{}")
          };
        if (path === "/api/v1/analysis/conversation-insights/knowledge/")
          return {
            data: { ...scope, answers: 0, citing_answers: 0, sources: [], unused: [] },
            response: new Response("{}")
          };
        if (path === "/api/v1/analysis/conversation-insights/tools/")
          return { data: { ...scope, tools: [] }, response: new Response("{}") };
        if (path === "/api/v1/analysis/conversation-insights/feedback/")
          return {
            data: { items: [], total_count: 0, next_cursor: null },
            response: new Response("{}")
          };
        if (path === "/api/v1/analysis/conversation-insights/sessions/")
          return {
            data: { items: [], total_count: 0, next_cursor: null },
            response: new Response("{}")
          };
        if (path === "/api/v1/analysis/conversation-insights/sessions/{session_id}/") {
          const id = init?.params?.path?.session_id ?? "";
          spies.previewed.push(id);
          return {
            data: {
              id,
              name: "Direktupphandling",
              source: "user",
              messages: [{ id: "m-1", question: "Vilka regler gäller?", answer: "LOU gäller." }]
            },
            response: new Response("{}")
          };
        }
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
      }
    )
  }
}));
vi.mock("@astryxdesign/core/hooks", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@astryxdesign/core/hooks")>()),
  useAnnounce: () => spies.announce
}));

import { AssistantInsightsPage, GroupChatInsightsPage } from "./assistant-insights-page";

afterEach(() => {
  cleanup();
  spies.announce.mockReset();
  spies.questionQueries.length = 0;
  spies.summaryQueries.length = 0;
  spies.paths.length = 0;
  spies.previewed.length = 0;
  spies.log = null;
  spies.logFails = null;
});

function renderPage(
  route?: string,
  assistant: { insight_enabled?: boolean; permissions?: string[]; space_id?: string } = {}
) {
  const queryClient = testQueryClient();
  queryClient.setQueryData(["assistants", "assistant-1"], {
    id: "assistant-1",
    name: "Upphandlingsassistenten",
    insight_enabled: true,
    permissions: ["read", "insight_view"],
    ...assistant
  });
  return renderInApp(<AssistantInsightsPage assistantId="assistant-1" />, { queryClient, route });
}

describe("AssistantInsightsPage", () => {
  it("shows the assistant's insights view under its header, with the way back to the overview", async () => {
    const { container } = renderPage();
    expect(screen.getByRole("heading", { name: "Upphandlingsassistenten", level: 1 })).toBeTruthy();
    expect(screen.getByRole("link", { name: "Insikter" }).getAttribute("href")).toBe(
      "/admin/insights"
    );
    // The same view as the chat page's Insikter tab: the period, its counts,
    // the analysis behind "Fråga analysen" and the question history.
    expect(screen.getByRole("button", { name: /Period/ })).toBeTruthy();
    const tiles = await screen.findByRole("region", { name: "Nyckeltal" });
    expect(within(tiles).getByText("12")).toBeTruthy();
    // No knowledge attached: no knowledge figure.
    expect(within(tiles).queryByText("Träff i kunskapen")).toBeNull();
    expect(screen.getByRole("button", { name: "Fråga analysen" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Utforska konversationer" })).toBeTruthy();
    const table = await screen.findByRole("table", { name: "Frågehistorik" });
    const row = within(table)
      .getAllByRole("row")
      .find((candidate) => within(candidate).queryByText("Hur lång är avtalstiden?"))!;
    // Each question says where its conversation came from.
    expect(within(row).getByText("API")).toBeTruthy();
    expect(screen.getByRole("region", { name: "Återkoppling från användarna" })).toBeTruthy();
    // The one-shot analysis is gone.
    expect(screen.queryByRole("tab", { name: "Analysera" })).toBeNull();
    await expectNoAxeViolations(container);
  });

  it("shows a group chat's insights the same way, without a question history", async () => {
    const queryClient = testQueryClient();
    queryClient.setQueryData(["group-chats", "group-1"], {
      id: "group-1",
      name: "Upphandlingsstöd",
      insight_enabled: true,
      permissions: ["read", "insight_view"]
    });
    renderInApp(<GroupChatInsightsPage groupChatId="group-1" />, { queryClient });
    expect(screen.getByRole("heading", { name: "Upphandlingsstöd", level: 1 })).toBeTruthy();
    await screen.findByRole("region", { name: "Nyckeltal" });
    expect(spies.summaryQueries[0]).toMatchObject({ group_chat_id: "group-1" });
    expect(screen.queryByRole("table", { name: "Frågehistorik" })).toBeNull();
  });

  it.each([
    [
      "switched off",
      { insight_enabled: false },
      "Insikter är avstängda",
      "Slå på insikter i assistentens inställningar för att se hur den används."
    ],
    [
      "not the caller's to see",
      { permissions: ["read"] },
      "Du kan inte se de här insikterna",
      "Insikter visas bara för den som har tillgång till dem, och bara när insikter är påslagna."
    ]
  ])(
    "says so for insights %s, without asking for them",
    async (_, assistant, title, description) => {
      renderPage(undefined, assistant);
      expect(
        screen.getByRole("heading", { name: "Upphandlingsassistenten", level: 1 })
      ).toBeTruthy();
      expect(screen.getByRole("heading", { name: title })).toBeTruthy();
      expect(screen.getByText(description)).toBeTruthy();
      expect(screen.queryByRole("button", { name: "Fråga analysen" })).toBeNull();
      expect(spies.paths).toEqual([]);
    }
  );

  it("opens a question's conversation read-only in the explore dialog", async () => {
    renderPage();
    const table = await screen.findByRole("table", { name: "Frågehistorik" });
    // Every row opens its conversation; the button's name says which one by
    // the question's time, as the row's Skapad cell writes it.
    const row = within(table)
      .getAllByRole("row")
      .find((candidate) => within(candidate).queryByText(QUESTIONS[0]!.question))!;
    const time = within(row).getAllByRole("cell")[0]!.textContent!;
    expect(time).toMatch(/2026/);
    const open = within(row).getByRole("button", { name: `Session från ${time}` });
    expect(open.textContent).toBe("Session");
    expect(open.getAttribute("aria-haspopup")).toBe("dialog");
    fireEvent.click(open);

    const dialog = await screen.findByRole("dialog", { name: "Utforska konversationer" });
    expect(await within(dialog).findByText("LOU gäller.")).toBeTruthy();
    expect(spies.previewed).toEqual(["session-1"]);
  });

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

  it("says calmly that a question has no log, with nothing to retry", async () => {
    spies.logFails = 400;
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: QUESTIONS[0]!.question }));
    const dialog = screen.getByRole("dialog", { name: "Frågedetaljer" });
    expect(await within(dialog).findByText(/Frågan har ingen logg/)).toBeTruthy();
    expect(within(dialog).queryByText("Question was not logged.")).toBeNull();
    expect(within(dialog).queryByRole("button", { name: "Försök igen" })).toBeNull();
    expect(within(dialog).queryByRole("button", { name: "Kopiera" })).toBeNull();
    expect(
      within(dialog).queryByRole("region", { name: "Loggad information som JSON" })
    ).toBeNull();
    spies.logFails = null;
  });

  it("retries a failed log read without passing a row off as a full log", async () => {
    spies.logFails = 500;
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: QUESTIONS[0]!.question }));
    const dialog = screen.getByRole("dialog", { name: "Frågedetaljer" });
    const retry = await within(dialog).findByRole("button", { name: "Försök igen" });
    expect(within(dialog).queryByRole("button", { name: "Kopiera" })).toBeNull();
    expect(
      within(dialog).queryByRole("region", { name: "Loggad information som JSON" })
    ).toBeNull();
    spies.logFails = null;
    spies.log = { ...QUESTIONS[0], logging_details: { prompt: "fixture" } };
    fireEvent.click(retry);
    expect(
      await within(dialog).findByRole("region", { name: "Loggad information som JSON" })
    ).toBeTruthy();
  });

  it("announces how many questions a search found once its results are in", async () => {
    renderPage();
    await screen.findByRole("table", { name: "Frågehistorik" });
    expect(spies.announce).not.toHaveBeenCalled();

    fireEvent.change(screen.getByRole("textbox", { name: "Sök" }), {
      target: { value: "avtal" }
    });

    await waitFor(() => expect(spies.announce).toHaveBeenCalledWith("Laddade 1/1 frågor"));
    const table = screen.getByRole("table", { name: "Frågehistorik" });
    expect(within(table).queryByText("Vilka regler gäller för direktupphandling?")).toBeNull();
  });

  it("opens the finding in the URL in place of the overview, with the editor for an editor", async () => {
    renderPage(
      "/admin/insights/assistant/assistant-1?from=2026-09-10&to=2026-09-30&finding=unanswered",
      { permissions: ["read", "edit", "insight_view"], space_id: "space-1" }
    );
    expect(
      await screen.findByRole("heading", {
        name: "Assistenten säger ofta att den inte kan svara",
        level: 2
      })
    ).toBeTruthy();
    const table = await screen.findByRole("table", { name: "Exempel" });
    expect(within(table).getByText("”har ingen information om”")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Redigera assistenten" }).getAttribute("href")).toBe(
      "/spaces/space-1/assistants/assistant-1/edit?section=instructions#instructions"
    );
    // The way back drops the finding from the address and keeps the filters.
    fireEvent.click(screen.getByRole("button", { name: "Tillbaka till insikterna" }));
    await waitFor(() => {
      const search = new URLSearchParams(window.location.search);
      expect(search.has("finding")).toBe(false);
      expect(search.get("from")).toBe("2026-09-10");
    });
    expect(await screen.findByRole("region", { name: "Nyckeltal" })).toBeTruthy();
  });

  it("reads the filters from the URL as full local days and keeps new ones there", async () => {
    vi.stubEnv("TZ", "Europe/Stockholm");
    try {
      renderPage(
        "/admin/insights/assistant/assistant-1?from=2026-09-10&to=2026-09-30&source=api_key&compare=1"
      );
      await waitFor(() =>
        expect(
          spies.questionQueries.some(
            (query) =>
              query.from_date === "2026-09-09T22:00:00.000Z" &&
              query.to_date === "2026-09-30T21:59:59.999999Z" &&
              query.include_followups === true &&
              query.source === "api_key"
          )
        ).toBe(true)
      );
      expect(spies.summaryQueries[0]).toMatchObject({ source: "api_key", compare: true });
      // A new source and the comparison switched off are written to the address.
      fireEvent.click(screen.getByRole("radio", { name: "Användare" }));
      fireEvent.click(screen.getByRole("switch", { name: "Jämför med föregående period" }));
      await waitFor(() => {
        const search = new URLSearchParams(window.location.search);
        expect(search.get("source")).toBe("user");
        expect(search.has("compare")).toBe(false);
      });
      // Leaving the follow-up questions out is the history's own choice, not the address's.
      fireEvent.click(screen.getByRole("switch", { name: "Inkludera uppföljningsfrågor" }));
      await waitFor(() => expect(spies.questionQueries.at(-1)?.include_followups).toBe(false));
      expect(new URLSearchParams(window.location.search).get("followups")).toBeNull();

      fireEvent.click(screen.getByRole("button", { name: /Period/ }));
      fireEvent.click(await screen.findByRole("button", { name: "Senaste 7 dagarna" }));
      await waitFor(() =>
        expect(new URLSearchParams(window.location.search).get("from")).not.toBe("2026-09-10")
      );
      const search = new URLSearchParams(window.location.search);
      expect(search.get("to")).toMatch(/^\d{4}-\d{2}-\d{2}$/);
    } finally {
      vi.unstubAllEnvs();
    }
  });
});

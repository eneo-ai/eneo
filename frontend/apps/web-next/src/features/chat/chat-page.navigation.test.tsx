// @vitest-environment jsdom
import {
  createBrowserHistory,
  createRoute,
  type AnyRootRoute,
  type RouterHistory
} from "@tanstack/react-router";
import { act, cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import type { ChatPartner } from "@/lib/chat/types";
import { useSearchParams } from "@/lib/navigation";
import { renderWithRouter } from "@/test/router";
import { ChatPage } from "./chat-page";

vi.unmock("@/lib/link");

const spies = vi.hoisted(() => ({ detailCalls: [] as string[] }));

vi.mock("@/lib/chat/transport", () => ({
  createChatTransport: () => ({
    sendMessages: async () => new ReadableStream(),
    reconnectToStream: async () => null
  })
}));

const counts = (total: number) => ({ total, user: total, widget: 0, api_key: 0 });

vi.mock("@/lib/api/browser", () => ({
  browserApi: {
    GET: vi.fn(async (path: string, init?: { params?: { path?: { session_id?: string } } }) => {
      if (path === "/api/v1/conversations/{session_id}/") {
        const id = init?.params?.path?.session_id ?? "";
        spies.detailCalls.push(id);
        return {
          data: {
            id,
            name: `Samtal ${id}`,
            feedback: null,
            messages: [
              {
                id: `m-${id}`,
                question: `Fråga i ${id}`,
                answer: `Svar i ${id}`,
                references: [],
                files: [],
                generated_files: [],
                tools: { assistants: [] },
                feedback: null
              }
            ]
          },
          response: new Response()
        };
      }
      if (path === "/api/v1/conversations/") {
        const updated_at = new Date().toISOString();
        return {
          data: {
            items: [
              { id: "s-1", name: "Samtal s-1", updated_at },
              { id: "s-2", name: "Samtal s-2", updated_at }
            ],
            total_count: 2,
            next_cursor: null
          },
          response: new Response()
        };
      }
      const period = {
        start: "2026-09-01T00:00:00Z",
        end: "2026-10-01T00:00:00Z",
        conversations: counts(12),
        questions: counts(30),
        followups: 18,
        users: 4,
        single_question_conversations: 5,
        returning_users: 1,
        unanswered: 2,
        knowledge: { searched: 20, missed: 5 },
        answer_ratings: { positive: 3, negative: 1, with_comment: 0, negative_with_comment: 0 },
        conversation_ratings: {
          positive: 0,
          negative: 0,
          with_comment: 0,
          negative_with_comment: 0
        }
      };
      const data = {
        "/api/v1/analysis/conversation-insights/summary/": { period, previous: null },
        "/api/v1/analysis/conversation-insights/activity/": { days: [] },
        "/api/v1/analysis/conversation-insights/findings/": {
          findings: [
            {
              kind: "knowledge_missed",
              affected: 5,
              base: 20,
              examples: [],
              sources: null,
              tool: null
            },
            {
              kind: "negative_ratings",
              affected: 1,
              base: 4,
              examples: [],
              sources: null,
              tool: null
            }
          ]
        },
        "/api/v1/analysis/conversation-insights/questions/top/": { groups: [] },
        "/api/v1/analysis/conversation-insights/knowledge/": { sources: [], unused: [] },
        "/api/v1/analysis/conversation-insights/tools/": { tools: [] }
      }[path];
      return {
        data: data ?? { items: [], total_count: 0, next_cursor: null },
        response: new Response()
      };
    }),
    POST: vi.fn(async () => ({ data: {}, response: new Response() }))
  }
}));
// The insights chat's own endpoints: no earlier analyses.
vi.mock("@/lib/api/base", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api/base")>()),
  apiFetch: vi.fn(async () => Response.json({ items: [], total_count: 0 }))
}));

let history: RouterHistory;

afterEach(() => {
  cleanup();
  history.destroy();
  // The composer keeps its draft for the tab (sessionStorage).
  sessionStorage.clear();
  spies.detailCalls.length = 0;
});

const partner: ChatPartner = {
  type: "assistant",
  id: "assistant-1",
  name: "Upphandlingsassistenten",
  insightEnabled: true,
  permissions: ["insight_view"]
};

function Chat() {
  const sessionId = useSearchParams().get("session_id");
  return (
    <ChatPage
      partner={partner}
      sessionId={sessionId}
      buildSessionUrl={(id) => (id ? `/chat?session_id=${id}` : "/chat")}
    />
  );
}

/** The chat page in the browser's own history, with conversation s-1 open in Chatt. */
async function renderChat() {
  window.history.replaceState(null, "", "/outside");
  window.history.pushState(null, "", "/chat?session_id=s-1");
  history = createBrowserHistory();
  const rendered = await renderWithRouter(null, {
    history,
    routes: (root: AnyRootRoute) => [
      createRoute({ getParentRoute: () => root, path: "/chat", component: Chat }),
      createRoute({
        getParentRoute: () => root,
        path: "/outside",
        component: () => <h1>Utanför chatten</h1>
      })
    ]
  });
  expect(await screen.findByText("Svar i s-1")).toBeTruthy();
  return rendered;
}

const tab = (name: string) => screen.getByRole("tab", { name });
const composer = () => screen.getByRole("textbox", { name: /^Fråga / }) as HTMLTextAreaElement;

it("keeps the tabs and an opened finding in the browser's history, past an unsent question", async () => {
  const { router } = await renderChat();
  fireEvent.change(composer(), { target: { value: "Osänd fråga" } });

  fireEvent.click(tab("Insikter"));
  fireEvent.click(await screen.findByRole("button", { name: "Visa frågorna" }));
  await screen.findByRole("heading", { name: "Många frågor får inget stöd i kunskapen", level: 2 });
  expect(router.state.location.search).toEqual({
    session_id: "s-1",
    tab: "insights",
    finding: "knowledge_missed"
  });

  // Back: Insikter's overview, then Chatt with its draft, on the page and without a question.
  act(() => history.back());
  expect(await screen.findByRole("region", { name: "Nyckeltal" })).toBeTruthy();
  expect(router.state.location.search).toEqual({ session_id: "s-1", tab: "insights" });
  act(() => history.back());
  await waitFor(() => expect(tab("Chatt").getAttribute("aria-selected")).toBe("true"));
  expect(router.state.location.pathname).toBe("/chat");
  expect(composer().value).toBe("Osänd fråga");
  expect(screen.queryByRole("alertdialog")).toBeNull();

  // Forward to the finding again; its way back returns to the overview's entry instead of adding one.
  act(() => history.forward());
  await waitFor(() => expect(tab("Insikter").getAttribute("aria-selected")).toBe("true"));
  act(() => history.forward());
  await screen.findByRole("heading", { name: "Många frågor får inget stöd i kunskapen", level: 2 });
  fireEvent.click(screen.getByRole("button", { name: "Tillbaka till insikterna" }));
  expect(await screen.findByRole("region", { name: "Nyckeltal" })).toBeTruthy();
  expect(router.state.location.state.__TSR_index).toBe(1);
  expect(spies.detailCalls).toEqual(["s-1"]);
});

it("keeps the conversation open since when Back returns to an earlier tab", async () => {
  const { router } = await renderChat();
  fireEvent.click(tab("Historik"));
  const historik = await screen.findByRole("tabpanel", { name: "Historik" });
  fireEvent.click(await within(historik).findByRole("button", { name: /^Samtal s-2/ }));
  expect(await screen.findByText("Svar i s-2")).toBeTruthy();
  expect(router.state.location.search).toEqual({ session_id: "s-2" });

  // Historik's entry named s-1: the tab comes back, s-2 stays open, and the address names it.
  act(() => history.back());
  await waitFor(() => expect(tab("Historik").getAttribute("aria-selected")).toBe("true"));
  await waitFor(() =>
    expect(router.state.location.search).toEqual({ session_id: "s-2", tab: "history" })
  );
  act(() => history.back());
  await waitFor(() => expect(tab("Chatt").getAttribute("aria-selected")).toBe("true"));
  await waitFor(() => expect(router.state.location.search).toEqual({ session_id: "s-2" }));
  expect(screen.getByText("Svar i s-2")).toBeTruthy();
  expect(spies.detailCalls).toEqual(["s-1", "s-2"]);
});

it('returns from "Läs kommentarerna" to the overview with the inbox\'s filter as it was', async () => {
  const { router } = await renderChat();
  fireEvent.click(tab("Insikter"));
  const inbox = await screen.findByRole("region", { name: "Återkoppling från användarna" });
  const heading = within(inbox).getByRole("heading", { name: "Återkoppling från användarna" });
  const filter = (name: RegExp) => within(inbox).getByRole("radio", { name });

  // The inbox's own filter changes the address in place.
  fireEvent.click(filter(/^Bra/));
  await waitFor(() => expect(router.state.location.search).toMatchObject({ feedback: "good" }));
  const overview = router.state.location.state.__TSR_index;

  const read = await screen.findByRole("button", { name: "Läs kommentarerna" });
  act(() => read.focus());
  fireEvent.click(read);
  await waitFor(() =>
    expect(router.state.location.search).toMatchObject({ feedback: "bad_commented" })
  );
  expect(router.state.location.state.__TSR_index).toBe(overview + 1);
  expect(filter(/^Dåliga med kommentar/).getAttribute("aria-checked")).toBe("true");
  expect(document.activeElement).toBe(heading);

  // Back: the overview as it was, with focus on the button, still on the page.
  act(() => history.back());
  await waitFor(() => expect(filter(/^Bra/).getAttribute("aria-checked")).toBe("true"));
  expect(router.state.location.pathname).toBe("/chat");
  expect(router.state.location.search).toEqual({
    session_id: "s-1",
    tab: "insights",
    feedback: "good"
  });
  await waitFor(() => expect(document.activeElement).toBe(read));

  // Forward: the comments again, with focus on the inbox.
  act(() => history.forward());
  await waitFor(() =>
    expect(filter(/^Dåliga med kommentar/).getAttribute("aria-checked")).toBe("true")
  );
  await waitFor(() => expect(document.activeElement).toBe(heading));
});

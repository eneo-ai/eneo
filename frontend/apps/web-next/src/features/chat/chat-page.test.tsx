// @vitest-environment jsdom
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import type { ChatPartner } from "@/lib/chat/types";
import { expectNoAxeViolations } from "@/test/axe";
import { ChatPage } from "./chat-page";
import { ChatTestProviders, installDomPolyfills } from "./testing";

const api = vi.hoisted(() => ({
  detailCalls: [] as string[],
  GET: vi.fn(async (path: string, init?: { params?: { path?: { session_id?: string } } }) => {
    if (path === "/api/v1/conversations/{session_id}/") {
      const id = init?.params?.path?.session_id ?? "";
      api.detailCalls.push(id);
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
              tools: { assistants: [] }
            }
          ]
        },
        response: new Response()
      };
    }
    return { data: { items: [], next_cursor: null }, response: new Response() };
  }),
  POST: vi.fn(),
  PATCH: vi.fn(),
  DELETE: vi.fn()
}));
vi.mock("@/lib/api/browser", () => ({ browserApi: api }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));

beforeAll(() => installDomPolyfills());
afterEach(() => {
  cleanup();
  api.detailCalls.length = 0;
});

const partner: ChatPartner = {
  type: "assistant",
  id: "assistant-1",
  name: "Upphandlingsassistenten",
  spaceName: "Upphandling"
};

function renderPage(sessionId: string | null) {
  const buildSessionUrl = (id: string | null) => (id ? `/chat?session_id=${id}` : "/chat");
  const view = render(
    <ChatTestProviders>
      <ChatPage partner={partner} sessionId={sessionId} buildSessionUrl={buildSessionUrl} />
    </ChatTestProviders>
  );
  const rerender = (next: string | null) =>
    view.rerender(
      <ChatTestProviders>
        <ChatPage partner={partner} sessionId={next} buildSessionUrl={buildSessionUrl} />
      </ChatTestProviders>
    );
  return rerender;
}

describe("ChatPage", () => {
  it("follows ?session_id= on the same route and starts fresh without one", async () => {
    const rerender = renderPage(null);
    expect(screen.getByRole("heading", { level: 1, name: "Upphandlingsassistenten" })).toBeTruthy();

    rerender("s-1");
    const log = await screen.findByRole("log", { name: "Konversation" });
    expect(within(log).getByText("Svar i s-1")).toBeTruthy();
    expect(screen.getAllByRole("heading", { level: 1, name: "Samtal s-1" }).length).toBeGreaterThan(
      0
    );

    rerender("s-2");
    await waitFor(() =>
      expect(within(screen.getByRole("log")).getByText("Svar i s-2")).toBeTruthy()
    );

    // "Ny konversation" in the SideNav: the same route without session_id.
    rerender(null);
    await waitFor(() => expect(screen.queryByRole("log")).toBeNull());
    expect(screen.getByRole("heading", { level: 1, name: "Upphandlingsassistenten" })).toBeTruthy();
    expect(api.detailCalls).toEqual(["s-1", "s-2"]);
  });

  it("does not reload the conversation it already shows", async () => {
    const rerender = renderPage("s-1");
    await screen.findByRole("log", { name: "Konversation" });
    rerender("s-1");
    await waitFor(() => expect(screen.getByRole("log")).toBeTruthy());
    expect(api.detailCalls).toEqual(["s-1"]);
  });

  it("has no axe violations with a loaded conversation", async () => {
    renderPage("s-1");
    await screen.findByRole("log", { name: "Konversation" });
    await expectNoAxeViolations(document.body);
  });
});

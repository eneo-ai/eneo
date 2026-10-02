// @vitest-environment jsdom
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ChatPartner } from "@/lib/chat/types";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";
import { ExploreConversationsDialog } from "./explore-conversations-dialog";

const spies = vi.hoisted(() => ({
  announce: vi.fn(),
  listCalls: [] as Record<string, unknown>[]
}));

const session = (id: string, name: string) => ({
  id,
  name,
  created_at: "2026-09-30T10:00:00Z",
  updated_at: "2026-09-30T10:00:00Z"
});

vi.mock("@/lib/api/browser", () => ({
  browserApi: {
    GET: vi.fn(
      async (
        path: string,
        init?: { params?: { query?: Record<string, unknown>; path?: Record<string, string> } }
      ) => {
        if (path === "/api/v1/analysis/conversation-insights/sessions/") {
          const query = init?.params?.query ?? {};
          spies.listCalls.push(query);
          if (query.name_filter === "LOU") {
            return {
              data: { items: [session("s-2", "LOU-gränser")], total_count: 1, next_cursor: null },
              response: new Response()
            };
          }
          if (query.cursor === "page-2") {
            return {
              data: {
                items: [session("s-3", "Tredje samtalet")],
                total_count: 3,
                next_cursor: null
              },
              response: new Response()
            };
          }
          return {
            data: {
              items: [session("s-1", "Direktupphandling"), session("s-2", "LOU-gränser")],
              total_count: 3,
              next_cursor: "page-2"
            },
            response: new Response()
          };
        }
        if (path === "/api/v1/analysis/conversation-insights/sessions/{session_id}/") {
          const id = init?.params?.path?.session_id;
          return {
            data: {
              id,
              name: "Direktupphandling",
              messages:
                id === "s-3"
                  ? []
                  : [
                      {
                        id: "m-1",
                        question: "Vad är gränsen?",
                        answer: "Gränsen är 700 000 kr.",
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
        return { data: undefined, error: { message: "unexpected" }, response: new Response() };
      }
    )
  }
}));
vi.mock("@astryxdesign/core/hooks", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@astryxdesign/core/hooks")>()),
  useAnnounce: () => spies.announce
}));

afterEach(() => {
  cleanup();
  spies.announce.mockReset();
  spies.listCalls.length = 0;
});

const partner: ChatPartner & { type: "assistant" } = {
  type: "assistant",
  id: "assistant-1",
  name: "Upphandlingsassistenten",
  insightEnabled: true
};

function renderDialog(onOpenChange = vi.fn()) {
  renderInApp(
    <ExploreConversationsDialog
      partner={partner}
      range={{ start: "2026-09-02", end: "2026-10-02" }}
      isOpen
      onOpenChange={onOpenChange}
    />
  );
  return onOpenChange;
}

describe("ExploreConversationsDialog", () => {
  it("lists the period's conversations a page at a time and opens one to read", async () => {
    renderDialog();
    const dialog = await screen.findByRole("dialog", { name: "Utforska konversationer" });
    expect(await within(dialog).findByRole("button", { name: /Direktupphandling/ })).toBeTruthy();
    expect(spies.listCalls[0]).toMatchObject({
      assistant_id: "assistant-1",
      start_date: "2026-09-02",
      end_date: "2026-10-03",
      limit: 50
    });
    expect(within(dialog).getByText("Laddade 2/3 konversationer")).toBeTruthy();
    expect(within(dialog).getByText("Välj en konversation.")).toBeTruthy();

    fireEvent.click(within(dialog).getByRole("button", { name: "Ladda fler konversationer" }));
    const third = await within(dialog).findByRole("button", { name: /Tredje samtalet/ });
    expect(spies.listCalls[1]).toMatchObject({ cursor: "page-2" });
    expect(within(dialog).getByText("Laddade alla 3 konversationer.")).toBeTruthy();
    expect(spies.announce).toHaveBeenCalledWith("Laddade alla 3 konversationer.");
    // Focus lands on the first conversation the page added.
    await waitFor(() => expect(document.activeElement).toBe(third));

    const row = within(dialog).getByRole("button", { name: /Direktupphandling/ });
    fireEvent.click(row);
    expect(row.getAttribute("aria-pressed")).toBe("true");
    const preview = within(dialog).getByRole("region", { name: "Vald konversation" });
    expect(await within(preview).findByText("Vad är gränsen?")).toBeTruthy();
    expect(within(preview).getByText("Gränsen är 700 000 kr.")).toBeTruthy();
    expect(
      within(preview).getByRole("article", { name: /svar från upphandlingsassistenten/i })
    ).toBeTruthy();

    fireEvent.click(third);
    expect(
      await within(preview).findByText("Den här konversationen innehåller inga meddelanden.")
    ).toBeTruthy();
  });

  it("filters by title once typing pauses", async () => {
    renderDialog();
    const dialog = await screen.findByRole("dialog", { name: "Utforska konversationer" });
    await within(dialog).findByRole("button", { name: /Direktupphandling/ });
    fireEvent.change(within(dialog).getByRole("textbox", { name: "Sök konversation" }), {
      target: { value: "LOU" }
    });
    await waitFor(() =>
      expect(spies.listCalls.some((call) => call.name_filter === "LOU")).toBe(true)
    );
    await waitFor(() =>
      expect(within(dialog).queryByRole("button", { name: /Direktupphandling/ })).toBeNull()
    );
    expect(within(dialog).getByRole("button", { name: /LOU-gränser/ })).toBeTruthy();
  });

  it("closes with Escape and has no axe violations", async () => {
    const onOpenChange = renderDialog();
    const dialog = await screen.findByRole("dialog", { name: "Utforska konversationer" });
    await within(dialog).findByRole("button", { name: /Direktupphandling/ });
    await expectNoAxeViolations(document.body);
    fireEvent.keyDown(dialog, { key: "Escape" });
    await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false));
  });
});

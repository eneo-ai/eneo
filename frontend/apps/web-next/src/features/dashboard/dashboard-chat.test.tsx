// @vitest-environment jsdom
import { act, cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { makeQueryClient } from "@/lib/api/query";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";
import { DashboardChat } from "@/features/dashboard/dashboard-chat.client";

const api = vi.hoisted(() => ({
  assistantCalls: 0,
  /** Whether the assistant request fails (the assistant is gone). */
  missing: true,
  /** The status it fails with. */
  status: 404,
  permissions: [] as string[],
  insights: false,
  GET: vi.fn(async (path: string) => {
    if (path === "/api/v1/assistants/{id}/") {
      api.assistantCalls += 1;
      if (api.missing) {
        return {
          data: undefined,
          error: { message: "Not found" },
          response: new Response(null, { status: api.status })
        };
      }
      return {
        data: {
          id: "assistant-1",
          name: "Upphandlingsassistenten",
          allowed_attachments: null,
          insight_enabled: api.insights,
          permissions: api.permissions,
          description: null,
          icon_id: null,
          mcp_servers: [],
          enabled_capabilities: [],
          available_capabilities: [],
          effective_config: null,
          completion_model: null,
          groups: [],
          websites: [],
          integration_knowledge_list: []
        },
        response: new Response()
      };
    }
    return { data: { items: [], next_cursor: null }, response: new Response() };
  }),
  POST: vi.fn(async () => ({ data: {}, response: new Response() }))
}));
vi.mock("@/lib/api/browser", () => ({ browserApi: api }));
vi.mock("@/lib/navigation", () => import("@/test/navigation"));

afterEach(() => {
  cleanup();
  api.assistantCalls = 0;
  api.missing = true;
  api.status = 404;
  api.permissions = [];
  api.insights = false;
});

function renderRoute() {
  return renderInApp(<DashboardChat assistantId="assistant-1" sessionId={null} />);
}

describe("DashboardChat", () => {
  it.each([false, true])(
    "projects the loaded assistant's insight permission (%s)",
    async (allowed) => {
      api.missing = false;
      api.insights = true;
      api.permissions = allowed ? ["read", "insight_view"] : ["read"];
      renderRoute();
      await screen.findByRole("heading", { name: "Upphandlingsassistenten", level: 1 });
      expect(Boolean(screen.queryByRole("radio", { name: "Insikter" }))).toBe(allowed);
    }
  );

  it("says the chat could not be opened instead of loading forever, and retries", async () => {
    const { container } = renderRoute();
    expect(screen.getByRole("heading", { level: 1, name: "Laddar assistenten…" })).toBeTruthy();
    expect(
      await screen.findByRole("heading", { level: 1, name: "Det gick inte att öppna chatten" })
    ).toBeTruthy();
    // A missing assistant is not retried behind the user's back.
    expect(api.assistantCalls).toBe(1);
    await expectNoAxeViolations(container);

    api.missing = false;
    fireEvent.click(screen.getByRole("button", { name: "Försök igen" }));
    expect(
      await screen.findByRole("heading", { level: 1, name: "Upphandlingsassistenten" })
    ).toBeTruthy();
    await waitFor(() => expect(api.assistantCalls).toBe(2));
  });
});

describe("the assistant request under the app's retry policy", () => {
  afterEach(() => vi.useRealTimers());

  it.each([
    [403, 1],
    [404, 1],
    [503, 2]
  ])("after a %s is sent %s time(s) in its first second", async (status, requests) => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    api.status = status;
    renderInApp(<DashboardChat assistantId="assistant-1" sessionId={null} />, {
      queryClient: makeQueryClient()
    });
    await waitFor(() => expect(api.assistantCalls).toBe(1));
    // The first retry waits one second, the next two more.
    await act(() => vi.advanceTimersByTimeAsync(1_500));
    expect(api.assistantCalls).toBe(requests);
  });
});

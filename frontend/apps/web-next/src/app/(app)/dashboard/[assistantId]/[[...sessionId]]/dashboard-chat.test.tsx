// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { retryPartnerQuery } from "@/features/chat/chat-partner-state";
import { ChatTestProviders, installDomPolyfills } from "@/features/chat/testing";
import { EneoApiError } from "@/lib/api/errors";
import { expectNoAxeViolations } from "@/test/axe";
import { DashboardChat } from "./dashboard-chat.client";

const api = vi.hoisted(() => ({
  assistantCalls: 0,
  /** Whether the assistant request fails (the assistant is gone). */
  missing: true,
  GET: vi.fn(async (path: string) => {
    if (path === "/api/v1/assistants/{id}/") {
      api.assistantCalls += 1;
      if (api.missing) {
        return {
          data: undefined,
          error: { message: "Not found" },
          response: new Response(null, { status: 404 })
        };
      }
      return {
        data: {
          id: "assistant-1",
          name: "Upphandlingsassistenten",
          allowed_attachments: null,
          insight_enabled: false,
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
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));

beforeAll(() => installDomPolyfills());
afterEach(() => {
  cleanup();
  api.assistantCalls = 0;
  api.missing = true;
});

function renderRoute() {
  return render(
    <ChatTestProviders>
      <DashboardChat assistantId="assistant-1" sessionId={null} />
    </ChatTestProviders>
  );
}

describe("DashboardChat", () => {
  it("says the chat could not be opened instead of loading forever, and retries", async () => {
    const { container } = renderRoute();
    expect(await screen.findByText("Det gick inte att öppna chatten")).toBeTruthy();
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

describe("retryPartnerQuery", () => {
  it("gives up at once on client errors and retries the rest three times", () => {
    const missing = new EneoApiError("Not found", { status: 404 });
    const down = new EneoApiError("Bad gateway", { status: 502 });
    expect(retryPartnerQuery(0, missing)).toBe(false);
    expect(retryPartnerQuery(0, down)).toBe(true);
    expect(retryPartnerQuery(3, down)).toBe(false);
    expect(retryPartnerQuery(1, new TypeError("Failed to fetch"))).toBe(true);
  });
});

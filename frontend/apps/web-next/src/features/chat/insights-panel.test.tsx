// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import type { ChatPartner } from "@/lib/chat/types";
import { expectNoAxeViolations } from "@/test/axe";
import { InsightsPanel } from "./insights-panel";
import { ChatTestProviders, installDomPolyfills } from "./testing";

const spies = vi.hoisted(() => ({
  announce: vi.fn(),
  /** What POST answers: an immediate answer or an asynchronous job. */
  response: { answer: "De flesta frågor gäller LOU." } as Record<string, unknown>,
  jobSignals: [] as (AbortSignal | undefined)[]
}));

vi.mock("@/lib/api/browser", () => ({
  browserApi: {
    GET: vi.fn(async (path: string, init?: { signal?: AbortSignal }) => {
      if (path === "/api/v1/analysis/conversation-insights/jobs/{job_id}/") {
        spies.jobSignals.push(init?.signal);
        return { data: { status: "running" }, response: new Response() };
      }
      return {
        data: { total_conversations: 12, total_questions: 30 },
        response: new Response()
      };
    }),
    POST: vi.fn(async () => ({ data: spies.response, response: new Response() }))
  }
}));
vi.mock("@astryxdesign/core/hooks", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@astryxdesign/core/hooks")>()),
  useAnnounce: () => spies.announce
}));

beforeAll(() => installDomPolyfills());
afterEach(() => {
  cleanup();
  spies.announce.mockReset();
  spies.response = { answer: "De flesta frågor gäller LOU." };
  spies.jobSignals.length = 0;
});

const partner: ChatPartner & { type: "assistant" } = {
  type: "assistant",
  id: "assistant-1",
  name: "Upphandlingsassistenten",
  insightEnabled: true
};

function renderPanel() {
  return render(
    <ChatTestProviders>
      <InsightsPanel partner={partner} />
    </ChatTestProviders>
  );
}

function ask(question: string) {
  fireEvent.change(screen.getByRole("textbox", { name: /Fråga om insikter/ }), {
    target: { value: question }
  });
  fireEvent.click(screen.getByRole("button", { name: "Generera insikter" }));
}

describe("InsightsPanel", () => {
  it("shows the counts and announces the answer without reading it out", async () => {
    renderPanel();
    expect(await screen.findByText("12")).toBeTruthy();
    expect(screen.getByText("30")).toBeTruthy();

    ask("Vad frågar folk om?");
    const answer = await screen.findByText("De flesta frågor gäller LOU.");
    expect(spies.announce).toHaveBeenCalledWith("Svaret är klart");
    // The answer is not inside a live region (that would read all of it).
    expect(answer.closest('[role="status"], [aria-live]')).toBeNull();
  });

  it("stops polling an insight job when the view closes", async () => {
    spies.response = { job_id: "job-1", is_async: true };
    const view = renderPanel();
    ask("Vad frågar folk om?");
    await waitFor(() => expect(spies.jobSignals).toHaveLength(1));
    expect(screen.getByText("Tar fram insikter…")).toBeTruthy();

    view.unmount();
    expect(spies.jobSignals[0]?.aborted).toBe(true);
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(spies.jobSignals).toHaveLength(1);
    expect(spies.announce).not.toHaveBeenCalled();
  });

  it("has no axe violations", async () => {
    const { container } = renderPanel();
    await screen.findByText("12");
    ask("Vad frågar folk om?");
    await screen.findByText("De flesta frågor gäller LOU.");
    await expectNoAxeViolations(container);
  });
});

// @vitest-environment jsdom
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ChatPartner } from "@/lib/chat/types";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";
import { InsightsPanel } from "./insights-panel";

const spies = vi.hoisted(() => ({
  announce: vi.fn(),
  /** What POST answers: an immediate answer or an asynchronous job. */
  response: { answer: "De flesta frågor gäller LOU." } as Record<string, unknown>,
  jobSignals: [] as (AbortSignal | undefined)[],
  /** The query of every statistics request. */
  statsQueries: [] as Record<string, unknown>[]
}));

vi.mock("@/lib/api/browser", () => ({
  browserApi: {
    GET: vi.fn(
      async (
        path: string,
        init?: { signal?: AbortSignal; params?: { query?: Record<string, unknown> } }
      ) => {
        if (path === "/api/v1/analysis/conversation-insights/jobs/{job_id}/") {
          spies.jobSignals.push(init?.signal);
          return { data: { status: "running" }, response: new Response() };
        }
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
        spies.statsQueries.push(init?.params?.query ?? {});
        return {
          data: {
            total_conversations: 12,
            total_questions: 30,
            feedback: { positive: 7, negative: 2 }
          },
          response: new Response()
        };
      }
    ),
    POST: vi.fn(async () => ({ data: spies.response, response: new Response() }))
  }
}));
vi.mock("@astryxdesign/core/hooks", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@astryxdesign/core/hooks")>()),
  useAnnounce: () => spies.announce
}));

afterEach(() => {
  cleanup();
  spies.announce.mockReset();
  spies.response = { answer: "De flesta frågor gäller LOU." };
  spies.jobSignals.length = 0;
  spies.statsQueries.length = 0;
});

const partner: ChatPartner & { type: "assistant" } = {
  type: "assistant",
  id: "assistant-1",
  name: "Upphandlingsassistenten",
  insightEnabled: true
};

function renderPanel() {
  return renderInApp(<InsightsPanel partner={partner} />);
}

function ask(question: string) {
  fireEvent.change(screen.getByRole("textbox", { name: /Fråga om insikter/ }), {
    target: { value: question }
  });
  fireEvent.click(screen.getByRole("button", { name: "Generera insikter" }));
}

describe("InsightsPanel", () => {
  it("shows an empty question at the field on submit, which takes focus", async () => {
    renderPanel();
    const question = screen.getByRole("textbox", { name: /Fråga om insikter/ });
    const generate = screen.getByRole("button", { name: "Generera insikter" });
    // Never disabled: a disabled button says nothing about what is missing.
    expect((generate as HTMLButtonElement).disabled).toBe(false);

    fireEvent.click(generate);

    expect(question.getAttribute("aria-invalid")).toBe("true");
    expect(screen.getAllByText("Detta fält är obligatoriskt").length).toBeGreaterThan(0);
    expect(document.activeElement).toBe(question);
    expect(spies.announce).not.toHaveBeenCalled();
  });

  it("shows the counts and announces the answer without reading it out", async () => {
    renderPanel();
    // Scoped to the statistics: the period picker's calendar also shows numbers.
    const stats = (await screen.findByText("Bra svar")).closest("dl")!;
    expect(within(stats).getByText("12")).toBeTruthy();
    expect(within(stats).getByText("30")).toBeTruthy();
    // How the answers were rated, each count named by its term.
    const good = within(stats).getByText("Bra svar").closest("div")!;
    expect(good.querySelector("dd")?.textContent).toBe("7");
    const bad = screen.getByText("Dåliga svar").closest("div")!;
    expect(bad.querySelector("dd")?.textContent).toBe("2");

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
    await screen.findByText("Bra svar");
    ask("Vad frågar folk om?");
    await screen.findByText("De flesta frågor gäller LOU.");
    await expectNoAxeViolations(container);
  });

  it("covers the last 30 days and refetches for a preset period", async () => {
    vi.useFakeTimers({ toFake: ["Date"], now: new Date(2026, 9, 2, 12) });
    try {
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
    } finally {
      vi.useRealTimers();
    }
  });

  it("opens the period's conversations to explore", async () => {
    renderPanel();
    await screen.findByText("Bra svar");
    fireEvent.click(screen.getByRole("button", { name: "Utforska konversationer" }));
    const dialog = await screen.findByRole("dialog", { name: "Utforska konversationer" });
    expect(await within(dialog).findByRole("button", { name: /Direktupphandling/ })).toBeTruthy();
  });
});

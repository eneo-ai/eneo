// @vitest-environment jsdom
import { cleanup, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";
import { AnswerFeedbackCell } from "./answer-feedback-cell";
import { AnswerFeedbackSummary } from "./answer-feedback-summary";

type ApiResult = { data?: unknown; error?: unknown; response: Response };

const api = vi.hoisted(() => ({
  GET: vi.fn<(path: string, init: unknown) => Promise<ApiResult>>(async () => ({
    data: { positive: 1204, negative: 37 },
    response: new Response()
  }))
}));
vi.mock("@/lib/api/browser", () => ({ browserApi: api }));

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

const filters = {
  start: "2026-08-27T00:00:00.000Z",
  end: "2026-09-26T21:59:59.000Z",
  includeFollowups: true
};

describe("AnswerFeedbackCell", () => {
  it("names a good rating and reads out the owner's comment", () => {
    const { container } = renderInApp(
      <AnswerFeedbackCell feedback={{ value: 1, text: "Tydligt och rätt paragraf" }} />
    );
    expect(screen.getByText("Bra svar")).toBeTruthy();
    const comment = screen.getByText("Tydligt och rätt paragraf");
    expect(comment.textContent).toBe("Kommentar: Tydligt och rätt paragraf");
    // The thumb is decoration: the rating is in the text.
    expect(container.querySelector("svg")?.getAttribute("aria-hidden")).toBe("true");
  });

  it("names a bad rating without a comment", () => {
    renderInApp(<AnswerFeedbackCell feedback={{ value: -1, text: null }} />);
    expect(screen.getByText("Dåligt svar")).toBeTruthy();
    expect(screen.queryByText(/Kommentar/)).toBeNull();
  });

  it("says so when the answer was not rated", () => {
    const { container } = renderInApp(<AnswerFeedbackCell feedback={null} />);
    expect(container.textContent).toBe("–Ingen återkoppling");
    expect(screen.getByText("–").getAttribute("aria-hidden")).toBe("true");
  });

  it("has no axe violations in a table", async () => {
    const { container } = renderInApp(
      <table>
        <thead>
          <tr>
            <th scope="col">Återkoppling</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td>
              <AnswerFeedbackCell feedback={{ value: -1, text: "Fel paragraf" }} />
            </td>
          </tr>
          <tr>
            <td>
              <AnswerFeedbackCell feedback={null} />
            </td>
          </tr>
        </tbody>
      </table>
    );
    await expectNoAxeViolations(container);
  });
});

describe("AnswerFeedbackSummary", () => {
  it("counts good and bad answer ratings for the page's filters", async () => {
    renderInApp(<AnswerFeedbackSummary assistantId="assistant-1" filters={filters} />);

    // Each count sits with its term, formatted for Swedish (a space groups thousands).
    const good = (await screen.findByText("Bra svar")).closest("div")!;
    expect(good.querySelector("dd")?.textContent).toBe(new Intl.NumberFormat("sv").format(1204));
    const bad = screen.getByText("Dåliga svar").closest("div")!;
    expect(bad.querySelector("dd")?.textContent).toBe("37");
    expect(api.GET).toHaveBeenCalledWith("/api/v1/analysis/assistants/{assistant_id}/feedback/", {
      params: {
        path: { assistant_id: "assistant-1" },
        query: {
          from_date: filters.start,
          to_date: filters.end,
          include_followups: true
        }
      },
      signal: expect.any(AbortSignal)
    });
  });

  it("shows loading as a status, then an error when the counts fail", async () => {
    api.GET.mockImplementationOnce(async () => ({
      data: undefined,
      error: { message: "Nope" },
      response: new Response(null, { status: 500 })
    }));
    renderInApp(<AnswerFeedbackSummary assistantId="assistant-1" filters={filters} />);

    expect(screen.getByRole("status")).toBeTruthy();
    expect(await screen.findByText("Något gick fel. Försök igen.")).toBeTruthy();
  });

  it("has no axe violations", async () => {
    const { container } = renderInApp(
      <AnswerFeedbackSummary assistantId="assistant-1" filters={filters} />
    );
    await screen.findByText("Dåliga svar");
    await expectNoAxeViolations(container);
  });
});

// @vitest-environment jsdom
import { cleanup, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";
import { AnswerFeedbackCell } from "./answer-feedback-cell";

afterEach(() => {
  cleanup();
});

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

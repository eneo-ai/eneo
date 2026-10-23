// @vitest-environment jsdom
import { cleanup, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";
import { ContextBudget, type ContextSegment } from "./context-budget";

afterEach(cleanup);

const segments: ContextSegment[] = [
  { key: "prompt", label: "Instruktioner", tokens: 1200, className: "bg-chart-1" },
  { key: "files", label: "Filer", tokens: 300, className: "bg-chart-2" }
];

describe("ContextBudget", () => {
  it("is a keyboard stop whose description is the per-input breakdown", async () => {
    const { container } = renderInApp(<ContextBudget segments={segments} maxTokens={1000} />);

    // Swedish number format (next-intl): "1,5 tn" with a no-break space.
    const trigger = screen.getByRole("button", { name: /^Kontextbudget: ~1,5\stn/ });
    expect(trigger.getAttribute("type")).toBe("button");
    trigger.focus();
    expect(document.activeElement).toBe(trigger);
    // Not only in a tooltip: the breakdown is the button's accessible description.
    const description = trigger
      .getAttribute("aria-describedby")
      ?.split(" ")
      .map((id) => document.getElementById(id)?.textContent)
      .join(" ");
    expect(description).toMatch(/Instruktioner 1,2\stn · Filer 300/);
    expect(trigger.className).toContain("focus-visible:outline-ring");
    await expectNoAxeViolations(container);
  });

  it("warns near the model's limit", () => {
    renderInApp(<ContextBudget segments={segments} maxTokens={1600} />);
    expect(screen.getByRole("button", { name: /94\s?%/ }).className).toContain("text-destructive");
  });
});

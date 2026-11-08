// @vitest-environment jsdom
import { cleanup, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";
import { ClassificationToken } from "./classification-token";

afterEach(cleanup);

describe("ClassificationToken", () => {
  it("shows the class with a shield and reads it as the space's security class", async () => {
    const { container } = renderInApp(<ClassificationToken name="Intern" />);
    const token = screen.getByText("Intern").parentElement!;
    expect(token.textContent).toBe("Säkerhetsklass: Intern");
    expect(token.querySelector("svg")?.getAttribute("aria-hidden")).toBe("true");
    await expectNoAxeViolations(container);
  });

  it("reads the same inline, in a line of supporting text", () => {
    renderInApp(<ClassificationToken name="Konfidentiell" variant="inline" />);
    expect(screen.getByText("Konfidentiell").parentElement!.textContent).toBe(
      "Säkerhetsklass: Konfidentiell"
    );
  });

  it("shows nothing for a space without a classification", () => {
    const { container } = renderInApp(<ClassificationToken name={null} />);
    expect(container.textContent).toBe("");
  });
});

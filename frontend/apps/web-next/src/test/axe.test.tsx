// @vitest-environment jsdom
import { cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { expectNoAxeViolations } from "./axe";

afterEach(cleanup);

// Guards the guard: a misconfigured helper (wrong tags, rules switched off)
// would pass every component silently.
describe("expectNoAxeViolations", () => {
  it("passes accessible markup", async () => {
    const { container } = render(
      <form>
        <label htmlFor="email">E-post</label>
        <input id="email" type="email" autoComplete="email" />
        <button type="submit">Logga in</button>
      </form>
    );
    await expectNoAxeViolations(container);
  });

  it("reports WCAG A violations with the rule id", async () => {
    const { container } = render(
      <div>
        <button type="button" />
        <input type="text" />
      </div>
    );
    await expect(expectNoAxeViolations(container)).rejects.toThrow(/button-name[\s\S]*label/);
  });

  it("reports WCAG 2.1 AA violations (1.3.5 input purpose)", async () => {
    const { container } = render(
      <>
        <label htmlFor="name">Namn</label>
        <input id="name" autoComplete="nickname-ish" />
      </>
    );
    await expect(expectNoAxeViolations(container)).rejects.toThrow(/autocomplete-valid/);
  });

  it("skips a rule only with a documented reason", async () => {
    const { container } = render(<input type="text" />);
    await expectNoAxeViolations(container, {
      disableRules: { label: "Covered by the surrounding fixture in this test" }
    });
  });
});

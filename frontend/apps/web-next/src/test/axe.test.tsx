// @vitest-environment jsdom
import { cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { expectNoAxeViolations } from "./axe";
import { assertDocumented } from "./wcag";

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

  it("skips a rule only with a reason and an issue link", async () => {
    const { container } = render(<input type="text" />);
    await expectNoAxeViolations(container, {
      disableRules: { label: "Labelled by the surrounding fixture, see #1234" }
    });
    await expectNoAxeViolations(container, {
      disableRules: {
        label: "Upstream Astryx bug https://github.com/facebook/astryx/issues/1"
      }
    });
  });

  it.each([
    ["an empty reason", ""],
    ["a blank reason", "   "],
    ["a reason without an issue", "Covered by the surrounding fixture"],
    ["a reason with a hash that is no issue", "Covered by the fixture #abc"],
    ["an issue without a reason", "#1234"],
    ["a bare link", "https://github.com/facebook/astryx/issues/1"]
  ])("refuses to skip a rule with %s", async (_case, reason) => {
    const { container } = render(<input type="text" />);
    await expect(
      expectNoAxeViolations(container, { disableRules: { label: reason } })
    ).rejects.toThrow(/needs a reason and an issue link/);
  });
});

// The page scans (tests/a11y.spec.ts) accept left-out regions and skipped
// rules on the same terms.
describe("assertDocumented", () => {
  const describeRegion = (selector: string) => `Leaving "${selector}" out of the page scan`;

  it("accepts every entry that has a reason and an issue link", () => {
    expect(() =>
      assertDocumented(
        {
          "#composer": "Astryx renders the dock twice, see facebook/astryx#12",
          ".tsqd-parent-container": "Dev tooling, see https://github.com/eneo-ai/eneo/issues/1"
        },
        describeRegion
      )
    ).not.toThrow();
  });

  it("names the entry that lacks one", () => {
    expect(() =>
      assertDocumented({ "#composer": "Astryx renders it twice" }, describeRegion)
    ).toThrow(
      'Leaving "#composer" out of the page scan needs a reason and an issue link ' +
        '(ACCESSIBILITY.md → Exceptions); got "Astryx renders it twice".'
    );
  });
});

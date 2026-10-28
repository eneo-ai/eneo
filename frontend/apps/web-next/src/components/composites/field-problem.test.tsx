// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { useState } from "react";
import { afterEach, expect, it } from "vitest";
import { FieldProblem, fieldProblemProps, revealProblems } from "./field-problem";

afterEach(cleanup);

/** What a screen reader meets the moment focus lands on `field`. */
function onFocus(field: HTMLElement) {
  const seen: { invalid: string | null; problem: string | null; detailsOpen: boolean | null } = {
    invalid: null,
    problem: null,
    detailsOpen: null
  };
  field.addEventListener("focus", () => {
    seen.invalid = field.getAttribute("aria-invalid");
    seen.problem =
      document.getElementById(field.getAttribute("aria-describedby") ?? "")?.textContent ?? null;
    seen.detailsOpen = field.closest("details")?.open ?? null;
  });
  return seen;
}

function Form({ inDetails = false }: { inDetails?: boolean }) {
  const [submitted, setSubmitted] = useState(false);
  const problem = submitted ? "Ange ett namn." : null;
  const field = (
    <>
      <label htmlFor="name">Namn</label>
      <input id="name" {...fieldProblemProps("name", problem)} />
      <FieldProblem id="name" problem={problem} />
    </>
  );
  return (
    <form>
      {inDetails ? (
        <details>
          <summary>Avancerat</summary>
          {field}
        </details>
      ) : (
        field
      )}
      <button type="button" onClick={() => revealProblems(() => setSubmitted(true), "name")}>
        Spara
      </button>
    </form>
  );
}

it("renders the problem before focus moves, so the field is read with it", () => {
  render(<Form />);
  const field = screen.getByRole("textbox", { name: "Namn" });
  const seen = onFocus(field);

  screen.getByRole("button", { name: "Spara" }).click();

  expect(document.activeElement).toBe(field);
  expect(seen.invalid).toBe("true");
  expect(seen.problem).toContain("Ange ett namn.");
});

it("opens a closed details around the field before focusing it", () => {
  const { container } = render(<Form inDetails />);
  const seen = onFocus(container.querySelector<HTMLElement>("#name")!);

  screen.getByRole("button", { name: "Spara" }).click();

  expect(seen.detailsOpen).toBe(true);
  expect(seen.invalid).toBe("true");
  expect(document.activeElement?.id).toBe("name");
});

it("hands a fieldset's focus to its first enabled input", () => {
  render(
    <fieldset id="role">
      <legend>Roll</legend>
      <input type="radio" aria-label="Läsare" disabled />
      <input type="radio" aria-label="Redaktör" />
    </fieldset>
  );

  revealProblems(() => {}, "role");

  expect(document.activeElement).toBe(screen.getByRole("radio", { name: "Redaktör" }));
});

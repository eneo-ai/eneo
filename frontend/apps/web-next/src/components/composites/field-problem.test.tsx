// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { useState } from "react";
import { afterEach, expect, it } from "vitest";
import { FieldProblem, fieldProblemProps, revealProblems } from "./field-problem";

afterEach(cleanup);

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

  screen.getByRole("button", { name: "Spara" }).click();

  const field = screen.getByRole("textbox", { name: "Namn" });
  expect(document.activeElement).toBe(field);
  expect(field.getAttribute("aria-invalid")).toBe("true");
  const describedBy = document.getElementById(field.getAttribute("aria-describedby") ?? "");
  expect(describedBy?.textContent).toContain("Ange ett namn.");
});

it("opens a closed details around the field before focusing it", () => {
  const { container } = render(<Form inDetails />);

  screen.getByRole("button", { name: "Spara" }).click();

  expect(container.querySelector("details")?.open).toBe(true);
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

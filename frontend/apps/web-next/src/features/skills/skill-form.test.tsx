// @vitest-environment jsdom
import { cleanup, fireEvent, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { renderInApp } from "@/test/render";
import { SkillForm } from "./skill-form";

afterEach(cleanup);

it("focuses the empty name field with its problem when an empty form is submitted", () => {
  const onSubmit = vi.fn(() => Promise.resolve());
  renderInApp(<SkillForm mode="create" onSubmit={onSubmit} />);
  const name = screen.getByRole("textbox", { name: "Namn" });
  // What a screen reader meets the moment focus lands on the field.
  const atFocus = { invalid: null as string | null, problem: null as string | null };
  name.addEventListener("focus", () => {
    const problemId = name.getAttribute("aria-describedby")?.split(" ")[0] ?? "";
    atFocus.invalid = name.getAttribute("aria-invalid");
    atFocus.problem = document.getElementById(problemId)?.textContent ?? null;
  });

  fireEvent.click(screen.getByRole("button", { name: "Skapa Skill" }));

  expect(document.activeElement).toBe(name);
  expect(atFocus.invalid).toBe("true");
  expect(atFocus.problem).toContain("Detta fält är obligatoriskt");
  expect(onSubmit).not.toHaveBeenCalled();
});

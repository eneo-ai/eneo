// @vitest-environment jsdom
import { cleanup, fireEvent, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { renderInApp } from "@/test/render";
import { SkillForm } from "./skill-form";

afterEach(cleanup);

it("focuses the empty name field with its problem when an empty form is submitted", () => {
  const onSubmit = vi.fn(() => Promise.resolve());
  renderInApp(<SkillForm mode="create" onSubmit={onSubmit} />);

  fireEvent.click(screen.getByRole("button", { name: "Skapa Skill" }));

  const name = screen.getByRole("textbox", { name: "Namn" });
  expect(document.activeElement).toBe(name);
  expect(name.getAttribute("aria-invalid")).toBe("true");
  const problem = document.getElementById(
    name.getAttribute("aria-describedby")?.split(" ")[0] ?? ""
  );
  expect(problem?.textContent).toContain("Detta fält är obligatoriskt");
  expect(onSubmit).not.toHaveBeenCalled();
});

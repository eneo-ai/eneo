// @vitest-environment jsdom
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeAll, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";

const api = vi.hoisted(() => ({ POST: vi.fn() }));
vi.mock("@/lib/api/browser", () => ({ browserApi: api }));

import { JustificationForm } from "./justification-form";

// Radix Select scrolls its selected option into view; jsdom has no layout.
beforeAll(() => {
  Element.prototype.scrollIntoView = () => {};
});
afterEach(() => vi.clearAllMocks());

it.each(["ctrlKey", "metaKey"])(
  "submits once with %s+Enter through the existing form",
  async (modifier) => {
    api.POST.mockReturnValue(new Promise(() => {}));
    renderInApp(<JustificationForm />);
    const reason = screen.getByRole("combobox", { name: "Åtkomstskäl" });
    const description = screen.getByLabelText("Detaljerad motivering");
    fireEvent.keyDown(description, { key: "Enter", [modifier]: true });
    expect(api.POST).not.toHaveBeenCalled();
    expect(document.activeElement).toBe(reason);
    fireEvent.keyDown(reason, { key: "Enter" });
    fireEvent.click(await screen.findByRole("option", { name: "Säkerhetsutredning" }));
    fireEvent.change(description, { target: { value: "Undersöker en testhändelse" } });
    fireEvent.keyDown(description, { key: "Enter" });
    expect(api.POST).not.toHaveBeenCalled();
    fireEvent.keyDown(description, { key: "Enter", [modifier]: true });
    await waitFor(() => expect(api.POST).toHaveBeenCalledTimes(1));
    fireEvent.keyDown(description, { key: "Enter", [modifier]: true });
    expect(api.POST).toHaveBeenCalledTimes(1);
    expect(api.POST).toHaveBeenCalledWith("/api/v1/audit/access-session", {
      body: { category: "security_investigation", description: "Undersöker en testhändelse" }
    });
  }
);

const problemOf = (control: HTMLElement) =>
  document.getElementById(control.getAttribute("aria-describedby") ?? "")?.textContent;

it("shows each problem at its field on submit, and moves focus to the first", async () => {
  const { container } = renderInApp(<JustificationForm />);
  const submit = screen.getByRole("button", { name: "Få åtkomst till loggar" });
  // Never disabled: a disabled button says nothing about what is missing.
  expect((submit as HTMLButtonElement).disabled).toBe(false);

  fireEvent.click(submit);
  const reason = screen.getByRole("combobox", { name: "Åtkomstskäl" });
  const description = screen.getByLabelText("Detaljerad motivering");
  expect(problemOf(reason)).toBe("Detta fält är obligatoriskt");
  expect(problemOf(description)).toBe("10 tecken till krävs");
  expect(document.activeElement).toBe(reason);
  await expectNoAxeViolations(container);

  fireEvent.keyDown(reason, { key: "Enter" });
  fireEvent.click(await screen.findByRole("option", { name: "Säkerhetsutredning" }));
  fireEvent.change(description, { target: { value: "Utreder" } });
  fireEvent.click(submit);
  expect(reason.getAttribute("aria-invalid")).toBeNull();
  expect(problemOf(description)).toBe("3 tecken till krävs");
  expect(document.activeElement).toBe(description);
  expect(api.POST).not.toHaveBeenCalled();
});

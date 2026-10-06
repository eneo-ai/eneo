// @vitest-environment jsdom
import { fireEvent, screen, within } from "@testing-library/react";
import { afterEach, beforeAll, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";

const api = vi.hoisted(() => ({
  GET: vi.fn(() => Promise.resolve({ data: { items: [] }, response: new Response("{}") })),
  POST: vi.fn()
}));
vi.mock("@/lib/api/browser", () => ({ browserApi: api }));

import { TemplateEditorDialog } from "./template-editor-dialog";

// Radix Select scrolls its selected option into view; jsdom has no layout.
beforeAll(() => {
  Element.prototype.scrollIntoView = () => {};
});
afterEach(() => vi.clearAllMocks());

it("shows each problem at its field on submit, and moves focus to the first", async () => {
  renderInApp(<TemplateEditorDialog kind="assistants" open onOpenChange={() => {}} />);
  const dialog = screen.getByRole("dialog", { name: "Ny mall" });
  const create = within(dialog).getByRole("button", { name: "Skapa" }) as HTMLButtonElement;
  // Never disabled: a disabled button says nothing about what is missing.
  expect(create.disabled).toBe(false);

  fireEvent.click(create);
  const name = within(dialog).getByLabelText("Mallnamn");
  const category = within(dialog).getByLabelText("Kategori");
  for (const field of [name, category]) {
    expect(field.getAttribute("aria-invalid")).toBe("true");
  }
  expect(document.activeElement).toBe(name);
  await expectNoAxeViolations(dialog);

  fireEvent.change(name, { target: { value: "Upphandlingsstöd" } });
  fireEvent.click(create);
  expect(name.getAttribute("aria-invalid")).toBeNull();
  expect(document.activeElement).toBe(category);
  expect(api.POST).not.toHaveBeenCalled();
});

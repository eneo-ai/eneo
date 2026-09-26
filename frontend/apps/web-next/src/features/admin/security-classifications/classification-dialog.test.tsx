// @vitest-environment jsdom
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";

const api = vi.hoisted(() => ({ POST: vi.fn() }));
vi.mock("@/lib/api/browser", () => ({ browserApi: api }));

import { ClassificationDialog } from "./classification-dialog";

afterEach(() => vi.clearAllMocks());

it("shows a missing name at the field on save, which takes focus, then creates", async () => {
  api.POST.mockReturnValue(new Promise(() => {}));
  renderInApp(<ClassificationDialog open onOpenChange={() => {}} />);
  const dialog = screen.getByRole("dialog", { name: "Skapa en ny säkerhetsklassificering" });
  const save = within(dialog).getByRole("button", { name: "Spara" }) as HTMLButtonElement;
  // Never disabled: a disabled button says nothing about what is missing.
  expect(save.disabled).toBe(false);

  fireEvent.click(save);
  const name = within(dialog).getByLabelText("Namn");
  expect(name.getAttribute("aria-invalid")).toBe("true");
  expect(document.getElementById(name.getAttribute("aria-describedby")!)?.textContent).toBe(
    "Detta fält är obligatoriskt"
  );
  expect(document.activeElement).toBe(name);
  expect(api.POST).not.toHaveBeenCalled();
  await expectNoAxeViolations(dialog);

  fireEvent.change(name, { target: { value: "Intern" } });
  fireEvent.click(save);
  await waitFor(() =>
    expect(api.POST).toHaveBeenCalledWith("/api/v1/security-classifications/", {
      body: { name: "Intern", description: "", set_lowest_security: true }
    })
  );
});

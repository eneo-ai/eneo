// @vitest-environment jsdom
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";

const api = vi.hoisted(() => ({ DELETE: vi.fn() }));
vi.mock("@/lib/api/browser", () => ({ browserApi: api }));

import { SharePointAppDeleteDialog } from "./sharepoint-app-delete-dialog";

afterEach(() => vi.clearAllMocks());

it("deletes only with DELETE typed, and says so at the labelled field otherwise", async () => {
  api.DELETE.mockReturnValue(new Promise(() => {}));
  renderInApp(<SharePointAppDeleteDialog open onOpenChange={() => {}} />);
  const dialog = screen.getByRole("dialog", { name: "Ta bort integration" });
  const field = within(dialog).getByRole("textbox", { name: "Skriv DELETE för att bekräfta" });
  const remove = within(dialog).getByRole("button", { name: "Permanent borttagning" });
  // Never disabled: deleting without the word says so at the field.
  expect((remove as HTMLButtonElement).disabled).toBe(false);

  fireEvent.click(remove);
  expect(field.getAttribute("aria-invalid")).toBe("true");
  expect(document.getElementById(field.getAttribute("aria-describedby")!)?.textContent).toBe(
    "Det stämmer inte. Skriv DELETE exakt som det står."
  );
  expect(document.activeElement).toBe(field);
  expect(api.DELETE).not.toHaveBeenCalled();
  await expectNoAxeViolations(dialog);

  fireEvent.change(field, { target: { value: "delete" } });
  fireEvent.click(remove);
  await waitFor(() => expect(api.DELETE).toHaveBeenCalledWith("/api/v1/admin/sharepoint/app"));
});

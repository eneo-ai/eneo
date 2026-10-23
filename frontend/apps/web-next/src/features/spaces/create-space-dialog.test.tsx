// @vitest-environment jsdom
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { useState } from "react";
import { afterEach, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";
import { CreateSpaceDialog } from "./create-space-dialog";

const router = vi.hoisted(() => ({ push: vi.fn() }));
const api = vi.hoisted(() => ({ POST: vi.fn() }));

vi.mock("next/navigation", () => ({ useRouter: () => router }));
vi.mock("@/lib/api/browser", () => ({ browserApi: api }));
vi.mock("sonner", () => ({ toast: { error: vi.fn(), success: vi.fn() } }));

function Harness() {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button type="button" onClick={() => setOpen(true)}>
        Ny yta
      </button>
      <CreateSpaceDialog open={open} onOpenChange={setOpen} />
    </>
  );
}

async function openDialog() {
  renderInApp(<Harness />);
  const opener = screen.getByRole("button", { name: "Ny yta" });
  opener.focus();
  fireEvent.click(opener);
  const dialog = await screen.findByRole("dialog", { name: "Skapa en ny yta" });
  return { opener, dialog };
}

afterEach(() => {
  cleanup();
  router.push.mockReset();
  api.POST.mockReset();
});

it("is a named modal form dialog with a labelled, required name field", async () => {
  renderInApp(<Harness />);
  // No Namn field in the page until the dialog opens.
  expect(screen.queryByLabelText(/Namn/)).toBeNull();

  fireEvent.click(screen.getByRole("button", { name: "Ny yta" }));
  const dialog = await screen.findByRole("dialog", { name: "Skapa en ny yta" });
  expect(dialog.getAttribute("aria-modal")).toBe("true");
  expect(within(dialog).getByLabelText(/Namn/).getAttribute("aria-required")).toBe("true");
  await expectNoAxeViolations(document.body);
});

it("explains how to fix an empty name at the field instead of submitting", async () => {
  const { dialog } = await openDialog();
  fireEvent.click(within(dialog).getByRole("button", { name: "Skapa yta" }));

  expect(await within(dialog).findByText(/Ange ett namn på ytan/)).toBeTruthy();
  const field = within(dialog).getByLabelText(/Namn/);
  expect(field.getAttribute("aria-invalid")).toBe("true");
  expect(document.activeElement).toBe(field);
  expect(api.POST).not.toHaveBeenCalled();
  await expectNoAxeViolations(dialog);
});

it("creates the space, opens its overview and leaves no form behind", async () => {
  api.POST.mockResolvedValue({ data: { id: "new-space" }, response: new Response(null) });
  const { dialog } = await openDialog();
  fireEvent.change(within(dialog).getByLabelText(/Namn/), { target: { value: "  Upphandling " } });
  fireEvent.click(within(dialog).getByRole("button", { name: "Skapa yta" }));

  await waitFor(() => expect(router.push).toHaveBeenCalledWith("/spaces/new-space/overview"));
  expect(api.POST).toHaveBeenCalledWith("/api/v1/spaces/", { body: { name: "Upphandling" } });
  expect(screen.queryByLabelText(/Namn/)).toBeNull();
});

it("keeps focus on the busy Skapa yta and ignores a second press", async () => {
  api.POST.mockReturnValue(new Promise(() => {}));
  const { dialog } = await openDialog();
  fireEvent.change(within(dialog).getByLabelText(/Namn/), { target: { value: "Upphandling" } });
  const create = within(dialog).getByRole("button", { name: "Skapa yta" });
  create.focus();

  fireEvent.click(create);

  await waitFor(() => expect(create.getAttribute("aria-busy")).toBe("true"));
  expect(create.hasAttribute("disabled")).toBe(false);
  expect(document.activeElement).toBe(create);
  fireEvent.click(create);
  expect(api.POST).toHaveBeenCalledTimes(1);
});

it("closes with Escape and returns focus to the opener", async () => {
  const { opener, dialog } = await openDialog();
  fireEvent.keyDown(dialog, { key: "Escape" });

  await waitFor(() => expect(dialog.hasAttribute("open")).toBe(false));
  expect(document.activeElement).toBe(opener);
  expect(screen.queryByLabelText(/Namn/)).toBeNull();
});

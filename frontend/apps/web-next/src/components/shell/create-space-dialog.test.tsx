// @vitest-environment jsdom
import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { useState } from "react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { CreateSpaceDialog } from "./create-space-dialog";
import { installBrowserMocks, renderWithProviders } from "./test-support";

const router = vi.hoisted(() => ({ push: vi.fn(), refresh: vi.fn() }));
const api = vi.hoisted(() => ({ POST: vi.fn() }));

vi.mock("next/navigation", () => ({ useRouter: () => router }));
vi.mock("@/lib/api/browser", () => ({ browserApi: api }));
vi.mock("sonner", () => ({ toast: { error: vi.fn(), success: vi.fn() } }));

function Harness() {
  const [open, setOpen] = useState(true);
  return (
    <>
      <button type="button" onClick={() => setOpen(true)}>
        öppna
      </button>
      <CreateSpaceDialog isOpen={open} onOpenChange={setOpen} />
    </>
  );
}

beforeEach(() => installBrowserMocks());
afterEach(() => {
  cleanup();
  router.push.mockReset();
  api.POST.mockReset();
});

it("is a named form dialog with a labelled, required name field", async () => {
  renderWithProviders(<Harness />);
  const dialog = screen.getByRole("dialog", { name: "Skapa en ny yta" });
  expect(dialog.getAttribute("aria-modal")).toBe("true");
  const name = screen.getByLabelText(/Namn/);
  expect(name.getAttribute("aria-required")).toBe("true");
  await expectNoAxeViolations(document.body);
});

it("explains how to fix an empty name instead of submitting", async () => {
  renderWithProviders(<Harness />);
  fireEvent.click(screen.getByRole("button", { name: "Skapa yta" }));
  expect(await screen.findByText(/Ange ett namn på ytan/)).toBeTruthy();
  expect(screen.getByLabelText(/Namn/).getAttribute("aria-invalid")).toBe("true");
  expect(api.POST).not.toHaveBeenCalled();
});

it("creates the space and opens its overview", async () => {
  api.POST.mockResolvedValue({ data: { id: "new-space" }, response: new Response(null) });
  renderWithProviders(<Harness />);
  fireEvent.change(screen.getByLabelText(/Namn/), { target: { value: "  Upphandling " } });
  fireEvent.click(screen.getByRole("button", { name: "Skapa yta" }));

  await waitFor(() => expect(router.push).toHaveBeenCalledWith("/spaces/new-space/overview"));
  expect(api.POST).toHaveBeenCalledWith("/api/v1/spaces/", { body: { name: "Upphandling" } });
  // The form is gone with the dialog: no stray "Namn" field left in the page.
  expect(screen.queryByLabelText(/Namn/)).toBeNull();
});

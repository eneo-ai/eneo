// @vitest-environment jsdom
import { act, cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { useState } from "react";
import { toast } from "sonner";
import { afterEach, describe, expect, it, vi } from "vitest";

// Vitest does not process CSS, so record that the Toaster imports it.
const stylesheet = vi.hoisted(() => ({ imported: false }));
vi.mock("sonner/dist/styles.css", () => {
  stylesheet.imported = true;
  return {};
});

import { renderInApp } from "@/test/render";
import { Dialog, DialogContent, DialogFooter, DialogTitle } from "./dialog";
import { Toaster } from "./sonner";
import type { Box } from "./toast-lift";

afterEach(() => {
  // Unmount the toasters: each unsubscribes from sonner's store and its
  // toasts' timers stop, so no React work runs after the test.
  cleanup();
  // Sonner's store is module-wide and replays the toasts still showing to
  // the next Toaster that subscribes: dismiss them, so none outlives its test.
  toast.dismiss();
  vi.restoreAllMocks();
});

it("styles toasts from the bundled stylesheet instead of an injected <style>", async () => {
  // The Toaster reads its labels from next-intl, so render it in the app providers.
  renderInApp(<Toaster theme="light" />);
  toast("Sparat");

  expect(await screen.findByText("Sparat")).toBeTruthy();
  expect(stylesheet.imported).toBe(true);
  // The nonce-based style-src CSP (src/proxy.ts) blocks and reports every
  // <style> without the request nonce, so Sonner must not inject one. After a
  // sonner upgrade bun silently skips the stale frontend/patches/sonner@*.patch;
  // recreate it for the new version with `bun patch sonner`.
  expect(document.querySelectorAll("style")).toHaveLength(0);
});

it("finds open dialogs without watching every DOM change on the page", () => {
  // A body-wide MutationObserver ran on each streamed chat token; dialogs
  // report themselves instead (open-modals.ts).
  const observe = vi.spyOn(MutationObserver.prototype, "observe");
  renderInApp(<Toaster theme="light" />);
  expect(observe).not.toHaveBeenCalledWith(
    document.body,
    expect.objectContaining({ subtree: true })
  );
});

it("leaves no toaster or toast behind for the next test", async () => {
  // Runs after the tests above, which showed "Sparat".
  expect(screen.queryByRole("region", { name: /Aviseringar/ })).toBeNull();
  renderInApp(<Toaster theme="light" />);
  // A new Toaster takes over the toasts still in sonner's store a task later.
  await act(() => new Promise((resolve) => setTimeout(resolve, 0)));
  expect(screen.queryByText("Sparat")).toBeNull();
});

/** Lays `element` out at `box` in the viewport (jsdom has no layout). */
function place(element: Element, { left, top, right, bottom }: Box) {
  const rect = {
    left,
    top,
    right,
    bottom,
    x: left,
    y: top,
    width: right - left,
    height: bottom - top
  };
  vi.spyOn(element, "getBoundingClientRect").mockReturnValue({ ...rect, toJSON: () => rect });
}

/**
 * Finds the toast showing `text` (in `scope`) and lays its list out where
 * sonner rests it in the 1280 × 800 test window: a 356 × 73 px toast 24 px from
 * the bottom right corner (x 900–1256, y 703–776). Then, as in a browser, it
 * has slid into place. Returns sonner's list.
 */
async function restingToast(text: string, scope: Pick<typeof screen, "findByText"> = screen) {
  const toastElement = (await scope.findByText(text)).closest<HTMLElement>("[data-sonner-toast]")!;
  const list = toastElement.closest<HTMLElement>("[data-sonner-toaster]")!;
  place(list, { left: 900, right: 1256, top: 776, bottom: 776 });
  for (const [name, value] of Object.entries({
    offsetLeft: 0,
    offsetWidth: 356,
    offsetHeight: 73
  })) {
    Object.defineProperty(toastElement, name, { configurable: true, value });
  }
  fireEvent.transitionEnd(toastElement);
  return list;
}

// WCAG 2.4.11: errors and warnings stay until closed, at the bottom edge where
// dialogs keep their primary button and the chat docks its composer.
describe("the toasts never cover what has keyboard focus", () => {
  it("rise above a focused element they would cover, and settle back once focus moves on", async () => {
    renderInApp(
      <>
        <Toaster theme="light" />
        <button type="button">Sök</button>
        <button type="button">Spara ändringar</button>
      </>
    );
    toast.error("Det gick inte att spara ändringarna.");
    const list = await restingToast("Det gick inte att spara ändringarna.");
    // A save bar's button in the bottom right corner, under the toasts.
    const save = screen.getByRole("button", { name: "Spara ändringar" });
    place(save, { left: 1125, right: 1256, top: 752, bottom: 788 });
    const search = screen.getByRole("button", { name: "Sök" });
    place(search, { left: 24, right: 90, top: 24, bottom: 60 });

    act(() => save.focus());
    // Their lower edge 8 px above the button: clear of its focus outline.
    await waitFor(() => expect(list.style.translate).toBe("0 -32px"));

    act(() => search.focus());
    await waitFor(() => expect(list.style.translate).toBe(""));
  });

  it("hold still while focus is in them", async () => {
    renderInApp(
      <>
        <Toaster theme="light" />
        <button type="button">Spara ändringar</button>
      </>
    );
    toast.error("Det gick inte att spara ändringarna.");
    const list = await restingToast("Det gick inte att spara ändringarna.");
    const save = screen.getByRole("button", { name: "Spara ändringar" });
    place(save, { left: 1125, right: 1256, top: 752, bottom: 788 });
    act(() => save.focus());
    await waitFor(() => expect(list.style.translate).toBe("0 -32px"));

    act(() => screen.getByRole("button", { name: "Stäng aviseringen" }).focus());
    await act(() => new Promise((resolve) => requestAnimationFrame(resolve)));

    expect(list.style.translate).toBe("0 -32px");
  });

  it("clear the whole group focus is in, such as the chat composer's Send while the user types", async () => {
    renderInApp(
      <>
        <Toaster theme="light" />
        <div data-clear-of-toasts="">
          <textarea aria-label="Meddelande" />
          <button type="button">Skicka meddelande</button>
        </div>
      </>
    );
    toast.error("rapport.exe: Filtypen stöds inte");
    const list = await restingToast("rapport.exe: Filtypen stöds inte");
    const field = screen.getByRole("textbox", { name: "Meddelande" });
    // The text field is clear of the toasts; the composer's button row is not.
    place(field, { left: 312, right: 890, top: 700, bottom: 740 });
    place(field.parentElement!, { left: 312, right: 968, top: 700, bottom: 790 });

    act(() => field.focus());

    await waitFor(() => expect(list.style.translate).toBe("0 -84px"));
  });

  it("rise above a dialog's primary button, in the toaster inside the dialog", async () => {
    function EditDialog() {
      const [open, setOpen] = useState(true);
      return (
        <Dialog open={open} onOpenChange={setOpen}>
          <DialogContent>
            <DialogTitle>Redigera assistent</DialogTitle>
            <DialogFooter>
              <button type="button" onClick={() => toast.error("Det gick inte att spara.")}>
                Spara
              </button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      );
    }
    renderInApp(
      <>
        <Toaster theme="light" />
        <EditDialog />
      </>
    );
    const dialog = await screen.findByRole("dialog", { name: "Redigera assistent" });
    await waitFor(() =>
      expect(within(dialog).getByRole("region", { name: /Aviseringar/ })).toBeTruthy()
    );
    const save = within(dialog).getByRole("button", { name: "Spara" });
    // A tall, wide dialog: the primary button in its footer is under the toasts.
    place(save, { left: 1000, right: 1240, top: 740, bottom: 784 });
    act(() => save.focus());

    act(() => save.click());

    const list = await restingToast("Det gick inte att spara.", within(dialog));
    await waitFor(() => expect(list.style.translate).toBe("0 -44px"));
  });
});

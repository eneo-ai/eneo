// @vitest-environment jsdom
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Toaster } from "@/components/ui/sonner";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";
import { SecretRevealDialog } from "./secret-reveal";

const SECRET = "example-secret-value-for-clipboard-test";
const writeText = vi.fn<(text: string) => Promise<void>>();

beforeEach(() => {
  Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText } });
});

afterEach(() => {
  cleanup();
  writeText.mockReset();
});

async function openDialog() {
  const onClose = vi.fn();
  renderInApp(
    <>
      <Toaster />
      <SecretRevealDialog title="Ny API-nyckel" secret={SECRET} onClose={onClose} />
    </>
  );
  const dialog = await screen.findByRole("dialog", { name: "Ny API-nyckel" });
  return { dialog, onClose };
}

describe("SecretRevealDialog", () => {
  it("shows the whole key without scrolling and announces the copy inside the dialog", async () => {
    writeText.mockResolvedValue();
    const { dialog } = await openDialog();

    // Wraps instead of overflowing, so no keyboard-unreachable scroll area.
    const key = within(dialog).getByText(SECRET);
    expect(key.className).toContain("break-all");
    expect(key.className).not.toContain("overflow-x-auto");

    fireEvent.click(within(dialog).getByRole("button", { name: "Kopiera till urklipp" }));

    await waitFor(() => expect(writeText).toHaveBeenCalledWith(SECRET));
    // Astryx's polite live region, moved into the modal so it is not inert.
    await waitFor(() =>
      expect(dialog.querySelector('[data-astryx-live-region="polite"]')?.textContent).toBe(
        "Kopierat till urklipp"
      )
    );
    await expectNoAxeViolations(document.body);
  });

  it("says so when the browser refuses the clipboard", async () => {
    writeText.mockRejectedValue(new DOMException("denied", "NotAllowedError"));
    const { dialog } = await openDialog();
    const button = within(dialog).getByRole("button", { name: "Kopiera till urklipp" });

    fireEvent.click(button);

    const message = await within(dialog).findByText(
      "Det gick inte att kopiera. Markera nyckeln och kopiera den själv."
    );
    expect(button.getAttribute("aria-describedby")).toContain(message.id);
    await expectNoAxeViolations(document.body);
  });

  it("closes from Klar", async () => {
    const { dialog, onClose } = await openDialog();
    fireEvent.click(within(dialog).getByRole("button", { name: "Klar" }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});

// @vitest-environment jsdom
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { API_BASE } from "@/lib/api/base";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";
import { AttachmentPreviewDialog, ComposerAttachments } from "./attachments";
import type { Attachment } from "./use-attachments";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("signed file previews", () => {
  it("shows a proxied PDF through a blob frame and revokes it when closed", async () => {
    const url = `${API_BASE}/api/v1/files/file-1/download/?token=signed-value`;
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(new Response(new Blob(["%PDF"], { type: "application/pdf" })));
    const createObjectURL = vi.fn(() => "blob:preview-pdf");
    const revokeObjectURL = vi.fn();
    const previousCreate = URL.createObjectURL;
    const previousRevoke = URL.revokeObjectURL;
    Object.assign(URL, { createObjectURL, revokeObjectURL });

    try {
      const { unmount } = renderInApp(
        <AttachmentPreviewDialog
          open
          onOpenChange={vi.fn()}
          name="Policy.pdf"
          mimetype="application/pdf"
          url={url}
        />
      );
      const dialog = await screen.findByRole("dialog", { name: "Policy.pdf" });
      await waitFor(() =>
        expect(within(dialog).getByTitle("Policy.pdf").getAttribute("src")).toBe("blob:preview-pdf")
      );
      expect(fetchMock).toHaveBeenCalledWith(url, { signal: expect.any(AbortSignal) });
      expect(createObjectURL).toHaveBeenCalledOnce();
      unmount();
      expect(revokeObjectURL).toHaveBeenCalledWith("blob:preview-pdf");
    } finally {
      cleanup();
      Object.assign(URL, { createObjectURL: previousCreate, revokeObjectURL: previousRevoke });
    }
  });

  it("offers a download when the PDF cannot be rendered", async () => {
    const url = `${API_BASE}/api/v1/files/file-1/download/?token=signed-value`;
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(null, { status: 503 }));
    renderInApp(
      <AttachmentPreviewDialog
        open
        onOpenChange={vi.fn()}
        name="Policy.pdf"
        mimetype="application/pdf"
        url={url}
      />
    );

    const dialog = await screen.findByRole("dialog", { name: "Policy.pdf" });
    const download = await within(dialog).findByRole("link", { name: "Ladda ner" });
    expect(download.getAttribute("href")).toBe(url);
    expect(
      within(dialog).getByText("Det gick inte att läsa in innehållet. Försök igen.")
    ).toBeTruthy();
    await expectNoAxeViolations(dialog);
  });
});

describe("ComposerAttachments", () => {
  const attachment = (index: number, uploading = false): Attachment => ({
    key: `key-${index}`,
    fileId: uploading ? undefined : `file-${index}`,
    name: `Policy ${index}.pdf`,
    size: 2_048,
    mimetype: "application/pdf",
    uploading
  });

  it("shows one or two attachments as chips with a named remove button", async () => {
    const removeAttachment = vi.fn();
    const { container } = renderInApp(
      <ComposerAttachments
        attachments={{
          attachments: [attachment(1), attachment(2, true)],
          removeAttachment
        }}
      />
    );
    const list = screen.getByRole("list", { name: "2 bilagor bifogade" });
    expect(within(list).getAllByRole("listitem")).toHaveLength(2);
    expect(within(list).getByText("PDF · 2 kB")).toBeTruthy();
    expect(within(list).getByText("Laddar upp…")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Ta bort alla bilagor" })).toBeNull();
    fireEvent.click(within(list).getByRole("button", { name: "Ta bort Policy 2.pdf" }));
    expect(removeAttachment).toHaveBeenCalledWith("key-2");
    await expectNoAxeViolations(container);
  });

  it("folds three or more into a summary row with the progress that unfolds on request", async () => {
    const removeAttachment = vi.fn();
    const items = [attachment(1), attachment(2, true), attachment(3, true)];
    const { container } = renderInApp(
      <ComposerAttachments attachments={{ attachments: items, removeAttachment }} />
    );
    expect(screen.getByText("3 bilagor bifogade")).toBeTruthy();
    expect(screen.getByText("· 6 kB")).toBeTruthy();
    expect(screen.getByText("1 av 3 klara")).toBeTruthy();
    expect(
      screen.getByRole("progressbar", { name: "Laddar upp…" }).getAttribute("aria-valuenow")
    ).toBe("1");
    expect(screen.queryByRole("list")).toBeNull();

    const show = screen.getByRole("button", { name: "Visa" });
    expect(show.getAttribute("aria-expanded")).toBe("false");
    fireEvent.click(show);
    expect(show.getAttribute("aria-expanded")).toBe("true");
    expect(show.textContent).toContain("Dölj");
    expect(
      within(screen.getByRole("list", { name: "3 bilagor bifogade" })).getAllByRole("listitem")
    ).toHaveLength(3);

    fireEvent.click(screen.getByRole("button", { name: "Ta bort alla bilagor" }));
    expect(removeAttachment.mock.calls.map(([key]) => key)).toEqual(items.map((item) => item.key));
    await expectNoAxeViolations(container);
  });
});

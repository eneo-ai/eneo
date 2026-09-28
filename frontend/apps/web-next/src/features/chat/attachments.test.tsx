// @vitest-environment jsdom
import { cleanup, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";
import { AttachmentPreviewDialog, proxiedFileDownloadUrl } from "./attachments";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("signed file previews", () => {
  it("keeps the signed token on the same-origin API proxy", () => {
    expect(
      proxiedFileDownloadUrl(
        "http://backend:8123/api/v1/files/file-1/download/?token=signed-value",
        "file-1"
      )
    ).toBe("/api/eneo/api/v1/files/file-1/download/?token=signed-value");
    expect(() =>
      proxiedFileDownloadUrl("https://example.org/other?token=signed-value", "file-1")
    ).toThrow("Unexpected signed file URL");
  });

  it("shows a proxied PDF through a blob frame and revokes it when closed", async () => {
    const url = "/api/eneo/api/v1/files/file-1/download/?token=signed-value";
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
    const url = "/api/eneo/api/v1/files/file-1/download/?token=signed-value";
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

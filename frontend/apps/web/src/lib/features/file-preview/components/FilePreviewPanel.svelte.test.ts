import { page, userEvent } from "@vitest/browser/context";
import { render } from "vitest-browser-svelte";
import { expect, it, vi } from "vitest";
import { m } from "$lib/paraglide/messages";
import { FilePreview, type DocumentExport } from "../FilePreview.svelte";
import FilePreviewPanel from "./FilePreviewPanel.svelte";

vi.mock("$lib/features/attachments/AttachmentUrlService.svelte", () => ({
  getAttachmentUrlService: () => ({ getOriginalUrl: () => "/original" })
}));
vi.mock("../loadPreview", () => ({
  loadPreview: async () => ({ kind: "text", text: "Report text", truncated: false }),
  PreviewTooLargeError: class extends Error {}
}));
const file = { id: "report", name: "Report.md", mimetype: "text/markdown", size: 20 };
const yes = { available: true };
const no = { available: false, reason: "format_unsupported" as const };

async function setup(availability: DocumentExport["availability"]) {
  const preview = new FilePreview({ resolveOriginalUrl: async () => "/original" } as never);
  preview.besideConversation = true;
  preview.open(file);
  await vi.waitFor(() => expect(preview.status).toBe("ready"));
  render(FilePreviewPanel, {
    preview,
    versionsOf: () => [file],
    exportOf: () => ({ availability, exportAs: vi.fn() })
  });
  return preview;
}

it("checks on each opening and enables only supported formats", async () => {
  const availability = vi
    .fn()
    .mockResolvedValueOnce({ docx: yes, pdf: no })
    .mockResolvedValueOnce({ docx: no, pdf: yes });
  await setup(availability);
  await page.getByRole("button", { name: m.file_preview_export(), exact: true }).click();
  await expect
    .element(page.getByRole("menuitem", { name: /Word/ }))
    .not.toHaveAttribute("data-disabled");
  await expect
    .element(page.getByRole("menuitem", { name: /PDF/ }))
    .toHaveAttribute("data-disabled");
  await expect.element(page.getByText(m.file_preview_export_format_unsupported())).toBeVisible();
  await userEvent.keyboard("{Escape}");
  await page.getByRole("button", { name: m.file_preview_export(), exact: true }).click();
  await expect
    .element(page.getByRole("menuitem", { name: /Word/ }))
    .toHaveAttribute("data-disabled");
  await expect
    .element(page.getByRole("menuitem", { name: /PDF/ }))
    .not.toHaveAttribute("data-disabled");
  expect(availability).toHaveBeenCalledTimes(2);
});

it("keeps Markdown available after a failed check and supports retry", async () => {
  const availability = vi
    .fn()
    .mockRejectedValueOnce(new Error("offline"))
    .mockResolvedValueOnce({ docx: yes, pdf: yes });
  await setup(availability);
  await page.getByRole("button", { name: m.file_preview_export(), exact: true }).click();
  await expect.element(page.getByText(m.file_preview_export_check_failed())).toBeVisible();
  await expect
    .element(page.getByRole("menuitem", { name: /Markdown/ }))
    .not.toHaveAttribute("data-disabled");
  await page.getByRole("menuitem", { name: m.retry() }).click();
  await expect
    .element(page.getByRole("menuitem", { name: /Word/ }))
    .not.toHaveAttribute("data-disabled");
});

it("discards pending availability when the displayed version changes", async () => {
  let oldResult!: (value: { docx: typeof yes; pdf: typeof yes }) => void;
  const availability = vi
    .fn()
    .mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          oldResult = resolve;
        })
    )
    .mockResolvedValue({ docx: no, pdf: no });
  const preview = await setup(availability);
  await page.getByRole("button", { name: m.file_preview_export(), exact: true }).click();
  await vi.waitFor(() => expect(availability).toHaveBeenCalledTimes(1));
  preview.open({ ...file, id: "revision" });
  await vi.waitFor(() => expect(availability).toHaveBeenCalledTimes(2));
  oldResult({ docx: yes, pdf: yes });
  await expect
    .element(page.getByRole("menuitem", { name: /Word/ }))
    .toHaveAttribute("data-disabled");
});

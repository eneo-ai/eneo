import { page, userEvent } from "@vitest/browser/context";
import { render } from "vitest-browser-svelte";
import { expect, it, vi } from "vitest";
import { m } from "$lib/paraglide/messages";
import { FilePreview, type DocumentExport } from "../FilePreview.svelte";
import { loadPreview } from "../loadPreview";
import FilePreviewPanel from "./FilePreviewPanel.svelte";

vi.mock("$lib/features/attachments/AttachmentUrlService.svelte", () => ({
  getAttachmentUrlService: () => ({
    getOriginalUrl: () => "/original",
    resolveUrl: async () => "/image"
  })
}));
vi.mock("../loadPreview", () => ({
  loadPreview: vi.fn(async () => ({ kind: "text", text: "Report text", truncated: false })),
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

async function setupDocument(truncated: boolean) {
  vi.mocked(loadPreview).mockResolvedValueOnce({ kind: "markdown", text: "# Del\n", truncated });
  const preview = new FilePreview({ resolveOriginalUrl: async () => "/original" } as never);
  preview.besideConversation = true;
  preview.open(file);
  await vi.waitFor(() => expect(preview.status).toBe("ready"));
  render(FilePreviewPanel, {
    preview,
    versionsOf: () => [file],
    saverOf: () => ({ save: vi.fn() })
  });
}

/** The editor's text surface, once it is on the page. */
const editorSurface = () =>
  vi.waitFor(() => {
    const surface = document.querySelector(".ProseMirror");
    expect(surface).not.toBeNull();
    return surface as HTMLElement;
  });

it("lets the reader edit a whole document", async () => {
  await setupDocument(false);
  const surface = await editorSurface();
  await vi.waitFor(() => expect(surface.getAttribute("contenteditable")).toBe("true"));
});

it("keeps a document cut short by the preview read-only", async () => {
  await setupDocument(true);
  await expect.element(page.getByText(m.file_preview_text_truncated())).toBeVisible();
  const surface = await editorSurface();
  await vi.waitFor(() => expect(surface.getAttribute("contenteditable")).toBe("false"));
});

async function editDocument(text: string) {
  const surface = await editorSurface();
  surface.focus();
  await userEvent.keyboard("{ControlOrMeta>}a{/ControlOrMeta}");
  await userEvent.keyboard(text);
}

it.each(["other-document", file.id])(
  "keeps edits in %s after leaving a document whose save is still pending",
  async (nextId) => {
    const preview = new FilePreview({ resolveOriginalUrl: async () => "/original" } as never);
    preview.saved(file, "Original document");
    let complete!: (version: typeof file) => void;
    const save = vi.fn(() => new Promise<typeof file>((resolve) => (complete = resolve)));
    const firstPanel = render(FilePreviewPanel, {
      preview,
      saverOf: () => ({ save })
    });
    await editDocument("First edit");
    await vi.waitFor(() => expect(preview.dirty).toBe(true));
    await page.getByRole("button", { name: m.save(), exact: true }).click();
    await vi.waitFor(() => expect(save).toHaveBeenCalledOnce());

    preview.close();
    preview.pendingDiscard?.proceed();
    await firstPanel.unmount();
    const next = { ...file, id: nextId };
    if (nextId !== file.id) {
      vi.mocked(loadPreview).mockResolvedValueOnce({
        kind: "markdown",
        text: "Original document",
        truncated: false
      });
    }
    preview.open(next);
    await vi.waitFor(() => expect(preview.status).toBe("ready"));
    render(FilePreviewPanel, { preview, saverOf: () => ({ save: vi.fn() }) });
    await editDocument("Keep this edit");
    await vi.waitFor(() => expect(preview.dirty).toBe(true));

    complete({ ...file, id: "saved-version" });
    await save.mock.results[0]!.value;
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(preview.file?.id).toBe(nextId);
    // The edited text follows the keystrokes a moment later.
    await vi.waitFor(() => expect(preview.editsOf(next)).toContain("Keep this edit"));
    expect(preview.dirty).toBe(true);
    expect((await editorSurface()).textContent).toContain("Keep this edit");
  }
);

it("keeps the same document read-only through a panel remount until its save completes", async () => {
  const preview = new FilePreview({ resolveOriginalUrl: async () => "/original" } as never);
  preview.saved(file, "Original document");
  let complete!: (version: typeof file) => void;
  const save = vi.fn(() => new Promise<typeof file>((resolve) => (complete = resolve)));
  const saverOf = () => ({ save });
  const firstPanel = render(FilePreviewPanel, { preview, saverOf });
  await editDocument("Saved edit");
  await vi.waitFor(() => expect(preview.dirty).toBe(true));
  await page.getByRole("button", { name: m.save(), exact: true }).click();
  await vi.waitFor(() => expect(save).toHaveBeenCalledOnce());

  // Crossing the responsive breakpoint remounts the panel without leaving its document.
  await firstPanel.unmount();
  render(FilePreviewPanel, { preview, saverOf });
  const surface = await editorSurface();
  await vi.waitFor(() => expect(surface.getAttribute("contenteditable")).toBe("false"));

  complete({ ...file, id: "saved-version" });
  await vi.waitFor(() => expect(preview.file?.id).toBe("saved-version"));
  expect(preview.dirty).toBe(false);
  expect((await editorSurface()).textContent).toContain("Saved edit");
});

it("shows the assistant's ready replacement after undo returns to the original text", async () => {
  const preview = new FilePreview({ resolveOriginalUrl: async () => "/original" } as never);
  preview.saved(file, "Original document");
  render(FilePreviewPanel, { preview, saverOf: () => ({ save: vi.fn() }) });
  await editDocument("Modified document");
  await vi.waitFor(() => expect(preview.dirty).toBe(true));
  vi.mocked(loadPreview).mockResolvedValueOnce({
    kind: "markdown",
    text: "Assistant replacement",
    truncated: false
  });
  preview.arrive({ ...file, id: "assistant-version" });
  await vi.waitFor(() => expect(document.querySelectorAll(".ProseMirror")).toHaveLength(2));
  expect(preview.file?.id).toBe(file.id);

  await userEvent.keyboard("{ControlOrMeta>}z{/ControlOrMeta}");

  await vi.waitFor(() => expect(preview.file?.id).toBe("assistant-version"));
  expect(preview.dirty).toBe(false);
  expect((await editorSurface()).textContent).toContain("Assistant replacement");
});

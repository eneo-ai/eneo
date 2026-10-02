import { page, userEvent } from "vitest/browser";
import { render } from "vitest-browser-svelte";
import { expect, it, vi } from "vitest";
import { m } from "$lib/paraglide/messages";
import { FilePreview } from "../FilePreview.svelte";
import type { PanelContents } from "../panelContents";
import Harness from "./FilePreviewLayoutHarness.svelte";

vi.mock("$lib/features/attachments/AttachmentUrlService.svelte", () => ({
  getAttachmentUrlService: () => ({ getOriginalUrl: () => "/original" })
}));
vi.mock("../loadPreview", () => ({
  loadPreview: async () => ({ kind: "text", text: "Report text", truncated: false }),
  PreviewTooLargeError: class extends Error {}
}));
const file = { id: "report", name: "Report.txt", mimetype: "text/plain", size: 20 };
const contents: PanelContents = { documents: [], uploads: [file], views: [] };
const launcher = () =>
  page.getByRole("button", { name: m.conversation_panel_open(), includeHidden: true });

async function setup(items = contents, width = 1100) {
  await page.viewport(width, 800);
  const preview = new FilePreview({ resolveOriginalUrl: async () => "/original" } as never);
  render(Harness, { preview, contents: items });
  await vi.waitFor(() => expect(preview.besideConversation).toBe(width >= 720));
  return preview;
}

it("opens the sidebar overview directly and returns keyboard focus on Escape", async () => {
  await setup();
  await launcher().click();
  await expect
    .element(page.getByRole("complementary", { name: m.conversation_panel_title() }))
    .toBeVisible();
  await expect.element(launcher()).not.toBeVisible();
  await expect
    .element(page.getByRole("button", { name: m.file_preview_open({ name: file.name }) }))
    .toBeVisible();
  await userEvent.keyboard("{Escape}");
  await expect.element(launcher()).toBeVisible();
  await expect.element(launcher()).toHaveFocus();
});

it("replaces the overview with the chosen file and closes without leaving an empty panel", async () => {
  const preview = await setup();
  await launcher().click();
  await page.getByRole("button", { name: m.file_preview_open({ name: file.name }) }).click();
  await expect.element(page.getByText("Report text")).toBeVisible();
  expect(preview.file?.id).toBe(file.id);
  await expect.element(page.getByRole("complementary")).toHaveFocus();
  await userEvent.keyboard("{Escape}");
  await expect.element(launcher()).toBeVisible();
  await expect.element(launcher()).toHaveFocus();
  expect(preview.shown).toBe(false);
});

it("makes a conversation with only interactive views reachable", async () => {
  await setup({
    documents: [],
    uploads: [],
    views: [{ id: "chart", title: "Budget chart", subject: null, shown: false, open: vi.fn() }]
  });
  await launcher().click();
  await page.getByRole("button", { name: /Budget chart/ }).click();
  await expect.element(page.getByText("Budget chart", { exact: true })).toBeVisible();
  await expect.element(launcher()).not.toBeVisible();
  await page.getByRole("button", { name: m.close(), exact: true }).click();
  await expect.element(launcher()).toBeVisible();
});

it("opens a narrow-screen sheet and keeps download-only files accessible", async () => {
  const archive = { ...file, name: "Archive.zip", mimetype: "application/zip" };
  await setup({ documents: [], uploads: [archive], views: [] }, 390);
  await launcher().click();
  await expect
    .element(page.getByRole("dialog", { name: m.conversation_panel_title() }))
    .toBeVisible();
  await expect
    .element(page.getByRole("link", { name: m.generated_file_download({ name: archive.name }) }))
    .toHaveAttribute("download", archive.name);
  await page.getByRole("button", { name: m.conversation_panel_close() }).click();
  await expect.element(launcher()).toBeVisible();
  await expect.element(launcher()).toHaveFocus();
});

it("does not offer an empty sidebar", async () => {
  await setup({ documents: [], uploads: [], views: [] });
  await expect.element(launcher()).not.toBeInTheDocument();
});

for (const width of [1100, 390]) {
  it(`returns from a file to the overview without closing the panel at ${width}px`, async () => {
    const preview = await setup(contents, width);
    await launcher().click();
    const overviewHeight = page
      .getByRole("heading", { name: m.conversation_panel_title() })
      .element()
      .closest("header")!
      .getBoundingClientRect().height;
    await page.getByRole("button", { name: m.file_preview_open({ name: file.name }) }).click();
    const fileHeaderHeight = page
      .getByRole("button", { name: m.conversation_panel_back() })
      .element()
      .closest("header")!
      .getBoundingClientRect().height;
    expect(fileHeaderHeight).toBe(overviewHeight);
    await page.getByRole("button", { name: m.conversation_panel_back() }).click();
    await expect
      .element(page.getByRole("heading", { name: m.conversation_panel_title() }))
      .toBeVisible();
    await expect.element(launcher()).not.toBeVisible();
    expect(preview.shown).toBe(false);
    await page.getByRole("button", { name: m.file_preview_open({ name: file.name }) }).click();
    await expect.element(page.getByText("Report text")).toBeVisible();
  });
}

it("returns from an interactive view to the overview", async () => {
  await setup({
    documents: [],
    uploads: [],
    views: [{ id: "chart", title: "Budget chart", subject: null, shown: false, open: vi.fn() }]
  });
  await launcher().click();
  await page.getByRole("button", { name: /Budget chart/ }).click();
  await page.getByRole("button", { name: m.conversation_panel_back() }).click();
  await expect
    .element(page.getByRole("heading", { name: m.conversation_panel_title() }))
    .toBeVisible();
  await expect.element(page.getByRole("button", { name: /Budget chart/ })).toBeVisible();
  await expect.element(launcher()).not.toBeVisible();
});

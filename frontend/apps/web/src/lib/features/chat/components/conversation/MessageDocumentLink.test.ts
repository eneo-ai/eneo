import { beforeEach, expect, it, vi } from "vitest";
import { render } from "svelte/server";
import { Markdown } from "$lib/components/markdown/index";
import MessageDocumentLink from "./MessageDocumentLink.svelte";
const preview = vi.hoisted(() => ({
  current: { open: vi.fn() } as { open: ReturnType<typeof vi.fn> } | undefined
}));
vi.mock("$lib/features/file-preview/FilePreview.svelte", () => ({
  getFilePreview: () => preview.current
}));
beforeEach(() => {
  preview.current = { open: vi.fn() };
});
vi.mock("../../ChatService.svelte", () => ({
  getChatService: () => ({ documents: { documents: [] } })
}));
vi.mock("../../MessageContext.svelte", () => ({
  getMessageContext: () => ({
    current: () => ({
      generated_files: [
        {
          id: "report",
          name: "report.xlsx",
          mimetype: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
          size: 100
        }
      ]
    })
  })
}));
vi.mock("$lib/features/attachments/AttachmentUrlService.svelte", () => ({
  getAttachmentUrlService: () => ({
    getOriginalUrl: () => "https://eneo.example/download?token=test"
  })
}));
it.each([
  "The workbook is ready: report.xlsx",
  "Open [report.xlsx](https://foreign.example/guessed)",
  "Ladda ner: report.xlsx"
])("opens a preview instead of downloading for %s", (source) => {
  const { body } = render(Markdown, {
    props: { source, fileNames: ["report.xlsx"], customRenderers: { file: MessageDocumentLink } }
  });
  expect(body).toContain('type="button"');
  expect(body).not.toContain("download=");
  expect(body).not.toContain("foreign.example");
  expect(body.match(/<button\s/g)).toHaveLength(1);
  expect(body.match(/<a\s/g)).toBeNull();
});
it("offers a real file download in a read-only transcript without a preview panel", () => {
  preview.current = undefined;
  const { body } = render(Markdown, {
    props: {
      source: "[report.xlsx](https://foreign.example/guessed)",
      fileNames: ["report.xlsx"],
      customRenderers: { file: MessageDocumentLink }
    }
  });
  expect(body).toContain('download="report.xlsx"');
  expect(body).toContain('href="https://eneo.example/download?token=test"');
  expect(body).not.toContain("foreign.example");
  expect(body.match(/<a\s/g)).toHaveLength(1);
});

import { page } from "@vitest/browser/context";
import { render } from "vitest-browser-svelte";
import { describe, expect, it, vi } from "vitest";
import { m } from "$lib/paraglide/messages";
import type { AcceptedFormat } from "../AttachmentManager";
import FileDropzoneTestHost from "./FileDropzoneTestHost.svelte";

const formats: AcceptedFormat[] = [
  { mimetype: "application/pdf", extensions: [".pdf"], maxSize: 10 * 1024 * 1024 },
  { mimetype: "text/plain", extensions: [".txt", ".text"], maxSize: 10 * 1024 * 1024 },
  { mimetype: "audio/mpeg", extensions: [".mp3"], maxSize: 200 * 1024 * 1024 }
];

function selectFiles(container: Element, files: File[]) {
  const input = container.querySelector("input[type=file]") as HTMLInputElement;
  const dataTransfer = new DataTransfer();
  for (const file of files) dataTransfer.items.add(file);
  input.files = dataTransfer.files;
  input.dispatchEvent(new Event("change", { bubbles: true }));
}

describe("FileDropzone", () => {
  it("lists the supported formats inline, grouped with their size limits", async () => {
    const screen = render(FileDropzoneTestHost, { formats });

    await expect.element(page.getByText(m.supported_formats())).toBeVisible();
    await expect.element(page.getByText(m.file_format_group_documents())).toBeVisible();
    await expect.element(page.getByText(m.file_format_group_audio())).toBeVisible();
    await expect.element(page.getByText(m.max_size_per_file({ size: "10 MB" }))).toBeVisible();
    await expect.element(page.getByText(m.max_size_per_file({ size: "200 MB" }))).toBeVisible();
    for (const extension of [".pdf", ".txt", ".text", ".mp3"]) {
      await expect.element(page.getByText(extension, { exact: true })).toBeVisible();
    }
    // The raw mimetypes stay out of the UI.
    expect(screen.container.textContent).not.toContain("application/pdf");
  });

  it("keeps accepted files, reports rejected ones and lets the user remove a file", async () => {
    const onselect = vi.fn();
    const onfileschanged = vi.fn();
    const screen = render(FileDropzoneTestHost, { formats, onselect, onfileschanged });

    const pdf = new File(["%PDF"], "report.pdf", { type: "application/pdf" });
    const image = new File(["png"], "photo.png", { type: "image/png" });
    selectFiles(screen.container, [pdf, image]);

    await expect.element(page.getByText("report.pdf")).toBeVisible();
    expect(screen.container.textContent).not.toContain("photo.png");
    expect(onselect).toHaveBeenCalledWith({ accepted: [pdf], rejected: [image] });
    await vi.waitFor(() => expect(onfileschanged).toHaveBeenLastCalledWith([pdf]));

    // Picking the same file again is a no-op instead of a duplicate row.
    selectFiles(screen.container, [pdf]);
    await vi.waitFor(() => expect(onfileschanged).toHaveBeenLastCalledWith([pdf]));
    expect(screen.container.querySelectorAll("li").length).toBe(1);

    await page.getByRole("button", { name: m.remove_file({ fileName: "report.pdf" }) }).click();
    await vi.waitFor(() => expect(onfileschanged).toHaveBeenLastCalledWith([]));
    await expect.element(page.getByText(m.upload_dropzone_prompt())).toBeVisible();
  });

  it("only reports files when the selection is not kept, honouring single-file mode", async () => {
    const onselect = vi.fn();
    const onfileschanged = vi.fn();
    const screen = render(FileDropzoneTestHost, {
      formats,
      multiple: false,
      keepSelection: false,
      onselect,
      onfileschanged
    });

    const first = new File(["a"], "first.txt", { type: "text/plain" });
    const second = new File(["b"], "second.txt", { type: "text/plain" });
    selectFiles(screen.container, [first, second]);

    await vi.waitFor(() =>
      expect(onselect).toHaveBeenCalledWith({ accepted: [first], rejected: [] })
    );
    expect(screen.container.querySelector("input[type=file]")).not.toHaveAttribute("multiple");
    expect(screen.container.textContent).not.toContain("first.txt");
    expect(onfileschanged).toHaveBeenLastCalledWith([]);
    await expect.element(page.getByText(m.upload_dropzone_prompt())).toBeVisible();
  });

  it("accepts dropped files", async () => {
    const onfileschanged = vi.fn();
    const screen = render(FileDropzoneTestHost, { formats, onfileschanged });

    const txt = new File(["hi"], "notes.txt", { type: "text/plain" });
    const dataTransfer = new DataTransfer();
    dataTransfer.items.add(txt);
    const dropzone = screen.container.querySelector("[role=presentation]") as HTMLElement;
    dropzone.dispatchEvent(new DragEvent("drop", { dataTransfer, bubbles: true }));

    await expect.element(page.getByText("notes.txt")).toBeVisible();
    await vi.waitFor(() => expect(onfileschanged).toHaveBeenLastCalledWith([txt]));
  });
});

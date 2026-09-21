import { page } from "@vitest/browser/context";
import { render } from "vitest-browser-svelte";
import { describe, expect, it, vi } from "vitest";
import { m } from "$lib/paraglide/messages";
import type { FormatLimit } from "../fileFormatSummary";
import FileDropzoneTestHost from "./FileDropzoneTestHost.svelte";

const formats: FormatLimit[] = [
  { mimetype: "application/pdf", extensions: [".pdf"], size: 10 * 1024 * 1024, vision: false },
  { mimetype: "text/plain", extensions: [".txt", ".text"], size: 10 * 1024 * 1024, vision: false },
  { mimetype: "audio/mpeg", extensions: [".mp3"], size: 200 * 1024 * 1024, vision: false }
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
    const onfilesrejected = vi.fn();
    const onfileschanged = vi.fn();
    const screen = render(FileDropzoneTestHost, { formats, onfilesrejected, onfileschanged });

    const pdf = new File(["%PDF"], "report.pdf", { type: "application/pdf" });
    const image = new File(["png"], "photo.png", { type: "image/png" });
    selectFiles(screen.container, [pdf, image]);

    await expect.element(page.getByText("report.pdf")).toBeVisible();
    expect(screen.container.textContent).not.toContain("photo.png");
    expect(onfilesrejected).toHaveBeenCalledWith([image]);
    await vi.waitFor(() => expect(onfileschanged).toHaveBeenLastCalledWith([pdf]));

    // Picking the same file again is a no-op instead of a duplicate row.
    selectFiles(screen.container, [pdf]);
    await vi.waitFor(() => expect(onfileschanged).toHaveBeenLastCalledWith([pdf]));
    expect(screen.container.querySelectorAll("li").length).toBe(1);

    await page.getByRole("button", { name: m.remove_file({ fileName: "report.pdf" }) }).click();
    await vi.waitFor(() => expect(onfileschanged).toHaveBeenLastCalledWith([]));
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

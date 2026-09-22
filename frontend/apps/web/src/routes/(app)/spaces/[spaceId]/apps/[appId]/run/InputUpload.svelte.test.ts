import type { App, Eneo } from "@eneo/eneo-js";
import { page } from "@vitest/browser/context";
import { render } from "vitest-browser-svelte";
import { describe, expect, it, vi } from "vitest";
import { m } from "$lib/paraglide/messages";
import InputUploadTestHost from "./InputUploadTestHost.svelte";

const input: App["input_fields"][number] = {
  type: "text-upload",
  description: null,
  accepted_file_types: [
    { mimetype: "application/pdf", size_limit: 1024, extensions: [".pdf"] },
    { mimetype: "text/plain", size_limit: 1024, extensions: [".txt"] }
  ],
  limit: { max_files: 1, max_size: 2048 }
};

function createEneoMock() {
  return {
    files: {
      upload: vi
        .fn()
        .mockResolvedValue({ id: "file-1", name: "doc.pdf", mimetype: "application/pdf" })
    }
  } as unknown as Eneo;
}

function selectFiles(container: Element, files: File[]) {
  const inputElement = container.querySelector("input[type=file]") as HTMLInputElement;
  const dataTransfer = new DataTransfer();
  for (const file of files) dataTransfer.items.add(file);
  inputElement.files = dataTransfer.files;
  inputElement.dispatchEvent(new Event("change", { bubbles: true }));
}

describe("InputUpload", () => {
  it("lists the app's accepted formats with extensions instead of mimetypes", async () => {
    const screen = render(InputUploadTestHost, { eneo: createEneoMock(), input });

    await page.getByRole("button", { name: m.file_types_and_sizes() }).click();
    await expect.element(page.getByText(".pdf", { exact: true })).toBeVisible();
    await expect.element(page.getByText(".txt", { exact: true })).toBeVisible();
    await expect.element(page.getByText(m.upload_files_description())).toBeVisible();
    expect(screen.container.textContent).not.toContain("application/pdf");
  });

  it("queues accepted files and hides the drop area once the file limit is reached", async () => {
    const eneo = createEneoMock();
    const screen = render(InputUploadTestHost, { eneo, input });

    selectFiles(screen.container, [new File(["%PDF"], "doc.pdf", { type: "application/pdf" })]);

    await vi.waitFor(() => expect(eneo.files.upload).toHaveBeenCalledTimes(1));
    await expect.element(page.getByText("doc.pdf")).toBeVisible();
    await vi.waitFor(() => expect(screen.container.querySelector("input[type=file]")).toBeNull());
  });

  it("explains rejected and oversized files inline", async () => {
    const eneo = createEneoMock();
    const screen = render(InputUploadTestHost, { eneo, input });

    selectFiles(screen.container, [
      new File(["png"], "photo.png", { type: "image/png" }),
      new File(["x".repeat(2048)], "big.txt", { type: "text/plain" })
    ]);

    await expect
      .element(
        page.getByText(
          m.attachment_error_unsupported_type({ fileName: "photo.png", fileType: "image/png" })
        )
      )
      .toBeVisible();
    await expect
      .element(
        page.getByText(
          m.file_too_large_detail({ fileName: "big.txt", currentSize: "2 KB", maxSize: "1 KB" })
        )
      )
      .toBeVisible();
    expect(eneo.files.upload).not.toHaveBeenCalled();
  });
});

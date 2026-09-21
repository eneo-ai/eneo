import type { Eneo } from "@eneo/eneo-js";
import { page } from "@vitest/browser/context";
import { render } from "vitest-browser-svelte";
import { describe, expect, it, vi } from "vitest";
import { m } from "$lib/paraglide/messages";
import type { AttachmentRules } from "../AttachmentManager";
import AttachmentDropzoneTestHost from "./AttachmentDropzoneTestHost.svelte";

const rules: AttachmentRules = {
  acceptString: "application/pdf,text/plain",
  acceptedFormats: [
    { mimetype: "application/pdf", maxSize: 1024, extensions: [".pdf"] },
    { mimetype: "text/plain", maxSize: 1024, extensions: [".txt"] }
  ]
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
  const input = container.querySelector("input[type=file]") as HTMLInputElement;
  const dataTransfer = new DataTransfer();
  for (const file of files) dataTransfer.items.add(file);
  input.files = dataTransfer.files;
  input.dispatchEvent(new Event("change", { bubbles: true }));
}

describe("AttachmentDropzone", () => {
  it("shows the manager's accepted formats and queues valid files", async () => {
    const eneo = createEneoMock();
    const screen = render(AttachmentDropzoneTestHost, { eneo, rules, multiple: true });

    await expect.element(page.getByText(m.supported_formats())).toBeVisible();
    await expect.element(page.getByText(".pdf", { exact: true })).toBeVisible();

    selectFiles(screen.container, [
      new File(["%PDF"], "a.pdf", { type: "application/pdf" }),
      new File(["b"], "b.txt", { type: "text/plain" })
    ]);
    await vi.waitFor(() => expect(eneo.files.upload).toHaveBeenCalledTimes(2));
  });

  it("only takes the first file in single-file mode", async () => {
    const eneo = createEneoMock();
    const screen = render(AttachmentDropzoneTestHost, { eneo, rules });

    selectFiles(screen.container, [
      new File(["%PDF"], "a.pdf", { type: "application/pdf" }),
      new File(["b"], "b.txt", { type: "text/plain" })
    ]);
    await vi.waitFor(() => expect(eneo.files.upload).toHaveBeenCalledTimes(1));
    expect(screen.container.querySelector("input[type=file]")).not.toHaveAttribute("multiple");
  });

  it("shows validation problems inline instead of a toast", async () => {
    const eneo = createEneoMock();
    const screen = render(AttachmentDropzoneTestHost, { eneo, rules, multiple: true });

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

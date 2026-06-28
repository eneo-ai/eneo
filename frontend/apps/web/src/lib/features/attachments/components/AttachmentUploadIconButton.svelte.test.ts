import type { Eneo } from "@eneo/eneo-js";
import { render } from "vitest-browser-svelte";
import { describe, expect, it, vi } from "vitest";
import AttachmentUploadIconButtonTestHost from "./AttachmentUploadIconButtonTestHost.svelte";

function createEneoMock() {
  return {
    files: {
      upload: vi.fn().mockResolvedValue({ id: "file-1", name: "doc.txt", mimetype: "text/plain" })
    }
  } as unknown as Eneo;
}

describe("AttachmentUploadIconButton", () => {
  it("accepts the same file twice in a row", async () => {
    const eneo = createEneoMock();
    const screen = render(AttachmentUploadIconButtonTestHost, { eneo });
    const input = screen.container.querySelector("input[type=file]") as HTMLInputElement;

    const file = new File(["hello"], "doc.txt", { type: "text/plain" });
    const selectFile = () => {
      const dataTransfer = new DataTransfer();
      dataTransfer.items.add(file);
      input.files = dataTransfer.files;
      input.dispatchEvent(new Event("change"));
    };

    selectFile();
    await vi.waitFor(() => expect(eneo.files.upload).toHaveBeenCalledTimes(1));
    // The input must be reset after queueing: a file input keeps its value,
    // and the browser never fires `change` when the user picks the same file
    // again, so the upload would silently do nothing.
    expect(input.value).toBe("");

    selectFile();
    await vi.waitFor(() => expect(eneo.files.upload).toHaveBeenCalledTimes(2));
  });
});
